"""Operator stores open verify-only: never a new root, schema, registry, container, table or lease."""
from network_guard import install
install()

import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from azure.storage.blob import BlobServiceClient

from support import fixture_settings
from support_approval import tree_snapshot
from support_azure import azure_settings
from test_azure_contracts import BLOB_ENDPOINT, RETRY, TABLE_ENDPOINT, ScriptedTransport, blob_error, response
from sec_edgar_ingest.storage import open_stores
from sec_edgar_ingest.storage.contracts import (REGISTRY_PATH, Conflict, StoreMissing, deployment_binding,
                                                payload_bytes)


class LocalOperatorOpenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.settings = fixture_settings()
        self.root = self.base / self.settings.storage.root

    def worker_open(self):
        for resource in reversed(open_stores(self.settings, base_path=self.base)):
            if hasattr(resource, 'close'):
                resource.close()

    def operator_open(self, base=None):
        return open_stores(self.settings, base_path=base or self.base, access='operator')

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
            open_stores(self.settings, base_path=self.base, access='admin')


class AzureOperatorOpenTests(unittest.TestCase):
    def setUp(self):
        from sec_edgar_ingest.storage import azure
        self.azure = azure
        self.settings = azure_settings()
        self.binding = payload_bytes(deployment_binding(self.settings))

    @contextlib.contextmanager
    def factories(self, responses):
        transport = ScriptedTransport(responses)
        service = BlobServiceClient(BLOB_ENDPOINT, api_version='2026-04-06', transport=transport, **RETRY)
        self.addCleanup(service.close)
        with patch.object(self.azure, 'BlobServiceClient', return_value=service) as blobs, \
                patch.object(self.azure, 'TableServiceClient') as tables, \
                patch.object(self.azure, 'ManagedIdentityCredential', side_effect=AssertionError('worker identity')):
            tables.return_value.get_table_client.side_effect = lambda name: Mock(url=TABLE_ENDPOINT, table_name=name)
            yield transport, blobs, tables

    def test_operator_open_reads_the_registry_and_never_writes(self):
        credential = object()
        with self.factories([response(body=self.binding)]) as (transport, blobs, tables):
            state, objects, leases = self.azure.open_azure_stores(self.settings, access='operator',
                                                                  credential=credential)
        self.assertIsNone(leases)
        self.assertEqual([request.method for request in transport.requests], ['GET'])
        self.assertIs(blobs.call_args.kwargs['credential'], credential)
        self.assertIs(tables.call_args.kwargs['credential'], credential)
        self.assertEqual(state.approval_client.table_name, 'Approvals')

    def test_a_missing_registry_is_store_missing_before_any_table_client(self):
        with self.factories([blob_error(404, 'BlobNotFound')]) as (_, _, tables):
            with self.assertRaises(StoreMissing):
                self.azure.open_azure_stores(self.settings, access='operator', credential=object())
        tables.assert_not_called()

    def test_a_different_registry_is_a_conflict(self):
        with self.factories([response(body=b'{"namespace":"other"}')]) as (_, _, tables):
            with self.assertRaises(Conflict):
                self.azure.open_azure_stores(self.settings, access='operator', credential=object())
        tables.assert_not_called()

    def test_open_stores_passes_access_and_credential_to_azure(self):
        credential = object()
        with patch.object(self.azure, 'open_azure_stores', return_value=('s', 'o', None)) as opened:
            self.assertEqual(open_stores(self.settings, access='operator', credential=credential), ('s', 'o', None))
        self.assertEqual(opened.call_args.kwargs, {'observer': None, 'access': 'operator', 'credential': credential})


if __name__ == '__main__':
    unittest.main()
