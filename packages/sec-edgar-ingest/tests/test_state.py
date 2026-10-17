import importlib
import importlib.util
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sec_edgar_ingest.models import Binding, BodyReceipt, CommandResult, Error, Permit
from support import Faults, FixtureClock, fixture_context, fixture_snapshot, fixture_source, store_bundle


class TracedBindingStore:
    """Barrier the real read consumed by bind_once; trace delegated creates."""

    def __init__(self, store, barrier, counter):
        self.store = store
        self.barrier = barrier
        self.counter = counter
        self.events = []
        self.absent_read_synchronized = False

    def record(self, event, **details):
        with self.counter.get_lock():
            self.counter.value += 1
            entry = {"order": self.counter.value, "at": datetime.now(timezone.utc).isoformat(),
                     "monotonic_ns": time.monotonic_ns(), "pid": os.getpid(), "event": event, **details}
        self.events.append(entry)

    def get(self, kind, key):
        row = self.store.get(kind, key)
        if kind == "Binding":
            if row is None and not self.absent_read_synchronized:
                self.absent_read_synchronized = True
                self.record("binding_read_absent", key=key)
                self.barrier.wait(timeout=20)
            elif row is not None:
                self.record("binding_read_existing", key=key, version=row.version,
                            snapshot_sha256=row.value["snapshot_sha256"])
        return row

    def insert(self, kind, key, value):
        from sec_edgar_ingest.storage.contracts import AlreadyExists
        if kind != "Binding":
            return self.store.insert(kind, key, value)
        self.record("binding_insert_attempt", key=key, snapshot_sha256=value["snapshot_sha256"])
        try:
            row = self.store.insert(kind, key, value)
        except AlreadyExists:
            self.record("binding_create_conflict", key=key)
            raise
        self.record("binding_insert_success", key=key, version=row.version,
                    snapshot_sha256=row.value["snapshot_sha256"])
        return row

    def replace(self, kind, key, value, version):
        return self.store.replace(kind, key, value, version)

    def scan(self, kind, filters):
        return self.store.scan(kind, filters)


def pin_in_process(root, barrier, counter, output, body):
    from sec_edgar_ingest.state import AcquisitionState
    store = store_bundle(Path(root))[0]
    try:
        source = fixture_source()
        snapshot = fixture_snapshot(source, body)
        AcquisitionState(store).remember_snapshot(snapshot)
        candidate = Binding("a" * 64, source.source_id, snapshot.sha256)
        traced = TracedBindingStore(store, barrier, counter)
        winner = AcquisitionState(traced).bind_once(candidate)
        traced.record("binding_adopted", snapshot_sha256=winner.snapshot_sha256)
        output.put({"binding": winner.to_mapping(), "events": traced.events})
    finally:
        store.close()


class StateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("sec_edgar_ingest.state"),
                             "First pins and attempt failures require durable state transitions")
        self.state_module = importlib.import_module("sec_edgar_ingest.state")
        self.contracts = importlib.import_module("sec_edgar_ingest.storage.contracts")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store, self.objects, self.leases = store_bundle(self.root)
        self.addCleanup(self.store.close)
        self.clock = FixtureClock()
        self.state = self.state_module.AcquisitionState(self.store, clock=self.clock)
        self.source = fixture_source()

    def test_first_pin_survives_reopen_and_newer_snapshot(self):
        old = fixture_snapshot(self.source, b"original")
        new = replace(fixture_snapshot(self.source, b"changed"), received_at=old.received_at + timedelta(seconds=5))
        self.state.remember_snapshot(old)
        winner = self.state.bind_once(Binding("a" * 64, self.source.source_id, old.sha256))
        self.state.remember_snapshot(new)
        self.store.close()
        reopened_store = store_bundle(self.root)[0]
        self.addCleanup(reopened_store.close)
        reopened = self.state_module.AcquisitionState(reopened_store)
        loser = reopened.bind_once(Binding("a" * 64, self.source.source_id, new.sha256))
        self.assertEqual(loser, winner)
        self.assertEqual(reopened.snapshot(self.source.source_id, winner.snapshot_sha256), old)

    def test_independent_processes_observe_absence_then_race_first_pin(self):
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        counter = context.Value("Q", 0)
        output = context.Queue()
        processes = [context.Process(target=pin_in_process, args=(str(self.root), barrier, counter, output, body))
                     for body in (b"first", b"second")]
        for process in processes:
            process.start()
        try:
            results = [output.get(timeout=30) for _ in processes]
        finally:
            for process in processes:
                process.join(timeout=30)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        self.assertEqual([process.exitcode for process in processes], [0, 0])
        self.assertTrue(all("binding" in result and "events" in result for result in results),
                        "The process race must retain internal Binding reads, two actual insert attempts and one actual AlreadyExists adoption")
        bindings = [result["binding"] for result in results]
        self.assertEqual(bindings[0], bindings[1])
        events = sorted((event for result in results for event in result["events"]), key=lambda event: event["order"])
        trace_path = os.environ.get("SEC_EDGAR_FIX1_TRACE")
        if trace_path is not None:
            Path(trace_path).write_text(json.dumps({"results": results, "ordered_events": events}, indent=2, sort_keys=True) + "\n")
        self.assertEqual([event["order"] for event in events], list(range(1, len(events) + 1)))
        for event in events:
            self.assertEqual(datetime.fromisoformat(event["at"]).utcoffset(), timedelta(0))
            self.assertGreater(event["monotonic_ns"], 0)
        absent = [event for event in events if event["event"] == "binding_read_absent"]
        attempts = [event for event in events if event["event"] == "binding_insert_attempt"]
        successes = [event for event in events if event["event"] == "binding_insert_success"]
        conflicts = [event for event in events if event["event"] == "binding_create_conflict"]
        reads = [event for event in events if event["event"] == "binding_read_existing"]
        adopted = [event for event in events if event["event"] == "binding_adopted"]
        self.assertEqual(len(absent), 2)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(len(reads), 1)
        self.assertEqual(len(adopted), 2)
        self.assertEqual({event["pid"] for event in absent}, {process.pid for process in processes})
        self.assertEqual({event["pid"] for event in attempts}, {process.pid for process in processes})
        self.assertLess(max(event["order"] for event in absent), min(event["order"] for event in attempts))
        self.assertNotEqual(successes[0]["pid"], conflicts[0]["pid"])
        self.assertEqual(reads[0]["pid"], conflicts[0]["pid"])
        self.assertLess(conflicts[0]["order"], reads[0]["order"])
        loser_adopted = next(event for event in adopted if event["pid"] == conflicts[0]["pid"])
        self.assertLess(reads[0]["order"], loser_adopted["order"])
        winner = self.state.binding("a" * 64, self.source.source_id)
        self.assertEqual(winner.to_mapping(), bindings[0])
        durable = self.store.get("Binding", winner.source_workset_id + ":" + winner.source_id)
        self.assertEqual(successes[0]["version"], durable.version)
        self.assertEqual(reads[0]["version"], durable.version)
        self.assertTrue(all(event["snapshot_sha256"] == winner.snapshot_sha256 for event in adopted))
        self.state.snapshot(self.source.source_id, winner.snapshot_sha256)

    def test_discovery_and_later_failure_preserve_success_and_existing_pin(self):
        at = self.clock.now()
        self.state.observe(self.source, at, "available")
        snapshot = fixture_snapshot(self.source, b"accepted")
        self.state.remember_snapshot(snapshot)
        binding = self.state.bind_once(Binding("a" * 64, self.source.source_id, snapshot.sha256))
        self.clock.advance(5)
        self.state.observe(self.source, self.clock.now(), "discovery_failed")
        error = Error("http", "later refresh failed", True, self.source.source_id, {"status": 503})
        self.state.record_failure(self.source, error)
        value = self.state.get_source(self.source.source_id).value
        self.assertEqual(value["first_discovered_at"], at.isoformat())
        self.assertEqual(value["last_discovered_at"], self.clock.now().isoformat())
        self.assertEqual(value["acquisition_status"], "downloaded")
        self.assertEqual(value["latest_downloaded_snapshot"], snapshot.sha256)
        self.assertEqual(value["last_error"]["code"], "http")
        self.assertEqual(self.state.binding("a" * 64, self.source.source_id), binding)
        self.assertEqual(self.state.pending_sources(), (self.source,))
        self.assertEqual(self.state.snapshot(self.source.source_id, snapshot.sha256), snapshot)
        self.assertEqual(len(tuple(self.store.scan("Failure", {}))), 1)

    def test_older_receipt_and_out_of_order_discovery_never_move_pointers_back(self):
        at = self.clock.now()
        self.state.observe(self.source, at + timedelta(seconds=10), "available")
        self.state.observe(self.source, at, "available")
        old = fixture_snapshot(self.source, b"old")
        new = replace(fixture_snapshot(self.source, b"new"), received_at=at + timedelta(seconds=10))
        self.state.remember_snapshot(new)
        self.state.remember_snapshot(old)
        value = self.state.get_source(self.source.source_id).value
        self.assertEqual(value["latest_downloaded_snapshot"], new.sha256)
        self.assertEqual(value["first_discovered_at"], at.isoformat())
        self.assertEqual(value["last_discovered_at"], new.received_at.isoformat())
        self.assertEqual(self.state.remember_snapshot(replace(old, received_at=at + timedelta(seconds=20))), old)
        receipt = self.state.get_source(self.source.source_id).value
        self.assertEqual(receipt["latest_downloaded_snapshot"], old.sha256)
        self.assertEqual(receipt["latest_received_at"], (at + timedelta(seconds=20)).isoformat())

    def test_pending_sources_include_old_failed_and_all_pages(self):
        sources = [fixture_source(f"2015Q{ordinal}") for ordinal in range(1, 5)]
        daily = fixture_source("2026-10-01", "daily")
        sources.append(daily)
        for source in sources:
            self.state.observe(source, self.clock.now(), "available")
        self.state.record_failure(sources[0], Error("failed", "old failure", True, sources[0].source_id, {}))
        self.state.remember_snapshot(fixture_snapshot(daily, b"downloaded"))
        paged_store = importlib.import_module("sec_edgar_ingest.storage.local").LocalStateStore(self.root, page_size=2)
        self.addCleanup(paged_store.close)
        pending = self.state_module.AcquisitionState(paged_store).pending_sources()
        self.assertEqual(set(pending), set(sources[:-1]))

    def test_attempts_reopen_unfinished_and_finish_idempotently_without_erasure(self):
        context = fixture_context()
        self.state.begin_attempt(context)
        unfinished = tuple(self.store.scan("Attempt", {}))
        self.assertEqual(len(unfinished), 1)
        self.assertEqual(unfinished[0].value["outcome"], "in_progress")
        reopened_store = store_bundle(self.root)[0]
        self.addCleanup(reopened_store.close)
        reopened = self.state_module.AcquisitionState(reopened_store)
        reopened.begin_attempt(context)
        self.assertEqual(tuple(reopened_store.scan("Attempt", {})), unfinished)
        error = Error("timeout", "interrupted body", True, self.source.source_id, {})
        result = CommandResult(context, "failed", None, None, 1, 0, 0, 1, 1, 0, (error,),
                               context.started_at, context.started_at + timedelta(seconds=10))
        reopened.finish_attempt(result)
        finished = tuple(self.store.scan("Attempt", {}))[0]
        self.assertEqual(finished.to_mapping()["value"]["result"], result.to_mapping())
        self.assertEqual(finished.value["structured_errors"][0]["code"], "timeout")
        reopened.finish_attempt(result)
        self.assertEqual(tuple(self.store.scan("Attempt", {}))[0], finished)
        with self.assertRaises(self.contracts.Conflict):
            reopened.finish_attempt(replace(result, outcome="success", gaps=()))

    def test_request_attempts_are_immutable_auditable_and_bounded(self):
        context = fixture_context()
        self.state.begin_attempt(context)
        receipt = BodyReceipt(self.source.canonical_url, 503, {"Retry-After": "120"}, self.root / "body",
                              context.started_at, 0, "0" * 64, False,
                              Error("http", "unavailable", True, self.source.source_id, {}))
        permit = Permit("owner", 3, "request", context.started_at + timedelta(seconds=1),
                        context.started_at + timedelta(seconds=90), context.started_at + timedelta(seconds=92),
                        1.0, 90.0)
        self.state.request_attempt(context, receipt, permit, 1)
        self.state.request_attempt(context, receipt, permit, 1)
        rows = tuple(self.store.scan("TransportAttempt", {}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].value["ownership_epoch"], 3)
        self.assertEqual(rows[0].value["request_id"], "request")
        self.assertEqual(rows[0].value["status"], 503)
        self.assertIsNone(rows[0].value["next_allowed_at"])
        with self.assertRaises(self.contracts.Conflict):
            self.state.request_attempt(context, replace(receipt, status=200), permit, 1)
        for ordinal in (0, 6, True):
            with self.subTest(ordinal=ordinal), self.assertRaises(ValueError):
                self.state.request_attempt(context, receipt, permit, ordinal)

    def test_snapshot_durable_boundary_can_be_replayed_without_erasing_raw_or_success(self):
        self.state.observe(self.source, self.clock.now(), "available")
        snapshot = fixture_snapshot(self.source, b"accepted bytes")
        self.objects.put_once(snapshot.raw_path, b"accepted bytes")
        faults = Faults()
        local = importlib.import_module("sec_edgar_ingest.storage.local")
        interrupted = local.LocalStateStore(self.root, observer=faults)
        self.addCleanup(interrupted.close)
        def crash():
            raise RuntimeError("snapshot committed, source not updated")
        faults.at("state.after_insert", crash)
        state = self.state_module.AcquisitionState(interrupted)
        with self.assertRaisesRegex(RuntimeError, "snapshot committed"):
            state.remember_snapshot(snapshot)
        self.objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
        self.assertEqual(self.state.snapshot(self.source.source_id, snapshot.sha256), snapshot)
        self.state.remember_snapshot(snapshot)
        self.assertEqual(self.state.get_source(self.source.source_id).value["latest_downloaded_snapshot"], snapshot.sha256)

    def test_binding_requires_snapshot_and_cas_conflicts_are_bounded(self):
        snapshot = fixture_snapshot(self.source, b"accepted")
        with self.assertRaises(self.contracts.Conflict):
            self.state.bind_once(Binding("a" * 64, self.source.source_id, snapshot.sha256))
        self.state.observe(self.source, self.clock.now(), "available")
        class ConflictingStore:
            def __init__(inner):
                inner.replaces = 0
            def get(inner, kind, key):
                return self.store.get(kind, key)
            def replace(inner, kind, key, value, version):
                inner.replaces += 1
                raise self.contracts.Conflict("concurrent writer")
        conflicting = ConflictingStore()
        state = self.state_module.AcquisitionState(conflicting)
        with self.assertRaises(self.contracts.Conflict):
            state.observe(self.source, self.clock.now(), "available")
        self.assertGreater(conflicting.replaces, 0)
        self.assertLessEqual(conflicting.replaces, 5)

    def test_mismatched_observed_source_address_is_not_remembered(self):
        self.state.observe(self.source, self.clock.now(), "available")
        snapshot = fixture_snapshot(self.source, b"bytes")
        mismatched = replace(snapshot, raw_path=snapshot.raw_path.replace("period=2015Q1", "period=2015Q2"))
        with self.assertRaises(self.contracts.Conflict):
            self.state.remember_snapshot(mismatched)
        self.assertEqual(tuple(self.store.scan("Snapshot", {})), ())

    def test_existing_pin_wins_even_if_a_retry_candidate_is_unremembered(self):
        snapshot = fixture_snapshot(self.source, b"accepted")
        self.state.remember_snapshot(snapshot)
        winner = self.state.bind_once(Binding("a" * 64, self.source.source_id, snapshot.sha256))
        candidate = Binding("a" * 64, self.source.source_id, "b" * 64)
        try:
            actual = self.state.bind_once(candidate)
        except self.contracts.Conflict as error:
            self.fail(f"A durable existing pin must win before validating a retry candidate: {error}")
        self.assertEqual(actual, winner)
