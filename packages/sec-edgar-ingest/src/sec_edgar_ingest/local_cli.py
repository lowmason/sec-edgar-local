"""Prepare immutable native invocations before delegating to the installed engine."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import math
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .config import normalize_paths, parse_config, pin_context
from .models import RunContext, canonical_json
from .runtime import native_descriptor, native_python_argv, preflight_current
from .runtime import isolated_environment
from .workflows.contracts import WORKFLOW_COMMANDS, WORKFLOW_PRIORITY

INVOCATION_VERSION = 'sec-local-invocation-v1'
DEFAULT_TIMEOUT_SECONDS = 3300
CONFIGURATION_EXIT = 2
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700
STREAM_CHUNK_BYTES = 65_536
TERMINAL_QUEUE_BYTES = 1_048_576
TERMINAL_DRAIN_SECONDS = 1.0
ENGINE_DRAIN_SECONDS = 10.0
POLL_SECONDS = 0.02


@dataclass(frozen=True, slots=True)
class Invocation:
    directory: Path
    config_path: Path
    argv: tuple[str, ...]
    run_id: str
    execution_id: str
    attempt_id: str
    started_at: datetime
    deadline: datetime
    release_id: str


def write_exclusive(path: Path, body: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_invocation_directory(log_root: Path, run_id: str, attempt_id: str) -> Path:
    log_root.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    run_directory = log_root / run_id
    run_directory.mkdir(mode=DIRECTORY_MODE)
    directory = run_directory / attempt_id
    directory.mkdir(mode=DIRECTORY_MODE)
    _fsync_directory(log_root.parent)
    _fsync_directory(log_root)
    _fsync_directory(run_directory)
    return directory


def prepare_invocation(config_path: Path, command: str, timeout_seconds: float, *,
                       project_root: Path) -> Invocation:
    """Archive the exact config/intent; do not open stores or dispatch a process.

    Partial preparation evidence is deliberately retained on every failure.
    Normal calls generate new identities; replay means manually using the saved argv.
    """
    if command not in WORKFLOW_COMMANDS:
        raise ValueError('launcher command must be backfill, daily, or reconcile')
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('timeout_seconds must be finite and positive')
    config_path = config_path.expanduser().resolve()
    original = config_path.read_bytes()
    settings = normalize_paths(parse_config(original.decode('utf-8')), config_path.parent)
    if timeout_seconds > settings.execution.max_run_seconds:
        raise ValueError('timeout_seconds exceeds execution.max_run_seconds')
    if settings.runtime.kind != 'native':
        raise ValueError('launcher requires an explicit installed native release')
    verified = preflight_current(Path(settings.runtime.release_manifest))
    started_at = datetime.now(timezone.utc)
    deadline = started_at + timedelta(seconds=timeout_seconds)
    run_id, execution_id, attempt_id = (str(uuid4()) for _ in range(3))
    runtime = native_descriptor(verified.release_id)
    context = RunContext(run_id=run_id, execution_id=execution_id, attempt_id=attempt_id,
        command=command, runtime=runtime, parser_version=settings.etl.parser_version,
        schema_version=settings.etl.schema_version, config_sha256=settings.config_sha256,
        started_at=started_at, deadline=deadline, priority=WORKFLOW_PRIORITY[command],
        format_version='sec-local-run-context-v1')
    _, pinned_end = pin_context(settings, context, started_at.date())
    log_root = Path(settings.logging.root)
    directory = _create_invocation_directory(log_root, run_id, attempt_id)
    archived_config = directory / 'config.json'
    argv = (*native_python_argv(verified.python), '-m', 'sec_edgar_ingest', command,
            '--config', str(archived_config), '--run-id', run_id,
            '--execution-id', execution_id, '--attempt-id', attempt_id,
            '--deadline', deadline.isoformat())
    invocation = Invocation(directory, archived_config, argv, run_id, execution_id,
                            attempt_id, started_at, deadline, verified.release_id)
    record = {
        'format_version': INVOCATION_VERSION, 'directory': str(directory),
        'config_path': str(archived_config), 'argv': list(argv), 'command': command,
        'run_id': run_id, 'execution_id': execution_id, 'attempt_id': attempt_id,
        'started_at': started_at.isoformat(), 'deadline': deadline.isoformat(),
        'release_id': verified.release_id, 'original_config_path': str(config_path),
        'original_config_sha256': hashlib.sha256(original).hexdigest(),
        'effective_config': settings.to_mapping(), 'config_sha256': settings.config_sha256,
        'data_path': settings.storage.root, 'log_path': str(log_root),
        'release_path': str(verified.directory), 'runtime': runtime,
        # The engine pins its own start; crossing midnight must not turn this into an asserted engine result.
        'preparation_pin': {'pinned_on': started_at.date().isoformat(), 'pinned_end_quarter': pinned_end,
                            'authority': 'supplementary; engine context is authoritative'},
    }
    write_exclusive(archived_config, canonical_json(settings.to_mapping()))
    write_exclusive(directory / 'invocation.json', canonical_json(record))
    write_exclusive(directory / 'stdout.jsonl', b'')
    write_exclusive(directory / 'stderr.jsonl', b'')
    _fsync_directory(directory)
    return invocation


class _Sink:
    """A failed sink is discarded independently of the engine's readable pipes."""

    def __init__(self, descriptor: int, name: str, *, terminal: bool = False):
        self.descriptor = descriptor
        self.name = name
        self.terminal = terminal
        self.pending = bytearray()
        self.error: str | None = None
        self.original_flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        if terminal:
            fcntl.fcntl(descriptor, fcntl.F_SETFL, self.original_flags | os.O_NONBLOCK)

    def fail(self, error: object) -> None:
        self.error = str(error)
        self.pending.clear()

    def accept(self, body: bytes) -> None:
        if self.error is not None:
            return
        self.pending.extend(body)
        self.flush()
        if self.terminal and len(self.pending) > TERMINAL_QUEUE_BYTES:
            self.fail('terminal output queue exceeded bounded capacity')

    def flush(self) -> None:
        while self.pending and self.error is None:
            try:
                count = os.write(self.descriptor, self.pending[:STREAM_CHUNK_BYTES])
                if count == 0:
                    raise OSError('output sink made no progress')
                del self.pending[:count]
            except BlockingIOError:
                return
            except OSError as error:
                self.fail(error)

    def close(self) -> None:
        try:
            if self.terminal:
                fcntl.fcntl(self.descriptor, fcntl.F_SETFL, self.original_flags)
        finally:
            os.close(self.descriptor)


