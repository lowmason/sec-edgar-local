"""One request client audits every exchange and keeps retries outside ownership."""
from __future__ import annotations

import hashlib
import http.client
import json
import multiprocessing
import os
import random
import signal
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from .config import Settings
from .coordination import Clock, Coordinator, PolicyBlocked, Sender
from .models import BodyReceipt, Error, Permit, RunContext, Source, error_text, require_number, require_utc
from .state import AcquisitionState
from .storage.contracts import ClockUncertain, OwnershipLost, TimeBounds
from .urls import canonical_listing_url, canonical_source_url
from .validation import ValidationError, advertised_length, header_value, is_denial, validate_envelope

HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500
HTTP_REDIRECT_START = 300
HTTP_CLIENT_ERROR_START = 400


class FetchError(RuntimeError):
    def __init__(self, error: Error, receipt: BodyReceipt):
        self.error, self.receipt = error, receipt
        super().__init__(error.message)


def retry_after(value: str | None, now: datetime) -> float | None:
    require_utc(now, "Retry-After reference time")
    if value is None:
        return None
    stripped = value.strip()
    if stripped.isascii() and stripped.isdigit():
        try:
            seconds = float(int(stripped))
            require_number(seconds, "Retry-After seconds")
            return seconds
        except (OverflowError, ValueError):
            return None
    try:
        instant = parsedate_to_datetime(stripped)
        require_utc(instant, "Retry-After date")
        return max(0.0, (instant-now).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def retry_delay(ordinal: int, server_delay: float | None, settings: Settings, jitter: float) -> float:
    require_number(ordinal, "retry ordinal", positive=True, integer=True)
    if ordinal > settings.http.max_attempts:
        raise ValueError("retry ordinal exceeds the configured attempt budget")
    require_number(jitter, "retry jitter")
    if jitter > 1:
        raise ValueError("jitter outside [0,1]")
    if server_delay is not None:
        require_number(server_delay, "server delay")
    local = min(settings.http.retry_cap_seconds, settings.http.retry_base_seconds * (2 ** (ordinal-1)))
    return max(local*jitter, server_delay or 0)


def _new_receipt(url, body, status, headers, now, *, complete=True, error=None, root=None):
    destination = Path(tempfile.mkdtemp(prefix="sec-entity-")) if root is None else Path(root)
    path = destination / ("body-"+uuid.uuid4().hex)
    path.write_bytes(body)
    return BodyReceipt(url, status, headers, path, now, len(body), hashlib.sha256(body).hexdigest(), complete, error)


@dataclass(frozen=True)
class ResponseSpec:
    """Only the offline ScriptedSender consumes these synthetic responses."""
    status: int
    body: bytes
    headers: dict[str, str]
    fault: str | None = None


class ScriptedSender:
    def __init__(self, responses: Sequence[ResponseSpec]):
        self.responses = list(responses)
        self.clock = Clock()
        self.starts = []
        self.maximum_active = self.active = 0
        self.directory = tempfile.TemporaryDirectory(prefix="sec-scripted-")

    def send(self, url: str, context: RunContext, permit: Permit, *, cancellation) -> BodyReceipt:
        if cancellation.is_set() or self.clock.monotonic() >= permit.start_before_mono:
            raise OwnershipLost("scripted transport refuses a cancelled or expired permit")
        if not self.responses:
            raise RuntimeError("scripted fixture has no remaining response")
        spec = self.responses.pop(0)
        self.starts.append(self.clock.monotonic())
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            error = Error(spec.fault, "scripted transport fault: "+spec.fault, True, None, {}) if spec.fault else None
            body = spec.body
            return _new_receipt(url, body, spec.status, spec.headers, self.clock.now(), complete=error is None,
                                error=error, root=self.directory.name)
        finally:
            self.active -= 1

    def close(self):
        self.directory.cleanup()


@dataclass
class _ResponsePolicy:
    outcome: str | None = None
    error: Error | None = None
    retry: dict = field(default_factory=dict)
    next_allowed: datetime | None = None


class _UnrepresentableRetry(ValueError):
    def __init__(self, metadata):
        self.metadata = metadata
        super().__init__("valid server Retry-After cannot be represented as a finite UTC scheduling instant")


class _AuditedSender:
    def __init__(self, sender, state, source, ordinal, clock):
        self.sender, self.state, self.source, self.ordinal, self.clock = sender, state, source, ordinal, clock
        self.permit = self.receipt = None
        self.begun = False

    def send(self, url, context, permit, *, cancellation):
        self.permit = permit
        halt = self.state.run_halt(context)
        if halt is not None:
            error = Error("run_halted", "serialized admission refused a durably halted run", False,
                          self.source.source_id if self.source else None, {"cause": halt.to_mapping(), "outcome": "halted"})
            raise FetchError(error, _new_receipt(url, b"", 0, {}, self.clock.now(), complete=False))
        self.state.begin_request(context, url, self.source.source_id if self.source else None, permit.request_id, self.ordinal)
        self.begun = True
        self.receipt = self.sender.send(url, context, permit, cancellation=cancellation)
        return self.receipt


class RequestClient:
    def __init__(self, settings: Settings, coordinator: Coordinator, sender: Sender,
                 state: AcquisitionState, clock: Clock):
        self.settings = Settings.from_mapping(settings.to_mapping())
        if coordinator.settings != self.settings:
            raise ValueError("request client and coordinator require the same effective settings")
        if isinstance(sender, ScriptedSender) and settings.storage.backend != "local-fixture":
            raise ValueError("scripted transport is fixture-only")
        self.coordinator, self.sender, self.state, self.clock = coordinator, sender, state, clock
        self.jitter = random.random

    def _error(self, code, message, source, *, retryable=False, details=None):
        return Error(code, message, retryable, source.source_id if source else None, details or {})

    def _empty(self, url):
        return _new_receipt(url, b"", 0, {}, self.clock.now(), complete=False)

    def _previous_receipt(self, rows, url):
        for row in reversed(rows):
            if row.value.get("receipt") is not None:
                return BodyReceipt.from_mapping(row.to_mapping()["value"]["receipt"])
        return self._empty(url)

    def _retry_time_bounds(self) -> TimeBounds:
        bounds = self.coordinator.leases.observe_time()
        if not isinstance(bounds, TimeBounds):
            raise ClockUncertain("retry requires an actual server-time bound")
        if (bounds.upper-bounds.lower).total_seconds() > self.settings.coordination.clock_uncertainty_seconds:
            raise ClockUncertain("retry server-time bound exceeds configured uncertainty")
        return bounds.at(self.clock.monotonic())

    def _outcome(self, receipt, source):
        if is_denial(receipt):
            return "halted", self._error("access_denied", "SEC access denial stops every subsequent request in this run", source)
        if receipt.error is not None or not receipt.complete:
            error = receipt.error or self._error("incomplete_body", "transport did not receive a complete entity", source, retryable=True)
            return "retry" if error.retryable and error.code != "ownership_lost" else "failed", error
        if receipt.status == HTTP_OK:
            if source is not None:
                try:
                    validate_envelope(source, receipt, self.settings)
                except ValidationError as error:
                    return "quarantined", self._error(error.code, "invalid acquisition envelope: "+error.code, source)
            return "received", None
        if receipt.status == HTTP_NOT_FOUND:
            return ("pending", self._error("listed_missing", "a listed source is temporarily absent", source, retryable=True)) if source else ("failed", self._error("listing_missing", "directory listing returned 404", source))
        if HTTP_REDIRECT_START <= receipt.status < HTTP_CLIENT_ERROR_START:
            return "failed", self._error("redirect_refused", "SEC redirect was refused without following its Location", source, details={"status": receipt.status})
        if receipt.status == HTTP_TOO_MANY_REQUESTS or receipt.status >= HTTP_SERVER_ERROR:
            return "retry", self._error("http_retryable", "retryable HTTP response", source, retryable=True, details={"status": receipt.status})
        return "failed", self._error("http_failed", "HTTP response is not an accepted entity", source, details={"status": receipt.status})

    def _retry_metadata(self, receipt, permit, ordinal):
        bounds = self._retry_time_bounds()
        if not isinstance(bounds, TimeBounds):
            raise ClockUncertain("retry requires server TimeBounds; host UTC is not a substitute")
        value = header_value(receipt.headers, "Retry-After")
        server_delay = retry_after(value, bounds.lower)
        metadata = {"retry_after_value": value, "retry_after_valid": value is None or server_delay is not None,
                    "server_delay_seconds": server_delay, "server_lower": bounds.lower.isoformat(),
                    "server_upper": bounds.upper.isoformat(), "observed_mono": bounds.monotonic_at}
        numeric = value is not None and value.strip().isascii() and value.strip().isdigit()
        if numeric and server_delay is None:
            raise _UnrepresentableRetry({**metadata, "retry_after_valid": True, "policy_blocked": True,
                                         "not_before": None, "ready_mono": None})
        delay = retry_delay(ordinal, server_delay, self.settings, self.jitter())
        metadata["delay_seconds"] = delay
        try:
            not_before = bounds.upper+timedelta(seconds=delay)
        except OverflowError as error:
            raise _UnrepresentableRetry({**metadata, "policy_blocked": True, "not_before": None, "ready_mono": None}) from error
        if permit.next_allowed_at is not None:
            not_before = max(not_before, permit.next_allowed_at)
        return {**metadata, "not_before": not_before.isoformat(),
                "ready_mono": bounds.monotonic_at+(not_before-bounds.lower).total_seconds()}, not_before

    def _publish_response_policy(self, context, source, ordinal, receipt, permit, policy):
        # Only the small transport/access policy is inside ownership; source envelope scans happen afterward.
        outcome, error = self._outcome(receipt, None)
        if outcome == "halted":
            error = replace(error, source_id=source.source_id if source else None)
            self.state.halt_run(context, error)
            policy.outcome, policy.error = outcome, error
        elif outcome == "retry":
            try:
                policy.retry, policy.next_allowed = self._retry_metadata(receipt, permit, ordinal)
                self.coordinator.defer_until(policy.next_allowed)
                policy.retry["cooldown_confirmed"] = True
            except _UnrepresentableRetry as unsupported:
                policy.retry = unsupported.metadata
                reason = self._error("retry_delay_unrepresentable", str(unsupported), source,
                                     details={"outcome": "deferred", "url": receipt.url, "request_id": permit.request_id,
                                              "ordinal": ordinal, "retry": policy.retry})
                self.coordinator.block_requests(reason)
                policy.outcome, policy.error = "deferred", reason
            except (ClockUncertain, OwnershipLost, ValueError) as exception:
                policy.outcome = "failed"
                policy.retry["cooldown_confirmed"] = False
                policy.next_allowed = None
                policy.error = self._error("clock_uncertain" if isinstance(exception, ClockUncertain) else "cooldown_unconfirmed",
                                          "retry cooldown could not be confirmed: "+error_text(exception), source)
                raise

    def fetch(self, url: str, context: RunContext, source: Source | None = None) -> BodyReceipt:
        canonical = canonical_source_url(url, source.kind) if source else canonical_listing_url(url)
        if canonical != url or (source is not None and source.canonical_url != url):
            raise ValueError("request URL must match its canonical SEC identity")
        command_deadline_mono = self.clock.monotonic()+(context.deadline-self.clock.now()).total_seconds()
        self.state.begin_attempt(context)
        halt = self.state.run_halt(context)
        if halt is not None:
            raise FetchError(self._error("run_halted", "run was durably halted by SEC access denial", source,
                                        details={"cause": halt.to_mapping(), "outcome": "halted"}), self._empty(url))
        rows = self.state.request_history(context, url)
        ordinal = len(rows)+1
        if ordinal > self.settings.http.max_attempts:
            raise FetchError(self._error("attempts_exhausted", "all accounted attempts for this command and URL are exhausted", source, details={"outcome": "exhausted"}), self._previous_receipt(rows, url))
        while ordinal <= self.settings.http.max_attempts:
            audited = _AuditedSender(self.sender, self.state, source, ordinal, self.clock)
            policy = _ResponsePolicy()
            try:
                receipt = self.coordinator.exchange(context, url, audited,
                    on_response=lambda received, permit: self._publish_response_policy(context, source, ordinal, received, permit, policy))
            except FetchError:
                raise
            except PolicyBlocked as blocked:
                error = self._error("policy_blocked", "durable owner policy forbids another request", source,
                                    details={"outcome": "deferred", "cause": blocked.reason.to_mapping()})
                raise FetchError(error, self._empty(url)) from blocked
            except Exception as exception:
                receipt = getattr(exception, "receipt", None) or audited.receipt or self._empty(url)
                error = self._error("ownership_lost" if isinstance(exception, OwnershipLost) else "sender_unverified",
                                    "exchange stopped without a confirmed transport outcome: "+error_text(exception), source, details={"outcome": "failed", "ordinal": ordinal})
                if audited.begun:
                    self.state.request_attempt(context, receipt, audited.permit, ordinal, outcome="failed", error=error)
                if source is not None:
                    self.state.record_failure(source, error)
                raise FetchError(error, receipt) from exception
            outcome, error = self._outcome(receipt, source)
            retry, next_allowed = policy.retry, policy.next_allowed or audited.permit.next_allowed_at
            if policy.outcome is not None:
                outcome, error = policy.outcome, policy.error
            elif receipt.error is not None and receipt.error.code == "ownership_lost":
                outcome, error = "failed", receipt.error
            if outcome == "retry":
                if ordinal == self.settings.http.max_attempts:
                    outcome = "exhausted"
                    error = self._error("attempts_exhausted", "fifth or configured final request failed", source,
                                        details={"cause": error.to_mapping()})
                elif retry["ready_mono"] >= command_deadline_mono:
                    outcome = "deferred"
                    error = self._error("deferred", "retry delay reaches or exceeds this command's deadline", source, retryable=True,
                                        details={"next_allowed_at": next_allowed.isoformat()})
            if error is not None:
                error = replace(error, source_id=source.source_id if source else None,
                                details={**error.to_mapping()["details"], "outcome": outcome,
                                         "ordinal": ordinal, "request_id": audited.permit.request_id})
            self.state.request_attempt(context, receipt, audited.permit, ordinal, outcome=outcome,
                                       error=error, retry=retry, next_allowed_at=next_allowed)
            if outcome == "received":
                return receipt
            if outcome != "retry":
                if source is not None:
                    self.state.record_failure(source, error)
                raise FetchError(error, receipt)
            self.clock.sleep(max(0, retry["ready_mono"]-self.clock.monotonic()))
            ordinal += 1
        raise AssertionError("unreachable attempt budget")


# IPC carries only a completion marker; response metadata and partial bytes survive child death on disk.
CHUNK_BYTES = 65536
SUPERVISOR_POLL_SECONDS = 0.05
DRAIN_JOIN_SECONDS = 1
SPAWN = multiprocessing.get_context("spawn")


class HardTimerUnavailable(RuntimeError):
    pass


class SenderFailure(OwnershipLost):
    def __init__(self, message: str, receipt: BodyReceipt):
        self.receipt = receipt
        super().__init__(message)


@dataclass(frozen=True)
class _Transport:
    url: str
    spool: str
    user_agent: str
    connect_timeout: float
    read_timeout: float
    max_received_bytes: int
    start_before_mono: float
    deadline_mono: float
    fixture_origin: str | None
    fixture_only: bool


def _canonical_request_url(url: str) -> None:
    if url.endswith("/index.json"):
        canonical = canonical_listing_url(url)
    else:
        kind = "quarterly" if "/full-index/" in url else "daily"
        canonical = canonical_source_url(url, kind)
    if canonical != url:
        raise ValueError("transport requires an exact canonical SEC URL")


def _validate_transport_origin(transport: _Transport) -> None:
    if transport.fixture_origin is None:
        _canonical_request_url(transport.url)
        return
    origin, url = urlsplit(transport.fixture_origin), urlsplit(transport.url)
    if (not transport.fixture_only or origin.scheme != "http" or origin.hostname != "127.0.0.1"
            or origin.path or origin.query or origin.fragment or origin.username or origin.password
            or url.scheme != origin.scheme or url.netloc != origin.netloc or url.fragment or url.username or url.password):
        raise ValueError("fixture transport is restricted to its explicitly selected loopback origin")


def _trace_transport(transport, event, **details):
    record = {"event": event, "pid": os.getpid(), "monotonic": time.monotonic(),
              "utc": datetime.now(timezone.utc).isoformat(), **details}
    descriptor = os.open(str(Path(transport.spool)/"transport.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, (json.dumps(record, sort_keys=True)+"\n").encode())
    finally:
        os.close(descriptor)


def _write_transport_metadata(transport, value):
    path = Path(transport.spool)/"receipt.json"
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value, sort_keys=True))
    temporary.replace(path)


def arm_child_deadline(transport) -> None:
    now = time.monotonic()
    if now >= transport.start_before_mono or now >= transport.deadline_mono:
        raise OwnershipLost("permit expired before DNS or socket start")
    if sys.platform not in ("linux", "darwin") or any(not hasattr(signal, name) for name in ("SIGALRM", "ITIMER_REAL", "pthread_sigmask", "setitimer")):
        raise HardTimerUnavailable("platform has no proven independent fatal HTTP timer")
    try:
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGALRM})
        remaining = transport.deadline_mono-time.monotonic()
        if remaining <= 0:
            raise OwnershipLost("whole exchange deadline expired before arming")
        signal.setitimer(signal.ITIMER_REAL, remaining)
        blocked = signal.SIGALRM in signal.pthread_sigmask(signal.SIG_BLOCK, set())
        if blocked or signal.getsignal(signal.SIGALRM) != signal.SIG_DFL or signal.getitimer(signal.ITIMER_REAL)[0] <= 0:
            raise HardTimerUnavailable("fatal HTTP timer was not positively armed")
    except (OSError, ValueError, RuntimeError) as error:
        raise HardTimerUnavailable("could not install independent fatal HTTP timer") from error
    _trace_transport(transport, "alarm-armed", deadline_mono=transport.deadline_mono,
                     alarm_disposition="default-fatal", alarm_blocked=blocked)


