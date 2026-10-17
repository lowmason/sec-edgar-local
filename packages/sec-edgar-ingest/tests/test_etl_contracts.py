"""Strict ETL schema and processing-identity contracts."""
import unittest
from hashlib import sha256
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.etl.contracts import canonical_schema, change_schema, processing_key


class EtlContractTests(unittest.TestCase):
    def test_canonical_field_types_and_nullability(self):
        schema = canonical_schema()
        expected = [
            ('cik', 'string', False), ('company_name', 'string', False),
            ('form_type', 'string', False), ('archive_path', 'string', False),
            ('filing_date', 'date32[day]', False), ('accession_number', 'string', True),
            ('source_id', 'string', False), ('source_sha256', 'string', False),
            ('parser_version', 'string', False), ('schema_version', 'string', False),
        ]
        self.assertEqual([(f.name, str(f.type), f.nullable) for f in schema], expected)

    def test_change_schema_embeds_nullable_full_rows(self):
        schema = change_schema()
        self.assertEqual(schema.names, ['change_type', 'cik', 'archive_path', 'before', 'after', 'reason'])
        self.assertEqual([f.nullable for f in schema], [False, False, False, True, True, True])
        for name in ('before', 'after'):
            self.assertEqual(list(schema.field(name).type), list(canonical_schema()))

    def test_processing_identity_includes_both_versions(self):
        args = ['a' * 64, 'b' * 64, 'parser-v1', 'sec-index-v1']
        expected = sha256(canonical_json(args)).hexdigest()
        self.assertEqual(processing_key(*args), expected)
        self.assertNotEqual(processing_key(*args), processing_key(*args[:2], 'parser-v2', args[3]))
        self.assertNotEqual(processing_key(*args), processing_key(*args[:3], 'sec-index-v2'))

    def test_observation_schema_preserves_original_fields(self):
        import pyarrow as pa
        from sec_edgar_ingest.etl.contracts import observation_schema
        schema = observation_schema()
        self.assertEqual(list(schema)[:-2], list(canonical_schema()))
        self.assertEqual(schema.field('original_fields'), pa.field('original_fields', pa.list_(pa.field('item', pa.string(), nullable=False), 5), nullable=False))
        self.assertEqual(schema.field('line_number'), pa.field('line_number', pa.int64(), nullable=False))

    def test_row_mapping_and_strict_validation(self):
        from dataclasses import replace
        from datetime import date
        from sec_edgar_ingest.etl.contracts import IndexRow, Observation
        row = IndexRow('0000000123', 'Company', '10-K', 'edgar/data/123/legacy.txt', date(2026, 1, 2), None, 'a'*64, 'b'*64, 'parser-v1', 'sec-index-v1')
        self.assertEqual(row.to_mapping()['filing_date'], '2026-01-02')
        self.assertEqual(IndexRow.from_mapping(row.to_mapping()), row)
        for changes in ({'source_sha256': 'bad'}, {'archive_path': '../raw'}, {'cik': 123}, {'cik': '00123'}, {'company_name': ''}, {'schema_version': 'unsupported'}, {'filing_date': '2026-01-02'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(row, **changes)
        with self.assertRaises(ValueError):
            IndexRow.from_mapping({**row.to_mapping(), 'extra': 1})
        for original, line in [(('a',)*4, 1), (('a',)*6, 1), (('a',)*5, 0), (('a',)*5, True)]:
            with self.assertRaises(ValueError):
                Observation(row, original, line)

    def test_transformed_codec_is_canonical_and_strict(self):
        from dataclasses import replace
        from sec_edgar_ingest.etl.contracts import TransformedWorkset, encode_transformed, decode_transformed, transformed_ref
        from support import fixture_context
        context = fixture_context()
        workset = TransformedWorkset('0'*64, 'worksets/sec/snapshot/sha256='+'a'*64+'/workset.json', context, context, (), (), True)
        payload = {'format_version': 'sec-transformed-workset-v1', **workset.to_mapping()}
        payload.pop('workset_id')
        workset = replace(workset, workset_id=sha256(canonical_json(payload)).hexdigest())
        body = encode_transformed(workset)
        self.assertEqual(encode_transformed(decode_transformed(body)), body)
        self.assertEqual(transformed_ref(workset), 'worksets/sec/transformed/sha256='+workset.workset_id+'/workset.json')
        for malformed in (b' '+body, body.replace(b'"complete":true', b'"complete":true,"complete":true'), body.replace(b'"complete":true', b'"unknown":1,"complete":true'), body.replace(b'sec-transformed-workset-v1', b'sec-transformed-workset-v9')):
            with self.subTest(body=malformed[:70]), self.assertRaises(ValueError):
                decode_transformed(malformed)
        with self.assertRaises(ValueError):
            encode_transformed(replace(workset, workset_id='b'*64))

    def test_retained_stage2_worksets_and_registry_remain_byte_identical(self):
        import json
        from pathlib import Path
        from sec_edgar_ingest.config import Settings
        from sec_edgar_ingest.storage.contracts import deployment_binding
        from sec_edgar_ingest.worksets import decode_source_workset, decode_snapshot_workset, encode_workset
        root = Path(__file__).resolve().parents[3]
        bundle = root/'specs/evidence/sec-filing-index-ingestion/stage-2/verification/sec-edgar-stage-2-46bhxh8j'
        objects = bundle/'state/.fixture-state/objects'
        paths = sorted((objects/'worksets/sec').glob('*/sha256=*/workset.json'))
        self.assertEqual(len(paths), 4)
        for path in paths:
            body = path.read_bytes()
            decoder = decode_source_workset if '/source/' in str(path) else decode_snapshot_workset
            workset = decoder(body)
            self.assertEqual(encode_workset(workset), body)
            config = workset.context.to_mapping()['effective_config']
            settings = Settings.from_mapping(config)
            self.assertEqual(settings.to_mapping(), config)
            self.assertEqual(settings.config_sha256, workset.context.config_sha256)
        registries = list((objects/'locks').glob('**/binding.json'))
        self.assertEqual(len(registries), 1)
        body = registries[0].read_bytes()
        saved = json.loads(body)
        binding = deployment_binding(settings, root=Path(saved['storage']['local_root']))
        self.assertEqual(canonical_json(binding), body)


def observation_ref():
    from support import fixture_source, fixture_snapshot
    from sec_edgar_ingest.etl.contracts import ObservationRef, observation_base
    source = fixture_source()
    snapshot = fixture_snapshot(source, b'raw')
    base = observation_base(source.source_id, snapshot.sha256, 'parser-v1', 'sec-index-v1')
    return ObservationRef(source, snapshot, 'parser-v1', 'sec-index-v1', base+'/rows.parquet', base+'/manifest.json', 'c'*64, 10, 1, 1, {'2015Q1': 1})


def generation_manifest():
    from sec_edgar_ingest.etl.contracts import GenerationManifest, FileRef
    return GenerationManifest(quarter='2015Q1', generation_id='d'*64, base_generation_id=None, source_fingerprint='e'*64, parser_version='parser-v1', schema_version='sec-index-v1', image_digest='sha256:'+'f'*64, sources=(observation_ref(),), files=(FileRef('curated/sec/g/data.parquet', 'a'*64, 10, 1, 'data'),), row_count=1, added=1, updated=0, withdrawn=0, unresolved_absence=0, provenance_refreshed=0, quarter_mode='open', membership_source=None, retained_from_generation=None, gate='clear')


class EtlRecordTests(unittest.TestCase):
    def test_all_records_are_strict_immutable_and_round_trip(self):
        from dataclasses import FrozenInstanceError, replace
        from sec_edgar_ingest.etl.contracts import Candidate, GenerationCapture, PublicationResult, EtlResult
        from support import fixture_context
        ref = observation_ref()
        manifest = generation_manifest()
        context = fixture_context()
        result = PublicationResult('2015Q1', 'published', 'd'*64, 'curated/sec/g/manifest.json', None, 0)
        records = (ref, *manifest.files, manifest, Candidate(manifest, 'curated/sec/g/manifest.json', 'a'*64, 10, None), result, GenerationCapture('2015Q1', 'd'*64, 'curated/sec/g/manifest.json', 'a'*64, 10), EtlResult(context=context, outcome='success', input_ref='worksets/sec/input.json', transformed_workset_ref=None, transformed=1, published=1, unchanged=0, quarantined=0, awaiting_approval=0, failed=0, quarters=(result,), gaps=(), started_at=context.started_at, ended_at=context.started_at))
        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertEqual(type(record).from_mapping(record.to_mapping()), record)
                with self.assertRaises(ValueError):
                    type(record).from_mapping({**record.to_mapping(), 'unknown': True})
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, next(iter(record.to_mapping())), None)
        with self.assertRaises(TypeError):
            ref.quarter_counts['2015Q1'] = 2
        for record, changes in [(ref, {'rows_sha256':'bad'}), (ref, {'distinct_key_count':2}), (ref, {'rows_ref':'../bad'}), (ref, {'quarter_counts':{'bad':1}}), (manifest, {'format_version':'unknown'}), (manifest, {'row_count':-1}), (manifest, {'gate':'approved'}), (records[-1], {'format_version':'unknown'})]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(record, **changes)

    def test_quarter_counts_include_retained_identical_duplicates(self):
        from dataclasses import replace
        ref = replace(observation_ref(), source_row_count=2, distinct_key_count=1, quarter_counts={'2015Q1': 2})
        self.assertEqual(sum(ref.quarter_counts.values()), ref.source_row_count)
        with self.assertRaises(ValueError):
            replace(ref, quarter_counts={'2015Q1': 1})

    def test_closed_daily_only_manifest_has_no_withdrawal_authority(self):
        from dataclasses import replace
        manifest = replace(generation_manifest(), quarter_mode='closed', membership_source=None)
        self.assertEqual(manifest.quarter_mode, 'closed')
        for changes in ({'withdrawn': 1}, {'gate': 'awaiting_approval'}):
            with self.assertRaises(ValueError):
                replace(manifest, **changes)

    def test_rows_follow_parser_padded_cik_and_safe_legacy_path_contract(self):
        from datetime import date
        from dataclasses import replace
        from sec_edgar_ingest.etl.contracts import IndexRow
        row = IndexRow('0000000123', 'Company', '10-K', 'edgar/data/123/legacy.txt', date(2026, 1, 2), None, 'a'*64, 'b'*64, 'parser-v1', 'sec-index-v1')
        for path in ('legacy/nested/Annual.TXT', 'edgar/data/unknown/legacy.txt'):
            self.assertEqual(replace(row, archive_path=path).archive_path, path)
        self.assertEqual(replace(row, cik='0000000000', archive_path='legacy/zero.txt').cik, '0000000000')
        for cik, path in [('123', row.archive_path), ('0000000123', 'edgar/data/456/annual.txt')]:
            with self.assertRaises(ValueError):
                replace(row, cik=cik, archive_path=path)
