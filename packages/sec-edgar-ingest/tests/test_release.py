"""Release setup contracts; package fetching is never part of these tests."""
import hashlib
import importlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch


class ReleaseUnitTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('sec_edgar_ingest.release'),
                             'Task 7 requires explicit immutable release setup')
        self.release = importlib.import_module('sec_edgar_ingest.release')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def wheel(self, members):
        path = self.root / 'sec_edgar_ingest-0.2.0-py3-none-any.whl'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w') as archive:
                for name, body in members:
                    archive.writestr(name, body)
        return path

    def test_payload_includes_sorted_resources_and_type_marker(self):
        wheel = self.wheel([('sec_edgar_ingest/z.json', b'{}'),
                            ('sec_edgar_ingest/py.typed', b''),
                            ('sec_edgar_ingest/__init__.py', b'__version__="0.2.0"'),
                            ('sec_edgar_ingest-0.2.0.dist-info/METADATA', b'Name: sec-edgar-ingest\nVersion: 0.2.0\n')])
        self.assertEqual(self.release.wheel_payload(wheel), [
            {'path': name, 'sha256': hashlib.sha256(body).hexdigest()}
            for name, body in sorted([('sec_edgar_ingest/z.json', b'{}'),
                                     ('sec_edgar_ingest/py.typed', b''),
                                     ('sec_edgar_ingest/__init__.py', b'__version__="0.2.0"')])])

    def test_unsafe_or_duplicate_members_refused(self):
        for name in ('../escape', '/absolute', 'sec_edgar_ingest/../escape', 'sec_edgar_ingest\\bad', 'sec_edgar_ingest//bad'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.release.wheel_payload(self.wheel([(name, b'x')]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.release.wheel_payload(self.wheel([('sec_edgar_ingest/a', b'1'), ('sec_edgar_ingest/a', b'2')]))

    def repository(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / 'tracked').write_text('base')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Proof', '-c', 'user.email=proof@example.invalid', 'commit', '-qm', 'base'], check=True)

    def test_dirty_untracked_and_uncommitted_source_refused_before_setup(self):
        self.repository()
        for path in ('tracked', 'new.py'):
            with self.subTest(path=path):
                target = self.root / path
                target.write_text('changed')
                with self.assertRaisesRegex(ValueError, 'clean committed'):
                    self.release.build_release(self.root, self.root / 'releases', python=Path(sys.executable), artifact_cache=self.root / 'absent', offline=True)
                if path == 'tracked':
                    target.write_text('base')
                else:
                    target.unlink()
        with tempfile.TemporaryDirectory() as empty, self.assertRaises((ValueError, subprocess.CalledProcessError)):
            self.release.build_release(Path(empty), self.root / 'releases', python=Path(sys.executable), artifact_cache=self.root / 'absent', offline=True)

    def test_stale_lock_refused_before_artifact_or_install(self):
        self.repository()
        real_run = subprocess.run
        def run(argv, **kwargs):
            if argv[:3] == ['uv', 'lock', '--check']:
                raise subprocess.CalledProcessError(1, argv, stderr='lock needs update')
            return real_run(argv, **kwargs)
        with patch.object(self.release.subprocess, 'run', side_effect=run), self.assertRaises(subprocess.CalledProcessError):
            self.release.build_release(self.root, self.root / 'releases', python=Path(sys.executable), artifact_cache=self.root / 'absent', offline=True)
        self.assertFalse((self.root / 'releases').exists())

    def test_missing_offline_cache_is_explicit_setup_error(self):
        with self.assertRaisesRegex(ValueError, 'explicit.*setup'):
            self.release.prepare_artifact_cache(Path(__file__).resolve().parents[3] / 'uv.lock',
                Path(sys.executable), self.root / 'absent', offline=True)

    def test_wheel_metadata_tag_mismatch_refused(self):
        path = self.wheel([
            ('sec_edgar_ingest/__init__.py', b'__version__="0.2.0"'),
            ('sec_edgar_ingest-0.2.0.dist-info/METADATA', b'Name: sec-edgar-ingest\nVersion: 0.2.0\n'),
            ('sec_edgar_ingest-0.2.0.dist-info/WHEEL', b'Wheel-Version: 1.0\nTag: cp314-cp314-win_amd64\n')])
        with self.assertRaisesRegex(ValueError, 'tags'):
            self.release._wheel_metadata(path, 'sec-edgar-ingest', '0.2.0')


class ReleaseProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec('sec_edgar_ingest.release') is None:
            return
        from support_release import proof_releases
        cls.project = Path(__file__).resolve().parents[3]
        cls.a, cls.b = proof_releases(cls.project, cls.project / 'releases/artifact-cache')

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('sec_edgar_ingest.release'), 'Task 7 release builder absent')
        self.release = importlib.import_module('sec_edgar_ingest.release')

    def test_real_committed_a_b_releases_differ_only_with_included_resource(self):
        self.assertNotEqual(self.a.release_id, self.b.release_id)
        self.assertNotEqual(self.a.manifest['identity']['git_revision'], self.b.manifest['identity']['git_revision'])
        self.assertTrue(any(item['path'].endswith('/proof_resource.txt') for item in self.b.manifest['identity']['package_files']))
        self.assertEqual({item['name'] for item in self.a.manifest['identity']['dependencies']},
                         {'certifi', 'charset-normalizer', 'idna', 'pyarrow', 'requests', 'urllib3'})
        self.assertNotIn('uv-build', {item['name'] for item in self.a.manifest['identity']['dependencies']})

    def test_reconstruct_fresh_venv_at_another_final_location(self):
        from sec_edgar_ingest.runtime import preflight
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(self.release.subprocess, 'run', wraps=subprocess.run) as run:
                directory = self.release.reconstruct_release(self.a.directory / 'release.json', Path(temporary) / 'releases', python=Path(sys.executable))
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn(['uv', 'venv', '--python', sys.executable, str(directory / 'venv')], commands)
            self.assertIn(['uv', 'pip', 'install', '--python', str(directory / 'venv/bin/python'), '--offline', '--no-index', '--find-links', str(directory / 'artifacts'), '--require-hashes', '-r', str(directory / 'runtime-requirements.txt')], commands)
            self.assertIn(['uv', 'pip', 'install', '--python', str(directory / 'venv/bin/python'), '--offline', '--no-deps', str(directory / 'wheels' / self.a.manifest['identity']['application']['wheel_filename'])], commands)
            verified = preflight(directory / 'release.json')
            self.assertEqual(verified.release_id, self.a.release_id)
            self.assertNotEqual(verified.python, self.a.python)
            result = subprocess.run([str(verified.python), '-I', '-c', 'import sys; print(sys.prefix)'], check=True, capture_output=True, text=True)
            self.assertEqual(Path(result.stdout.strip()), directory / 'venv')
            self.assertIn(str(directory / 'venv'), (directory / 'venv/bin/sec-edgar-ingest').read_text())

    def test_artifact_tamper_is_refused_before_install_or_destination_creation(self):
        dependency = self.a.manifest['identity']['dependencies'][0]
        path = self.a.directory / 'artifacts' / dependency['filename']
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'tamper')
            with tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / 'releases'
                with patch.object(self.release.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'artifact.*hash'):
                    self.release.reconstruct_release(self.a.directory / 'release.json', destination, python=Path(sys.executable))
                run.assert_not_called()
                self.assertFalse(destination.exists())
        finally:
            path.write_bytes(original)

    def test_complete_release_reused_without_mutation_and_partial_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            releases = Path(temporary) / 'releases'
            directory = self.release.reconstruct_release(self.a.directory / 'release.json', releases, python=Path(sys.executable))
            before = (directory / 'setup.json').read_bytes()
            with patch.object(self.release.subprocess, 'run', wraps=subprocess.run) as run:
                self.assertEqual(self.release.reconstruct_release(self.a.directory / 'release.json', releases, python=Path(sys.executable)), directory)
            self.assertFalse(any(call.args[0][:2] in (['uv', 'venv'], ['uv', 'pip']) for call in run.call_args_list))
            self.assertEqual((directory / 'setup.json').read_bytes(), before)
            receipt = directory / 'installation.json'
            receipt.unlink()
            with self.assertRaisesRegex(ValueError, 'incomplete|receipt'):
                self.release.reconstruct_release(self.a.directory / 'release.json', releases, python=Path(sys.executable))
            self.assertFalse(receipt.exists())

    def test_setup_cache_declares_hash_verified_runtime_and_build_artifacts(self):
        import json
        inventory = json.loads((self.project / 'releases/artifact-cache/artifacts.json').read_text())
        entries = inventory['artifacts']
        self.assertEqual(entries, sorted(entries, key=lambda entry: (entry['role'], entry['filename'])))
        self.assertEqual({entry['role'] for entry in entries}, {'runtime', 'build'})
        self.assertEqual(len(entries), 7)
        for entry in entries:
            path = self.project / 'releases/artifact-cache' / entry['role'] / entry['filename']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry['sha256'])

    def test_failed_install_retains_unusable_partial_evidence(self):
        real_run = subprocess.run
        def run(argv, **kwargs):
            if argv[:3] == ['uv', 'pip', 'install']:
                raise subprocess.CalledProcessError(1, argv, stderr='deliberate install failure')
            return real_run(argv, **kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            releases = Path(temporary) / 'releases'
            with patch.object(self.release.subprocess, 'run', side_effect=run), self.assertRaises(subprocess.CalledProcessError):
                self.release.reconstruct_release(self.a.directory / 'release.json', releases, python=Path(sys.executable))
            partial = releases / ('sha256=' + self.a.release_id)
            self.assertTrue((partial / 'release.json').is_file())
            self.assertFalse((partial / 'installation.json').exists())
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                self.release.reconstruct_release(self.a.directory / 'release.json', releases, python=Path(sys.executable))

    def test_manifest_missing_transitive_artifact_identity_refused(self):
        import copy
        import shutil
        from sec_edgar_ingest import runtime
        from sec_edgar_ingest.models import canonical_json
        manifest = copy.deepcopy(self.a.manifest)
        manifest['identity']['dependencies'].pop()
        manifest['release_id'] = runtime.release_id(manifest['identity'])
        with tempfile.TemporaryDirectory() as temporary:
            retained = Path(temporary) / ('sha256=' + manifest['release_id'])
            retained.mkdir()
            for name in ('uv.lock', 'runtime-requirements.txt'):
                shutil.copyfile(self.a.directory / name, retained / name)
            (retained / 'release.json').write_bytes(canonical_json(manifest))
            with patch.object(self.release.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'full transitive'):
                self.release.reconstruct_release(retained / 'release.json', Path(temporary) / 'destination', python=Path(sys.executable))
            run.assert_not_called()

    def test_proof_build_uses_pinned_pep517_backend_and_clean_source(self):
        import json
        for proof in (self.a, self.b):
            setup = json.loads((proof.directory / 'setup.json').read_text())
            self.assertEqual(setup['build_backend']['version'], '0.12.24')
            self.assertIn('--force-pep517', setup['build_argv'])
            self.assertIn('--require-build-hashes', setup['build_argv'])
            self.assertNotIn('outside the range', setup['build_stderr'])
            self.assertNotIn('warning:', setup['build_stderr'])
            self.assertTrue(list((proof.directory / 'wheels').glob('*.tar.gz')))

    def test_application_hash_rechecked_after_runtime_install(self):
        real_run = subprocess.run
        application_installs = []
        def run(argv, **kwargs):
            result = real_run(argv, **kwargs)
            if argv[:3] == ['uv', 'pip', 'install']:
                if '--require-hashes' in argv:
                    directory = Path(argv[-1]).parent
                    wheel = directory / 'wheels' / self.a.manifest['identity']['application']['wheel_filename']
                    wheel.write_bytes(wheel.read_bytes() + b'tamper after dependency install')
                else:
                    application_installs.append(argv)
            return result
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(self.release.subprocess, 'run', side_effect=run), self.assertRaisesRegex(ValueError, 'wheel hash.*before installation'):
                self.release.reconstruct_release(self.a.directory / 'release.json', Path(temporary) / 'releases', python=Path(sys.executable))
            self.assertEqual(application_installs, [])

    def test_cache_only_cli_needs_no_release_destination_or_clean_project(self):
        import shutil
        script = self.project / 'scripts/prepare-native-release.py'
        with tempfile.TemporaryDirectory() as temporary:
            dirty = Path(temporary)
            shutil.copyfile(self.project / 'uv.lock', dirty / 'uv.lock')
            (dirty / 'untracked-implementation.py').write_text('intentionally uncommitted')
            result = subprocess.run([sys.executable, str(script), '--project', str(dirty),
                '--python', sys.executable, '--artifact-cache', str(self.project / 'releases/artifact-cache'),
                '--prepare-cache-only', '--offline'], check=True, capture_output=True, text=True,
                env=dict(__import__('os').environ, UV_OFFLINE='1', UV_PYTHON_DOWNLOADS='never'))
            self.assertEqual(Path(result.stdout.strip()), self.project / 'releases/artifact-cache/artifacts.json')
            self.assertFalse((dirty / 'releases').exists())

    def test_identical_committed_build_ignores_mtime_and_install_location(self):
        import os
        source = self.b.directory.parent.parent / 'source'
        package = source / 'packages/sec-edgar-ingest/src/sec_edgar_ingest/__init__.py'
        original_stat = package.stat()
        try:
            os.utime(package, (1, 1))
            with tempfile.TemporaryDirectory() as temporary:
                directory = self.release.build_release(source, Path(temporary) / 'releases',
                    python=Path(sys.executable), artifact_cache=self.project / 'releases/artifact-cache', offline=True)
                from sec_edgar_ingest.runtime import preflight
                self.assertEqual(preflight(directory / 'release.json').release_id, self.b.release_id)
                self.assertNotEqual(directory, self.b.directory)
        finally:
            os.utime(package, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    def test_actual_committed_stale_lock_fails_before_destination(self):
        source = self.b.directory.parent.parent / 'source'
        with tempfile.TemporaryDirectory() as temporary:
            clone = Path(temporary) / 'source'
            subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(source), str(clone)], check=True)
            metadata = clone / 'packages/sec-edgar-ingest/pyproject.toml'
            metadata.write_text(metadata.read_text().replace('dependencies = [', 'dependencies = ["idna==3.20", '))
            subprocess.run(['git', '-C', str(clone), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(clone), '-c', 'user.name=Proof', '-c', 'user.email=proof@example.invalid',
                            'commit', '-qm', 'Deliberate committed stale lock'], check=True)
            destination = Path(temporary) / 'releases'
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                self.release.build_release(clone, destination, python=Path(sys.executable),
                    artifact_cache=self.project / 'releases/artifact-cache', offline=True)
            self.assertEqual(raised.exception.cmd[:3], ['uv', 'lock', '--check'])
            self.assertFalse(destination.exists())

    def test_offline_cache_tamper_fails_without_an_installer(self):
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / 'cache'
            shutil.copytree(self.project / 'releases/artifact-cache', cache)
            artifact = next((cache / 'runtime').glob('requests-*.whl'))
            artifact.write_bytes(artifact.read_bytes() + b'tamper')
            with patch.object(self.release.subprocess, 'run', wraps=subprocess.run) as run:
                with self.assertRaisesRegex(ValueError, 'cached artifact hash'):
                    self.release.prepare_artifact_cache(self.project / 'uv.lock', Path(sys.executable), cache, offline=True)
            self.assertFalse(any(call.args[0][:2] == ['uv', 'pip'] for call in run.call_args_list))

    def test_builder_refuses_built_module_version_that_differs_from_distribution(self):
        source = self.b.directory.parent.parent / 'source'
        with tempfile.TemporaryDirectory() as temporary:
            clone = Path(temporary) / 'source'
            subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(source), str(clone)], check=True)
            module = clone / 'packages/sec-edgar-ingest/src/sec_edgar_ingest/__init__.py'
            module.write_text('__version__ = "0.3.0"\n')
            subprocess.run(['git', '-C', str(clone), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(clone), '-c', 'user.name=Proof', '-c', 'user.email=proof@example.invalid',
                            'commit', '-qm', 'Deliberate module/distribution version mismatch'], check=True)
            destination = Path(temporary) / 'releases'
            with self.assertRaisesRegex(ValueError, 'application.*version'):
                self.release.build_release(clone, destination, python=Path(sys.executable),
                    artifact_cache=self.project / 'releases/artifact-cache', offline=True)
            self.assertEqual(list(destination.rglob('installation.json')), [])
