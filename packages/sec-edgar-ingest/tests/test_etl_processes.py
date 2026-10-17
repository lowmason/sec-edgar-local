"""Real spawn proof entry points; every target installs the offline guard."""
from network_guard import install
install()
import contextlib
import io
import os
import shutil
import importlib.util
import tempfile
import unittest
from pathlib import Path


class ProcessProofTests(unittest.TestCase):
    def test_driver_exposes_real_process_proof(self):
        self.assertIsNotNone(importlib.util.find_spec('etl_proof'), 'Task 7 process proof driver is missing')

    def test_aligned_insert_replace_and_gate_races(self):
        from etl_proof import process_proof
        with tempfile.TemporaryDirectory() as directory:
            try:
                report = process_proof(Path(directory))
                self.assertEqual(len(report['races']), 3)
                self.assertEqual(len(report['deaths']), 4)
            finally:
                destination = os.environ.get('SEC_EDGAR_TASK7_PROCESS_PROOF')
                if destination:
                    shutil.copytree(directory, destination)

    def test_each_command_help_and_required_proof_output(self):
        from sec_edgar_ingest.cli import main
        from etl_proof import main as proof_main
        for command in ('discover', 'collect', 'transform', 'publish'):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as caught:
                main([command, '--help'])
            self.assertEqual(caught.exception.code, 0)
            self.assertIn('--config', output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            proof_main(['sequence'])
        self.assertEqual(caught.exception.code, 2)


def guarded_wait(ready, ignore_terminate):
    """Controlled real child; each red test also owns an emergency reap path."""
    install()
    import signal
    import threading
    if ignore_terminate:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    ready.set()
    threading.Event().wait(60)


class ProofTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.addCleanup(self.retain)

    def retain(self):
        destination = os.environ.get('SEC_EDGAR_TASK7_TIMEOUT_PROOF')
        if destination:
            shutil.copytree(self.root, Path(destination) / self._testMethodName)

    def emergency_reap(self, children):
        for child in children:
            if child.pid is not None:
                if child.is_alive():
                    child.kill()
                child.join(5)
                self.assertFalse(child.is_alive(), f'emergency reap failed for {child.pid}')

    def test_first_timeout_reaps_all_real_children_with_kill_fallback(self):
        import multiprocessing
        import signal
        import time
        from unittest.mock import patch
        import etl_proof
        spawn = multiprocessing.get_context('spawn')
        events = [spawn.Event(), spawn.Event()]
        children = [spawn.Process(target=guarded_wait, args=(ready, index == 0))
                    for index, ready in enumerate(events)]
        started = time.monotonic()
        try:
            for child in children:
                child.start()
            self.assertTrue(all(ready.wait(10) for ready in events))
            with patch.object(etl_proof, 'JOIN_SECONDS', .05), \
                 patch.object(etl_proof, 'TERMINATE_SECONDS', .1, create=True), \
                 self.assertRaises(AssertionError):
                etl_proof.join_children(children)
            status = [{'pid': child.pid, 'alive': child.is_alive(), 'exit': child.exitcode} for child in children]
            etl_proof.save(self.root / 'observed.json', {'children': status, 'runtime_seconds': time.monotonic() - started})
            self.assertEqual([value['alive'] for value in status], [False, False], 'timeout left owned children alive')
            self.assertEqual([value['exit'] for value in status], [-signal.SIGKILL, -signal.SIGTERM])
        finally:
            self.emergency_reap(children)
            etl_proof.save(self.root / 'emergency-reap.json', {'children': [
                {'pid': child.pid, 'alive': child.is_alive(), 'exit': child.exitcode} for child in children]})

    def test_partial_race_start_reaps_already_started_child(self):
        import multiprocessing
        from types import SimpleNamespace
        from unittest.mock import patch
        import etl_proof
        spawn = multiprocessing.get_context('spawn')
        ready = spawn.Event()
        children = []
        class StartControlled:
            def __init__(self, child, fail):
                self.child, self.fail = child, fail

            def __getattr__(self, name):
                return getattr(self.child, name)

            def start(self):
                if self.fail:
                    raise RuntimeError('injected second process start failure')
                self.child.start()
                if not ready.wait(10):
                    raise AssertionError('first controlled child did not start')

        def process(**kwargs):
            child = spawn.Process(target=guarded_wait, args=(ready, False))
            children.append(child)
            return StartControlled(child, len(children) == 2)
        context = SimpleNamespace(Process=process, Barrier=spawn.Barrier, Event=spawn.Event)
        try:
            with patch.object(etl_proof.multiprocessing, 'get_context', return_value=context), \
                 patch.object(etl_proof, 'JOIN_SECONDS', .05), \
                 patch.object(etl_proof, 'TERMINATE_SECONDS', .1, create=True), \
                 self.assertRaisesRegex(RuntimeError, 'injected second process start failure'):
                etl_proof.prove_race(self.root / 'race')
            self.assertEqual(len(children), 2)
            status = [{'pid': child.pid, 'alive': child.is_alive(), 'exit': child.exitcode} for child in children]
            etl_proof.save(self.root / 'observed.json', {'children': status})
            self.assertFalse(children[0].is_alive(), 'partial startup leaked the first owned child')
            self.assertIsNone(children[1].pid)
        finally:
            self.emergency_reap(children)

    def test_real_subprocess_timeout_retains_partial_output_bytes(self):
        import json
        import subprocess
        import sys
        import inspect
        import etl_proof
        self.assertEqual(inspect.signature(etl_proof.run_logged).parameters['timeout'].default, 300)
        script = self.root / 'timeout.py'
        guard_path = str(Path(__file__).resolve().parent)
        script.write_text('import sys\nsys.path.insert(0, ' + repr(guard_path) + ')\n'
                          'from network_guard import install\ninstall()\n'
                          'import os, time\nos.write(1, b"stdout-before-timeout\\xff\\n")\n'
                          'os.write(2, b"stderr-before-timeout\\xfe\\n")\ntime.sleep(60)\n')
        with self.assertRaises(subprocess.TimeoutExpired):
            etl_proof.run_logged([sys.executable, str(script)], self.root, self.root, 'timeout', timeout=1)
        record = self.root / 'timeout.json'
        self.assertTrue(record.is_file(), 'timeout lost command record and captured subprocess output')
        value = json.loads(record.read_text())
        self.assertIsNone(value['exit'])
        self.assertEqual(value['outcome'], 'timeout')
        self.assertEqual(value['timeout_seconds'], 1)
        self.assertIn('environment', value)
        self.assertEqual(value['cwd'], str(self.root))
        self.assertGreater(value['runtime_seconds'], .5)
        self.assertIn('platform', value)
        self.assertIn('dependencies', value)
        for stream, expected in [('stdout', b'stdout-before-timeout\xff\n'), ('stderr', b'stderr-before-timeout\xfe\n')]:
            self.assertEqual((self.root / value[stream + '_raw_file']).read_bytes(), expected)


if __name__ == '__main__':
    unittest.main()
