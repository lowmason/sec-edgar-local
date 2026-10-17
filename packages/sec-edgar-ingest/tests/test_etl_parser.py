import unittest
from sec_edgar_ingest.etl.parser import parse_fields
from support import fixture_source, fixture_snapshot

class EtlParserTests(unittest.TestCase):
    def test_daily_date_chooses_older_output_quarter(self):
        source = fixture_source(kind='daily', period='2026-09-30')
        snapshot = fixture_snapshot(source, b'fixture-only')
        fields = ('123456', 'Example Corp', '10-K/A', '20250825',
                  'edgar/data/123456/0000123456-25-000001.txt')
        obs = parse_fields(fields, source, snapshot, line_number=12,
                           parser_version='fixture-index-parser-v1',
                           schema_version='sec-index-v1')
        self.assertEqual(obs.row.cik, '0000123456')
        self.assertEqual(obs.row.filing_date.isoformat(), '2025-08-25')
        self.assertEqual(obs.row.accession_number, '0000123456-25-000001')
        self.assertEqual(obs.row.form_type, '10-K/A')
        self.assertEqual(obs.original_fields, fields)


import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from sec_edgar_ingest.etl.parser import ParseError, iter_observations, supported_parser

FIXTURES = Path(__file__).parent / 'fixtures/etl'
VERSIONS = dict(parser_version='fixture-index-parser-v1', schema_version='sec-index-v1')


def archive_bytes(body):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        member = zipfile.ZipInfo('master.idx', (2000, 1, 1, 0, 0, 0))
        member.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(member, body)
    return stream.getvalue()


