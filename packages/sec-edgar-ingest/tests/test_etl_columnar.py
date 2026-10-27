"""Stage 1b readers: hash-checked columnar reads give the rows that the full readers give (S1)."""
from network_guard import install
install()

import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pyarrow as pa

from support_catalog import Lane, row
from sec_edgar_ingest.etl import transform
from sec_edgar_ingest.etl.catalog import _database, _load_observations
from sec_edgar_ingest.etl.columnar import generation_table, key_mask, quarter_observations, table_keys
from sec_edgar_ingest.etl.manifest import iter_file_rows
from sec_edgar_ingest.etl.transform import read_observations
from sec_edgar_ingest.models import quarter_for
from sec_edgar_ingest.storage.contracts import Conflict


class ColumnarReaderTests(unittest.TestCase):
    def setUp(self):
        self.lane = Lane()
        self.addCleanup(self.lane.close)
        self.ref = self.lane.observation('2026-10-02', 'daily',
                                         row() + row(number=2) + row(number=3, day='2026-09-30'))
        old = self.lane.build([self.lane.observation('2026-10-01', 'daily', row('Old') + row(number=4))])
        self.candidate = self.lane.build([self.ref], old)

    def changed(self, name):
        path = self.lane.path(name)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b'\0')

    def test_generation_tables_equal_the_full_reader(self):
        for ref in self.candidate.manifest.files:
            with self.subTest(role=ref.role):
                self.assertEqual(generation_table(ref, self.lane.objects).to_pylist(),
                                 list(iter_file_rows(ref, self.lane.objects)))

    def test_generation_table_refuses_changed_counts_and_bytes(self):
        data = next(ref for ref in self.candidate.manifest.files if ref.role == 'data')
        with self.assertRaisesRegex(ValueError, 'generation file row count differs'):
            generation_table(replace(data, row_count=data.row_count + 1), self.lane.objects)
        self.changed(data.path)
        with self.assertRaisesRegex(Conflict, 'generation file hash or length differs'):
            generation_table(data, self.lane.objects)

    def test_quarter_observations_equal_the_full_reader_without_a_readback(self):
        with closing(read_observations(self.ref, self.lane.objects)) as rows:
            expected = [obs for obs in rows if quarter_for(obs.row.filing_date) == '2026Q4']
        self.assertEqual(len(expected), 2)
        keys = {(expected[1].row.cik, expected[1].row.archive_path)}
        with patch.object(transform, '_verify_parquet', side_effect=AssertionError('readback')):
            self.assertEqual(list(quarter_observations(self.ref, self.lane.objects, '2026Q4')), expected)
            self.assertEqual(list(quarter_observations(self.ref, self.lane.objects, '2026Q4', keys)), expected[1:])
            self.assertEqual(len(list(quarter_observations(self.ref, self.lane.objects, '2026Q3'))), 1)

    def test_quarter_observations_refuse_changed_bytes(self):
        self.changed(self.ref.rows_ref)
        with self.assertRaisesRegex(Conflict, 'observation bytes differ from manifest hash or length'):
            list(quarter_observations(self.ref, self.lane.objects, '2026Q4'))

    def test_key_masks_select_exact_pairs(self):
        table = pa.table({'cik': ['1', '1', '2'], 'archive_path': ['a', 'b', 'a']})
        self.assertEqual(key_mask(table, {('1', 'b'), ('2', 'a'), ('3', 'a')}).to_pylist(), [False, True, True])
        self.assertEqual(key_mask(table, set()).to_pylist(), [False, False, False])
        self.assertEqual(table_keys(table), {('1', 'a'), ('1', 'b'), ('2', 'a')})

    def test_the_reader_seam_resolves_the_same_proposed_rows(self):
        sources = self.candidate.manifest.sources

        def proposed(**kwargs):
            with TemporaryDirectory() as directory, closing(_database(Path(directory) / 'db.sqlite')) as db:
                _load_observations(db, sources, '2026Q4', None, self.lane.objects, self.lane.context, **kwargs)
                return db.execute('SELECT cik,path,payload FROM proposed ORDER BY cik,path').fetchall()

        everything = proposed()
        self.assertEqual(len(everything), 3)
        self.assertEqual(proposed(read=lambda ref, objects: quarter_observations(ref, objects, '2026Q4')), everything)
        first = {(everything[0][0], everything[0][1])}
        self.assertEqual(proposed(read=lambda ref, objects: quarter_observations(ref, objects, '2026Q4', first)),
                         everything[:1])


if __name__ == '__main__':
    unittest.main()
