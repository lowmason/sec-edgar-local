"""Stage 1b C1 and C11: integrity checks read manifests and file hashes, never rows."""
from network_guard import install
install()

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from support_catalog import Lane, capture, row
from sec_edgar_ingest.etl import manifest as generation
from sec_edgar_ingest.etl import transform
from sec_edgar_ingest.etl.manifest import (approval_for, approval_ref, check_candidate_integrity,
                                           read_manifest)
from sec_edgar_ingest.etl.reader import checked_manifest, validated_manifest
from sec_edgar_ingest.etl.transform import _read_manifest, checked_observation
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage.contracts import Conflict


class GenerationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.lane = Lane()
        self.addCleanup(self.lane.close)
        self.candidate = self.lane.build([self.lane.observation(rows=row() + row(number=2))])
        self.capture = capture(self.candidate)

    def corrupt(self, name, body):
        path = self.lane.path(name)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(body(original))

    def test_accepts_the_exact_generation_without_reading_rows(self):
        with patch.object(generation, 'iter_file_rows', side_effect=AssertionError('read a row')), \
                patch.object(generation, '_validate_row_origins', side_effect=AssertionError('full check')):
            self.assertEqual(checked_manifest(self.capture, self.lane.objects),
                             read_manifest(self.capture, self.lane.objects))
            check_candidate_integrity(self.candidate, self.lane.objects)

    def test_refuses_a_changed_data_file_byte_with_the_full_check_class(self):
        data = next(ref for ref in self.candidate.manifest.files if ref.role == 'data')
        self.corrupt(data.path, lambda body: body[:-1] + bytes([body[-1] ^ 1]))
        for check in (checked_manifest, validated_manifest):
            with self.subTest(check=check.__name__), self.assertRaises(Conflict):
                check(self.capture, self.lane.objects)
        with self.assertRaises(Conflict):
            check_candidate_integrity(self.candidate, self.lane.objects)

    def test_refuses_a_missing_change_file_with_the_full_check_class(self):
        changes = next(ref for ref in self.candidate.manifest.files if ref.role == 'changes')
        path = self.lane.path(changes.path)
        original = path.read_bytes()
        path.unlink()
        self.addCleanup(path.write_bytes, original)
        for check in (checked_manifest, validated_manifest):
            with self.subTest(check=check.__name__), self.assertRaises(FileNotFoundError):
                check(self.capture, self.lane.objects)

    def test_refuses_a_changed_manifest(self):
        self.corrupt(self.capture.manifest_ref, lambda body: body + b' ')
        for check in (checked_manifest, validated_manifest):
            with self.subTest(check=check.__name__), self.assertRaises(Conflict):
                check(self.capture, self.lane.objects)


class GatedIntegrityTests(unittest.TestCase):
    """An awaiting-approval generation needs its exact approval and gate record, as today."""

    def setUp(self):
        self.lane = Lane()
        self.addCleanup(self.lane.close)
        old = self.lane.build([self.lane.observation(rows=row() + row(number=2))])
        revised = self.lane.observation(rows=row('Revised'), seconds=1)
        retained = self.lane.build([revised], old)
        self.lane.pin(date(2027, 1, 1))
        self.gated = self.lane.build([revised], retained)
        self.assertEqual(self.gated.manifest.gate, 'awaiting_approval')

    def approve(self, candidate):
        approval = approval_for(candidate, 'owner', datetime(2027, 1, 2, tzinfo=timezone.utc))
        self.lane.objects.put_once(approval_ref(candidate.manifest.quarter, candidate.manifest.generation_id),
                                   canonical_json(approval.to_mapping()))

    def test_refuses_an_awaiting_generation_without_its_approval(self):
        for check in (checked_manifest, validated_manifest):
            with self.subTest(check=check.__name__), \
                    self.assertRaisesRegex(ValueError, 'awaiting-approval generation cannot be current'):
                check(capture(self.gated), self.lane.objects)

    def test_accepts_an_approved_generation_without_reading_rows(self):
        self.approve(self.gated)
        with patch.object(generation, 'iter_file_rows', side_effect=AssertionError('read a row')):
            self.assertEqual(checked_manifest(capture(self.gated), self.lane.objects), self.gated.manifest)

    def test_refuses_a_changed_gate_record(self):
        path = self.lane.path(self.gated.candidate_ref)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b' ')
        with self.assertRaisesRegex(Conflict, 'candidate gate record differs'):
            check_candidate_integrity(self.gated, self.lane.objects)


class ObservationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.lane = Lane()
        self.addCleanup(self.lane.close)
        self.ref = self.lane.observation(rows=row() + row(number=2))

    def test_accepts_the_exact_observation_without_reading_rows(self):
        with patch.object(transform, '_verify_parquet', side_effect=AssertionError('read a row')):
            self.assertEqual(checked_observation(self.ref.manifest_ref, self.lane.objects), self.ref)

    def test_refuses_a_changed_rows_byte_with_the_readback_class(self):
        path = self.lane.path(self.ref.rows_ref)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        for check in (checked_observation, _read_manifest):
            with self.subTest(check=check.__name__), \
                    self.assertRaisesRegex(Conflict, 'observation bytes differ from manifest hash or length'):
                check(self.ref.manifest_ref, self.lane.objects)

    def test_refuses_a_changed_observation_manifest(self):
        path = self.lane.path(self.ref.manifest_ref)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b' ')
        for check in (checked_observation, _read_manifest):
            with self.subTest(check=check.__name__), self.assertRaises(ValueError):
                check(self.ref.manifest_ref, self.lane.objects)


if __name__ == '__main__':
    unittest.main()
