from network_guard import install
install()

from sec_edgar_ingest.models import to_mapping_value
import tempfile
import unittest
from pathlib import Path

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
version = "0.1.0"
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


class InstalledLockTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[3]
        self.lock = (self.repo / 'uv.lock').read_bytes()
        self.export = (self.repo / 'specs/evidence/sec-filing-index-ingestion/stage-3/'
                       'verification/installed/requirements.txt').read_text()
        self.environment = marker_environment()

    def test_complete_accepted_graph_rejects_wrong_transitive_with_direct_pins_intact(self):
        expected = locked_requirements(self.lock, self.export, self.environment)
        self.assertEqual(len(expected), 19 if self.environment['platform_python_implementation'] == 'PyPy' else 21)
        actual = dict(expected, **{'sec-edgar-ingest': '0.1.0'})
        actual['urllib3'] = '2.7.0'
        for direct in ('pyarrow', 'requests', 'azure-identity', 'azure-storage-blob', 'azure-data-tables'):
            self.assertEqual(actual[direct], expected[direct])
        with self.assertRaisesRegex(ValueError, 'installed dependency set'):
            assert_inventory(expected, actual, '0.1.0')

    def test_exact_set_rejects_missing_and_extra_distribution(self):
        expected = locked_requirements(self.lock, self.export, self.environment)
        for actual in (dict(expected), dict(expected, **{'sec-edgar-ingest': '0.1.0', 'unrequested': '1.0'})):
            with self.assertRaisesRegex(ValueError, 'installed dependency set'):
                assert_inventory(expected, actual, '0.1.0')
        self.assertIsNone(assert_inventory(expected, dict(expected, **{'sec-edgar-ingest': '0.1.0'}), '0.1.0'))

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
            (package / '__init__.py').write_bytes(b'__version__="0.1.0"\n')
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