def _drain_terminals(terminals: Sequence[_Sink]) -> None:
    until = time.monotonic() + TERMINAL_DRAIN_SECONDS
    while any(sink.pending for sink in terminals) and time.monotonic() < until:
        for sink in terminals:
            sink.flush()
        if any(sink.pending for sink in terminals):
            time.sleep(POLL_SECONDS)
    for sink in terminals:
        if sink.pending:
            sink.fail('terminal output did not drain within bounded allowance')


def _emit_event(sinks: Sequence[_Sink], event: str, **fields: object) -> None:
    body = canonical_json({'event': event, **fields}) + b'\n'
    for sink in sinks:
        sink.accept(body)


def _process_tree() -> dict[int, tuple[int, int, bytes]]:
    """Native POSIX process ancestry, including the engine's separate child groups.

    Checked stages create their own sessions. Remember their ancestry while the
    engine can still reap them; an engine-group kill alone cannot reach them.
    """
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,lstart='],
        stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=1)
    return {int(pid): (int(parent), int(group), started)
            for line in result.stdout.splitlines()
            for pid, parent, group, started in [line.split(None, 3)]}


def _remember_descendants(engine_pid: int, descendants: dict[int, tuple[int, bytes]]) -> None:
    processes = _process_tree()
    if engine_pid not in descendants:
        if engine_pid not in processes:
            raise ValueError('engine birth identity unavailable before ancestry observation')
        descendants[engine_pid] = processes[engine_pid][1:]
    parents = {pid for pid, identity in descendants.items()
               if pid in processes and processes[pid][1:] == identity}
    while True:
        additions = {pid: (group, started) for pid, (parent, group, started) in processes.items()
                     if parent in parents and pid not in parents}
        if not additions:
            return
        descendants.update(additions)
        parents.update(additions)


