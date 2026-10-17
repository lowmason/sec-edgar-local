"""Offline withdrawal approval evidence, reader acceptance and the approve operation."""
from network_guard import install
install()

import hashlib
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from support_approval import GateFixture, operator_cli, row
from sec_edgar_ingest.etl.contracts import Candidate, WithdrawalApproval
from sec_edgar_ingest.etl.manifest import approval_for, approval_ref, read_approval, read_manifest
from sec_edgar_ingest.etl.publication import pointer_value, repair_publication
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage.contracts import Conflict, blob_address, table_for
from support import Faults
from sec_edgar_ingest.etl.approval import approve

APPROVED_AT = datetime(2027, 1, 2, tzinfo=timezone.utc)


class ApprovalEvidenceTests(GateFixture):
    def test_approval_binds_the_exact_candidate_and_validates_its_fields(self):
        base, revised, candidate = self.gated()
        approval = approval_for(candidate, 'Lowell Mason', APPROVED_AT)
        manifest = candidate.manifest
        self.assertEqual((approval.quarter, approval.generation_id, approval.base_generation_id),
                         ('2026Q4', manifest.generation_id, base.generation_id))
        self.assertEqual(approval.quarterly_sha256, revised.snapshot.sha256)
        self.assertEqual(approval.gate_sha256,
                         hashlib.sha256(self.objects.read(candidate.candidate_ref)).hexdigest())
        self.assertEqual((approval.manifest_ref, approval.format_version),
                         (candidate.manifest_ref, 'sec-withdrawal-approval-v1'))
        self.assertEqual(WithdrawalApproval.from_mapping(approval.to_mapping()), approval)
        ref = approval_ref('2026Q4', manifest.generation_id)
        self.assertEqual(ref, 'approvals/sec/filing_index/year=2026/quarter=4/generation='
                         + manifest.generation_id + '/approval.json')
        self.assertEqual(blob_address(ref), ('approvals', ref.removeprefix('approvals/')))
        for approver in ('', '   ', 'two\nlines', 'tab\there', 'x' * 257, 'zero\u200bwidth'):
            with self.subTest(approver=approver), self.assertRaises(ValueError):
                approval_for(candidate, approver, APPROVED_AT)
        self.assertEqual(approval_for(candidate, 'x' * 256, APPROVED_AT).approver, 'x' * 256)
        with self.assertRaises(ValueError):
            approval_for(candidate, 'Lowell Mason', APPROVED_AT.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            replace(approval, format_version='sec-withdrawal-approval-v0')
        clear = Candidate(read_manifest(base, self.objects), base.manifest_ref, base.manifest_sha256,
                          base.manifest_bytes, None)
        with self.assertRaisesRegex(ValueError, 'exact awaiting-approval candidate'):
            approval_for(clear, 'Lowell Mason', APPROVED_AT)

    def test_reader_accepts_an_awaiting_approval_pointer_only_with_its_exact_approval(self):
        _, _, candidate = self.gated()
        self.state.commit_pointer('2026Q4', pointer_value(candidate), self.state.pointer('2026Q4'))
        with self.assertRaisesRegex(ValueError, 'awaiting-approval'):
            self.capture()
        with self.assertRaisesRegex(ValueError, 'awaiting-approval'):
            repair_publication('2026Q4', self.objects, self.state)
        approval = approval_for(candidate, 'Lowell Mason', APPROVED_AT)
        ref = approval_ref('2026Q4', candidate.manifest.generation_id)
        self.objects.put_once(ref, canonical_json(approval.to_mapping()))
        self.assertEqual(self.rows(), [(1, 'Example')])
        repair_publication('2026Q4', self.objects, self.state)
        self.assertEqual(read_approval(candidate, self.objects), approval)
        path = self.object_path(ref)
        path.write_bytes(json.dumps(approval.to_mapping(), indent=1).encode())
        with self.assertRaisesRegex(ValueError, 'canonical JSON'):
            self.capture()
        path.write_bytes(canonical_json(replace(approval, quarterly_sha256='0' * 64).to_mapping()))
        with self.assertRaisesRegex(ValueError, 'not bound'):
            self.capture()

    def test_approval_index_is_immutable_and_routes_to_the_approvals_table(self):
        _, _, candidate = self.gated()
        approval = approval_for(candidate, 'Lowell Mason', APPROVED_AT)
        self.assertIsNone(self.state.approval(approval.generation_id))
        self.state.record_approval(approval)
        self.state.record_approval(approval)
        self.assertEqual(self.state.approval(approval.generation_id), approval)
        with self.assertRaises(Conflict):
            self.state.record_approval(replace(approval, approver='Someone Else'))
        self.assertEqual(table_for('WithdrawalApproval'), 'Approvals')


class ApproveTests(GateFixture):
    def approve(self, candidate, quarterly_sha256, approver='Lowell Mason', **kwargs):
        return approve('2026Q4', candidate.manifest.generation_id, quarterly_sha256, approver,
                       self.objects, self.state, **kwargs)

    def assert_unwritten(self, candidate):
        self.assertIsNone(self.state.approval(candidate.manifest.generation_id))
        with self.assertRaises(FileNotFoundError):
            self.objects.read(approval_ref('2026Q4', candidate.manifest.generation_id))

    def moved_base(self):
        """A clear closed-quarter update (no withdrawal) that publishes over the candidate's base."""
        return self.observation(rows=row('Updated') + row(number=2), seconds=2)

    def test_approve_activates_the_exact_candidate_once(self):
        _, revised, candidate = self.gated()
        result = self.approve(candidate, revised.snapshot.sha256)
        self.assertEqual((result.outcome, result.publication.outcome, result.publication.generation_id),
                         ('success', 'published', candidate.manifest.generation_id))
        self.assertEqual(result.approval, self.state.approval(candidate.manifest.generation_id))
        self.assertEqual(result.approval, read_approval(candidate, self.objects))
        self.assertEqual(self.capture().generation_id, candidate.manifest.generation_id)
        self.assertEqual(self.rows(), [(1, 'Example')])
        pointer = self.state.pointer('2026Q4')
        again = self.approve(candidate, revised.snapshot.sha256, 'Someone Else')
        self.assertEqual((again.outcome, again.approval.approver), ('unchanged', 'Lowell Mason'))
        self.assertEqual(self.state.pointer('2026Q4'), pointer)

    def test_refusals_write_nothing(self):
        base, revised, candidate = self.gated()
        generation = candidate.manifest.generation_id
        cases = {
            'wrong quarterly hash': ('2026Q4', generation, '0' * 64, 'Lowell Mason'),
            'clear generation': ('2026Q4', base.generation_id, revised.snapshot.sha256, 'Lowell Mason'),
            'missing generation': ('2026Q4', 'f' * 64, revised.snapshot.sha256, 'Lowell Mason'),
            'invalid quarter': ('2026Q5', generation, revised.snapshot.sha256, 'Lowell Mason'),
            'invalid hash text': ('2026Q4', generation, 'not-a-hash', 'Lowell Mason'),
            'invalid approver': ('2026Q4', generation, revised.snapshot.sha256, 'two\nlines'),
        }
        pointer = self.state.pointer('2026Q4')
        for label, args in cases.items():
            with self.subTest(label):
                result = approve(*args, self.objects, self.state)
                self.assertEqual((result.outcome, result.error.code), ('approval_refused', 'approval_refused'))
                self.assertIsNone(result.publication)
        self.assertEqual(self.state.pointer('2026Q4'), pointer)
        self.assert_unwritten(candidate)

    def test_a_moved_base_makes_the_candidate_stale_without_writes(self):
        _, revised, candidate = self.gated()
        self.assertEqual(self.publish(self.moved_base()).outcome, 'published')
        pointer = self.state.pointer('2026Q4')
        result = self.approve(candidate, revised.snapshot.sha256)
        self.assertEqual((result.outcome, result.error.code), ('approval_stale', 'approval_stale'))
        self.assertEqual(result.error.details['base_generation_id'], candidate.manifest.base_generation_id)
        self.assertEqual(self.state.pointer('2026Q4'), pointer)
        self.assert_unwritten(candidate)

    def test_the_first_stored_approval_wins(self):
        _, revised, candidate = self.gated()
        first = approval_for(candidate, 'First Approver', APPROVED_AT)
        self.objects.put_once(approval_ref('2026Q4', candidate.manifest.generation_id),
                              canonical_json(first.to_mapping()))
        result = self.approve(candidate, revised.snapshot.sha256)
        self.assertEqual((result.outcome, result.approval), ('success', first))
        self.assertEqual(self.state.approval(candidate.manifest.generation_id), first)

    def test_a_lost_pointer_race_rereads_to_unchanged(self):
        _, revised, candidate = self.gated()
        faults = Faults()
        faults.at('approval.before_pointer', lambda: self.assertEqual(
            self.approve(candidate, revised.snapshot.sha256, 'Second Approver').outcome, 'success'))
        result = self.approve(candidate, revised.snapshot.sha256, observer=faults)
        self.assertEqual((result.outcome, result.publication.conflicts), ('unchanged', 1))
        self.assertEqual(result.approval.approver, 'Lowell Mason')

    def test_a_lost_pointer_race_to_a_new_generation_is_stale(self):
        _, revised, candidate = self.gated()
        moved = self.moved_base()
        faults = Faults()
        faults.at('approval.before_pointer', lambda: self.assertEqual(self.publish(moved).outcome, 'published'))
        result = self.approve(candidate, revised.snapshot.sha256, 'Racing Approver', observer=faults)
        self.assertEqual(result.outcome, 'approval_stale')
        self.assertNotEqual(self.capture().generation_id, candidate.manifest.generation_id)
        # The approval is written before the pointer swap, so the lost race leaves an exact-bound orphan.
        orphan = self.state.approval(candidate.manifest.generation_id)
        self.assertIsNotNone(orphan)
        self.assertEqual(read_approval(candidate, self.objects), orphan)
        self.assertEqual(orphan.approver, 'Racing Approver')
        self.assertNotEqual(self.state.pointer('2026Q4').value['generation_id'], candidate.manifest.generation_id)

    def test_after_approval_only_a_new_quarterly_snapshot_changes_membership(self):
        _, revised, candidate = self.gated()
        self.assertEqual(self.approve(candidate, revised.snapshot.sha256).outcome, 'success')
        self.publish(self.observation(period='2026-10-02', kind='daily', rows=row(number=2)))
        self.assertEqual(self.rows(), [(1, 'Example')])
        returned = self.observation(rows=row() + row('Returned', number=2), seconds=2)
        self.assertEqual(self.publish(returned).outcome, 'published')
        self.assertEqual(read_manifest(self.capture(), self.objects).added, 1)
        self.assertEqual(self.rows(), [(1, 'Example'), (2, 'Returned')])
        renamed = self.observation(rows=row('Renamed'), seconds=3)
        gated = self.publish(renamed)
        self.assertEqual(gated.outcome, 'awaiting_approval')
        later = self.candidate(gated.candidate_ref)
        self.assertEqual(self.approve(later, revised.snapshot.sha256).outcome, 'approval_refused')
        self.assertEqual(self.approve(later, renamed.snapshot.sha256).outcome, 'success')
        self.assertEqual(self.rows(), [(1, 'Renamed')])

    def test_approve_cli_maps_named_outcomes_to_exit_codes(self):
        _, revised, candidate = self.gated()
        generation = candidate.manifest.generation_id
        command = ('approve', '--config', str(self.write_config()), '--state-dir', str(self.root),
                   '--quarter', '2026Q4', '--generation', generation, '--approver', 'Lowell Mason')
        code, message, _ = operator_cli(*command, '--quarterly-sha256', '0' * 64)
        self.assertEqual((code, message['outcome'], message['approval_ref']), (2, 'approval_refused', None))
        code, message, events = operator_cli(*command, '--quarterly-sha256', revised.snapshot.sha256)
        self.assertEqual((code, message['outcome']), (0, 'success'))
        self.assertEqual((message['quarter'], message['generation_id']), ('2026Q4', generation))
        self.assertEqual(message['approval_ref'], approval_ref('2026Q4', generation))
        self.assertEqual(message['approval']['approver'], 'Lowell Mason')
        self.assertEqual(json.loads(events.splitlines()[-1])['event'], 'withdrawal_approval')
        code, message, _ = operator_cli(*command, '--quarterly-sha256', revised.snapshot.sha256)
        self.assertEqual((code, message['outcome']), (0, 'unchanged'))
        missing = ('approve', '--config', str(self.root / 'missing.json'), '--quarter', '2026Q4',
                   '--generation', generation, '--quarterly-sha256', revised.snapshot.sha256, '--approver', 'x')
        self.assertEqual(operator_cli(*missing)[:2], (2, None))

    def test_a_corrupt_approval_object_reports_state_conflict_through_the_cli(self):
        _, revised, candidate = self.gated()
        generation = candidate.manifest.generation_id
        command = ('approve', '--config', str(self.write_config()), '--state-dir', str(self.root),
                   '--quarter', '2026Q4', '--generation', generation, '--approver', 'Lowell Mason',
                   '--quarterly-sha256', revised.snapshot.sha256)
        code, message, _ = operator_cli(*command)
        self.assertEqual((code, message['outcome']), (0, 'success'))
        self.object_path(approval_ref('2026Q4', generation)).write_bytes(
            json.dumps(message['approval'], indent=1).encode())
        code, message, _ = operator_cli(*command)
        self.assertEqual((code, message['outcome']), (9, 'state_conflict'))
        self.assertEqual(set(message), {'outcome', 'quarter', 'generation_id', 'approval_ref', 'approval',
                                        'publication', 'activation', 'activation_ref', 'error'})
        self.assertEqual(message['error']['code'], 'state_conflict')

    def test_approve_cli_reports_a_stale_candidate_with_exit_11(self):
        _, revised, candidate = self.gated()
        self.assertEqual(self.publish(self.moved_base()).outcome, 'published')
        code, message, _ = operator_cli(
            'approve', '--config', str(self.write_config()), '--state-dir', str(self.root),
            '--quarter', '2026Q4', '--generation', candidate.manifest.generation_id,
            '--quarterly-sha256', revised.snapshot.sha256, '--approver', 'Lowell Mason')
        self.assertEqual((code, message['outcome']), (11, 'approval_stale'))


if __name__ == '__main__':
    unittest.main()
