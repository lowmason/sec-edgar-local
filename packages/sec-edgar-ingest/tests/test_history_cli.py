"""`history` prints a quarter's lineage, rollback records and activation records, read-only."""
from network_guard import install
install()

import json
import unittest
from unittest.mock import patch

from support_approval import GateFixture, operator_cli, tree_snapshot
from sec_edgar_ingest.etl.approval import approve
from sec_edgar_ingest.etl.rollback import rollback
from sec_edgar_ingest.models import canonical_json, to_mapping_value
from sec_edgar_ingest.storage.contracts import Conflict

KEYS = {'outcome', 'quarter', 'lineage', 'rollbacks', 'activations', 'error'}


class HistoryCliTests(GateFixture):
    def history(self, quarter='2026Q4', state_dir=None):
        return operator_cli('history', '--config', str(self.write_config()),
                            '--state-dir', str(state_dir or self.root), '--quarter', quarter)

    def test_a_quarter_without_a_pointer_has_empty_history(self):
        self.gated()
        code, message, _ = self.history('2026Q3')
        self.assertEqual((code, message), (0, {'outcome': 'success', 'quarter': '2026Q3', 'lineage': [],
                                                'rollbacks': [], 'activations': [], 'error': None}))

    def test_history_lists_lineage_rollbacks_and_activations(self):
        base, revised, candidate = self.gated()
        approved = approve('2026Q4', candidate.manifest.generation_id, revised.snapshot.sha256, 'Lowell Mason',
                           self.objects, self.state)
        code, message, _ = self.history()
        self.assertEqual((code, set(message)), (0, KEYS))
        self.assertEqual([entry['generation_id'] for entry in message['lineage']],
                         [candidate.manifest.generation_id, base.generation_id])
        self.assertEqual(message['activations'],
                         [json.loads(canonical_json(to_mapping_value(approved.activation.to_mapping())))])
        self.assertEqual(rollback('2026Q4', candidate.manifest.generation_id, base.generation_id, 'Lowell Mason',
                                  'reconsider', self.objects, self.state).outcome, 'success')
        code, message, _ = self.history()
        self.assertEqual([entry['generation_id'] for entry in message['lineage']], [base.generation_id])
        record, = message['rollbacks']
        self.assertEqual((record['from_generation_id'], record['to_generation_id']),
                         (candidate.manifest.generation_id, base.generation_id))
        self.assertEqual(len(message['activations']), 1)

    def test_an_invalid_quarter_or_missing_store_is_a_configuration_error(self):
        self.gated()
        for result in (self.history('2026Q5'), self.history(state_dir=self.root / 'typo')):
            code, message, events = result
            self.assertEqual((code, message), (2, None))
            self.assertEqual(json.loads(events.splitlines()[-1])['outcome'], 'configuration')
        self.assertFalse((self.root / 'typo').exists())

    def test_a_failed_read_reports_state_conflict(self):
        self.gated()
        with patch('sec_edgar_ingest.cli.quarter_history', side_effect=Conflict('lineage drifted')):
            code, message, _ = self.history()
        self.assertEqual((code, message['outcome'], set(message), message['error']['code']),
                         (9, 'state_conflict', KEYS, 'state_conflict'))

    def test_history_and_candidates_leave_the_store_unchanged(self):
        self.gated()
        self.write_config()
        before = tree_snapshot(self.root)
        self.assertEqual(self.history()[0], 0)
        self.assertEqual(operator_cli('candidates', '--config', str(self.write_config()),
                                      '--state-dir', str(self.root))[0], 0)
        self.assertEqual(tree_snapshot(self.root), before)


if __name__ == '__main__':
    unittest.main()