class _Descendants:
    """Ancestry inspection must never block stream reads or signal forwarding."""

    def __init__(self, engine_pid: int):
        self.engine_pid = engine_pid
        self.processes: dict[int, tuple[int, bytes]] = {}
        self.error: str | None = None
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._observe, daemon=True)
        self.thread.start()

    def _observe(self) -> None:
        while not self.stopped.is_set():
            try:
                _remember_descendants(self.engine_pid, self.processes)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                self.error = str(error)
            self.stopped.wait(0.05)

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=1.2)
        if self.thread.is_alive():
            self.error = 'process ancestry inspection did not stop within its bound'


def _signal_group(group: int, signum: int) -> None:
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        pass


def _cleanup_descendants(descendants: dict[int, tuple[int, bytes]]) -> bool:
    """Remove recorded surviving descendants without treating forced exit as drain."""
    try:
        processes = _process_tree()
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    survivors = {pid: identity for pid, identity in descendants.items()
                 if pid in processes and processes[pid][1:] == identity}
    groups = {group for group, _ in survivors.values()}
    if not groups:
        return True
    for group in groups:
        _signal_group(group, signal.SIGTERM)
    until = time.monotonic() + 1
    while groups and time.monotonic() < until:
        try:
            processes = _process_tree()
        except (OSError, ValueError, subprocess.SubprocessError):
            break
        groups = {group for pid, (group, started) in survivors.items()
                  if pid in processes and processes[pid][1:] == (group, started)}
        if groups:
            time.sleep(POLL_SECONDS)
    for group in groups:
        _signal_group(group, signal.SIGKILL)
    until = time.monotonic() + 1
    while groups and time.monotonic() < until:
        try:
            processes = _process_tree()
        except (OSError, ValueError, subprocess.SubprocessError):
            break
        groups = {group for pid, (group, started) in survivors.items()
                  if pid in processes and processes[pid][1:] == (group, started)}
        if groups:
            time.sleep(POLL_SECONDS)
    return False


