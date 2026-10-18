"""Uninstalled, guarded process fixture for launcher stream and shutdown faults."""
from __future__ import annotations

import json
import hashlib
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Isolated Python deliberately omits the script directory. Install the test guard
# explicitly before importing the application, including at every exec boundary.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from network_guard import install
install()


def event(root, name, **fields):
    with (root / 'events.jsonl').open('ab', buffering=0) as stream:
        stream.write((json.dumps({'event': name, 'pid': os.getpid(), **fields}) + '\n').encode())


def argv(*args):
    return [sys.executable, '-I', '-B', '-X', 'pycache_prefix=/dev/null', __file__, *map(str, args)]


def child(root):
    stopped = threading.Event()
    def stop(signum, frame):
        stopped.set()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    event(root, 'child_started')
    stopped.wait()
    event(root, 'child_drained')


def engine(root, status, mode):
    stopped = threading.Event()
    def stop(signum, frame):
        stopped.set()
        event(root, 'engine_signal', signal=signum)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    event(root, 'engine_started', argv=sys.argv, isolated=sys.flags.isolated,
          no_bytecode=sys.dont_write_bytecode, cache_prefix=sys.pycache_prefix)
    descendant = subprocess.Popen(argv('child', root), start_new_session=True,
        stdout=subprocess.DEVNULL if mode == 'orphan' else None,
        stderr=subprocess.DEVNULL if mode == 'orphan' else None)
    until = time.monotonic() + 10
    while not any(json.loads(line)['event'] == 'child_started'
                  for line in (root / 'events.jsonl').read_text().splitlines()):
        if time.monotonic() > until:
            raise RuntimeError('child did not acknowledge start')
        time.sleep(0.01)
    event(root, 'ready')
    if mode in ('wait', 'stubborn', 'orphan'):
        if mode == 'stubborn':
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        stopped.wait()
    result = b'{ "outcome" : "fixture", "status" : ' + str(status).encode() + b' }\n'
    with (root / 'durable-result.json').open('xb') as stream:
        stream.write(result)
        stream.flush()
        os.fsync(stream.fileno())
    os.write(1, result)
    os.write(2, b'{"event":"engine_output","bytes":"\\u00ff"}\n')
    if mode in ('volume', 'slow'):
        for index in range(64):
            os.write(2, b'x' * 65536)
            if mode == 'slow':
                time.sleep(0.01)
    if mode == 'orphan':
        return status
    descendant.send_signal(signal.SIGTERM)
    descendant.wait(timeout=10)
    event(root, 'engine_drained', status=status)
    return status


def runner(root, status, mode, fault, timeout):
    from unittest.mock import patch
    from sec_edgar_ingest import local_cli
    event(root, 'wrapper_runtime', module_file=local_cli.__file__,
          module_sha256=hashlib.sha256(Path(local_cli.__file__).read_bytes()).hexdigest())
    now = datetime.now(timezone.utc)
    invocation = local_cli.Invocation(root, root / 'config.json', tuple(argv('engine', root, status, mode)),
        'fixture-run', 'fixture-execution', 'fixture-attempt', now,
        now + timedelta(seconds=timeout), 'a' * 64)
    actual_write, actual_fsync, actual_popen = os.write, os.fsync, subprocess.Popen
    actual_tree = local_cli._process_tree
    archives = {name: (root / (name + '.jsonl')).stat().st_ino for name in ('stdout', 'stderr')}
    def fail_write(fd, body):
        if fault in ('stdout', 'stderr', 'both') and os.fstat(fd).st_ino in (
                archives.values() if fault == 'both' else (archives[fault],)):
            raise OSError('injected archive failure')
        return actual_write(fd, body)
    stderr_fsyncs = 0
    def fail_fsync(fd):
        nonlocal stderr_fsyncs
        if os.fstat(fd).st_ino == archives['stderr']:
            stderr_fsyncs += 1
            if fault == 'late_fsync' and stderr_fsyncs > 1:
                raise OSError('injected final stderr fsync failure')
        if fault == 'fsync' and os.fstat(fd).st_ino in archives.values():
            raise OSError('injected archive fsync failure')
        return actual_fsync(fd)
    def launch(command, *args, **kwargs):
        if str(Path(__file__).resolve()) in map(str, command) and 'engine' in command:
            event(root, 'launch', command=list(command))
        if Path(str(command[0])).name in ('uv', 'pip', 'pip3'):
            raise AssertionError('dependency tooling during invocation')
        process = actual_popen(command, *args, **kwargs)
        if 'engine' in command:
            event(root, 'engine_dispatched', engine_pid=process.pid)
            if fault == 'launch_signal':
                os.kill(os.getpid(), signal.SIGTERM)
        return process
    def snapshot():
        if fault == 'ancestry':
            raise OSError('injected process ancestry failure')
        tree = actual_tree()
        events = [json.loads(line) for line in (root / 'events.jsonl').read_text().splitlines()]
        children = [item['pid'] for item in events if item['event'] == 'child_started']
        if any(pid in tree for pid in children):
            event(root, 'tree_observed')
        return tree
    with patch.object(local_cli.os, 'write', side_effect=fail_write), \
            patch.object(local_cli.os, 'fsync', side_effect=fail_fsync), \
            patch.object(local_cli.subprocess, 'Popen', side_effect=launch), \
            patch.object(local_cli, '_process_tree', side_effect=snapshot):
        status = local_cli.run_invocation(invocation)
    event(root, 'wrapper_finished', status=status)
    return status


if __name__ == '__main__':
    role, directory, *options = sys.argv[1:]
    root = Path(directory)
    if role == 'child':
        child(root)
        raise SystemExit(0)
    if role == 'engine':
        raise SystemExit(engine(root, int(options[0]), options[1]))
    raise SystemExit(runner(root, int(options[0]), options[1], options[2], float(options[3])))
