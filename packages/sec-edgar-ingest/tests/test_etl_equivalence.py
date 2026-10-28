"""Stage 1b C6: an incremental candidate must equal the full rebuild on every key it can change."""
from network_guard import install
install()

import hashlib
import unittest
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq

from support_catalog import Lane, capture, row
from sec_edgar_ingest.etl import equivalence
from sec_edgar_ingest.etl.columnar import generation_table
from sec_edgar_ingest.etl.contracts import canonical_schema, change_schema
from sec_edgar_ingest.etl.equivalence import validate_incremental_candidate
from sec_edgar_ingest.etl.manifest import generation_base, generation_identity, source_fingerprint
from sec_edgar_ingest.models import canonical_json

CLOSED = date(2027, 1, 7)


def forge(lane, candidate, *, data=None, changes=None, **fields):
    """Rewrite a candidate's files and manifest, keeping every hash and the generation identity consistent.

    A forged source set or retained basis gives a new identity, so the forgery moves to that identity's address.
    """
    manifest = replace(candidate.manifest, **fields)
    fingerprint = source_fingerprint(manifest.quarter, manifest.sources, mode=manifest.quarter_mode,
                                     membership_source=manifest.membership_source,
                                     retained_from_generation=manifest.retained_from_generation)
    generation_id = generation_identity(manifest.quarter, manifest.base_generation_id, fingerprint)
    base = generation_base(manifest.quarter, generation_id)
    files = []
    for ref in manifest.files:
        name = base + '/' + ref.path.rsplit('/', 1)[1]
        path = lane.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = data if ref.role == 'data' else changes
        if rows is None:
            path.write_bytes(lane.objects.read(ref.path))
            files.append(replace(ref, path=name))
            continue
        pq.write_table(pa.Table.from_pylist(rows, schema=canonical_schema() if ref.role == 'data' else change_schema()), path)
        body = path.read_bytes()
        files.append(replace(ref, path=name, sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body),
                             row_count=len(rows)))
    manifest = replace(manifest, source_fingerprint=fingerprint, generation_id=generation_id, files=tuple(files))
    body = canonical_json(manifest.to_mapping())
    lane.path(base + '/manifest.json').write_bytes(body)
    return replace(candidate, manifest=manifest, manifest_ref=base + '/manifest.json',
                   manifest_sha256=hashlib.sha256(body).hexdigest(), manifest_bytes=len(body))


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

    def authority_flip(self):
        lane = self.lane()
        g0 = lane.build([lane.observation(rows=row())])
        g1 = lane.build([lane.observation('2026-10-02', 'daily', row(number=2))], g0)
        self.check(lane, g1, g0)
        g2 = lane.build([lane.observation('2026-10-03', 'daily', row(number=3))], g1)
        self.assertEqual(g2.manifest.unresolved_absence, 1)
        return lane, g1, g2

    def re_emitted_absence(self):
        lane = self.lane()
        g1 = lane.build([lane.observation('2026-10-01', 'daily', row() + row(number=2))])
        g2 = lane.build([lane.observation('2026-10-01', 'daily', row(), seconds=1)], g1)
        g3 = lane.build([lane.observation('2026-10-02', 'daily', row(number=3))], g2)
        return lane, g2, g3

    def test_accepts_the_full_rebuild_of_an_open_daily_addition(self):
        lane, base, candidate = self.open_addition()
        self.check(lane, candidate, base)

    def test_accepts_the_open_authority_flip(self):
        lane, g1, g2 = self.authority_flip()
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
        lane, g2, g3 = self.re_emitted_absence()
        kept = [value for value in lane.rows(g3, 'changes') if value['change_type'] != 'unresolved_absence']
        with self.assertRaisesRegex(ValueError, 'outside its recomputed keys'):
            self.check(lane, forge(lane, g3, changes=kept), g2)

    def test_accepts_an_untouched_re_emitted_absence(self):
        lane, g2, g3 = self.re_emitted_absence()
        self.assertEqual([(value['change_type'], value['archive_path'][-10:]) for value in lane.rows(g3, 'changes')],
                         [('unresolved_absence', '000002.txt'), ('added', '000003.txt')])
        self.check(lane, g3, g2)

    def test_refuses_a_duplicated_touched_row(self):
        lane, base, candidate = self.open_addition()
        rows = lane.rows(candidate)
        rows.insert(3, rows[2])
        with self.assertRaisesRegex(ValueError, 'generation keys are duplicate or unsorted'):
            self.check(lane, forge(lane, candidate, data=rows, row_count=4), base)

    def test_refuses_a_changed_touched_change_row(self):
        lane, base, candidate = self.open_addition()
        changes = lane.rows(candidate, 'changes')
        self.assertEqual([value['change_type'] for value in changes], ['updated', 'added'])
        changes[0] = {**changes[0], 'reason': 'Forged'}
        with self.assertRaisesRegex(ValueError, 'incremental change rows differ from the full resolution of their keys'):
            self.check(lane, forge(lane, candidate, changes=changes), base)

    def test_refuses_a_delta_source_that_differs_from_its_observation_manifest(self):
        lane, base, candidate = self.open_addition()
        base_ids = {ref.source.source_id for ref in base.manifest.sources}
        sources = tuple(ref if ref.source.source_id in base_ids else replace(ref, distinct_key_count=ref.distinct_key_count - 1)
                        for ref in candidate.manifest.sources)
        self.assertNotEqual(sources, candidate.manifest.sources)
        with self.assertRaisesRegex(ValueError, 'incremental source differs from its immutable observation manifest'):
            self.check(lane, forge(lane, candidate, sources=sources), base)

    def test_refuses_a_wrong_retained_basis(self):
        lane, g1, g2 = self.authority_flip()
        self.assertEqual(g2.manifest.retained_from_generation, g1.manifest.generation_id)
        with self.assertRaisesRegex(ValueError, 'incremental retained basis or gate differs'):
            self.check(lane, forge(lane, g2, retained_from_generation=None), g1)

    def test_refuses_a_forged_count(self):
        lane, base, candidate = self.open_addition()
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            self.check(lane, forge(lane, candidate, updated=candidate.manifest.updated + 1), base)

    def test_recomputes_every_base_key_that_the_authority_does_not_list_in_the_quarter(self):
        lane = self.lane()
        base = lane.build([lane.observation('2026-10-01', 'daily', row() + row(number=2) + row(number=4))])
        data = generation_table(next(ref for ref in base.manifest.files if ref.role == 'data'), lane.objects)
        chunked = pa.concat_tables([data.slice(0, 1), data.slice(1)])  # `is_in` must accept a chunked key column.
        daily = lane.observation('2026-10-02', 'daily', row(number=3))
        key = lambda number: ('0000123456', f'edgar/data/123456/0000123456-26-{number:06}.txt')
        cases = {
            'no authority row in the quarter': (row(number=1, day='2026-09-30') + row(number=2, day='2026-09-30'),
                                                {key(1), key(2), key(3), key(4)}),
            'key 2 listed only outside the quarter': (row(number=1) + row(number=4) + row(number=2, day='2026-09-30'),
                                                      {key(2), key(3)}),
        }
        for label, (rows, expected) in cases.items():
            with self.subTest(label):
                authority = lane.observation(rows=rows, seconds=len(expected))
                manifest = SimpleNamespace(quarter='2026Q4', quarter_mode='open', membership_source=authority)
                for table in (data, chunked):
                    self.assertEqual(equivalence._recomputed_keys(manifest, [daily], table, lane.objects), expected)

    def test_refuses_a_candidate_checked_against_another_base(self):
        lane, base, candidate = self.open_addition()
        other = lane.build([lane.observation('2026-10-05', 'daily', row(number=7))])
        with self.assertRaisesRegex(ValueError, 'eligible base'):
            self.check(lane, candidate, other)


if __name__ == '__main__':
    unittest.main()
