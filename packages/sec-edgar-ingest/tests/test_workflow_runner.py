from network_guard import install
install()
from sec_edgar_ingest.models import to_mapping_value
import hashlib, json, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from support_workflows import BASE, CommandHarness, simple_pack, idx
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.models import RunContext, canonical_json
from sec_edgar_ingest.etl.reader import capture_quarter
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.workflows.checked import Dispatcher
from sec_edgar_ingest.workflows.runner import run_workflow
from sec_edgar_ingest.workflows.results import freeze_workflow, write_workflow_result, read_workflow_result
from sec_edgar_ingest.workflows.contracts import workflow_path

class RunnerTests(unittest.TestCase):
    def run_parent(self, h, *, run='runner', command='backfill'):
        now = datetime.now(timezone.utc)
        context = RunContext(run, 'manual', command, 'a', h.settings.worker.image_digest,
            h.settings.etl.parser_version, h.settings.etl.schema_version, h.settings.config_sha256,
            now, now + timedelta(seconds=1800), 'daily' if command == 'daily' else 'backfill')
        context = pin_context(h.settings, context, date(2026, 10, 7))[0]
        intent = {'command': command, 'today': '2026-10-07',
                  'fixture_sha256': hashlib.sha256(h.pack.read_bytes()).hexdigest(),
                  'pinned_end_quarter': '2026Q4'}
        context = freeze_workflow(context, intent, h.store, h.objects)
        dispatcher = Dispatcher(context, h.settings, h.pack, h.root, h.store, h.objects)
        report = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
        path = write_workflow_result(report, h.store, h.objects)
        self.assertEqual(read_workflow_result(path, h.store, h.objects), report)
        return report

    def test_deadline_after_selection_records_undispatched_units_without_child_work(self):
        from unittest.mock import patch
        from sec_edgar_ingest.workflows.runner import select_work
        from sec_edgar_ingest.workflows.results import freeze_selection
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                now = datetime.now(timezone.utc)
                context = RunContext('midrun-deadline', 'manual', 'backfill', 'a',
                    h.settings.worker.image_digest, h.settings.etl.parser_version,
                    h.settings.etl.schema_version, h.settings.config_sha256,
                    now, now + timedelta(seconds=1800), 'backfill')
                context = pin_context(h.settings, context, date(2026, 10, 7))[0]
                intent = {'command': 'backfill', 'today': '2026-10-07',
                    'fixture_sha256': hashlib.sha256(h.pack.read_bytes()).hexdigest(),
                    'pinned_end_quarter': '2026Q4'}
                context = freeze_workflow(context, intent, h.store, h.objects)
                dispatcher = Dispatcher(context, h.settings, h.pack, h.root, h.store, h.objects)
                selected = select_work(context, h.settings, intent, dispatcher, h.store, h.objects)
                # Discovery runs in real time: a stall of over 1/3 s before a fixture send loses that listing
                # (deferred by plan 11). Report the gaps here instead of a bare count mismatch further down.
                self.assertEqual(len(selected['members']), 2, selected['gaps'])
                freeze_selection(context, selected, h.store, h.objects)
                expired = context.deadline + timedelta(seconds=1)
                with patch('sec_edgar_ingest.workflows.runner.datetime') as clock, \
                     patch('sec_edgar_ingest.workflows.results.datetime') as accounting_clock, \
                     patch.object(dispatcher, 'execute', side_effect=AssertionError('expired child dispatch')):
                    clock.now.return_value = expired
                    accounting_clock.now.return_value = expired
                    report = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                    from dataclasses import replace
                    from sec_edgar_ingest.etl.contracts import PublicationResult
                    from sec_edgar_ingest.models import Error
                    from sec_edgar_ingest.storage.contracts import Conflict
                    from sec_edgar_ingest.workflows.contracts import summarize
                    from sec_edgar_ingest.workflows.results import _validate_report
                    changes = ({'downloaded': True}, {'downloaded': True, 'transformed': True},
                        {'transformed_ref': 'worksets/sec/transformed/sha256=' + 'a' * 64 + '/workset.json'},
                        {'quarters': (PublicationResult('2026Q3', 'published', 'a' * 64,
                            'fabricated/manifest.json', None, 0),)},
                        {'outcome': 'deferred'}, {'gaps': ()},
                        {'gaps': (Error('workflow_deferred', 'fabricated reason', True,
                            report.members[0].source.source_id, {}),)})
                    for change in changes:
                        altered = replace(report.members[0], **change)
                        members = (altered,) + report.members[1:]
                        gaps = tuple(gap for member in members for gap in member.gaps)
                        outcome, counts = summarize(members, gaps, report.intent['discovered_sources'],
                            report.intent['unresolved_before'], context.command, ())
                        bad = replace(report, members=members, gaps=gaps, outcome=outcome, counts=counts)
                        with self.subTest(change=change), self.assertRaises(Conflict):
                            _validate_report(bad, h.store, h.objects)
                    path = write_workflow_result(report, h.store, h.objects)
                    self.assertEqual(read_workflow_result(path, h.store, h.objects), report)
                self.assertEqual(report.counts['pending_sources'], 2)
                self.assertEqual(report.counts['complete_sources'], 0)
                self.assertNotEqual(report.outcome, 'success')
                self.assertTrue(all(member.outcome == 'pending' and not member.child_refs for member in report.members))
                self.assertEqual(report.intent['member_receipts'], (None, None))
                self.assertEqual(len(report.intent['child_calls']), 1)
                self.assertEqual(tuple(h.store.scan('Processing', {})), ())
                for quarter in ('2026Q3', '2026Q4'):
                    self.assertIsNone(EtlState(h.store).pointer(quarter))
            finally:
                h.close()

    def test_corrupt_retained_registry_and_receipt_do_not_block_valid_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                h.store.insert('WorkflowMember', 'broken-member-row', {'source': {'source_id': 'bad'}})
                first = self.run_parent(h, run='valid-with-corrupt-sibling')
                self.assertEqual(first.counts['complete_sources'], 2)
                self.assertEqual(first.outcome, 'incomplete')
                self.assertTrue(any(gap.code == 'legacy_member_unresolved' for gap in first.gaps))
                from sec_edgar_ingest.workflows.members import WorkflowMembers
                valid = WorkflowMembers(h.store, h.objects).inventory()[0]
                old = valid[0]
                h.store.insert('WorkflowMemberResult', 'broken-receipt-row', {
                    'member_id': old['member_id'], 'parser_version': h.settings.etl.parser_version,
                    'schema_version': h.settings.etl.schema_version, 'ref': 'missing/corrupt-receipt.json',
                    'sha256': 'a' * 64, 'bytes': 1})
                second = self.run_parent(h, run='valid-with-corrupt-receipt')
                self.assertGreaterEqual(second.counts['complete_sources'], 2)
                self.assertEqual(second.outcome, 'incomplete')
                self.assertTrue(any(gap.code == 'legacy_member_unresolved' and
                    gap.details.get('member_id') == old['member_id'] for gap in second.gaps))
                self.assertEqual([len(h.capture(quarter)[1]) for quarter in ('2026Q3', '2026Q4')], [1, 1])
            finally:
                h.close()

    def test_bounded_inclusive_backfill_captures_both_quarters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                report = self.run_parent(h)
                self.assertEqual(report.requested_quarters, ('2026Q3', '2026Q4'))
                self.assertEqual(report.outcome, 'success')
                self.assertEqual(report.counts['complete_sources'], 2)
                self.assertEqual([len(h.capture(q)[1]) for q in report.requested_quarters], [1, 1])
                self.assertEqual(len(report.intent['member_receipts']), 2)
                self.assertEqual(len(report.intent['completion_captures']), 2)
            finally:
                h.close()

    def test_all_refused_retains_baseline_gaps_and_quarantine_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack', conflicting=True))
            try:
                report = self.run_parent(h)
                self.assertEqual(report.outcome, 'quarantined')
                self.assertEqual((report.counts['complete_sources'], report.counts['failed_sources'],
                                  report.counts['quarantined_sources']), (0, 2, 2))
                self.assertEqual({g.details['quarter'] for g in report.gaps if g.code == 'baseline_publication_missing'},
                                 {'2026Q3', '2026Q4'})
                self.assertTrue(all(g.details.get('coverage_cause') == 'selected_source_quarantine'
                                    for g in report.gaps if g.code == 'baseline_publication_missing'))
                self.assertEqual(tuple(h.store.scan('Processing', {})), ())
                for quarter in report.requested_quarters:
                    self.assertIsNone(capture_quarter(quarter, h.objects, EtlState(h.store)))
            finally:
                h.close()

    def test_refusal_and_valid_progress_are_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pack = simple_pack(root / 'pack', conflicting=True)
            manifest = json.loads(pack.read_text())
            url = BASE + 'full-index/2026/QTR4/master.zip'
            body = idx((('123456', 'Example', '10-K', '2026-10-01',
                         'edgar/data/123456/0000123456-26-000004.txt'),), 'quarterly')
            digest = hashlib.sha256(body).hexdigest()
            (pack.parent / 'bodies' / (digest + '.body')).write_bytes(body)
            for response in manifest['responses'][url]:
                response.update(body_path='bodies/' + digest + '.body', body_sha256=digest)
                response['headers']['Content-Length'] = str(len(body))
            pack.write_bytes(canonical_json(to_mapping_value(manifest))); h = CommandHarness(root, pack)
            try:
                report = self.run_parent(h)
                self.assertEqual(report.outcome, 'incomplete')
                self.assertEqual((report.counts['complete_sources'], report.counts['failed_sources']), (1, 1))
                self.assertEqual(len(h.capture('2026Q4')[1]), 1)
                self.assertIsNone(capture_quarter('2026Q3', h.objects, EtlState(h.store)))
            finally:
                h.close()

    def test_empty_quarter_is_independent_missing_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pack = simple_pack(root / 'pack', conflicting=True)
            manifest = json.loads(pack.read_text())
            url = BASE + 'full-index/2026/QTR3/index.json'
            from support_workflows import listing
            body = listing(url, [])
            digest = hashlib.sha256(body).hexdigest()
            (pack.parent / 'bodies' / (digest + '.body')).write_bytes(body)
            for response in manifest['responses'][url]:
                response.update(body_path='bodies/' + digest + '.body', body_sha256=digest)
                response['headers']['Content-Length'] = str(len(body))
            pack.write_bytes(canonical_json(to_mapping_value(manifest))); h = CommandHarness(root, pack)
            try:
                report = self.run_parent(h)
                self.assertEqual(report.outcome, 'incomplete')
                self.assertTrue(any(g.code == 'baseline_source_missing' and g.details['quarter'] == '2026Q3'
                                    for g in report.gaps))
                self.assertTrue(all('coverage_cause' not in g.details for g in report.gaps
                                    if g.code == 'baseline_publication_missing'))
                self.assertEqual(report.counts['quarantined_sources'], 1)
            finally:
                h.close()

    def prepared(self, h, run='prepared', command='backfill', attempt='a'):
        now = datetime.now(timezone.utc)
        context = RunContext(run, 'manual', command, attempt, h.settings.worker.image_digest,
            h.settings.etl.parser_version, h.settings.etl.schema_version, h.settings.config_sha256,
            now, now + timedelta(seconds=1800), command)
        context = pin_context(h.settings, context, date(2026, 10, 7))[0]
        intent = {'command': command, 'today': '2026-10-07',
                  'fixture_sha256': hashlib.sha256(h.pack.read_bytes()).hexdigest(),
                  'pinned_end_quarter': '2026Q4'}
        context = freeze_workflow(context, intent, h.store, h.objects)
        dispatcher = Dispatcher(context, h.settings, h.pack, h.root, h.store, h.objects)
        return context, intent, dispatcher

    def test_fresh_backfill_counts_every_original_parent_and_replay_dispatches_nothing(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                self.run_parent(h, run='initial')
                second = self.run_parent(h, run='fresh')
                self.assertEqual(second.counts['discovered_sources'], 2)
                self.assertEqual(second.counts['complete_sources'], 2)
                context, intent = second.context, to_mapping_value(second.intent['invocation'])
                dispatcher = Dispatcher(context, h.settings, h.pack, h.root, h.store, h.objects)
                with patch.object(dispatcher, 'execute', side_effect=AssertionError('exact replay dispatch')):
                    replay = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertEqual(replay.intent, second.intent)
                self.assertEqual(replay.members, second.members)
                self.assertEqual([len(h.capture(q)[1]) for q in ('2026Q3', '2026Q4')], [1, 1])
            finally:
                h.close()

    def test_same_attempt_receipts_replay_after_mutable_discovery_index_is_corrupt(self):
        from unittest.mock import patch
        from sec_edgar_ingest.state import AcquisitionState
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                first = self.run_parent(h, run='historical')
                context, intent = first.context, to_mapping_value(first.intent['invocation'])
                dispatcher = Dispatcher(context, h.settings, h.pack, h.root, h.store, h.objects)
                row = AcquisitionState(h.store).discovery_session('workflow-backfill-historical')
                h.store.replace('DiscoverySession', hashlib.sha256(b'workflow-backfill-historical').hexdigest(),
                                {'corrupt': True}, row.version)
                with patch.object(dispatcher, 'execute', side_effect=AssertionError('historical redispatch')):
                    replay = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertEqual(replay.intent, first.intent)
                self.assertEqual(replay.members, first.members)
            finally:
                h.close()

    def test_backfill_and_daily_same_run_ids_have_separate_child_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                backfill = self.run_parent(h, run='shared')
                daily = self.run_parent(h, run='shared', command='daily')
                back_calls = {c['result_ref'] for c in backfill.intent['child_calls']}
                self.assertTrue(back_calls.isdisjoint(c['result_ref'] for c in daily.intent['child_calls']))
                self.assertEqual(daily.requested_quarters, ())
                self.assertEqual([len(h.capture(q)[1]) for q in ('2026Q3', '2026Q4')], [1, 1])
            finally:
                h.close()

    def test_empty_daily_without_backlog_is_no_new_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack', empty=True))
            try:
                report = self.run_parent(h, command='daily')
                self.assertEqual(report.outcome, 'no_new_sources')
                self.assertEqual(report.members, ())
                self.assertEqual(report.counts['discovered_sources'], 0)
            finally:
                h.close()

    def test_access_blocked_source_defers_every_later_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pack = simple_pack(root / 'pack')
            manifest = json.loads(pack.read_text())
            for response in manifest['responses'][BASE + 'full-index/2026/QTR3/master.zip']:
                response['status'] = 403
            pack.write_bytes(canonical_json(to_mapping_value(manifest)))
            h = CommandHarness(root, pack)
            try:
                report = self.run_parent(h)
                self.assertEqual(report.outcome, 'access_blocked')
                self.assertEqual([m.outcome for m in report.members], ['access_blocked', 'pending'])
                self.assertEqual(report.members[1].child_refs, ())
                self.assertEqual(len(report.intent['child_calls']), 2)
                self.assertEqual(tuple(h.store.scan('Processing', {})), ())
            finally:
                h.close()

    def test_failed_daily_directory_holds_boundary_and_retains_baseline_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pack = simple_pack(root / 'pack')
            manifest = json.loads(pack.read_text())
            for response in manifest['responses'][BASE + 'daily-index/2026/QTR4/index.json']:
                response['status'] = 404
            pack.write_bytes(canonical_json(to_mapping_value(manifest)))
            h = CommandHarness(root, pack)
            try:
                self.run_parent(h, run='baseline')
                report = self.run_parent(h, run='failed-daily', command='daily')
                self.assertEqual(report.outcome, 'incomplete')
                self.assertEqual(report.boundary_before, report.boundary_after)
                self.assertTrue(report.gaps)
                self.assertEqual([len(h.capture(q)[1]) for q in ('2026Q3', '2026Q4')], [1, 1])
            finally:
                h.close()

    def test_formerly_affected_q3_is_not_completed_by_q4_publication(self):
        from support_workflow_evidence import EvidenceFixture, quarterly_bytes
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = EvidenceFixture(root / '.fixture-state')
            h = None
            try:
                _, _, transformed = f.invoke('transform', f.snapshot_input(quarterly_bytes('2026-07-01')))
                self.assertEqual(f.invoke('publish', transformed.transformed_workset_ref)[0], 0)
                prior = EtlState(f.store).pointer('2026Q3')
                f.revised_member()
                f.snapshot_input(quarterly_bytes('2026-10-01'), seconds=1)
                h = CommandHarness(root, simple_pack(root / 'fresh-pack', empty=True), settings=f.settings)
                report = self.run_parent(h, run='affected-quarter', command='daily')
                self.assertEqual(report.outcome, 'incomplete')
                self.assertTrue(any(m.outcome == 'invalid_source' and
                    [q.outcome for q in m.quarters] == ['invalid_source', 'published'] for m in report.members))
                self.assertEqual(EtlState(h.store).pointer('2026Q3'), prior)
                self.assertEqual(len(h.capture('2026Q4')[1]), 1)
            finally:
                if h is not None:
                    h.close()
                f.close()

    def test_gate_only_and_mixed_gate_progress_preserve_current_pointer(self):
        from support_workflow_evidence import EvidenceFixture, quarterly_bytes
        for mixed in (False, True):
            with self.subTest(mixed=mixed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); f = EvidenceFixture(root / '.fixture-state')
                h = None
                try:
                    old = idx((('123456', 'A', '10-K', '2026-07-01', 'edgar/data/123456/a.txt'),
                               ('123456', 'B', '10-K', '2026-07-02', 'edgar/data/123456/b.txt')), 'quarterly')
                    _, _, transformed = f.invoke('transform', f.snapshot_input(old))
                    self.assertEqual(f.invoke('publish', transformed.transformed_workset_ref)[0], 0)
                    prior = EtlState(f.store).pointer('2026Q3')
                    f.revised_member()
                    f.snapshot_input(quarterly_bytes('2026-07-01'), seconds=1)
                    h = CommandHarness(root, simple_pack(root / 'fresh-pack', empty=not mixed), settings=f.settings)
                    report = self.run_parent(h, run='gated', command='daily')
                    self.assertEqual(report.outcome, 'awaiting_approval')
                    self.assertTrue(any(m.outcome == 'awaiting_approval' for m in report.members))
                    self.assertEqual(EtlState(h.store).pointer('2026Q3'), prior)
                    self.assertGreaterEqual(report.counts['pending_sources'], 1)
                    self.assertEqual(report.counts['complete_sources'], 1 if mixed else 0)
                finally:
                    if h is not None:
                        h.close()
                    f.close()

    def test_post_cas_failure_and_process_death_repair_before_report(self):
        from unittest.mock import patch
        from sec_edgar_ingest.storage.contracts import Conflict
        from sec_edgar_ingest.workflows.checked import ChildUnfinished
        for failure in (Conflict('ancillary failure'), KeyboardInterrupt('process death')):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack'))
                try:
                    context, intent, dispatcher = self.prepared(h, run='repair')
                    with patch.object(EtlState, '_record_membership', side_effect=failure):
                        with self.assertRaises((ChildUnfinished, KeyboardInterrupt)):
                            run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                    prior = EtlState(h.store).pointer('2026Q3')
                    self.assertIsNotNone(prior)
                    with self.assertRaises(FileNotFoundError):
                        h.objects.read(workflow_path(context))
                    report = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                    self.assertEqual(report.outcome, 'success')
                    self.assertEqual(report.counts['complete_sources'], 2)
                    self.assertTrue(report.intent['repair_resolutions'])
                    self.assertEqual(EtlState(h.store).pointer('2026Q3'), prior)
                    path = write_workflow_result(report, h.store, h.objects)
                    self.assertEqual(read_workflow_result(path, h.store, h.objects), report)
                finally:
                    h.close()

    def test_missing_result_discovery_gap_omission_refuses(self):
        from unittest.mock import patch
        from sec_edgar_ingest.state import AcquisitionState
        from sec_edgar_ingest.storage.contracts import Conflict
        from sec_edgar_ingest.workflows.runner import select_work
        from sec_edgar_ingest.workflows.results import freeze_selection
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack', empty=True))
            try:
                context, intent, dispatcher = self.prepared(h, run='missing-empty-discovery', command='daily')
                with patch.object(AcquisitionState, 'finish_discovery', side_effect=RuntimeError('original discovery failure')):
                    selected = select_work(context, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertIsNone(selected['parent_ref'])
                self.assertEqual(selected['members'], [])
                self.assertTrue(selected['halted'])
                self.assertEqual(selected['discovery_error']['code'], 'internal_error')
                self.assertTrue(selected['gaps'])
                with self.assertRaises(Conflict):
                    freeze_selection(context, {**selected, 'gaps': []}, h.store, h.objects)
                from copy import deepcopy
                altered = deepcopy(selected)
                original_gap = altered['discovery_error']['details']['gaps'][0]
                fabricated_gap = {**original_gap, 'message': 'fabricated original failure'}
                altered['discovery_error']['details']['gaps'][0] = fabricated_gap
                altered['gaps'] = [fabricated_gap if gap == original_gap else
                    altered['discovery_error'] if gap == selected['discovery_error'] else gap
                    for gap in altered['gaps']]
                with self.assertRaisesRegex(Conflict, 'persisted Attempt'):
                    freeze_selection(context, altered, h.store, h.objects)
                transplanted = deepcopy(selected)
                transplanted['discovery_error']['details']['call']['step_id'] = 'another-discovery'
                with self.assertRaises(Conflict):
                    freeze_selection(context, transplanted, h.store, h.objects)
                freeze_selection(context, selected, h.store, h.objects)
                report = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertEqual(report.outcome, 'internal_error')
                result_path = write_workflow_result(report, h.store, h.objects)
                before = h.objects.read(result_path)
                repaired = dispatcher.execute('discover', 'discover', h.settings,
                    ('--mode', 'daily', '--discovery-id', 'workflow-daily-' + context.run_id))
                self.assertIsNotNone(repaired.result.source_workset_ref)
                self.assertEqual(read_workflow_result(result_path, h.store, h.objects), report)
                import sqlite3
                from contextlib import closing
                from sec_edgar_ingest.storage.contracts import table_for
                with closing(sqlite3.connect(h.store.database)) as database:
                    for kind in ('Attempt', 'DiscoverySession', 'WorkflowChildCall', 'WorkflowAttempt'):
                        database.execute('DELETE FROM records WHERE table_name=?', (table_for(kind),))
                    database.commit()
                self.assertEqual(tuple(h.store.scan('Attempt', {})), ())
                self.assertEqual(tuple(h.store.scan('DiscoverySession', {})), ())
                self.assertEqual(read_workflow_result(result_path, h.store, h.objects), report)
                self.assertEqual(h.objects.read(result_path), before)
                self.assertEqual(freeze_selection(context, selected, h.store, h.objects), selected)
                terminal_ref = selected['discovery_call']['result_ref'].rsplit('/', 1)[0] + '/terminal.json'
                retained = h.objects.read(terminal_ref)
                self.assertEqual(json.loads(retained)['terminal_error'], selected['discovery_error']['details'])
            finally:
                h.close()

    def test_failed_empty_daily_directory_gap_omission_refuses(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        from sec_edgar_ingest.workflows.runner import select_work
        from sec_edgar_ingest.workflows.results import freeze_selection
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = simple_pack(root / 'pack', empty=True)
            manifest = json.loads(pack.read_text())
            for response in manifest['responses'][BASE + 'daily-index/2026/QTR4/index.json']:
                response['status'] = 404
            pack.write_bytes(canonical_json(to_mapping_value(manifest)))
            h = CommandHarness(root, pack)
            try:
                context, intent, dispatcher = self.prepared(h, run='failed-empty-discovery', command='daily')
                selected = select_work(context, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertIsNotNone(selected['parent_ref'])
                self.assertEqual(selected['members'], [])
                self.assertTrue(any(d['outcome'] == 'discovery_failed' for d in selected['directories']))
                self.assertTrue(selected['gaps'])
                with self.assertRaises(Conflict):
                    freeze_selection(context, {**selected, 'gaps': []}, h.store, h.objects)
                with self.assertRaisesRegex(Conflict, 'failure classification'):
                    freeze_selection(context, {**selected, 'halted': True}, h.store, h.objects)
                with self.assertRaises(Conflict):
                    freeze_selection(context, {**selected, 'discovery_error': selected['gaps'][0]}, h.store, h.objects)
                freeze_selection(context, selected, h.store, h.objects)
                report = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertEqual(report.outcome, 'incomplete')
                result_path = write_workflow_result(report, h.store, h.objects)
                self.assertEqual(read_workflow_result(result_path, h.store, h.objects), report)
            finally:
                h.close()

    def test_no_result_discovery_keeps_required_ledger_and_older_pending_jobs(self):
        from unittest.mock import patch
        from sec_edgar_ingest.state import AcquisitionState
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack', conflicting=True))
            try:
                self.run_parent(h, run='older')
                context, intent, dispatcher = self.prepared(h, run='no-discovery-result', command='daily')
                with patch.object(AcquisitionState, 'finish_discovery', side_effect=RuntimeError('discovery process failure')):
                    report = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                selection = json.loads(h.objects.read(report.intent['selection']['ref']))
                self.assertIsNone(report.source_workset_ref)
                self.assertTrue(selection['required_units'])
                self.assertEqual(selection['required_units'], selection['discovery_session']['frozen']['units'])
                self.assertEqual(report.counts['pending_sources'], 2)
                self.assertTrue(all(m.outcome == 'pending' and not m.child_refs for m in report.members))
                self.assertEqual(report.outcome, 'internal_error')
                path = write_workflow_result(report, h.store, h.objects)
                self.assertEqual(read_workflow_result(path, h.store, h.objects), report)
            finally:
                h.close()

    def test_expired_original_repairs_with_new_valid_workflow_attempt(self):
        from dataclasses import replace
        from unittest.mock import patch
        from sec_edgar_ingest.storage.contracts import Conflict
        from sec_edgar_ingest.workflows.checked import ChildUnfinished
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                original, intent, dispatcher = self.prepared(h, run='expired-repair')
                with patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary failure')):
                    with self.assertRaises(ChildUnfinished):
                        run_workflow(original, h.settings, intent, dispatcher, h.store, h.objects)
                prior = EtlState(h.store).pointer('2026Q3')
                old_calls = [r.to_mapping() for r in h.store.scan('WorkflowChildCall', {})]
                self.assertTrue(old_calls)
                clock = original.deadline + timedelta(seconds=1)
                fresh = replace(original, attempt_id='fresh', started_at=clock,
                                deadline=clock + timedelta(seconds=3600))
                with patch('sec_edgar_ingest.cli.Clock.now', return_value=clock), \
                     patch('sec_edgar_ingest.workflows.runner.datetime') as runner_clock:
                    runner_clock.now.return_value = clock
                    fresh = freeze_workflow(fresh, intent, h.store, h.objects)
                    dispatcher = Dispatcher(fresh, h.settings, h.pack, h.root, h.store, h.objects)
                    report = run_workflow(fresh, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertEqual(report.counts['complete_sources'], 2)
                self.assertEqual(report.outcome, 'success')
                self.assertTrue(report.intent['repair_resolutions'])
                self.assertEqual(EtlState(h.store).pointer('2026Q3'), prior)
                self.assertTrue(all(row in [r.to_mapping() for r in h.store.scan('WorkflowChildCall', {})]
                                    for row in old_calls))
                path = write_workflow_result(report, h.store, h.objects)
                self.assertEqual(read_workflow_result(path, h.store, h.objects), report)
            finally:
                h.close()

    def test_saved_receipt_repairs_missing_index_and_refuses_divergent_index(self):
        from unittest.mock import patch
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                context, intent, dispatcher = self.prepared(h, run='receipt-index')
                with patch('sec_edgar_ingest.workflows.members.immutable', side_effect=Conflict('index interrupted')):
                    with self.assertRaises(Conflict):
                        run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertEqual(tuple(h.store.scan('WorkflowMemberResult', {})), ())
                report = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertEqual(report.counts['complete_sources'], 2)
                self.assertEqual(len(tuple(h.store.scan('WorkflowMemberResult', {}))), 2)
                member = report.members[0]
                key = hashlib.sha256(canonical_json(to_mapping_value([context.run_id, context.command,
                    context.attempt_id, member.member_id, member.parser_version, member.schema_version]))).hexdigest()
                row = h.store.get('WorkflowMemberResult', key)
                divergent = row.to_mapping()['value']
                divergent['bytes'] += 1
                h.store.replace('WorkflowMemberResult', key, divergent, row.version)
                with patch.object(dispatcher, 'execute', side_effect=AssertionError('receipt replay dispatched')):
                    with self.assertRaises(Conflict):
                        run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
                self.assertEqual(h.store.get('WorkflowMemberResult', key).to_mapping()['value'], divergent)
            finally:
                h.close()

    def test_missing_frozen_provenance_never_recomputes_existing_selection(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                first = self.run_parent(h, run='missing-proof')
                context, intent = first.context, to_mapping_value(first.intent['invocation'])
                dispatcher = Dispatcher(context, h.settings, h.pack, h.root, h.store, h.objects)
                selection = json.loads(h.objects.read(first.intent['selection']['ref']))
                missing = selection['members'][0]['member_ref']
                original_read = h.objects.read
                def read(path):
                    if path == missing:
                        raise FileNotFoundError('missing frozen member provenance')
                    return original_read(path)
                with patch.object(h.objects, 'read', side_effect=read), \
                     patch.object(dispatcher, 'execute', side_effect=AssertionError('recomputed frozen selection')):
                    with self.assertRaises(FileNotFoundError):
                        run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
            finally:
                h.close()
