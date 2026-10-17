"""Offline complete-generation publication and crash recovery contracts."""
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import patch
from support import Faults, fixture_settings
from support_etl import etl_context, seed_observation
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.etl.catalog import build_candidate
from sec_edgar_ingest.etl.manifest import read_manifest
from sec_edgar_ingest.storage.contracts import CAS_ATTEMPTS


from support import store_bundle
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.storage.contracts import Conflict


class EtlPublicationTests(unittest.TestCase):
    def test_stale_pointer_version_cannot_replace_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            store, objects, leases = store_bundle(Path(directory))
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            state = EtlState(store)
            first = state.commit_pointer('2026Q4', {
                'quarter': '2026Q4', 'generation_id': '1'*64,
                'manifest_ref': 'curated/sec/filing_index/year=2026/quarter=4/generation='+'1'*64+'/manifest.json',
                'manifest_sha256': 'a'*64, 'manifest_bytes': 10, 'source_fingerprint': 'b'*64}, None)
            newer = first.to_mapping()['value']
            newer['generation_id'] = '2'*64
            newer['manifest_ref'] = 'curated/sec/filing_index/year=2026/quarter=4/generation='+'2'*64+'/manifest.json'
            state.commit_pointer('2026Q4', newer, first)
            with self.assertRaises(Conflict):
                state.commit_pointer('2026Q4', first.to_mapping()['value'], first)
            self.assertEqual(state.pointer('2026Q4').value['generation_id'], '2'*64)

    def test_publication_and_reader_interfaces_exist(self):
        import importlib.util
        for name in ('publication', 'reader'):
            self.assertIsNotNone(importlib.util.find_spec('sec_edgar_ingest.etl.' + name))


def row(name='Example', number=1, day='2026-10-01'):
    return f'123456|{name}|10-K|{day}|edgar/data/123456/0000123456-26-{number:06}.txt\n'.encode()


class PublicationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store, self.objects, leases = store_bundle(self.root)
        leases.close()
        self.addCleanup(self.store.close)
        self.state = EtlState(self.store)
        self.settings, self.context = etl_context(command='publish')
        self.pin(date(2026, 10, 7))

    def pin(self, day):
        self.settings = fixture_settings(etl={'parser_version': self.context.parser_version}, fixture={'allow_clock_override': True})
        self.context = pin_context(self.settings, replace(self.context, config_sha256=self.settings.config_sha256,
                                  effective_config={}, pinned_on=None), day)[0]

    def observation(self, **kwargs):
        return seed_observation(self.objects, self.state, self.context, self.settings, **kwargs)

    def publish(self, *refs, quarter='2026Q4', **kwargs):
        from sec_edgar_ingest.etl.publication import publish_quarter
        return publish_quarter(quarter, refs, self.context, self.settings, self.objects, self.state, **kwargs)

    def capture(self, quarter='2026Q4'):
        from sec_edgar_ingest.etl.reader import capture_quarter
        return capture_quarter(quarter, self.objects, self.state)

    def rows(self, capture=None):
        from sec_edgar_ingest.etl.reader import read_quarter
        return list(read_quarter(capture or self.capture(), self.objects))

    def test_publish_noop_force_replay_and_pinned_old_capture(self):
        first = self.observation()
        result = self.publish(first)
        self.assertEqual(result.outcome, 'published')
        old = self.capture()
        pointer = self.state.pointer('2026Q4')
        from sec_edgar_ingest.etl.transform import transform_member
        forced = transform_member(first.source, first.snapshot, self.context, self.settings, self.objects, self.state, force=True)
        for _ in range(3):
            self.assertEqual(self.publish(forced).outcome, 'unchanged')
            self.assertEqual(self.state.pointer('2026Q4'), pointer)
        revised = self.observation(rows=row('New'), seconds=1)
        self.assertEqual(self.publish(revised).outcome, 'published')
        self.assertEqual(self.rows(old)[0].company_name, 'Example')
        self.assertEqual(self.rows()[0].company_name, 'New')
        self.assertEqual(len(list(self.store.scan('PublicationReceipt', {}))), 2)

    def test_open_retained_basis_noop_and_version_replay(self):
        first = self.observation(rows=row() + row(number=2))
        self.publish(first)
        revised = self.observation(rows=row('Revised'), seconds=1)
        self.publish(revised)
        pointer = self.state.pointer('2026Q4')
        self.assertIsNotNone(read_manifest(self.capture(), self.objects).retained_from_generation)
        self.assertEqual(self.publish(revised).outcome, 'unchanged')
        self.assertEqual(self.state.pointer('2026Q4'), pointer)
        self.settings, self.context = etl_context('fixture-index-parser-v2', command='publish')
        self.pin(date(2026, 10, 7))
        self.assertEqual(self.publish(revised).outcome, 'published')
        self.assertEqual(read_manifest(self.capture(), self.objects).parser_version, 'fixture-index-parser-v2')

    def _assert_pointer_race(self, initial):
        winner = self.observation(period='2026-10-03', kind='daily', rows=row('Winner'))
        incoming = self.observation(period='2026-10-02', kind='daily', rows=row('Incoming') + row(number=2))
        if initial:
            self.publish(self.observation(period='2026-10-01', kind='daily', rows=row('Old')))
        faults = Faults()
        faults.at('publication.before_pointer', lambda: self.publish(winner))
        result = self.publish(incoming, observer=faults)
        self.assertEqual((result.outcome, result.conflicts), ('published', 1))
        self.assertEqual([r.company_name for r in self.rows()], ['Winner', 'Example'])
        manifest = read_manifest(self.capture(), self.objects)
        self.assertIn(winner, manifest.sources)
        self.assertIn(incoming, manifest.sources)

    def test_missing_pointer_insert_race_rebuilds_union(self):
        self._assert_pointer_race(False)

    def test_stale_replace_race_rebuilds_union_and_updated_winner_fields(self):
        self._assert_pointer_race(True)

    def test_cas_retry_reevaluates_withdrawal_gate(self):
        incoming = self.observation(rows=row())
        winner = self.observation(period='2026-10-02', kind='daily', rows=row() + row(number=2))
        self.pin(date(2027, 1, 1))
        faults = Faults()
        faults.at('publication.before_pointer', lambda: self.publish(winner))
        result = self.publish(incoming, observer=faults)
        self.assertEqual((result.outcome, result.conflicts), ('awaiting_approval', 1))
        self.assertIsNotNone(result.candidate_ref)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(self.state.processing(incoming).to_mapping()['value']['publications'], {})

    def test_five_conflicts_and_expired_deadline_have_no_commit(self):
        from sec_edgar_ingest.etl import publication
        ref = self.observation()
        with patch.object(self.state, 'commit_pointer', side_effect=Conflict('race')) as commit:
            result = self.publish(ref)
        self.assertEqual((result.outcome, result.conflicts, commit.call_count), ('publication_conflict', CAS_ATTEMPTS, CAS_ATTEMPTS))
        self.assertIsNone(self.capture())
        self.assertIsNotNone(result.manifest_ref)
        self.assertIsNone(result.generation_id)
        self.assertIsNone(result.candidate_ref)
        self.assertTrue(self.objects.read(result.manifest_ref))
        with patch.object(publication, '_now', return_value=self.context.deadline):
            self.assertEqual(self.publish(ref).outcome, 'publication_conflict')
        self.assertEqual(list(self.store.scan('PublicationReceipt', {})), [])
        self.assertEqual(list(self.store.scan('Source', {})), [])

    def test_deadline_expires_at_commit_boundary(self):
        from sec_edgar_ingest.etl import publication
        ref = self.observation()
        with patch.object(publication, '_now', side_effect=[self.context.started_at, self.context.deadline]):
            result = self.publish(ref)
        self.assertEqual(result.outcome, 'publication_conflict')
        self.assertIsNone(self.capture())

    def test_named_crash_boundaries_preserve_old_or_new_and_repair(self):
        from sec_edgar_ingest.etl.publication import repair_publication
        first = self.observation()
        self.publish(first)
        for index, boundary in enumerate(('candidate.after_data', 'candidate.after_changes', 'candidate.after_manifest',
                                         'candidate.after_validation', 'publication.before_pointer',
                                         'publication.after_pointer', 'publication.after_repair')):
            previous = self.capture()
            revised = self.observation(rows=row(boundary), seconds=index+1)
            faults = Faults()
            def crash():
                raise RuntimeError('boundary crash')
            faults.at(boundary, crash)
            with self.subTest(boundary=boundary), self.assertRaisesRegex(RuntimeError, 'boundary crash'):
                self.publish(revised, observer=faults)
            capture = self.capture()
            committed = boundary in ('publication.after_pointer', 'publication.after_repair')
            self.assertEqual(capture != previous, committed)
            self.assertEqual(self.rows()[0].company_name, boundary if committed else self.rows(previous)[0].company_name)
            repair_publication('2026Q4', self.objects, self.state)
            self.assertEqual(self.state.pointer('2026Q4').value['generation_id'], capture.generation_id)
            outcome = self.publish(revised).outcome
            self.assertEqual(outcome, 'unchanged' if committed else 'published')

    def test_repair_interruption_multiquarter_and_monotonic_memberships(self):
        from sec_edgar_ingest.etl.publication import repair_publication
        ref = self.observation(period='2026-10-02', kind='daily', rows=row() + row(number=2, day='2026-09-30'))
        with patch.object(self.state, '_record_membership', side_effect=RuntimeError('repair crash')):
            with self.assertRaisesRegex(RuntimeError, 'repair crash'):
                self.publish(ref)
        pointer = self.state.pointer('2026Q4')
        repair_publication('2026Q4', self.objects, self.state)
        self.assertEqual(self.state.pointer('2026Q4'), pointer)
        self.assertFalse(self.state.processing(ref).value['published'])
        self.publish(ref, quarter='2026Q3')
        self.assertTrue(self.state.processing(ref).value['published'])
        old_manifest = read_manifest(self.capture(), self.objects)
        self.publish(self.observation(period='2026-10-03', kind='daily', rows=row('Later')))
        before = self.state.processing(ref)
        self.state.record_publication(old_manifest)
        self.assertEqual(self.state.processing(ref), before)
        self.assertEqual(before.to_mapping()['value']['observation'], ref.to_mapping())
        self.assertEqual(len(before.value['publications']['2026Q4']), 2)

    def test_corruption_or_missing_files_cannot_leak_first_row_or_repair(self):
        from sec_edgar_ingest.etl.reader import read_quarter
        from sec_edgar_ingest.etl.publication import repair_publication
        self.publish(self.observation(rows=row() + row(number=2)))
        capture = self.capture()
        manifest = read_manifest(capture, self.objects)
        for name in (capture.manifest_ref, *(ref.path for ref in manifest.files)):
            path = self.root / 'objects' / name
            body = path.read_bytes()
            for replacement in (None, body[:-1]):
                if replacement is None:
                    path.unlink()
                else:
                    path.write_bytes(replacement)
                with self.subTest(name=name, missing=replacement is None):
                    with self.assertRaises((ValueError, Conflict, FileNotFoundError)):
                        next(read_quarter(capture, self.objects))
                    with self.assertRaises((ValueError, Conflict, FileNotFoundError)):
                        repair_publication('2026Q4', self.objects, self.state)
                path.write_bytes(body)
        self.assertEqual(len(self.rows(capture)), 2)

    def test_unreferenced_candidate_data_is_never_read(self):
        ref = self.observation()
        self.publish(ref)
        before = self.capture()
        loser = self.observation(rows=row('Losing'), seconds=1)
        candidate = build_candidate('2026Q4', before, (loser,), self.context, self.settings, self.objects, self.state)
        (self.root / 'objects' / candidate.manifest.files[0].path).write_bytes(b'corrupt orphan')
        self.assertEqual(self.rows()[0].company_name, 'Example')
        self.assertEqual(self.capture(), before)

    def test_pointer_shape_address_hash_and_fingerprint_are_checked(self):
        from sec_edgar_ingest.etl.reader import capture_from_pointer
        self.publish(self.observation())
        pointer = self.state.pointer('2026Q4')
        value = pointer.to_mapping()['value']
        for changed in ({**value, 'extra': True}, {**value, 'manifest_sha256': 'bad'},
                        {**value, 'manifest_ref': 'curated/sec/wrong/manifest.json'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                capture_from_pointer(replace(pointer, value=changed))
        self.store.replace('QuarterPublication', '2026Q4', {**value, 'source_fingerprint': 'f'*64}, pointer.version)
        with self.assertRaisesRegex(Conflict, 'fingerprint'):
            self.capture()
        with self.assertRaisesRegex(Conflict, 'fingerprint'):
            self.publish(self.observation())

    def test_noop_still_refuses_forged_incoming_observation_reference(self):
        ref = self.observation()
        self.publish(ref)
        with self.assertRaises((ValueError, Conflict)):
            self.publish(replace(ref, rows_bytes=ref.rows_bytes+1))

    def test_no_receipt_for_source_without_rows_in_committed_quarter(self):
        incoming = self.observation(period='2026-10-02', kind='daily', rows=row(day='2026-09-30'))
        self.publish(incoming, self.observation())
        self.assertEqual(self.state.processing(incoming).to_mapping()['value']['publications'], {})
        self.assertEqual(len(list(self.store.scan('PublicationReceipt', {}))), 1)

    def test_reader_checks_semantics_and_late_counts_before_first_row(self):
        import hashlib
        import pyarrow as pa
        import pyarrow.parquet as pq
        from sec_edgar_ingest.models import canonical_json
        from sec_edgar_ingest.etl.contracts import canonical_schema
        from sec_edgar_ingest.etl.manifest import iter_file_rows
        from sec_edgar_ingest.etl.reader import read_quarter
        self.publish(self.observation(rows=row() + row(number=2)))
        capture = self.capture()
        manifest = read_manifest(capture, self.objects)
        data = next(ref for ref in manifest.files if ref.role == 'data')
        values = list(iter_file_rows(data, self.objects))
        path = self.root / 'objects' / data.path
        original = path.read_bytes()
        manifest_path = self.root / 'objects' / capture.manifest_ref
        manifest_bytes = manifest_path.read_bytes()
        wrong_quarter = [values[0], {**values[1], 'filing_date': date(2026, 9, 30)}]
        for bad_rows, schema, count in ((values, canonical_schema(), 3),
                                        ([values[0], values[0]], canonical_schema(), 2),
                                        (wrong_quarter, canonical_schema(), 2),
                                        (values, canonical_schema().with_metadata({b'unexpected': b'schema'}), 2)):
            pq.write_table(pa.Table.from_pylist(bad_rows, schema=schema), path)
            body = path.read_bytes()
            corrupted = replace(data, row_count=count, byte_count=len(body), sha256=hashlib.sha256(body).hexdigest())
            bad_manifest = replace(manifest, files=tuple(corrupted if ref.role == 'data' else ref for ref in manifest.files))
            encoded = canonical_json(bad_manifest.to_mapping())
            manifest_path.write_bytes(encoded)
            forged = replace(capture, manifest_sha256=hashlib.sha256(encoded).hexdigest(), manifest_bytes=len(encoded))
            with self.subTest(count=count, schema=schema), self.assertRaises((ValueError, Conflict)):
                next(read_quarter(forged, self.objects))
        path.write_bytes(original)
        manifest_path.write_bytes(manifest_bytes)

    def test_mocked_sdk_actual_etags_412_and_large_candidate_descriptor(self):
        import json
        from azure.core.credentials import AzureSasCredential
        from azure.data.tables import TableServiceClient
        from azure.storage.blob import BlobServiceClient
        from sec_edgar_ingest.etl.publication import pointer_value
        from sec_edgar_ingest.models import canonical_json
        from sec_edgar_ingest.storage.azure import AzureStateStore, AzureObjectStore
        from sec_edgar_ingest.storage.contracts import AlreadyExists
        from test_azure_contracts import TABLE_ENDPOINT, BLOB_ENDPOINT, RETRY
        from test_azure_state_payloads import LimitedStorageTransport
        refs = tuple(self.observation(period=(date(2026, 8, 1) + timedelta(days=i)).isoformat(), kind='daily') for i in range(50))
        candidate = build_candidate('2026Q4', None, refs, self.context, self.settings, self.objects, self.state)
        self.assertGreater(len(canonical_json(candidate.to_mapping())), 64*1024)
        transport = LimitedStorageTransport()
        blobs = BlobServiceClient(BLOB_ENDPOINT, api_version='2026-04-06', transport=transport, **RETRY)
        tables = TableServiceClient(TABLE_ENDPOINT, credential=AzureSasCredential('sv=offline&sig=synthetic'),
                                    api_version='2020-12-06', transport=transport, **RETRY)
        self.addCleanup(blobs.close)
        self.addCleanup(tables.close)
        objects = AzureObjectStore(blobs)
        store = AzureStateStore(tables.get_table_client('SourceState'), tables.get_table_client('Attempts'),
                                active_client=tables.get_table_client('ActivePointers'), objects=objects)
        state = EtlState(store)
        state.record_candidate(candidate)
        self.assertEqual(store.get('Candidate', candidate.manifest.generation_id).to_mapping()['value'], candidate.to_mapping())
        first = state.commit_pointer('2026Q4', pointer_value(candidate), None)
        with self.assertRaises(AlreadyExists):
            state.commit_pointer('2026Q4', pointer_value(candidate), None)
        winner = state.commit_pointer('2026Q4', pointer_value(candidate), first)
        with self.assertRaises(Conflict):
            state.commit_pointer('2026Q4', pointer_value(candidate), first)
        self.assertEqual(state.pointer('2026Q4'), winner)
        writes = [request for request in transport.requests if request.method == 'PUT' and '/ActivePointers' in request.url]
        self.assertEqual([r.headers['If-Match'] for r in writes], [first.version, first.version])
        descriptor = next(json.loads(r.body) for r in transport.requests if r.method == 'POST' and '/SourceState' in r.url)
        self.assertEqual(descriptor['PayloadFormat'], 'sec-state-blob-v1')
        self.assertGreater(descriptor['PayloadByteCount'], 64*1024)

    def test_deadline_expiry_inside_candidate_build_returns_conflict(self):
        from sec_edgar_ingest.etl import publication
        ref = self.observation()
        with patch.object(publication, 'build_candidate', side_effect=TimeoutError('transform deadline exceeded')):
            with patch.object(publication, '_now', side_effect=[self.context.started_at, self.context.deadline]):
                result = self.publish(ref)
        self.assertEqual((result.outcome, result.conflicts), ('publication_conflict', 0))
        self.assertIsNone(self.state.pointer('2026Q4'))

    def test_repair_membership_cas_preserves_competing_quarter_receipt(self):
        ref = self.observation(period='2026-10-02', kind='daily', rows=row() + row(number=2, day='2026-09-30'))
        original_replace = self.store.replace
        raced = False
        def race(kind, key, value, version):
            nonlocal raced
            if kind == 'Processing' and not raced:
                raced = True
                self.publish(ref, quarter='2026Q3')
            return original_replace(kind, key, value, version)
        with patch.object(self.store, 'replace', side_effect=race):
            self.publish(ref)
        value = self.state.processing(ref).value
        self.assertTrue(value['published'])
        self.assertEqual(set(value['publications']), {'2026Q3', '2026Q4'})
        self.assertEqual(self.state.processing(ref).to_mapping()['value']['observation'], ref.to_mapping())

    def test_awaiting_approval_pointer_is_refused_by_capture_and_repair(self):
        from sec_edgar_ingest.etl.publication import pointer_value, repair_publication
        initial = self.observation(rows=row() + row(number=2))
        self.publish(initial)
        before = self.capture()
        revised = self.observation(rows=row(), seconds=1)
        self.pin(date(2027, 1, 1))
        gated = build_candidate('2026Q4', before, (revised,), self.context, self.settings, self.objects, self.state)
        self.assertEqual(gated.manifest.gate, 'awaiting_approval')
        self.state.commit_pointer('2026Q4', pointer_value(gated), self.state.pointer('2026Q4'))
        with self.assertRaisesRegex(ValueError, 'awaiting-approval'):
            self.capture()
        with self.assertRaisesRegex(ValueError, 'awaiting-approval'):
            repair_publication('2026Q4', self.objects, self.state)

    def test_retained_publication_proof(self):
        import json
        import os
        import shutil
        from sec_edgar_ingest.etl.publication import repair_publication
        first = self.observation(rows=row() + row(number=2))
        self.publish(first)
        old = self.capture()
        ref = self.observation(period='2026-10-02', kind='daily', rows=row(number=3) + row(number=4, day='2026-09-30'))
        faults = Faults()
        def crash():
            raise RuntimeError('proof crash after commit')
        faults.at('publication.after_pointer', crash)
        with self.assertRaisesRegex(RuntimeError, 'proof crash'):
            self.publish(ref, observer=faults)
        committed_pointer = self.state.pointer('2026Q4')
        before = self.state.processing(ref).to_mapping()
        repair_publication('2026Q4', self.objects, self.state)
        partial = self.state.processing(ref).to_mapping()
        self.assertFalse(partial['value']['published'])
        self.assertEqual(self.state.pointer('2026Q4'), committed_pointer)
        self.publish(ref, quarter='2026Q3')
        self.assertTrue(self.state.processing(ref).value['published'])
        revised = self.observation(rows=row(), seconds=1)
        self.pin(date(2027, 1, 1))
        gated = self.publish(revised)
        self.assertEqual(gated.outcome, 'awaiting_approval')
        captures = [old, self.capture(), self.capture('2026Q3')]
        destination = os.environ.get('SEC_EDGAR_TASK5_PROOF_DIR')
        if destination:
            path = Path(destination)
            path.mkdir(parents=True, exist_ok=False)
            proof = {'old_and_current': [{'capture': capture.to_mapping(),
                     'manifest': read_manifest(capture, self.objects).to_mapping(),
                     'rows': [item.to_mapping() for item in self.rows(capture)]} for capture in captures],
                     'committed_pointer': committed_pointer.to_mapping(),
                     'before_repair': before, 'one_quarter_repaired': partial,
                     'fully_published': self.state.processing(ref).to_mapping(),
                     'gated_result': gated.to_mapping(),
                     'indexes': {kind: [item.to_mapping() for item in self.store.scan(kind, {})]
                         for kind in ('QuarterPublication', 'Candidate', 'Processing', 'PublicationReceipt', 'Source')}}
            (path / 'proof.json').write_text(json.dumps(proof, indent=2, sort_keys=True) + '\n')
            shutil.copytree(self.root / 'objects', path / 'objects')
            print('retained-publication-proof', str(path / 'proof.json'))

    def test_deadline_after_loss_retains_attempted_manifest_without_commit_claim(self):
        from sec_edgar_ingest.etl import publication
        ref = self.observation()
        now = self.context.started_at
        with patch.object(self.state, 'commit_pointer', side_effect=Conflict('lost race')) as commit:
            with patch.object(publication, '_now', side_effect=[now, now, self.context.deadline]):
                result = self.publish(ref)
        self.assertEqual((result.outcome, result.conflicts, commit.call_count), ('publication_conflict', 1, 1))
        self.assertEqual(result.manifest_ref, commit.call_args.args[1]['manifest_ref'])
        self.assertIsNone(result.generation_id)
        self.assertIsNone(result.candidate_ref)
        self.assertIsNone(self.state.pointer('2026Q4'))

    def test_late_spool_failure_exposes_no_row_after_successful_validation(self):
        from contextlib import closing
        from sec_edgar_ingest.etl import reader
        self.publish(self.observation(rows=row() + row(number=2)))
        capture = self.capture()
        actual_validate = reader.validated_manifest
        actual_rows = reader.iter_file_rows
        events = []
        emitted = []

        def validate(*args):
            manifest = actual_validate(*args)
            events.append('validated')
            return manifest

        def fail_after_real_row(ref, objects):
            self.assertEqual(events, ['validated'])
            with closing(actual_rows(ref, objects)) as rows:
                value = next(rows)
                emitted.append(value)
                events.append('spooled_row')
                yield value
                events.append('late_failure')
                raise OSError('injected late spool read failure')

        with patch.object(reader, 'validated_manifest', side_effect=validate):
            with patch.object(reader, 'iter_file_rows', side_effect=fail_after_real_row):
                with closing(reader.read_quarter(capture, self.objects)) as rows:
                    with self.assertRaisesRegex(OSError, 'injected late spool read failure'):
                        next(rows)
        self.assertEqual(events, ['validated', 'spooled_row', 'late_failure'])
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]['archive_path'], 'edgar/data/123456/0000123456-26-000001.txt')
        self.assertEqual(len(self.rows(capture)), 2)
