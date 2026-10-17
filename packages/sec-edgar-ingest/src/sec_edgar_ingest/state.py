"""Durable source observations, accepted receipts, first pins and attempt audit."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .etl.contracts import EtlResult

import hashlib
import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone

from .config import HTTP_ATTEMPT_LIMIT
from .models import Binding, BodyReceipt, CommandResult, DirectoryOutcome, Error, Permit, RunContext, Snapshot, Source, Versioned, canonical_json, require_hash, require_number, require_text, require_utc, safe_relative_path
from .storage.contracts import AlreadyExists, CAS_ATTEMPTS, Conflict, StateStore


HTTP_SUCCESS = 200


def attempt_key(context: RunContext) -> str:
    return hashlib.sha256(canonical_json({name: getattr(context, name) for name in
        ("run_id", "execution_id", "command", "attempt_id", "image_digest")})).hexdigest()


class AcquisitionState:
    def __init__(self, store: StateStore, *, clock=None):
        self.store = store
        self.clock = clock
        self.active_context = None

    def _now(self) -> datetime:
        instant = self.clock.now() if self.clock is not None else datetime.now(timezone.utc)
        require_utc(instant, "clock.now")
        return instant

    def _update_source(self, source: Source, change) -> Versioned:
        for _ in range(CAS_ATTEMPTS):
            current = self.get_source(source.source_id)
            value = current.to_mapping()["value"] if current is not None else {
                "source": source.to_mapping(), "first_discovered_at": None, "last_discovered_at": None,
                "discovery_status": "unobserved", "acquisition_status": "pending", "needs_acquisition": True,
                "latest_downloaded_snapshot": None, "latest_received_at": None, "last_error": None,
            }
            if Source.from_mapping(value["source"]) != source:
                raise Conflict("source identity has conflicting metadata")
            change(value)
            try:
                if current is None:
                    return self.store.insert("Source", source.source_id, value)
                return self.store.replace("Source", source.source_id, value, current.version)
            except (AlreadyExists, Conflict):
                continue
        raise Conflict("source update exhausted conditional races")

    def observe(self, source: Source, at: datetime, discovery_status: str) -> None:
        require_utc(at, "discovery time")
        require_text(discovery_status, "discovery_status")
        def change(value):
            first = value["first_discovered_at"]
            last = value["last_discovered_at"]
            value["first_discovered_at"] = min(at, datetime.fromisoformat(first)).isoformat() if first else at.isoformat()
            if last is None or at >= datetime.fromisoformat(last):
                value["last_discovered_at"] = at.isoformat()
                value["discovery_status"] = discovery_status
        self._update_source(source, change)

    def get_source(self, source_id: str) -> Versioned | None:
        return self.store.get("Source", source_id)

    def pending_sources(self) -> tuple[Source, ...]:
        return tuple(Source.from_mapping(row.to_mapping()["value"]["source"])
                     for row in self.store.scan("Source", {"needs_acquisition": True}))

    def discovery_session(self, discovery_id: str) -> Versioned | None:
        require_text(discovery_id, "discovery_id")
        return self.store.get("DiscoverySession", hashlib.sha256(discovery_id.encode()).hexdigest())

    def begin_discovery(self, discovery_id: str, frozen: dict[str, object], context: RunContext,
                        mode: str, acquisition_mode: str) -> Versioned:
        key = hashlib.sha256(discovery_id.encode()).hexdigest()
        value = {"discovery_id": discovery_id, "frozen": frozen, "workset_id": None,
                 "predecessor_workset_id": None, "history": [], "registered": False}
        try:
            session = self.store.insert("DiscoverySession", key, value)
        except AlreadyExists:
            session = self.discovery_session(discovery_id)
        saved = session.to_mapping()["value"]["frozen"]
        original = RunContext.from_mapping(saved["context"])
        if (_run_provenance(original) != _run_provenance(context) or original.command != context.command
                or saved["mode"] != mode or saved["acquisition_mode"] != acquisition_mode):
            raise Conflict("discovery session has conflicting frozen provenance or acquisition mode")
        required = {unit["url"]: unit for unit in saved["units"]}
        if len(required) != len(saved["units"]) or not required:
            raise Conflict("discovery session requires unique directory units")
        if session.value["registered"]:
            return session
        def register(value):
            for url, unit in required.items():
                progress = self.directory_progress(discovery_id, url)
                successful = progress is not None and progress.value["outcome"]["outcome"] != "discovery_failed"
                if url not in value["gaps"] and not successful:
                    pending = DirectoryOutcome(url, unit["period"], "discovery_failed", None, (),
                        Error("discovery_pending", "required directory has not completed", True, None, {}))
                    value["gaps"][url] = {"token": hashlib.sha256(canonical_json([discovery_id, url])).hexdigest(),
                                          "discovery_id": discovery_id, "outcome": pending.to_mapping()}
        self._change_boundary(register)
        for _ in range(CAS_ATTEMPTS):
            current = self.discovery_session(discovery_id)
            value = current.to_mapping()["value"]
            if value["registered"]:
                return current
            value["registered"] = True
            try:
                return self.store.replace("DiscoverySession", key, value, current.version)
            except Conflict:
                continue
        raise Conflict("discovery registration exhausted conditional races")

    def _change_boundary(self, change: Callable[[dict[str, object]], None]) -> Versioned:
        for _ in range(CAS_ATTEMPTS):
            row = self.store.get("DiscoveryBoundary", "daily")
            value = row.to_mapping()["value"] if row else {"day": None, "gaps": {}}
            change(value)
            try:
                if row is None:
                    return self.store.insert("DiscoveryBoundary", "daily", value)
                return self.store.replace("DiscoveryBoundary", "daily", value, row.version)
            except (AlreadyExists, Conflict):
                continue
        raise Conflict("discovery boundary exhausted conditional races")

    def directory_gap(self, url: str) -> str | None:
        row = self.store.get("DiscoveryBoundary", "daily")
        gap = None if row is None else row.to_mapping()["value"]["gaps"].get(url)
        return gap["token"] if gap else None

    def directory_progress(self, discovery_id: str, url: str) -> Versioned | None:
        return self.store.get("DirectoryProgress", hashlib.sha256(canonical_json([discovery_id, url])).hexdigest())

    def record_directory(self, discovery_id: str, outcome: DirectoryOutcome, members: tuple[Source, ...], *,
                         evidence: dict[str, object] | None = None, selection: dict[str, object] | None = None,
                         expected_gap: str | None = None) -> None:
        if tuple(sorted(member.source_id for member in members)) != outcome.source_ids:
            raise Conflict("directory outcome must name its exact members")
        if any(member.canonical_url.rsplit("/", 1)[0] + "/index.json" != outcome.url for member in members):
            raise Conflict("source member must originate from its immediate directory")
        failed = outcome.outcome == "discovery_failed"
        if not failed and (evidence is None or evidence.get("sha256") != outcome.listing_sha256):
            raise Conflict("successful directory progress requires durable original evidence")
        if failed:
            audit = {"discovery_id": discovery_id, "outcome": outcome.to_mapping(), "recorded_at": self._now().isoformat(), "event_id": uuid.uuid4().hex,
                     "attempt_key": attempt_key(self.active_context) if self.active_context is not None else None,
                     "context": self.active_context.to_mapping() if self.active_context is not None else None}
            token = hashlib.sha256(canonical_json(audit)).hexdigest()
            def add_gap(value):
                value["gaps"][outcome.url] = {"token": token, "discovery_id": discovery_id, "outcome": outcome.to_mapping()}
            # The shared CAS gap is durable before a failure row can appear complete elsewhere.
            self._change_boundary(add_gap)
            self._insert_immutable("Failure", token, audit)
        key = hashlib.sha256(canonical_json([discovery_id, outcome.url])).hexdigest()
        value = {"discovery_id": discovery_id, "outcome": outcome.to_mapping(),
                 "members": [member.to_mapping() for member in members], "evidence": evidence,
                 "selection": selection or {"ignored": []}, "observed_gap_token": expected_gap}
        for _ in range(CAS_ATTEMPTS):
            current = self.directory_progress(discovery_id, outcome.url)
            if current is not None and current.value["outcome"]["outcome"] != "discovery_failed":
                if current.to_mapping()["value"] != value:
                    raise Conflict("successful directory progress is immutable within a session")
                break
            try:
                if current is None:
                    self.store.insert("DirectoryProgress", key, value)
                else:
                    self.store.replace("DirectoryProgress", key, value, current.version)
                break
            except (AlreadyExists, Conflict):
                continue
        else:
            raise Conflict("directory progress exhausted conditional races")
        if not failed:
            def resolve(value):
                gap = value["gaps"].get(outcome.url)
                if gap and expected_gap is not None and gap["token"] == expected_gap:
                    del value["gaps"][outcome.url]
            self._change_boundary(resolve)

    def failed_directories(self) -> tuple[DirectoryOutcome, ...]:
        row = self.store.get("DiscoveryBoundary", "daily")
        gaps = {} if row is None else row.to_mapping()["value"]["gaps"]
        return tuple(DirectoryOutcome.from_mapping(gaps[url]["outcome"]) for url in sorted(gaps))

    def daily_boundary(self) -> date | None:
        row = self.store.get("DiscoveryBoundary", "daily")
        day = None if row is None else row.value["day"]
        return date.fromisoformat(day) if day else None

    def advance_boundary(self, candidate: date, discovery_id: str,
                         outcomes: tuple[DirectoryOutcome, ...]) -> None:
        if type(candidate) is not date:
            raise ValueError("boundary candidate must be a date")
        session = self.discovery_session(discovery_id)
        if session is None:
            raise Conflict("boundary requires a registered discovery session")
        if not session.value["registered"]:
            raise Conflict("required discovery gaps were never registered")
        frozen = session.to_mapping()["value"]["frozen"]
        if frozen["mode"] != "daily" or candidate != date.fromisoformat(frozen["today"]):
            raise Conflict("boundary candidate differs from its pinned daily discovery")
        supplied = {outcome.url: outcome for outcome in outcomes}
        required = {unit["url"] for unit in frozen["units"]}
        if len(supplied) != len(outcomes) or set(supplied) != required:
            raise Conflict("boundary requires the complete exact required-unit outcome set")
        for url, outcome in supplied.items():
            progress = self.directory_progress(discovery_id, url)
            if progress is None or progress.to_mapping()["value"]["outcome"] != outcome.to_mapping():
                raise Conflict("boundary outcome lacks its exact durable directory progress")
        def advance(value):
            if value["gaps"] or any(outcome.outcome == "discovery_failed" for outcome in outcomes):
                return
            previous = date.fromisoformat(value["day"]) if value["day"] else None
            value["day"] = (max(previous, candidate) if previous else candidate).isoformat()
        self._change_boundary(advance)

    def finish_discovery(self, discovery_id: str, workset_id: str, context: RunContext) -> None:
        key = hashlib.sha256(discovery_id.encode()).hexdigest()
        for _ in range(CAS_ATTEMPTS):
            row = self.discovery_session(discovery_id)
            if row is None:
                raise Conflict("discovery session was never begun")
            value = row.to_mapping()["value"]
            if value["workset_id"] == workset_id:
                return
            predecessor = value["workset_id"]
            value.update(workset_id=workset_id, predecessor_workset_id=predecessor)
            value["history"].append({"workset_id": workset_id, "predecessor_workset_id": predecessor,
                                     "resumed_by": context.to_mapping()})
            try:
                self.store.replace("DiscoverySession", key, value, row.version)
                return
            except Conflict:
                continue
        raise Conflict("discovery checkpoint exhausted conditional races")

    def remember_snapshot(self, snapshot: Snapshot) -> Snapshot:
        row = self.get_source(snapshot.source_id)
        source = None if row is None else Source.from_mapping(row.to_mapping()["value"]["source"])
        if source is not None:
            expected = f"raw/sec/indexes/kind={source.kind}/period={source.period}/sha256={snapshot.sha256}/master.{source.representation}"
            if snapshot.raw_path != expected:
                raise Conflict("snapshot address disagrees with observed source")
        key = snapshot.source_id + ":" + snapshot.sha256
        try:
            self.store.insert("Snapshot", key, snapshot.to_mapping())
            accepted = snapshot
        except AlreadyExists:
            accepted = self.snapshot(snapshot.source_id, snapshot.sha256)
            if (accepted.raw_path, accepted.byte_count, accepted.representation, accepted.envelope_version) != (
                    snapshot.raw_path, snapshot.byte_count, snapshot.representation, snapshot.envelope_version):
                raise Conflict("same snapshot hash has conflicting immutable metadata")
        if source is not None:
            def change(value):
                latest = value["latest_received_at"]
                is_newer = latest is None or snapshot.received_at > datetime.fromisoformat(latest)
                is_current = latest is not None and snapshot.received_at == datetime.fromisoformat(latest) and value["latest_downloaded_snapshot"] == accepted.sha256
                if is_newer or is_current:
                    value["latest_downloaded_snapshot"] = accepted.sha256
                    value["latest_received_at"] = snapshot.received_at.isoformat()
                    value["acquisition_status"] = "downloaded"
                    value["needs_acquisition"] = False
            self._update_source(source, change)
        return accepted

    def reusable_snapshot(self, source: Source, envelope_version: str) -> Snapshot | None:
        row = self.get_source(source.source_id)
        if row is None:
            return None
        value = row.to_mapping()["value"]
        if Source.from_mapping(value["source"]) != source:
            raise Conflict("reusable source has conflicting immutable identity")
        digest = value["latest_downloaded_snapshot"]
        if digest is None:
            return None
        snapshot = self.snapshot(source.source_id, digest)
        if snapshot.envelope_version != envelope_version:
            return None
        expected = f"raw/sec/indexes/kind={source.kind}/period={source.period}/sha256={snapshot.sha256}/master.{source.representation}"
        if snapshot.raw_path != expected or snapshot.representation != source.representation:
            raise Conflict("reusable snapshot differs from its exact source address")
        return snapshot

    def staged_receipt(self, workset_id: str, source_id: str) -> dict[str, object] | None:
        require_hash(workset_id, "workset_id")
        require_hash(source_id, "source_id")
        entries = [row.to_mapping()["value"] for row in self.store.scan("StagedReceipt", {
            "workset_id": workset_id, "source_id": source_id})]
        entries.sort(key=lambda value: (value["receipt"]["received_at"], value["checkpoint_id"]))
        return {"workset_id": workset_id, "source_id": source_id, "receipts": entries} if entries else None

    def record_receipt(self, workset_id: str, source: Source, receipt: BodyReceipt, temporary_ref: str) -> None:
        require_hash(workset_id, "workset_id")
        safe_relative_path(temporary_ref, "temporary_ref")
        context = self.active_context
        if context is None:
            raise Conflict("staged receipt requires a begun audited request context")
        rows = self.request_history(context, source.canonical_url)
        if not rows:
            raise Conflict("staged receipt requires an actual recorded request reservation")
        request = rows[-1].to_mapping()["value"]
        expected = f"staging/sec/{context.run_id}/{context.attempt_id}/{source.source_id}/{request['request_id']}/body"
        if (request["receipt"] != receipt.to_mapping() or request["source_id"] != source.source_id
                or request["ended_at"] is None or request["outcome"] != "received"
                or temporary_ref != expected or receipt.url != source.canonical_url
                or receipt.status != HTTP_SUCCESS or not receipt.complete or receipt.error is not None):
            raise Conflict("staged receipt differs from the exact finalized accepted request")
        value = {"workset_id": workset_id, "source_id": source.source_id, "source": source.to_mapping(),
                 "context": context.to_mapping(), "receipt": receipt.to_mapping(), "temporary_ref": temporary_ref,
                 "request_id": request["request_id"], "transport_attempt": request}
        checkpoint = hashlib.sha256(canonical_json(value)).hexdigest()
        self._insert_immutable("StagedReceipt", checkpoint, {**value, "checkpoint_id": checkpoint})

    def promotion_receipt(self, workset_id: str, source_id: str) -> dict[str, object] | None:
        require_hash(workset_id, "workset_id")
        require_hash(source_id, "source_id")
        entries = [row.to_mapping()["value"] for row in self.store.scan("PromotionReceipt", {
            "workset_id": workset_id, "source_id": source_id})]
        entries.sort(key=lambda value: (value["snapshot"]["received_at"], value["checkpoint_id"]))
        return {"workset_id": workset_id, "source_id": source_id,
                "snapshots": [value["snapshot"] for value in entries]} if entries else None

    def record_promotion(self, workset_id: str, snapshot: Snapshot) -> None:
        require_hash(workset_id, "workset_id")
        staged = self.staged_receipt(workset_id, snapshot.source_id)
        if staged is None or not any(entry["receipt"]["sha256"] == snapshot.sha256
                and entry["receipt"]["byte_count"] == snapshot.byte_count for entry in staged["receipts"]):
            raise Conflict("promotion checkpoint requires the exact durable received entity")
        value = {"workset_id": workset_id, "source_id": snapshot.source_id, "snapshot": snapshot.to_mapping()}
        checkpoint = hashlib.sha256(canonical_json(value)).hexdigest()
        self._insert_immutable("PromotionReceipt", checkpoint, {**value, "checkpoint_id": checkpoint})

    def snapshot(self, source_id: str, sha256: str) -> Snapshot:
        row = self.store.get("Snapshot", source_id + ":" + sha256)
        if row is None:
            raise Conflict("snapshot is not durably remembered")
        return Snapshot.from_mapping(row.to_mapping()["value"])

    def binding(self, workset_id: str, source_id: str) -> Binding | None:
        row = self.store.get("Binding", workset_id + ":" + source_id)
        return None if row is None else Binding.from_mapping(row.to_mapping()["value"])

    def bind_once(self, binding: Binding) -> Binding:
        existing = self.binding(binding.source_workset_id, binding.source_id)
        if existing is not None:
            return existing
        self.snapshot(binding.source_id, binding.snapshot_sha256)
        try:
            self.store.insert("Binding", binding.source_workset_id + ":" + binding.source_id, binding.to_mapping())
            return binding
        except AlreadyExists:
            winner = self.binding(binding.source_workset_id, binding.source_id)
            if winner is None:
                raise Conflict("binding vanished after create conflict")
            return winner

    def _insert_immutable(self, kind: str, key: str, value: dict[str, object]) -> None:
        try:
            self.store.insert(kind, key, value)
        except AlreadyExists:
            existing = self.store.get(kind, key)
            if existing is None or existing.to_mapping()["value"] != value:
                raise Conflict("immutable audit row differs after create conflict")

    def begin_attempt(self, context: RunContext) -> None:
        key = attempt_key(context)
        existing = self.store.get("Attempt", key)
        if existing is None:
            value = {"context": context.to_mapping(), "started_at": context.started_at.isoformat(),
                     "ended_at": None, "outcome": "in_progress", "result": None, "structured_errors": []}
            try:
                self.store.insert("Attempt", key, value)
            except AlreadyExists:
                existing = self.store.get("Attempt", key)
                if existing is None:
                    raise Conflict("attempt vanished after create conflict")
        if existing is not None and existing.to_mapping()["value"]["context"] != context.to_mapping():
            raise Conflict("attempt identity has conflicting provenance")
        self.active_context = context

    def finish_attempt(self, result: CommandResult | EtlResult) -> None:
        key = attempt_key(result.context)
        for _ in range(CAS_ATTEMPTS):
            existing = self.store.get("Attempt", key)
            if existing is None:
                raise Conflict("attempt was never begun")
            value = existing.to_mapping()["value"]
            if value["context"] != result.context.to_mapping():
                raise Conflict("result context differs from begun attempt")
            if value["result"] is not None:
                if value["result"] != result.to_mapping():
                    raise Conflict("finished attempt cannot be replaced")
                return
            value.update(ended_at=result.ended_at.isoformat(), outcome=result.outcome,
                         result=result.to_mapping(), structured_errors=[gap.to_mapping() for gap in result.gaps])
            try:
                self.store.replace("Attempt", key, value, existing.version)
                return
            except Conflict:
                continue
        raise Conflict("attempt finish exhausted conditional races")

    def record_failure(self, source: Source, error: Error) -> None:
        if error.source_id is not None and error.source_id != source.source_id:
            raise ValueError("failure belongs to a different source")
        at = self._now()
        value = {"source_id": source.source_id, "error": error.to_mapping(), "recorded_at": at.isoformat(),
                 "attempt_key": attempt_key(self.active_context) if self.active_context is not None else None}
        key = hashlib.sha256(canonical_json(value)).hexdigest()
        self._insert_immutable("Failure", key, value)
        def change(value):
            value["last_error"] = error.to_mapping()
            value["needs_acquisition"] = True
            if value["latest_downloaded_snapshot"] is None:
                value["acquisition_status"] = "failed"
        self._update_source(source, change)

    def request_history(self, context: RunContext, url: str) -> tuple[Versioned, ...]:
        rows = tuple(self.store.scan("TransportAttempt", {"attempt_key": attempt_key(context), "url": url}))
        for row in rows:
            if row.to_mapping()["value"]["context"] != context.to_mapping():
                raise Conflict("request history has conflicting command provenance")
        return tuple(sorted(rows, key=lambda row: row.value["ordinal"]))

    def begin_request(self, context: RunContext, url: str, source_id: str | None, request_id: str, ordinal: int) -> None:
        require_text(url, "request URL")
        require_text(request_id, "request_id")
        require_number(ordinal, "request ordinal", positive=True, integer=True)
        if ordinal > HTTP_ATTEMPT_LIMIT:
            raise ValueError("request ordinal exceeds five total attempts")
        self.begin_attempt(context)
        rows = self.request_history(context, url)
        if [row.value["ordinal"] for row in rows] != list(range(1, ordinal)):
            raise Conflict("request ordinal must follow every accounted durable attempt")
        prior = {}
        for row in self.store.scan("TransportAttempt", {"url": url}):
            old = row.value["context"]
            budget = old.get("effective_config", {}).get("http", {}).get("max_attempts", HTTP_ATTEMPT_LIMIT)
            exhausted = row.value["outcome"] == "exhausted" or row.value["ordinal"] >= budget
            if exhausted and old["run_id"] == context.run_id and row.value["attempt_key"] != attempt_key(context):
                prior[row.value["attempt_key"]] = {name: old[name] for name in ("run_id", "execution_id", "command", "attempt_id")}
        value = {"attempt_key": attempt_key(context), "context": context.to_mapping(), "request_id": request_id,
                 "ordinal": ordinal, "url": url, "source_id": source_id, "begun_at": self._now().isoformat(),
                 "ended_at": None, "outcome": "uncertain", "receipt": None, "permit": None,
                 "status": None, "byte_count": None, "ownership_epoch": None, "next_allowed_at": None,
                 "permit_next_allowed_at": None, "error": None, "retry": {},
                 "prior_exhaustion": [prior[key] for key in sorted(prior)]}
        key = _request_key(context, url, ordinal)
        try:
            self.store.insert("TransportAttempt", key, value)
        except AlreadyExists as error:
            raise Conflict("request ordinal was already consumed before dispatch") from error

    def request_attempt(self, context: RunContext, receipt: BodyReceipt, permit: Permit, ordinal: int, *,
                        outcome: str = "received", error: Error | None = None,
                        retry: dict[str, object] | None = None, next_allowed_at: datetime | None = None) -> None:
        require_number(ordinal, "request ordinal", positive=True, integer=True)
        if ordinal > HTTP_ATTEMPT_LIMIT:
            raise ValueError("request ordinal exceeds five total attempts")
        require_text(outcome, "request outcome")
        permit_next = permit.next_allowed_at
        next_allowed = next_allowed_at if next_allowed_at is not None else permit_next
        if retry and retry.get("policy_blocked"):
            next_allowed = None
        if next_allowed is not None:
            require_utc(next_allowed, "next_allowed_at")
        key = _request_key(context, receipt.url, ordinal)
        for _ in range(CAS_ATTEMPTS):
            row = self.store.get("TransportAttempt", key)
            if row is not None:
                value = row.to_mapping()["value"]
                if value["context"] != context.to_mapping() or value["request_id"] != permit.request_id:
                    raise Conflict("receipt differs from the request's durable reservation")
            else:
                # Preserve Task 3's direct, immutable receipt audit API for existing callers.
                value = {"attempt_key": attempt_key(context), "context": context.to_mapping(),
                         "request_id": permit.request_id, "ordinal": ordinal, "url": receipt.url,
                         "source_id": None, "begun_at": receipt.received_at.isoformat(), "ended_at": None,
                         "receipt": None, "prior_exhaustion": []}
            final = {**value, "status": receipt.status, "byte_count": receipt.byte_count,
                     "ownership_epoch": permit.epoch, "next_allowed_at": next_allowed.isoformat() if next_allowed is not None else None,
                     "permit_next_allowed_at": permit_next.isoformat() if permit_next is not None else None,
                     "receipt": receipt.to_mapping(), "permit": permit.to_mapping(), "outcome": outcome,
                     "error": (error or receipt.error).to_mapping() if error or receipt.error else None,
                     "retry": dict(retry or {}), "ended_at": value.get("ended_at") or self._now().isoformat()}
            if value["receipt"] is not None:
                if value != final:
                    raise Conflict("finished request receipt and outcome cannot be replaced")
                return
            try:
                if row is None:
                    self.store.insert("TransportAttempt", key, final)
                else:
                    self.store.replace("TransportAttempt", key, final, row.version)
                return
            except (AlreadyExists, Conflict):
                continue
        raise Conflict("request finish exhausted conditional races")

    def halt_run(self, context: RunContext, error: Error) -> None:
        provenance = _run_provenance(context)
        value = {"provenance": provenance, "context": context.to_mapping(), "error": error.to_mapping(),
                 "halted_at": self._now().isoformat()}
        key = hashlib.sha256(canonical_json(context.run_id)).hexdigest()
        try:
            self.store.insert("RunHalt", key, value)
        except AlreadyExists:
            self.run_halt(context)

    def run_halt(self, context: RunContext) -> Error | None:
        key = hashlib.sha256(canonical_json(context.run_id)).hexdigest()
        row = self.store.get("RunHalt", key)
        if row is None:
            return None
        value = row.to_mapping()["value"]
        if value["provenance"] != _run_provenance(context):
            raise Conflict("run halt has conflicting immutable run provenance")
        return Error.from_mapping(value["error"])


def _request_key(context: RunContext, url: str, ordinal: int) -> str:
    return hashlib.sha256(canonical_json([attempt_key(context), url, ordinal])).hexdigest()


def _run_provenance(context: RunContext) -> dict[str, str]:
    return {name: getattr(context, name) for name in ("run_id", "image_digest", "parser_version", "schema_version", "config_sha256")}
