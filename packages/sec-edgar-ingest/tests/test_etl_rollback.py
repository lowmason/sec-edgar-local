"""Offline recorded pointer rollback within one quarter's exact lineage."""
from network_guard import install
install()

import json
import unittest

from support import Faults
from support_approval import GateFixture, operator_cli, row
from sec_edgar_ingest.etl.approval import approve
from sec_edgar_ingest.etl.contracts import QuarterRollback
from sec_edgar_ingest.etl.manifest import read_manifest
from sec_edgar_ingest.etl.rollback import rollback, rollback_ref
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage.contracts import Conflict, table_for

CLI_KEYS = {'outcome', 'quarter', 'from_generation_id', 'to_generation_id', 'rollback_ref', 'active', 'rollback',
            'error'}


class RollbackTests(GateFixture):
    def rollback_objects(self):
        """Every rollback.json anywhere in the object store."""
        return sorted(self.objects.directory.rglob('rollback.json'))

    def lineage_of_two(self):
        """Publish G1 {1, 2} then G2 {1 Renamed, 2} in the open 2026Q4."""
        first = self.observation(rows=row() + row(number=2))
        self.assertEqual(self.publish(first).outcome, 'published')
        older = self.capture()
        second = self.observation(rows=row('Renamed') + row(number=2), seconds=1)
        self.assertEqual(self.publish(second).outcome, 'published')
        return older, self.capture(), second

    def rollback(self, source, target, operator='Lowell Mason', reason='SEC correction withdrawn', **kwargs):
        return rollback('2026Q4', source, target, operator, reason, self.objects, self.state, **kwargs)

    def test_rollback_records_then_restores_an_earlier_lineage_generation(self):
        older, newer, _ = self.lineage_of_two()
        before = self.state.pointer('2026Q4')
        result = self.rollback(newer.generation_id, older.generation_id)
        self.assertEqual((result.outcome, result.active), ('success', older))
        self.assertEqual(self.capture(), older)
        self.assertEqual(self.rows(), [(1, 'Example'), (2, 'Example')])
        record = result.rollback
        self.assertEqual((record.quarter, record.from_generation_id, record.to_generation_id,
                          record.from_pointer_version, record.operator, record.reason, record.format_version),
                         ('2026Q4', newer.generation_id, older.generation_id, before.version, 'Lowell Mason',
                          'SEC correction withdrawn', 'sec-pointer-rollback-v1'))
        self.assertEqual((record.to_manifest_ref, record.to_manifest_sha256, record.to_manifest_bytes),
                         (older.manifest_ref, older.manifest_sha256, older.manifest_bytes))
        ref = rollback_ref(record)
        self.assertEqual(ref, 'approvals/sec/filing_index/year=2026/quarter=4/rollback='
                         + record.rollback_id + '/rollback.json')
        self.assertEqual(self.objects.read(ref), canonical_json(record.to_mapping()))
        self.assertEqual(self.rollback_objects(), [self.object_path(ref)])
        self.assertEqual(QuarterRollback.from_mapping(record.to_mapping()), record)
        self.assertEqual(self.state.rollbacks('2026Q4'), (record,))
        self.assertEqual(table_for('QuarterRollback'), 'Approvals')
        pointer = self.state.pointer('2026Q4')
        again = self.rollback(newer.generation_id, older.generation_id, reason='repeated')
        self.assertEqual((again.outcome, again.active, again.rollback), ('unchanged', older, None))
        self.assertEqual(self.state.pointer('2026Q4'), pointer)
        self.assertEqual(self.state.rollbacks('2026Q4'), (record,))

    def test_rollback_is_not_a_pin_and_never_rolls_forward(self):
        older, newer, second = self.lineage_of_two()
        self.assertEqual(self.rollback(newer.generation_id, older.generation_id).outcome, 'success')
        forward = self.rollback(older.generation_id, newer.generation_id)
        self.assertEqual((forward.outcome, forward.error.code), ('rollback_refused', 'rollback_refused'))
        self.assertEqual(self.capture(), older)
        # Receipt-ordered selection rebuilds the same deterministic generation from the restored base.
        self.assertEqual(self.publish(second).outcome, 'published')
        self.assertEqual(self.capture(), newer)

    def test_refusals_and_stale_requests_write_nothing(self):
        older, newer, _ = self.lineage_of_two()
        pointer = self.state.pointer('2026Q4')
        cases = {
            'same generation': ('2026Q4', newer.generation_id, newer.generation_id, 'Lowell Mason', 'x'),
            'unknown target': ('2026Q4', newer.generation_id, 'f' * 64, 'Lowell Mason', 'x'),
            'invalid hash text': ('2026Q4', newer.generation_id, 'not-a-hash', 'Lowell Mason', 'x'),
            'invalid quarter': ('2026Q5', newer.generation_id, older.generation_id, 'Lowell Mason', 'x'),
            'invalid operator': ('2026Q4', newer.generation_id, older.generation_id, 'two\nlines', 'x'),
            'long reason': ('2026Q4', newer.generation_id, older.generation_id, 'Lowell Mason', 'r' * 1025),
            'no pointer': ('2026Q3', newer.generation_id, older.generation_id, 'Lowell Mason', 'x'),
        }
        for label, args in cases.items():
            with self.subTest(label):
                result = rollback(*args, self.objects, self.state)
                self.assertEqual((result.outcome, result.error.code), ('rollback_refused', 'rollback_refused'))
                self.assertIsNone(result.rollback)
                self.assertEqual(self.rollback_objects(), [])
        stale = rollback('2026Q4', 'e' * 64, older.generation_id, 'Lowell Mason', 'x', self.objects, self.state)
        self.assertEqual((stale.outcome, stale.error.details['active_generation_id']),
                         ('rollback_stale', newer.generation_id))
        self.assertEqual(self.state.pointer('2026Q4'), pointer)
        self.assertEqual((self.state.rollbacks('2026Q4'), self.rollback_objects()), ((), []))

    def test_a_lineage_target_that_fails_validation_writes_nothing(self):
        older, newer, _ = self.lineage_of_two()
        pointer = self.state.pointer('2026Q4')
        data = next(ref for ref in read_manifest(older, self.objects).files if ref.role == 'data')
        path = self.object_path(data.path)
        path.write_bytes(path.read_bytes() + b'\0')
        with self.assertRaisesRegex(Conflict, 'generation file hash or length differs'):
            self.rollback(newer.generation_id, older.generation_id)
        # Validating the active generation would now re-read the corrupt base, so compare the raw pointer row.
        self.assertEqual(self.state.pointer('2026Q4'), pointer)
        self.assertEqual((self.state.rollbacks('2026Q4'), self.rollback_objects()), ((), []))

    def test_an_approved_gated_generation_is_a_valid_target(self):
        _, revised, candidate = self.gated()
        approved = approve('2026Q4', candidate.manifest.generation_id, revised.snapshot.sha256, 'Lowell Mason',
                           self.objects, self.state)
        self.assertEqual(approved.outcome, 'success')
        returned = self.observation(rows=row() + row('Returned', number=2), seconds=2)
        self.assertEqual(self.publish(returned).outcome, 'published')
        latest = self.capture()
        result = self.rollback(latest.generation_id, candidate.manifest.generation_id)
        self.assertEqual((result.outcome, self.capture().generation_id),
                         ('success', candidate.manifest.generation_id))
        self.assertEqual(self.rows(), [(1, 'Example')])
        # Rollbacks and approvals share the Approvals table; each lookup sees only its own kind.
        self.assertEqual(self.state.rollbacks('2026Q4'), (result.rollback,))
        self.assertEqual(self.state.approval(candidate.manifest.generation_id), approved.approval)

    def test_a_lost_pointer_race_to_the_same_target_rereads_to_unchanged(self):
        older, newer, _ = self.lineage_of_two()
        raced, faults = [], Faults()
        faults.at('rollback.before_pointer', lambda: raced.append(
            self.rollback(newer.generation_id, older.generation_id, operator='Racing Operator')))
        result = self.rollback(newer.generation_id, older.generation_id, observer=faults)
        self.assertEqual((result.outcome, result.active, result.rollback, result.error),
                         ('unchanged', older, None, None))
        winner, = raced
        self.assertEqual((winner.outcome, winner.active), ('success', older))
        self.assertEqual(self.capture(), older)
        # Both attempts move the same pointer version, so they share one record and the first stored one wins.
        self.assertEqual(winner.rollback.operator, 'Lowell Mason')
        self.assertEqual(self.state.rollbacks('2026Q4'), (winner.rollback,))
        self.assertEqual(self.rollback_objects(), [self.object_path(rollback_ref(winner.rollback))])

    def test_a_lost_pointer_race_is_stale_and_keeps_its_attempt_record(self):
        older, newer, _ = self.lineage_of_two()
        third = self.observation(rows=row('Third') + row(number=2), seconds=2)
        faults = Faults()
        faults.at('rollback.before_pointer', lambda: self.assertEqual(self.publish(third).outcome, 'published'))
        result = self.rollback(newer.generation_id, older.generation_id, observer=faults)
        self.assertEqual((result.outcome, result.error.details['from_generation_id']),
                         ('rollback_stale', newer.generation_id))
        self.assertNotIn(self.capture().generation_id, (older.generation_id, newer.generation_id))
        attempt, = self.state.rollbacks('2026Q4')
        self.assertEqual((attempt.from_generation_id, attempt.to_generation_id),
                         (newer.generation_id, older.generation_id))
        self.assertEqual(self.rollback_objects(), [self.object_path(rollback_ref(attempt))])

    def test_rollback_cli_maps_named_outcomes_to_exit_codes(self):
        older, newer, _ = self.lineage_of_two()
        command = ('rollback', '--config', str(self.write_config()), '--state-dir', str(self.root),
                   '--quarter', '2026Q4', '--operator', 'Lowell Mason', '--reason', 'bad correction')
        code, message, _ = operator_cli(*command, '--from-generation', 'e' * 64,
                                        '--to-generation', older.generation_id)
        self.assertEqual((code, message['outcome'], message['rollback_ref']), (11, 'rollback_stale', None))
        self.assertEqual(set(message), CLI_KEYS)
        code, message, events = operator_cli(*command, '--from-generation', newer.generation_id,
                                             '--to-generation', older.generation_id)
        self.assertEqual((code, message['outcome'], message['active']['generation_id']),
                         (0, 'success', older.generation_id))
        self.assertEqual(set(message), CLI_KEYS)
        self.assertEqual(message['rollback_ref'], rollback_ref(QuarterRollback.from_mapping(message['rollback'])))
        self.assertEqual(json.loads(events.splitlines()[-1])['event'], 'quarter_rollback')
        code, message, _ = operator_cli(*command, '--from-generation', newer.generation_id,
                                        '--to-generation', older.generation_id)
        self.assertEqual((code, message['outcome'], set(message)), (0, 'unchanged', CLI_KEYS))
        code, message, _ = operator_cli(*command, '--from-generation', older.generation_id,
                                        '--to-generation', newer.generation_id)
        self.assertEqual((code, message['outcome'], set(message)), (2, 'rollback_refused', CLI_KEYS))
        self.assertEqual((message['quarter'], message['from_generation_id'], message['to_generation_id']),
                         ('2026Q4', older.generation_id, newer.generation_id))
        missing = ('rollback', '--config', str(self.root / 'missing.json'), '--quarter', '2026Q4',
                   '--from-generation', newer.generation_id, '--to-generation', older.generation_id,
                   '--operator', 'Lowell Mason', '--reason', 'bad correction')
        # Exit 2 is shared with rollback_refused; only the empty stdout marks a configuration error.
        code, message, events = operator_cli(*missing)
        self.assertEqual((code, message), (2, None))
        self.assertEqual(json.loads(events.splitlines()[-1])['outcome'], 'configuration')


if __name__ == '__main__':
    unittest.main()
