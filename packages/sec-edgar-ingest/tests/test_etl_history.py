"""Offline withdrawal approval requests and per-quarter generation lineage."""
from network_guard import install
install()

import unittest
from itertools import islice
from unittest import mock

from support import Faults
from support_approval import GateFixture, operator_cli, row
from sec_edgar_ingest.etl.approval import approve
from sec_edgar_ingest.etl.contracts import GenerationCapture
from sec_edgar_ingest.etl.history import lineage, quarter_history, withdrawal_candidates
from sec_edgar_ingest.storage.contracts import Conflict


def capture_of(candidate):
    return GenerationCapture(candidate.manifest.quarter, candidate.manifest.generation_id, candidate.manifest_ref,
                             candidate.manifest_sha256, candidate.manifest_bytes)


class HistoryTests(GateFixture):
    def approve(self, candidate, revised):
        result = approve('2026Q4', candidate.manifest.generation_id, revised.snapshot.sha256, 'Lowell Mason',
                         self.objects, self.state)
        self.assertEqual(result.outcome, 'success')
        return result

    def candidates_cli(self):
        return operator_cli('candidates', '--config', str(self.write_config()), '--state-dir', str(self.root))

    def test_lineage_refuses_a_cycle_or_a_self_reference(self):
        base, _, candidate = self.gated()
        top = capture_of(candidate)
        self.assertEqual([capture for capture, _ in lineage(top, self.objects)], [top, base])
        cases = {'cycle': ({top.generation_id: base, base.generation_id: top}, [top, base]),
                 'self-reference': ({top.generation_id: top}, [top])}
        for label, (bases, expected) in cases.items():
            walked = []
            # Generation ids are content hashes, so only a forged retained base can close a loop.
            with self.subTest(label), mock.patch('sec_edgar_ingest.etl.history.retained_base',
                                                 lambda manifest, _: bases[manifest.generation_id]):
                with self.assertRaisesRegex(Conflict, 'lineage repeats a generation'):
                    for capture, _ in islice(lineage(top, self.objects), 5):
                        walked.append(capture)
                self.assertEqual(walked, expected)

    def test_lineage_raises_when_a_retained_base_manifest_is_missing(self):
        base, _, candidate = self.gated()
        top = capture_of(candidate)
        self.object_path(base.manifest_ref).unlink()
        walk = lineage(top, self.objects)
        self.assertEqual(next(walk)[0], top)
        # The top's retained-base record still names the base; reading the base manifest itself fails.
        with self.assertRaises(FileNotFoundError):
            next(walk)

    def test_history_walks_the_exact_lineage_with_approval_evidence(self):
        base, revised, candidate = self.gated()
        approved = self.approve(candidate, revised)
        returned = self.observation(rows=row() + row('Returned', number=2), seconds=2)
        self.assertEqual(self.publish(returned).outcome, 'published')
        history = quarter_history('2026Q4', self.objects, self.state)
        self.assertEqual([entry['gate'] for entry in history], ['clear', 'awaiting_approval', 'clear'])
        self.assertEqual([entry['generation_id'] for entry in history[1:]],
                         [candidate.manifest.generation_id, base.generation_id])
        self.assertEqual(history[0]['base_generation_id'], candidate.manifest.generation_id)
        self.assertEqual((history[0]['added'], history[1]['withdrawn'], history[2]['row_count']), (1, 1, 2))
        self.assertEqual(history[1]['approval'], approved.approval.to_mapping())
        self.assertEqual(history[1]['membership_sha256'], revised.snapshot.sha256)
        self.assertEqual((history[2]['approval'], history[2]['base_generation_id']), (None, None))
        self.assertTrue(history[1]['changes']['path'].endswith('/changes.parquet'))
        self.assertEqual(quarter_history('2026Q3', self.objects, self.state), ())

    def test_candidates_report_status_approval_and_withdrawn_rows(self):
        base, revised, candidate = self.gated()
        listed, = withdrawal_candidates(self.objects, self.state)
        self.assertEqual((listed['status'], listed['approved'], listed['quarterly_sha256']),
                         ('pending', False, revised.snapshot.sha256))
        self.assertEqual((listed['base_generation_id'], listed['candidate_ref']),
                         (base.generation_id, candidate.candidate_ref))
        self.assertEqual([item['archive_path'] for item in listed['withdrawn']],
                         ['edgar/data/123456/0000123456-26-000002.txt'])
        # seed_observation records no acquisition state; the CLI acceptance covers observed hashes.
        self.assertEqual((listed['latest_observed_sha256'], listed['latest_observed_at']), (None, None))
        self.approve(candidate, revised)
        listed, = withdrawal_candidates(self.objects, self.state)
        self.assertEqual((listed['status'], listed['approved']), ('active', True))
        self.publish(self.observation(rows=row() + row('Returned', number=2), seconds=2))
        listed, = withdrawal_candidates(self.objects, self.state)
        self.assertEqual(listed['status'], 'stale')

    def test_candidates_cli_prints_the_listing(self):
        _, _, candidate = self.gated()
        code, message, _ = operator_cli('candidates', '--config', str(self.write_config()),
                                        '--state-dir', str(self.root))
        self.assertEqual((code, message['outcome'], message['error']), (0, 'success', None))
        self.assertEqual([entry['generation_id'] for entry in message['candidates']],
                         [candidate.manifest.generation_id])
        self.assertEqual(operator_cli('candidates', '--config', str(self.root / 'missing.json'))[:2], (2, None))

    def test_candidates_cli_reports_a_failed_listing_with_exit_9(self):
        self.gated()
        for error, outcome in ((Conflict('changes object drifted'), 'state_conflict'),
                               (RuntimeError('listing exploded'), 'internal_error')):
            with self.subTest(outcome), mock.patch('sec_edgar_ingest.etl.history.iter_file_rows', side_effect=error):
                code, message, _ = self.candidates_cli()
                self.assertEqual((code, message), (9, {'outcome': outcome, 'candidates': None, 'error': {
                    'code': outcome, 'message': str(error), 'retryable': False, 'source_id': None,
                    'details': {'type': type(error).__name__}}}))

    def test_a_corrupt_candidate_row_fails_the_whole_listing(self):
        _, _, first = self.gated()
        withdrawn = self.publish(self.observation(rows=row(number=2), seconds=2))
        self.assertEqual(withdrawn.outcome, 'awaiting_approval')
        second = self.candidate(withdrawn.candidate_ref)
        self.assertEqual(len(withdrawal_candidates(self.objects, self.state)), 2)
        # Corrupt the row scanned last, so a valid entry has already been listed when the drift is found.
        corrupt, other = sorted((first, second), key=lambda candidate: candidate.manifest.generation_id, reverse=True)
        stored = self.store.get('Candidate', corrupt.manifest.generation_id)
        self.store.replace('Candidate', corrupt.manifest.generation_id,
                           {**stored.value, 'candidate_ref': other.candidate_ref}, stored.version)
        with self.assertRaisesRegex(Conflict, 'candidate index differs'):
            withdrawal_candidates(self.objects, self.state)
        code, message, _ = self.candidates_cli()
        self.assertEqual((code, message['outcome'], message['candidates'], message['error']['details']),
                         (9, 'state_conflict', None, {'type': 'Conflict'}))

    def test_candidates_report_an_approval_whose_pointer_race_was_lost(self):
        _, revised, candidate = self.gated()
        moved = self.observation(rows=row('Updated') + row(number=2), seconds=2)
        faults = Faults()
        faults.at('approval.before_pointer', lambda: self.assertEqual(self.publish(moved).outcome, 'published'))
        result = approve('2026Q4', candidate.manifest.generation_id, revised.snapshot.sha256, 'Racing Approver',
                         self.objects, self.state, observer=faults)
        self.assertEqual(result.outcome, 'approval_stale')
        listed, = withdrawal_candidates(self.objects, self.state)
        self.assertEqual((listed['generation_id'], listed['status'], listed['approved']),
                         (candidate.manifest.generation_id, 'stale', True))


if __name__ == '__main__':
    unittest.main()
