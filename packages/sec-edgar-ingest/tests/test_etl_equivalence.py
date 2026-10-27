"""Stage 1b C6: an incremental candidate must equal the full rebuild on every key it can change."""
from network_guard import install
install()

import hashlib
import unittest
from dataclasses import replace
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq

from support_catalog import Lane, capture, row
from sec_edgar_ingest.etl.contracts import canonical_schema, change_schema
from sec_edgar_ingest.etl.equivalence import validate_incremental_candidate
from sec_edgar_ingest.models import canonical_json

CLOSED = date(2027, 1, 7)


def forge(lane, candidate, *, data=None, changes=None, **fields):
    """Rewrite a candidate's files and manifest in place, keeping every hash consistent."""
    files = []
    for ref in candidate.manifest.files:
        rows = data if ref.role == 'data' else changes
        if rows is None:
            files.append(ref)
            continue
        path = lane.path(ref.path)
        pq.write_table(pa.Table.from_pylist(rows, schema=canonical_schema() if ref.role == 'data' else change_schema()), path)
        body = path.read_bytes()
        files.append(replace(ref, sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body), row_count=len(rows)))
    manifest = replace(candidate.manifest, files=tuple(files), **fields)
    body = canonical_json(manifest.to_mapping())
    lane.path(candidate.manifest_ref).write_bytes(body)
    return replace(candidate, manifest=manifest, manifest_sha256=hashlib.sha256(body).hexdigest(),
                   manifest_bytes=len(body))


class EquivalenceTests(unittest.TestCase):
    def lane(self, day=date(2026, 10, 7)):
        lane = Lane(day)
        self.addCleanup(lane.close)
        return lane

    def check(self, lane, candidate, base):
        validate_incremental_candidate(candidate, capture(base), lane.context, lane.objects)

    def open_addition(self):
        lane = self.lane()
        base = lane.build([lane.observation('2026-10-01', 'daily', row() + row(number=2))])
        candidate = lane.build([lane.observation('2026-10-02', 'daily', row('Changed') + row(number=3))], base)
        return lane, base, candidate

    def test_accepts_the_full_rebuild_of_an_open_daily_addition(self):
        lane, base, candidate = self.open_addition()
        self.check(lane, candidate, base)

    def test_accepts_the_open_authority_flip(self):
        lane = self.lane()
        g0 = lane.build([lane.observation(rows=row())])
        g1 = lane.build([lane.observation('2026-10-02', 'daily', row(number=2))], g0)
        g2 = lane.build([lane.observation('2026-10-03', 'daily', row(number=3))], g1)
        self.assertEqual(g2.manifest.unresolved_absence, 1)
        self.check(lane, g1, g0)
        self.check(lane, g2, g1)

    def test_accepts_a_closed_back_dated_addition(self):
        lane = self.lane(CLOSED)
        base = lane.build([lane.observation(rows=row() + row(number=2))])
        daily = lane.observation('2027-01-02', 'daily', row('Daily', day='2026-10-03') + row(number=9, day='2026-11-01'))
        self.check(lane, lane.build([daily], base), base)

    def test_accepts_a_touched_key_that_the_base_retained(self):
        lane = self.lane()
        g1 = lane.build([lane.observation('2026-10-01', 'daily', row() + row(number=2))])
        g2 = lane.build([lane.observation('2026-10-01', 'daily', row(), seconds=1)], g1)
        g3 = lane.build([lane.observation('2026-10-02', 'daily', row('Back', number=2))], g2)
        self.check(lane, g3, g2)

    def test_refuses_a_changed_untouched_row(self):
        lane, base, candidate = self.open_addition()
        rows = lane.rows(candidate)
        rows[1] = {**rows[1], 'company_name': 'Forged'}
        with self.assertRaisesRegex(ValueError, 'outside its recomputed keys'):
            self.check(lane, forge(lane, candidate, data=rows), base)

    def test_refuses_a_changed_touched_row(self):
        lane, base, candidate = self.open_addition()
        rows = lane.rows(candidate)
        rows[2] = {**rows[2], 'company_name': 'Forged'}
        with self.assertRaisesRegex(ValueError, 'rows differ from the full resolution'):
            self.check(lane, forge(lane, candidate, data=rows), base)

    def test_refuses_a_dropped_re_emitted_absence(self):
        lane = self.lane()
        g1 = lane.build([lane.observation('2026-10-01', 'daily', row() + row(number=2))])
        g2 = lane.build([lane.observation('2026-10-01', 'daily', row(), seconds=1)], g1)
        g3 = lane.build([lane.observation('2026-10-02', 'daily', row(number=3))], g2)
        kept = [value for value in lane.rows(g3, 'changes') if value['change_type'] != 'unresolved_absence']
        with self.assertRaisesRegex(ValueError, 'outside its recomputed keys'):
            self.check(lane, forge(lane, g3, changes=kept), g2)

    def test_refuses_a_forged_count(self):
        lane, base, candidate = self.open_addition()
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            self.check(lane, forge(lane, candidate, updated=candidate.manifest.updated + 1), base)

    def test_refuses_a_candidate_checked_against_another_base(self):
        lane, base, candidate = self.open_addition()
        other = lane.build([lane.observation('2026-10-05', 'daily', row(number=7))])
        with self.assertRaisesRegex(ValueError, 'eligible base'):
            self.check(lane, candidate, other)


if __name__ == '__main__':
    unittest.main()
