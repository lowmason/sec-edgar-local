"""Verify the pinned import and independently retained fixture bytes."""

import hashlib
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
FIXTURES = PACKAGE / "tests" / "fixtures"
SOURCE_COMMIT = "0e7701a1e2e98b669334546c90f5c9d4c45b1537"


class SourceImportTests(unittest.TestCase):
    def test_import_manifest_records_pinned_original_bytes(self):
        manifest = json.loads((ROOT / "specs/evidence/source-import.json").read_text())
        self.assertEqual(manifest["format_version"], "sec-local-source-import-v1")
        self.assertEqual(manifest["source_commit"], SOURCE_COMMIT)
        records = manifest["files"]
        self.assertEqual(len(records), 240)
        self.assertEqual(sum('/src/' in item['destination_path'] for item in records), 42)
        self.assertEqual(sum(item['original_path'].startswith(
            'packages/sec-edgar-ingest/tests/fixtures/') for item in records), 50)
        self.assertEqual(records, sorted(records, key=lambda item: (
            item["original_path"], item["destination_path"])))
        self.assertEqual(len({item["destination_path"] for item in records}), len(records))
        for record in records:
            with self.subTest(path=record["destination_path"]):
                self.assertTrue((ROOT / record["destination_path"]).is_file())
                self.assertRegex(record["sha256"], r"^[0-9a-f]{64}$")

    def test_retained_fixtures_match_unchanged_upstream_manifest(self):
        manifest_body = (FIXTURES / "retained-manifest.json").read_bytes()
        imports = json.loads((ROOT / 'specs/evidence/source-import.json').read_text())['files']
        imported = next(item for item in imports if item['destination_path'] ==
                        'packages/sec-edgar-ingest/tests/fixtures/retained-manifest.json')
        self.assertEqual(hashlib.sha256(manifest_body).hexdigest(), imported['sha256'])
        expected = json.loads(manifest_body)
        mapping = json.loads((FIXTURES / "retained-path-map.json").read_text())
        self.assertEqual(mapping["format_version"], "sec-local-retained-paths-v1")
        mapped = mapping["files"]
        by_original = {item["original_path"]: item for item in mapped}
        records = [*expected["records"], *expected["provenance"].values()]
        self.assertEqual(len(expected["records"]), 83)
        self.assertEqual(len(mapped), len(records))
        self.assertEqual(len(by_original), len(records))
        for record in records:
            with self.subTest(path=record["path"]):
                entry = by_original[record["path"]]
                target = (FIXTURES / entry["local_path"]).resolve()
                self.assertTrue(target.is_relative_to(FIXTURES))
                body = target.read_bytes()
                self.assertEqual(hashlib.sha256(body).hexdigest(), record["sha256"])
                self.assertEqual(entry["sha256"], record["sha256"])
                self.assertEqual(len(body), entry["bytes"])
        self.assertEqual(sum(item["bytes"] for item in mapped
                             if item["original_path"] in {
                                 record["path"] for record in expected["records"]}), 14_278_591)

    def test_guard_bootstraps_without_cloud_imports_and_denies_network(self):
        code = """
import sys
sys.path.insert(0, sys.argv[1])
import network_guard
network_guard.install()
assert not any(name == 'msal' or name.startswith('azure') for name in sys.modules)
import socket
for operation in (lambda: socket.getaddrinfo('www.sec.gov', 443),
                  lambda: socket.socket().connect(('127.0.0.1', 9))):
    try:
        operation()
    except AssertionError:
        pass
    else:
        raise AssertionError('network guard allowed an unselected address')
with network_guard.selected_origin('http://127.0.0.1:9876'):
    socket.getaddrinfo('127.0.0.1', 9876)
"""
        result = subprocess.run([sys.executable, '-c', code, str(PACKAGE / 'tests')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_local_package_graph_excludes_cloud_dependencies(self):
        metadata = tomllib.loads((PACKAGE / 'pyproject.toml').read_text())
        self.assertEqual(metadata['project']['version'], '0.2.0')
        self.assertEqual(metadata['project']['requires-python'], '>=3.14')
        self.assertEqual(metadata['project']['dependencies'],
                         ['pyarrow==25.0.1', 'requests==2.34.2'])
        self.assertEqual(metadata['build-system']['requires'], ['uv_build>=0.12.15,<0.13.0'])
        self.assertEqual((ROOT / '.python-version').read_text().strip(), '3.14')
        lock = tomllib.loads((ROOT / 'uv.lock').read_text())
        names = {item['name'] for item in lock['package']}
        self.assertFalse(any(name.startswith('azure') or name.startswith('msal') for name in names))
        self.assertEqual((PACKAGE / 'src/sec_edgar_ingest/__init__.py').read_text(),
                         '__version__ = "0.2.0"\n')
        for relative in ('deployment.py', 'storage/azure.py', 'storage/identity.py'):
            self.assertFalse((PACKAGE / 'src/sec_edgar_ingest' / relative).exists())

    def test_retained_lookup_reads_only_verified_manifest_paths(self):
        from support import retained_path
        mapping = json.loads((FIXTURES / 'retained-path-map.json').read_text())['files']
        for entry in mapping:
            self.assertEqual(retained_path(entry['original_path']),
                             FIXTURES / entry['local_path'])
        with self.assertRaises(KeyError):
            retained_path('unlisted/path')

    def test_retained_lookup_refuses_escape_missing_or_corrupt_bytes(self):
        import support
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = root / 'fixtures'
            fixtures.mkdir()
            (fixtures / 'body').write_bytes(b'original')
            (root / 'outside').write_bytes(b'original')
            entry = {'original_path': 'original', 'local_path': 'body', 'bytes': 8,
                     'sha256': hashlib.sha256(b'original').hexdigest()}
            changes = ({'local_path': '../outside'}, {'local_path': 'missing'},
                       {'bytes': 9}, {'sha256': '0' * 64})
            for change in changes:
                with self.subTest(change=change):
                    (fixtures / 'retained-path-map.json').write_text(json.dumps(
                        {'files': [{**entry, **change}]}))
                    with patch.object(support, '__file__', str(root / 'support.py')):
                        with self.assertRaises(ValueError):
                            support.retained_path('original')


if __name__ == "__main__":
    unittest.main()
