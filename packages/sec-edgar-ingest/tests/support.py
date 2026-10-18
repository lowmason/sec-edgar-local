"""Validated builders shared by offline acquisition tests."""
import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from network_guard import install as _install_offline_guard, selected_origin

_install_offline_guard()

if TYPE_CHECKING:
    from sec_edgar_ingest.config import Settings
    from sec_edgar_ingest.download import ResponseSpec
    from sec_edgar_ingest.models import RunContext, Source, SourceWorkset, Snapshot, SnapshotWorkset, CommandResult
    from sec_edgar_ingest.storage.contracts import StateStore, ObjectStore, LeaseStore, BoundaryObserver

FIXTURE_CONFIG = Path(__file__).parent / "fixtures/config/local.json"
# Spawned-child timing. Measured 2026-10-14 on a 14-core host at load average 26, spawn-to-first-line latency
# was median 0.15 s, p90 0.65 s and max 1.03 s, against production windows of 1/3 s to start a request.
# A window a test must sit through is SPAWN_ALLOWANCE_SECONDS long. A wait that returns once a process reaches
# its point uses SPAWN_WAIT_SECONDS, which only bounds a hang. SLOW_SPAWN_SECONDS is a deterministic start delay
# longer than every production window (1/3 s to start, 0.4 s to finish), so a test can exercise a slow spawn.
SPAWN_ALLOWANCE_SECONDS = 3
SPAWN_WAIT_SECONDS = 30
SLOW_SPAWN_SECONDS = 0.5


