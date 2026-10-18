"""One `workflow_summary` per fresh workflow result; it never changes the result, stdout or exit code."""
from network_guard import install
install()

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from support_approval import operator_cli
from support_reconcile import sha
from support_scenario import BASE_Q3, GATED_Q3, scenario_pack, scenario_settings
from support_workflows import CommandHarness
from sec_edgar_ingest.workflows.contracts import LOCAL_CONTRACT
from sec_edgar_ingest.workflows.results import read_workflow_result
from sec_edgar_ingest.workflows.summary import (MILESTONE_KIND, RECONCILE_MILESTONE, SUMMARY_FIELDS,
                                                last_successful_reconcile, record_reconcile_success)


class WorkflowSummaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.h = CommandHarness(self.root, scenario_pack(self.root, 'pack-1', BASE_Q3), scenario_settings())
        self.addCleanup(self.h.close)

    def events(self):
        return [json.loads(line) for line in self.h.calls[-1]['stderr'].splitlines()]

    def summary(self):
        events = self.events()
        self.assertEqual([event['event'] for event in events[-2:]], ['command_finished', 'workflow_summary'])
        self.assertEqual(set(events[-1]['fields']), SUMMARY_FIELDS)
        return events[-1]['fields']

    def gate(self):
        self.assertEqual(self.h.invoke('backfill', run='base')[0], 0)
        self.assertEqual(self.h.invoke('daily', run='day')[0], 0)
        self.h.pack = scenario_pack(self.root, 'pack-2', GATED_Q3)
        self.assertEqual(self.h.invoke('reconcile', run='gate')[0], 10)

    def test_each_fresh_result_logs_one_summary_after_command_finished(self):
        self.assertEqual(self.h.invoke('backfill', run='base')[0], 0)
        fields = self.summary()
        self.assertEqual((fields['command'], fields['outcome'], fields['summary_error']), ('backfill', 'success', None))
        self.assertEqual(fields['counts'], self.h.calls[-1]['stdout']['counts'])
        self.assertEqual(fields['result_ref'], self.h.calls[-1]['stdout']['result_ref'])
        self.assertEqual(self.h.invoke('daily', run='day')[0], 0)
        fields = self.summary()
        self.assertEqual((fields['outcome'], fields['discovery_complete'], fields['pending_approvals'],
                          fields['last_successful_reconcile_at']), ('no_new_sources', True, 0, None))

    def test_a_gated_reconcile_reports_its_pending_approval_and_oldest_unresolved_source(self):
        self.gate()
        fields = self.summary()
        self.assertEqual((fields['outcome'], fields['pending_approvals'], fields['oldest_unresolved_period'],
                          fields['last_successful_reconcile_at']), ('awaiting_approval', 1, '2026Q3', None))
        self.assertGreaterEqual(fields['member_outcomes']['awaiting_approval'], 1)

    def test_a_successful_reconcile_advances_the_milestone_that_every_summary_reports(self):
        self.gate()
        listing = operator_cli('candidates', '--config', str(self.h.config))[1]
        request, = listing['candidates']
        approved = operator_cli('approve', '--config', str(self.h.config),
                                '--quarter', '2026Q3', '--generation', request['generation_id'],
                                '--quarterly-sha256', sha(GATED_Q3), '--approver', 'Lowell Mason')
        self.assertEqual(approved[0], 0)
        self.assertEqual(self.h.invoke('reconcile', run='after')[0], 0)
        reference = self.h.calls[-1]['stdout']['result_ref']
        ended_at = json.loads(self.h.objects.read(reference))['ended_at']
        self.assertEqual(self.summary()['last_successful_reconcile_at'], ended_at)
        self.assertEqual(dict(self.h.store.get(MILESTONE_KIND, RECONCILE_MILESTONE).value),
                         {'contract_version': LOCAL_CONTRACT, 'workflow': 'reconcile', 'ended_at': ended_at, 'result_ref': reference})
        self.assertEqual(self.h.invoke('daily', run='day2')[0], 0)
        self.assertEqual(self.summary()['last_successful_reconcile_at'], ended_at)

    def test_the_milestone_only_moves_forward_on_an_exit_zero_reconcile(self):
        reports = []
        for run in ('first', 'later'):
            self.assertEqual(self.h.invoke('reconcile', run=run)[0], 0)
            reference = self.h.calls[-1]['stdout']['result_ref']
            reports.append((read_workflow_result(reference, self.h.store, self.h.objects), reference))
        first, later = reports
        record_reconcile_success(first[0], first[1], self.h.store, self.h.objects)
        self.assertEqual(last_successful_reconcile(self.h.store, self.h.objects), later[0].ended_at)
        self.assertEqual(self.h.invoke('daily', run='ignored-daily')[0], 0)
        reference = self.h.calls[-1]['stdout']['result_ref']
        daily = read_workflow_result(reference, self.h.store, self.h.objects)
        record_reconcile_success(daily, reference, self.h.store, self.h.objects)
        self.assertEqual(last_successful_reconcile(self.h.store, self.h.objects), later[0].ended_at)

    def test_a_failed_extra_is_reported_without_changing_the_outcome(self):
        with patch('sec_edgar_ingest.workflows.summary.withdrawal_candidates',
                   side_effect=RuntimeError('listing exploded')):
            code, message = self.h.invoke('backfill', run='base')
        self.assertEqual((code, message['outcome']), (0, 'success'))
        self.assertEqual(self.summary()['summary_error'], {'type': 'RuntimeError', 'message': 'listing exploded'})

    def test_a_replayed_result_logs_no_summary(self):
        self.assertEqual(self.h.invoke('backfill', run='base')[0], 0)
        self.assertEqual(self.h.invoke('backfill', run='base')[0], 0)
        self.assertEqual([event['event'] for event in self.events()][-1], 'result_replayed')
        self.assertNotIn('workflow_summary', [event['event'] for event in self.events()])

    def test_workflow_commands_write_no_approval_evidence(self):
        self.gate()
        with closing(sqlite3.connect(self.root / '.fixture-state' / 'state.sqlite3')) as database:
            rows = database.execute("SELECT COUNT(*) FROM records WHERE table_name='Approvals'").fetchone()[0]
        self.assertEqual(rows, 0)
        self.assertFalse((self.h.objects.directory / 'approvals').exists())

    def test_milestone_contract_and_referenced_result_refusals_do_not_mutate(self):
        from dataclasses import replace
        from test_local_workflow_contracts import durable_snapshot
        from sec_edgar_ingest.models import Error, canonical_json, parse_json
        from sec_edgar_ingest.workflows.contracts import summarize
        from sec_edgar_ingest.workflows.summary import emit_summary
        self.assertEqual(self.h.invoke('reconcile', run='milestone-authority')[0], 0)
        reference = self.h.calls[-1]['stdout']['result_ref']
        result = read_workflow_result(reference, self.h.store, self.h.objects)
        row = self.h.store.get(MILESTONE_KIND, RECONCILE_MILESTONE)
        original = row.to_mapping()['value']
        self.assertEqual(last_successful_reconcile(self.h.store, self.h.objects), result.ended_at)
        # Summary validation must not repair an engine index before refusing a corrupt milestone.
        from sec_edgar_ingest.storage.contracts import identity, table_for
        from sec_edgar_ingest.workflows.results import workflow_key
        key = workflow_key(result.context)
        partition, _ = identity('WorkflowAttempt', key)
        with closing(sqlite3.connect(self.h.store.database)) as database:
            database.execute('DELETE FROM records WHERE table_name=? AND partition=? AND key=?',
                             (table_for('WorkflowAttempt'), partition, key))
            database.commit()
        variants = [{k: v for k, v in original.items() if k != 'contract_version'},
                    {**original, 'contract_version': 'foreign'}, {**original, 'unknown': True},
                    {**original, 'workflow': 'daily'}, {**original, 'ended_at': result.context.started_at.isoformat()},
                    {**original, 'result_ref': '../outside'},
                    {**original, 'result_ref': 'runs/sec/missing/reconcile/a/result.json'},
                    {**original, 'result_ref': 123}]
        for changed in variants:
            current = self.h.store.get(MILESTONE_KIND, RECONCILE_MILESTONE)
            self.h.store.replace(MILESTONE_KIND, RECONCILE_MILESTONE, changed, current.version)
            with self.subTest(milestone=changed):
                before = durable_snapshot(self.h.store, self.h.objects)
                with self.assertRaises((ValueError, OSError)):
                    last_successful_reconcile(self.h.store, self.h.objects)
                with self.assertRaises((ValueError, OSError)):
                    record_reconcile_success(result, reference, self.h.store, self.h.objects)
                with patch('sec_edgar_ingest.workflows.summary.log_event') as logged:
                    emit_summary(result, reference, self.h.objects, self.h.store)
                self.assertIsNotNone(logged.call_args.args[2]['summary_error'])
                self.assertEqual(durable_snapshot(self.h.store, self.h.objects), before)
        current = self.h.store.get(MILESTONE_KIND, RECONCILE_MILESTONE)
        self.h.store.replace(MILESTONE_KIND, RECONCILE_MILESTONE, original, current.version)
        target = self.h.objects.directory / reference
        body = target.read_bytes()
        gap = Error('publication_pending', 'not complete', True, None, {})
        outcome, counts = summarize(result.members, (gap,), result.intent['discovered_sources'],
                                    result.intent['unresolved_before'], 'reconcile',
                                    tuple(result.intent['already_complete_sources']))
        failed = replace(result, gaps=(gap,), outcome=outcome, counts=counts)
        daily = replace(result, context=replace(result.context, command='daily'))
        payload = parse_json(body)
        variants = [canonical_json({k: v for k, v in payload.items() if k != 'contract_version'}),
                    canonical_json({**payload, 'contract_version': 'foreign'}),
                    canonical_json({**payload, 'format_version': 'sec-workflow-result-v1'}),
                    canonical_json({**payload, 'unknown': True}), body + b' ',
                    canonical_json(failed.to_mapping()), canonical_json(daily.to_mapping())]
        for altered in variants:
            target.write_bytes(altered)
            try:
                before = durable_snapshot(self.h.store, self.h.objects)
                with self.assertRaises(ValueError):
                    last_successful_reconcile(self.h.store, self.h.objects)
                with patch('sec_edgar_ingest.workflows.summary.log_event') as logged:
                    emit_summary(result, reference, self.h.objects, self.h.store)
                self.assertIsNotNone(logged.call_args.args[2]['summary_error'])
                self.assertEqual(durable_snapshot(self.h.store, self.h.objects), before)
            finally:
                target.write_bytes(body)
        with self.assertRaises((ValueError, OSError)):
            record_reconcile_success(result, 'runs/sec/elsewhere/reconcile/a/result.json', self.h.store, self.h.objects)

    def test_milestone_rows_route_to_source_state_locally(self):
        from sec_edgar_ingest.storage.contracts import table_for
        self.assertEqual(table_for(MILESTONE_KIND), 'SourceState')
        self.assertEqual(self.h.invoke('reconcile', run='local-milestone')[0], 0)
        self.assertIsNotNone(last_successful_reconcile(self.h.store, self.h.objects))


if __name__ == '__main__':
    unittest.main()
