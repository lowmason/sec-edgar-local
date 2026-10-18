"""Read-only installed verification against genuine offline release installations."""
import copy
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sec_edgar_ingest import runtime
from sec_edgar_ingest.models import canonical_json


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not hasattr(runtime, 'preflight'):
            return
        from support_release import proof_releases
        cls.project = Path(__file__).resolve().parents[3]
        cls.a, cls.b = proof_releases(cls.project, cls.project / 'releases/artifact-cache')

    def setUp(self):
        self.assertTrue(hasattr(runtime, 'preflight'), 'Task 7 requires read-only native installed preflight')

    def test_installed_preflight_uses_isolated_referenced_python(self):
        with patch.dict(os.environ, {'PYTHONPATH': str(self.project / 'packages/sec-edgar-ingest/src')}):
            verified = runtime.preflight(self.a.directory / 'release.json')
        self.assertEqual(verified, self.a)
        result = subprocess.run([*runtime.native_python_argv(self.a.python), '-c',
            'import json,sec_edgar_ingest; from sec_edgar_ingest.runtime import preflight_current; '
            'import sys; r=preflight_current(__import__("pathlib").Path(sys.argv[1])); '
            'print(json.dumps({"id":r.release_id,"origin":sec_edgar_ingest.__file__}))', str(self.a.directory / 'release.json')], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)['id'], self.a.release_id)
        self.assertTrue(Path(json.loads(result.stdout)['origin']).is_relative_to(self.a.directory / 'venv'))
        with self.assertRaisesRegex(ValueError, 'executing|interpreter|installation'):
            runtime.preflight_current(self.a.directory / 'release.json')

    def changed_file(self, path, body):
        original = path.read_bytes()
        path.write_bytes(body)
        self.addCleanup(path.write_bytes, original)

    def test_manifest_noncanonical_and_digest_tamper_refused(self):
        manifest = self.a.directory / 'release.json'
        self.changed_file(manifest, json.dumps(self.a.manifest, indent=2).encode())
        with self.assertRaisesRegex(ValueError, 'canonical'):
            runtime.preflight(manifest)
        changed = copy.deepcopy(self.a.manifest)
        changed['identity']['git_revision'] = '0' * 40
        manifest.write_bytes(canonical_json(changed))
        with self.assertRaisesRegex(ValueError, 'identity'):
            runtime.preflight(manifest)

    def test_wheel_and_installed_payload_tamper_refused(self):
        wheel = self.a.directory / 'wheels' / self.a.manifest['identity']['application']['wheel_filename']
        original = wheel.read_bytes()
        self.changed_file(wheel, original + b'tamper')
        with self.assertRaisesRegex(ValueError, 'wheel.*hash'):
            runtime.preflight(self.a.directory / 'release.json')
        wheel.write_bytes(original)
        site = next((self.a.directory / 'venv/lib').glob('python*/site-packages'))
        payload = site / 'sec_edgar_ingest/__init__.py'
        self.changed_file(payload, payload.read_bytes() + b'\n# tamper\n')
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            runtime.preflight(self.a.directory / 'release.json')

    def test_missing_artifact_and_extra_payload_refused(self):
        dependency = self.a.manifest['identity']['dependencies'][0]
        path = self.a.directory / 'artifacts' / dependency['filename']
        hidden = path.with_suffix('.hidden')
        path.rename(hidden)
        try:
            with self.assertRaises((ValueError, FileNotFoundError)):
                runtime.preflight(self.a.directory / 'release.json')
        finally:
            hidden.rename(path)
        site = next((self.a.directory / 'venv/lib').glob('python*/site-packages'))
        extra = site / 'sec_edgar_ingest/extra-resource.txt'
        extra.write_text('unidentified payload')
        self.addCleanup(extra.unlink)
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            runtime.preflight(self.a.directory / 'release.json')

    def test_different_dependency_version_and_extra_distribution_refused(self):
        site = next((self.a.directory / 'venv/lib').glob('python*/site-packages'))
        metadata = next(site.glob('requests-*.dist-info/METADATA'))
        original = metadata.read_bytes()
        self.changed_file(metadata, original.replace(b'Version: 2.34.2', b'Version: 2.34.1'))
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            runtime.preflight(self.a.directory / 'release.json')
        metadata.write_bytes(original)
        with tempfile.TemporaryDirectory(dir=site, suffix='.dist-info') as extra:
            (Path(extra) / 'METADATA').write_text('Name: unexpected\nVersion: 1.0\n')
            with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                runtime.preflight(self.a.directory / 'release.json')

    def test_wrong_interpreter_and_missing_executable_refused(self):
        with self.assertRaisesRegex(ValueError, 'interpreter|installation'):
            runtime.preflight(self.a.directory / 'release.json', executable=Path(sys.executable))
        python = self.a.python
        hidden = python.with_name('python.hidden')
        python.rename(hidden)
        try:
            with self.assertRaises((ValueError, FileNotFoundError)):
                runtime.preflight(self.a.directory / 'release.json')
        finally:
            hidden.rename(python)

    def test_digest_ignores_setup_logs_paths_and_timestamps(self):
        identity = self.a.manifest['identity']
        self.assertEqual(runtime.release_id(copy.deepcopy(identity)), self.a.release_id)
        setup = self.a.directory / 'setup.json'
        self.changed_file(setup, b'{"arbitrary_setup_time":"tomorrow","path":"elsewhere"}')
        os.utime(self.a.directory / 'uv.lock', (1, 1))
        self.assertEqual(runtime.preflight(self.a.directory / 'release.json').release_id, self.a.release_id)

    def test_wrong_reported_interpreter_identity_refused(self):
        real_run = subprocess.run
        for field, value in [('version', '3.14.1'), ('cache_tag', 'cpython-313'),
                             ('platform_tag', 'macosx_26_6_x86_64'), ('implementation', 'pypy')]:
            def run(argv, **kwargs):
                result = real_run(argv, **kwargs)
                evidence = json.loads(result.stdout)
                evidence['interpreter'][field] = value
                result.stdout = json.dumps(evidence)
                return result
            with self.subTest(field=field), patch.object(runtime.subprocess, 'run', side_effect=run):
                with self.assertRaisesRegex(ValueError, 'interpreter'):
                    runtime.preflight(self.a.directory / 'release.json')

    def test_export_directive_or_hash_tamper_refused_without_subprocess(self):
        path = self.a.directory / 'runtime-requirements.txt'
        original = path.read_bytes()
        self.changed_file(path, original + b'\n--index-url https://example.invalid\n')
        with patch.object(runtime.subprocess, 'run') as run, self.assertRaises(ValueError):
            runtime.preflight(self.a.directory / 'release.json')
        run.assert_not_called()
        path.write_bytes(original.replace(b'--hash=sha256:', b'--hash=sha256:0', 1))
        with patch.object(runtime.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'hashes'):
            runtime.preflight(self.a.directory / 'release.json')
        run.assert_not_called()

    def test_editable_install_marker_refused(self):
        site = next((self.a.directory / 'venv/lib').glob('python*/site-packages'))
        direct = next(site.glob('sec_edgar_ingest-*.dist-info/direct_url.json'))
        self.changed_file(direct, b'{"url":"file:///checkout","dir_info":{"editable":true}}')
        with self.assertRaises(subprocess.CalledProcessError):
            runtime.preflight(self.a.directory / 'release.json')

    def test_site_packages_symlink_cannot_redirect_import_outside_release_venv(self):
        site = next((self.a.directory / 'venv/lib').glob('python*/site-packages'))
        for target in (site, site / 'sec_edgar_ingest'):
            with self.subTest(target=target):
                outside = self.a.directory / 'outside-venv-payload'
                target.rename(outside)
                target.symlink_to(outside, target_is_directory=True)
                try:
                    with patch.object(runtime.subprocess, 'run') as run:
                        with self.assertRaisesRegex(ValueError, 'installation|origin'):
                            runtime.preflight(self.a.directory / 'release.json')
                    run.assert_not_called()
                finally:
                    target.unlink()
                    outside.rename(target)

    def poisoned_cache(self, module='__init__'):
        import importlib.util
        import marshal
        import struct
        site = next((self.a.directory / 'venv/lib').glob('python*/site-packages'))
        source = site / 'sec_edgar_ingest' / (module + '.py')
        cache = Path(importlib.util.cache_from_source(str(source)))
        marker = self.a.directory / 'unverified-bytecode-executed'
        original = cache.read_bytes() if cache.exists() else None
        cache.parent.mkdir(exist_ok=True)
        code = compile(source.read_bytes() + ('\nopen(' + repr(str(marker)) + ', "w").write("unverified")\n').encode(), str(source), 'exec')
        source_stat = source.stat()
        header = importlib.util.MAGIC_NUMBER + struct.pack('<III', 0, int(source_stat.st_mtime) & 0xffffffff, source_stat.st_size)
        cache.write_bytes(header + marshal.dumps(code))
        self.addCleanup(marker.unlink, missing_ok=True)
        if original is None:
            self.addCleanup(cache.unlink, missing_ok=True)
        else:
            self.addCleanup(cache.write_bytes, original)
        return cache, marker

    def test_timestamp_valid_bytecode_cannot_execute_during_preflight(self):
        cache, marker = self.poisoned_cache()
        # Control: -B alone still reads the timestamp/size-valid altered code.
        subprocess.run([str(self.a.python), '-I', '-B', '-c', 'import sec_edgar_ingest'], check=True)
        self.assertEqual(marker.read_text(), 'unverified')
        marker.unlink()
        cached_body = cache.read_bytes()
        self.assertEqual(runtime.preflight(self.a.directory / 'release.json').release_id, self.a.release_id)
        self.assertFalse(marker.exists(), 'preflight executed bytecode outside the hashed application payload')
        self.assertEqual(cache.read_bytes(), cached_body, 'read-only preflight must preserve even ignored cache bytes')

    def test_preflight_does_not_generate_missing_application_caches(self):
        import hashlib
        import shutil
        site = next((self.a.directory / 'venv/lib').glob('python*/site-packages'))
        package = site / 'sec_edgar_ingest'
        cache = package / '__pycache__'
        backup = self.a.directory / 'preflight-cache-backup'
        if cache.exists():
            cache.rename(backup)
        def snapshot():
            return {path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    if path.is_file() else 'directory' for path in package.rglob('*')}
        before = snapshot()
        try:
            runtime.preflight(self.a.directory / 'release.json')
            self.assertEqual(snapshot(), before, 'read-only preflight created application bytecode')
        finally:
            if cache.exists():
                shutil.rmtree(cache)
            if backup.exists():
                backup.rename(cache)

    def test_current_process_refuses_cache_enabled_startup(self):
        code = ('from pathlib import Path; from sec_edgar_ingest.runtime import preflight_current; '
                'import sys\ntry: preflight_current(Path(sys.argv[1]))\n'
                'except ValueError: print("unsafe-startup-refused")\n'
                'else: print("unsafe-startup-accepted")')
        result = subprocess.run([str(self.a.python), '-I', '-c', code, str(self.a.directory / 'release.json')],
                                check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), 'unsafe-startup-refused')

    def test_native_startup_bypasses_altered_submodule_caches_without_writes(self):
        cache, marker = self.poisoned_cache('models')
        body = cache.read_bytes()
        code = ('import sec_edgar_ingest.models; from sec_edgar_ingest.runtime import preflight_current; '
                'from pathlib import Path; import sys; '
                'print(preflight_current(Path(sys.argv[1])).release_id)')
        result = subprocess.run([*runtime.native_python_argv(self.a.python), '-c', code,
                                 str(self.a.directory / 'release.json')], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), self.a.release_id)
        self.assertFalse(marker.exists())
        self.assertEqual(cache.read_bytes(), body)

    def test_isolated_bootstrap_effective_policy_precedes_application_import(self):
        cache, marker = self.poisoned_cache()
        body = cache.read_bytes()
        # This preserves Task16's fixed -I absolute-script process shape.
        code = ('import os,sys; sys.dont_write_bytecode=True; sys.pycache_prefix=os.devnull; '
                'from pathlib import Path; from sec_edgar_ingest.runtime import preflight_current; '
                'print(preflight_current(Path(sys.argv[1])).release_id)')
        with tempfile.TemporaryDirectory() as temporary:
            child = Path(temporary) / 'native-child.py'
            child.write_text(code)
            result = subprocess.run([str(self.a.python), '-I', str(child), str(self.a.directory / 'release.json')],
                                    check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), self.a.release_id)
        self.assertFalse(marker.exists())
        self.assertEqual(cache.read_bytes(), body)

    def test_legacy_sourceless_bytecode_is_uninventoried_application_payload(self):
        cached, marker = self.poisoned_cache()
        package = cached.parent.parent
        legacy = package / 'unretained.pyc'
        legacy.write_bytes(cached.read_bytes())
        self.addCleanup(legacy.unlink)
        # A legacy sourceless module has no source path to redirect a cache for.
        subprocess.run([*runtime.native_python_argv(self.a.python), '-c',
                        'import sec_edgar_ingest.unretained'], check=True)
        self.assertTrue(marker.exists())
        marker.unlink()
        with patch.object(runtime.subprocess, 'run', wraps=subprocess.run) as run:
            with self.assertRaisesRegex(ValueError, 'payload'):
                runtime.preflight(self.a.directory / 'release.json')
        run.assert_not_called()

    def test_ordinary_valid_optimization_caches_are_preserved(self):
        site = next((self.a.directory / 'venv/lib').glob('python*/site-packages'))
        package = site / 'sec_edgar_ingest'
        code = ('import py_compile,sys; from pathlib import Path; '
                '[py_compile.compile(str(Path(sys.argv[1])/"__init__.py"),optimize=level,doraise=True) '
                'for level in (0,1,2)]')
        subprocess.run([str(self.a.python), '-I', '-c', code, str(package)], check=True)
        def caches():
            return {path.relative_to(package).as_posix(): path.read_bytes() for path in package.rglob('*.pyc')}
        before = caches()
        self.assertTrue(any('.opt-1.pyc' in name for name in before))
        self.assertTrue(any('.opt-2.pyc' in name for name in before))
        self.assertEqual(runtime.preflight(self.a.directory / 'release.json').release_id, self.a.release_id)
        self.assertEqual(caches(), before)