def retained_path(original_path: str) -> Path:
    fixtures = Path(__file__).resolve().parent / "fixtures"
    mapping = json.loads((fixtures / "retained-path-map.json").read_text())
    by_original = {item["original_path"]: item for item in mapping["files"]}
    entry = by_original[original_path]
    target = (fixtures / entry["local_path"]).resolve()
    if not target.is_relative_to(fixtures) or not target.is_file():
        raise ValueError("retained fixture escaped or is missing")
    body = target.read_bytes()
    if len(body) != entry["bytes"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
        raise ValueError("retained fixture bytes differ from the import map")
    return target


def local_config_mapping(*, root: Path | None = None) -> dict:
    """Build a detached config map without constructing a store."""
    from sec_edgar_ingest.config import load_config
    value = load_config(FIXTURE_CONFIG).to_mapping()
    if root is not None:
        value["storage"]["root"] = str(root.resolve())
        value["logging"]["root"] = str((root.parent / (root.name + "-logs")).resolve())
    return value


def fixture_settings(*, root: Path | None = None, **overrides: object) -> "Settings":
    from sec_edgar_ingest.config import Settings, normalize_paths
    value = local_config_mapping(root=root)
    for key, override in overrides.items():
        if isinstance(override, dict) and isinstance(value.get(key), dict):
            value[key].update(override)
        else:
            value[key] = override
    return normalize_paths(Settings.from_mapping(value), FIXTURE_CONFIG.resolve().parent)


def spawn_tolerant_settings(*, root: Path | None = None, **overrides: dict) -> "Settings":
    """Fixture settings whose real coordinator windows absorb a slow spawn.

    A permit gives its child 1 / requests_per_second to start and exchange_deadline_seconds to finish.
    """
    sections = {"sec": {"requests_per_second": 1 / SPAWN_ALLOWANCE_SECONDS},
                "http": {"exchange_deadline_seconds": SPAWN_ALLOWANCE_SECONDS + 0.5}}
    for key, value in overrides.items():
        sections[key] = {**sections.get(key, {}), **value}
    return fixture_settings(root=root, **sections)


def fixture_context(command: str = "collect", priority: str = "backfill", *, settings: "Settings | None" = None) -> "RunContext":
    from sec_edgar_ingest.config import pin_context
    from sec_edgar_ingest.models import RunContext
    from sec_edgar_ingest.runtime import configured_descriptor
    settings = settings or fixture_settings()
    started = datetime(2026, 10, 6, tzinfo=timezone.utc)
    context = RunContext(
        run_id="fixture-run", execution_id="fixture-execution", command=command,
        attempt_id="fixture-attempt", runtime=configured_descriptor(settings),
        format_version="sec-local-run-context-v1",
        parser_version=settings.etl.parser_version, schema_version=settings.etl.schema_version,
        config_sha256=settings.config_sha256, started_at=started,
        deadline=started + timedelta(seconds=3600), priority=priority,
    )
    return pin_context(settings, context, date(2026, 10, 6))[0]


def fixture_source(period: str = "2015Q1", kind: str = "quarterly") -> "Source":
    from sec_edgar_ingest.models import Source
    from sec_edgar_ingest.urls import child_url, source_id
    if kind == "quarterly":
        year, quarter = period.split("Q")
        parent = f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/index.json"
        name, representation = "master.zip", "zip"
    else:
        day = date.fromisoformat(period)
        quarter = (day.month - 1) // 3 + 1
        parent = f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{quarter}/index.json"
        name, representation = f"master.{day:%Y%m%d}.idx", "idx"
    url = child_url(parent, name, name, False)
    return Source(source_id(url), url, kind, period, representation)


def fixture_workset(members: tuple["Source", ...], discovery_complete: bool = True, *, context: "RunContext | None" = None) -> "SourceWorkset":
    from sec_edgar_ingest.models import DirectoryOutcome, Error
    from sec_edgar_ingest.worksets import make_source_workset
    by_directory = {}
    for source in members:
        url = source.canonical_url.rsplit("/", 1)[0] + "/index.json"
        by_directory.setdefault(url, []).append(source)
    if not by_directory:
        by_directory["https://www.sec.gov/Archives/edgar/full-index/2015/QTR1/index.json"] = []
    directories = tuple(
        DirectoryOutcome(url, group[0].period if group else "2015Q1",
                         "available" if group else "no_new_sources", "a" * 64,
                         tuple(member.source_id for member in group), None)
        for url, group in by_directory.items()
    )
    if not discovery_complete:
        failed = DirectoryOutcome(
            "https://www.sec.gov/Archives/edgar/full-index/2015/QTR2/index.json",
            "2015Q2", "discovery_failed", None, (), Error("listing", "failed", True, None, {}),
        )
        directories += (failed,)
    return make_source_workset(context or fixture_context(), "2026Q4", "fixture-discovery",
                               tuple(members), directories, date(2026, 10, 1))


def fixture_snapshot(source: "Source", body: bytes) -> "Snapshot":
    import hashlib
    from sec_edgar_ingest.models import Snapshot, QUARTERLY_ENVELOPE_VERSION, DAILY_ENVELOPE_VERSION
    digest = hashlib.sha256(body).hexdigest()
    envelope = QUARTERLY_ENVELOPE_VERSION if source.kind == "quarterly" else DAILY_ENVELOPE_VERSION
    return Snapshot(source.source_id, digest,
                    f"raw/sec/indexes/kind={source.kind}/period={source.period}/sha256={digest}/master.{source.representation}",
                    len(body), datetime(2026, 10, 6, tzinfo=timezone.utc), {}, source.representation, envelope)


def exception_texts(type_name: str) -> tuple[tuple[str, str], ...]:
    """Empty, multi-line and already-safe exception text, each with the one line a structured Error must record."""
    return (("", type_name), ("a\nb", "a b"), ("fixture outage", "fixture outage"))


class Faults:
    """One-shot observers interrupt the real durable transition at a named boundary."""
    def __init__(self):
        self._actions = {}

    def at(self, point: str, action: Callable[[], None]) -> None:
        self._actions[point] = action

    def hit(self, point: str) -> None:
        self(point)

    def __call__(self, point: str) -> None:
        action = self._actions.pop(point, None)
        if action is not None:
            action()


class FixtureClock:
    def __init__(self):
        self.instant = datetime(2026, 10, 6, tzinfo=timezone.utc)
        self.elapsed = 0.0

    def now(self) -> datetime:
        return self.instant

    def monotonic(self) -> float:
        return self.elapsed

    def advance(self, seconds: float) -> None:
        self.instant += timedelta(seconds=seconds)
        self.elapsed += seconds


def store_bundle(root: Path, *, observer: "BoundaryObserver | None" = None, clock=None) -> tuple["StateStore", "ObjectStore", "LeaseStore"]:
    from sec_edgar_ingest.storage.local import LocalStateStore, LocalObjectStore, LocalLeaseStore
    return (LocalStateStore(root, observer=observer), LocalObjectStore(root, observer=observer),
            LocalLeaseStore(root, observer=observer, clock=clock))


# Task 4 controls drive real coordinators/stores; they own no alternate scheduling state.
def fixture_clock():
    from sec_edgar_ingest.coordination import ManualClock
    return ManualClock(datetime(2026, 10, 6, tzinfo=timezone.utc))


class ControlledSender:
    """Record actual controlled transport starts; returning a receipt proves this send drained."""
    def __init__(self, root, clock, *, on_send=None, status=200):
        self.root, self.clock, self.on_send, self.status = Path(root), clock, on_send, status
        self.starts, self.ends, self.events = [], [], []
        self.active = self.maximum_active = 0
        self.cancellations = []

    def send(self, url, context, permit, *, cancellation):
        import hashlib
        import uuid
        from sec_edgar_ingest.models import BodyReceipt, Error
        from sec_edgar_ingest.storage.contracts import OwnershipLost
        if cancellation.is_set() or self.clock.monotonic() >= permit.start_before_mono:
            raise OwnershipLost("controlled socket refuses cancelled/late dispatch")
        instant = self.clock.now()
        self.starts.append((permit.owner_id, instant))
        self.events.append({"event": "request-start", "at": instant.isoformat(), "epoch": permit.epoch,
                            "owner": permit.owner_id, "request_id": permit.request_id})
        self.cancellations.append(cancellation)
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            if self.on_send is not None:
                self.on_send(cancellation, permit)
        finally:
            self.active -= 1
            end = self.clock.now()
            self.ends.append((permit.owner_id, end))
            self.events.append({"event": "request-end", "at": end.isoformat(), "epoch": permit.epoch,
                                "owner": permit.owner_id, "request_id": permit.request_id})
        path = self.root / ("receipt-"+uuid.uuid4().hex)
        body = b"bounded offline partial" if cancellation.is_set() else b"bounded offline response"
        path.write_bytes(body)
        error = Error("cancelled", "controlled exchange drained after cancellation", True, None, {}) if cancellation.is_set() else None
        return BodyReceipt(url, self.status, {}, path, self.clock.now(), len(body), hashlib.sha256(body).hexdigest(),
                           error is None, error)


class CoordinationHarness:
    def __init__(self, root, clock):
        self.root, self.clock = Path(root), clock
        self.coordinators, self.turns, self.contexts, self.leases, self.faults, self.permits = {}, {}, {}, {}, {}, {}
        self.starts, self.events, self.active = [], [], set()
        self.maximum_active = 0

    def start(self, owner, priority):
        from sec_edgar_ingest.coordination import Coordinator
        faults = Faults()
        state, _, leases = store_bundle(self.root, clock=self.clock, observer=faults)
        self.faults[owner], self.leases[owner] = faults, leases
        coordinator = Coordinator(fixture_settings(root=self.root), state, leases, self.clock)
        coordinator.observer = self.events.append
        self.coordinators[owner] = coordinator
        context = coordinator.turn(owner, priority, self.clock.now()+timedelta(seconds=3600))
        self.contexts[owner] = context
        self.turns[owner] = context.__enter__()

    def reserve(self, owner):
        permit = self.turns[owner].reserve(owner+"-request")
        self.permits[owner] = permit
        self.dispatch(owner, permit)
        return permit

    def hold_request(self, owner):
        return self.reserve(owner)

    def dispatch(self, owner, permit):
        self.turns[owner].assert_current(permit)
        if self.clock.monotonic() >= permit.start_before_mono:
            raise AssertionError("harness socket would dispatch late")
        self.permits[owner] = permit
        self.starts.append((owner, self.clock.now()))
        self.events.append({"event": "request-start", "owner": owner, "epoch": permit.epoch,
                            "at": self.clock.now().isoformat()})
        self.active.add(owner)
        self.maximum_active = max(self.maximum_active, len(self.active))

    def expire_owner(self, owner):
        until = self.turns[owner].handle.ownership_until_upper
        context = self.contexts.pop(owner)
        context.__exit__(RuntimeError, RuntimeError("fixture parent abandoned the bounded sender"), None)
        self.clock.advance(max(0, (until-self.clock.now()).total_seconds()))
        if not self.turns[owner].cancelled.is_set():
            raise AssertionError("expired ownership did not cancel the real turn")

    def finish_request(self, owner):
        from sec_edgar_ingest.storage.contracts import OwnershipLost
        self.active.discard(owner)
        self.events.append({"event": "request-end", "owner": owner, "epoch": self.permits[owner].epoch,
                            "at": self.clock.now().isoformat()})
        try:
            self.turns[owner].complete(self.permits[owner], drained=True)
        except OwnershipLost:
            pass
        context = self.contexts.pop(owner, None)
        if context is not None:
            context.__exit__(None, None, None)

    def acquire_successor(self, owner):
        self.start(owner, "daily")

    def close(self):
        if hasattr(self, "trace_name"):
            retain_coordination_trace(self.trace_name, self.events)
        for context in tuple(self.contexts.values()):
            context.__exit__(RuntimeError, RuntimeError("fixture cleanup retains guard"), None)
        self.contexts.clear()
        for coordinator in self.coordinators.values():
            coordinator.store.close()
        for leases in self.leases.values():
            leases.close()


def coordination_harness(root: Path, *, clock):
    return CoordinationHarness(root, clock)


def retain_coordination_trace(name, events):
    import os
    destination = os.environ.get("SEC_EDGAR_TASK4_TRACE_DIR")
    if destination:
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(json.dumps(events, indent=2, sort_keys=True)+"\n")


class ProcessClock:
    """Shared logical time moves only when every exchange process is parked at a barrier."""
    def __init__(self, value, condition, recorder=None):
        self.value, self.condition, self.recorder = value, condition, recorder

    def now(self):
        return datetime(2026, 10, 6, tzinfo=timezone.utc)+timedelta(seconds=self.monotonic())

    def monotonic(self):
        with self.condition:
            return self.value.value

    def sleep(self, seconds):
        target = self.monotonic()+seconds
        self.recorder.emit("clock-wait", target=target)
        with self.condition:
            if not self.condition.wait_for(lambda: self.value.value >= target, timeout=10):
                raise TimeoutError("parent did not advance shared logical clock")
        self.recorder.emit("clock-awake")

    def subscribe(self, callback):
        import threading
        stopped = threading.Event()
        def monitor():
            observed = self.monotonic()
            while not stopped.is_set():
                with self.condition:
                    changed = self.condition.wait_for(lambda: stopped.is_set() or self.value.value != observed, timeout=10)
                    observed = self.value.value
                if changed and not stopped.is_set():
                    callback()
        thread = threading.Thread(target=monitor, name="fixture-logical-renewal", daemon=True)
        thread.start()
        def unsubscribe():
            stopped.set()
            with self.condition:
                self.condition.notify_all()
            thread.join(2)
        return unsubscribe


class ProcessRecorder:
    def __init__(self, worker, clock, queue, lock, sequence):
        self.worker, self.clock, self.queue, self.lock, self.sequence = worker, clock, queue, lock, sequence

    def emit(self, event, **details):
        import os
        import time
        with self.lock:
            self.sequence.value += 1
            self.queue.put({"sequence": self.sequence.value, "event": event, "worker": self.worker,
                            "pid": os.getpid(), "logical_at": self.clock.now().isoformat(),
                            "logical_mono": self.clock.monotonic(), "real_monotonic_ns": time.monotonic_ns(), **details})

    def observe(self, event):
        details = dict(event)
        kind = details.pop("event")
        self.emit(kind, **details)


class ProcessSender:
    def __init__(self, root, clock, coordinator, recorder, status):
        self.root, self.clock, self.coordinator, self.recorder, self.status = root, clock, coordinator, recorder, status

    def send(self, url, context, permit, *, cancellation):
        import hashlib
        from sec_edgar_ingest.models import BodyReceipt
        from sec_edgar_ingest.storage.contracts import OwnershipLost
        if cancellation.is_set() or self.clock.monotonic() >= permit.start_before_mono:
            raise OwnershipLost("process controlled socket refuses stale permit")
        turn = self.coordinator._active
        row = self.coordinator.leases.read_journal(turn.handle)
        if row.value["owner_id"] != permit.owner_id or row.value["epoch"] != permit.epoch:
            raise OwnershipLost("process transport observes a replaced sentinel epoch")
        self.recorder.emit("socket-start", owner=permit.owner_id, epoch=permit.epoch, request_id=permit.request_id,
                           journal_epoch=row.value["epoch"], journal_owner=row.value["owner_id"],
                           lease_id=turn.handle.lease_id, start_before_mono=permit.start_before_mono,
                           deadline_mono=permit.deadline_mono, cancelled=cancellation.is_set(), status=self.status)
        if self.status == 503:
            self.coordinator.defer_until(self.clock.now()+timedelta(seconds=2))
        self.clock.sleep(0.1)
        self.recorder.emit("socket-end", owner=permit.owner_id, epoch=permit.epoch, request_id=permit.request_id)
        if cancellation.is_set():
            raise OwnershipLost("process controlled exchange unexpectedly lost ownership")
        body = b"bounded independent process response"
        path = self.root / ("process-receipt-"+permit.request_id)
        path.write_bytes(body)
        return BodyReceipt(url, self.status, {"Retry-After": "2"} if self.status == 503 else {}, path,
                           self.clock.now(), len(body), hashlib.sha256(body).hexdigest(), True, None)


def _exchange_process(root, worker, value, condition, queue, lock, sequence, begin):
    from dataclasses import replace
    import traceback
    from sec_edgar_ingest.coordination import Coordinator
    root = Path(root)
    clock = ProcessClock(value, condition)
    recorder = ProcessRecorder(worker, clock, queue, lock, sequence)
    clock.recorder = recorder
    state = leases = None
    try:
        state, _, leases = store_bundle(root, clock=clock)
        settings = fixture_settings(root=root)
        coordinator = Coordinator(settings, state, leases, clock)
        coordinator.observer = recorder.observe
        recorder.emit("ready")
        if not begin.wait(10):
            raise TimeoutError("parent did not release process launch barrier")
        exchanges = 2 if worker == "backfill" else 1
        for ordinal in range(exchanges):
            context = replace(fixture_context(priority=worker, settings=settings), execution_id=worker, attempt_id=f"{worker}-{ordinal}")
            sender = ProcessSender(root, clock, coordinator, recorder, 503 if worker == "backfill" and ordinal == 0 else 200)
            receipt = coordinator.exchange(context, "https://www.sec.gov/Archives/edgar/full-index/2015/QTR1/index.json", sender)
            if not receipt.complete:
                raise AssertionError(receipt.error)
            recorder.emit("exchange-return", attempt=ordinal, status=receipt.status)
    except BaseException:
        recorder.emit("process-error", traceback=traceback.format_exc())
    finally:
        if state is not None:
            state.close()
        if leases is not None:
            leases.close()
        recorder.emit("done")


def exchange_process_trace(root):
    import multiprocessing
    context = multiprocessing.get_context("spawn")
    condition, value = context.Condition(), context.Value("d", 0)
    queue, lock, sequence = context.Queue(), context.Lock(), context.Value("i", 0)
    names = ("backfill", "daily", "reconciliation")
    begins = {name: context.Event() for name in names}
    processes = [context.Process(target=_exchange_process, args=(str(root), name, value, condition, queue, lock, sequence, begins[name])) for name in names]
    records, ready, done, waiting = [], set(), set(), {}
    states = {name: "not-started" for name in names}
    contenders_started = False
    try:
        for process in processes:
            process.start()
        while len(ready) < 3:
            event = queue.get(timeout=10)
            records.append(event)
            if event["event"] == "process-error":
                raise AssertionError(event["traceback"])
            if event["event"] == "ready":
                ready.add(event["worker"])
        begins["backfill"].set()
        states["backfill"] = "running"
        steps = 0
        while len(done) < 3:
            event = queue.get(timeout=10)
            records.append(event)
            worker, kind = event["worker"], event["event"]
            if kind == "process-error":
                raise AssertionError(event["traceback"])
            if kind == "socket-start" and worker == "backfill" and not contenders_started:
                for contender in ("daily", "reconciliation"):
                    states[contender] = "running"
                    begins[contender].set()
                contenders_started = True
            if kind == "clock-wait":
                waiting[worker], states[worker] = event["target"], "waiting"
            elif kind == "clock-awake":
                waiting.pop(worker, None)
                states[worker] = "running"
            elif kind == "done":
                done.add(worker)
                waiting.pop(worker, None)
                states[worker] = "done"
            if contenders_started and waiting and all(state in ("waiting", "done") for state in states.values()):
                target = min(waiting.values())
                for name, instant in tuple(waiting.items()):
                    if instant <= target:
                        states[name] = "waking"
                with condition:
                    value.value = max(value.value, target)
                    condition.notify_all()
                steps += 1
                if steps > 1000:
                    raise AssertionError("logical process barriers did not make bounded progress")
        for process in processes:
            process.join(10)
            if process.exitcode != 0:
                raise AssertionError(f"independent exchange process exited {process.exitcode}")
        return sorted(records, key=lambda event: event["sequence"])
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(10)
        queue.close()
        queue.join_thread()



def cancellation_child(cancellation, ready, returned):
    import os
    ready.set()
    returned.put({"pid": os.getpid(), "cancelled": cancellation.wait(5)})


def _constructor_process(root, begin, queue):
    import os
    import time
    import traceback
    state = leases = None
    queue.put({"event": "ready", "pid": os.getpid(), "real_monotonic_ns": time.monotonic_ns()})
    try:
        if not begin.wait(10):
            raise TimeoutError("constructor launch barrier did not open")
        state, _, leases = store_bundle(Path(root), clock=FixtureClock())
        state.insert("QueueTicket", "startup-"+str(os.getpid()), {"pid": os.getpid()})
        queue.put({"event": "constructed", "pid": os.getpid(), "real_monotonic_ns": time.monotonic_ns()})
    except BaseException:
        queue.put({"event": "constructor-error", "pid": os.getpid(), "traceback": traceback.format_exc()})
    finally:
        if state is not None:
            state.close()
        if leases is not None:
            leases.close()


def constructor_process_probe(root):
    import multiprocessing
    context = multiprocessing.get_context("spawn")
    begin, queue = context.Event(), context.Queue()
    processes = [context.Process(target=_constructor_process, args=(str(root), begin, queue)) for _ in range(3)]
    records = []
    try:
        for process in processes:
            process.start()
        for _ in processes:
            event = queue.get(timeout=10)
            records.append(event)
            if event["event"] != "ready":
                raise AssertionError(event)
        begin.set()
        for _ in processes:
            event = queue.get(timeout=10)
            records.append(event)
            if event["event"] != "constructed":
                raise AssertionError(event)
        for process in processes:
            process.join(10)
            if process.exitcode != 0:
                raise AssertionError(f"constructor process exited {process.exitcode}")
        return records
    finally:
        retain_coordination_trace("initialized-root-constructor-probe.json", records)
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(10)
        queue.close()
        queue.join_thread()


# Task 5 controls retain entity bytes; ZIP fixtures are synthetic, never SEC receipts.
def zip_bytes(body: bytes) -> bytes:
    import io
    import zipfile
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        member = zipfile.ZipInfo("master.idx", date_time=(2015, 1, 1, 0, 0, 0))
        member.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(member, body)
    return stream.getvalue()


def body_receipt(root, body, *, status=200, headers=None, complete=True, error=None):
    import hashlib
    import uuid
    from sec_edgar_ingest.models import BodyReceipt
    path = Path(root) / ("entity-"+uuid.uuid4().hex)
    path.write_bytes(body)
    return BodyReceipt(fixture_source().canonical_url, status, headers or {}, path,
                       fixture_context().started_at, len(body), hashlib.sha256(body).hexdigest(), complete, error)


class DownloadHarness:
    def __init__(self, responses, *, settings=None, context=None, root=None, clock=None):
        import tempfile
        from sec_edgar_ingest.coordination import Coordinator
        from sec_edgar_ingest.download import RequestClient, ResponseSpec, ScriptedSender
        from sec_edgar_ingest.state import AcquisitionState
        self.directory = tempfile.TemporaryDirectory() if root is None else None
        self.root = Path(self.directory.name) if root is None else Path(root)
        self.clock = clock or fixture_clock()
        self.settings = settings or fixture_settings(root=self.root)
        try:
            if self.settings.storage.root != str(self.root.resolve()):
                raise ValueError('download fixture settings root differs from the actual store root')
            self.context = context or fixture_context(settings=self.settings)
        except ValueError:
            if self.directory is not None:
                self.directory.cleanup()
            raise
        self.store, self.objects, self.leases = store_bundle(self.root, clock=self.clock)
        self.state = AcquisitionState(self.store, clock=self.clock)
        self.coordinator = Coordinator(self.settings, self.store, self.leases, self.clock)
        self.events = []
        self.coordinator.observer = self.events.append
        specs = [item if isinstance(item, ResponseSpec) else ResponseSpec(*item) for item in responses]
        self.sender = ScriptedSender(specs)
        self.sender.clock = self.clock
        self.client = RequestClient(self.settings, self.coordinator, self.sender, self.state, self.clock)
        self.client.jitter = lambda: 1.0

    @property
    def context(self):
        return self._context

    @context.setter
    def context(self, context):
        from sec_edgar_ingest.config import pin_context
        if (context.config_sha256 != self.settings.config_sha256
                or context.to_mapping()['effective_config'] != self.settings.to_mapping()
                or context.pinned_on is None
                or pin_context(self.settings, context, context.pinned_on)[0] != context):
            raise ValueError('download fixture context differs from the actual store settings')
        self._context = context

    def fetch(self, source):
        return self.client.fetch(source.canonical_url, self.context, source)

    def fetch_response_only(self, url=None):
        return self.client.fetch(url or "https://www.sec.gov/Archives/edgar/full-index/2015/QTR1/index.json", self.context)

    @property
    def starts(self):
        return self.sender.starts

    @property
    def attempt_count(self):
        return len(self.starts)

    @property
    def maximum_active(self):
        return self.sender.maximum_active

    def close(self):
        for row in self.store.scan("TransportAttempt", {}):
            value = row.to_mapping()["value"]
            if value["receipt"] is not None and value["outcome"] != "received":
                from sec_edgar_ingest.models import BodyReceipt
                receipt = BodyReceipt.from_mapping(value["receipt"])
                if receipt.temporary_path.parent != Path(self.sender.directory.name):
                    continue  # A shared ledger includes sibling harness spools with separate cleanup owners.
                code = value["error"]["code"] if value.get("error") else value["outcome"]
                retain_download_evidence("ledger-"+value["request_id"], receipt, code)
        self.store.close()
        self.leases.close()
        self.sender.close()
        if self.directory is not None:
            self.directory.cleanup()


def download_harness(responses):
    return DownloadHarness(responses)


def retain_download_evidence(name, receipt, code):
    import os
    import shutil
    destination = os.environ.get("SEC_EDGAR_TASK5_TRACE_DIR")
    if destination:
        target = Path(destination) / "invalid"
        target.mkdir(parents=True, exist_ok=True)
        path = target / (name+".body")
        shutil.copyfile(receipt.temporary_path, path)
        path.with_suffix(".json").write_text(json.dumps({"reason": code, "receipt": receipt.to_mapping()}, indent=2, sort_keys=True)+"\n")


class LoopbackServer:
    """Exactly one explicitly fixture-only HTTP peer records accepted sockets and closure."""
    def __init__(self, body=b"fixture prefix", *, mode="complete", status=200, headers=None, drip_seconds=0.02):
        import socket
        import threading
        import time
        self.body, self.mode, self.status, self.headers = body, mode, status, dict(headers or {})
        self.drip_seconds = drip_seconds
        self.events, self.requests, self.sent = [], [], 0
        self.connected, self.prefix_sent, self.closed, self.stopped = (threading.Event() for _ in range(4))
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(2)
        self.socket.settimeout(0.05)
        self.origin = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.url = self.origin+"/fixture"
        self._network_origin = selected_origin(self.origin)
        self._network_origin.__enter__()
        self.thread = threading.Thread(target=self._serve, name="bounded-loopback-fixture", daemon=True)
        self.thread.start()

    def record(self, event, **details):
        import time
        self.events.append({"event": event, "monotonic": time.monotonic(), **details})

    def _serve(self):
        import select
        import socket
        try:
            while not self.stopped.is_set():
                try:
                    peer, _ = self.socket.accept()
                    break
                except socket.timeout:
                    continue
            else:
                return
            with peer:
                self.record("socket-accepted")
                self.connected.set()
                peer.settimeout(1)
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = peer.recv(4096)
                    if not chunk:
                        return
                    request += chunk
                self.requests.append(request.decode("ascii"))
                self.record("request-received")
                headers = {"Content-Length": str(len(self.body)), "Connection": "close", **self.headers}
                if self.mode == "trickle":
                    headers["Content-Length"] = "1000000"
                elif self.mode == "truncated":
                    headers["Content-Length"] = str(len(self.body)+10)
                elif self.mode == "unadvertised":
                    headers.pop("Content-Length")
                response = (f"HTTP/1.1 {self.status} Fixture\r\n"+"".join(f"{key}: {value}\r\n" for key,value in headers.items())+"\r\n").encode("ascii")
                if self.mode == "headers":
                    for byte in response:
                        peer.sendall(bytes([byte]))
                        if self.stopped.wait(self.drip_seconds):
                            return
                elif self.mode == "blocked-headers":
                    peer.sendall(b"HTTP/1.1 200 Fixture\r\nX-Fixture: ")
                    self.record("blocked-headers-sent")
                else:
                    peer.sendall(response)
                    self.record("headers-sent")
                    if self.mode == "trickle":
                        while not self.stopped.is_set():
                            if select.select([peer], [], [], 0)[0] and peer.recv(1) == b"":
                                return
                            peer.sendall(self.body)
                            self.sent += len(self.body)
                            self.record("entity-sent", byte_count=self.sent)
                            self.prefix_sent.set()
                            if self.stopped.wait(0.02):
                                return
                    else:
                        peer.sendall(self.body)
                        self.sent = len(self.body)
                        self.record("entity-sent", byte_count=self.sent)
                        self.prefix_sent.set()
                        if self.mode == "truncated":
                            return
                while not self.stopped.is_set():
                    if select.select([peer], [], [], 0.05)[0] and peer.recv(1) == b"":
                        return
        except (BrokenPipeError, ConnectionResetError):
            self.record("peer-disconnected")
        except OSError as error:
            if not self.stopped.is_set():
                self.record("server-error", message=str(error))
        finally:
            self.record("socket-closed")
            self.closed.set()

    def close(self):
        self.stopped.set()
        self.socket.close()
        try:
            self.thread.join(2)
            if self.thread.is_alive():
                raise AssertionError("fixture server did not drain")
        finally:
            self._network_origin.__exit__(None, None, None)


def loopback_sender(settings, clock, origin, *, target=None, spool=None):
    from sec_edgar_ingest.download import BoundedSender
    from urllib.parse import urlsplit
    class FixtureLoopbackSender(BoundedSender):
        def _validated_origin(self, url):
            if self.settings.acquisition.mode != "fixture":
                raise ValueError("loopback exception is expressly fixture-only")
            parsed = urlsplit(url)
            if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password or parsed.fragment or urlsplit(origin).netloc != parsed.netloc:
                raise ValueError("fixture sender can contact only its one selected loopback origin")
            return origin
        def _child_target(self):
            from functools import partial
            from network_guard import guarded_transport_child, checkout_policy
            return partial(guarded_transport_child, target=target or super()._child_target(),
                           origin=origin, policy=checkout_policy())
        def _spool_directory(self):
            if spool is None:
                return super()._spool_directory()
            root = Path(spool)
            root.mkdir(parents=True, exist_ok=True)
            return root
    return FixtureLoopbackSender(settings, clock)


def real_permit(clock, seconds=0.4, *, start_seconds=1/3):
    from sec_edgar_ingest.models import Permit
    now, mono = clock.now(), clock.monotonic()
    start = min(start_seconds, seconds)
    return Permit("fixture-real-owner", 1, "fixture-real-request", now+timedelta(seconds=start),
                  now+timedelta(seconds=seconds), now+timedelta(seconds=seconds+2),
                  mono+start, mono+seconds, now+timedelta(seconds=start+1/3))


def real_context(clock, settings):
    from dataclasses import replace
    now = clock.now()
    return replace(fixture_context(settings=settings), started_at=now, deadline=now+timedelta(seconds=10),
                   pinned_on=now.date(), config_sha256=settings.config_sha256, effective_config=settings.to_mapping())


def timer_failure_child(transport, cancellation, channel):
    import sec_edgar_ingest.download as download
    def fail_timer(_):
        raise download.HardTimerUnavailable("fixture OS timer installation failed")
    download.arm_child_deadline = fail_timer
    download._child_exchange(transport, cancellation, channel)


def slow_spawn_timer_failure_child(transport, cancellation, channel):
    import time
    time.sleep(SLOW_SPAWN_SECONDS)
    timer_failure_child(transport, cancellation, channel)


def slow_spawn_child_exchange(transport, cancellation, channel):
    import time
    import sec_edgar_ingest.download as download
    time.sleep(SLOW_SPAWN_SECONDS)
    download._child_exchange(transport, cancellation, channel)


def stale_start_child(transport, cancellation, channel):
    import time
    import sec_edgar_ingest.download as download
    time.sleep(max(0, transport.start_before_mono-time.monotonic()+0.01))
    download._child_exchange(transport, cancellation, channel)


def ipc_loss_child(transport, cancellation, channel):
    import sec_edgar_ingest.download as download
    channel.close()
    download._child_exchange(transport, cancellation, channel)


def crash_supervisor(root, url, origin, cancellation):
    import os
    from sec_edgar_ingest.coordination import Clock, Coordinator
    import gc
    clock = Clock()
    settings = spawn_tolerant_settings(root=Path(root) / "state", coordination={"lease_seconds": 2, "renew_every_seconds": 1})
    store, _, leases = store_bundle(Path(root) / "state", clock=clock)
    coordinator = Coordinator(settings, store, leases, clock)
    sender = loopback_sender(settings, clock, origin, spool=Path(root) / "sender")
    context = real_context(clock, settings)
    with coordinator.turn("crashing-fixture-supervisor", "backfill", context.deadline) as turn:
        # The surviving fixture parent owns semaphore cleanup even when this supervisor is killed.
        turn.cancelled = cancellation
        gc.collect()
        permit = turn.reserve("crashing-fixture-request")
        turn.assert_current(permit)
        sender.send(url, context, permit, cancellation=cancellation)
        turn.complete(permit, drained=True)
    os._exit(2)


def retain_process_evidence(name, spool, server, extra=None):
    import os
    import shutil
    destination = os.environ.get("SEC_EDGAR_TASK5_TRACE_DIR")
    if destination:
        target = Path(destination) / "process" / name
        target.mkdir(parents=True, exist_ok=True)
        if spool is not None and Path(spool).exists():
            shutil.copytree(spool, target / "sender", dirs_exist_ok=True)
        (target / "server.json").write_text(json.dumps({"events": server.events, "sent_bytes": server.sent, "requests": server.requests, "extra": extra or {}}, indent=2, sort_keys=True)+"\n")


def malformed_metadata_child(transport, cancellation, channel):
    import sec_edgar_ingest.download as download
    download._child_exchange(transport, cancellation, channel)
    (Path(transport.spool)/"receipt.json").write_text("[]")


def unexpected_failure_child(transport, cancellation, channel):
    import sec_edgar_ingest.download as download
    def fail_exchange(*args):
        raise RuntimeError("fixture unexpected transport exception")
    download._read_http_entity = fail_exchange
    download._child_exchange(transport, cancellation, channel)


def stale_preparation_child(transport, cancellation, channel):
    import time
    import requests
    import sec_edgar_ingest.download as download
    prepare = requests.Session.prepare_request
    def delayed_prepare(session, request):
        prepared = prepare(session, request)
        time.sleep(max(0, transport.start_before_mono-time.monotonic()+0.01))
        return prepared
    requests.Session.prepare_request = delayed_prepare
    download._child_exchange(transport, cancellation, channel)


def delayed_adapter_child(transport, cancellation, channel):
    import time
    import requests
    import sec_edgar_ingest.download as download
    send = requests.adapters.HTTPAdapter.send
    def delayed_send(adapter, request, **kwargs):
        download._trace_transport(transport, "adapter-delay-begin")
        time.sleep(0.55)
        download._trace_transport(transport, "adapter-delay-end")
        return send(adapter, request, **kwargs)
    requests.adapters.HTTPAdapter.send = delayed_send
    download._child_exchange(transport, cancellation, channel)


# These JSON listings are synthetic offline fixtures, distinct from retained SEC evidence.
def listing_response(period: str, names: list[str], *, family: str = 'daily-index') -> "ResponseSpec":
    from sec_edgar_ingest.download import ResponseSpec
    if period in ('daily-index', 'full-index'):
        path = period+'/'
    elif 'Q' in period:
        year, quarter = period.split('Q')
        path = f'{family}/{year}/QTR{quarter}/'
    else:
        path = f'{family}/{period}/'
    items = [{'name': name.rstrip('/'), 'href': name, 'type': 'dir' if name.endswith('/') else 'file',
              'size': '', 'last-modified': 'synthetic fixture label'} for name in names]
    return ResponseSpec(200, json.dumps({'directory': {'name': path, 'parent-dir': '../', 'item': items}}).encode(),
                        {'Content-Type': 'application/json', 'X-Fixture': 'synthetic'})


def failed_response(status: int) -> "ResponseSpec":
    from sec_edgar_ingest.download import ResponseSpec
    return ResponseSpec(status, b'synthetic fixture HTTP failure', {})


class DiscoveryHarness:
    def __init__(self, root, responses):
        import tempfile
        from sec_edgar_ingest.coordination import Coordinator
        from sec_edgar_ingest.download import RequestClient, ScriptedSender
        from sec_edgar_ingest.state import AcquisitionState
        self.directory = tempfile.TemporaryDirectory(prefix='sec-discovery-') if root is None else None
        self.root = Path(self.directory.name) if root is None else Path(root)
        self.clock = fixture_clock()
        self.settings = fixture_settings(root=self.root, fixture={"allow_clock_override": True})
        self.store, self.objects, self.leases = store_bundle(self.root, clock=self.clock)
        self.state = AcquisitionState(self.store, clock=self.clock)
        self.coordinator = Coordinator(self.settings, self.store, self.leases, self.clock)
        self.responses = {key: list(value) for key, value in responses.items()}
        self.attempted_urls = []
        self.family = 'daily-index'
        harness = self
        class ListingSender(ScriptedSender):
            def send(self, url, context, permit, *, cancellation):
                harness.attempted_urls.append(url)
                key = harness.key(url)
                supplied = harness.responses.get(url, harness.responses.get(key))
                if supplied:
                    spec = supplied[0]
                    if (spec.status == 200 and spec.fault is None) or len(supplied) > 1:
                        supplied.pop(0)
                elif supplied is not None:
                    raise AssertionError('synthetic response sequence exhausted for '+url)
                elif key in ('daily-index', 'full-index'):
                    years = sorted({str(y) for y in range(2010, 2028)})
                    spec = listing_response(key, [year+'/' for year in years], family=key)
                elif len(key) == 4:
                    spec = listing_response(key, ['QTR1/', 'QTR2/', 'QTR3/', 'QTR4/'], family=url.split('/edgar/')[1].split('/')[0])
                else:
                    spec = listing_response(key, [], family=url.split('/edgar/')[1].split('/')[0])
                self.responses = [spec]
                return super().send(url, context, permit, cancellation=cancellation)
        self.sender = ListingSender([])
        self.sender.clock = self.clock
        self.client = RequestClient(self.settings, self.coordinator, self.sender, self.state, self.clock)
        self.client.jitter = lambda: 0.0
        self.closed = False
        self.invocations = 0

    @staticmethod
    def key(url):
        path = url.split('/edgar/')[1].split('/')[:-1]
        return path[0] if len(path) == 1 else path[1] if len(path) == 2 else path[1]+'Q'+path[2][3:]

    def url(self, key):
        prefix = 'https://www.sec.gov/Archives/edgar/'
        if key in ('daily-index', 'full-index'):
            return prefix+key+'/index.json'
        path = key.replace('Q', '/QTR')
        return prefix+self.family+'/'+path+'/index.json'

    @property
    def requested_quarters(self):
        return tuple(sorted({self.key(url) for url in self.attempted_urls if 'QTR' in url}))

    @property
    def boundary(self):
        return self.state.daily_boundary()

    def seed_boundary(self, day: date) -> None:
        self.store.insert('DiscoveryBoundary', 'daily', {'day': day.isoformat(), 'gaps': {}})

    def add_pending(self, source: "Source") -> None:
        self.state.observe(source, self.clock.now(), 'available')

    @staticmethod
    def workset_path(workset):
        return f'worksets/sec/source/sha256={workset.workset_id}/workset.json'

    def run(self, mode: str, today: date, discovery_id: str, *, refresh: bool = False) -> "SourceWorkset":
        from dataclasses import replace
        from sec_edgar_ingest.discovery import discover
        from sec_edgar_ingest.config import pin_context
        self.family = 'daily-index' if mode == 'daily' else 'full-index'
        self.invocations += 1
        context = replace(fixture_context(command='discover', priority='daily' if mode == 'daily' else 'backfill', settings=self.settings),
                          attempt_id=f'discover-{self.invocations}', execution_id=f'discover-{today}',
                          config_sha256=self.settings.config_sha256, pinned_on=None)
        context, _ = pin_context(self.settings, context, today)
        return discover(self.settings, context, mode, discovery_id, self.client, self.state, self.objects, today, refresh)

    def run_single_directory(self, period: str) -> "SourceWorkset":
        year, quarter = period.split('Q')
        day = date(int(year), (int(quarter)-1)*3+1, 1)
        self.settings = fixture_settings(root=self.root, backfill={'start_quarter': period, 'end_quarter': 'open'}, daily={'start_date': day.isoformat()}, fixture={'allow_clock_override': True})
        # The explicit fixture clock override pins this selected historical test quarter.
        from dataclasses import replace
        from sec_edgar_ingest.config import pin_context
        from sec_edgar_ingest.discovery import discover
        self.coordinator.settings = self.settings
        self.client.settings = self.settings
        context = replace(fixture_context('discover', 'daily', settings=self.settings), config_sha256=self.settings.config_sha256, pinned_on=None)
        context, _ = pin_context(self.settings, context, day)
        self.seed_boundary(day)
        # Daily always includes preceding overlap; synthesize the other leaf as valid empty.
        return discover(self.settings, context, 'daily', 'single-'+period, self.client, self.state, self.objects, day)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.store.close()
        self.leases.close()
        self.sender.close()
        if self.directory is not None:
            self.directory.cleanup()


def discovery_harness(root: Path | None, responses: dict[str, list["ResponseSpec"]]) -> DiscoveryHarness:
    return DiscoveryHarness(root, responses)


# Collection uses the same local stores, audited client and fixed coordinator as discovery.
def valid_idx_response(kind: str, company: str = 'Fixture Co') -> "ResponseSpec":
    from sec_edgar_ingest.download import ResponseSpec
    ending = '\r\n' if kind == 'quarterly' else '\n'
    filename = 'Filename' if kind == 'quarterly' else 'File Name'
    text = ending.join(('Synthetic SEC acquisition envelope',
        f'CIK|Company Name|Form Type|Date Filed|{filename}', '-' * 70,
        f'123456|{company}|10-K|2026-10-01|edgar/data/123456/fixture.txt', ''))
    body = text.encode('ascii')
    if kind == 'quarterly':
        body = zip_bytes(body)
    return ResponseSpec(200, body, {'Content-Length': str(len(body)),
        'Content-Type': 'application/zip' if kind == 'quarterly' else 'text/plain',
        'ETag': '"synthetic-'+company+'"', 'X-Fixture': 'synthetic'})


class CollectionCrash(BaseException):
    pass


class CollectionHarness:
    def __init__(self, root: Path, responses: Sequence["ResponseSpec"], *, clock=None):
        from sec_edgar_ingest.coordination import Coordinator
        from sec_edgar_ingest.download import RequestClient, ScriptedSender
        from sec_edgar_ingest.state import AcquisitionState
        self.root = Path(root)
        self.clock = clock or fixture_clock()
        self.settings = fixture_settings(root=self.root)
        self.store, self.objects, self.leases = store_bundle(self.root, clock=self.clock)
        self.source_state = AcquisitionState(self.store, clock=self.clock)
        self.coordinator = Coordinator(self.settings, self.store, self.leases, self.clock)
        harness = self
        class CollectionSender(ScriptedSender):
            def send(self, url, context, permit, *, cancellation):
                harness.trace('fetch', url=url, context=context.to_mapping(), request_id=permit.request_id)
                if harness.forbid_fetch:
                    raise AssertionError('recovery must not call the sender')
                return super().send(url, context, permit, cancellation=cancellation)
        self.sender = CollectionSender(responses)
        self.sender.clock = self.clock
        self.client = RequestClient(self.settings, self.coordinator, self.sender, self.source_state, self.clock)
        self.client.jitter = lambda: 0.0
        self.faults = Faults()
        self.forbid_fetch = False
        self.context = fixture_context(settings=self.settings)
        self.invocations = 0
        self.closed = False

    def trace(self, event, **details):
        import os
        from sec_edgar_ingest.models import canonical_json
        path = self.root / 'collection-events.jsonl'
        with path.open('ab') as stream:
            stream.write(canonical_json({'event': event, 'pid': os.getpid(), **details}) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())

    @property
    def fetch_count(self):
        return len(tuple(self.store.scan('TransportAttempt', {})))

    @staticmethod
    def source_workset_path(workset):
        return f'worksets/sec/source/sha256={workset.workset_id}/workset.json'

    def collect(self, workset: "SourceWorkset") -> "CommandResult":
        from dataclasses import replace
        from sec_edgar_ingest.collection import collect
        from sec_edgar_ingest.worksets import encode_workset
        self.invocations += 1
        context = replace(self.context, attempt_id=f'collect-{self.invocations}',
                          execution_id=f'collection-{self.invocations}')
        self.objects.put_once(self.source_workset_path(workset), encode_workset(workset))
        result = collect(workset, context, self.settings, self.client, self.source_state, self.objects, self.faults)
        self.trace('result', result=result.to_mapping())
        return result

    def snapshot_workset(self, result: "CommandResult") -> "SnapshotWorkset":
        from sec_edgar_ingest.worksets import decode_snapshot_workset
        return decode_snapshot_workset(self.objects.read(result.snapshot_workset_ref))

    def fail_at(self, point: str) -> None:
        def fail():
            self.trace('injected_crash', point=point)
            raise CollectionCrash(point)
        self.faults.at(point, fail)

    def reopen(self) -> "CollectionHarness":
        remaining = list(self.sender.responses)
        invocations = self.invocations
        context, settings, clock = self.context, self.settings, self.clock
        self.close()
        resumed = CollectionHarness(self.root, remaining, clock=clock)
        resumed.context, resumed.settings = context, settings
        resumed.client.settings, resumed.coordinator.settings = settings, settings
        resumed.invocations = invocations
        resumed.forbid_fetch = self.forbid_fetch
        return resumed

    def install_newer_snapshot(self, source: "Source", body: bytes) -> "Snapshot":
        from dataclasses import replace
        from sec_edgar_ingest.collection import snapshot_for, stage_receipt
        from sec_edgar_ingest.validation import validate_envelope
        self.clock.advance(5)
        receipt = replace(body_receipt(self.root, body), url=source.canonical_url,
                          received_at=self.clock.now())
        self.source_state.observe(source, self.clock.now(), 'available')
        snapshot = snapshot_for(source, validate_envelope(source, receipt, self.settings))
        # This labelled identity belongs to the fixture install; it claims no HTTP exchange.
        temporary_ref = stage_receipt(self.objects, self.context, source, receipt,
                                       request_id='synthetic-fixture-install')
        self.objects.promote(temporary_ref, snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
        return self.source_state.remember_snapshot(snapshot)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.store.close()
        self.leases.close()
        self.sender.close()


def collection_harness(root: Path, responses: Sequence["ResponseSpec"]) -> CollectionHarness:
    return CollectionHarness(root, responses)


def retain_collection_proof(name, value):
    import os
    destination = os.environ.get('SEC_EDGAR_TASK7_TRACE_DIR')
    if destination:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        (target / (name+'.json')).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def collection_process_entry(root, point=None, *, raw_only=False, retry_prefix=False):
    import os
    from sec_edgar_ingest.collection import collect
    from sec_edgar_ingest.worksets import decode_source_workset, make_snapshot_workset
    root = Path(root)
    responses = [valid_idx_response('daily')]
    if retry_prefix:
        from sec_edgar_ingest.download import ResponseSpec
        responses.insert(0, ResponseSpec(200, b'retained retry prefix', {'X-Fixture': 'partial'}, 'read_timeout'))
    h = collection_harness(root, responses)
    workset = decode_source_workset((root / 'input-workset.json').read_bytes())
    h.forbid_fetch = raw_only
    if retry_prefix and raw_only:
        from dataclasses import replace
        h.context = replace(h.context, run_id='successor-run', execution_id='successor-execution',
                            attempt_id='successor-attempt')
    h.source_state.begin_attempt(h.context)
    if point:
        def terminate():
            import gc
            # Completed turns may form cycles; collect their transient semaphores before forced exit.
            gc.collect()
            from sec_edgar_ingest.collection import raw_path
            from sec_edgar_ingest.models import Source
            staged = [row.to_mapping()['value'] for row in h.store.scan('StagedReceipt', {})]
            snapshots = [row.to_mapping()['value'] for row in h.store.scan('Snapshot', {})]
            bindings = [row.to_mapping()['value'] for row in h.store.scan('Binding', {})]
            promotions = [row.to_mapping()['value'] for row in h.store.scan('PromotionReceipt', {})]
            raw = []
            for entry in staged:
                receipt = entry['receipt']
                path = raw_path(Source.from_mapping(entry['source']), receipt['sha256'])
                try:
                    h.objects.verify(path, receipt['sha256'], receipt['byte_count'])
                    raw.append({'path': path, 'body_hex': h.objects.read(path).hex(), 'verified': True})
                except FileNotFoundError:
                    raw.append({'path': path, 'verified': False})
            saved_workset = None
            if point in ('after_snapshot_workset_write', 'before_result_write'):
                pinned = tuple(h.source_state.snapshot(source.source_id,
                    h.source_state.binding(workset.workset_id, source.source_id).snapshot_sha256)
                    for source in workset.members)
                frozen = make_snapshot_workset(workset, pinned)
                path = f'worksets/sec/snapshot/sha256={frozen.workset_id}/workset.json'
                saved_workset = h.objects.read(path).decode()
            retry_evidence = []
            if retry_prefix:
                import shutil
                from sec_edgar_ingest.models import canonical_json
                for source in workset.members:
                    for row in h.source_state.request_history(h.context, source.canonical_url):
                        request = row.to_mapping()['value']
                        if request['error'] is None or request['receipt'] is None:
                            continue
                        path = f'quarantine/sec/{h.context.run_id}/{source.source_id}/{h.context.attempt_id}/{request["request_id"]}/body'
                        expected = canonical_json({'receipt': request['receipt'], 'error': request['error'],
                            'context': h.context.to_mapping(), 'source': source.to_mapping(),
                            'request_id': request['request_id'], 'body_path': path})
                        try:
                            h.objects.verify(path, request['receipt']['sha256'], request['receipt']['byte_count'])
                            retained_body = h.objects.read(path).hex()
                            sidecar = h.objects.read(path.rsplit('/', 1)[0]+'/receipt.json').decode()
                            verified = sidecar.encode() == expected
                        except FileNotFoundError:
                            retained_body = sidecar = None
                            verified = False
                        retry_evidence.append({'request': request, 'path': path, 'body_hex': retained_body,
                            'sidecar_bytes': sidecar, 'verified': verified,
                            'temporary_body_hex': Path(request['receipt']['temporary_path']).read_bytes().hex()})
                # Remove only this synthetic sender's temporary fixture spool after verified retention.
                if retry_evidence and all(entry['verified'] for entry in retry_evidence):
                    shutil.rmtree(h.sender.directory.name)
                for entry in retry_evidence:
                    entry['temporary_exists_after'] = Path(entry['request']['receipt']['temporary_path']).exists()
            h.trace('forced_exit', point=point, staged_receipts=staged, snapshots=snapshots,
                    bindings=bindings, promotions=promotions, raw=raw, retry_evidence=retry_evidence,
                    snapshot_workset_bytes=saved_workset, fetch_count=h.fetch_count)
            os._exit(73)
        h.faults.at(point, terminate)
    result = collect(workset, h.context, h.settings, h.client, h.source_state, h.objects, h.faults)
    h.trace('process_result', result=result.to_mapping())
    (root / 'final-result.json').write_text(json.dumps(result.to_mapping(), sort_keys=True))
    if result.snapshot_workset_ref:
        (root / 'final-snapshot-workset.json').write_bytes(h.objects.read(result.snapshot_workset_ref))
    h.close()


def run_collection_process(root, point=None, *, raw_only=False, retry_prefix=False):
    import os
    import subprocess
    import sys
    command = [sys.executable, '-c',
        'from support import collection_process_entry; import sys; '
        'collection_process_entry(sys.argv[1], None if sys.argv[2] == "none" else sys.argv[2], '
        'raw_only=sys.argv[3] == "yes", retry_prefix=sys.argv[4] == "yes")',
        str(root), point or 'none', 'yes' if raw_only else 'no', 'yes' if retry_prefix else 'no']
    completed = subprocess.run(command, capture_output=True, text=True, timeout=45,
                               env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent)})
    return {'command': command, 'exit_code': completed.returncode,
            'stdout': completed.stdout, 'stderr': completed.stderr}


