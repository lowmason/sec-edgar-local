"""Real guarded process trees, byte streams, sink faults and forwarded signals."""
from network_guard import install
install()

import json
import hashlib
import os
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from sec_edgar_ingest import local_cli
from sec_edgar_ingest.runtime import native_python_argv

FIXTURE = Path(__file__).with_name('launcher_engine.py').resolve()
ENGINE_STDERR = b'{"event":"engine_output","bytes":"\\u00ff"}\n'


class LauncherProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support_release import proof_releases
        project = FIXTURE.parents[3]
        cls.release, _ = proof_releases(project, project / 'releases/artifact-cache')

    def setUp(self):
        self.assertTrue(callable(getattr(local_cli, 'run_invocation', None)),
                        'Task 12 requires bounded stream/status supervision')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name in ('stdout', 'stderr'):
            (self.root / (name + '.jsonl')).touch(mode=0o600)
        self.process = None
        self.addCleanup(self.cleanup_processes)

    def events(self):
        path = self.root / 'events.jsonl'
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def wait_event(self, name, timeout=10):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            matches = [item for item in self.events() if item['event'] == name]
            if matches:
                return matches[0]
            if self.process.poll() is not None:
                self.fail('wrapper exited before ' + name + ': ' + repr(self.process.communicate()))
            time.sleep(0.01)
        self.fail('timed out waiting for event ' + name)

    def start(self, status=0, mode='normal', fault='none', timeout=10):
        self.process = subprocess.Popen([*native_python_argv(self.release.python),
            str(FIXTURE), 'runner', str(self.root), str(status), mode, fault, str(timeout)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self.process

    def result(self, status=0):
        return b'{ "outcome" : "fixture", "status" : ' + str(status).encode() + b' }\n'

    def assert_drained(self, status):
        events = self.events()
        runtime = next(item for item in events if item['event'] == 'wrapper_runtime')
        self.assertTrue(Path(runtime['module_file']).is_relative_to(self.release.directory / 'venv'))
        self.assertEqual(runtime['module_sha256'], hashlib.sha256(Path(local_cli.__file__).read_bytes()).hexdigest())
        self.assertEqual(sum(item['event'] == 'launch' for item in events), 1)
        self.assertEqual(sum(item['event'] == 'engine_started' for item in events), 1)
        self.assertEqual(sum(item['event'] == 'child_started' for item in events), 1)
        self.assertEqual(sum(item['event'] == 'child_drained' for item in events), 1)
        self.assertEqual([item['status'] for item in events if item['event'] == 'engine_drained'], [status])
        self.assertEqual((self.root / 'durable-result.json').read_bytes(), self.result(status))
        engine = next(item for item in events if item['event'] == 'engine_started')
        self.assertEqual((engine['isolated'], engine['no_bytecode'], engine['cache_prefix']),
                         (1, True, os.devnull))
        for event in events:
            if event['event'] in ('engine_started', 'child_started'):
                with self.assertRaises(ProcessLookupError):
                    os.kill(event['pid'], 0)

    def cleanup_processes(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.communicate(timeout=10)
        for item in self.events():
            if item['event'] == 'engine_dispatched':
                try:
                    os.killpg(item['engine_pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if item['event'] in ('engine_started', 'child_started'):
                try:
                    os.kill(item['pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_status_matrix_and_original_bytes_are_preserved_separately(self):
        for status in (0, 5, 7, 10, 11):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                original = self.root
                self.root = Path(temporary)
                for name in ('stdout', 'stderr'):
                    (self.root / (name + '.jsonl')).touch(mode=0o600)
                process = self.start(status)
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, status, stderr)
                self.assertEqual(stdout, self.result(status))
                self.assertEqual(stderr, ENGINE_STDERR)
                self.assertEqual((self.root / 'stdout.jsonl').read_bytes(), stdout)
                self.assertEqual((self.root / 'stderr.jsonl').read_bytes(), stderr)
                self.assert_drained(status)
                self.root = original

    def test_archive_failures_take_precedence_after_durable_engine_result(self):
        for fault, status in (('stdout', 0), ('stderr', 5), ('both', 7), ('fsync', 11), ('late_fsync', 10)):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                original = self.root
                self.root = Path(temporary)
                for name in ('stdout', 'stderr'):
                    (self.root / (name + '.jsonl')).touch(mode=0o600)
                process = self.start(status, fault=fault)
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 9, stderr)
                self.assertEqual(stdout, self.result(status))
                self.assertIn(b'"engine_returncode":' + str(status).encode(), stderr)
                self.assertIn(b'"event":"logging_failed"', stderr)
                self.assert_drained(status)
                self.root = original

    def test_closed_stdout_terminal_still_archives_engine_and_drains_child(self):
        process = self.start(10, mode='wait')
        self.wait_event('ready')
        process.stdout.close()
        process.send_signal(signal.SIGTERM)
        stderr = process.stderr.read()
        process.wait(timeout=15)
        self.assertEqual(process.returncode, 9, stderr)
        self.assertEqual((self.root / 'stdout.jsonl').read_bytes(), self.result(10))
        self.assertIn(b'"engine_returncode":10', stderr)
        self.assert_drained(10)

    def test_closed_stderr_terminal_reports_failure_in_remaining_archive(self):
        process = self.start(7, mode='wait')
        self.wait_event('ready')
        process.stderr.close()
        process.send_signal(signal.SIGTERM)
        stdout = process.stdout.read()
        process.wait(timeout=15)
        self.assertEqual(process.returncode, 9)
        self.assertEqual(stdout, self.result(7))
        self.assertIn(b'"engine_returncode":7', (self.root / 'stderr.jsonl').read_bytes())
        self.assert_drained(7)

    def test_terminal_archive_and_engine_failures_preserve_real_engine_status(self):
        process = self.start(11, mode='wait', fault='stderr')
        self.wait_event('ready')
        process.stdout.close()
        process.send_signal(signal.SIGINT)
        stderr = process.stderr.read()
        process.wait(timeout=15)
        self.assertEqual(process.returncode, 9, stderr)
        self.assertIn(b'"engine_returncode":11', stderr)
        self.assertIn(b'"event":"logging_failed"', stderr)
        self.assertEqual((self.root / 'stdout.jsonl').read_bytes(), self.result(11))
        self.assert_drained(11)

    def test_signals_forward_to_engine_allowing_separate_child_group_to_drain(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signum), tempfile.TemporaryDirectory() as temporary:
                original = self.root
                self.root = Path(temporary)
                for name in ('stdout', 'stderr'):
                    (self.root / (name + '.jsonl')).touch(mode=0o600)
                process = self.start(5, mode='wait')
                self.wait_event('ready')
                process.send_signal(signum)
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 5, stderr)
                self.assertEqual(stdout, self.result(5))
                self.assertEqual([item['signal'] for item in self.events()
                                  if item['event'] == 'engine_signal'], [signum])
                self.assert_drained(5)
                self.root = original

    def test_deadline_forwards_termination_without_relaunch(self):
        process = self.start(11, mode='wait', timeout=0.6)
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 11, stderr)
        self.assertEqual(stdout, self.result(11))
        self.assertEqual([item['signal'] for item in self.events()
                          if item['event'] == 'engine_signal'], [signal.SIGTERM])
        self.assert_drained(11)

    def test_open_but_blocked_terminal_is_bounded_and_does_not_block_archives(self):
        process = self.start(7, mode='volume', timeout=1)
        stdout = process.stdout.read()
        # Deliberately hold stderr open without reading while the engine emits
        # more than the terminal queue can hold. This must not delay supervision.
        process.wait(timeout=12)
        stderr = process.stderr.read()
        self.assertEqual(process.returncode, 9)
        self.assertEqual(stdout, self.result(7))
        archive = (self.root / 'stderr.jsonl').read_bytes()
        self.assertTrue(archive.startswith(ENGINE_STDERR + b'x' * (64 * 65536)))
        self.assertIn(b'"engine_returncode":7', archive)
        self.assertLess(len(stderr), 64 * 65536)
        self.assert_drained(7)

    def test_slow_terminal_retains_bytes_within_bounded_queue(self):
        process = self.start(0, mode='slow')
        chunks = []
        def read_slowly():
            while chunk := process.stderr.read(65536):
                chunks.append(chunk)
                time.sleep(0.003)
        reader = threading.Thread(target=read_slowly)
        reader.start()
        stdout = process.stdout.read()
        process.wait(timeout=15)
        reader.join(timeout=5)
        self.assertFalse(reader.is_alive())
        self.assertEqual(process.returncode, 0)
        self.assertEqual(stdout, self.result())
        self.assertEqual(b''.join(chunks), ENGINE_STDERR + b'x' * (64 * 65536))
        self.assert_drained(0)

    def test_unavailable_ancestry_keeps_draining_and_retains_uncertainty(self):
        process = self.start(7, fault='ancestry')
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 7, stderr)
        self.assertEqual(stdout, self.result(7))
        self.assertIn(b'"event":"shutdown_uncertain"', stderr)
        self.assertIn(b'"engine_returncode":7', stderr)
        self.assert_drained(7)

    def test_signal_at_popen_boundary_cannot_kill_wrapper_and_orphan_engine(self):
        process = self.start(5, mode='wait', fault='launch_signal')
        stdout, stderr = process.communicate(timeout=20)
        self.assertEqual(process.returncode, 241, stderr)  # SystemExit(-SIGTERM).
        events = self.events()
        self.assertEqual([item['status'] for item in events if item['event'] == 'wrapper_finished'], [-15])
        self.assertEqual(sum(item['event'] == 'launch' for item in events), 1)
        self.assertEqual(stdout, b'')

    def test_forced_engine_exit_keeps_actual_status_and_cleans_separate_child(self):
        process = self.start(0, mode='stubborn', timeout=0.8)
        self.wait_event('tree_observed')
        stdout, stderr = process.communicate(timeout=20)
        self.assertEqual(process.returncode, 247, stderr)  # SystemExit(-SIGKILL).
        self.assertEqual(stdout, b'')
        self.assertIn(b'"event":"shutdown_uncertain"', stderr)
        self.assertIn(b'"engine_returncode":-9', stderr)
        events = self.events()
        self.assertEqual([item['status'] for item in events if item['event'] == 'wrapper_finished'], [-9])
        self.assertEqual(sum(item['event'] == 'launch' for item in events), 1)
        self.assertFalse((self.root / 'durable-result.json').exists())
        self.assertEqual(sum(item['event'] == 'child_drained' for item in events), 1)
        for item in events:
            if item['event'] in ('engine_started', 'child_started'):
                with self.assertRaises(ProcessLookupError):
                    os.kill(item['pid'], 0)

    def test_dead_engine_never_authorizes_child_drain_from_exit_status(self):
        process = self.start(5, mode='orphan')
        self.wait_event('tree_observed')
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=20)
        self.assertEqual(process.returncode, 5, stderr)
        self.assertEqual(stdout, self.result(5))
        self.assertIn(b'"event":"shutdown_uncertain"', stderr)
        self.assertIn(b'"engine_returncode":5', stderr)
        self.assertEqual(sum(item['event'] == 'child_drained' for item in self.events()), 1)
        for item in self.events():
            if item['event'] in ('engine_started', 'child_started'):
                with self.assertRaises(ProcessLookupError):
                    os.kill(item['pid'], 0)


if __name__ == '__main__':
    unittest.main()
