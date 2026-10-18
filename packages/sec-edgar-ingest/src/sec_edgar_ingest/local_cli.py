"""Prepare immutable native invocations before delegating to the installed engine."""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .config import normalize_paths, parse_config, pin_context
from .models import RunContext, canonical_json
from .runtime import native_descriptor, native_python_argv, preflight_current
from .workflows.contracts import WORKFLOW_COMMANDS, WORKFLOW_PRIORITY

INVOCATION_VERSION = 'sec-local-invocation-v1'
DEFAULT_TIMEOUT_SECONDS = 3300
CONFIGURATION_EXIT = 2
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700


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
    # Stream forwarding and bounded dispatch are the next task's integration boundary.
    sys.stderr.write(canonical_json({'outcome': 'configuration', 'error': 'launcher dispatch is not yet implemented',
                                    'invocation': str(invocation.directory / 'invocation.json')}).decode() + '\n')
    return CONFIGURATION_EXIT


if __name__ == '__main__':
    raise SystemExit(main())