class CollectionRaceStore:
    """Synchronize the internal absent read used by the real bind_once insert."""
    def __init__(self, store, barrier, trace):
        self.store, self.barrier, self.trace = store, barrier, trace
        self.binding_reads = 0

    def get(self, kind, key):
        row = self.store.get(kind, key)
        if kind == 'Binding':
            self.binding_reads += 1
            if row is None and self.binding_reads == 2:
                self.trace('bind_read_absent', key=key)
                self.barrier.wait(timeout=20)
            elif row is not None:
                self.trace('bind_read_winner', snapshot_sha256=row.value['snapshot_sha256'])
        return row

    def insert(self, kind, key, value):
        from sec_edgar_ingest.storage.contracts import AlreadyExists
        if kind != 'Binding':
            return self.store.insert(kind, key, value)
        self.trace('bind_insert_attempt', snapshot_sha256=value['snapshot_sha256'])
        try:
            row = self.store.insert(kind, key, value)
        except AlreadyExists:
            self.trace('bind_insert_conflict')
            raise
        self.trace('bind_insert_success', snapshot_sha256=value['snapshot_sha256'])
        return row

    def replace(self, kind, key, value, version):
        return self.store.replace(kind, key, value, version)

    def scan(self, kind, filters):
        return self.store.scan(kind, filters)