def incomplete_read_bytes(exception: BaseException) -> bytes:
    pending, visited = [exception], set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, http.client.IncompleteRead) and isinstance(current.partial, bytes):
            return current.partial
        if isinstance(current, BaseException):
            pending.extend(item for item in current.args if isinstance(item, BaseException))
            pending.extend(item for item in (current.__cause__, current.__context__) if isinstance(item, BaseException))
    return b""


class _TransportProblem(RuntimeError):
    def __init__(self, code, message, *, retryable=False, details=None):
        self.code, self.retryable, self.details = code, retryable, details or {}
        super().__init__(message)


def _require_child_current(transport, cancellation, *, starting=False):
    now = time.monotonic()
    if cancellation.is_set():
        raise _TransportProblem("cancelled", "ownership cancellation reached the HTTP child")
    if now >= transport.deadline_mono:
        raise _TransportProblem("exchange_deadline", "absolute HTTP exchange deadline expired", retryable=True)
    if starting and now >= transport.start_before_mono:
        raise _TransportProblem("permit_expired", "child refused a stale dispatch window")


def _write_chunk(stream, body: bytes, count: int, maximum: int) -> int:
    received = count+len(body)
    allowed = min(len(body), max(0, maximum-count))
    if allowed:
        stream.write(body[:allowed])
    if received > maximum:
        raise _TransportProblem("received_limit", "received entity exceeded its absolute byte guard",
                                details={"received_bytes": received, "retained_bytes": count+allowed})
    return received


