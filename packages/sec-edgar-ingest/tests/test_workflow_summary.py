"""One `workflow_summary` per fresh workflow result; it never changes the result, stdout or exit code."""
from network_guard import install
install()

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from support_approval import operator_cli
from support_reconcile import sha
from support_scenario import BASE_Q3, GATED_Q3, scenario_pack, scenario_settings
from support_workflows import CommandHarness
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
        listing = operator_cli('candidates', '--config', str(self.h.config), '--state-dir', str(self.root))[1]
        request, = listing['candidates']
        approved = operator_cli('approve', '--config', str(self.h.config), '--state-dir', str(self.root),
                                '--quarter', '2026Q3', '--generation', request['generation_id'],
                                '--quarterly-sha256', sha(GATED_Q3), '--approver', 'Lowell Mason')
        self.assertEqual(approved[0], 0)
        self.assertEqual(self.h.invoke('reconcile', run='after')[0], 0)
        reference = self.h.calls[-1]['stdout']['result_ref']
        ended_at = json.loads(self.h.objects.read(reference))['ended_at']
        self.assertEqual(self.summary()['last_successful_reconcile_at'], ended_at)
        self.assertEqual(dict(self.h.store.get(MILESTONE_KIND, RECONCILE_MILESTONE).value),
                         {'workflow': 'reconcile', 'ended_at': ended_at, 'result_ref': reference})
        self.assertEqual(self.h.invoke('daily', run='day2')[0], 0)
        self.assertEqual(self.summary()['last_successful_reconcile_at'], ended_at)

    def test_the_milestone_only_moves_forward_on_an_exit_zero_reconcile(self):
        now = datetime.now(timezone.utc)

        def result(command, outcome, at):
            return SimpleNamespace(context=SimpleNamespace(command=command), outcome=outcome, ended_at=at.isoformat())
        record_reconcile_success(result('reconcile', 'unchanged', now), 'runs/sec/a/reconcile/a/result.json',
                                 self.h.store)
        for ignored in (result('reconcile', 'unchanged', now - timedelta(days=1)),
                        result('reconcile', 'awaiting_approval', now + timedelta(days=1)),
                        result('daily', 'success', now + timedelta(days=1))):
            record_reconcile_success(ignored, 'runs/sec/b/reconcile/a/result.json', self.h.store)
        self.assertEqual(last_successful_reconcile(self.h.store), now.isoformat())
        later = now + timedelta(days=2)
        record_reconcile_success(result('reconcile', 'success', later), 'runs/sec/c/reconcile/a/result.json',
                                 self.h.store)
        self.assertEqual(last_successful_reconcile(self.h.store), later.isoformat())

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

    def test_milestone_rows_route_to_source_state_on_azure(self):
        from azure.core.credentials import AzureSasCredential
        from azure.data.tables import TableServiceClient
        from sec_edgar_ingest.storage.azure import AzureStateStore
        from sec_edgar_ingest.storage.contracts import table_for
        from test_azure_contracts import RETRY, TABLE_ENDPOINT, ScriptedTransport, table_response
        self.assertEqual(table_for(MILESTONE_KIND), 'SourceState')
        transport = ScriptedTransport([table_response(201, etag='W/"milestone"')])
        service = TableServiceClient(TABLE_ENDPOINT, credential=AzureSasCredential('sv=offline&sig=synthetic'),
                                     api_version='2020-12-06', transport=transport, **RETRY)
        self.addCleanup(service.close)
        tables = service.get_table_client
        store = AzureStateStore(tables('SourceState'), tables('Attempts'), active_client=tables('ActivePointers'),
                                approval_client=tables('Approvals'))
        inserted = store.insert(MILESTONE_KIND, RECONCILE_MILESTONE, {'workflow': 'reconcile'})
        self.assertEqual(inserted.version, 'W/"milestone"')
        self.assertIn('/SourceState', transport.requests[0].url)


if __name__ == '__main__':
    unittest.main()