def collection_race_entry(root, company, staged_barrier, binding_barrier, output):
    import os
    from dataclasses import replace
    from sec_edgar_ingest.collection import collect
    from sec_edgar_ingest.worksets import decode_source_workset
    root = Path(root)
    h = collection_harness(root, [valid_idx_response('daily', company=company)])
    h.context = replace(h.context, execution_id='race-'+company, attempt_id='race-'+company)
    workset = decode_source_workset((root / 'input-workset.json').read_bytes())
    events = []
    def trace(event, **details):
        import time
        events.append({'event': event, 'pid': os.getpid(), 'monotonic_ns': time.monotonic_ns(),
                       'at': datetime.now(timezone.utc).isoformat(), **details})
    def await_staging():
        trace('receipt_checkpoint')
        staged_barrier.wait(timeout=20)
    h.faults.at('after_receipt_checkpoint', await_staging)
    h.source_state.store = CollectionRaceStore(h.store, binding_barrier, trace)
    try:
        result = collect(workset, h.context, h.settings, h.client, h.source_state, h.objects, h.faults)
        trace('adopted', snapshots=h.snapshot_workset(result).to_mapping()['snapshots'])
        output.put({'result': result.to_mapping(), 'events': events,
                    'candidate_sha256': __import__('hashlib').sha256(valid_idx_response('daily', company).body).hexdigest()})
    finally:
        h.close()


