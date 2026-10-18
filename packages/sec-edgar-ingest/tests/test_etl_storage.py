"""Offline ETL logical object routing contracts."""
import unittest
from sec_edgar_ingest.models import safe_relative_path


class EtlStorageTests(unittest.TestCase):
    def test_logical_paths_are_safe_relative_posix_keys(self):
        for path in ('runs/sec/r/transform/a/result.json',
                     'curated/sec/filing_index/year=2026/quarter=4/generation=g/manifest.json',
                     'observations/sec/indexes/source=s/sha256=h/parser=p/schema=v/rows.parquet',
                     'raw/sec/a'):
            self.assertEqual(safe_relative_path(path, 'key'), path)
        for path in ('curated/../raw/a', '/absolute', 'a\\b', 'a//b'):
            with self.assertRaises(ValueError):
                safe_relative_path(path, 'key')

    def test_local_materialize_is_exclusive_and_cleans_failed_copy(self):
        import tempfile
        from pathlib import Path
        from sec_edgar_ingest.storage.local import LocalObjectStore
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            objects = LocalObjectStore(root/'store')
            body = b'rows' * (1024 * 300)
            objects.put_once('observations/sec/rows.parquet', body)
            target = root/'rows.parquet'
            objects.materialize('observations/sec/rows.parquet', target)
            self.assertEqual(target.read_bytes(), body)
            with self.assertRaises(FileExistsError):
                objects.materialize('observations/sec/rows.parquet', target)
            self.assertEqual(target.read_bytes(), body)
            missing = root/'missing.parquet'
            with self.assertRaises(FileNotFoundError):
                objects.materialize('observations/sec/missing.parquet', missing)
            self.assertFalse(missing.exists())

    def test_pointer_commit_uses_actual_revision_and_propagates_conflict(self):
        import tempfile
        from pathlib import Path
        from sec_edgar_ingest.etl.state import EtlState
        from sec_edgar_ingest.storage.local import LocalStateStore
        from sec_edgar_ingest.storage.contracts import Conflict, AlreadyExists
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStateStore(Path(directory))
            self.addCleanup(store.close)
            state = EtlState(store)
            value = dict(quarter='2026Q4', generation_id='a'*64, manifest_ref='curated/sec/generation=a/manifest.json', manifest_sha256='b'*64, manifest_bytes=10, source_fingerprint='c'*64)
            self.assertIsNone(state.pointer('2026Q4'))
            first = state.commit_pointer('2026Q4', value, None)
            with self.assertRaises((AlreadyExists, Conflict)):
                state.commit_pointer('2026Q4', value, None)
            next_value = {**value, 'generation_id': 'd'*64}
            second = state.commit_pointer('2026Q4', next_value, first)
            self.assertNotEqual(first.version, second.version)
            with self.assertRaises(Conflict):
                state.commit_pointer('2026Q4', value, first)
            self.assertEqual(state.pointer('2026Q4'), second)
            for bad in ({**value, 'quarter': '2026Q3'}, {**value, 'extra': True}, {**value, 'manifest_sha256': '*'}):
                with self.assertRaises(ValueError):
                    state.commit_pointer('2026Q4', bad, second)



    def test_local_approval_and_rollback_rows_persist_in_the_approvals_table(self):
        import sqlite3
        import tempfile
        from contextlib import closing
        from pathlib import Path
        from sec_edgar_ingest.storage.local import LocalStateStore
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStateStore(Path(directory))
            self.addCleanup(store.close)
            approval = store.insert('WithdrawalApproval', 'a' * 64, {'approver': 'Lowell Mason'})
            rollback = store.insert('QuarterRollback', 'b' * 64, {'operator': 'Lowell Mason', 'quarter': '2026Q4'})
            # A get/scan round-trip cannot see routing because both sides call table_for; inspect the stored rows.
            with closing(sqlite3.connect(store.database)) as connection:
                rows = connection.execute('SELECT table_name, partition, key FROM records ORDER BY key').fetchall()
            self.assertEqual(rows, [('Approvals', 'sec-owner-lowell-mason:WithdrawalApproval', 'a' * 64),
                                    ('Approvals', 'sec-owner-lowell-mason:QuarterRollback', 'b' * 64)])
            self.assertEqual((store.get('WithdrawalApproval', 'a' * 64), list(store.scan('QuarterRollback', {'quarter': '2026Q4'}))),
                             (approval, [rollback]))

    def test_transform_acceptance_and_publication_receipts_are_idempotent(self):
        import tempfile
        from dataclasses import replace
        from pathlib import Path
        from sec_edgar_ingest.etl.state import EtlState
        from sec_edgar_ingest.etl.contracts import Candidate
        from sec_edgar_ingest.storage.local import LocalStateStore
        from sec_edgar_ingest.storage.contracts import Conflict
        from test_etl_contracts import observation_ref, generation_manifest
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStateStore(Path(directory))
            self.addCleanup(store.close)
            state = EtlState(store)
            ref = observation_ref()
            self.assertIsNone(state.processing(ref))
            state.accept_transform(ref)
            accepted = state.processing(ref)
            state.accept_transform(ref)
            self.assertEqual(state.processing(ref), accepted)
            with self.assertRaises(Conflict):
                state.accept_transform(replace(ref, rows_sha256='f'*64))
            manifest = generation_manifest()
            state.record_publication(manifest)
            state.record_publication(manifest)
            self.assertEqual(len(list(store.scan('PublicationReceipt', {}))), 1)
            self.assertEqual(len(list(store.scan('Source', {}))), 0)
            candidate = Candidate(manifest, 'curated/sec/g/manifest.json', 'a'*64, 10, None)
            state.record_candidate(candidate)
            state.record_candidate(candidate)
            self.assertEqual(len(list(store.scan('Candidate', {}))), 1)


    def test_materialize_close_failure_removes_its_created_scratch(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from sec_edgar_ingest.storage.local import LocalObjectStore
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            objects = LocalObjectStore(root/'store')
            objects.put_once('raw/sec/source', b'raw')
            target = root/'scratch'
            original_open = Path.open
            class FailingClose:
                def __init__(self, stream):
                    self.stream = stream
                def __enter__(self):
                    return self.stream
                def __exit__(self, *args):
                    self.stream.close()
                    raise OSError('scratch flush failed')
            def open_file(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                return FailingClose(stream) if path == target else stream
            with patch.object(Path, 'open', open_file), self.assertRaises(OSError):
                objects.materialize('raw/sec/source', target)
            self.assertFalse(target.exists())

    def test_conflicting_transform_cannot_leave_a_publication_receipt(self):
        import tempfile
        from dataclasses import replace
        from pathlib import Path
        from sec_edgar_ingest.etl.state import EtlState
        from sec_edgar_ingest.storage.local import LocalStateStore
        from sec_edgar_ingest.storage.contracts import Conflict
        from test_etl_contracts import observation_ref, generation_manifest
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStateStore(Path(directory))
            self.addCleanup(store.close)
            state = EtlState(store)
            state.accept_transform(observation_ref())
            manifest = replace(generation_manifest(), sources=(replace(observation_ref(), rows_sha256='f'*64),))
            with self.assertRaises(Conflict):
                state.record_publication(manifest)
            self.assertEqual(list(store.scan('PublicationReceipt', {})), [])

    def test_publication_membership_is_monotonic_and_cas_is_bounded(self):
        import tempfile
        from dataclasses import replace
        from pathlib import Path
        from unittest.mock import patch
        from sec_edgar_ingest.etl.state import EtlState
        from sec_edgar_ingest.storage.local import LocalStateStore
        from sec_edgar_ingest.storage.contracts import Conflict, CAS_ATTEMPTS
        from test_etl_contracts import observation_ref, generation_manifest
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStateStore(Path(directory))
            self.addCleanup(store.close)
            state = EtlState(store)
            state.accept_transform(observation_ref())
            manifest = generation_manifest()
            with patch.object(store, 'replace', side_effect=Conflict('race')) as replace_row:
                with self.assertRaises(Conflict):
                    state.record_publication(manifest)
                self.assertEqual(replace_row.call_count, CAS_ATTEMPTS)
            state.record_publication(manifest)
            newer = replace(manifest, generation_id='9'*64)
            state.record_publication(newer)
            state.record_publication(manifest)
            memberships = state.processing(observation_ref()).value['publications']['2015Q1']
            self.assertEqual(set(memberships), {manifest.generation_id, newer.generation_id})
            self.assertEqual(len(list(store.scan('PublicationReceipt', {}))), 2)

    def test_large_active_pointer_roundtrips_all_bytes_and_revisions(self):
        import tempfile
        from pathlib import Path
        from sec_edgar_ingest.storage.local import LocalStateStore
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStateStore(Path(directory))
            self.addCleanup(store.close)
            value = {'retained_evidence': 'x' * (70 * 1024)}
            first = store.insert('QuarterPublication', '2026Q4', value)
            self.assertEqual(store.get('QuarterPublication', '2026Q4').to_mapping()['value'], value)
            second = store.replace('QuarterPublication', '2026Q4', {**value, 'new': True}, first.version)
            with self.assertRaises(Conflict):
                store.replace('QuarterPublication', '2026Q4', value, first.version)
            self.assertEqual(store.get('QuarterPublication', '2026Q4'), second)

    def test_stream_failure_removes_only_new_scratch_and_retains_existing_target(self):
        import tempfile
        from contextlib import contextmanager
        from pathlib import Path
        from unittest.mock import patch
        from sec_edgar_ingest.storage.local import LocalObjectStore
        class BrokenStream:
            def __init__(self): self.first = True
            def read(self, count):
                if self.first:
                    self.first = False
                    return b'prefix'
                raise OSError('truncated retained object read')
        @contextmanager
        def broken_open(path):
            yield BrokenStream()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            objects = LocalObjectStore(root / 'store')
            target = root / 'scratch'
            with patch.object(objects, '_open', side_effect=broken_open):
                with self.assertRaises(OSError):
                    objects.materialize('observations/sec/rows.parquet', target)
                self.assertFalse(target.exists())
                target.write_bytes(b'existing')
                with self.assertRaises(FileExistsError):
                    objects.materialize('observations/sec/rows.parquet', target)
                self.assertEqual(target.read_bytes(), b'existing')
