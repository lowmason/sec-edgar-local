"""Stage 1b §5 items 3–5: incremental generations are byte-identical to full rebuilds (C4–C6)."""
from network_guard import install
install()

import unittest
from datetime import date
from unittest.mock import patch

from support_catalog import Lane, row
from support_incremental import Twin
from sec_edgar_ingest.etl import incremental
from sec_edgar_ingest.etl.publication import publish_quarter
from sec_edgar_ingest.models import canonical_json, parse_json

OPEN = date(2026, 10, 7)
CLOSED = date(2027, 1, 7)


class TwinCase(unittest.TestCase):
    def twin(self, day=OPEN):
        twin = Twin(day)
        self.addCleanup(twin.close)
        return twin

    def step(self, twin, pairs, previous=None, *, incremental_expected=True, quarter='2026Q4'):
        pair, built = twin.build(pairs, previous, quarter)
        self.assertEqual(pair[0], pair[1])  # Same manifest, so the same file hashes and counts.
        self.assertEqual(built, int(incremental_expected))
        return pair

    @staticmethod
    def names(twin, pair):
        return {value['archive_path'][-10:]: value['company_name'] for value in twin.fast.rows(pair[0])}


class OracleTests(TwinCase):
    def test_open_daily_addition_updates_and_adds(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row() + row(number=2))], incremental_expected=False)
        g2 = self.step(t, [t.observation('2026-10-02', 'daily', row('Changed') + row(number=3))], g1)
        self.assertEqual((g2[0].manifest.updated, g2[0].manifest.added), (1, 1))

    def test_a_new_row_beats_the_winner_and_one_loses(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-02', 'daily', row('Mid') + row('Mid', number=2))],
                       incremental_expected=False)
        newer = t.observation('2026-10-03', 'daily', row('New'))
        older = t.observation('2026-10-01', 'daily', row('Old', number=2))
        g2 = self.step(t, [newer, older], g1)
        self.assertEqual(self.names(t, g2), {'000001.txt': 'New', '000002.txt': 'Mid'})

    def test_two_delta_rows_with_one_key(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row())], incremental_expected=False)
        first = t.observation('2026-10-03', 'daily', row('A', number=5))
        second = t.observation('2026-10-04', 'daily', row('B', number=5))
        g2 = self.step(t, [first, second], g1)
        self.assertEqual((g2[0].manifest.added, self.names(t, g2)['000005.txt']), (1, 'B'))

    def test_closed_quarter_with_authority_takes_back_dated_rows(self):
        t = self.twin(CLOSED)
        g1 = self.step(t, [t.observation(rows=row() + row(number=2))], incremental_expected=False)
        daily = t.observation('2027-01-02', 'daily', row('Daily', day='2026-10-03') + row(number=9, day='2026-11-01'))
        g2 = self.step(t, [daily], g1)
        manifest = g2[0].manifest
        self.assertEqual((manifest.row_count, manifest.added, manifest.updated, manifest.gate), (2, 0, 0, 'clear'))

    def test_touched_key_retained_without_membership(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row() + row(number=2))], incremental_expected=False)
        replacement = t.observation('2026-10-01', 'daily', row(), seconds=1)
        g2 = self.step(t, [replacement], g1, incremental_expected=False)  # §5 item 4: a replacement snapshot
        self.assertEqual(g2[0].manifest.unresolved_absence, 1)
        g3 = self.step(t, [t.observation('2026-10-02', 'daily', row('Back', number=2))], g2)
        self.assertEqual((g3[0].manifest.updated, g3[0].manifest.unresolved_absence), (1, 0))
        self.assertIsNone(g3[0].manifest.retained_from_generation)

    def test_open_quarter_authority_and_keys_it_does_not_list(self):
        t = self.twin()
        g0 = self.step(t, [t.observation(rows=row())], incremental_expected=False)
        g1 = self.step(t, [t.observation('2026-10-02', 'daily', row(number=2))], g0)
        self.assertEqual((g1[0].manifest.added, g1[0].manifest.unresolved_absence), (1, 0))
        # A1: key 2 is untouched here, but the base added it and the authority does not list it.
        g2 = self.step(t, [t.observation('2026-10-03', 'daily', row(number=3))], g1)
        self.assertEqual((g2[0].manifest.added, g2[0].manifest.unresolved_absence), (1, 1))
        self.assertEqual(g2[0].manifest.retained_from_generation, g1[0].manifest.generation_id)
        # Key 2 is touched and retained; key 3 is the next untouched flip.
        g3 = self.step(t, [t.observation('2026-10-04', 'daily', row('Again', number=2))], g2)
        self.assertEqual(g3[0].manifest.unresolved_absence, 2)

    def test_closed_daily_only_quarter(self):
        t = self.twin(CLOSED)
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row() + row(number=2))], incremental_expected=False)
        g2 = self.step(t, [t.observation('2026-10-02', 'daily', row('Changed'))], g1)
        self.assertEqual((g2[0].manifest.updated, g2[0].manifest.gate), (1, 'clear'))

    def test_more_than_one_batch_with_a_boundary_shift(self):
        t = self.twin(CLOSED)
        big = b''.join(row(number=number) for number in range(100, 9100))
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', big)], incremental_expected=False)
        self.assertEqual(g1[0].manifest.row_count, 9000)
        shift = b''.join(row(number=number) for number in range(1, 6)) + row('Changed', number=8290)
        g2 = self.step(t, [t.observation('2026-10-02', 'daily', shift)], g1)
        self.assertEqual((g2[0].manifest.row_count, g2[0].manifest.added, g2[0].manifest.updated), (9005, 5, 1))

    def test_rows_filed_in_another_quarter_are_ignored(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row())], incremental_expected=False)
        g2 = self.step(t, [t.observation('2026-10-02', 'daily', row(number=2) + row(number=3, day='2026-09-30'))], g1)
        self.assertEqual((g2[0].manifest.added, g2[0].manifest.row_count), (1, 2))