ACQUISITION_PACK = Path(__file__).parent / 'fixtures/acquisition/manifest.json'


def block_external_network():
    """Keep existing fixture call sites under the suite's exact-origin/auth guard."""
    _install_offline_guard()


def cli_process_entry():
    import sys
    import sec_edgar_ingest.cli as cli
    from sec_edgar_ingest.storage import open_stores
    block_external_network()
    def audited_open(*args, **kwargs):
        audit = Path.cwd() / 'constructions.json'
        count = json.loads(audit.read_text()) if audit.exists() else 0
        audit.write_text(json.dumps(count + 1))
        return open_stores(*args, **kwargs)
    cli.open_stores = audited_open
    raise SystemExit(cli.main(sys.argv[1:]))


class CliHarness:
    """Actual argument parser in independent Python processes, durable local stores."""
    def __init__(self, fixture, missing_user_agent=False):
        import tempfile
        self.temporary = tempfile.TemporaryDirectory(prefix='sec-cli-')
        self.root = Path(self.temporary.name)
        self.config_path = self.root / 'config.json'
        self.pack_path = self.root / 'manifest.json'
        config = local_config_mapping(root=self.root / '.fixture-state')
        config['backfill'] = {'start_quarter': '2015Q1', 'end_quarter': '2015Q1'}
        config['fixture'] = {'allow_clock_override': True, 'allow_deadline_override': True}
        config['http']['retry_base_seconds'] = 0.001
        config['http']['retry_cap_seconds'] = 0.001
        if missing_user_agent:
            del config['sec']['user_agent']
        self.config_path.write_text(json.dumps(config))
        manifest = json.loads(ACQUISITION_PACK.read_text())
        for responses in manifest['responses'].values():
            for response in responses:
                response['body_path'] = str(Path('bodies') / Path(response['body_path']).name)
        import shutil
        shutil.copytree(ACQUISITION_PACK.parent / 'bodies', self.root / 'bodies')
        self.fixture = fixture
        quarter = fixture_source().canonical_url
        quarter_listing = quarter.rsplit('/', 1)[0] + '/index.json'
        if fixture == 'failed-earlier-quarter':
            manifest['responses'][quarter_listing] = [self.response(404)]
        elif fixture == 'valid-empty':
            empty = listing_response('2015Q1', [], family='full-index')
            manifest['responses'][quarter_listing] = [self.response(200, empty.body)]
        elif fixture in ('pending', 'retry-exhausted', 'access-blocked', 'quarantined', 'ownership-lost', 'deferred'):
            spec = {'pending': (404, b''), 'retry-exhausted': (503, b'failure'),
                    'access-blocked': (403, b'access denied'), 'quarantined': (200, b'invalid index'),
                    'ownership-lost': (200, b'prefix'), 'deferred': (503, b'failure')}[fixture]
            response = self.response(*spec)
            if fixture == 'ownership-lost':
                response['fault'] = 'ownership_lost'
            if fixture == 'deferred':
                response['headers']['Retry-After'] = '9' * 400
            manifest['responses'][quarter] = [response] * (5 if fixture == 'retry-exhausted' else 1)
        self.pack_path.write_text(json.dumps(manifest))
        self.common = ['--config', str(self.config_path), '--fixture-pack', str(self.pack_path),
                       '--today', '2026-10-06',
                       '--deadline', '2099-01-01T00:00:00Z', '--run-id', 'cli-run']
        self.calls = []

    def response(self, status, body=b''):
        import hashlib
        digest = hashlib.sha256(body).hexdigest()
        path = self.root / 'bodies' / (digest + '.body')
        path.write_bytes(body)
        return {'status': status, 'headers': {}, 'body_path': 'bodies/' + path.name, 'body_sha256': digest}

    @property
    def external_client_constructions(self):
        path = self.root / 'constructions.json'
        return json.loads(path.read_text()) if path.exists() else 0

    @property
    def state_root(self):
        return self.root / '.fixture-state'

    def invoke(self, command, arguments, *, common=None):
        import os
        import subprocess
        import sys
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).parent), 'PYTHONDONTWRITEBYTECODE': '1'}
        argv = [sys.executable, '-c', 'from support import cli_process_entry; cli_process_entry()',
                command, *(self.common if common is None else common), *arguments]
        completed = subprocess.run(argv, cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
        self.calls.append({'argv': argv, 'exit': completed.returncode,
                           'stdout': completed.stdout, 'stderr': completed.stderr})
        return completed

    def discover(self):
        return self.invoke('discover', ['--mode', 'quarterly', '--discovery-id', 'cli-discovery',
                                       '--execution-id', 'cli-discover', '--attempt-id', 'discover-1'])

    def collect(self, workset_ref, *, attempt='collect-1', execution='cli-collect'):
        return self.invoke('collect', ['--workset', workset_ref, '--execution-id', execution, '--attempt-id', attempt])

    def read_durable_result(self, ref):
        from sec_edgar_ingest.models import CommandResult
        return CommandResult.from_json((self.state_root / 'objects' / ref).read_bytes())

    def close(self):
        import os
        import shutil
        destination = os.environ.get('SEC_EDGAR_TASK8_TRACE_DIR')
        if destination:
            target = Path(destination) / 'cli-files' / self.root.name
            self.root.joinpath('calls.json').write_text(json.dumps(self.calls, indent=2, sort_keys=True) + '\n')
            shutil.copytree(self.root, target, dirs_exist_ok=True)
            (target / 'retention-map.json').write_text(json.dumps({'original_root': str(self.root), 'retained_root': str(target)}) + '\n')
        self.temporary.cleanup()


def cli_harness(fixture: str, missing_user_agent: bool = False) -> CliHarness:
    return CliHarness(fixture, missing_user_agent)


def result_crash_entry(point, *argv):
    """Interrupt actual result object/Attempt transitions in an independent CLI process."""
    import gc
    import os
    import sec_edgar_ingest.cli as cli
    original = cli.write_result
    class Objects:
        def __init__(self, objects): self.objects = objects
        def __getattr__(self, name): return getattr(self.objects, name)
        def put_once(self, path, body):
            if path.endswith('/result.json') and point == 'before_result_object':
                gc.collect()
                os._exit(74)
            value = self.objects.put_once(path, body)
            if path.endswith('/result.json') and point == 'after_result_object':
                gc.collect()
                os._exit(74)
            return value
    class State:
        def __init__(self, state): self.state = state
        def __getattr__(self, name): return getattr(self.state, name)
        def finish_attempt(self, result):
            if point == 'before_attempt_finish':
                gc.collect()
                os._exit(74)
            self.state.finish_attempt(result)
            if point == 'after_attempt_finish':
                gc.collect()
                os._exit(74)
    def writer(result, objects, state):
        return original(result, Objects(objects), State(state))
    cli.write_result = writer
    if point == 'unexpected_error':
        def failure(*args, **kwargs): raise RuntimeError('explicit unexpected CLI fixture failure')
        cli.collect = failure
    if point == 'unexpected_sender':
        class ExplodingSender:
            def send(self, *args, **kwargs): raise RuntimeError('explicit unexpected sender fixture failure')
        cli.FixturePack.sender = lambda self, state: ExplodingSender()
    block_external_network()
    raise SystemExit(cli.main(list(argv)))


def retain_acquisition_proof(name, value):
    import os
    destination = os.environ.get('SEC_EDGAR_TASK8_TRACE_DIR')
    if destination:
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        (root / (name + '.json')).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def acquisition_race_entry(root, company, request_barrier, staged_barrier, binding_barrier, output):
    import os
    import time
    from dataclasses import replace
    from sec_edgar_ingest.collection import collect
    from sec_edgar_ingest.coordination import Clock
    from sec_edgar_ingest.results import write_result
    from sec_edgar_ingest.worksets import decode_source_workset
    root = Path(root)
    clock = Clock()
    h = CollectionHarness(root, [valid_idx_response('daily', company='process-' + company)], clock=clock)
    h.context = replace(real_context(clock, h.settings), execution_id='process-' + company,
                        attempt_id='process-' + company, deadline=clock.now() + timedelta(seconds=30))
    events = []
    def trace(event, **details):
        events.append({'event': event, 'pid': os.getpid(), 'monotonic_ns': time.monotonic_ns(),
                       'at': clock.now().isoformat(), **details})
    def observe(event):
        details = dict(event)
        trace(details.pop('event'), **details)
    h.coordinator.observer = observe
    original_fetch = h.client.fetch
    def fetch(*args, **kwargs):
        # All collectors must choose download before any can checkpoint a receipt.
        # Wait before fetch acquires coordinator ownership so requests remain serialized.
        trace('request_barrier_ready')
        request_barrier.wait(timeout=20)
        trace('request_barrier_released')
        return original_fetch(*args, **kwargs)
    h.client.fetch = fetch
    def staged():
        trace('receipt_checkpoint')
        staged_barrier.wait(timeout=20)
    h.faults.at('after_receipt_checkpoint', staged)
    h.source_state.store = CollectionRaceStore(h.store, binding_barrier, trace)
    workset = decode_source_workset((root / 'input-workset.json').read_bytes())
    try:
        result = collect(workset, h.context, h.settings, h.client, h.source_state, h.objects, h.faults)
        reference = write_result(result, h.objects, h.source_state)
        trace('result_written', result_ref=reference)
        output.put({'result': result.to_mapping(), 'result_ref': reference, 'events': events,
                    'candidate_sha256': __import__('hashlib').sha256(valid_idx_response('daily', company='process-' + company).body).hexdigest(),
                    'result_hex': h.objects.read(reference).hex()})
    finally:
        h.close()


def _integrated_settings(*, root=None):
    # The lease outlasts both successors' spawn and queueing, so they queue inside the unsafe interval.
    return spawn_tolerant_settings(root=root, coordination={'lease_seconds': 2 * SPAWN_ALLOWANCE_SECONDS,
                                                 'renew_every_seconds': SPAWN_ALLOWANCE_SECONDS,
                                                 'clock_uncertainty_seconds': 0.05})


def _append_process_event(path, event, **fields):
    import os
    import time
    with Path(path).open('a') as stream:
        stream.write(json.dumps({'event': event, 'pid': os.getpid(), 'monotonic': time.monotonic(),
                                 'at': datetime.now(timezone.utc).isoformat(), **fields}, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def integrated_old_sender(root, url, origin, cancellation):
    import gc
    from sec_edgar_ingest.coordination import Clock, Coordinator
    root = Path(root)
    clock, settings = Clock(), _integrated_settings(root=root / 'state')
    store, objects, leases = store_bundle(root / 'state', clock=clock)
    coordinator = Coordinator(settings, store, leases, clock)
    coordinator.observer = lambda event: _append_process_event(root / 'old-events.jsonl', 'coordinator', value=event)
    # The old child always starts late, so every run shows the dispatch window absorbing a slow spawn.
    sender = loopback_sender(settings, clock, origin, target=slow_spawn_child_exchange, spool=root / 'old-sender')
    context = real_context(clock, settings)
    with coordinator.turn('integrated-old-owner', 'backfill', context.deadline) as turn:
        turn.cancelled = cancellation
        gc.collect()
        permit = turn.reserve('integrated-old-request')
        _append_process_event(root / 'old-events.jsonl', 'permit', permit=permit.to_mapping(),
                              journal=leases.read_journal(turn.handle).to_mapping())
        turn.assert_current(permit)
        receipt = sender.send(url, context, permit, cancellation=cancellation)
        turn.complete(permit, drained=True)
    raise AssertionError('hostile fixture parent should have been killed')


def integrated_successor(root, priority, servers, ready):
    from dataclasses import replace
    from sec_edgar_ingest.coordination import Clock, Coordinator
    from sec_edgar_ingest.download import RequestClient
    from sec_edgar_ingest.state import AcquisitionState
    root = Path(root)
    clock, settings = Clock(), _integrated_settings(root=root / 'state')
    store, objects, leases = store_bundle(root / 'state', clock=clock)
    state = AcquisitionState(store, clock=clock)
    coordinator = Coordinator(settings, store, leases, clock)
    trace_path = root / (priority + '-events.jsonl')
    def observed(event):
        _append_process_event(trace_path, 'coordinator', value=event)
        if event['event'] == 'enqueue': ready.set()
    coordinator.observer = observed
    class MappedSender:
        def __init__(self): self.index = 0
        def send(self, url, context, permit, *, cancellation):
            selected = servers[self.index]
            self.index += 1
            target = root / (priority + '-sender-' + str(self.index))
            bounded = loopback_sender(settings, clock, selected['origin'], spool=target)
            _append_process_event(trace_path, 'request-dispatch', permit=permit.to_mapping(), url=url)
            receipt = bounded.send(selected['url'], context, permit, cancellation=cancellation)
            return replace(receipt, url=url)
    sender = MappedSender()
    client = RequestClient(settings, coordinator, sender, state, clock)
    client.jitter = lambda: 0
    context = replace(real_context(clock, settings), run_id='integrated-' + priority,
                      execution_id='integrated-' + priority, attempt_id='integrated-' + priority,
                      priority=priority, deadline=clock.now() + timedelta(seconds=4 * SPAWN_WAIT_SECONDS))
    try:
        if priority == 'daily':
            listing = client.fetch('https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/index.json', context)
            _append_process_event(trace_path, 'listing-received', receipt=listing.to_mapping(), body_hex=listing.temporary_path.read_bytes().hex())
            source = fixture_source('2026-10-01', 'daily')
        else:
            source = fixture_source()
        receipt = client.fetch(source.canonical_url, context, source)
        _append_process_event(trace_path, 'source-received', receipt=receipt.to_mapping(), body_hex=receipt.temporary_path.read_bytes().hex())
        _append_process_event(trace_path, 'request-history', rows=[row.to_mapping() for row in store.scan('TransportAttempt', {})])
    finally:
        leases.close()
        store.close()


def integrated_takeover_proof():
    import multiprocessing
    import subprocess
    import tempfile
    import time
    import shutil
    import os
    spawn = multiprocessing.get_context('spawn')
    with tempfile.TemporaryDirectory(prefix='sec-integrated-takeover-') as temporary:
        root = Path(temporary)
        old = LoopbackServer(mode='blocked-headers')
        listing = listing_response('2026Q4', ['master.20261001.idx'])
        specs = [LoopbackServer(b'retry prefix', status=503, headers={'Retry-After': '1'}),
                 LoopbackServer(listing.body), LoopbackServer(valid_idx_response('daily').body),
                 LoopbackServer(valid_idx_response('quarterly').body)]
        cancellation = spawn.Event()
        old_process = spawn.Process(target=integrated_old_sender, args=(str(root), old.url, old.origin, cancellation))
        processes = [old_process]
        try:
            old_process.start()
            if not old.connected.wait(SPAWN_WAIT_SECONDS): raise AssertionError('old child did not reach held loopback')
            old_process.terminate()
            old_process.join(2)
            killed = time.monotonic()
            old_events = [json.loads(line) for line in (root / 'old-events.jsonl').read_text().splitlines()]
            reservation = next(event for event in old_events if event['event'] == 'permit')
            permit = reservation['permit']
            unsafe_mono = reservation['monotonic'] + (datetime.fromisoformat(permit['takeover_after']) - datetime.fromisoformat(reservation['at'])).total_seconds()
            # Backfill queues first; the subsequently queued daily client must get the next turn.
            backfill_ready, daily_ready = spawn.Event(), spawn.Event()
            mapping = [{'url': server.url, 'origin': server.origin} for server in specs]
            backfill = spawn.Process(target=integrated_successor, args=(str(root), 'backfill', mapping[3:], backfill_ready))
            daily = spawn.Process(target=integrated_successor, args=(str(root), 'daily', mapping[:3], daily_ready))
            processes += [backfill, daily]
            backfill.start()
            if not backfill_ready.wait(SPAWN_WAIT_SECONDS): raise AssertionError('backfill client failed to queue')
            daily.start()
            if not daily_ready.wait(SPAWN_WAIT_SECONDS): raise AssertionError('daily client failed to queue')
            observations = []
            while time.monotonic() < unsafe_mono - 0.02:
                observations.append({'monotonic': time.monotonic(), 'successor_requests': sum(len(server.requests) for server in specs)})
                if observations[-1]['successor_requests']: raise AssertionError('successor reached loopback inside persisted unsafe interval')
                time.sleep(min(0.025, max(0, unsafe_mono - 0.02 - time.monotonic())))
            for process in (daily, backfill):
                process.join(4 * SPAWN_WAIT_SECONDS)
                if process.exitcode != 0: raise AssertionError('integrated successor failed: ' + str(process.exitcode))
            if not old.closed.wait(SPAWN_WAIT_SECONDS): raise AssertionError('orphan old child socket did not drain')
            old_transport = [json.loads(line) for line in (root / 'old-sender/transport.jsonl').read_text().splitlines()]
            armed = next(event for event in old_transport if event['event'] == 'alarm-armed')
            status = subprocess.run(['ps', '-o', 'stat=', '-p', str(armed['pid'])], capture_output=True, text=True, timeout=1)
            drained = status.returncode == 1 or not status.stdout.strip() or status.stdout.strip().startswith('Z')
            daily_events = [json.loads(line) for line in (root / 'daily-events.jsonl').read_text().splitlines()]
            backfill_events = [json.loads(line) for line in (root / 'backfill-events.jsonl').read_text().splitlines()]
            starts = sorted([{'priority': 'daily' if index < 3 else 'backfill', **event} for index, server in enumerate(specs) for event in server.events if event['event'] == 'request-received'], key=lambda event: event['monotonic'])
            for before, after in zip(starts, starts[1:]):
                if after['monotonic'] - before['monotonic'] < 1 / _integrated_settings().sec.requests_per_second: raise AssertionError('shared wire pacing compressed across listing/retry/download')
            child_traces = {path.relative_to(root).as_posix(): [json.loads(line) for line in path.read_text().splitlines()] for path in root.rglob('transport.jsonl')}
            proof = {'parent_pid': old_process.pid, 'parent_exit': old_process.exitcode, 'killed_at': killed,
                     'successor_exit': daily.exitcode, 'successor_processes': [{'pid': process.pid, 'exit': process.exitcode} for process in (daily, backfill)],
                     'old_permit': permit, 'old_journal': reservation['journal'], 'unsafe_until_mono': unsafe_mono,
                     'unsafe_observations': observations, 'zero_successor_through_guard': bool(observations) and all(item['successor_requests'] == 0 for item in observations),
                     'successor_first_start': starts[0]['monotonic'], 'old_socket_closed': next(event['monotonic'] for event in old.events if event['event'] == 'socket-closed'),
                     'ordered_priorities': [item['priority'] for item in starts], 'all_wire_starts': starts,
                     'child_alarm_disposition': armed['alarm_disposition'], 'old_child_drained': drained,
                     'orphan_status': {'argv': status.args, 'stdout': status.stdout, 'stderr': status.stderr, 'exit': status.returncode},
                     'old_server': old.events, 'old_events': old_events, 'daily_events': daily_events,
                     'backfill_events': backfill_events, 'child_traces': child_traces,
                     'servers': [{'events': server.events, 'requests': server.requests, 'body_hex': server.body.hex(), 'body_sha256': __import__('hashlib').sha256(server.body).hexdigest()} for server in specs]}
            return proof
        finally:
            destination = os.environ.get('SEC_EDGAR_TASK8_TRACE_DIR')
            if destination:
                target = Path(destination) / 'integrated-takeover-files'
                shutil.copytree(root, target, dirs_exist_ok=True)
                (target / 'retention-map.json').write_text(json.dumps({'original_root': str(root), 'retained_root': str(target)}) + '\n')
            for process in processes:
                if process.is_alive(): process.terminate(); process.join(2)
            old.close()
            for server in specs: server.close()