def _read_http_entity(transport, cancellation, metadata):
    import requests
    from urllib3.exceptions import HTTPError
    from urllib3.util import Retry
    session = requests.Session()
    session.trust_env = False
    adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1,
        max_retries=Retry(total=0, connect=0, read=0, redirect=0, status=0, other=0))
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    count = 0
    response = None
    try:
        _require_child_current(transport, cancellation, starting=True)
        request = session.prepare_request(requests.Request("GET", transport.url,
            headers={"User-Agent": transport.user_agent, "Accept-Encoding": "identity"}))
        # Session.send prepares a possible redirect by consuming its body, even with allow_redirects=False.
        _require_child_current(transport, cancellation, starting=True)
        _trace_transport(transport, "socket-start")
        _require_child_current(transport, cancellation, starting=True)
        response = adapter.send(request, stream=True, timeout=(transport.connect_timeout, transport.read_timeout),
                                verify=True, proxies={})
        metadata.update(status=response.status_code, headers=dict(response.headers), received_at=datetime.now(timezone.utc).isoformat())
        _write_transport_metadata(transport, metadata)
        _trace_transport(transport, "headers-received", status=response.status_code)
        response.raw.decode_content = False
        encoding = header_value(response.headers, "Content-Encoding")
        unsupported_encoding = encoding and encoding.strip().lower() != "identity"
        try:
            length = advertised_length(response.headers)
        except ValueError as error:
            raise _TransportProblem("invalid_content_length", error_text(error)) from error
        if length is not None and length > transport.max_received_bytes:
            raise _TransportProblem("received_limit", "advertised entity exceeds its received byte guard")
        with (Path(transport.spool)/"body").open("ab", buffering=0) as stream:
            try:
                while True:
                    _require_child_current(transport, cancellation)
                    chunk = response.raw.read1(min(CHUNK_BYTES, transport.max_received_bytes-count+1), decode_content=False)
                    if not chunk:
                        break
                    count = _write_chunk(stream, chunk, count, transport.max_received_bytes)
                    _trace_transport(transport, "entity-spooled", retained_bytes=count)
            except (requests.RequestException, HTTPError, OSError) as error:
                partial = incomplete_read_bytes(error)
                if partial:
                    count = _write_chunk(stream, partial, count, transport.max_received_bytes)
                    _trace_transport(transport, "incomplete-read-partial-spooled", retained_bytes=count)
                code = "timeout" if isinstance(error, requests.Timeout) or "timeout" in type(error).__name__.lower() else "incomplete_body"
                raise _TransportProblem(code, "HTTP stream interrupted: "+error_text(error), retryable=True) from error
        if length is not None and length != count:
            raise _TransportProblem("content_length_mismatch", "advertised entity length differs from retained bytes", retryable=True)
        if unsupported_encoding:
            raise _TransportProblem("unsupported_content_encoding", "unexpected Content-Encoding retained without decoding")
        return count
    except requests.RequestException as error:
        code = "timeout" if isinstance(error, requests.Timeout) else "connection_failed"
        raise _TransportProblem(code, "HTTP connection failed: "+error_text(error), retryable=True) from error
    finally:
        if response is not None:
            response.close()
        session.close()
        _trace_transport(transport, "session-closed", retained_bytes=count)


