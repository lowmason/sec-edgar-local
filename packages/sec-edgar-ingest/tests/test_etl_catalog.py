"""Offline canonical generation resolution through real immutable stores."""
import io
import tempfile
import unittest
import zipfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from support import fixture_source, fixture_snapshot, fixture_settings, store_bundle
from support_etl import etl_context
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.etl.catalog import build_candidate, select_sources, source_fingerprint
from sec_edgar_ingest.etl.contracts import GenerationCapture, ObservationRef, observation_base
from sec_edgar_ingest.etl.manifest import read_manifest, validate_candidate, iter_file_rows
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.transform import transform_member
from sec_edgar_ingest.storage.contracts import Conflict

HEADER = b'CIK|Company Name|Form Type|Date Filed|File Name\n-----\n'


def row(name='Example', number=1, day='2026-10-01', form='10-K'):
    return f'123456|{name}|{form}|{day}|edgar/data/123456/0000123456-26-{number:06}.txt\n'.encode()


class EtlCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store, self.objects, leases = store_bundle(self.root)
        leases.close()
        self.addCleanup(self.store.close)
        self.state = EtlState(self.store)
        self.settings, self.context = etl_context()
        self.pin(date(2026, 10, 7))

    def pin(self, day):
        self.settings = fixture_settings(etl={"parser_version": self.context.parser_version}, fixture={"allow_clock_override": True})
        context = replace(self.context, config_sha256=self.settings.config_sha256, pinned_on=None, effective_config={})
        self.context = pin_context(self.settings, context, day)[0]

    def observation(self, period='2026Q4', kind='quarterly', rows=None, seconds=0):
        source = fixture_source(period, kind)
        body = HEADER + (row() if rows is None else rows)
        if kind == 'quarterly':
            target = io.BytesIO()
            with zipfile.ZipFile(target, 'w') as archive:
                info = zipfile.ZipInfo('master.idx', (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, body.replace(b'File Name', b'Filename').replace(b'\n', b'\r\n'))
            body = target.getvalue()
        else:
            import re
            body = re.sub(rb'\|(\d{4})-(\d{2})-(\d{2})\|', rb'|\1\2\3|', body)
        snapshot = fixture_snapshot(source, body)
        snapshot = replace(snapshot, received_at=snapshot.received_at + timedelta(seconds=seconds))
        self.objects.put_once(snapshot.raw_path, body)
        return transform_member(source, snapshot, self.context, self.settings, self.objects, self.state)

    def build(self, refs, previous=None, quarter='2026Q4', **kwargs):
        result = build_candidate(quarter, self.capture(previous) if previous else None, tuple(refs),
                                 self.context, self.settings, self.objects, self.state, **kwargs)
        validate_candidate(result, self.objects)
        self.assertIsNone(self.state.pointer(quarter))
        return result

    @staticmethod
    def capture(candidate):
        return GenerationCapture(candidate.manifest.quarter, candidate.manifest.generation_id,
                                 candidate.manifest_ref, candidate.manifest_sha256, candidate.manifest_bytes)

    def rows(self, candidate, role='data'):
        return [value for ref in candidate.manifest.files if ref.role == role
                for value in iter_file_rows(ref, self.objects)]

    def test_stale_snapshot_cannot_replace_newer_source_revision(self):
        source = fixture_source()
        old = fixture_snapshot(source, b'old')
        new = replace(fixture_snapshot(source, b'new'), received_at=old.received_at + timedelta(seconds=1))
        def ref(snapshot):
            base = observation_base(source.source_id, snapshot.sha256, 'fixture-index-parser-v1', 'sec-index-v1')
            return ObservationRef(source, snapshot, 'fixture-index-parser-v1', 'sec-index-v1',
                                  base + '/rows.parquet', base + '/manifest.json', 'a'*64, 12, 1, 1, {'2015Q1': 1})
        self.assertEqual(select_sources((ref(new),), (ref(old),)), (ref(new),))

    def test_quarterly_fields_beat_latest_daily_and_order_is_deterministic(self):
        quarterly = self.observation(rows=row('Quarterly'))
        daily = self.observation('2026-10-02', 'daily', row('Daily'))
        first = self.build([quarterly, daily])
        second = self.build([daily, quarterly])
        self.assertEqual(first, second)
        self.assertEqual(self.rows(first)[0]['company_name'], 'Quarterly')

    def test_latest_daily_wins_and_prior_sources_survive(self):
        first = self.observation('2026-10-01', 'daily', row('Old'))
        old = self.build([first])
        second = self.observation('2026-10-02', 'daily', row('New'))
        new = self.build([second], old)
        self.assertEqual(self.rows(new)[0]['company_name'], 'New')
        self.assertEqual(len(new.manifest.sources), 2)
        self.assertEqual(new.manifest.updated, 1)
        self.assertEqual(self.rows(new, 'changes')[0]['before']['company_name'], 'Old')

    def test_open_absence_retains_then_closed_withdrawal_is_gated(self):
        initial = self.observation(rows=row() + row(number=2))
        old = self.build([initial])
        revised = self.observation(rows=row('Revised'), seconds=1)
        open_candidate = self.build([revised], old)
        self.assertEqual((open_candidate.manifest.row_count, open_candidate.manifest.unresolved_absence), (2, 1))
        self.pin(date(2027, 1, 1))
        closed = self.build([revised], open_candidate)
        self.assertEqual((closed.manifest.row_count, closed.manifest.withdrawn, closed.manifest.gate), (1, 1, 'awaiting_approval'))
        self.assertIsNotNone(closed.candidate_ref)
        self.assertIsNotNone(self.store.get('Candidate', closed.manifest.generation_id))
        self.assertEqual(len(self.rows(old)), 2)

    def test_closed_membership_withholds_daily_only_keys(self):
        self.pin(date(2027, 1, 1))
        quarterly = self.observation()
        daily = self.observation('2026-10-02', 'daily', row(number=2))
        candidate = self.build([daily, quarterly])
        self.assertEqual(candidate.manifest.row_count, 1)

    def test_empty_or_invalid_input_never_builds_candidate(self):
        for body in (b'', b'bad row\n'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.observation(rows=body)
        self.assertEqual(list(self.store.scan('Candidate', {})), [])

    def test_equal_receipt_distinct_hash_conflicts_and_newer_revision_wins(self):
        first = self.observation('2026-10-01', 'daily', row('First'))
        equal = self.observation('2026-10-01', 'daily', row('Equal'))
        with self.assertRaisesRegex(Conflict, 'ambiguous'):
            select_sources((first,), (equal,))
        later = self.observation('2026-10-01', 'daily', row('Later'), seconds=2)
        candidate = self.build([first])
        newest = self.build([later], candidate)
        self.assertEqual(self.rows(newest)[0]['company_name'], 'Later')
        self.assertEqual(self.build([first], newest), newest)
        with self.assertRaisesRegex(Conflict, 'conflicting observations'):
            select_sources((first,), (replace(first, rows_sha256='a'*64),))
        with self.assertRaisesRegex(ValueError, 'source date does not match URL'):
            select_sources((first,), (replace(first, source=replace(first.source, period='2026-10-02')),))

    def test_duplicate_overlap_amendment_and_null_accession(self):
        legacy = row(number=3).replace(b'0000123456-26-000003.txt', b'legacy.txt')
        ref = self.observation(rows=row() * 2 + row(number=2, form='10-K/A') + legacy)
        daily = self.observation('2026-10-02', 'daily')
        candidate = self.build([ref, daily])
        self.assertEqual(candidate.manifest.row_count, 3)
        self.assertEqual([r['form_type'] for r in self.rows(candidate)], ['10-K', '10-K/A', '10-K'])
        self.assertIsNone(self.rows(candidate)[-1]['accession_number'])

    def test_filing_quarter_distributes_daily_and_off_period_quarterly_has_no_authority(self):
        daily = self.observation('2026-10-02', 'daily', row() + row(number=2, day='2026-09-30'))
        quarterly = self.observation('2026Q3', rows=row('Off-period'))
        candidate = self.build([daily, quarterly])
        self.assertIsNone(candidate.manifest.membership_source)
        self.assertEqual(self.rows(candidate)[0]['company_name'], 'Off-period')
        prior = self.build([daily], quarter='2026Q3')
        self.assertEqual(prior.manifest.row_count, 1)
        with self.assertRaisesRegex(ValueError, 'empty target-quarter'):
            self.build([quarterly], previous=prior, quarter='2026Q3')
        self.assertTrue(list((self.root / 'objects/quarantine').rglob('*.json')))

    def test_closed_daily_only_revised_absence_never_withdraws(self):
        self.pin(date(2027, 1, 1))
        first = self.observation('2026-10-01', 'daily', row() + row(number=2))
        before = self.build([first])
        revised = self.observation('2026-10-01', 'daily', row('Changed'), seconds=1)
        after = self.build([revised], before)
        self.assertEqual((after.manifest.row_count, after.manifest.withdrawn, after.manifest.gate), (2, 0, 'clear'))
        self.assertEqual(after.manifest.unresolved_absence, 1)
        self.assertEqual(self.build([revised], after), after)

    def test_provenance_only_refresh_has_no_business_update(self):
        first = self.observation('2026-10-01', 'daily')
        before = self.build([first])
        second = self.observation('2026-10-02', 'daily')
        after = self.build([second], before)
        self.assertEqual((after.manifest.updated, after.manifest.provenance_refreshed), (0, 1))
        self.assertEqual(self.rows(after, 'changes'), [])

    def test_previous_raw_contributors_replay_together_under_new_parser(self):
        from unittest.mock import patch
        from sec_edgar_ingest.etl import catalog
        first = self.observation('2026-10-01', 'daily')
        old = self.build([first])
        second = self.observation('2026-10-02', 'daily', row(number=2))
        self.settings, self.context = etl_context('fixture-index-parser-v2')
        self.pin(date(2026, 10, 7))
        with patch.object(catalog, 'transform_member', wraps=transform_member) as replay:
            candidate = self.build([second], old)
        self.assertEqual(replay.call_count, 2)
        self.assertEqual({ref.parser_version for ref in candidate.manifest.sources}, {'fixture-index-parser-v2'})
        self.assertEqual(candidate.manifest.sources[0].snapshot, select_sources((first,), (second,))[0].snapshot)
        self.assertEqual({value['parser_version'] for value in self.rows(candidate)}, {'fixture-index-parser-v2'})
        self.assertEqual(len(self.rows(old)), 1)

    def test_fingerprint_noop_and_base_bound_generation(self):
        first = self.observation('2026-10-01', 'daily')
        old = self.build([first])
        self.assertEqual(self.build([first], old), old)
        second = self.observation('2026-10-02', 'daily', row('Changed'))
        based = self.build([second], old)
        fresh = self.build([first, second])
        self.assertEqual(based.manifest.source_fingerprint, fresh.manifest.source_fingerprint)
        self.assertNotEqual(based.manifest.generation_id, fresh.manifest.generation_id)
        self.assertEqual((based.manifest.updated, fresh.manifest.added), (1, 1))
        self.assertEqual(source_fingerprint('2026Q4', (second, first), mode='open', membership_source=None,
                                           retained_from_generation=None), fresh.manifest.source_fingerprint)

    def test_future_and_unpinned_context_refused(self):
        ref = self.observation()
        with self.assertRaisesRegex(ValueError, 'future'):
            self.build([ref], quarter='2027Q1')
        self.context = replace(self.context, pinned_on=None)
        with self.assertRaisesRegex(ValueError, 'pinned'):
            self.build([ref])

    def test_existing_generation_preserves_producing_image(self):
        ref = self.observation()
        first = self.build([ref])
        self.settings = fixture_settings(etl={'parser_version': self.context.parser_version}, worker={'image_digest': 'sha256:' + 'b'*64}, fixture={'allow_clock_override': True})
        self.context = replace(self.context, image_digest=self.settings.worker.image_digest,
                               config_sha256=self.settings.config_sha256, pinned_on=None, effective_config={})
        self.context = pin_context(self.settings, self.context, date(2026, 10, 7))[0]
        self.assertEqual(self.build([ref]), first)

    def test_corrupt_manifest_and_data_are_refused(self):
        candidate = self.build([self.observation()])
        path = self.root / 'objects' / candidate.manifest_ref
        original = path.read_bytes()
        path.write_bytes(original + b'\n')
        with self.assertRaises(Conflict):
            read_manifest(self.capture(candidate), self.objects)
        path.write_bytes(original)
        data = self.root / 'objects' / candidate.manifest.files[0].path
        data.write_bytes(data.read_bytes()[:-1])
        with self.assertRaises(Conflict):
            validate_candidate(candidate, self.objects)
        with self.assertRaises(Conflict):
            self.build(candidate.manifest.sources)

    def test_retained_dependency_missing_corrupt_and_mismatched_refused(self):
        from sec_edgar_ingest.models import canonical_json
        old = self.build([self.observation(rows=row() + row(number=2))])
        candidate = self.build([self.observation(rows=row(), seconds=1)], old)
        dependency = self.root / 'objects' / candidate.manifest_ref.replace('manifest.json', 'retained-base.json')
        original = dependency.read_bytes()
        dependency.unlink()
        with self.assertRaises(FileNotFoundError):
            validate_candidate(candidate, self.objects)
        dependency.write_bytes(original + b'\n')
        with self.assertRaises(ValueError):
            validate_candidate(candidate, self.objects)
        dependency.write_bytes(canonical_json(self.capture(candidate).to_mapping()))
        with self.assertRaises(ValueError):
            validate_candidate(candidate, self.objects)
        dependency.write_bytes(original)
        validate_candidate(candidate, self.objects)

    def test_gate_record_is_exact_and_corruption_is_refused(self):
        from sec_edgar_ingest.models import parse_json
        old = self.build([self.observation(rows=row() + row(number=2))])
        revised = self.observation(rows=row(), seconds=1)
        self.pin(date(2027, 1, 1))
        candidate = self.build([revised], old)
        record = parse_json(self.objects.read(candidate.candidate_ref))
        self.assertEqual(record['base_generation_id'], old.manifest.generation_id)
        self.assertEqual(record['quarterly_hash'], revised.snapshot.sha256)
        self.assertEqual(record['source_fingerprint'], candidate.manifest.source_fingerprint)
        path = self.root / 'objects' / candidate.candidate_ref
        path.write_bytes(b'{}')
        with self.assertRaises((ValueError, Conflict)):
            validate_candidate(candidate, self.objects)

    def test_all_four_boundaries_recover_without_early_candidate_index(self):
        from support import Faults
        old = self.build([self.observation(rows=row() + row(number=2))])
        revised = self.observation(rows=row(), seconds=1)
        self.pin(date(2027, 1, 1))
        for boundary in ('candidate.after_data', 'candidate.after_changes', 'candidate.after_manifest', 'candidate.after_validation'):
            fault = Faults()
            def crash():
                raise RuntimeError('interrupted candidate')
            fault.at(boundary, crash)
            with self.subTest(boundary=boundary), self.assertRaisesRegex(RuntimeError, 'interrupted'):
                self.build([revised], old, observer=fault)
            self.assertEqual(list(self.store.scan('Candidate', {})), [])
        candidate = self.build([revised], old)
        self.assertIsNotNone(self.store.get('Candidate', candidate.manifest.generation_id))

    def test_valid_hash_but_invented_canonical_row_is_refused(self):
        import hashlib
        import pyarrow as pa
        import pyarrow.parquet as pq
        from sec_edgar_ingest.models import canonical_json
        from sec_edgar_ingest.etl.contracts import canonical_schema
        candidate = self.build([self.observation()])
        values = self.rows(candidate)
        values[0]['company_name'] = 'Invented row'
        ref = candidate.manifest.files[0]
        path = self.root / 'objects' / ref.path
        pq.write_table(pa.Table.from_pylist(values, schema=canonical_schema()), path,
                       version='2.6', compression='snappy', use_dictionary=False)
        body = path.read_bytes()
        changed_ref = replace(ref, sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body))
        manifest = replace(candidate.manifest, files=(changed_ref, candidate.manifest.files[1]))
        body = canonical_json(manifest.to_mapping())
        (self.root / 'objects' / candidate.manifest_ref).write_bytes(body)
        forged = replace(candidate, manifest=manifest, manifest_sha256=hashlib.sha256(body).hexdigest(), manifest_bytes=len(body))
        with self.assertRaises((ValueError, Conflict)):
            validate_candidate(forged, self.objects)

    def test_wrong_precedence_with_valid_source_row_is_refused(self):
        import hashlib
        import pyarrow as pa
        import pyarrow.parquet as pq
        from sec_edgar_ingest.models import canonical_json
        from sec_edgar_ingest.etl.contracts import canonical_schema, change_schema
        from sec_edgar_ingest.etl.transform import read_observations
        quarterly = self.observation(rows=row('Quarterly'))
        daily = self.observation('2026-10-02', 'daily', row('Daily loser'))
        candidate = self.build([quarterly, daily])
        loser = next(read_observations(daily, self.objects)).row
        value = {**loser.to_mapping(), 'filing_date': loser.filing_date}
        files = []
        for ref in candidate.manifest.files:
            path = self.root / 'objects' / ref.path
            values = [value] if ref.role == 'data' else [{
                'change_type': 'added', 'cik': loser.cik, 'archive_path': loser.archive_path,
                'before': None, 'after': value, 'reason': None}]
            schema = canonical_schema() if ref.role == 'data' else change_schema()
            pq.write_table(pa.Table.from_pylist(values, schema=schema), path,
                           version='2.6', compression='snappy', use_dictionary=False)
            body = path.read_bytes()
            files.append(replace(ref, sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body)))
        manifest = replace(candidate.manifest, files=tuple(files))
        body = canonical_json(manifest.to_mapping())
        (self.root / 'objects' / candidate.manifest_ref).write_bytes(body)
        forged = replace(candidate, manifest=manifest, manifest_sha256=hashlib.sha256(body).hexdigest(), manifest_bytes=len(body))
        with self.assertRaisesRegex(ValueError, 'rank|precedence'):
            validate_candidate(forged, self.objects)

    def test_batches_are_bounded_and_rows_are_sorted(self):
        import pyarrow.parquet as pq
        ref = self.observation('2026-10-02', 'daily', b''.join(row(number=number) for number in range(8193, 0, -1)))
        candidate = self.build([ref])
        self.assertEqual(candidate.manifest.row_count, 8193)
        for ref in candidate.manifest.files:
            with pq.ParquetFile(self.root / 'objects' / ref.path) as parquet:
                self.assertEqual(parquet.num_row_groups, 2)
                self.assertEqual([parquet.metadata.row_group(i).num_rows for i in range(2)], [8192, 1])

    def test_same_hash_adopts_prior_snapshot_receipt_and_fingerprint(self):
        first = self.observation()
        candidate = self.build([first])
        changed_receipt = replace(first, snapshot=replace(first.snapshot, received_at=first.snapshot.received_at + timedelta(seconds=1)))
        self.assertEqual(select_sources((first,), (changed_receipt,)), (first,))
        self.assertEqual(self.build([changed_receipt], candidate), candidate)

    def test_manifest_capture_noncanonical_wrong_identity_and_counts_refused(self):
        import hashlib
        from sec_edgar_ingest.models import canonical_json
        candidate = self.build([self.observation()])
        capture = self.capture(candidate)
        with self.assertRaises(ValueError):
            read_manifest(replace(capture, quarter='2026Q3'), self.objects)
        path = self.root / 'objects' / candidate.manifest_ref
        for body in (path.read_bytes() + b'\n', canonical_json({**candidate.manifest.to_mapping(), 'generation_id': 'a'*64})):
            path.write_bytes(body)
            with self.assertRaises(ValueError):
                read_manifest(replace(capture, manifest_sha256=hashlib.sha256(body).hexdigest(), manifest_bytes=len(body)), self.objects)
        manifest = replace(candidate.manifest, added=2)
        body = canonical_json(manifest.to_mapping())
        path.write_bytes(body)
        with self.assertRaisesRegex(ValueError, 'count'):
            validate_candidate(replace(candidate, manifest=manifest, manifest_sha256=hashlib.sha256(body).hexdigest(), manifest_bytes=len(body)), self.objects)

    def test_retain_real_candidate_proof_when_requested(self):
        import hashlib
        import json
        import os
        import shutil
        old = self.build([self.observation(rows=row() + row(number=2))])
        revised = self.observation(rows=row('Changed'), seconds=1)
        retained = self.build([revised], old)
        self.pin(date(2027, 1, 1))
        gated = self.build([revised], retained)
        proof = {'initial': old.to_mapping(), 'retained': retained.to_mapping(), 'gated': gated.to_mapping(),
                 'gate_bytes_hex': self.objects.read(gated.candidate_ref).hex(),
                 'gate_sha256': hashlib.sha256(self.objects.read(gated.candidate_ref)).hexdigest(),
                 'pointer': None, 'source_set_sha256': hashlib.sha256(__import__('sec_edgar_ingest.models', fromlist=['canonical_json']).canonical_json([ref.to_mapping() for ref in gated.manifest.sources])).hexdigest()}
        destination = os.environ.get('SEC_EDGAR_CATALOG_PROOF')
        if destination:
            output = Path(destination)
            output.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.root / 'objects', output / 'objects', dirs_exist_ok=True)
            (output / 'proof.json').write_text(json.dumps(proof, sort_keys=True, indent=2) + '\n')
        self.assertIsNone(self.state.pointer('2026Q4'))

    def test_consistent_hashes_and_counts_cannot_hide_a_missing_selected_key(self):
        import hashlib
        import pyarrow as pa
        import pyarrow.parquet as pq
        from sec_edgar_ingest.models import canonical_json
        from sec_edgar_ingest.etl.contracts import canonical_schema, change_schema
        candidate = self.build([self.observation(rows=row() + row(number=2))])
        files = []
        for ref in candidate.manifest.files:
            values = self.rows(candidate, ref.role)[:1]
            path = self.root / 'objects' / ref.path
            schema = canonical_schema() if ref.role == 'data' else change_schema()
            pq.write_table(pa.Table.from_pylist(values, schema=schema), path,
                           version='2.6', compression='snappy', use_dictionary=False)
            body = path.read_bytes()
            files.append(replace(ref, sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body), row_count=1))
        manifest = replace(candidate.manifest, files=tuple(files), row_count=1, added=1)
        body = canonical_json(manifest.to_mapping())
        (self.root / 'objects' / candidate.manifest_ref).write_bytes(body)
        forged = replace(candidate, manifest=manifest, manifest_sha256=hashlib.sha256(body).hexdigest(), manifest_bytes=len(body))
        with self.assertRaisesRegex(ValueError, 'missing selected'):
            validate_candidate(forged, self.objects)

    def rewrite_changes(self, candidate, changes, **counts):
        """Tamper real immutable fixture bytes and consistently update references."""
        import hashlib
        import pyarrow as pa
        import pyarrow.parquet as pq
        from sec_edgar_ingest.etl.contracts import change_schema
        from sec_edgar_ingest.models import canonical_json
        change_ref = next(ref for ref in candidate.manifest.files if ref.role == 'changes')
        path = self.root / 'objects' / change_ref.path
        pq.write_table(pa.Table.from_pylist(changes, schema=change_schema()), path,
                       version='2.6', compression='snappy', use_dictionary=False)
        body = path.read_bytes()
        change_ref = replace(change_ref, sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body), row_count=len(changes))
        files = tuple(change_ref if ref.role == 'changes' else ref for ref in candidate.manifest.files)
        manifest = replace(candidate.manifest, files=files, **counts)
        body = canonical_json(manifest.to_mapping())
        (self.root / 'objects' / candidate.manifest_ref).write_bytes(body)
        return replace(candidate, manifest=manifest, manifest_sha256=hashlib.sha256(body).hexdigest(),
                       manifest_bytes=len(body), candidate_ref=None if manifest.gate == 'clear' else candidate.candidate_ref)

    def test_suppressed_withdrawal_with_consistent_hashes_cannot_clear_gate(self):
        old = self.build([self.observation(rows=row() + row(number=2))])
        revised = self.observation(rows=row(), seconds=1)
        self.pin(date(2027, 1, 1))
        candidate = self.build([revised], old)
        forged = self.rewrite_changes(candidate, [], withdrawn=0, gate='clear')
        with self.assertRaisesRegex(ValueError, 'delta'):
            validate_candidate(forged, self.objects)
        with self.assertRaisesRegex(ValueError, 'delta'):
            self.build([revised], old)

    def test_omitted_update_with_consistent_counts_is_refused(self):
        old = self.build([self.observation('2026-10-01', 'daily')])
        revised = self.observation('2026-10-02', 'daily', row('Changed'))
        candidate = self.build([revised], old)
        forged = self.rewrite_changes(candidate, [], updated=0)
        with self.assertRaisesRegex(ValueError, 'delta'):
            validate_candidate(forged, self.objects)

    def test_forged_update_before_value_is_refused(self):
        old = self.build([self.observation('2026-10-01', 'daily')])
        revised = self.observation('2026-10-02', 'daily', row('Changed'))
        candidate = self.build([revised], old)
        changes = self.rows(candidate, 'changes')
        changes[0]['before']['company_name'] = 'Invented before'
        forged = self.rewrite_changes(candidate, changes)
        with self.assertRaisesRegex(ValueError, 'delta'):
            validate_candidate(forged, self.objects)

    def test_forged_provenance_refresh_count_is_refused(self):
        old = self.build([self.observation('2026-10-01', 'daily')])
        candidate = self.build([self.observation('2026-10-02', 'daily')], old)
        forged = self.rewrite_changes(candidate, [], provenance_refreshed=0)
        with self.assertRaisesRegex(ValueError, 'delta'):
            validate_candidate(forged, self.objects)

    def test_nonretaining_candidate_requires_exact_base_capture(self):
        from sec_edgar_ingest.models import canonical_json
        old = self.build([self.observation('2026-10-01', 'daily')])
        revised = self.observation('2026-10-02', 'daily', row('Changed'))
        candidate = self.build([revised], old)
        self.assertIsNone(candidate.manifest.retained_from_generation)
        dependency = self.root / 'objects' / candidate.manifest_ref.replace('manifest.json', 'retained-base.json')
        original = dependency.read_bytes()
        self.assertEqual(original, canonical_json(self.capture(old).to_mapping()))
        dependency.unlink()
        with self.assertRaises(FileNotFoundError):
            validate_candidate(candidate, self.objects)
        dependency.write_bytes(original + b'\n')
        with self.assertRaises(ValueError):
            validate_candidate(candidate, self.objects)
        dependency.write_bytes(canonical_json(self.capture(candidate).to_mapping()))
        with self.assertRaises(ValueError):
            validate_candidate(candidate, self.objects)
        dependency.write_bytes(original)
        self.assertEqual(self.build([revised], old), candidate)
