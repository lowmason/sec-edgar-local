"""R5/R7/R10 operator acceptance: reconcile, review, approve, reintroduce and roll back through the CLI."""
from network_guard import install
install()

import unittest

from support_approval import operator_cli
from support_reconcile import A, B, ReconcileFixture, sha
from sec_edgar_ingest.etl.history import quarter_history
from sec_edgar_ingest.etl.state import EtlState


class ReconcileAcceptanceTests(ReconcileFixture):
    def test_reconcile_gate_review_approve_reintroduce_and_roll_back(self):
        h = self.harness((A, B))
        self.assertEqual(self.run_phase(h, 'backfill', 'base')[0], 0, h.calls[-1])
        code, _, report = self.run_phase(h, 'reconcile', 'same', (A, B))
        self.assertEqual((code, report.outcome), (0, 'unchanged'), h.calls[-1])
        code, _, report = self.run_phase(h, 'reconcile', 'gate', (A,))
        self.assertEqual((code, report.outcome, report.counts['awaiting_approval_quarters']),
                         (10, 'awaiting_approval', 1), h.calls[-1])
        self.assertEqual(self.names(h, '2026Q3'), ['A', 'B'])

        operator = ('--config', str(h.config), '--state-dir', str(h.root))
        code, listing, _ = operator_cli('candidates', *operator)
        self.assertEqual(code, 0)
        request, = listing['candidates']
        self.assertEqual((request['status'], request['approved'], request['quarterly_sha256'],
                          request['latest_observed_sha256']), ('pending', False, sha((A,)), sha((A,))))
        self.assertEqual([row['company_name'] for row in request['withdrawn']], ['B'])

        command = ('approve', *operator, '--quarter', '2026Q3', '--generation', request['generation_id'],
                   '--approver', 'Lowell Mason')
        code, refused, _ = operator_cli(*command, '--quarterly-sha256', sha((A, B)))
        self.assertEqual((code, refused['outcome']), (2, 'approval_refused'))
        self.assertEqual(self.names(h, '2026Q3'), ['A', 'B'])
        code, approved, _ = operator_cli(*command, '--quarterly-sha256', sha((A,)))
        self.assertEqual((code, approved['outcome']), (0, 'success'))
        self.assertEqual(self.names(h, '2026Q3'), ['A'])
        self.assertEqual(operator_cli(*command, '--quarterly-sha256', sha((A,)))[1]['outcome'], 'unchanged')

        code, _, report = self.run_phase(h, 'reconcile', 'after', (A,))
        self.assertEqual((code, report.outcome), (0, 'unchanged'), h.calls[-1])
        returned = ('123456', 'B Returned', *B[2:])
        code, _, report = self.run_phase(h, 'reconcile', 'returned', (A, returned))
        self.assertEqual((code, report.outcome), (0, 'success'), h.calls[-1])
        self.assertEqual(self.names(h, '2026Q3'), ['A', 'B Returned'])
        history = quarter_history('2026Q3', h.objects, EtlState(h.store))
        self.assertEqual([entry['gate'] for entry in history], ['clear', 'awaiting_approval', 'clear'])
        self.assertEqual((history[0]['added'], history[1]['withdrawn']), (1, 1))
        self.assertEqual(history[1]['approval']['approver'], 'Lowell Mason')
        code, listing, _ = operator_cli('candidates', *operator)
        self.assertEqual([(entry['status'], entry['approved']) for entry in listing['candidates']],
                         [('stale', True)])

        # The SEC reverts to the approved (A,) bytes: reported, not published.
        code, _, report = self.run_phase(h, 'reconcile', 'revert', (A,))
        self.assertEqual((code, report.outcome), (3, 'incomplete'), h.calls[-1])
        self.assertEqual([gap.code for gap in report.gaps], ['source_reverted'])
        self.assertEqual(self.names(h, '2026Q3'), ['A', 'B Returned'])
        history = quarter_history('2026Q3', h.objects, EtlState(h.store))
        target = next(entry for entry in history if entry['membership_sha256'] == sha((A,)))
        code, rolled, _ = operator_cli('rollback', *operator, '--quarter', '2026Q3',
                                       '--from-generation', history[0]['generation_id'],
                                       '--to-generation', target['generation_id'],
                                       '--operator', 'Lowell Mason', '--reason', 'SEC reverted to the approved bytes')
        self.assertEqual((code, rolled['outcome']), (0, 'success'))
        self.assertEqual(self.names(h, '2026Q3'), ['A'])
        self.assertEqual([record.to_generation_id for record in EtlState(h.store).rollbacks('2026Q3')],
                         [target['generation_id']])
        code, _, report = self.run_phase(h, 'reconcile', 'restored', (A,))
        self.assertEqual((code, report.outcome, report.gaps), (0, 'unchanged', ()), h.calls[-1])
        code, listing, _ = operator_cli('candidates', *operator)
        self.assertEqual([(entry['status'], entry['approved']) for entry in listing['candidates']],
                         [('active', True)])


if __name__ == '__main__':
    unittest.main()
