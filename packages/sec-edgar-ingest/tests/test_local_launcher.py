"""Immutable preparation and stdlib-to-installed-release bootstrap contracts."""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import os
import stat
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from support import fixture_settings
from test_runtime import native_identity
from sec_edgar_ingest.config import load_config
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.runtime import VerifiedRelease, native_descriptor, native_python_argv, release_id

PROJECT = Path(__file__).resolve().parents[3]


class LauncherPreparationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('sec_edgar_ingest.local_cli'),
                             'Task 11 requires immutable launcher preparation')
        self.launcher = importlib.import_module('sec_edgar_ingest.local_cli')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'
        (self.project / 'conf').mkdir(parents=True)
        identity = native_identity()
        digest = release_id(identity)
        directory = self.project / 'releases' / ('sha256=' + digest)
        directory.mkdir(parents=True)
        manifest = {'format_version': 'sec-native-release-v1', 'release_id': digest, 'identity': identity}
        (directory / 'release.json').write_bytes(canonical_json(manifest))
        self.verified = VerifiedRelease(digest, manifest, directory, directory / 'venv/bin/python')
        value = fixture_settings().to_mapping()
        value['acquisition'] = {'mode': 'live'}
        value['runtime'] = {'kind': 'native', 'release_manifest': '../releases/sha256=' + digest + '/release.json'}
        value['etl']['parser_version'] = 'sec-index-parser-v1'
        value['storage']['root'] = '../data'
        value['logging']['root'] = '../logs'
        self.config = self.project / 'conf/sec-edgar-local.json'
        self.config.write_text(json.dumps(value, indent=3) + '\n')
        self.preflight = self.enterContext(patch.object(self.launcher, 'preflight_current', return_value=self.verified))
        self.engine = self.enterContext(patch('subprocess.Popen', side_effect=AssertionError('preparation dispatched engine')))
        self.stores = self.enterContext(patch('sec_edgar_ingest.storage.open_stores', side_effect=AssertionError('opened store')))
        self.http = self.enterContext(patch('requests.Session', side_effect=AssertionError('HTTP during preparation')))

    def prepare(self, timeout=3300, command='backfill'):
        return self.launcher.prepare_invocation(self.config, command, timeout, project_root=self.project)

    def main(self, *args):
        with contextlib.redirect_stderr(io.StringIO()):
            return self.launcher.main(['--project-root', str(self.project), *args])

    def test_archive_has_exact_normalized_bytes_original_hash_and_native_argv(self):
        original = self.config.read_bytes()
        invocation = self.prepare()
        record = json.loads((invocation.directory / 'invocation.json').read_bytes())
        self.assertEqual(set(record), {'format_version', 'directory', 'config_path', 'argv', 'command',
            'run_id', 'execution_id', 'attempt_id', 'started_at', 'deadline', 'release_id',
            'original_config_path', 'original_config_sha256', 'effective_config', 'config_sha256',
            'data_path', 'log_path', 'release_path', 'runtime', 'preparation_pin'})
        self.assertEqual(record['format_version'], 'sec-local-invocation-v1')
        self.assertEqual(record['original_config_sha256'], hashlib.sha256(original).hexdigest())
        self.assertNotEqual(record['original_config_sha256'], record['config_sha256'])
        settings = load_config(self.config)
        self.assertEqual(invocation.config_path.read_bytes(), canonical_json(settings.to_mapping()))
        self.assertEqual(load_config(invocation.config_path).config_sha256, settings.config_sha256)
        self.assertEqual(record['effective_config'], settings.to_mapping())
        self.assertEqual(record['config_sha256'], settings.config_sha256)
        self.assertEqual(record['data_path'], str(self.project / 'data'))
        self.assertEqual(record['log_path'], str(self.project / 'logs'))
        self.assertEqual(record['release_path'], str(self.verified.directory))
        self.assertEqual(record['runtime'], native_descriptor(self.verified.release_id))
        self.assertEqual(record['argv'], list(invocation.argv))
        self.assertEqual(invocation.argv[:7], (*native_python_argv(self.verified.python), '-m', 'sec_edgar_ingest'))
        self.assertEqual(invocation.argv[7], 'backfill')
        self.assertEqual(invocation.argv[invocation.argv.index('--config') + 1], str(invocation.config_path))
        self.assertNotIn(str(self.config), invocation.argv)
        self.assertEqual(invocation.deadline - invocation.started_at, timedelta(seconds=3300))
        self.assertEqual(invocation.started_at.tzinfo, timezone.utc)
        self.assertEqual(datetime.fromisoformat(record['deadline']), invocation.deadline)
        self.assertEqual(record['preparation_pin']['pinned_on'], invocation.started_at.date().isoformat())
        self.assertEqual(record['preparation_pin']['authority'], 'supplementary; engine context is authoritative')
        self.assertEqual(record['effective_config']['backfill']['end_quarter'], 'open')
        with self.assertRaises(FrozenInstanceError):
            invocation.run_id = 'changed'
        self.preflight.assert_called_once_with(self.verified.directory / 'release.json')
        self.assertFalse((self.project / 'data').exists())

    def test_ids_unique_safe_segments_and_files_restrictive_durable_empty_streams(self):
        first, second = self.prepare(), self.prepare()
        identifiers = [getattr(invocation, name) for invocation in (first, second)
                       for name in ('run_id', 'execution_id', 'attempt_id')]
        self.assertEqual(len(set(identifiers)), 6)
        for identifier in identifiers:
            self.assertRegex(identifier, r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
        self.assertEqual(first.directory, self.project / 'logs' / first.run_id / first.attempt_id)
        for name in ('config.json', 'invocation.json', 'stdout.jsonl', 'stderr.jsonl'):
            self.assertEqual(stat.S_IMODE((first.directory / name).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(first.directory.stat().st_mode), 0o700)
        self.assertEqual((first.directory / 'stdout.jsonl').read_bytes(), b'')
        self.assertEqual((first.directory / 'stderr.jsonl').read_bytes(), b'')

    def test_default_config_uses_explicit_project_root_from_arbitrary_cwd(self):
        old = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.object(self.launcher, 'prepare_invocation', wraps=self.launcher.prepare_invocation) as prepare, \
                    patch.object(self.launcher, 'run_invocation', create=True, return_value=5) as run:
                self.assertEqual(self.main('daily'), 5)
            self.assertEqual(run.call_args.args[0].config_path.name, 'config.json')
            self.assertEqual(prepare.call_args.args[:3], (self.config, 'daily', 3300))
        finally:
            os.chdir(old)

    def test_explicit_config_resolves_relative_to_calling_cwd(self):
        old = Path.cwd()
        try:
            os.chdir(self.project)
            with patch.object(self.launcher, 'prepare_invocation', wraps=self.launcher.prepare_invocation) as prepare, \
                    patch.object(self.launcher, 'run_invocation', create=True, return_value=10):
                self.assertEqual(self.main('reconcile', '--config', 'conf/sec-edgar-local.json'), 10)
            self.assertEqual(prepare.call_args.args[0], self.config)
        finally:
            os.chdir(old)

    def test_invalid_timeout_and_workflow_refuse_before_preflight_or_logs(self):
        for timeout in (0, -1, float('inf'), float('-inf'), float('nan'), 3600.01, True, '5'):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.prepare(timeout)
        with self.assertRaises(ValueError):
            self.prepare(command='collect')
        for value in ('0', '-1', 'nan', 'inf', '3601', 'bad'):
            with self.subTest(value=value):
                self.assertEqual(self.main('backfill', '--timeout-seconds', value), 2)
        self.preflight.assert_not_called()
        self.assertFalse((self.project / 'logs').exists())

    def test_missing_or_unverified_runtime_refuses_before_logs(self):
        for error in (FileNotFoundError('release missing'), ValueError('runtime tampered')):
            with self.subTest(error=error):
                self.preflight.side_effect = error
                self.assertEqual(self.main('backfill'), 2)
                self.assertFalse((self.project / 'logs').exists())
        self.preflight.side_effect = None
        value = json.loads(self.config.read_text())
        value['acquisition']['mode'] = 'fixture'
        value['runtime'] = {'kind': 'fixture', 'fixture_id': 'test'}
        self.config.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_invocation_collision_does_not_overwrite_or_retry(self):
        with patch.object(self.launcher, 'uuid4', return_value=__import__('uuid').UUID(int=1)):
            first = self.prepare()
            before = {path.name: path.read_bytes() for path in first.directory.iterdir()}
            with self.assertRaises(FileExistsError):
                self.prepare()
        self.assertEqual({path.name: path.read_bytes() for path in first.directory.iterdir()}, before)

    def test_exclusive_file_cannot_overwrite(self):
        target = self.root / 'evidence'
        target.write_bytes(b'prior evidence')
        with self.assertRaises(FileExistsError):
            self.launcher.write_exclusive(target, b'new')
        self.assertEqual(target.read_bytes(), b'prior evidence')

    def test_preparation_failures_return_two_retain_evidence_and_never_dispatch(self):
        real_open = os.open
        for stage in ('mkdir', 'write', 'fsync', 'stdout', 'stderr'):
            with self.subTest(stage=stage):
                if stage == 'mkdir':
                    fault = patch.object(self.launcher.Path, 'mkdir', side_effect=OSError('mkdir failed'))
                elif stage == 'write':
                    fault = patch.object(self.launcher, 'write_exclusive', side_effect=OSError('write failed'))
                elif stage == 'fsync':
                    fault = patch.object(self.launcher.os, 'fsync', side_effect=OSError('fsync failed'))
                else:
                    def open_file(path, *args, **kwargs):
                        if Path(path).name == stage + '.jsonl':
                            raise OSError('stream open failed')
                        return real_open(path, *args, **kwargs)
                    fault = patch.object(self.launcher.os, 'open', side_effect=open_file)
                with fault:
                    self.assertEqual(self.main('backfill'), 2)
                self.engine.assert_not_called()
                self.stores.assert_not_called()
                self.http.assert_not_called()
                self.assertFalse((self.project / 'data').exists())
        self.assertTrue(any((self.project / 'logs').glob('*/*/config.json')))

    def test_pre_dispatch_archive_reopen_failure_retains_prepared_bytes(self):
        invocation = self.prepare()
        before = {path.name: path.read_bytes() for path in invocation.directory.iterdir()}
        real_open = self.launcher.os.open
        def fail_stderr(path, *args, **kwargs):
            if Path(path).name == 'stderr.jsonl':
                raise OSError('cannot reopen prepared stream')
            return real_open(path, *args, **kwargs)
        with patch.object(self.launcher.os, 'open', side_effect=fail_stderr), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.launcher.run_invocation(invocation), 2)
        self.engine.assert_not_called()
        self.assertEqual({path.name: path.read_bytes() for path in invocation.directory.iterdir()}, before)

    def test_expired_invocation_refuses_before_open_or_dispatch(self):
        from dataclasses import replace
        invocation = replace(self.prepare(), deadline=datetime.now(timezone.utc) - timedelta(seconds=1))
        with patch.object(self.launcher.os, 'open', side_effect=AssertionError('opened stream')), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.launcher.run_invocation(invocation), 2)
        self.engine.assert_not_called()

    def test_reused_descendant_pid_does_not_signal_new_process_group(self):
        with patch.object(self.launcher, '_process_tree', return_value={42: (1, 42, b'new birth')}), \
                patch.object(self.launcher.os, 'killpg') as kill:
            self.assertTrue(self.launcher._cleanup_descendants({42: (42, b'old birth')}))
        kill.assert_not_called()

    def test_reused_engine_pid_cannot_adopt_unrelated_children(self):
        remembered = {42: (42, b'old birth')}
        with patch.object(self.launcher, '_process_tree', return_value={
                42: (1, 42, b'new birth'), 43: (42, 43, b'unrelated child')}):
            self.launcher._remember_descendants(42, remembered)
        self.assertEqual(remembered, {42: (42, b'old birth')})


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        path = PROJECT / 'scripts/local-bootstrap.py'
        self.assertTrue(path.is_file(), 'Task 11 requires a stdlib-only release selector')
        spec = importlib.util.spec_from_file_location('local_bootstrap_test', path)
        self.bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bootstrap)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.directory = self.root / 'releases' / ('sha256=' + 'a' * 64)
        (self.directory / 'venv/bin').mkdir(parents=True)
        (self.directory / 'venv/bin/python').touch()
        (self.directory / 'release.json').write_text('{}')
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'config_version': 'sec-local-config-v1',
            'runtime': {'kind': 'native', 'release_manifest': str(self.directory / 'release.json')}}))

    def main(self, *args):
        with contextlib.redirect_stderr(io.StringIO()):
            return self.bootstrap.main(list(args))

    def test_bootstrap_execs_native_flags_and_original_argv_with_clean_environment(self):
        original = ['daily', '--config', str(self.config), '--timeout-seconds', '23.5']
        with patch.object(self.bootstrap.os, 'execve') as execute, patch.dict(os.environ,
                {'PYTHONPATH': '/malicious', 'PYTHONHOME': '/wrong', 'UV_PROJECT_ENVIRONMENT': '/wrong'}):
            self.main(*original)
        python, argv, environment = execute.call_args.args
        self.assertEqual(python, str(self.directory / 'venv/bin/python'))
        self.assertEqual(argv, [*native_python_argv(Path(python)), '-m', 'sec_edgar_ingest.local_cli',
                               '--project-root', str(PROJECT), *original])
        self.assertFalse(any(key.startswith(('PYTHON', 'UV_')) for key in environment))

    def test_malformed_and_ambiguous_selection_never_executes(self):
        bodies = ['[]', '{}', '{"runtime":NaN}',
            '{"runtime":{},"runtime":{}}',
            json.dumps({'config_version': 'sec-local-config-v1', 'runtime': {
                'kind': 'native', 'release_manifest': str(self.root / 'release.json')}}),
            json.dumps({'config_version': 'sec-local-config-v1', 'runtime': {
                'kind': 'fixture', 'fixture_id': 'test'}})]
        with patch.object(self.bootstrap.os, 'execve') as execute:
            for body in bodies:
                self.config.write_text(body)
                with self.subTest(body=body):
                    self.assertEqual(self.main('backfill', '--config', str(self.config)), 2)
            execute.assert_not_called()
        self.assertFalse((self.root / 'data').exists())

    def test_internal_project_root_cannot_be_supplied_in_original_argv(self):
        with patch.object(self.bootstrap.os, 'execve') as execute:
            for option in (['--project-root', '/wrong'], ['--project-root=/wrong']):
                self.assertEqual(self.main('backfill', '--config', str(self.config), *option), 2)
            execute.assert_not_called()

    def test_bootstrap_contains_no_application_import_or_setup(self):
        import ast
        tree = ast.parse((PROJECT / 'scripts/local-bootstrap.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name.split('.')[0] in __import__('sys').stdlib_module_names
                                    for alias in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertIn(node.module.split('.')[0], __import__('sys').stdlib_module_names)
        shell = (PROJECT / 'scripts/sec-edgar-local').read_text()
        self.assertNotIn('uv ', shell)
        self.assertNotIn('pip ', shell)


class InstalledLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (PROJECT / 'scripts/local-bootstrap.py').is_file():
            return
        from support_release import proof_releases
        cls.release, _ = proof_releases(PROJECT, PROJECT / 'releases/artifact-cache')

    def setUp(self):
        self.assertTrue((PROJECT / 'scripts/sec-edgar-local').is_file(),
                        'Task 11 requires project shell launcher')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'
        (self.project / 'scripts').mkdir(parents=True)
        (self.project / 'conf').mkdir()
        for name in ('sec-edgar-local', 'local-bootstrap.py'):
            shutil.copy2(PROJECT / 'scripts' / name, self.project / 'scripts' / name)
        (self.project / '.venv').symlink_to(PROJECT / '.venv', target_is_directory=True)
        value = fixture_settings().to_mapping()
        value['acquisition'] = {'mode': 'live'}
        value['runtime'] = {'kind': 'native', 'release_manifest': str(self.release.directory / 'release.json')}
        value['etl']['parser_version'] = 'sec-index-parser-v1'
        value['storage']['root'] = '../data'
        value['logging']['root'] = '../logs'
        self.config = self.project / 'conf/sec-edgar-local.json'
        self.config.write_text(json.dumps(value))
        self.poison = self.root / 'poison'
        self.poison.mkdir()
        (self.poison / 'sec_edgar_ingest').mkdir()
        (self.poison / 'sec_edgar_ingest/__init__.py').write_text('raise RuntimeError("checkout import")')
        (self.poison / 'sitecustomize.py').write_text('raise RuntimeError("inherited path")')
        self.environment = dict(os.environ, PYTHONPATH=str(self.poison), PYTHONHOME='/absent',
                                PYTHONPYCACHEPREFIX=str(self.poison), UV_OFFLINE='1',
                                UV_PYTHON_DOWNLOADS='never')

    def test_shell_finds_default_outside_checkout_and_archives_real_installed_release(self):
        # An expired preparation deadline proves real installed dispatch selection
        # without authorizing any live engine/network work in this bootstrap test.
        result = subprocess.run([str(self.project / 'scripts/sec-edgar-local'), 'backfill',
            '--timeout-seconds', '0.000001'],
            cwd=self.poison, env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')
        event = json.loads(result.stderr)
        self.assertEqual(event['error'], 'deadline expired before engine dispatch')
        record = json.loads(Path(event['invocation']).read_bytes())
        self.assertEqual(record['release_id'], self.release.release_id)
        self.assertEqual(record['original_config_path'], str(self.config))
        self.assertEqual(record['argv'][:5], native_python_argv(self.release.python))
        self.assertEqual(record['config_sha256'], load_config(self.config).config_sha256)
        self.assertFalse((self.project / 'data').exists())
        probe = subprocess.run([*native_python_argv(self.release.python), '-c',
            'import sec_edgar_ingest,sys,json; print(json.dumps([sec_edgar_ingest.__file__,sys.flags.isolated,sys.dont_write_bytecode,sys.pycache_prefix]))'],
            cwd=self.poison, env=self.environment, capture_output=True, text=True, check=True)
        origin, isolated, no_bytecode, prefix = json.loads(probe.stdout)
        self.assertTrue(Path(origin).is_relative_to(self.release.directory / 'venv'))
        self.assertEqual((isolated, no_bytecode, prefix), (1, True, os.devnull))

    def test_installed_preflight_refuses_tamper_before_logs_or_store(self):
        receipt = self.release.directory / 'installation.json'
        original = receipt.read_bytes()
        try:
            receipt.write_bytes(b'{}')
            result = subprocess.run([str(self.project / 'scripts/sec-edgar-local'), 'backfill', '--config', str(self.config)],
                cwd=self.poison, env=self.environment, capture_output=True, text=True, timeout=30)
        finally:
            receipt.write_bytes(original)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('receipt', json.loads(result.stderr)['error'])
        self.assertFalse((self.project / 'logs').exists())
        self.assertFalse((self.project / 'data').exists())

    def test_native_fixture_still_requires_current_process_bytecode_policy(self):
        value = json.loads(self.config.read_bytes())
        value['acquisition']['mode'] = 'fixture'
        self.config.write_text(json.dumps(value))
        result = subprocess.run([str(self.release.python), '-I', '-B', '-m', 'sec_edgar_ingest.local_cli',
            '--project-root', str(self.project), 'backfill', '--config', str(self.config)],
            cwd=self.poison, env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('bytecode', json.loads(result.stderr)['error'])
        self.assertFalse((self.project / 'logs').exists())
        self.assertFalse((self.project / 'data').exists())

    def test_missing_release_refuses_without_install_or_download(self):
        value = json.loads(self.config.read_bytes())
        value['runtime']['release_manifest'] = str(self.root / 'releases' / ('sha256=' + 'b' * 64) / 'release.json')
        self.config.write_text(json.dumps(value))
        result = subprocess.run([str(self.project / 'scripts/sec-edgar-local'), 'daily'],
            cwd=self.poison, env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)['outcome'], 'configuration')
        self.assertFalse((self.project / 'logs').exists())
        self.assertFalse((self.project / 'data').exists())


if __name__ == '__main__':
    unittest.main()
