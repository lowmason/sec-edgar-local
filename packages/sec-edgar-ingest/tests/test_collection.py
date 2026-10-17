import hashlib
import importlib
import importlib.util
import json
import multiprocessing
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.worksets import decode_snapshot_workset, encode_workset, make_source_workset
from support import (CollectionCrash, collection_harness, collection_race_entry, discovery_harness,
                     failed_response, fixture_context, fixture_source, fixture_workset,
                     listing_response, retain_collection_proof, run_collection_process, valid_idx_response)

CRASH_POINTS = ('after_receipt_checkpoint', 'after_raw_promotion', 'after_promotion_receipt',
                'after_snapshot_record', 'after_binding', 'after_snapshot_workset_write', 'before_result_write')


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('sec_edgar_ingest.collection'),
                             'Collection must durably promote and pin exact immutable inputs')
        self.collection = importlib.import_module('sec_edgar_ingest.collection')
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = fixture_source(kind='daily', period='2026-10-01')
        self.workset = fixture_workset((self.source,))

    def harness(self, responses):
        h = collection_harness(self.root, responses)
        self.addCleanup(h.close)
        return h

    def test_retry_preserves_first_member_pin(self):
        h = self.harness([valid_idx_response('daily')])
        first = h.collect(self.workset)
        old = h.snapshot_workset(first).snapshots[0]
        h.install_newer_snapshot(self.source, valid_idx_response('daily', company='Changed fixture').body)
        resumed = h.reopen()
        self.addCleanup(resumed.close)
        result = resumed.collect(self.workset)
        self.assertEqual(resumed.snapshot_workset(result).snapshots[0], old)
        self.assertEqual(resumed.fetch_count, 1)
        self.assertEqual((result.downloaded, result.unchanged, result.pending, result.failed), (0, 1, 0, 0))
        self.assertEqual(result.snapshot_workset_ref, first.snapshot_workset_ref)

    def test_partial_success_404_then_only_unresolved_member_fetches(self):
        sources = tuple(sorted((self.source, fixture_source(kind='daily', period='2026-10-02')),
                               key=lambda source: source.source_id))
        workset = fixture_workset(sources)
        h = self.harness([valid_idx_response('daily'), failed_response(404), valid_idx_response('daily', 'Recovery')])
        first = h.collect(workset)
        self.assertEqual(first.outcome, 'incomplete')
        self.assertIsNone(first.snapshot_workset_ref)
        self.assertEqual((first.downloaded, first.pending, first.failed), (1, 1, 1))
        pin = h.source_state.binding(workset.workset_id, sources[0].source_id)
        self.assertIsNotNone(pin)
        recovered = h.reopen()
        self.addCleanup(recovered.close)
        result = recovered.collect(workset)
        self.assertEqual(result.outcome, 'success')
        self.assertEqual((result.downloaded, result.unchanged, result.pending), (1, 1, 0))
        self.assertEqual(recovered.fetch_count, 3)
        self.assertEqual(recovered.source_state.binding(workset.workset_id, sources[0].source_id), pin)
        self.assertEqual(len(tuple(recovered.store.scan('Failure', {}))), 1)

    def unsafe_text_harness(self, name):
        h = collection_harness(self.root / name, [])
        self.addCleanup(h.close)
        return h

    def test_unsafe_member_exception_text_is_recorded_as_one_line_gap(self):
        for name, exception, message in (
                ('empty', Conflict(''), 'Conflict'),
                ('multi-line', OSError('state store refused\nRequestId: fixture'), 'state store refused RequestId: fixture'),
                ('safe', Conflict('member pin conflicts'), 'member pin conflicts')):
            with self.subTest(name):
                h = self.unsafe_text_harness(name)
                with patch('sec_edgar_ingest.collection.collect_member', side_effect=exception):
                    result = h.collect(self.workset)
                self.assertEqual((result.outcome, result.failed), ('state_conflict', 1))
                self.assertEqual([(gap.code, gap.message, gap.source_id) for gap in result.gaps],
                                 [('state_conflict', message, self.source.source_id)])

    def test_unsafe_failure_checkpoint_text_is_recorded_as_one_line_gap(self):
        prefix = 'source failure checkpoint could not be recorded: '
        for name, failure, message in (('empty', OSError(''), prefix + 'OSError'),
                                       ('multi-line', OSError('disk\nfull'), prefix + 'disk full')):
            with self.subTest(name):
                h = self.unsafe_text_harness(name)
                with patch('sec_edgar_ingest.collection.collect_member', side_effect=Conflict('member pin conflicts')), \
                     patch.object(h.source_state, 'record_failure', side_effect=failure):
                    result = h.collect(self.workset)
                self.assertEqual(result.outcome, 'state_conflict')
                self.assertEqual([gap.message for gap in result.gaps], [message, 'member pin conflicts'])
                self.assertEqual(result.gaps[0].details['cause']['message'], 'member pin conflicts')

    def test_unsafe_input_check_text_is_recorded_as_one_line_gap(self):
        for name, exception, message in (('empty', ValueError(''), 'ValueError'),
                                         ('multi-line', ValueError('workset\ninvalid'), 'workset invalid')):
            with self.subTest(name):
                h = self.unsafe_text_harness(name)
                with patch('sec_edgar_ingest.collection._check_collection_input', side_effect=exception):
                    result = h.collect(self.workset)
                self.assertEqual(result.outcome, 'configuration')
                self.assertEqual([(gap.code, gap.message) for gap in result.gaps], [('configuration', message)])

    def test_new_workset_reuses_accepted_and_explicit_refresh_fetches_new_original(self):
        h = self.harness([valid_idx_response('daily'), valid_idx_response('daily', 'Refreshed')])
        first = h.snapshot_workset(h.collect(self.workset)).snapshots[0]
        reuse = make_source_workset(self.workset.context, self.workset.pinned_end_quarter, 'new-reuse',
            self.workset.members, self.workset.directories, self.workset.overlap_from)
        self.assertEqual(h.snapshot_workset(h.collect(reuse)).snapshots[0], first)
        self.assertEqual(h.fetch_count, 1)
        refresh = make_source_workset(self.workset.context, self.workset.pinned_end_quarter, 'new-refresh',
            self.workset.members, self.workset.directories, self.workset.overlap_from, acquisition_mode='refresh')
        fresh = h.snapshot_workset(h.collect(refresh)).snapshots[0]
        self.assertNotEqual(fresh.sha256, first.sha256)
        self.assertEqual(h.fetch_count, 2)
        self.assertEqual(h.snapshot_workset(h.collect(self.workset)).snapshots[0], first)

    def test_refresh_same_hash_retains_first_receipt_metadata(self):
        h = self.harness([valid_idx_response('daily'), valid_idx_response('daily')])
        first = h.snapshot_workset(h.collect(self.workset)).snapshots[0]
        h.clock.advance(5)
        refresh = make_source_workset(self.workset.context, self.workset.pinned_end_quarter, 'same-hash',
            self.workset.members, self.workset.directories, self.workset.overlap_from, acquisition_mode='refresh')
        repeated = h.snapshot_workset(h.collect(refresh)).snapshots[0]
        self.assertEqual(repeated, first)
        self.assertEqual(h.fetch_count, 2)
        self.assertGreater(h.source_state.get_source(self.source.source_id).value['latest_received_at'], first.received_at.isoformat())

    def test_successful_empty_and_failed_empty_have_distinct_results(self):
        h = self.harness([])
        empty = fixture_workset(())
        successful = h.collect(empty)
        self.assertEqual(successful.outcome, 'no_new_sources')
        self.assertEqual(h.snapshot_workset(successful).snapshots, ())
        failed = h.collect(fixture_workset((), discovery_complete=False))
        self.assertEqual(failed.outcome, 'incomplete')
        self.assertIsNone(failed.snapshot_workset_ref)
        self.assertTrue(any(gap.code == 'discovery_failed' for gap in failed.gaps))
        self.assertEqual(h.fetch_count, 0)

    def test_incomplete_discovery_retains_successful_member_without_snapshot_workset(self):
        h = self.harness([valid_idx_response('daily')])
        workset = fixture_workset((self.source,), discovery_complete=False)
        result = h.collect(workset)
        self.assertEqual(result.outcome, 'incomplete')
        self.assertEqual(result.downloaded, 1)
        self.assertIsNotNone(h.source_state.binding(workset.workset_id, self.source.source_id))
        self.assertIsNone(result.snapshot_workset_ref)

    def test_pinned_missing_or_corrupt_raw_refuses_repair_and_fetch(self):
        for corruption in ('missing', 'corrupt'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as directory:
                h = collection_harness(Path(directory), [valid_idx_response('daily')])
                self.addCleanup(h.close)
                first = h.collect(self.workset)
                snapshot = h.snapshot_workset(first).snapshots[0]
                path = h.objects.directory / snapshot.raw_path
                path.unlink() if corruption == 'missing' else path.write_bytes(b'corrupt')
                h.forbid_fetch = True
                result = h.collect(self.workset)
                self.assertEqual(result.outcome, 'state_conflict')
                self.assertIsNone(result.snapshot_workset_ref)
                self.assertEqual(h.fetch_count, 1)
                self.assertEqual(h.source_state.binding(self.workset.workset_id, self.source.source_id).snapshot_sha256, snapshot.sha256)

    def test_mismatched_config_parser_image_or_client_refuses_before_request(self):
        for field, value in (('config_sha256', 'f'*64), ('parser_version', 'other-parser'),
                             ('image_digest', 'sha256:'+'f'*64)):
            with self.subTest(field=field):
                h = self.harness([])
                h.context = replace(fixture_context(), **{field: value})
                result = h.collect(self.workset)
                self.assertEqual(result.outcome, 'configuration')
                self.assertIsNone(result.snapshot_workset_ref)
                self.assertEqual(h.fetch_count, 0)
        with self.assertRaises(ValueError):
            replace(fixture_context(), schema_version='sec-index-v2')

    def test_collector_current_context_and_snapshot_workset_origin_are_distinct(self):
        origin = replace(self.workset.context, command='discover', execution_id='discovery-execution')
        workset = make_source_workset(origin, self.workset.pinned_end_quarter, 'origin',
            self.workset.members, self.workset.directories, self.workset.overlap_from)
        h = self.harness([valid_idx_response('daily')])
        h.context = replace(fixture_context(), run_id='current-collection-run')
        result = h.collect(workset)
        self.assertEqual(result.context.command, 'collect')
        self.assertEqual(result.context.run_id, 'current-collection-run')
        self.assertEqual(h.snapshot_workset(result).context, origin)

    def test_invalid_source_workset_digest_and_retained_path_are_refused(self):
        h = self.harness([])
        result = h.collect(replace(self.workset, workset_id='f'*64))
        self.assertEqual(result.outcome, 'state_conflict')
        self.assertEqual(h.fetch_count, 0)
        with tempfile.TemporaryDirectory() as directory:
            other = collection_harness(Path(directory), [])
            self.addCleanup(other.close)
            result = self.collection.collect(self.workset, other.context, other.settings, other.client,
                                             other.source_state, other.objects, other.faults)
            self.assertEqual(result.outcome, 'state_conflict')
            self.assertEqual(other.fetch_count, 0)

    def test_snapshot_workset_immutable_collision_returns_failure(self):
        h = self.harness([valid_idx_response('daily')])
        first = h.collect(self.workset)
        (h.objects.directory / first.snapshot_workset_ref).write_bytes(b'collision')
        failed = h.collect(self.workset)
        self.assertEqual(failed.outcome, 'state_conflict')
        self.assertIsNone(failed.snapshot_workset_ref)
        self.assertEqual(h.fetch_count, 1)

    def test_snapshot_assembly_checks_actual_source_period(self):
        h = self.harness([valid_idx_response('daily')])
        first = h.snapshot_workset(h.collect(self.workset)).snapshots[0]
        wrong = replace(first, raw_path=first.raw_path.replace('2026-10-01', '2026-10-02'))
        from sec_edgar_ingest.worksets import make_snapshot_workset
        with self.assertRaisesRegex(ValueError, 'source|period|address'):
            make_snapshot_workset(self.workset, (wrong,))

    def test_quarantine_retains_original_receipt_and_partial_bytes(self):
        from sec_edgar_ingest.download import ResponseSpec
        response = ResponseSpec(200, b'prefix bytes', {'Content-Type': 'text/html'}, 'ownership_lost')
        h = self.harness([response])
        result = h.collect(self.workset)
        self.assertEqual(result.outcome, 'ownership_lost')
        self.assertEqual(result.quarantined, 1)
        self.assertEqual((result.downloaded, result.pending, result.failed), (0, 1, 1))
        retained = list(h.objects.directory.glob('quarantine/sec/*/*/*/*/body'))
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), response.body)
        metadata = json.loads(retained[0].with_name('receipt.json').read_bytes())
        self.assertEqual(metadata['receipt']['byte_count'], len(response.body))
        self.assertFalse(metadata['receipt']['complete'])
        self.assertEqual(metadata['error']['code'], 'ownership_lost')
        self.assertEqual(metadata['receipt']['headers'], response.headers)
        self.assertEqual(metadata['receipt']['sha256'], hashlib.sha256(response.body).hexdigest())
        self.assertEqual(metadata['request_id'], tuple(h.store.scan('TransportAttempt', {}))[0].value['request_id'])

    def test_bad_envelope_continues_safe_independent_member(self):
        from sec_edgar_ingest.download import ResponseSpec
        sources = tuple(sorted((self.source, fixture_source(kind='daily', period='2026-10-02')),
                               key=lambda source: source.source_id))
        h = self.harness([ResponseSpec(200, b'bad envelope', {}), valid_idx_response('daily')])
        result = h.collect(fixture_workset(sources))
        self.assertEqual(result.outcome, 'incomplete')
        self.assertEqual((result.downloaded, result.pending, result.failed, result.quarantined), (1, 1, 1, 1))
        self.assertEqual(h.fetch_count, 2)
        self.assertIsNotNone(h.source_state.binding(fixture_workset(sources).workset_id, sources[1].source_id))

    def test_access_denial_and_policy_block_stop_remaining_members(self):
        from sec_edgar_ingest.download import ResponseSpec
        sources = tuple(sorted((self.source, fixture_source(kind='daily', period='2026-10-02')),
                               key=lambda source: source.source_id))
        for response, outcome in ((ResponseSpec(403, b'access denied', {}), 'access_blocked'),
            (ResponseSpec(429, b'throttled', {'Retry-After': '1'+'0'*400}), 'deferred')):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                h = collection_harness(Path(directory), [response, valid_idx_response('daily')])
                self.addCleanup(h.close)
                result = h.collect(fixture_workset(sources))
                self.assertEqual(result.outcome, outcome)
                self.assertEqual(h.fetch_count, 1)
                self.assertEqual(result.pending, 2)
                self.assertIsNone(result.snapshot_workset_ref)
                again = h.collect(fixture_workset(sources))
                self.assertEqual(again.outcome, outcome)
                self.assertEqual(h.fetch_count, 1)

    def test_stage_receipt_without_reservation_fails_closed(self):
        from support import body_receipt
        receipt = replace(body_receipt(self.root, valid_idx_response('daily').body), url=self.source.canonical_url)
        h = self.harness([])
        with self.assertRaisesRegex(ValueError, 'request|reservation'):
            self.collection.stage_receipt(h.objects, h.context, self.source, receipt)

    def test_real_discover_to_collect_verifies_approved_source_path_and_digest(self):
        h = discovery_harness(self.root, {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
        self.addCleanup(h.close)
        workset = h.run('daily', date(2026, 10, 6), 'integration')
        approved = f'worksets/sec/source/sha256={workset.workset_id}/workset.json'
        self.assertEqual(h.objects.read(approved), encode_workset(workset))
        collector = self.harness([valid_idx_response('daily')])
        collector.settings = h.settings
        collector.client.settings = collector.coordinator.settings = h.settings
        collector.context = replace(workset.context, command='collect', execution_id='consumer', attempt_id='consumer')
        result = self.collection.collect(workset, collector.context, collector.settings, collector.client,
                                         collector.source_state, collector.objects, collector.faults)
        self.assertEqual(result.outcome, 'success')
        self.assertEqual(result.source_workset_ref, approved)
        self.assertEqual(collector.snapshot_workset(result).source_workset_id, workset.workset_id)
        (h.objects.directory / approved).write_bytes(b'corrupt source workset')
        corrupted = self.collection.collect(workset, replace(collector.context, attempt_id='corrupt'), collector.settings,
            collector.client, collector.source_state, collector.objects, collector.faults)
        self.assertEqual(corrupted.outcome, 'state_conflict')

    def test_existing_pin_does_not_consult_broken_mutable_latest(self):
        h = self.harness([valid_idx_response('daily')])
        first = h.collect(self.workset)
        row = h.source_state.get_source(self.source.source_id)
        value = row.to_mapping()['value']
        value['latest_downloaded_snapshot'] = 'f'*64
        h.store.replace('Source', self.source.source_id, value, row.version)
        h.forbid_fetch = True
        result = h.collect(self.workset)
        self.assertEqual(result.outcome, 'success')
        self.assertEqual(result.snapshot_workset_ref, first.snapshot_workset_ref)
        self.assertEqual((result.downloaded, result.unchanged), (0, 1))

    def test_staged_only_recovery_accounts_missing_receipt_as_next_request(self):
        h = self.harness([valid_idx_response('daily'), valid_idx_response('daily', 'Second accounted original')])
        h.fail_at('after_receipt_checkpoint')
        with self.assertRaises(CollectionCrash):
            h.collect(self.workset)
        context = h.source_state.active_context
        staged = h.source_state.staged_receipt(self.workset.workset_id, self.source.source_id)['receipts'][0]
        (h.objects.directory / staged['temporary_ref']).unlink()
        result = self.collection.collect(self.workset, context, h.settings, h.client, h.source_state, h.objects, h.faults)
        self.assertEqual(result.outcome, 'success')
        rows = h.source_state.request_history(context, self.source.canonical_url)
        self.assertEqual([row.value['ordinal'] for row in rows], [1, 2])
        self.assertEqual(h.fetch_count, 2)
        self.assertEqual(h.snapshot_workset(result).snapshots[0].sha256,
                         hashlib.sha256(valid_idx_response('daily', 'Second accounted original').body).hexdigest())

    def test_promoted_missing_or_corrupt_raw_cannot_be_repaired_from_staging(self):
        for corruption in ('missing', 'corrupt'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as directory:
                h = collection_harness(Path(directory), [valid_idx_response('daily')])
                self.addCleanup(h.close)
                h.fail_at('after_promotion_receipt')
                with self.assertRaises(CollectionCrash):
                    h.collect(self.workset)
                promoted = h.source_state.promotion_receipt(self.workset.workset_id, self.source.source_id)['snapshots'][0]
                path = h.objects.directory / promoted['raw_path']
                path.unlink() if corruption == 'missing' else path.write_bytes(b'corrupt')
                h.forbid_fetch = True
                result = h.collect(self.workset)
                self.assertEqual(result.outcome, 'state_conflict')
                self.assertEqual(h.fetch_count, 1)
                self.assertIsNone(result.snapshot_workset_ref)
                self.assertIsNone(h.source_state.binding(self.workset.workset_id, self.source.source_id))

    def test_checkpoint_tampering_does_not_invent_transport_provenance(self):
        h = self.harness([valid_idx_response('daily')])
        h.fail_at('after_raw_promotion')
        with self.assertRaises(CollectionCrash):
            h.collect(self.workset)
        row = tuple(h.store.scan('StagedReceipt', {}))[0]
        value = row.to_mapping()['value']
        value['transport_attempt']['request_id'] = 'unrelated-reservation'
        h.store.replace('StagedReceipt', value['checkpoint_id'], value, row.version)
        h.forbid_fetch = True
        result = h.collect(self.workset)
        self.assertEqual(result.outcome, 'state_conflict')
        self.assertIsNone(result.snapshot_workset_ref)
        self.assertEqual(h.fetch_count, 1)

    def test_each_failed_retry_prefix_is_quarantined_before_success_result(self):
        from sec_edgar_ingest.download import ResponseSpec
        prefix = ResponseSpec(200, b'retained truncated prefix', {'X-Fixture': 'partial'}, 'read_timeout')
        h = self.harness([prefix, valid_idx_response('daily')])
        result = h.collect(self.workset)
        self.assertEqual(result.outcome, 'success')
        self.assertEqual(result.quarantined, 1)
        self.assertEqual(h.fetch_count, 2)
        rows = h.source_state.request_history(result.context, self.source.canonical_url)
        path = f'quarantine/sec/{result.context.run_id}/{self.source.source_id}/{result.context.attempt_id}/{rows[0].value["request_id"]}/body'
        self.assertEqual(h.objects.read(path), prefix.body)
        metadata = json.loads(h.objects.read(path.rsplit('/', 1)[0]+'/receipt.json'))
        self.assertEqual(metadata['error']['code'], 'read_timeout')
        self.assertFalse(metadata['receipt']['complete'])
        self.assertEqual(metadata['request_id'], rows[0].value['permit']['request_id'])

    def test_fatal_halt_still_counts_later_existing_pin_as_complete(self):
        from sec_edgar_ingest.download import ResponseSpec
        sources = tuple(sorted((self.source, fixture_source(kind='daily', period='2026-10-02')),
                               key=lambda source: source.source_id))
        workset = fixture_workset(sources)
        h = self.harness([valid_idx_response('daily'), ResponseSpec(403, b'access denied', {})])
        h.objects.put_once(h.source_workset_path(workset), encode_workset(workset))
        h.source_state.observe(sources[1], h.clock.now(), 'available')
        self.collection.collect_member(workset, sources[1], h.context, h.settings, h.client,
                                       h.source_state, h.objects, h.faults)
        result = h.collect(workset)
        self.assertEqual(result.outcome, 'access_blocked')
        self.assertEqual((result.pending, result.unchanged, result.failed), (1, 1, 1))
        self.assertEqual(h.fetch_count, 2)

    def test_repeated_attempt_identity_with_changed_context_returns_state_conflict(self):
        h = self.harness([])
        h.source_state.begin_attempt(h.context)
        h.objects.put_once(h.source_workset_path(self.workset), encode_workset(self.workset))
        changed = replace(h.context, priority='daily')
        result = self.collection.collect(self.workset, changed, h.settings, h.client, h.source_state, h.objects, h.faults)
        self.assertEqual(result.outcome, 'state_conflict')
        self.assertEqual(h.fetch_count, 0)

    def test_direct_member_call_refuses_incompatible_versions_before_fetch(self):
        h = self.harness([valid_idx_response('daily')])
        h.objects.put_once(h.source_workset_path(self.workset), encode_workset(self.workset))
        wrong = replace(h.context, parser_version='other-parser')
        with self.assertRaises(ValueError):
            self.collection.collect_member(self.workset, self.source, wrong, h.settings, h.client,
                                           h.source_state, h.objects, h.faults)
        self.assertEqual(h.fetch_count, 0)
        self.assertIsNone(h.source_state.binding(self.workset.workset_id, self.source.source_id))

    def test_path_components_are_refused_before_request(self):
        for field in ('run_id', 'attempt_id'):
            with self.subTest(field=field):
                h = self.harness([valid_idx_response('daily')])
                h.context = replace(h.context, **{field: 'unsafe/nested'})
                h.objects.put_once(h.source_workset_path(self.workset), encode_workset(self.workset))
                result = self.collection.collect(self.workset, h.context, h.settings, h.client,
                                                 h.source_state, h.objects, h.faults)
                self.assertEqual(result.outcome, 'configuration')
                self.assertEqual(h.fetch_count, 0)
                self.assertIsNone(result.snapshot_workset_ref)

    def test_state_failure_record_conflict_returns_honest_gap(self):
        h = self.harness([])
        h.source_state.observe(self.source, h.clock.now(), 'available')
        row = h.source_state.get_source(self.source.source_id)
        value = row.to_mapping()['value']
        value['source'] = fixture_source(kind='daily', period='2026-10-02').to_mapping()
        h.store.replace('Source', self.source.source_id, value, row.version)
        result = h.collect(self.workset)
        self.assertEqual(result.outcome, 'state_conflict')
        self.assertEqual(result.pending, 1)
        self.assertEqual(h.fetch_count, 0)
        self.assertTrue(result.gaps)

    def test_quarterly_collection_preserves_original_zip_representation(self):
        source = fixture_source(period='2015Q1')
        response = valid_idx_response('quarterly')
        h = self.harness([response])
        result = h.collect(fixture_workset((source,)))
        self.assertEqual(result.outcome, 'success')
        snapshot = h.snapshot_workset(result).snapshots[0]
        self.assertEqual(snapshot.representation, 'zip')
        self.assertEqual(snapshot.envelope_version, 'sec-quarterly-envelope-v1')
        self.assertEqual(snapshot.raw_path,
            f'raw/sec/indexes/kind=quarterly/period=2015Q1/sha256={hashlib.sha256(response.body).hexdigest()}/master.zip')
        self.assertEqual(h.objects.read(snapshot.raw_path), response.body)
        self.assertEqual(h.fetch_count, 1)

    def test_promotion_metadata_must_match_exact_original_receipt(self):
        for field, value in (('received_at', '2026-10-06T01:00:00+00:00'),
                             ('validators', {'ETag': 'invented validator'})):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                h = collection_harness(Path(directory), [valid_idx_response('daily')])
                self.addCleanup(h.close)
                h.fail_at('after_promotion_receipt')
                with self.assertRaises(CollectionCrash):
                    h.collect(self.workset)
                row = tuple(h.store.scan('PromotionReceipt', {}))[0]
                modified = row.to_mapping()['value']
                modified['snapshot'][field] = value
                h.store.replace('PromotionReceipt', modified['checkpoint_id'], modified, row.version)
                h.forbid_fetch = True
                result = h.collect(self.workset)
                self.assertEqual(result.outcome, 'state_conflict')
                self.assertIsNone(result.snapshot_workset_ref)
                self.assertIsNone(h.source_state.binding(self.workset.workset_id, self.source.source_id))
                self.assertEqual(h.fetch_count, 1)

    def test_process_exit_preserves_first_pin_and_fetches_only_unresolved_member(self):
        sources = tuple(sorted((self.source, fixture_source(kind='daily', period='2026-10-02')),
                               key=lambda source: source.source_id))
        workset = fixture_workset(sources)
        h = self.harness([])
        h.objects.put_once(h.source_workset_path(workset), encode_workset(workset))
        (self.root / 'input-workset.json').write_bytes(encode_workset(workset))
        crash = run_collection_process(self.root, 'after_binding')
        self.assertEqual(crash['exit_code'], 73, crash)
        self.assertEqual(crash['stderr'], '')
        pin = h.source_state.binding(workset.workset_id, sources[0].source_id)
        self.assertIsNotNone(pin)
        self.assertIsNone(h.source_state.binding(workset.workset_id, sources[1].source_id))
        recovery = run_collection_process(self.root)
        self.assertEqual(recovery['exit_code'], 0, recovery)
        result = json.loads((self.root / 'final-result.json').read_bytes())
        self.assertEqual((result['outcome'], result['downloaded'], result['unchanged'], result['pending']),
                         ('success', 1, 1, 0))
        self.assertEqual(h.source_state.binding(workset.workset_id, sources[0].source_id), pin)
        events = [json.loads(line) for line in (self.root / 'collection-events.jsonl').read_text().splitlines()]
        self.assertEqual([event['url'] for event in events if event['event'] == 'fetch'],
                         [source.canonical_url for source in sources])
        snapshot_bytes = (self.root / 'final-snapshot-workset.json').read_bytes()
        repeated = run_collection_process(self.root, raw_only=True)
        self.assertEqual(repeated['exit_code'], 0, repeated)
        self.assertEqual((self.root / 'final-snapshot-workset.json').read_bytes(), snapshot_bytes)
        retain_collection_proof('two-source-process-resume', {'crash': crash, 'recovery': recovery,
            'repeated': repeated, 'events': events, 'result': result, 'snapshot_workset_bytes': snapshot_bytes.decode()})

    def test_each_durable_boundary_forced_process_exit_recovers_without_sender(self):
        for point in CRASH_POINTS:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                h = collection_harness(root, [])
                h.objects.put_once(h.source_workset_path(self.workset), encode_workset(self.workset))
                h.close()
                (root / 'input-workset.json').write_bytes(encode_workset(self.workset))
                crash = run_collection_process(root, point)
                self.assertEqual(crash['exit_code'], 73, crash)
                self.assertEqual(crash['stderr'], '')
                crashed_events = [json.loads(line) for line in (root / 'collection-events.jsonl').read_text().splitlines()]
                checkpoint = next(event for event in crashed_events if event['event'] == 'forced_exit')
                self.assertEqual(checkpoint['fetch_count'], 1)
                self.assertEqual(len(checkpoint['staged_receipts']), 1)
                self.assertEqual(len(checkpoint['promotions']), int(CRASH_POINTS.index(point) >= 2))
                self.assertEqual(len(checkpoint['snapshots']), int(CRASH_POINTS.index(point) >= 3))
                self.assertEqual(len(checkpoint['bindings']), int(CRASH_POINTS.index(point) >= 4))
                self.assertEqual(checkpoint['raw'][0]['verified'], point != 'after_receipt_checkpoint')
                before = checkpoint['snapshot_workset_bytes']
                if point == 'after_raw_promotion':
                    # Remove every retained staging byte: only the exact receipt + raw can recover.
                    for path in (root / 'objects/staging').rglob('body'):
                        path.unlink()
                recovered = run_collection_process(root, raw_only=True)
                self.assertEqual(recovered['exit_code'], 0, recovered)
                self.assertEqual(recovered['stderr'], '')
                result = json.loads((root / 'final-result.json').read_bytes())
                self.assertEqual(result['outcome'], 'success', result)
                completed_bytes = (root / 'final-snapshot-workset.json').read_bytes()
                snapshot = decode_snapshot_workset(completed_bytes).snapshots[0]
                self.assertEqual(snapshot.sha256, hashlib.sha256(valid_idx_response('daily').body).hexdigest())
                self.assertEqual((root / 'objects' / snapshot.raw_path).read_bytes(), valid_idx_response('daily').body)
                if before is not None:
                    self.assertEqual(completed_bytes.decode(), before)
                repeated = run_collection_process(root, raw_only=True)
                self.assertEqual(repeated['exit_code'], 0, repeated)
                self.assertEqual((root / 'final-snapshot-workset.json').read_bytes(), completed_bytes)
                events = [json.loads(line) for line in (root / 'collection-events.jsonl').read_text().splitlines()]
                self.assertEqual(len([event for event in events if event['event'] == 'fetch']), 1)
                self.assertEqual(len({event['pid'] for event in events}), 3)
                retain_collection_proof('crash-'+point, {'crash': crash, 'recovered': recovered, 'repeated': repeated,
                    'events': events, 'snapshot_workset_bytes': completed_bytes.decode(), 'prior_snapshot_bytes': before})

    def test_retry_prefix_quarantine_precedes_every_success_crash_boundary(self):
        for point in CRASH_POINTS:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                h = collection_harness(root, [])
                h.objects.put_once(h.source_workset_path(self.workset), encode_workset(self.workset))
                h.close()
                (root / 'input-workset.json').write_bytes(encode_workset(self.workset))
                crash = run_collection_process(root, point, retry_prefix=True)
                recovered = run_collection_process(root, raw_only=True, retry_prefix=True)
                recovered_snapshot_bytes = (root / 'final-snapshot-workset.json').read_bytes()
                repeated = run_collection_process(root, raw_only=True, retry_prefix=True)
                events = [json.loads(line) for line in (root / 'collection-events.jsonl').read_text().splitlines()]
                checkpoint = next(event for event in events if event['event'] == 'forced_exit')
                before = checkpoint['retry_evidence'][0]
                body_path = root / 'objects' / before['path']
                sidecar_path = body_path.with_name('receipt.json')
                after = {'body_hex': body_path.read_bytes().hex() if body_path.exists() else None,
                         'sidecar_bytes': sidecar_path.read_text() if sidecar_path.exists() else None,
                         'old_temporary_exists': Path(before['request']['receipt']['temporary_path']).exists()}
                result = json.loads((root / 'final-result.json').read_bytes())
                snapshot_bytes = (root / 'final-snapshot-workset.json').read_bytes()
                retain_collection_proof('retry-prefix-crash-'+point, {'crash': crash, 'recovered': recovered,
                    'repeated': repeated, 'events': events, 'after': after, 'result': result,
                    'recovered_snapshot_workset_bytes': recovered_snapshot_bytes.decode(),
                    'snapshot_workset_bytes': snapshot_bytes.decode()})
                self.assertEqual([process['exit_code'] for process in (crash, recovered, repeated)], [73, 0, 0])
                self.assertTrue(all(process[stream] == '' for process in (crash, recovered, repeated)
                                    for stream in ('stdout', 'stderr')))
                self.assertTrue(before['verified'], 'failed retry prefix must be durable before '+point)
                self.assertEqual(before['temporary_body_hex'], b'retained retry prefix'.hex())
                self.assertEqual(before['body_hex'], b'retained retry prefix'.hex())
                self.assertFalse(before['temporary_exists_after'])
                self.assertFalse(after['old_temporary_exists'])
                self.assertEqual(after['body_hex'], before['body_hex'])
                self.assertEqual(after['sidecar_bytes'], before['sidecar_bytes'])
                request = before['request']
                metadata = json.loads(after['sidecar_bytes'])
                self.assertEqual(metadata['receipt'], request['receipt'])
                self.assertEqual(metadata['error'], request['error'])
                self.assertEqual(metadata['context'], request['context'])
                self.assertEqual(metadata['request_id'], request['request_id'])
                self.assertEqual(request['permit']['request_id'], request['request_id'])
                self.assertEqual(metadata['body_path'], before['path'])
                self.assertEqual(metadata['receipt']['sha256'], hashlib.sha256(b'retained retry prefix').hexdigest())
                self.assertEqual(metadata['receipt']['headers'], {'X-Fixture': 'partial'})
                self.assertEqual((metadata['receipt']['byte_count'], metadata['receipt']['complete']), (21, False))
                self.assertEqual((result['outcome'], result['downloaded'], result['unchanged'], result['pending'],
                                  result['failed'], result['quarantined']), ('success', 0, 1, 0, 0, 0))
                self.assertEqual(result['gaps'], [])
                self.assertEqual((result['context']['run_id'], result['context']['execution_id'],
                                  result['context']['attempt_id']),
                                 ('successor-run', 'successor-execution', 'successor-attempt'))
                fetches = [event for event in events if event['event'] == 'fetch']
                self.assertEqual(len(fetches), 2)
                self.assertEqual({event['pid'] for event in fetches}, {checkpoint['pid']})
                self.assertEqual(len({event['pid'] for event in events}), 3)
                self.assertEqual(snapshot_bytes, recovered_snapshot_bytes)
                snapshot = decode_snapshot_workset(snapshot_bytes)
                self.assertEqual(snapshot.context, self.workset.context)
                self.assertEqual(snapshot.snapshots[0].sha256, hashlib.sha256(valid_idx_response('daily').body).hexdigest())
                self.assertEqual((root / 'objects' / snapshot.snapshots[0].raw_path).read_bytes(), valid_idx_response('daily').body)
                if checkpoint['snapshot_workset_bytes'] is not None:
                    self.assertEqual(snapshot_bytes.decode(), checkpoint['snapshot_workset_bytes'])

    def test_multiple_failed_prefixes_remain_distinct_when_recovered(self):
        from sec_edgar_ingest.download import ResponseSpec
        prefixes = (ResponseSpec(200, b'retained first prefix', {'X-Fixture': 'first'}, 'read_timeout'),
                    ResponseSpec(503, b'retained second prefix', {'X-Fixture': 'second'}))
        h = self.harness([*prefixes, valid_idx_response('daily')])
        h.fail_at('after_receipt_checkpoint')
        with self.assertRaises(CollectionCrash):
            h.collect(self.workset)
        original = h.source_state.active_context
        rows = h.source_state.request_history(original, self.source.canonical_url)
        self.assertEqual([row.value['outcome'] for row in rows], ['retry', 'retry', 'received'])
        retained = []
        for row, response in zip(rows, prefixes):
            request = row.to_mapping()['value']
            path = f'quarantine/sec/{original.run_id}/{self.source.source_id}/{original.attempt_id}/{request["request_id"]}/body'
            self.assertTrue((h.objects.directory / path).is_file(), 'each failed prefix must precede the success checkpoint')
            body = h.objects.read(path)
            sidecar = h.objects.read(path.rsplit('/', 1)[0]+'/receipt.json')
            self.assertEqual(body, response.body)
            self.assertEqual(json.loads(sidecar)['receipt']['headers'], response.headers)
            retained.append((path, body, sidecar))
            Path(request['receipt']['temporary_path']).unlink()
        self.assertNotEqual(retained[0][0], retained[1][0])
        h.forbid_fetch = True
        resumed = h.reopen()
        self.addCleanup(resumed.close)
        result = resumed.collect(self.workset)
        self.assertEqual((result.outcome, result.downloaded, result.unchanged, result.quarantined), ('success', 0, 1, 0))
        self.assertEqual(resumed.fetch_count, 3)
        for path, body, sidecar in retained:
            self.assertEqual(resumed.objects.read(path), body)
            self.assertEqual(resumed.objects.read(path.rsplit('/', 1)[0]+'/receipt.json'), sidecar)

    def test_recovery_verifies_original_quarantine_without_failed_spool(self):
        from sec_edgar_ingest.download import ResponseSpec
        from sec_edgar_ingest.models import canonical_json
        for corruption in ('body', 'sidecar', 'missing'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as directory:
                h = collection_harness(Path(directory), [ResponseSpec(200, b'retained retry prefix',
                    {'X-Fixture': 'partial'}, 'read_timeout'), valid_idx_response('daily')])
                self.addCleanup(h.close)
                h.fail_at('after_receipt_checkpoint')
                with self.assertRaises(CollectionCrash):
                    h.collect(self.workset)
                original = h.source_state.active_context
                request = h.source_state.request_history(original, self.source.canonical_url)[0].to_mapping()['value']
                path = f'quarantine/sec/{original.run_id}/{self.source.source_id}/{original.attempt_id}/{request["request_id"]}/body'
                # Install exact audited fixture evidence so this refusal test is independent of retention ordering.
                h.objects.stage(path, Path(request['receipt']['temporary_path']))
                h.objects.put_once(path.rsplit('/', 1)[0]+'/receipt.json', canonical_json({
                    'receipt': request['receipt'], 'error': request['error'], 'context': original.to_mapping(),
                    'source': self.source.to_mapping(), 'request_id': request['request_id'], 'body_path': path}))
                Path(request['receipt']['temporary_path']).unlink()
                retained = h.objects.directory / path
                target = retained.with_name('receipt.json') if corruption == 'sidecar' else retained
                target.unlink() if corruption == 'missing' else target.write_bytes(b'damaged quarantine')
                current = replace(original, run_id='successor-run', execution_id='successor-execution',
                                  attempt_id='successor-attempt')
                h.forbid_fetch = True
                result = self.collection.collect(self.workset, current, h.settings, h.client,
                                                 h.source_state, h.objects, h.faults)
                self.assertEqual(result.outcome, 'state_conflict')
                self.assertIsNone(result.snapshot_workset_ref)
                self.assertEqual(h.fetch_count, 2)
                self.assertEqual(h.source_state.request_history(current, self.source.canonical_url), ())
                self.assertIsNone(h.source_state.binding(self.workset.workset_id, self.source.source_id))
                if corruption != 'missing':
                    self.assertEqual(target.read_bytes(), b'damaged quarantine')

    def test_two_independent_collectors_race_changed_originals_and_adopt_one_pin(self):
        h = self.harness([])
        h.objects.put_once(h.source_workset_path(self.workset), encode_workset(self.workset))
        (self.root / 'input-workset.json').write_bytes(encode_workset(self.workset))
        spawn = multiprocessing.get_context('spawn')
        staged_barrier, binding_barrier, output = spawn.Barrier(2), spawn.Barrier(2), spawn.Queue()
        processes = [spawn.Process(target=collection_race_entry,
            args=(str(self.root), name, staged_barrier, binding_barrier, output)) for name in ('Original One', 'Original Two')]
        for process in processes:
            process.start()
        try:
            results = [output.get(timeout=40) for _ in processes]
        finally:
            for process in processes:
                process.join(timeout=20)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        self.assertEqual([process.exitcode for process in processes], [0, 0])
        ordered = sorted((event for result in results for event in result['events']), key=lambda event: event['monotonic_ns'])
        retain_collection_proof('changed-original-bind-race', {'results': results, 'ordered_events': ordered,
            'exit_codes': [p.exitcode for p in processes]})
        self.assertEqual(len({result['candidate_sha256'] for result in results}), 2)
        self.assertEqual({result['result']['outcome'] for result in results}, {'success'})
        self.assertEqual(len({result['result']['snapshot_workset_ref'] for result in results}), 1)
        events = [event for result in results for event in result['events']]
        self.assertEqual(len([event for event in events if event['event'] == 'bind_insert_attempt']), 2)
        self.assertEqual(len([event for event in events if event['event'] == 'bind_insert_success']), 1)
        self.assertEqual(len([event for event in events if event['event'] == 'bind_insert_conflict']), 1)
        absent = [event for event in events if event['event'] == 'bind_read_absent']
        attempts = [event for event in events if event['event'] == 'bind_insert_attempt']
        self.assertEqual(len(absent), 2)
        self.assertLess(max(event['monotonic_ns'] for event in absent), min(event['monotonic_ns'] for event in attempts))
        self.assertEqual({event['pid'] for event in attempts}, {process.pid for process in processes})
        winners = [event['snapshots'][0]['sha256'] for event in events if event['event'] == 'adopted']
        self.assertEqual(winners[0], winners[1])
        self.assertEqual(h.source_state.binding(self.workset.workset_id, self.source.source_id).snapshot_sha256, winners[0])
        for result in results:
            path = self.collection.raw_path(self.source, result['candidate_sha256'])
            self.assertTrue((h.objects.directory / path).is_file())
        self.assertEqual(h.fetch_count, 2)
