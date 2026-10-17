"""Offline immutable observation and crash-recovery contracts."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.transform import transform_workset, read_observations
from sec_edgar_ingest.state import AcquisitionState
from support import fixture_source
from support_etl import etl_context, seed_snapshot

HEADER = b'CIK|Company Name|Form Type|Date Filed|File Name\n-----\n'
ROW = b'123456|Example Corp|10-K/A|20250825|edgar/data/123456/0000123456-25-000001.txt\n'
BODY = HEADER + ROW


class EtlTransformTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = fixture_source('2026-09-30', 'daily')
        self.settings, self.context = etl_context()

    def seed(self, body=BODY):
        self.store, self.objects, self.origin = seed_snapshot(self.root, self.source, body)
        self.addCleanup(self.store.close)
        self.path = f'worksets/sec/snapshot/sha256={self.origin.workset_id}/workset.json'

    def transform(self, **kwargs):
        return transform_workset(self.path, self.context, self.settings, self.objects,
                                 EtlState(self.store), AcquisitionState(self.store), **kwargs)

    def test_parser_replay_keeps_raw_origin_and_changes_processing_identity(self):
        self.seed()
        source_path = f'worksets/sec/source/sha256={self.origin.source_workset_id}/workset.json'
        before = {path: self.objects.read(path) for path in (self.path, source_path, self.origin.snapshots[0].raw_path)}
        first = self.transform()
        again = self.transform()
        self.settings, self.context = etl_context('fixture-index-parser-v2', attempt='etl2')
        second = self.transform()
        self.assertTrue(first.complete and second.complete)
        self.assertEqual(first.observations, again.observations)
        self.assertNotEqual(first.observations[0].rows_ref, second.observations[0].rows_ref)
        self.assertEqual(second.origin_context, self.origin.context)
        for path, body in before.items():
            self.assertEqual(self.objects.read(path), body)
        self.assertEqual(list(read_observations(second.observations[0], self.objects))[0].row.cik, '0000123456')

    def test_duplicates_and_cross_quarter_counts_are_retained(self):
        self.seed(HEADER + ROW * 2 + ROW.replace(b'20250825', b'20260101').replace(b'000001.txt', b'000002.txt'))
        result = self.transform()
        self.assertTrue(result.complete, result.failures)
        ref = result.observations[0]
        self.assertEqual((ref.source_row_count, ref.distinct_key_count), (3, 2))
        self.assertEqual(dict(ref.quarter_counts), {'2025Q3': 2, '2026Q1': 1})
        self.assertEqual([obs.line_number for obs in read_observations(ref, self.objects)], [3, 4, 5])

    def test_conflicting_last_duplicate_after_full_batch_quarantines_source(self):
        self.seed(HEADER + ROW * 8192 + ROW.replace(b'Example Corp', b'Other Corp'))
        result = self.transform()
        self.assertFalse(result.complete)
        self.assertEqual(result.observations, ())
        self.assertEqual(result.failures[0].details['line_number'], 8195)
        self.assertIn('conflicting duplicate', result.failures[0].message)
        self.assertEqual(list(self.store.scan('Processing', {})), [])
        quarantine = list((self.root / 'objects/quarantine').rglob('error.json'))
        self.assertEqual(len(quarantine), 1)

    def test_corrupt_raw_and_accepted_data_fail_closed(self):
        self.seed()
        first = self.transform()
        self.assertTrue(first.complete)
        ref = first.observations[0]
        data = self.root / 'objects' / ref.rows_ref
        original = data.read_bytes()
        data.write_bytes(original[:-1])
        failed = self.transform()
        self.assertFalse(failed.complete)
        self.assertEqual(failed.observations, ())
        data.write_bytes(original)
        raw = self.root / 'objects' / self.origin.snapshots[0].raw_path
        raw.write_bytes(BODY.replace(b'Example', b'Changed'))
        self.assertFalse(self.transform(force=True).complete)
        self.assertIsNotNone(EtlState(self.store).processing(ref))

    def test_force_reparses_and_verifies_immutable_output(self):
        self.seed()
        first = self.transform()
        from sec_edgar_ingest.etl import transform
        with patch.object(transform, 'iter_observations', wraps=transform.iter_observations) as parse:
            forced = self.transform(force=True)
        self.assertTrue(forced.complete, forced.failures)
        parse.assert_called_once()
        self.assertEqual(first.observations, forced.observations)

    def test_interrupt_each_durability_boundary_and_repair(self):
        class Crash(BaseException):
            pass
        self.seed()
        for point in ('transform.after_rows', 'transform.after_manifest', 'transform.after_processing', 'transform.after_workset'):
            with self.subTest(point=point):
                def crash(observed):
                    if observed == point:
                        raise Crash(point)
                with self.assertRaises(Crash):
                    self.transform(force=True, observer=crash)
                result = self.transform()
                self.assertTrue(result.complete, result.failures)
                self.assertIsNotNone(EtlState(self.store).processing(result.observations[0]))

    def test_no_transport_constructors(self):
        self.seed()
        with (patch('sec_edgar_ingest.coordination.Coordinator', side_effect=AssertionError('transport')),
              patch('sec_edgar_ingest.download.BoundedSender', side_effect=AssertionError('transport')),
              patch('sec_edgar_ingest.download.RequestClient', side_effect=AssertionError('transport'))):
            self.assertTrue(self.transform().complete)
            self.assertTrue(self.transform(force=True).complete)

    def test_binding_mismatch_and_source_workset_mismatch_reject_input(self):
        self.seed()
        acquisition = AcquisitionState(self.store)
        with patch.object(acquisition, 'binding', return_value=None):
            with self.assertRaises(ValueError):
                transform_workset(self.path, self.context, self.settings, self.objects,
                                 EtlState(self.store), acquisition)
        source_path = f'worksets/sec/source/sha256={self.origin.source_workset_id}/workset.json'
        from support import fixture_workset
        from sec_edgar_ingest.worksets import encode_workset
        (self.root / 'objects' / source_path).write_bytes(encode_workset(fixture_workset(())))
        with self.assertRaises(ValueError):
            self.transform()

    def test_malformed_and_invalid_envelope_sources_never_accept(self):
        for body in (HEADER + b'bad row\n', b'<html>access denied</html>', BODY[:-1] + b'|extra\n'):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                store, objects, origin = seed_snapshot(Path(directory), self.source, body)
                try:
                    result = transform_workset(f'worksets/sec/snapshot/sha256={origin.workset_id}/workset.json',
                                               self.context, self.settings, objects, EtlState(store), AcquisitionState(store))
                    self.assertFalse(result.complete)
                    self.assertEqual(list(store.scan('Processing', {})), [])
                finally:
                    store.close()

    def test_manifest_repair_after_real_preprocessing_crash(self):
        class Crash(BaseException):
            pass
        self.seed()
        def crash(point):
            if point == 'transform.after_manifest':
                raise Crash()
        with self.assertRaises(Crash):
            self.transform(observer=crash)
        self.assertEqual(list(self.store.scan('Processing', {})), [])
        manifests = list((self.root / 'objects/observations').rglob('manifest.json'))
        self.assertEqual(len(manifests), 1)
        before = manifests[0].read_bytes()
        with patch('sec_edgar_ingest.etl.transform.iter_observations', side_effect=AssertionError('reparse')):
            repaired = self.transform()
        self.assertTrue(repaired.complete, repaired.failures)
        self.assertEqual(before, manifests[0].read_bytes())
        self.assertEqual(len(list(self.store.scan('Processing', {}))), 1)

    def test_image_change_adopts_original_producer_manifest_even_when_forced(self):
        from dataclasses import replace
        from sec_edgar_ingest.config import Settings, pin_context
        self.seed()
        first = self.transform()
        ref = first.observations[0]
        before = self.objects.read(ref.manifest_ref)
        mapping = self.settings.to_mapping()
        mapping['worker']['image_digest'] = 'sha256:' + 'b' * 64
        self.settings = Settings.from_mapping(mapping)
        updated = replace(self.context, image_digest=self.settings.worker.image_digest,
                          config_sha256=self.settings.config_sha256, effective_config={}, pinned_on=None)
        self.context = pin_context(self.settings, updated, updated.started_at.date())[0]
        second = self.transform(force=True)
        self.assertTrue(second.complete, second.failures)
        self.assertEqual(second.observations, first.observations)
        self.assertEqual(self.objects.read(ref.manifest_ref), before)

    def test_partial_members_recover_using_successful_processing(self):
        from sec_edgar_ingest.models import Binding
        from sec_edgar_ingest.worksets import encode_workset, make_snapshot_workset
        from support import fixture_snapshot, fixture_workset, store_bundle
        self.store, self.objects, leases = store_bundle(self.root)
        self.addCleanup(self.store.close)
        leases.close()
        sources = (self.source, fixture_source('2026-09-29', 'daily'))
        source_set = fixture_workset(sources)
        snapshots = tuple(fixture_snapshot(source, BODY) for source in sources)
        acquisition = AcquisitionState(self.store)
        for source, snapshot in zip(sources, snapshots):
            self.objects.put_once(snapshot.raw_path, BODY)
            acquisition.remember_snapshot(snapshot)
            acquisition.bind_once(Binding(source_set.workset_id, source.source_id, snapshot.sha256))
        self.origin = make_snapshot_workset(source_set, snapshots)
        self.path = f'worksets/sec/snapshot/sha256={self.origin.workset_id}/workset.json'
        self.objects.put_once(self.path, encode_workset(self.origin))
        self.objects.put_once(f'worksets/sec/source/sha256={source_set.workset_id}/workset.json', encode_workset(source_set))
        broken = self.root / 'objects' / snapshots[0].raw_path
        broken.write_bytes(b'corrupt')
        partial = self.transform()
        self.assertFalse(partial.complete)
        self.assertEqual(len(partial.observations), 1)
        broken.write_bytes(BODY)
        from sec_edgar_ingest.etl import transform
        with patch.object(transform, 'iter_observations', wraps=transform.iter_observations) as parser:
            recovered = self.transform()
        self.assertTrue(recovered.complete, recovered.failures)
        self.assertIn(partial.observations[0], recovered.observations)
        parser.assert_called_once()
        self.assertNotEqual(partial.workset_id, recovered.workset_id)

    def test_empty_complete_workset_and_incomplete_snapshot_membership(self):
        from sec_edgar_ingest.models import canonical_json, parse_json
        from sec_edgar_ingest.worksets import encode_workset, make_snapshot_workset
        from support import fixture_workset, store_bundle
        self.store, self.objects, leases = store_bundle(self.root)
        self.addCleanup(self.store.close)
        leases.close()
        source_set = fixture_workset(())
        self.origin = make_snapshot_workset(source_set, ())
        self.path = f'worksets/sec/snapshot/sha256={self.origin.workset_id}/workset.json'
        self.objects.put_once(self.path, encode_workset(self.origin))
        self.objects.put_once(f'worksets/sec/source/sha256={source_set.workset_id}/workset.json', encode_workset(source_set))
        result = self.transform()
        self.assertTrue(result.complete)
        self.assertEqual(result.observations, ())
        # Give the empty snapshot the nonempty directory evidence from a real member.
        payload = parse_json(self.objects.read(self.path))
        payload['directories'] = fixture_workset((self.source,)).to_mapping()['directories']
        import hashlib
        payload['workset_id'] = hashlib.sha256(canonical_json({k: v for k, v in payload.items() if k != 'workset_id'})).hexdigest()
        path = f"worksets/sec/snapshot/sha256={payload['workset_id']}/workset.json"
        self.objects.put_once(path, canonical_json(payload))
        self.path = path
        with self.assertRaises(ValueError):
            self.transform()

    def test_raw_length_drift_missing_accepted_output_and_force_collision(self):
        from dataclasses import replace
        from sec_edgar_ingest.etl.transform import transform_member
        self.seed()
        snapshot = self.origin.snapshots[0]
        with self.assertRaises(ValueError):
            transform_member(self.source, replace(snapshot, byte_count=snapshot.byte_count + 1),
                             self.context, self.settings, self.objects, EtlState(self.store))
        first = self.transform()
        ref = first.observations[0]
        data = self.root / 'objects' / ref.rows_ref
        body = data.read_bytes()
        data.unlink()
        self.assertFalse(self.transform().complete)
        data.write_bytes(body)
        from sec_edgar_ingest.etl import transform
        original = transform._write_rows
        def changed(*args):
            path, fresh = original(*args)
            return path, replace(fresh, rows_sha256='f' * 64)
        with patch.object(transform, '_write_rows', side_effect=changed):
            failed = self.transform(force=True)
        self.assertEqual(failed.failures[0].code, 'state_conflict')
        self.assertEqual(data.read_bytes(), body)

    def test_quarterly_zip_validation_and_crc_rejection(self):
        import io
        import zipfile
        from sec_edgar_ingest.etl.transform import transform_member
        from support import fixture_snapshot
        self.seed()
        source = fixture_source('2025Q3')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('master.idx', BODY.replace(b'File Name', b'Filename').replace(b'20250825', b'2025-08-25').replace(b'\n', b'\r\n'))
        body = buffer.getvalue()
        snapshot = fixture_snapshot(source, body)
        self.objects.put_once(snapshot.raw_path, body)
        ref = transform_member(source, snapshot, self.context, self.settings, self.objects, EtlState(self.store))
        self.assertEqual(dict(ref.quarter_counts), {'2025Q3': 1})
        corrupt = bytearray(body)
        central = corrupt.index(b'PK\x01\x02')
        corrupt[central + 16] ^= 1
        broken = fixture_snapshot(source, bytes(corrupt))
        self.objects.put_once(broken.raw_path, bytes(corrupt))
        with self.assertRaisesRegex(ValueError, 'invalid_archive'):
            transform_member(source, broken, self.context, self.settings, self.objects, EtlState(self.store))
        self.assertIsNotNone(EtlState(self.store).processing(ref))

    def test_concurrent_transform_adopts_one_immutable_manifest(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.seed()
        barrier = Barrier(2)
        def observe(point):
            if point == 'transform.after_rows':
                barrier.wait(timeout=10)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.transform, observer=observe) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertTrue(all(result.complete for result in results), results)
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(list(self.store.scan('Processing', {}))), 1)

    def test_new_process_reuses_accepted_output_with_guard_before_imports(self):
        import json
        import subprocess
        import sys
        self.seed()
        first = self.transform()
        context_file = self.root / 'context.json'
        context_file.write_text(json.dumps(self.context.to_mapping()))
        script = '''import sys
sys.path.insert(0, 'packages/sec-edgar-ingest/tests')
import network_guard
network_guard.install()
import json
from pathlib import Path
from unittest.mock import patch
from sec_edgar_ingest.models import RunContext
from sec_edgar_ingest.config import Settings
from sec_edgar_ingest.storage.local import LocalStateStore, LocalObjectStore
from sec_edgar_ingest.state import AcquisitionState
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.transform import transform_workset
root, path = Path(sys.argv[1]), sys.argv[2]
context = RunContext.from_mapping(json.loads((root / 'context.json').read_text()))
settings = Settings.from_mapping(context.to_mapping()['effective_config'])
store, objects = LocalStateStore(root), LocalObjectStore(root)
try:
    with patch('sec_edgar_ingest.etl.transform.iter_observations', side_effect=AssertionError('reparse')):
        result = transform_workset(path, context, settings, objects, EtlState(store), AcquisitionState(store))
    assert result.complete, result.failures
    print(json.dumps(result.to_mapping()))
finally:
    store.close()
'''
        child = subprocess.run([sys.executable, '-c', script, str(self.root), self.path], capture_output=True, text=True, timeout=20)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(json.loads(child.stdout), first.to_mapping())

    def test_binding_must_match_all_identity_fields(self):
        from sec_edgar_ingest.models import Binding
        self.seed()
        acquisition = AcquisitionState(self.store)
        wrong = Binding('a' * 64, self.source.source_id, self.origin.snapshots[0].sha256)
        with patch.object(acquisition, 'binding', return_value=wrong):
            with self.assertRaises(ValueError):
                transform_workset(self.path, self.context, self.settings, self.objects, EtlState(self.store), acquisition)

    def test_readback_counts_and_scratch_iterator_lifetime(self):
        from dataclasses import replace
        from sec_edgar_ingest.etl import transform
        self.seed()
        ref = self.transform().observations[0]
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            list(read_observations(replace(ref, source_row_count=2, quarter_counts={'2025Q3': 2}), self.objects))
        scratch_parent = self.root / 'scratch'
        scratch_parent.mkdir()
        original = tempfile.TemporaryDirectory
        def scratch(**kwargs):
            return original(dir=scratch_parent, **kwargs)
        with patch.object(transform, 'TemporaryDirectory', side_effect=scratch):
            iterator = read_observations(ref, self.objects)
            next(iterator)
            self.assertEqual(len(list(scratch_parent.iterdir())), 1)
            iterator.close()
            self.assertEqual(list(scratch_parent.iterdir()), [])

    def test_deadline_uses_injected_clock_without_expired_fixture(self):
        from unittest.mock import Mock
        self.seed()
        clock = Mock()
        clock.now.return_value = self.context.deadline
        with patch('sec_edgar_ingest.etl.transform.datetime', clock):
            with self.assertRaisesRegex(TimeoutError, 'deadline'):
                self.transform()
        self.assertEqual(list(self.store.scan('Processing', {})), [])

    def test_uploaded_data_is_read_back_before_accepting_checkpoint(self):
        self.seed()
        original_stage = self.objects.stage
        def corrupt(path, body):
            result = original_stage(path, body)
            (self.root / 'objects' / path).write_bytes(b'corrupted output')
            return result
        with patch.object(self.objects, 'stage', side_effect=corrupt):
            result = self.transform()
        self.assertFalse(result.complete)
        self.assertEqual(list(self.store.scan('Processing', {})), [])
        self.assertEqual(list((self.root / 'objects/observations').rglob('manifest.json')), [])
