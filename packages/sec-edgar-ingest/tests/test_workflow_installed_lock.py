from network_guard import install
install()

from sec_edgar_ingest.models import to_mapping_value
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from locked_proof import (
    assert_inventory, locked_requirements, marker_environment, inventory, verify_inventory,
    package_inventory,
)
from sec_edgar_ingest.models import canonical_json


def small_lock_and_export():
    first, second = 'a' * 64, 'b' * 64
    lock = f'''version = 1
[[package]]
name = "sec-edgar-ingest"
version = "0.2.0"
source = {{ editable = "packages/sec-edgar-ingest" }}
dependencies = [{{name="requests"}}, {{name="pycparser", marker="implementation_name != 'PyPy'"}}]
[[package]]
name = "requests"
version = "2.34.2"
source = {{registry="https://pypi.org/simple"}}
wheels = [{{hash="sha256:{first}"}}]
[[package]]
name = "pycparser"
version = "3.0"
source = {{registry="https://pypi.org/simple"}}
wheels = [{{hash="sha256:{second}"}}]
'''.encode()
    export = (f'requests==2.34.2 --hash=sha256:{first}\n'
              f"pycparser==3.0 ; implementation_name != 'PyPy' --hash=sha256:{second}\n")
    return lock, export


class InstalledProofArgumentsTests(unittest.TestCase):
    def test_obsolete_artifact_options_refuse_before_proofs_or_output(self):
        import contextlib
        import io
        import workflow_proof
        repo = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            for mode, flags in (('installed', ['--wheel', str(repo / 'uv.lock')]),
                                ('installed', ['--reviewed-source', str(repo / 'conf')]),
                                ('installed', ['--wheel', str(repo / 'uv.lock'),
                                               '--reviewed-source', str(repo / 'conf')]),
                                ('native', ['--wheel', str(repo / 'uv.lock'),
                                            '--reviewed-source', str(repo / 'conf')])):
                output = Path(directory) / 'proof'
                with self.subTest(mode=mode, flags=flags), patch('support_release.proof_releases') as build:
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as refusal:
                        workflow_proof.main([mode, '--output', str(output), *flags])
                    self.assertEqual(refusal.exception.code, 2)
                    build.assert_not_called()
                    self.assertFalse(output.exists())

    def test_installed_python_api_accepts_only_its_actual_output_target(self):
        import inspect
        from workflow_proof import installed
        self.assertEqual(list(inspect.signature(installed).parameters), ['output'])

    def test_installed_cli_needs_only_output_for_current_proofs(self):
        import contextlib
        import io
        import workflow_proof
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'proof'
            with patch.object(workflow_proof, 'installed', return_value={'exit': 0, 'releases': []}) as run:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    try:
                        code = workflow_proof.main(['installed', '--output', str(output)])
                    except SystemExit:
                        self.fail('current A/B proof CLI still requires ignored artifact arguments')
            self.assertEqual(code, 0)
            run.assert_called_once_with(output.resolve())


class InstalledLockTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[3]
        self.lock = (self.repo / 'uv.lock').read_bytes()
        import subprocess
        self.export = subprocess.run(['uv', 'export', '--offline', '--locked', '--package',
            'sec-edgar-ingest', '--no-dev', '--no-emit-workspace', '--format', 'requirements.txt'],
            cwd=self.repo, check=True, capture_output=True, text=True).stdout
        self.environment = marker_environment()

    def test_complete_accepted_graph_rejects_wrong_transitive_with_direct_pins_intact(self):
        expected = locked_requirements(self.lock, self.export, self.environment)
        self.assertEqual(expected['requests'], '2.34.2')
        self.assertEqual(expected['pyarrow'], '25.0.1')
        self.assertTrue({'urllib3', 'certifi', 'charset-normalizer', 'idna'} <= expected.keys())
        self.assertFalse(any(name.startswith(('azure', 'msal')) for name in expected))
        actual = dict(expected, **{'sec-edgar-ingest': '0.2.0'})
        actual['urllib3'] = '2.7.0'
        for direct in ('pyarrow', 'requests'):
            self.assertEqual(actual[direct], expected[direct])
        with self.assertRaisesRegex(ValueError, 'installed dependency set'):
            assert_inventory(expected, actual, '0.2.0')

    def test_exact_set_rejects_missing_and_extra_distribution(self):
        expected = locked_requirements(self.lock, self.export, self.environment)
        for actual in (dict(expected), dict(expected, **{'sec-edgar-ingest': '0.2.0', 'unrequested': '1.0'})):
            with self.assertRaisesRegex(ValueError, 'installed dependency set'):
                assert_inventory(expected, actual, '0.2.0')
        self.assertIsNone(assert_inventory(expected, dict(expected, **{'sec-edgar-ingest': '0.2.0'}), '0.2.0'))

    def test_marker_exclusion_does_not_drop_other_transitives(self):
        lock, export = small_lock_and_export()
        cpython = dict(self.environment, implementation_name='cpython', platform_python_implementation='CPython')
        pypy = dict(self.environment, implementation_name='PyPy', platform_python_implementation='PyPy')
        self.assertEqual(locked_requirements(lock, export, cpython), {'requests': '2.34.2', 'pycparser': '3.0'})
        self.assertEqual(locked_requirements(lock, export, pypy), {'requests': '2.34.2'})

    def test_frozen_export_hash_or_transitive_omission_refuses(self):
        lock, export = small_lock_and_export()
        for altered in (export.replace('a' * 64, 'c' * 64),
                        export.splitlines()[0] + '\n',
                        export.replace("implementation_name != 'PyPy'", "unknown_name == 'anything'")):
            with self.assertRaises(ValueError):
                locked_requirements(lock, altered, self.environment)

    def test_inventory_checks_exact_files_and_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'proof.json').write_bytes(b'{}')
            (root / 'sha256.json').write_bytes(canonical_json(to_mapping_value(inventory(root))))
            verify_inventory(root)
            (root / 'extra.json').write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'inventory membership'):
                verify_inventory(root)
            (root / 'extra.json').unlink()
            (root / 'proof.json').write_bytes(b'{"altered":true}')
            with self.assertRaisesRegex(ValueError, 'inventory bytes'):
                verify_inventory(root)

    def test_package_inventory_includes_py_typed_and_all_data_and_excludes_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'sec_edgar_ingest'
            package.mkdir()
            (package / '__init__.py').write_bytes(b'__version__="0.2.0"\n')
            (package / 'py.typed').write_bytes(b'')
            (package / 'schema.bin').write_bytes(b'production retained data')
            cache = package / '__pycache__'
            cache.mkdir()
            (cache / 'module.pyc').write_bytes(b'cache is not source')
            before = package_inventory(root)
            self.assertEqual(set(before), {'sec_edgar_ingest/__init__.py',
                'sec_edgar_ingest/py.typed', 'sec_edgar_ingest/schema.bin'})
            self.assertEqual(before['sec_edgar_ingest/py.typed']['bytes'], 0)
            (package / 'py.typed').write_bytes(b'changed marker')
            after = package_inventory(root)
            self.assertEqual(set(after), set(before))
            self.assertNotEqual(after, before)
            (package / 'schema.bin').unlink()
            self.assertNotEqual(set(package_inventory(root)), set(before))


