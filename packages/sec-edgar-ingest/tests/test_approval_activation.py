"""Write-ahead activation records of approve's pointer moves."""
from network_guard import install
install()

import hashlib
import unittest
from dataclasses import replace

from support import Faults
from support_approval import GateFixture, operator_cli, row
from sec_edgar_ingest.etl.approval import _store_activation, activation_ref, approve
from sec_edgar_ingest.etl.contracts import ApprovalActivation
from sec_edgar_ingest.etl.manifest import approval_ref
from sec_edgar_ingest.etl.rollback import rollback
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage.contracts import table_for


class ActivationTests(GateFixture):
    def approve(self, candidate, quarterly_sha256, approver='Lowell Mason', **kwargs):
        return approve('2026Q4', candidate.manifest.generation_id, quarterly_sha256, approver,
                       self.objects, self.state, **kwargs)

    def activation_objects(self):
        return sorted(self.objects.directory.rglob('activation.json'))

    def moved_base(self):
        return self.observation(rows=row('Updated') + row(number=2), seconds=2)

    def test_a_first_approval_writes_the_decision_and_one_activation(self):
        base, revised, candidate = self.gated()
        before = self.state.pointer('2026Q4')
        result = self.approve(candidate, revised.snapshot.sha256)
        activation = result.activation
        generation = candidate.manifest.generation_id
        self.assertEqual(result.outcome, 'success')
        self.assertEqual((activation.quarter, activation.generation_id, activation.base_generation_id,
                          activation.from_pointer_version, activation.actor),
                         ('2026Q4', generation, base.generation_id, before.version, 'Lowell Mason'))
        approval_body = self.objects.read(approval_ref('2026Q4', generation))
        self.assertEqual((activation.approval_ref, activation.approval_sha256),
                         (approval_ref('2026Q4', generation), hashlib.sha256(approval_body).hexdigest()))
        self.assertEqual(activation.activation_id,
                         hashlib.sha256(canonical_json(['2026Q4', generation, before.version])).hexdigest())
        self.assertEqual(activation_ref(activation),
                         f'approvals/sec/filing_index/year=2026/quarter=4/generation={generation}'
                         f'/activation={activation.activation_id}/activation.json')
        self.assertEqual(self.objects.read(activation_ref(activation)), canonical_json(activation.to_mapping()))
        self.assertEqual(self.state.activations('2026Q4'), (activation,))

    def test_refused_and_unchanged_approvals_write_no_activation(self):
        _, revised, candidate = self.gated()
        self.assertEqual(self.approve(candidate, '0' * 64).outcome, 'approval_refused')
        self.assertEqual(self.activation_objects(), [])
        self.assertEqual(self.approve(candidate, revised.snapshot.sha256).outcome, 'success')
        again = self.approve(candidate, revised.snapshot.sha256, 'Someone Else')
        self.assertEqual((again.outcome, again.activation), ('unchanged', None))
        self.assertEqual(len(self.state.activations('2026Q4')), 1)

    def test_a_stale_candidate_writes_no_activation(self):
        _, revised, candidate = self.gated()
        self.assertEqual(self.publish(self.moved_base()).outcome, 'published')
        self.assertEqual(self.approve(candidate, revised.snapshot.sha256).outcome, 'approval_stale')
        self.assertEqual((self.activation_objects(), self.state.activations('2026Q4')), ([], ()))

    def test_a_lost_race_keeps_its_activation_as_evidence(self):
        _, revised, candidate = self.gated()
        moved = self.moved_base()
        faults = Faults()
        faults.at('approval.before_pointer', lambda: self.assertEqual(self.publish(moved).outcome, 'published'))
        result = self.approve(candidate, revised.snapshot.sha256, 'Racing Approver', observer=faults)
        self.assertEqual(result.outcome, 'approval_stale')
        attempt, = self.state.activations('2026Q4')
        self.assertEqual(attempt.actor, 'Racing Approver')
        self.assertNotEqual(self.capture().generation_id, attempt.generation_id)

    def test_the_first_record_of_an_attempted_move_wins_and_is_revalidated(self):
        _, revised, candidate = self.gated()
        first = self.approve(candidate, revised.snapshot.sha256).activation
        self.assertEqual(_store_activation(replace(first, actor='Retry Actor'), self.objects), first)
        with self.assertRaisesRegex(ValueError, 'exact pointer move'):
            _store_activation(replace(first, approval_sha256='f' * 64), self.objects)

    def test_reactivation_after_rollback_records_only_its_own_activation(self):
        base, revised, candidate = self.gated()
        self.assertEqual(self.approve(candidate, revised.snapshot.sha256, 'First Approver').outcome, 'success')
        self.assertEqual(rollback('2026Q4', candidate.manifest.generation_id, base.generation_id, 'Lowell Mason',
                                  'reconsider', self.objects, self.state).outcome, 'success')
        again = self.approve(candidate, revised.snapshot.sha256, 'Second Approver')
        self.assertEqual((again.outcome, again.approval.approver, again.activation.actor),
                         ('success', 'First Approver', 'Second Approver'))
        self.assertEqual([record.actor for record in self.state.activations('2026Q4')],
                         ['First Approver', 'Second Approver'])
        self.assertEqual(len(list(self.objects.directory.rglob('approval.json'))), 1)

    def test_approve_cli_prints_the_activation_reference(self):
        _, revised, candidate = self.gated()
        command = ('approve', '--config', str(self.write_config()), '--state-dir', str(self.root),
                   '--quarter', '2026Q4', '--generation', candidate.manifest.generation_id,
                   '--quarterly-sha256', revised.snapshot.sha256, '--approver', 'Lowell Mason')
        code, message, _ = operator_cli(*command)
        self.assertEqual((code, message['outcome']), (0, 'success'))
        self.assertEqual(message['activation_ref'],
                         activation_ref(ApprovalActivation.from_mapping(message['activation'])))
        code, message, _ = operator_cli(*command)
        self.assertEqual((code, message['outcome'], message['activation'], message['activation_ref']),
                         (0, 'unchanged', None, None))

    def test_activation_rows_route_to_the_approvals_table(self):
        from azure.core.credentials import AzureSasCredential
        from azure.data.tables import TableServiceClient
        from sec_edgar_ingest.storage.azure import AzureStateStore
        from test_azure_contracts import RETRY, TABLE_ENDPOINT, ScriptedTransport, table_response
        self.assertEqual(table_for('ApprovalActivation'), 'Approvals')
        transport = ScriptedTransport([table_response(201, etag='W/"activation"')])
        service = TableServiceClient(TABLE_ENDPOINT, credential=AzureSasCredential('sv=offline&sig=synthetic'),
                                     api_version='2020-12-06', transport=transport, **RETRY)
        self.addCleanup(service.close)
        tables = service.get_table_client
        store = AzureStateStore(tables('SourceState'), tables('Attempts'), active_client=tables('ActivePointers'),
                                approval_client=tables('Approvals'))
        self.assertEqual(store.insert('ApprovalActivation', 'c' * 64, {'actor': 'Lowell Mason'}).version,
                         'W/"activation"')
        self.assertIn('/Approvals', transport.requests[0].url)


if __name__ == '__main__':
    unittest.main()
