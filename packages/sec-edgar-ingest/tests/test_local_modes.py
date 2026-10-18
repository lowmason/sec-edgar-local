"""Explicit source modes and runtime checks refuse before store or HTTP creation."""
from network_guard import install
install()

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from support import ACQUISITION_PACK, local_config_mapping
from sec_edgar_ingest.cli import main


class LocalModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.mapping = local_config_mapping(root=self.root / 'state')
        self.mapping['etl']['parser_version'] = 'sec-index-parser-v1'
        self.deadline = (datetime.now(timezone.utc) + timedelta(seconds=1800)).isoformat()

    def argv(self, command='discover', *, pack=True):
        args = [command, '--config', str(self.config)]
        if command in ('discover', 'collect', 'transform', 'publish', 'backfill', 'daily', 'reconcile'):
            args += ['--run-id', 'r', '--execution-id', 'e', '--attempt-id', 'a', '--deadline', self.deadline]
        if command == 'discover':
            args += ['--mode', 'quarterly', '--discovery-id', 'd']
        elif command in ('collect', 'transform', 'publish'):
            kind = {'collect': 'source', 'transform': 'snapshot', 'publish': 'transformed'}[command]
            args += ['--workset', 'worksets/sec/' + kind + '/sha256=' + 'a' * 64 + '/workset.json']
        elif command == 'history':
            args += ['--quarter', '2026Q4']
        elif command == 'approve':
            args += ['--quarter', '2026Q4', '--generation', 'a' * 64,
                     '--quarterly-sha256', 'b' * 64, '--approver', 'Local approver']
        elif command == 'rollback':
            args += ['--quarter', '2026Q4', '--from-generation', 'a' * 64,
                     '--to-generation', 'b' * 64, '--reason', 'bad correction', '--operator', 'Local operator']
        if pack and command in ('discover', 'collect', 'backfill', 'daily', 'reconcile'):
            args += ['--fixture-pack', str(ACQUISITION_PACK)]
        return args

    def invoke_refused(self, argv):
        self.config.write_text(json.dumps(self.mapping))
        output, errors = io.StringIO(), io.StringIO()
        with patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')) as stores, \
                patch('sec_edgar_ingest.cli.BoundedSender', side_effect=AssertionError('constructed HTTP')) as sender, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                code = main(argv)
            except SystemExit as error:
                code = error.code
        self.assertEqual(code, 2, errors.getvalue())
        stores.assert_not_called()
        sender.assert_not_called()
        return errors.getvalue()

    def native(self):
        self.mapping['runtime'] = {'kind': 'native', 'release_manifest': str(self.root / 'releases' / ('sha256=' + 'a' * 64) / 'release.json')}

    def test_native_current_runtime_is_checked_before_any_command_store(self):
        self.native()
        for command in ('discover', 'collect', 'transform', 'publish', 'backfill', 'daily', 'reconcile', 'candidates', 'history', 'approve', 'rollback'):
            with self.subTest(command=command):
                self.invoke_refused(self.argv(command))

    def test_fixture_requires_valid_pack_before_stores(self):
        self.invoke_refused(self.argv(pack=False))
        args = self.argv()
        args[-1] = str(self.root / 'corrupt.json')
        Path(args[-1]).write_text('{}')
        self.invoke_refused(args)

    def test_live_refuses_each_fixture_marker_before_stores(self):
        original = json.loads(json.dumps(self.mapping))
        for marker in ('pack', 'clock', 'deadline', 'parser', 'runtime'):
            with self.subTest(marker=marker):
                self.mapping = json.loads(json.dumps(original))
                self.mapping['acquisition']['mode'] = 'live'
                self.mapping.pop('fixture', None)
                self.native()
                args = self.argv(pack=marker == 'pack')
                if marker == 'clock': args += ['--today', '2026-10-01']
                elif marker == 'deadline': self.mapping['fixture'] = {'allow_deadline_override': True}
                elif marker == 'parser': self.mapping['etl']['parser_version'] = 'fixture-index-parser-v1'
                elif marker == 'runtime': self.mapping['runtime'] = original['runtime']
                self.invoke_refused(args)

    def test_probe_failure_is_a_configuration_refusal_before_stores(self):
        import subprocess
        self.native()
        with patch('sec_edgar_ingest.cli.preflight_current', side_effect=subprocess.CalledProcessError(1, ['python'])):
            self.invoke_refused(self.argv('candidates'))

    def test_unknown_fixture_parser_refused_for_etl_before_stores(self):
        self.mapping['etl']['parser_version'] = 'unsupported-parser'
        self.invoke_refused(self.argv('transform'))


class NativeCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support_release import proof_releases
        cls.project = Path(__file__).resolve().parents[3]
        cls.a, cls.b = proof_releases(cls.project, cls.project / 'releases/artifact-cache')

    def setUp(self):
        import subprocess
        self.run_process = subprocess.run
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        value = local_config_mapping(root=self.root / 'state')
        value['runtime'] = {'kind': 'native', 'release_manifest': str(self.a.directory / 'release.json')}
        value['backfill'] = {'start_quarter': '2015Q1', 'end_quarter': '2015Q1'}
        value['etl']['parser_version'] = 'sec-index-parser-v1'
        self.config.write_text(json.dumps(value))
        self.argv = [str(self.a.directory / 'venv/bin/sec-edgar-ingest'), 'discover',
            '--config', str(self.config), '--run-id', 'native', '--execution-id', 'e', '--attempt-id', 'a',
            '--deadline', (datetime.now(timezone.utc) + timedelta(seconds=1800)).isoformat(),
            '--mode', 'quarterly', '--discovery-id', 'd', '--fixture-pack', str(ACQUISITION_PACK)]

    def invoke(self, argv=None):
        return self.run_process(argv or self.argv, cwd=self.root, capture_output=True, text=True, timeout=30)

    def test_installed_console_runs_preflight_retains_manifest_and_replays_exactly(self):
        from sec_edgar_ingest.models import canonical_json
        from sec_edgar_ingest.results import read_result
        from sec_edgar_ingest.storage import open_stores
        from sec_edgar_ingest.config import load_config
        first = self.invoke()
        self.assertEqual(first.returncode, 0, first.stderr)
        saved = json.loads(first.stdout)
        opened = open_stores(load_config(self.config), access='operator')
        self.addCleanup(opened[0].close)
        self.assertEqual(read_result(saved['result_ref'], opened[1]).context.runtime['release_sha256'], self.a.release_id)
        self.assertEqual(opened[1].read('runtime/native/sha256=' + self.a.release_id + '/release.json'), canonical_json(self.a.manifest))
        replay = self.invoke()
        self.assertEqual((replay.returncode, replay.stdout), (0, first.stdout), replay.stderr)
        from support_fs import tree_snapshot
        actual_root = Path(load_config(self.config).storage.root)
        before = tree_snapshot(actual_root)
        operator = self.invoke([self.argv[0], 'candidates', '--config', str(self.config)])
        self.assertEqual(operator.returncode, 0, operator.stderr)
        self.assertEqual(tree_snapshot(actual_root), before)
        value = json.loads(self.config.read_text())
        value['runtime']['release_manifest'] = str(self.b.directory / 'release.json')
        self.config.write_text(json.dumps(value))
        mismatch = self.invoke()
        self.assertEqual(mismatch.returncode, 2, mismatch.stderr)
        another_release = self.invoke([str(self.b.directory / 'venv/bin/sec-edgar-ingest'), *self.argv[1:]])
        self.assertEqual(another_release.returncode, 9, another_release.stderr)
        self.assertIsNone(json.loads(another_release.stdout)['result_ref'])
        self.assertEqual(read_result(saved['result_ref'], opened[1]).context.runtime['release_sha256'], self.a.release_id)

    def test_console_ignores_valid_poisoned_application_bytecode_before_first_import(self):
        import importlib.util
        from importlib._bootstrap_external import _code_to_timestamp_pyc
        source = self.a.directory / 'venv/lib/python3.14/site-packages/sec_edgar_ingest/__init__.py'
        cache = Path(importlib.util.cache_from_source(str(source)))
        old = cache.read_bytes() if cache.exists() else None
        cache.parent.mkdir(exist_ok=True)
        def restore():
            if old is None: cache.unlink(missing_ok=True)
            else: cache.write_bytes(old)
        self.addCleanup(restore)
        poison = compile('raise RuntimeError("poisoned application cache executed")', str(source), 'exec')
        cache.write_bytes(_code_to_timestamp_pyc(poison, int(source.stat().st_mtime), source.stat().st_size))
        ordinary = self.invoke([str(self.a.python), '-I', '-c', 'import sec_edgar_ingest'])
        self.assertNotEqual(ordinary.returncode, 0)
        self.assertIn('poisoned application cache executed', ordinary.stderr)
        safe = self.invoke()
        self.assertEqual(safe.returncode, 0, safe.stderr)
        self.assertEqual(json.loads(safe.stdout)['outcome'], 'success')

    def test_console_script_tamper_is_refused_by_read_only_preflight(self):
        from sec_edgar_ingest.runtime import preflight
        console = self.a.directory / 'venv/bin/sec-edgar-ingest'
        original = console.read_bytes()
        self.addCleanup(console.write_bytes, original)
        console.write_bytes(original + b'\n# tamper\n')
        with self.assertRaisesRegex(ValueError, 'console'):
            preflight(self.a.directory / 'release.json')

    def test_live_storage_only_etl_refuses_fixture_origin_before_output(self):
        from dataclasses import replace
        from sec_edgar_ingest.config import Settings, load_config, pin_context
        from sec_edgar_ingest.etl.commands import run_publish, run_transform
        from sec_edgar_ingest.storage import open_stores
        first = self.invoke()
        self.assertEqual(first.returncode, 0, first.stderr)
        source_ref = json.loads(first.stdout)['source_workset_ref']
        collect_args = [self.argv[0], 'collect', *self.argv[2:self.argv.index('--mode')],
                        '--workset', source_ref, '--fixture-pack', str(ACQUISITION_PACK)]
        collect_args[collect_args.index('--attempt-id') + 1] = 'collect'
        collected = self.invoke(collect_args)
        self.assertEqual(collected.returncode, 0, collected.stderr)
        snapshot_ref = json.loads(collected.stdout)['snapshot_workset_ref']
        transform_args = [*collect_args[:collect_args.index('--fixture-pack')]]
        transform_args[1] = 'transform'
        transform_args[transform_args.index('--attempt-id') + 1] = 'transform'
        transform_args[transform_args.index('--workset') + 1] = snapshot_ref
        transformed = self.invoke(transform_args)
        # This synthetic header is invalid for the live parser; retain its honest quarantine.
        self.assertEqual(transformed.returncode, 7, transformed.stderr)
        transformed_ref = json.loads(transformed.stdout)['transformed_workset_ref']
        fixture_settings = load_config(self.config)
        store, objects, leases = open_stores(fixture_settings)
        self.addCleanup(store.close)
        self.addCleanup(leases.close)
        from sec_edgar_ingest.etl.commands import read_etl_result
        prior = read_etl_result(json.loads(transformed.stdout)['result_ref'], objects).context
        value = fixture_settings.to_mapping()
        value['acquisition']['mode'] = 'live'
        value.pop('fixture', None)
        live = Settings.from_mapping(value)
        for command, function, reference in (('transform', run_transform, snapshot_ref), ('publish', run_publish, transformed_ref)):
            context = replace(prior, command=command, config_sha256=live.config_sha256,
                              effective_config={}, pinned_on=None, attempt_id='live-' + command)
            context = pin_context(live, context, prior.pinned_on)[0]
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'fixture|acquisition'):
                function(reference, context, live, objects, store)

    def test_native_module_and_console_report_fork_version(self):
        from sec_edgar_ingest.runtime import native_python_argv
        for argv in ([self.argv[0], '--version'], [*native_python_argv(self.a.python), '-m', 'sec_edgar_ingest', '--version']):
            done = self.invoke(argv)
            self.assertEqual((done.returncode, done.stdout.strip(), done.stderr), (0, '0.2.0', ''))

    def test_local_live_mode_selects_bounded_sender_with_real_clock(self):
        from sec_edgar_ingest.runtime import native_python_argv
        value = json.loads(self.config.read_text())
        value['acquisition']['mode'] = 'live'
        value.pop('fixture', None)
        self.config.write_text(json.dumps(value))
        code = ('import sys; from unittest.mock import patch; '
                'import sec_edgar_ingest.cli as cli\n'
                'with patch.object(cli, "BoundedSender", side_effect=RuntimeError("selected live sender")) as sender, '
                'patch.object(cli.FixturePack, "load", side_effect=AssertionError("live loaded fixture")):\n'
                ' result=cli.main(sys.argv[1:])\n'
                ' sender.assert_called_once()\n'
                ' assert sender.call_args.args[0].acquisition.mode == "live"\n'
                ' assert type(sender.call_args.args[1]) is cli.Clock\n'
                ' assert result == 9\n')
        args = self.argv[1:self.argv.index('--fixture-pack')]
        done = self.invoke([*native_python_argv(self.a.python), '-c', code, *args])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['outcome'], 'internal_error')
        self.assertIn('selected live sender', done.stderr)