class ProofInputsTests(unittest.TestCase):
    def test_explicit_verifier_harness_wins_over_conflicting_inherited_catalog(self):
        import json
        import shutil
        import subprocess
        from locked_proof import inventory
        from sec_edgar_ingest.runtime import isolated_environment, native_python_argv
        from support_release import proof_releases
        from workflow_proof import harness_files
        project = Path(__file__).resolve().parents[3]
        a, b = proof_releases(project, project / 'releases/artifact-cache')
        accepted_before = inventory(a.directory)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path(__file__).parent
            for name in ('explicit', 'catalog'):
                harness = root / name
                for path in harness_files():
                    target = harness / path.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                with (harness / 'workflow_proof.py').open('a') as stream:
                    stream.write('\ndef sequence(output, *, release_manifest=None):\n'
                        '    return ' + repr({'exit': 0, 'harness_probe': name}) + '\n')
                with (harness / 'network_guard.py').open('a') as stream:
                    stream.write('\n_original_install = install\ndef install():\n'
                        '    _original_install()\n    from pathlib import Path\n'
                        '    with Path(' + repr(str(root / (name + '-guard.log'))) + ').open("a") as stream:\n'
                        '        stream.write("guard installed\\n")\n')
            catalog = root / 'catalog.json'
            catalog.write_text(json.dumps({'format_version': 'sec-local-proof-catalog-v1',
                'a_manifest': str(a.directory / 'release.json'), 'b_manifest': str(b.directory / 'release.json'),
                'harness': str(root / 'catalog')}))
            evidence = root / 'evidence'
            environment = dict(isolated_environment(), SEC_LOCAL_PROOF_CATALOG=str(catalog))
            done = subprocess.run([*native_python_argv(a.python), str(project / 'scripts/verify-native-release.py'),
                '--release', str(a.directory), '--harness', str(root / 'explicit'), '--evidence', str(evidence)],
                cwd=root, env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            report = json.loads((evidence / 'report.json').read_text())
            self.assertEqual(report['sequence']['harness_probe'], 'explicit',
                             'inherited catalog silently replaced the declared verifier harness')
            self.assertTrue((root / 'explicit-guard.log').is_file())
            self.assertFalse((root / 'catalog-guard.log').exists(), 'guard and executed harness must agree')
        self.assertEqual(inventory(a.directory), accepted_before)

    def test_upgrade_missing_runtime_probe_uses_disposable_release_paths(self):
        import json
        import subprocess
        import workflow_proof
        from support_release import proof_releases
        project = Path(__file__).resolve().parents[3]
        a, b = proof_releases(project, project / 'releases/artifact-cache')
        accepted_before = {release.release_id: inventory(release.directory) for release in (a, b)}
        actual_run = subprocess.run
        commands = []
        def checked_run(argv, **kwargs):
            if any('installed_upgrade_cases' in str(item) for item in argv):
                commands.append(argv)
                self.assertNotEqual(Path(argv[-2]), a.directory / 'release.json',
                    'missing-runtime upgrade proof must not rename catalog release A')
                self.assertNotEqual(Path(argv[-1]), b.directory / 'release.json')
                self.assertTrue(a.python.is_file())
                self.assertTrue(b.python.is_file())
                return subprocess.CompletedProcess(argv, 0, json.dumps({'exit': 0}), '')
            return actual_run(argv, **kwargs)
        with tempfile.TemporaryDirectory() as directory, patch.object(workflow_proof.subprocess, 'run', checked_run):
            report = workflow_proof.upgrade_sequence(Path(directory), a.directory / 'release.json',
                                                      b.directory / 'release.json')
        self.assertEqual(report['exit'], 0)
        self.assertEqual(len(commands), 1)
        self.assertEqual({release.release_id: inventory(release.directory) for release in (a, b)},
                         accepted_before, 'upgrade proof mutated supplied catalog release content')

    def test_relative_cache_override_is_refused_before_setup(self):
        import os
        from support_release import proof_releases
        with patch.dict(os.environ, {'SEC_LOCAL_PROOF_CACHE': 'relative/cache', 'SEC_LOCAL_PROOF_CATALOG': ''}), \
             patch('support_release.prepare_artifact_cache') as prepare:
            with self.assertRaisesRegex(ValueError, 'absolute'):
                proof_releases(Path(__file__).resolve().parents[3], Path('/unused'))
            prepare.assert_not_called()

    def test_missing_override_cache_fails_without_fetching(self):
        import os
        from support_release import proof_releases
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'absent'
            with patch.dict(os.environ, {'SEC_LOCAL_PROOF_CACHE': str(cache), 'SEC_LOCAL_PROOF_CATALOG': ''}):
                with self.assertRaisesRegex(ValueError, 'artifact cache absent'):
                    proof_releases(Path(__file__).resolve().parents[3], Path('/unused'))
            self.assertFalse(cache.exists())

    def test_catalog_requires_exact_versioned_absolute_inputs(self):
        import json, os
        from support_release import proof_releases
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / 'catalog.json'
            base = {'format_version': 'sec-local-proof-catalog-v1',
                    'a_manifest': '/missing/a/release.json', 'b_manifest': '/missing/b/release.json',
                    'harness': str(Path(__file__).parent.resolve())}
            invalid = [dict(base, format_version='old'), dict(base, extra='bad'),
                       dict(base, a_manifest='relative.json'), dict(base, harness='relative')]
            for value in invalid:
                catalog.write_text(json.dumps(value))
                with self.subTest(value=value), patch.dict(os.environ, {'SEC_LOCAL_PROOF_CATALOG': str(catalog)}), \
                     patch('support_release.prepare_artifact_cache') as prepare:
                    with self.assertRaises(ValueError):
                        proof_releases(Path(__file__).resolve().parents[3], Path('/unused'))
                    prepare.assert_not_called()

    def test_installed_selected_harness_runs_with_real_release_and_transitive_tamper(self):
        import json, os, shutil
        from support_release import proof_releases
        from workflow_proof import installed
        project = Path(__file__).resolve().parents[3]
        a, b = proof_releases(project, project / 'releases/artifact-cache')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / 'selected-harness'
            shutil.copytree(Path(__file__).parent, harness, ignore=shutil.ignore_patterns('__pycache__'))
            # The selected support must execute, not merely pass schema validation.
            with (harness / 'workflow_proof.py').open('a') as stream:
                stream.write("\n_original_sequence = sequence\ndef sequence(*args, **kwargs):\n"
                    "    report = dict(_original_sequence(*args, **kwargs))\n"
                    "    report['selected_harness_probe'] = 'executed'\n    return report\n")
            catalog = root / 'catalog.json'
            catalog.write_text(json.dumps({'format_version': 'sec-local-proof-catalog-v1',
                'a_manifest': str(a.directory / 'release.json'), 'b_manifest': str(b.directory / 'release.json'),
                'harness': str(harness)}))
            with patch.dict(os.environ, {'SEC_LOCAL_PROOF_CATALOG': str(catalog)}):
                report = installed(root / 'evidence')
            self.assertEqual(report['exit'], 0)
            for release in report['releases']:
                self.assertEqual(release['sequence']['selected_harness_probe'], 'executed')
                self.assertEqual(len(release['command_help']), 11)
                self.assertFalse(release['pythonpath_present'])
                self.assertIn('sec_edgar_ingest/py.typed', release['payload'])
                self.assertFalse(any('azure' in name.lower() or 'msal' in name.lower()
                                     for name in release['payload']))
            self.assertEqual(report['wrong_transitive']['actual_transitive'], '0.0.0')
            self.assertEqual(report['wrong_transitive']['direct_pins'], {'requests': '2.34.2', 'pyarrow': '25.0.1'})
