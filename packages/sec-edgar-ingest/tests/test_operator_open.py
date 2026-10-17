"""Operator stores verify existing local roots, schemas and registries without creating a lease."""
from network_guard import install
install()

import tempfile
import unittest
from pathlib import Path

from support import fixture_settings
from support_fs import tree_snapshot
from sec_edgar_ingest.storage import open_stores
from sec_edgar_ingest.storage.contracts import (REGISTRY_PATH, Conflict, StoreMissing, deployment_binding,
                                                payload_bytes)


class LocalOperatorOpenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "data"
        self.settings = fixture_settings(root=self.root)

    def worker_open(self):
        for resource in reversed(open_stores(self.settings)):
            if hasattr(resource, 'close'):
                resource.close()

    def operator_open(self, base=None):
        settings = self.settings if base is None else fixture_settings(root=base / 'data')
        return open_stores(settings, access='operator')

    def test_a_missing_store_is_refused_and_nothing_is_created(self):
        for base in (self.base / 'typo', self.base):
            with self.subTest(base=base), self.assertRaises(StoreMissing):
                self.operator_open(base)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_a_store_without_its_registry_or_database_is_refused_unchanged(self):
        for missing in (self.root / 'objects' / REGISTRY_PATH, self.root / 'state.sqlite3'):
            with self.subTest(missing=missing.name):
                self.worker_open()
                missing.unlink()
                before = tree_snapshot(self.base)
                with self.assertRaises(StoreMissing):
                    self.operator_open()
                self.assertEqual(tree_snapshot(self.base), before)

    def test_a_different_binding_is_a_conflict(self):
        self.worker_open()
        (self.root / 'objects' / REGISTRY_PATH).write_bytes(b'{"namespace":"other"}')
        with self.assertRaises(Conflict):
            self.operator_open()

    def test_an_existing_store_opens_without_writes_or_a_lease(self):
        self.worker_open()
        before = tree_snapshot(self.base)
        state, objects, leases = self.operator_open()
        self.assertIsNone(leases)
        self.assertIsNone(state.get('Candidate', 'a' * 64))
        self.assertEqual(objects.read(REGISTRY_PATH),
                         payload_bytes(deployment_binding(self.settings, root=self.root)))
        state.close()
        self.assertEqual(tree_snapshot(self.base), before)

    def test_access_must_be_worker_or_operator(self):
        with self.assertRaisesRegex(ValueError, 'worker or operator'):
            open_stores(self.settings, access='admin')


if __name__ == '__main__':
    unittest.main()