def _supervise(invocation: Invocation, process: subprocess.Popen,
               channels: dict[object, tuple[_Sink, _Sink]],
               pending_signals: Sequence[int]) -> tuple[int, bool]:
    stopped_at = None
    forced = False
    descendants = _Descendants(process.pid)

    def forward(signum, frame=None):
        nonlocal stopped_at
        if stopped_at is None:
            stopped_at = time.monotonic()
        if process.returncode is None:
            _signal_group(process.pid, signum)

    handlers = {}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            handlers[signum] = signal.signal(signum, forward)
    for signum in pending_signals:
        forward(signum)
    try:
        with selectors.DefaultSelector() as selector:
            for stream in channels:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if stopped_at is None and datetime.now(timezone.utc) >= invocation.deadline:
                    forward(signal.SIGTERM)
                if stopped_at is not None and now - stopped_at >= ENGINE_DRAIN_SECONDS:
                    forced = True
                    if process.returncode is None:
                        _signal_group(process.pid, signal.SIGKILL)
                    # EOF itself may be held by a descendant after engine death.
                    break
                for key, _ in selector.select(POLL_SECONDS):
                    try:
                        body = os.read(key.fd, STREAM_CHUNK_BYTES)
                    except BlockingIOError:
                        continue
                    if not body:
                        selector.unregister(key.fileobj)
                    else:
                        for sink in channels[key.fileobj]:
                            sink.accept(body)
                for _, terminal in channels.values():
                    terminal.flush()
                # A dead engine with inherited pipes still open is uncertain.
                if process.poll() is not None and selector.get_map() and stopped_at is None:
                    forward(signal.SIGTERM)
            returncode = process.wait(timeout=ENGINE_DRAIN_SECONDS)
            descendants.close()
            descendants_drained = _cleanup_descendants(descendants.processes)
            if forced:
                # Read any final buffered bytes without waiting on inherited EOF.
                for stream, sinks in channels.items():
                    while True:
                        try:
                            body = os.read(stream.fileno(), STREAM_CHUNK_BYTES)
                        except BlockingIOError:
                            break
                        if not body:
                            break
                        for sink in sinks:
                            sink.accept(body)
            return returncode, forced or not descendants_drained or descendants.error is not None
    finally:
        for stream in channels:
            stream.close()
        if process.poll() is None:
            _signal_group(process.pid, signal.SIGKILL)
            process.wait(timeout=ENGINE_DRAIN_SECONDS)
            descendants.close()
            _cleanup_descendants(descendants.processes)
        descendants.close()
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def run_invocation(invocation: Invocation) -> int:
    """Dispatch once; log failure never stops engine drain or rewrites its result."""
    sinks: list[_Sink] = []
    process = None
    pending_signals: list[int] = []
    handlers = {}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            handlers[signum] = signal.signal(signum, lambda signum, frame: pending_signals.append(signum))
    try:
        if datetime.now(timezone.utc) >= invocation.deadline:
            raise ValueError('deadline expired before engine dispatch')
        for name, terminal in (('stdout', sys.stdout), ('stderr', sys.stderr)):
            descriptor = os.open(invocation.directory / (name + '.jsonl'), os.O_WRONLY | os.O_APPEND)
            sinks.append(_Sink(descriptor, name + '_archive'))
            sinks.append(_Sink(os.dup(terminal.fileno()), name + '_terminal', terminal=True))
        process = subprocess.Popen(invocation.argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            env=isolated_environment())
        channels = {process.stdout: (sinks[0], sinks[1]), process.stderr: (sinks[2], sinks[3])}
        engine_returncode, uncertain = _supervise(invocation, process, channels, pending_signals)
        _drain_terminals((sinks[1], sinks[3]))
        for archive in (sinks[0], sinks[2]):
            try:
                os.fsync(archive.descriptor)
            except OSError as error:
                archive.fail(error)
        if uncertain:
            _emit_event(sinks[2:], 'shutdown_uncertain', engine_returncode=engine_returncode)
        _drain_terminals((sinks[3],))
        try:
            os.fsync(sinks[2].descriptor)
        except OSError as error:
            sinks[2].fail(error)
        failed = {sink.name: sink.error for sink in sinks if sink.error is not None}
        if failed:
            _emit_event(sinks[2:], 'logging_failed', engine_returncode=engine_returncode,
                        failures=failed, shutdown_uncertain=uncertain)
            _drain_terminals((sinks[3],))
            try:
                os.fsync(sinks[2].descriptor)
            except OSError as error:
                sinks[2].fail(error)
        return 9 if failed else engine_returncode
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if process is None:
            body = canonical_json({'outcome': 'configuration', 'error': str(error),
                'invocation': str(invocation.directory / 'invocation.json')}) + b'\n'
            try:
                os.write(sys.stderr.fileno(), body)
            except OSError:
                pass
            return CONFIGURATION_EXIT
        # An unexpected supervision failure is evidence of uncertainty, never
        # permission to dispatch a replacement engine.
        _emit_event(sinks[2:], 'shutdown_uncertain', engine_returncode=process.returncode,
                    error=str(error))
        _drain_terminals((sinks[3],))
        return 9
    finally:
        for sink in reversed(sinks):
            sink.close()
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='sec-edgar-local')
    parser.add_argument('command', choices=WORKFLOW_COMMANDS)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--timeout-seconds', type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument('--project-root', type=Path, required=True, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    try:
        project_root = args.project_root.expanduser().resolve()
        config_path = (args.config or project_root / 'conf/sec-edgar-local.json').expanduser().resolve()
        invocation = prepare_invocation(config_path, args.command, args.timeout_seconds,
                                        project_root=project_root)
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError) as error:
        sys.stderr.write(canonical_json({'outcome': 'configuration', 'error': str(error)}).decode() + '\n')
        return CONFIGURATION_EXIT
    return run_invocation(invocation)


if __name__ == '__main__':
    raise SystemExit(main())