class FallbackTests(TwinCase):
    """§5 item 4: each ineligible input takes today's full path, with today's output."""

    def test_a_revert_to_an_earlier_snapshot(self):
        t = self.twin()
        first = t.observation('2026-10-01', 'daily', row('A'))
        g1 = self.step(t, [first], incremental_expected=False)
        g2 = self.step(t, [t.observation('2026-10-01', 'daily', row('B'), seconds=1)], g1, incremental_expected=False)
        self.step(t, [first], g2, incremental_expected=False)

    def test_an_incoming_quarterly_authority(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row())], incremental_expected=False)
        self.step(t, [t.observation(rows=row() + row(number=2))], g1, incremental_expected=False)

    def test_a_mode_change(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row())], incremental_expected=False)
        t.pin(CLOSED)
        self.step(t, [t.observation('2026-10-02', 'daily', row(number=2))], g1, incremental_expected=False)

    def test_a_gate_other_than_clear(self):
        t = self.twin()
        g1 = self.step(t, [t.observation(rows=row() + row(number=2))], incremental_expected=False)
        revised = t.observation(rows=row('Revised'), seconds=1)
        g2 = self.step(t, [revised], g1, incremental_expected=False)
        t.pin(CLOSED)
        g3 = self.step(t, [revised], g2, incremental_expected=False)
        self.assertEqual(g3[0].manifest.gate, 'awaiting_approval')
        daily = t.observation('2027-01-02', 'daily', row('Daily', day='2026-10-03'))
        self.step(t, [daily], g3, incremental_expected=False)


class PrePointerRefusalTests(unittest.TestCase):
    """§5 item 5: C6 refuses a wrong incremental row before the pointer commits."""

    def test_a_wrong_incremental_row_is_refused_before_the_pointer(self):
        lane = Lane(command='publish')
        self.addCleanup(lane.close)
        publish = lambda ref: publish_quarter('2026Q4', (ref,), lane.context, lane.settings, lane.objects, lane.state)
        publish(lane.observation('2026-10-01', 'daily', row()))
        pointer = lane.state.pointer('2026Q4')
        original = incremental._resolve_touched

        def wrong(*args, **kwargs):
            output, change = original(*args, **kwargs)
            if output is not None:
                output = canonical_json({**parse_json(output), 'company_name': 'Wrong'})
            return output, change

        with patch.object(incremental, '_resolve_touched', side_effect=wrong), \
                self.assertRaisesRegex(ValueError, 'incremental rows differ'):
            publish(lane.observation('2026-10-02', 'daily', row(number=2)))
        self.assertEqual(lane.state.pointer('2026Q4'), pointer)


if __name__ == '__main__':
    unittest.main()