def _child_exchange(transport: _Transport, cancellation, channel):
    # Spawn carries no SDK clients. Clear ambient credentials/proxy variables before importing Requests.
    os.environ.clear()
    metadata = {"status": 0, "headers": {}, "received_at": datetime.now(timezone.utc).isoformat(),
                "complete": False, "error": None, "unsafe": False}
    _trace_transport(transport, "child-environment-cleared", remaining_environment_keys=len(os.environ))
    _write_transport_metadata(transport, metadata)
    try:
        _validate_transport_origin(transport)
        _require_child_current(transport, cancellation, starting=True)
        arm_child_deadline(transport)
        _read_http_entity(transport, cancellation, metadata)
        metadata["complete"] = True
    except _TransportProblem as error:
        metadata["error"] = {"code": error.code, "message": error_text(error), "retryable": error.retryable, "details": error.details}
    except HardTimerUnavailable as error:
        metadata["error"] = {"code": "hard_timer_unavailable", "message": error_text(error), "retryable": False, "details": {}}
    except OwnershipLost as error:
        metadata["error"] = {"code": "permit_expired", "message": error_text(error), "retryable": False, "details": {}}
    except BaseException as error:
        metadata["unsafe"] = True
        metadata["error"] = {"code": "sender_internal", "message": "unexpected HTTP child failure: "+error_text(error), "retryable": False, "details": {"type": type(error).__name__}}
    _write_transport_metadata(transport, metadata)
    try:
        channel.send_bytes(b"complete")
        _trace_transport(transport, "child-completed", complete=metadata["complete"])
    except (OSError, ValueError):
        _trace_transport(transport, "ipc-send-failed")
    finally:
        channel.close()
        # Leave the fatal timer armed through interpreter exit and process finalizers.