class StrictParserTests(unittest.TestCase):
    def parse(self, fields, kind='daily'):
        source = fixture_source('2026-09-30', kind) if kind == 'daily' else fixture_source()
        return parse_fields(fields, source, fixture_snapshot(source, b'fixture'), line_number=19, **VERSIONS)

    def observations(self, body, kind='daily'):
        source = fixture_source('2026-09-30', kind) if kind == 'daily' else fixture_source()
        original = archive_bytes(body) if kind == 'quarterly' else body
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source'
            path.write_bytes(original)
            try:
                return list(iter_observations(path, source, fixture_snapshot(source, original), **VERSIONS))
            finally:
                self.assertEqual(path.read_bytes(), original)

    def test_independent_goldens_and_manifest(self):
        expected = json.loads((FIXTURES / 'expected.json').read_text())
        for name, rows in expected.items():
            with self.subTest(name=name):
                body = (FIXTURES / name).read_bytes()
                observations = self.observations(body, 'quarterly' if name == 'quarterly.idx' else 'daily')
                actual = []
                for obs in observations:
                    row = obs.row
                    actual.append(dict(cik=row.cik, company_name=row.company_name, form_type=row.form_type,
                                       filing_date=row.filing_date.isoformat(), archive_path=row.archive_path,
                                       accession_number=row.accession_number, line_number=obs.line_number,
                                       original_fields=list(obs.original_fields)))
                    self.assertEqual(row.parser_version, VERSIONS['parser_version'])
                    self.assertEqual(row.schema_version, 'sec-index-v1')
                self.assertEqual(actual, rows)
        for record in json.loads((FIXTURES / 'fixture-manifest.json').read_text())['records']:
            body = (FIXTURES / record['path']).read_bytes()
            self.assertEqual(len(body), record['bytes'])
            self.assertEqual(hashlib.sha256(body).hexdigest(), record['sha256'])
        self.assertEqual(archive_bytes(b'abc'), archive_bytes(b'abc'))

    def test_field_refusal_matrix(self):
        good = ('123456', 'Example', '10-K/A', '20240229', 'edgar/data/123456/legacy.txt')
        cases = []
        for cik in ('', '-1', '1.0', '１２', '12345678901'):
            cases.append((0, cik, 'invalid CIK'))
        for index in (1, 2):
            cases.append((index, '  ', 'empty company/form'))
        for spelling in ('2024-02-29', '2024022', '20240230', '20230229', '20241301', '20240001'):
            cases.append((3, spelling, 'date'))
        for path in ('/a', '../a', 'a/../b', 'a//b', 'a\\b', 'a%20b', 'a?b', 'a#b', 'a:b', 'a\x00b', 'a\tb', 'edgar/data/2/legacy.txt'):
            cases.append((4, path, 'path'))
        for index, value, reason in cases:
            fields = list(good); fields[index] = value
            with self.subTest(fields=fields), self.assertRaises(ParseError) as raised:
                self.parse(tuple(fields))
            self.assertEqual(raised.exception.line_number, 19)
            self.assertIn(reason, raised.exception.reason)
        for fields in (good[:4], good + ('extra',), good[:4] + (None,)):
            with self.subTest(fields=fields), self.assertRaises(ParseError):
                self.parse(fields)

    def test_cik_dates_paths_and_originals(self):
        for cik in ('0', '0000000000', '1234567890'):
            fields = (cik, ' Company ', '10-K/A', '20000229', 'safe/Nested/Legacy.TXT')
            obs = self.parse(fields)
            self.assertEqual(obs.row.cik, cik.zfill(10))
            self.assertEqual(obs.original_fields, fields)
            self.assertEqual(obs.row.archive_path, fields[4])
            self.assertIsNone(obs.row.accession_number)
        for text in ('2024-02-30', '2023-02-29', '20240229'):
            with self.assertRaises(ParseError):
                self.parse(('1', 'Company', '10-K', text, 'safe/path'), 'quarterly')

    def test_stream_refusal_matrix(self):
        header = b'CIK|Company Name|Form Type|Date Filed|File Name'
        row = b'123456|Example|10-K|20240229|safe/path'
        cases = [(b'malformed\n'+header+b'\n--------\n'+row, 1, 'preamble'), (b'', 1, 'header'), (header, 2, 'separator'),
                 (header+b'\n--------', 3, 'rows'),
                 (header+b'\nwrong\n'+row, 2, 'separator'),
                 (header.replace(b'File Name', b'Filename')+b'\n--------\n'+row, 1, 'header'),
                 (header+b'\r\n--------\r\n'+row, 1, 'line endings'),
                 (header+b'\n--------\n'+row+b'\n\xff', 4, 'ASCII'),
                 (header+b'\n--------\n'+row+b'\n\x00', 4, 'control'),
                 (header+b'\n--------\n'+row+b'\n', None, None),
                 (header+b'\n--------\n'+row+b'\n\n', 4, 'blank'),
                 (header+b'\n--------\n'+row+b'\n'+header, 4, 'header'),
                 (header+b'\n--------\n'+row+b'\n--------', 4, 'fields'),
                 (header+b'\n--------\n'+row+b'\nmalformed', 4, 'fields'),
                 (row+b'\n'+header+b'\n--------\n'+row, 1, 'preamble')]
        for body, line, reason in cases:
            with self.subTest(body=body):
                if line is None:
                    self.assertEqual(len(self.observations(body)), 1)
                else:
                    with self.assertRaises(ParseError) as raised:
                        self.observations(body)
                    self.assertEqual(raised.exception.line_number, line)
                    self.assertIn(reason, raised.exception.reason)

    def test_final_newline_families_and_duplicates(self):
        for kind in ('daily', 'quarterly'):
            body = (FIXTURES / (kind+'.idx')).read_bytes()
            for final in (body, body.rstrip(b'\r\n')):
                self.assertTrue(self.observations(final, kind))
            newline = b'\r\n' if kind == 'quarterly' else b'\n'
            last = body.rstrip(b'\r\n').split(newline)[-1]
            observations = self.observations(body+last+newline, kind)
            self.assertEqual(observations[-1].row, observations[-2].row)
            self.assertNotEqual(observations[-1].line_number, observations[-2].line_number)
        quarterly = (FIXTURES / 'quarterly.idx').read_bytes()
        with self.assertRaises(ParseError):
            self.observations(quarterly.replace(b'\r\n', b'\n'), 'quarterly')
        with self.assertRaises(ParseError):
            self.observations(quarterly.replace(b'Filename', b'File Name'), 'quarterly')

    def test_version_registration_and_preopen_refusal(self):
        supported_parser('sec-index-parser-v1', fixture=False)
        for version in ('fixture-index-parser-v1', 'fixture-index-parser-v2'):
            supported_parser(version, fixture=True)
            with self.assertRaises(ValueError):
                supported_parser(version, fixture=False)
        for version in ('fixture-envelope-v1', 'anything'):
            with self.assertRaises(ValueError):
                supported_parser(version, fixture=True)
        source = fixture_source('2026-09-30', 'daily')
        snapshot = fixture_snapshot(source, b'fixture')
        for versions in (dict(parser_version='anything', schema_version='sec-index-v1'),
                         dict(parser_version='sec-index-parser-v1', schema_version='anything')):
            with patch.object(Path, 'open', side_effect=AssertionError('opened')):
                with self.assertRaises(ValueError):
                    list(iter_observations(Path('/does-not-exist'), source, snapshot, **versions))
