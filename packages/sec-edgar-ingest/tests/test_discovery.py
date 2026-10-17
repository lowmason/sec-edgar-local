"""Offline trusted listing discovery and durable recovery contracts."""
import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from support import discovery_harness, failed_response, fixture_source, listing_response, retained_path


class DiscoveryTests(unittest.TestCase):
    def harness(self, responses, root=None):
        result = discovery_harness(root, responses)
        self.addCleanup(result.close)
        return result

    def test_later_success_cannot_cross_a_failed_directory(self):
        h = self.harness({'2026Q2': [failed_response(503)],
                          '2026Q3': [listing_response('2026Q3', ['master.20260930.idx'])],
                          '2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
        h.seed_boundary(date(2026, 3, 31))
        workset = h.run('daily', date(2026, 10, 6), 'outage-a')
        self.assertFalse(workset.discovery_complete)
        self.assertEqual(h.boundary, date(2026, 3, 31))
        self.assertTrue(any(d.outcome == 'discovery_failed' for d in workset.directories))
        self.assertIn('2026Q2', h.requested_quarters)

    def test_valid_empty_listing_has_a_distinct_outcome(self):
        h = self.harness({'2026Q4': [listing_response('2026Q4', [])]})
        workset = h.run_single_directory('2026Q4')
        self.assertTrue(workset.discovery_complete)
        self.assertEqual(workset.members, ())
        leaf = next(d for d in workset.directories if d.period == '2026Q4')
        self.assertEqual(leaf.outcome, 'no_new_sources')
        self.assertEqual(leaf.listing_sha256, hashlib.sha256(listing_response('2026Q4', []).body).hexdigest())

    def test_first_daily_run_replays_handoff_and_preceding_quarter(self):
        h = self.harness({})
        workset = h.run('daily', date(2026, 10, 6), 'first')
        self.assertEqual(h.requested_quarters, ('2026Q3', '2026Q4'))
        self.assertEqual(workset.overlap_from, date(2026, 7, 1))
        self.assertEqual(h.boundary, date(2026, 10, 6))

    def test_pending_old_source_is_revisited_without_handoff_filter(self):
        old = fixture_source('2015-01-02', 'daily')
        h = self.harness({'2015Q1': [listing_response('2015Q1', ['master.20150102.idx'])]})
        h.add_pending(old)
        workset = h.run('daily', date(2026, 10, 6), 'pending')
        self.assertIn('2015Q1', h.requested_quarters)
        self.assertIn(old, workset.members)

    def test_multi_quarter_outage_includes_entire_boundary_range(self):
        h = self.harness({'2026Q1': [failed_response(503)], '2026Q2': [failed_response(503)]})
        h.seed_boundary(date(2025, 12, 31))
        workset = h.run('daily', date(2026, 10, 6), 'long-outage')
        self.assertEqual(h.requested_quarters, ('2025Q4', '2026Q1', '2026Q2', '2026Q3', '2026Q4'))
        self.assertFalse(workset.discovery_complete)
        self.assertEqual(h.boundary, date(2025, 12, 31))

    def test_failed_ancestor_never_constructs_child_requests(self):
        h = self.harness({'daily-index': [failed_response(503)]})
        workset = h.run('daily', date(2026, 10, 6), 'ancestor')
        self.assertFalse(workset.discovery_complete)
        self.assertEqual(set(h.attempted_urls), {h.url('daily-index')})
        self.assertIsNone(h.boundary)

    def test_missing_requested_quarter_is_gap_not_empty_child(self):
        h = self.harness({'2026': [listing_response('2026', ['QTR3/'])]})
        workset = h.run('daily', date(2026, 10, 6), 'missing')
        self.assertFalse(workset.discovery_complete)
        leaf = next(d for d in workset.directories if d.period == '2026Q4')
        self.assertEqual(leaf.error.code, 'missing_directory')
        self.assertNotIn(h.url('2026Q4'), h.attempted_urls)
        self.assertIsNone(leaf.listing_sha256)

    def test_malformed_untrusted_and_unsupported_listing_remain_gaps(self):
        from sec_edgar_ingest.download import ResponseSpec
        for body in (b'<html>untrusted</html>', b'<directory/>', b'{',
                     listing_response('2026Q4', ['master.gz']).body,
                     listing_response('2026Q4', ['master.20261001.idx.gz']).body):
            with self.subTest(body=body[:70]):
                h = self.harness({'2026Q4': [ResponseSpec(200, body, {})]})
                workset = h.run_single_directory('2026Q4')
                leaf = next(d for d in workset.directories if d.period == '2026Q4')
                self.assertFalse(workset.discovery_complete)
                self.assertEqual(leaf.outcome, 'discovery_failed')
                self.assertIsNone(leaf.listing_sha256)
                self.assertEqual(leaf.source_ids, ())
                self.assertIn('evidence', leaf.error.details)

    def test_supported_representation_retains_ignored_codec_reason(self):
        h = self.harness({'2026Q4': [listing_response('2026Q4', ['master.20261001.idx', 'master.20261001.idx.gz'])]})
        workset = h.run_single_directory('2026Q4')
        self.assertTrue(workset.discovery_complete)
        self.assertEqual(len(workset.members), 1)
        progress = h.state.directory_progress(workset.discovery_id, h.url('2026Q4'))
        self.assertTrue(progress.value['selection']['ignored'])

    def test_delayed_file_requires_fresh_session_and_old_bytes_stay_immutable(self):
        h = self.harness({'2026Q4': [listing_response('2026Q4', []),
                          listing_response('2026Q4', ['master.20261001.idx'])]})
        first = h.run('daily', date(2026, 10, 6), 'late-first')
        first_bytes = h.objects.read(h.workset_path(first))
        before = len(h.attempted_urls)
        same = h.run('daily', date(2026, 10, 6), 'late-first')
        self.assertEqual(same, first)
        self.assertEqual(len(h.attempted_urls), before)
        fresh = h.run('daily', date(2026, 10, 6), 'late-fresh')
        self.assertEqual(len(fresh.members), 1)
        self.assertNotEqual(fresh.workset_id, first.workset_id)
        self.assertEqual(h.objects.read(h.workset_path(first)), first_bytes)

    def test_restart_reuses_verified_success_and_retries_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            h = self.harness({'2026Q3': [listing_response('2026Q3', ['master.20260930.idx'])],
                              '2026Q4': [failed_response(503)]}, root)
            old = h.run('daily', date(2026, 10, 6), 'resume')
            old_bytes = h.objects.read(h.workset_path(old))
            old_sha = next(d.listing_sha256 for d in old.directories if d.period == '2026Q3')
            h.close()
            resumed = self.harness({'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]}, root)
            final = resumed.run('daily', date(2026, 10, 7), 'resume')
            self.assertTrue(final.discovery_complete)
            self.assertNotEqual(final.workset_id, old.workset_id)
            self.assertEqual(final.context, old.context)
            self.assertEqual(next(d.listing_sha256 for d in final.directories if d.period == '2026Q3'), old_sha)
            self.assertEqual(resumed.objects.read(resumed.workset_path(old)), old_bytes)
            self.assertNotIn(resumed.url('2026Q3'), resumed.attempted_urls)
            checkpoint = resumed.state.discovery_session('resume').value
            self.assertEqual(checkpoint['predecessor_workset_id'], old.workset_id)
            self.assertEqual(checkpoint['workset_id'], final.workset_id)
            self.assertEqual(resumed.boundary, date(2026, 10, 6))

    def test_same_session_refuses_changed_refresh_or_configuration(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        h = self.harness({})
        h.run('daily', date(2026, 10, 6), 'frozen')
        with self.assertRaises(Conflict):
            h.run('daily', date(2026, 10, 6), 'frozen', refresh=True)

    def test_absence_does_not_erase_pending_or_accepted_snapshot(self):
        from support import fixture_snapshot
        source = fixture_source('2015-01-02', 'daily')
        h = self.harness({})
        h.add_pending(source)
        snapshot = fixture_snapshot(source, b'previously accepted fixture')
        h.state.remember_snapshot(snapshot)
        from sec_edgar_ingest.models import Error
        h.state.record_failure(source, Error('retry', 'fixture pending', True, source.source_id, {}))
        h.run('daily', date(2026, 10, 6), 'absent')
        row = h.state.get_source(source.source_id).value
        self.assertEqual(row['latest_downloaded_snapshot'], snapshot.sha256)
        self.assertTrue(row['needs_acquisition'])
        self.assertIn('2015Q1', h.requested_quarters)

    def test_boundary_rejects_unbacked_future_candidate(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        h = self.harness({})
        workset = h.run('daily', date(2026, 10, 6), 'exact-day')
        with self.assertRaises(Conflict):
            h.state.advance_boundary(date(2026, 10, 7), 'exact-day', workset.directories)
        self.assertEqual(h.boundary, date(2026, 10, 6))

    def test_success_progress_crash_resumes_gap_resolution_without_refetch(self):
        h = self.harness({})
        original = h.store.insert
        crashed = []
        def interrupted(kind, key, value):
            result = original(kind, key, value)
            if kind == 'DirectoryProgress' and not crashed:
                crashed.append(True)
                raise RuntimeError('fixture crash after durable successful progress')
            return result
        h.store.insert = interrupted
        with self.assertRaisesRegex(RuntimeError, 'fixture crash'):
            h.run('daily', date(2026, 10, 6), 'progress-crash')
        h.store.insert = original
        root_before = h.attempted_urls.count(h.url('daily-index'))
        workset = h.run('daily', date(2026, 10, 6), 'progress-crash')
        self.assertTrue(workset.discovery_complete)
        self.assertEqual(h.attempted_urls.count(h.url('daily-index')), root_before)
        self.assertEqual(h.boundary, date(2026, 10, 6))
        self.assertEqual(h.state.failed_directories(), ())

    def test_concurrent_boundary_cas_cannot_erase_older_unrelated_gap(self):
        from sec_edgar_ingest.models import DirectoryOutcome, Error
        from sec_edgar_ingest.state import AcquisitionState
        from sec_edgar_ingest.storage.local import LocalStateStore
        h = self.harness({})
        h.seed_boundary(date(2026, 10, 5))
        sibling_store = LocalStateStore(h.root, page_size=1)
        self.addCleanup(sibling_store.close)
        sibling = AcquisitionState(sibling_store, clock=h.clock)
        missing = DirectoryOutcome(h.url('2015Q1'), '2015Q1', 'discovery_failed', None, (),
                                   Error('listing_outage', 'older required gap', True, None, {}))
        original = h.store.replace
        injected = []
        def race(kind, key, value, version):
            if kind == 'DiscoveryBoundary' and value['day'] == '2026-10-06' and not injected:
                injected.append(True)
                sibling.record_directory('older-outage', missing, ())
            return original(kind, key, value, version)
        h.store.replace = race
        workset = h.run('daily', date(2026, 10, 6), 'boundary-race')
        self.assertTrue(workset.discovery_complete)
        self.assertTrue(injected)
        self.assertEqual(h.boundary, date(2026, 10, 5))
        self.assertIn(missing, h.state.failed_directories())

    def test_cached_old_listing_cannot_resolve_newer_same_url_gap(self):
        from sec_edgar_ingest.models import DirectoryOutcome, Error
        h = self.harness({})
        workset = h.run('daily', date(2026, 10, 6), 'cached-old')
        outage = DirectoryOutcome(h.url('2026Q3'), '2026Q3', 'discovery_failed', None, (),
                                  Error('listing_outage', 'newer failed reread', True, None, {}))
        h.state.record_directory('newer-outage', outage, ())
        h.run('daily', date(2026, 10, 6), 'cached-old')
        self.assertIn(outage, h.state.failed_directories())
        self.assertEqual(h.state.directory_progress('cached-old', outage.url).value['outcome']['listing_sha256'],
                         next(d.listing_sha256 for d in workset.directories if d.url == outage.url))

    def test_successful_receipt_and_exact_bytes_precede_progress_and_are_verified(self):
        from sec_edgar_ingest.models import parse_json
        from sec_edgar_ingest.storage.contracts import Conflict
        h = self.harness({'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
        original = h.store.insert
        verified = []
        def verify_at_insert(kind, key, value):
            if kind == 'DirectoryProgress' and value['outcome']['outcome'] != 'discovery_failed':
                evidence = value['evidence']
                raw = h.objects.read(evidence['body_path'])
                metadata = parse_json(h.objects.read(evidence['receipt_path']))
                self.assertEqual(hashlib.sha256(raw).hexdigest(), value['outcome']['listing_sha256'])
                self.assertEqual(metadata['receipt']['sha256'], value['outcome']['listing_sha256'])
                verified.append(value['outcome']['url'])
            return original(kind, key, value)
        h.store.insert = verify_at_insert
        workset = h.run('daily', date(2026, 10, 6), 'durable')
        self.assertEqual(set(verified), {outcome.url for outcome in workset.directories})
        progress = h.state.directory_progress('durable', h.url('2026Q4')).value
        (h.objects.directory/progress['evidence']['body_path']).write_bytes(b'corrupted fixture support')
        before = len(h.attempted_urls)
        with self.assertRaises(Conflict):
            h.run('daily', date(2026, 10, 6), 'durable')
        self.assertEqual(len(h.attempted_urls), before)

    def test_quarterly_uses_actual_master_zip_and_records_open_bridge_alternative(self):
        from support import fixture_settings
        h = self.harness({'full-index': [listing_response('full-index', ['2026/', 'master.zip', 'master.gz'])],
                          '2026Q3': [listing_response('2026Q3', ['master.zip', 'master.gz'], family='full-index')],
                          '2026Q4': [listing_response('2026Q4', ['master.zip'], family='full-index')]})
        h.settings = fixture_settings(backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
                              fixture={'allow_clock_override': True})
        h.coordinator.settings = h.settings
        h.client.settings = h.settings
        workset = h.run('quarterly', date(2026, 10, 6), 'quarterly')
        self.assertTrue(workset.discovery_complete)
        self.assertEqual({source.period for source in workset.members}, {'2026Q3', '2026Q4'})
        self.assertEqual({source.representation for source in workset.members}, {'zip'})
        root = h.state.directory_progress('quarterly', h.url('full-index')).value
        self.assertIn('alternative', root['selection'])
        self.assertEqual(tuple(entry['name'] for entry in root['selection']['ignored']), ('master.gz',))
        self.assertEqual(root['outcome']['source_ids'], ())
        self.assertIsNone(h.boundary)

    def test_refresh_is_frozen_in_immutable_workset(self):
        from sec_edgar_ingest.worksets import decode_source_workset
        h = self.harness({})
        result = h.run('daily', date(2026, 10, 6), 'refresh', refresh=True)
        self.assertEqual(result.acquisition_mode, 'refresh')
        self.assertEqual(decode_source_workset(h.objects.read(h.workset_path(result))), result)

    def test_source_workset_uses_approved_path_with_independent_digest_identity(self):
        from sec_edgar_ingest.models import canonical_json
        from sec_edgar_ingest.worksets import decode_source_workset, encode_workset
        h = self.harness({'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
        result = h.run('daily', date(2026, 10, 6), 'approved-source-path')
        path = f'worksets/sec/source/sha256={result.workset_id}/workset.json'
        self.assertTrue((h.objects.directory/path).is_file(), path)
        body = h.objects.read(path)
        payload = json.loads(body)
        identity = payload.pop('workset_id')
        self.assertEqual(hashlib.sha256(canonical_json(payload)).hexdigest(), identity)
        self.assertEqual(identity, result.workset_id)
        self.assertEqual(decode_source_workset(body), result)
        self.assertEqual(body, encode_workset(result))

    def test_historical_closed_quarter_does_not_register_root_bridge_as_coverage(self):
        from support import fixture_settings
        h = self.harness({'full-index': [listing_response('full-index', ['2015/', 'master.zip'])],
                          '2015Q1': [listing_response('2015Q1', ['master.zip'], family='full-index')]})
        h.settings = fixture_settings(backfill={'start_quarter': '2015Q1', 'end_quarter': '2015Q1'},
                                      fixture={'allow_clock_override': True})
        h.coordinator.settings = h.client.settings = h.settings
        workset = h.run('quarterly', date(2026, 10, 6), 'historical')
        self.assertEqual(len(workset.members), 1)
        root = h.state.directory_progress('historical', h.url('full-index')).value
        self.assertNotIn('alternative', root['selection'])

    def test_unresolved_old_year_unit_is_revisited_even_without_sources(self):
        from sec_edgar_ingest.models import DirectoryOutcome, Error
        h = self.harness({})
        old_url = h.url('2015')
        gap = DirectoryOutcome(old_url, '2015', 'discovery_failed', None, (),
                               Error('year_outage', 'older failed year unit', True, None, {}))
        h.state.record_directory('older-year', gap, ())
        workset = h.run('daily', date(2026, 10, 6), 'year-recovery')
        self.assertIn(old_url, h.attempted_urls)
        self.assertIn(old_url, {d.url for d in workset.directories})
        self.assertEqual(h.state.failed_directories(), ())
        self.assertEqual(h.boundary, date(2026, 10, 6))

    def test_completed_sessions_do_not_accumulate_in_shared_boundary_row(self):
        from sec_edgar_ingest.models import canonical_json
        h = self.harness({})
        h.run('daily', date(2026, 10, 6), 'bounded-0')
        baseline = len(canonical_json(h.store.get('DiscoveryBoundary', 'daily').to_mapping()['value']))
        for ordinal in range(1, 8):
            h.run('daily', date(2026, 10, 6), f'bounded-{ordinal}')
        final = len(canonical_json(h.store.get('DiscoveryBoundary', 'daily').to_mapping()['value']))
        self.assertLessEqual(final, baseline + 100)

    def test_pending_sources_are_paginated_and_old_failed_quarter_is_also_retried(self):
        from sec_edgar_ingest.models import DirectoryOutcome, Error
        h = self.harness({})
        h.store.page_size = 1
        for day in ('2015-01-02', '2016-05-04', '2017-09-01'):
            h.add_pending(fixture_source(day, 'daily'))
        old = DirectoryOutcome(h.url('2014Q2'), '2014Q2', 'discovery_failed', None, (),
                               Error('old_outage', 'failed listing before handoff', True, None, {}))
        h.state.record_directory('older-quarter', old, ())
        workset = h.run('daily', date(2026, 10, 6), 'paged')
        self.assertTrue(workset.discovery_complete)
        for quarter in ('2014Q2', '2015Q1', '2016Q2', '2017Q3'):
            self.assertIn(quarter, h.requested_quarters)
        self.assertEqual(h.state.failed_directories(), ())

    def test_named_synthetic_fixtures_are_used_separately_from_retained_evidence(self):
        from sec_edgar_ingest.discovery import parse_listing
        from sec_edgar_ingest.download import ResponseSpec
        directory = Path(__file__).parent/'fixtures/listings'
        empty = (directory/'empty.json').read_bytes()
        self.assertEqual(parse_listing('https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/index.json', empty), ())
        for name in ('malformed.json', 'unsafe.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_listing('https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/index.json', (directory/name).read_bytes())
        for name, period in (('leap-day.json', '2024Q1'), ('late-daily.json', '2026Q4')):
            h = self.harness({period: [ResponseSpec(200, (directory/name).read_bytes(), {})]})
            result = h.run_single_directory(period)
            self.assertTrue(result.discovery_complete)
            self.assertEqual(len(result.members), 1)

    def test_denial_and_owner_policy_latch_remain_terminal_directory_gaps(self):
        from sec_edgar_ingest.download import ResponseSpec
        h = self.harness({'daily-index': [failed_response(403)]})
        result = h.run('daily', date(2026, 10, 6), 'denied')
        self.assertFalse(result.discovery_complete)
        self.assertEqual(len(h.attempted_urls), 1)
        self.assertTrue(any(d.error and d.error.code == 'access_denied' for d in result.directories))
        blocked = self.harness({'daily-index': [ResponseSpec(429, b'synthetic retry delay', {'Retry-After': '1000000000000'})]})
        first = blocked.run('daily', date(2026, 10, 6), 'latched')
        second = blocked.run('daily', date(2026, 10, 6), 'latched-next')
        self.assertFalse(first.discovery_complete or second.discovery_complete)
        self.assertEqual(len(blocked.attempted_urls), 1)
        self.assertTrue(any(d.error and d.error.code == 'policy_blocked' for d in second.directories))
        self.assertIsNone(blocked.boundary)

    def test_boundary_requires_exact_complete_durable_outcome_set(self):
        from sec_edgar_ingest.models import DirectoryOutcome
        from sec_edgar_ingest.storage.contracts import Conflict
        h = self.harness({})
        result = h.run('daily', date(2026, 10, 6), 'proof-set')
        with self.assertRaises(Conflict):
            h.state.advance_boundary(date(2026, 10, 6), 'proof-set', result.directories[:-1])
        changed = result.directories[0].to_mapping(); changed['listing_sha256'] = 'b' * 64
        supplied = (DirectoryOutcome.from_mapping(changed),) + result.directories[1:]
        with self.assertRaises(Conflict):
            h.state.advance_boundary(date(2026, 10, 6), 'proof-set', supplied)

    def test_discovery_requests_share_one_budget_and_preserve_actual_child_membership(self):
        h = self.harness({'2026Q3': [listing_response('2026Q3', ['master.20260930.idx'])],
                          '2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
        result = h.run('daily', date(2026, 10, 6), 'budget')
        starts = h.sender.starts
        self.assertEqual(h.sender.maximum_active, 1)
        self.assertTrue(all(later - earlier >= 1/3 for earlier, later in zip(starts, starts[1:])))
        attempts = tuple(h.store.scan('TransportAttempt', {}))
        self.assertEqual(len(attempts), len(h.attempted_urls))
        self.assertTrue(all(row.value['source_id'] is None for row in attempts))
        directories = {d.url: d for d in result.directories}
        for source in result.members:
            directory_url = source.canonical_url.rsplit('/', 1)[0]+'/index.json'
            self.assertIn(source.source_id, directories[directory_url].source_ids)

    def test_listing_absence_and_truncation_preserve_original_failure_bytes(self):
        from sec_edgar_ingest.download import ResponseSpec
        for spec in (failed_response(404), ResponseSpec(200, b'{"directory":', {}, 'timeout')):
            with self.subTest(spec=spec):
                h = self.harness({'2026Q4': [spec]})
                result = h.run_single_directory('2026Q4')
                leaf = next(d for d in result.directories if d.period == '2026Q4')
                self.assertEqual(leaf.outcome, 'discovery_failed')
                self.assertEqual(leaf.source_ids, ())
                self.assertIsNone(leaf.listing_sha256)
                evidence = leaf.error.details['evidence']
                self.assertEqual(h.objects.read(evidence['body_path']), spec.body)
                self.assertTrue(evidence['body_path'].startswith('quarantine/discovery/'))

    def test_failed_year_and_missing_year_do_not_invent_quarter_fetches(self):
        for responses in ({'2026': [failed_response(503)]},
                          {'daily-index': [listing_response('daily-index', ['2015/'])]}):
            with self.subTest(responses=responses):
                h = self.harness(responses)
                result = h.run('daily', date(2026, 10, 6), 'hierarchy-gap')
                self.assertFalse(result.discovery_complete)
                self.assertEqual(h.requested_quarters, ())
                self.assertIsNone(h.boundary)

    def test_crash_before_receipt_metadata_write_cannot_record_successful_progress(self):
        from support import Faults
        h = self.harness({})
        faults, writes = Faults(), []
        def interrupt_second_link():
            writes.append(True)
            if len(writes) == 2:
                raise RuntimeError('fixture crash before receipt metadata link')
            faults.at('object.before_link', interrupt_second_link)
        faults.at('object.before_link', interrupt_second_link)
        h.objects.observer = faults
        with self.assertRaisesRegex(RuntimeError, 'metadata link'):
            h.run('daily', date(2026, 10, 6), 'receipt-crash')
        self.assertIsNone(h.state.directory_progress('receipt-crash', h.url('daily-index')))
        self.assertIsNone(h.boundary)
        result = h.run('daily', date(2026, 10, 6), 'receipt-crash')
        self.assertTrue(result.discovery_complete)
        self.assertEqual(h.attempted_urls.count(h.url('daily-index')), 2)

    def test_configuration_change_is_refused_on_same_discovery_session(self):
        from support import fixture_settings
        from sec_edgar_ingest.storage.contracts import Conflict
        h = self.harness({})
        h.run('daily', date(2026, 10, 6), 'config-frozen')
        before = len(h.attempted_urls)
        h.settings = fixture_settings(backfill={'start_quarter': '2026Q3'}, fixture={'allow_clock_override': True})
        h.coordinator.settings = h.client.settings = h.settings
        with self.assertRaises(Conflict):
            h.run('daily', date(2026, 10, 6), 'config-frozen')
        self.assertEqual(len(h.attempted_urls), before)

    def test_daily_endpoint_cannot_exclude_current_quarter_even_when_listings_are_empty(self):
        from support import fixture_settings
        h = self.harness({})
        h.settings = fixture_settings(backfill={'start_quarter': '2015Q1', 'end_quarter': '2015Q1'},
                                      fixture={'allow_clock_override': True})
        h.coordinator.settings = h.client.settings = h.settings
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            h.run('daily', date(2026, 10, 6), 'closed-daily')
        self.assertEqual(h.attempted_urls, [])

    def test_source_observation_uses_actual_successful_receipt_time(self):
        h = self.harness({'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
        result = h.run('daily', date(2026, 10, 6), 'observation-time')
        source = result.members[0]
        progress = h.state.directory_progress('observation-time', h.url('2026Q4')).value
        metadata = json.loads(h.objects.read(progress['evidence']['receipt_path']))
        self.assertEqual(h.state.get_source(source.source_id).value['first_discovered_at'],
                         metadata['receipt']['received_at'])

    def test_cached_progress_must_match_requested_directory_metadata(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        h = self.harness({})
        h.run('daily', date(2026, 10, 6), 'metadata-integrity')
        url = h.url('daily-index')
        row = h.state.directory_progress('metadata-integrity', url)
        value = row.to_mapping()['value']; value['outcome']['period'] = 'wrong-family'
        key = hashlib.sha256(json.dumps(['metadata-integrity', url], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        h.store.replace('DirectoryProgress', key, value, row.version)
        with self.assertRaises(Conflict):
            h.run('daily', date(2026, 10, 6), 'metadata-integrity')

    def test_cached_receipt_rejects_conflicting_or_invalid_transport_context(self):
        from sec_edgar_ingest.models import canonical_json
        from sec_edgar_ingest.storage.contracts import Conflict
        cases = (
            ('run_id', 'another-run'), ('command', 'collect'),
            ('config_sha256', 'b'*64), ('image_digest', 'sha256:'+'b'*64),
            ('parser_version', 'another-parser'), ('schema_version', 'sec-index-v2'),
            ('effective_config', {}), ('pinned_on', None),
            ('pinned_on', '2014-01-01'), (None, None),
        )
        for field, replacement in cases:
            with self.subTest(field=field, replacement=replacement):
                h = self.harness({})
                discovery_id = 'receipt-provenance'
                first = h.run('daily', date(2026, 10, 6), discovery_id)
                url = h.url('daily-index')
                row = h.state.directory_progress(discovery_id, url)
                value = row.to_mapping()['value']
                metadata = json.loads(h.objects.read(value['evidence']['receipt_path']))
                if field is None:
                    metadata['context'] = replacement
                else:
                    metadata['context'][field] = replacement
                changed = canonical_json(metadata)
                digest = hashlib.sha256(changed).hexdigest()
                path = f'worksets/discovery/listings/receipts/sha256={digest}.json'
                h.objects.put_once(path, changed)
                value['evidence'].update(receipt_path=path, receipt_sha256=digest, receipt_byte_count=len(changed))
                key = hashlib.sha256(canonical_json([discovery_id, url])).hexdigest()
                h.store.replace('DirectoryProgress', key, value, row.version)
                before = len(h.attempted_urls)
                with self.assertRaisesRegex(Conflict, 'receipt.*context|receipt.*provenance'):
                    h.run('daily', date(2026, 10, 7), discovery_id)
                self.assertEqual(len(h.attempted_urls), before)
                self.assertEqual(h.state.discovery_session(discovery_id).value['workset_id'], first.workset_id)
                self.assertEqual(h.boundary, date(2026, 10, 6))

    def test_cached_receipt_accepts_actual_resumed_execution_and_attempt_context(self):
        h = self.harness({'2026Q4': [failed_response(503)]})
        first = h.run('daily', date(2026, 10, 6), 'transport-resume')
        h.responses['2026Q4'] = [listing_response('2026Q4', ['master.20261001.idx'])]
        completed = h.run('daily', date(2026, 10, 7), 'transport-resume')
        value = h.state.directory_progress('transport-resume', h.url('2026Q4')).to_mapping()['value']
        transport = json.loads(h.objects.read(value['evidence']['receipt_path']))['context']
        self.assertNotEqual(transport['execution_id'], first.context.execution_id)
        self.assertNotEqual(transport['attempt_id'], first.context.attempt_id)
        self.assertEqual(transport['pinned_on'], '2026-10-07')
        before = len(h.attempted_urls)
        reopened = h.run('daily', date(2026, 10, 8), 'transport-resume')
        self.assertEqual(reopened, completed)
        self.assertEqual(completed.context, first.context)
        self.assertEqual(len(h.attempted_urls), before)

    def test_retained_root_year_and_quarter_select_exact_actual_zip_child(self):
        from support import fixture_settings
        from sec_edgar_ingest.download import ResponseSpec
        manifest = json.loads((Path(__file__).parent/'fixtures/retained-manifest.json').read_bytes())
        records = {item['path']: item for item in manifest['records']}
        for entry in manifest['provenance'].values():
            self.assertEqual(hashlib.sha256(retained_path(entry['path']).read_bytes()).hexdigest(), entry['sha256'])
        responses, hashes = {}, {}
        for number in (1, 2, 3):
            stem = f'specs/evidence/sec-filing-index-ingestion/stage-1/listings/SEC-{number:04d}'
            values = {}
            for suffix in ('body', 'headers.json', 'intent.json'):
                path = stem+'.'+suffix; body = retained_path(path).read_bytes()
                self.assertEqual(hashlib.sha256(body).hexdigest(), records[path]['sha256'])
                self.assertEqual(len(body), records[path]['bytes'])
                values[suffix] = body
            url = json.loads(values['intent.json'])['url']
            self.assertEqual(json.loads(values['headers.json'])['url'], url)
            responses[url] = [ResponseSpec(200, values['body'], {'X-Fixture': f'retained-original-SEC-{number:04d}'})]
            hashes[url] = records[stem+'.body']['sha256']
        h = self.harness(responses)
        h.settings = fixture_settings(backfill={'start_quarter': '2010Q1', 'end_quarter': '2010Q1'},
                                      fixture={'allow_clock_override': True})
        h.coordinator.settings = h.client.settings = h.settings
        result = h.run('quarterly', date(2026, 10, 6), 'retained-hierarchy')
        self.assertTrue(result.discovery_complete)
        self.assertEqual(len(result.members), 1)
        self.assertEqual(result.members[0].canonical_url,
                         'https://www.sec.gov/Archives/edgar/full-index/2010/QTR1/master.zip')
        self.assertEqual({d.url: d.listing_sha256 for d in result.directories}, hashes)


class ListingTests(unittest.TestCase):
    def test_retained_originals_parse_with_verified_manifest_provenance(self):
        from sec_edgar_ingest.discovery import parse_listing
        manifest = json.loads((Path(__file__).parent/'fixtures/retained-manifest.json').read_bytes())
        records = {item['path']: item for item in manifest['records']}
        for row in manifest['provenance'].values():
            self.assertEqual(hashlib.sha256(retained_path(row['path']).read_bytes()).hexdigest(), row['sha256'])
        for number in (1, 2, 3, 28, 85, 86, 87, 88, 89, 104, 135, 137, 138, 139):
            stem = f'specs/evidence/sec-filing-index-ingestion/stage-1/listings/SEC-{number:04d}'
            values = {}
            for suffix in ('body', 'headers.json', 'intent.json'):
                path = stem+'.'+suffix
                body = retained_path(path).read_bytes()
                self.assertEqual(hashlib.sha256(body).hexdigest(), records[path]['sha256'])
                self.assertEqual(len(body), records[path]['bytes'])
                values[suffix] = body
            headers = json.loads(values['headers.json'])
            intent = json.loads(values['intent.json'])
            self.assertEqual(intent['url'], headers['url'])
            self.assertEqual(headers['sha256'], records[stem+'.body']['sha256'])
            entries = parse_listing(intent['url'], values['body'])
            raw = json.loads(values['body'])['directory']['item']
            self.assertEqual(len(entries), len(raw))
            self.assertEqual({e.name: (e.size_label, e.modified_label) for e in entries},
                             {e['name']: (e['size'], e['last-modified']) for e in raw})

    def test_rejects_wrong_directory_duplicate_unsafe_missing_or_wrong_typed_fields(self):
        from sec_edgar_ingest.discovery import parse_listing
        url = 'https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/index.json'
        normal = json.loads(listing_response('2026Q4', ['master.20261001.idx']).body)
        cases = []
        for key, value in (('name', 'full-index/2026/QTR4/'), ('item', {}), ('parent-dir', None)):
            changed = json.loads(json.dumps(normal)); changed['directory'][key] = value; cases.append(changed)
        for key, value in (('href', '../master.20261001.idx'), ('name', '../master.idx'), ('type', 'unknown'), ('size', 42)):
            changed = json.loads(json.dumps(normal)); changed['directory']['item'][0][key] = value; cases.append(changed)
        changed = json.loads(json.dumps(normal)); changed['directory']['item'].append(dict(changed['directory']['item'][0])); cases.append(changed)
        changed = json.loads(json.dumps(normal)); del changed['directory']['item'][0]['href']; cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                parse_listing(url, json.dumps(changed).encode())

    def test_filename_calendar_and_hierarchy_validation_including_leap_day(self):
        h = discovery_harness(None, {'2024Q1': [listing_response('2024Q1', ['master.20240229.idx'])]})
        self.addCleanup(h.close)
        self.assertEqual(h.run_single_directory('2024Q1').members[0].period, '2024-02-29')
        for name in ('master.20260229.idx', 'master.20261000.idx', 'master.20260930.idx'):
            with self.subTest(name=name):
                bad = discovery_harness(None, {'2026Q4': [listing_response('2026Q4', [name])]})
                self.addCleanup(bad.close)
                self.assertFalse(bad.run_single_directory('2026Q4').discovery_complete)

    def test_quarter_functions_rollover_and_contiguous_boundary(self):
        from sec_edgar_ingest.discovery import advance_daily_boundary, quarter_of, quarter_span, required_daily_quarters
        self.assertEqual(quarter_of(date(2024, 2, 29)), '2024Q1')
        self.assertEqual(quarter_span('2025Q4', '2026Q2'), ('2025Q4', '2026Q1', '2026Q2'))
        self.assertEqual(required_daily_quarters(date(2027, 1, 1), date(2026, 10, 1), None, ('2015Q1',)),
                         ('2015Q1', '2026Q4', '2027Q1'))
        self.assertIsNone(advance_daily_boundary(None, date(2026, 10, 6), ()))
        with self.assertRaises(ValueError):
            quarter_span('2026Q2', '2026Q1')


if __name__ == '__main__':
    unittest.main()
