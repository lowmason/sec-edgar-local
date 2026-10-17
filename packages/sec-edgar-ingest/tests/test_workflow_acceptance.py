from network_guard import install
install()
from sec_edgar_ingest.models import to_mapping_value
import hashlib, json, os, shutil, tempfile, unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from support import fixture_settings
from support_workflows import (BASE, CommandHarness, simple_pack, quarter_pack,
    set_harness_settings, prefix_response, replace_pack_body, idx)
from sec_edgar_ingest.models import canonical_json, parse_json
from sec_edgar_ingest.state import AcquisitionState
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.workflows.results import read_workflow_result
from sec_edgar_ingest.workflows.completion import evaluate_member
from sec_edgar_ingest.workflows.checked import read_child


class WorkflowAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.command_harnesses = []
        self.reader_captures = []
        evidence = os.environ.get('SEC_EDGAR_TASK10_ACCEPTANCE_EVIDENCE')
        if evidence:
            def retain():
                target = Path(evidence) / self._testMethodName
                shutil.copytree(self.root, target)
                payload = {'original_root': str(self.root), 'retained_root': str(target),
                           'commands': [call for harness in self.command_harnesses for call in harness.calls],
                           'reader_captures': self.reader_captures}
                with (target / 'checked-evidence.json').open('xb') as stream:
                    stream.write(canonical_json(to_mapping_value(payload)))
            self.addCleanup(retain)

    def harness(self, pack, start='2026Q3', end='open'):
        settings = fixture_settings(backfill={'start_quarter': start, 'end_quarter': end},
            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
            http={'retry_base_seconds': 0.001, 'retry_cap_seconds': 0.001},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        h = CommandHarness(self.root, pack, settings)
        self.addCleanup(h.close)
        self.command_harnesses.append(h)
        actual_capture = h.capture
        def capture(quarter):
            captured, rows = actual_capture(quarter)
            self.reader_captures.append({'quarter': quarter, 'capture': captured.to_mapping(), 'rows': rows})
            return captured, rows
        h.capture = capture
        return h

    def report(self, h, message):
        return read_workflow_result(message['result_ref'], h.store, h.objects)

    def test_F2_retry_prefix_survives_without_terminal_source_quarantine(self):
        pack = simple_pack(self.root / 'pack')
        prefix = prefix_response(pack, BASE + 'daily-index/2026/QTR4/master.20261001.idx')
        h = self.harness(pack)
        code, message = h.invoke('daily')
        self.assertEqual(code, 0, h.calls[-1])
        report = self.report(h, message)
        self.assertEqual(report.counts['complete_sources'], 1)
        self.assertEqual(report.counts['quarantined_sources'], 0)
        self.assertEqual(report.counts['failed_sources'], 0)
        calls = report.to_mapping()['intent']['child_calls']
        collect = next(call for call in calls if call['context']['command'] == 'collect')
        source = report.members[0].source
        child_context = read_child(collect, h.store, h.objects).context
        history = AcquisitionState(h.store).request_history(child_context, source.canonical_url)
        self.assertEqual(len(history), 2)
        first = history[0].value
        base = f'quarantine/sec/{report.context.run_id}/{source.source_id}/{collect["context"]["attempt_id"]}/{first["request_id"]}'
        self.assertEqual(h.objects.read(base + '/body'), prefix)
        self.assertEqual(parse_json(h.objects.read(base + '/receipt.json'))['error']['code'], 'read_timeout')
        self.assertEqual(len(h.capture('2026Q4')[1]), 1)

    def test_F4_parent_command_namespace_and_exact_completed_replay(self):
        h = self.harness(simple_pack(self.root / 'pack'))
        outputs = []
        for command in ('backfill', 'daily'):
            code, message = h.invoke(command, run='same', attempt='same')
            self.assertEqual(code, 0, h.calls[-1])
            outputs.append(message)
        reports = [self.report(h, value) for value in outputs]
        discovery = [next(call for call in result.to_mapping()['intent']['child_calls']
                          if call['context']['command'] == 'discover') for result in reports]
        self.assertNotEqual(discovery[0]['context']['attempt_id'], discovery[1]['context']['attempt_id'])
        self.assertEqual({call['workflow_command'] for call in discovery}, {'backfill', 'daily'})
        cursors = tuple(row.to_mapping() for row in h.store.scan('FixtureResponseCursor', {}))
        for command, expected in zip(('backfill', 'daily'), outputs):
            self.assertEqual(h.invoke(command, run='same', attempt='same'), (0, expected))
        self.assertEqual(tuple(row.to_mapping() for row in h.store.scan('FixtureResponseCursor', {})), cursors)

    def test_F5_all_conflicting_baseline_is_quarantined_with_gaps_and_no_pointer(self):
        h = self.harness(simple_pack(self.root / 'pack', conflicting=True))
        code, message = h.invoke('backfill')
        self.assertEqual(code, 7, h.calls[-1])
        report = self.report(h, message)
        self.assertEqual(report.outcome, 'quarantined')
        self.assertEqual(report.counts['complete_sources'], 0)
        self.assertEqual(report.counts['failed_sources'], 2)
        self.assertEqual(report.counts['quarantined_sources'], 2)
        self.assertEqual(tuple(h.store.scan('Processing', {})), ())
        self.assertEqual(tuple(h.store.scan('QuarterPublication', {})), ())
        baseline = [gap for gap in report.gaps if gap.code == 'baseline_publication_missing']
        self.assertEqual({gap.details['quarter'] for gap in baseline}, {'2026Q3', '2026Q4'})
        self.assertTrue(all(gap.details['coverage_cause'] == 'selected_source_quarantine' for gap in baseline))
        self.assertTrue(all(member.quarantined and member.gaps for member in report.members))

    def test_R1_empty_quarter_is_unresolved_and_preserves_valid_quarter(self):
        pack = simple_pack(self.root / 'pack')
        manifest = json.loads(pack.read_text())
        from support_workflows import listing
        from sec_edgar_ingest.models import canonical_json
        url = BASE + 'full-index/2026/QTR3/index.json'
        body = listing(url, [])
        digest = hashlib.sha256(body).hexdigest()
        (pack.parent / 'bodies' / (digest + '.body')).write_bytes(body)
        response = {'status': 200, 'headers': {'Content-Length': str(len(body))},
                    'body_path': 'bodies/' + digest + '.body', 'body_sha256': digest}
        manifest['responses'][url] = [dict(response) for _ in range(16)]
        pack.write_bytes(canonical_json(to_mapping_value(manifest)))
        h = self.harness(pack)
        code, message = h.invoke('backfill')
        self.assertEqual(code, 3)
        report = self.report(h, message)
        self.assertEqual(report.counts['complete_sources'], 1)
        self.assertIsNone(EtlState(h.store).pointer('2026Q3'))
        self.assertEqual(len(h.capture('2026Q4')[1]), 1)
        self.assertTrue(any(gap.details.get('quarter') == '2026Q3' for gap in report.gaps))

    def test_R1_mixed_valid_and_refused_members_preserves_good_pointer(self):
        h = self.harness(quarter_pack(self.root / 'pack', ('2026Q3', '2026Q4'),
                                      conflicting=('2026Q3',)))
        code, message = h.invoke('backfill')
        self.assertEqual(code, 3, h.calls[-1])
        report = self.report(h, message)
        self.assertEqual(report.counts['complete_sources'], 1)
        self.assertEqual(report.counts['failed_sources'], 1)
        self.assertEqual(report.counts['quarantined_sources'], 1)
        self.assertIsNone(EtlState(h.store).pointer('2026Q3'))
        self.assertEqual(len(h.capture('2026Q4')[1]), 1)
        self.assertEqual(len(tuple(h.store.scan('Processing', {}))), 1)

    def test_R2_older_nonempty_closed_withdrawal_gate_remains_pending(self):
        periods = ('2026Q3', '2026Q4')
        pack = quarter_pack(self.root / 'initial', periods, empty_daily=True)
        url = BASE + 'full-index/2026/QTR3/master.zip'
        a = ('123456', 'A', '10-K', '2026-07-01', 'edgar/data/123456/0000123456-26-000031.txt')
        b = ('123456', 'B', '10-K', '2026-07-02', 'edgar/data/123456/0000123456-26-000032.txt')
        replace_pack_body(pack, url, idx((a, b), 'quarterly'))
        h = self.harness(pack, end='2026Q3')
        self.assertEqual(h.invoke('backfill', run='closed-baseline')[0], 0)
        before = EtlState(h.store).pointer('2026Q3').to_mapping()
        revision = quarter_pack(self.root / 'revision', periods, empty_daily=True)
        replace_pack_body(revision, url, idx((a,), 'quarterly'))
        h.pack = revision
        code, found = h.invoke('discover', ('--mode', 'quarterly', '--discovery-id', 'gate-refresh', '--refresh'), run='gate-find')
        self.assertEqual(code, 0)
        code, collected = h.invoke('collect', ('--workset', found['source_workset_ref']), run='gate-collect')
        self.assertEqual(code, 0)
        code, transformed = h.invoke('transform', ('--workset', collected['snapshot_workset_ref']), run='gate-transform')
        self.assertEqual(code, 0)
        code, published = h.invoke('publish', ('--workset', transformed['transformed_workset_ref']), run='gate-publish')
        self.assertEqual(code, 10, h.calls[-1])
        self.assertEqual(EtlState(h.store).pointer('2026Q3').to_mapping(), before)
        current = fixture_settings(backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        set_harness_settings(h, current)
        code, message = h.invoke('daily', run='gate-backlog')
        self.assertEqual(code, 10, h.calls[-1])
        report = self.report(h, message)
        self.assertEqual(report.outcome, 'awaiting_approval')
        self.assertEqual(report.counts['pending_sources'], 1)
        self.assertEqual(report.counts['complete_sources'], 0)
        self.assertGreaterEqual(report.counts['awaiting_approval_quarters'], 1)
        self.assertEqual(EtlState(h.store).pointer('2026Q3').to_mapping(), before)
        self.assertEqual(len(h.capture('2026Q3')[1]), 2)

    def seed_older_unacquired(self, h):
        # Only actual shipped primitive discovery: no WorkflowMember or completion is fabricated.
        prior = fixture_settings(backfill={'start_quarter': '2025Q2', 'end_quarter': '2025Q2'},
            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        current = h.settings
        set_harness_settings(h, prior)
        code, result = h.invoke('discover', ('--mode', 'quarterly', '--discovery-id', 'older-unacquired'), run='older')
        self.assertEqual(code, 0)
        self.assertEqual(tuple(h.store.scan('WorkflowMember', {})), ())
        set_harness_settings(h, current)
        return result['source_workset_ref']

    def test_R2_outage_spans_Q4_Q1_Q2_and_keeps_older_pending(self):
        periods = ('2025Q2', '2026Q3', '2026Q4', '2027Q1', '2027Q2')
        handoff_pack = quarter_pack(self.root / 'handoff-pack', periods, empty_daily=True)
        h = self.harness(handoff_pack, start='2025Q2')
        code, _ = h.invoke('daily', run='handoff', today='2026-10-02')
        self.assertEqual(code, 0, h.calls[-1])
        self.assertEqual(AcquisitionState(h.store).daily_boundary(), date(2026, 10, 2))
        self.assertEqual(tuple(h.store.scan('WorkflowMember', {})), ())
        older_ref = self.seed_older_unacquired(h)
        h.pack = quarter_pack(self.root / 'outage-pack', periods)
        code, message = h.invoke('daily', run='outage', today='2027-04-01')
        self.assertEqual(code, 0, h.calls[-1])
        report = self.report(h, message)
        self.assertEqual(report.boundary_before, '2026-10-02')
        self.assertEqual(report.boundary_after, '2027-04-01')
        self.assertEqual(report.intent['unresolved_before'], 1)
        self.assertTrue(any(member.parent_ref == older_ref for member in report.members))
        periods_seen = {directory['period'] for directory in report.to_mapping()['directories']}
        self.assertTrue({'2025Q2', '2026Q4', '2027Q1', '2027Q2'} <= periods_seen)
        for quarter in ('2025Q2', '2026Q4', '2027Q1', '2027Q2'):
            self.assertEqual(len(h.capture(quarter)[1]), 1)

    def test_R2_failed_outage_directory_holds_boundary_with_independent_progress(self):
        periods = ('2025Q2', '2026Q3', '2026Q4', '2027Q1', '2027Q2')
        handoff_pack = quarter_pack(self.root / 'handoff-pack', periods, empty_daily=True)
        h = self.harness(handoff_pack, start='2025Q2')
        self.assertEqual(h.invoke('daily', run='handoff', today='2026-10-02')[0], 0)
        self.assertEqual(tuple(h.store.scan('WorkflowMember', {})), ())
        self.seed_older_unacquired(h)
        h.pack = quarter_pack(self.root / 'failed-outage-pack', periods, failed_daily=('2027Q1',))
        code, message = h.invoke('daily', run='outage-failed', today='2027-04-01')
        self.assertEqual(code, 3, h.calls[-1])
        report = self.report(h, message)
        self.assertEqual(report.boundary_before, '2026-10-02')
        self.assertEqual(report.boundary_after, '2026-10-02')
        failed = [directory for directory in report.to_mapping()['directories'] if directory['outcome'] == 'discovery_failed']
        self.assertEqual({directory['period'] for directory in failed}, {'2027Q1'})
        self.assertGreaterEqual(report.counts['complete_sources'], 1)
        self.assertEqual(len(h.capture('2025Q2')[1]), 1)
        self.assertEqual(len(h.capture('2027Q2')[1]), 1)
        self.assertIsNone(EtlState(h.store).pointer('2027Q1'))

    def test_R2_Q4_Q1_transition_uses_both_required_quarters(self):
        h = self.harness(quarter_pack(self.root / 'pack', ('2026Q3', '2026Q4', '2027Q1')))
        self.assertEqual(h.invoke('daily', run='q4', today='2026-12-31')[0], 0)
        code, message = h.invoke('daily', run='q1', today='2027-01-02')
        self.assertEqual(code, 0, h.calls[-1])
        report = self.report(h, message)
        periods = {directory['period'] for directory in report.to_mapping()['directories']}
        self.assertTrue({'2026Q4', '2027Q1'} <= periods)
        self.assertEqual(len(h.capture('2026Q4')[1]), 1)
        self.assertEqual(len(h.capture('2027Q1')[1]), 1)

    def test_F1_moved_quarter_remains_backlog_after_Q4_publishes(self):
        h = self.harness(simple_pack(self.root / 'initial'))
        self.assertEqual(h.invoke('backfill', run='initial')[0], 0)
        before = EtlState(h.store).pointer('2026Q3').to_mapping()
        h.pack = quarter_pack(self.root / 'revision', ('2026Q3', '2026Q4'),
                              moved={'2026Q3': '2026-10-01'}, empty_daily=True)
        code, found = h.invoke('discover', ('--mode', 'quarterly', '--discovery-id', 'revision', '--refresh'), run='revision-find')
        self.assertEqual(code, 0)
        code, collected = h.invoke('collect', ('--workset', found['source_workset_ref']), run='revision-collect')
        self.assertEqual(code, 0)
        code, transformed = h.invoke('transform', ('--workset', collected['snapshot_workset_ref']), run='revision-transform')
        self.assertEqual(code, 0)
        code, published = h.invoke('publish', ('--workset', transformed['transformed_workset_ref']), run='revision-publish')
        self.assertEqual(code, 7, h.calls[-1])
        from sec_edgar_ingest.etl.commands import read_etl_result
        result = read_etl_result(published['result_ref'], h.objects)
        quarters = {quarter.quarter: quarter.outcome for quarter in result.quarters}
        self.assertEqual(quarters, {'2026Q3': 'invalid_source', '2026Q4': 'published'})
        self.assertEqual(EtlState(h.store).pointer('2026Q3').to_mapping(), before)
        code, daily = h.invoke('daily', run='backlog')
        report = self.report(h, daily)
        self.assertNotEqual(report.outcome, 'no_new_sources')
        values = [row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {})
                  if row.value['parent_ref'] == found['source_workset_ref']]
        self.assertTrue(values)
        self.assertTrue(any(not evaluate_member(value, report.context.parser_version,
            report.context.schema_version, h.store, h.objects).complete for value in values))

    def test_F3_ordinary_post_CAS_failure_has_no_report_then_fresh_checked_repair(self):
        h = self.harness(simple_pack(self.root / 'pack'), start='2026Q4')
        import sec_edgar_ingest.cli as cli
        from sec_edgar_ingest.etl.commands import run_publish
        fired = []
        def boundary(point):
            if point == 'publication.after_pointer' and not fired:
                fired.append(True)
                raise OSError('ordinary retained post-CAS failure')
        def publish(*args, **kwargs): return run_publish(*args, observer=boundary, **kwargs)
        with patch.object(cli, 'run_publish', side_effect=publish):
            code, message = h.invoke('backfill', run='repair', attempt='original')
        self.assertEqual(code, 9, h.calls[-1])
        self.assertIsNone(message['result_ref'])
        self.assertEqual(fired, [True])
        pointers = [row.to_mapping() for row in h.store.scan('QuarterPublication', {})]
        self.assertEqual(len(pointers), 1)
        attempts = [row.to_mapping() for row in h.store.scan('Attempt', {}) if row.value['context']['command'] == 'publish']
        self.assertEqual(len(attempts), 1)
        self.assertIsNone(attempts[0]['value']['result'])
        self.assertEqual(attempts[0]['value']['structured_errors'][0]['details']['type'], 'PublicationRepairPending')
        with self.assertRaises(FileNotFoundError):
            h.objects.read('runs/sec/repair/backfill/original/result.json')
        h.pack = simple_pack(self.root / 'empty-after-repair', empty=True)
        code, message = h.invoke('daily', run='repair', attempt='fresh')
        self.assertEqual(code, 0, h.calls[-1])
        report = self.report(h, message)
        self.assertNotEqual(report.outcome, 'no_new_sources')
        self.assertTrue(report.intent['repair_resolutions'])
        self.assertEqual([row.to_mapping() for row in h.store.scan('QuarterPublication', {})], pointers)
        old = next(row.to_mapping() for row in h.store.scan('Attempt', {})
                   if row.value['context']['attempt_id'] == attempts[0]['value']['context']['attempt_id'])
        self.assertEqual(old, attempts[0])