def _drain_child(process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(DRAIN_JOIN_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(DRAIN_JOIN_SECONDS)
    if process.is_alive() or process.exitcode is None:
        raise OwnershipLost("sender child did not positively drain; retain its unsafe ownership window")
    process.join(timeout=0)


def wait_for_sender(process, cancellation, deadline_mono: float, clock: Clock) -> bool:
    while process.is_alive():
        remaining = deadline_mono-clock.monotonic()
        if cancellation.is_set() or remaining <= 0:
            _drain_child(process)
            return False
        process.join(timeout=min(remaining, SUPERVISOR_POLL_SECONDS))
    process.join(timeout=0)
    if process.exitcode is None:
        raise OwnershipLost("sender completion did not confirm a joined process")
    return True


class BoundedSender:
    def __init__(self, settings: Settings, clock: Clock):
        if type(clock) is not Clock:
            raise ValueError("OS-enforced HTTP timers require the real same-host OS monotonic Clock")
        if sys.platform not in ("linux", "darwin") or not hasattr(signal, "setitimer"):
            raise OwnershipLost("execution platform lacks a proven independent fatal HTTP timer")
        self.settings = Settings.from_mapping(settings.to_mapping())
        self.clock = clock

    def _validated_origin(self, url):
        _canonical_request_url(url)
        return None

    def _child_target(self):
        return _child_exchange

    def _spool_directory(self):
        return Path(tempfile.mkdtemp(prefix="sec-http-"))

    def _receipt(self, transport, *, reason=None):
        body_path = Path(transport.spool)/"body"
        digest, count = hashlib.sha256(), 0
        with body_path.open("rb") as body:
            while chunk := body.read(CHUNK_BYTES):
                count += len(chunk)
                digest.update(chunk)
        try:
            metadata = json.loads((Path(transport.spool)/"receipt.json").read_text())
            if not isinstance(metadata, dict) or type(metadata.get("unsafe")) is not bool or type(metadata.get("complete")) is not bool:
                raise ValueError("invalid child metadata shape")
            problem = metadata["error"]
            error = Error(problem["code"], problem["message"], problem["retryable"], None, problem.get("details", {})) if problem else None
            receipt = BodyReceipt(transport.url, metadata["status"], metadata["headers"], body_path,
                                  datetime.fromisoformat(metadata["received_at"]), count, digest.hexdigest(),
                                  metadata["complete"] and reason is None and error is None, error)
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            metadata = {"unsafe": True}
            error = Error("sender_protocol", "child metadata did not confirm a valid receipt", False, None, {})
            receipt = BodyReceipt(transport.url, 0, {}, body_path, self.clock.now(), count, digest.hexdigest(), False, error)
        if reason is not None:
            receipt = replace(receipt, complete=False, error=Error(reason, "HTTP child was drained after "+reason,
                              reason == "exchange_deadline", None, {}))
        return receipt, metadata["unsafe"]

    def send(self, url: str, context: RunContext, permit: Permit, *, cancellation) -> BodyReceipt:
        origin = self._validated_origin(url)
        spool = self._spool_directory()
        (spool/"body").write_bytes(b"")
        transport = _Transport(url, str(spool), self.settings.sec.user_agent,
            self.settings.http.connect_timeout_seconds, self.settings.http.read_timeout_seconds,
            self.settings.http.max_received_bytes, permit.start_before_mono, permit.deadline_mono,
            origin, self.settings.storage.backend == "local-fixture" and "fixture" in self.settings.worker.provenance)
        _validate_transport_origin(transport)
        if cancellation.is_set() or self.clock.monotonic() >= min(permit.start_before_mono, permit.deadline_mono):
            receipt, _ = self._receipt(transport, reason="permit_expired")
            raise SenderFailure("sender refused cancellation or a stale permit before spawning", receipt)
        reader, writer = SPAWN.Pipe(duplex=False)
        process = SPAWN.Process(target=self._child_target(), args=(transport, cancellation, writer))
        _trace_transport(transport, "supervisor-start", start_before_mono=permit.start_before_mono, deadline_mono=permit.deadline_mono)
        stopped = marker = False
        try:
            process.start()
            writer.close()
            stopped = not wait_for_sender(process, cancellation, permit.deadline_mono, self.clock)
            _trace_transport(transport, "child-joined", pid=process.pid, exitcode=process.exitcode)
            if reader.poll(0):
                try:
                    marker = reader.recv_bytes(maxlength=32) == b"complete"
                except (EOFError, OSError):
                    marker = False
            reason = "cancelled" if cancellation.is_set() else "exchange_deadline" if stopped or process.exitcode == -signal.SIGALRM else None
            receipt, unsafe = self._receipt(transport, reason=reason)
            if unsafe:
                raise SenderFailure("HTTP child reported an unconfirmed outcome; retain unsafe guard", receipt)
            if reason is None and (not marker or process.exitcode != 0):
                receipt = replace(receipt, complete=False, error=Error("ipc_loss", "child receipt or completion channel was not positively confirmed", False, None, {}))
                raise SenderFailure("HTTP child has an unconfirmed result; retain unsafe guard", receipt)
            return receipt
        except SenderFailure:
            raise
        except BaseException as error:
            if process.pid is not None:
                try:
                    _drain_child(process)
                    _trace_transport(transport, "child-joined", pid=process.pid, exitcode=process.exitcode)
                except OwnershipLost as drain_error:
                    receipt, _ = self._receipt(transport, reason="shutdown_unverified")
                    raise SenderFailure(str(drain_error), receipt) from error
            receipt, _ = self._receipt(transport, reason="sender_unverified")
            raise SenderFailure("HTTP supervisor could not confirm its child outcome: "+error_text(error), receipt) from error
        finally:
            reader.close()
            writer.close()


class FixtureError(ValueError):
    """Missing, corrupt or exhausted explicit fixture inputs never authorize HTTP."""


@dataclass(frozen=True)
class FixturePack:
    responses: dict[str, tuple[ResponseSpec, ...]]
    manifest_sha256: str
    provenance: str

    @classmethod
    def load(cls, path: Path) -> FixturePack:
        from .models import canonical_json, parse_json, require_hash, safe_relative_path
        root = Path(path).resolve().parent
        value = parse_json(Path(path).read_bytes())
        if not isinstance(value, dict) or set(value) != {'fixture_version', 'provenance', 'responses'}:
            raise FixtureError('fixture manifest requires the exact v1 fields')
        if value['fixture_version'] != 'sec-acquisition-fixture-v1' or value['provenance'] not in ('synthetic', 'retained-stage-1'):
            raise FixtureError('unsupported fixture version or provenance')
        if not isinstance(value['responses'], dict) or not value['responses']:
            raise FixtureError('fixture responses must be a nonempty URL mapping')
        responses = {}
        for url, items in value['responses'].items():
            try:
                _canonical_request_url(url)
            except (ValueError, TypeError) as error:
                raise FixtureError('fixture response URL must be a canonical SEC identity') from error
            if not isinstance(items, list) or not items:
                raise FixtureError('fixture URL requires a nonempty response sequence')
            parsed = []
            for spec in items:
                required = {'status', 'headers', 'body_path', 'body_sha256'}
                if not isinstance(spec, dict) or not required <= spec.keys() or set(spec) - required - {'fault'}:
                    raise FixtureError('fixture response has unsupported fields')
                if type(spec['status']) is not int or not 100 <= spec['status'] <= 599:
                    raise FixtureError('fixture status must be an HTTP integer')
                if not isinstance(spec['headers'], dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in spec['headers'].items()):
                    raise FixtureError('fixture headers require string keys and values')
                fault = spec.get('fault')
                if fault is not None and fault not in ('read_timeout', 'connection_failed', 'incomplete_body', 'ownership_lost'):
                    raise FixtureError('unsupported explicit fixture fault')
                relative = safe_relative_path(spec['body_path'], 'fixture body_path')
                file = (root / relative).resolve()
                if not file.is_relative_to(root) or not file.is_file():
                    raise FixtureError('fixture body must be a file beneath the manifest directory')
                require_hash(spec['body_sha256'], 'fixture body_sha256')
                body = file.read_bytes()
                if hashlib.sha256(body).hexdigest() != spec['body_sha256']:
                    raise FixtureError('fixture body hash differs from explicit manifest')
                parsed.append(ResponseSpec(spec['status'], body, dict(spec['headers']), fault))
            responses[url] = tuple(parsed)
        return cls(responses, hashlib.sha256(canonical_json(value)).hexdigest(), value['provenance'])

    def sender(self, state) -> Sender:
        return _FixtureSender(self, state)


class _FixtureSender:
    def __init__(self, pack: FixturePack, state):
        self.pack, self.state = pack, state
        self.clock = Clock()
        self.directory = tempfile.TemporaryDirectory(prefix='sec-fixture-')

    def send(self, url: str, context: RunContext, permit: Permit, *, cancellation) -> BodyReceipt:
        from .models import canonical_json
        from .storage.contracts import AlreadyExists, CAS_ATTEMPTS, Conflict
        if context.effective_config.get('storage', {}).get('backend') != 'local-fixture':
            raise FixtureError('fixture transport refuses a production context')
        if cancellation.is_set() or self.clock.monotonic() >= permit.start_before_mono:
            raise OwnershipLost('fixture transport refuses a cancelled or expired permit')
        sequence = self.pack.responses.get(url)
        if sequence is None:
            raise FixtureError('fixture has no mapping for ' + url)
        key = hashlib.sha256(canonical_json({'manifest_sha256': self.pack.manifest_sha256, 'url': url})).hexdigest()
        for _ in range(CAS_ATTEMPTS):
            row = self.state.get('FixtureResponseCursor', key)
            previous = row.to_mapping()['value'] if row is not None else {
                'fixture_only': True, 'manifest_sha256': self.pack.manifest_sha256, 'url': url, 'cursor': 0}
            if set(previous) != {'fixture_only', 'manifest_sha256', 'url', 'cursor'} or previous['fixture_only'] is not True or previous['manifest_sha256'] != self.pack.manifest_sha256 or previous['url'] != url or type(previous['cursor']) is not int or previous['cursor'] < 0:
                raise FixtureError('durable fixture cursor has conflicting provenance')
            cursor = previous['cursor']
            if cursor >= len(sequence):
                raise FixtureError('fixture response mapping is exhausted: ' + url)
            changed = {**previous, 'cursor': cursor + 1}
            try:
                if row is None:
                    self.state.insert('FixtureResponseCursor', key, changed)
                else:
                    self.state.replace('FixtureResponseCursor', key, changed, row.version)
                break
            except (AlreadyExists, Conflict):
                continue
        else:
            raise FixtureError('fixture response cursor exhausted conditional races')
        spec = sequence[cursor]
        error = Error(spec.fault, 'explicit fixture transport fault: ' + spec.fault,
                      spec.fault != 'ownership_lost', None, {}) if spec.fault else None
        return _new_receipt(url, spec.body, spec.status, spec.headers, self.clock.now(),
                            complete=error is None, error=error, root=self.directory.name)

    def close(self):
        self.directory.cleanup()
