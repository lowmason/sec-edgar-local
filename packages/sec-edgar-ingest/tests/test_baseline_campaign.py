"""Offline invariants for the read-only Stage 2 baseline-campaign evidence tool."""
from network_guard import install
install()

import contextlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from support import fixture_settings
from support_workflows import BASE, CommandHarness, build_pack, idx

PROJECT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT / 'scripts/baseline-campaign.py'
FULL, DAILY = BASE + 'full-index/', BASE + 'daily-index/'


def tool():
    if not SCRIPT.exists():
        raise AssertionError('missing read-only baseline campaign evidence tool')
    return runpy.run_path(str(SCRIPT))


def row(cik, name, filed, number):
    return (cik, name, '10-K', filed, f'edgar/data/{cik}/0000{cik}-26-{number:06d}.txt')


def campaign_pack(root, quarterly, daily_rows):
    """Quarterly 2026Q2-Q4 plus one daily body on 2026-10-01 under daily-index QTR4."""
    listings = {FULL + 'index.json': [('2026', 'dir')],
                FULL + '2026/index.json': [('QTR2', 'dir'), ('QTR3', 'dir'), ('QTR4', 'dir')],
                DAILY + 'index.json': [('2026', 'dir')],
                DAILY + '2026/index.json': [('QTR3', 'dir'), ('QTR4', 'dir')],
                DAILY + '2026/QTR3/index.json': [],
                DAILY + '2026/QTR4/index.json': [('master.20261001.idx', 'file')]}
    bodies = {DAILY + '2026/QTR4/master.20261001.idx': idx(daily_rows, 'daily')}
    for quarter, rows in quarterly.items():
        listings[FULL + f'2026/QTR{quarter}/index.json'] = [('master.zip', 'file')]
        bodies[FULL + f'2026/QTR{quarter}/master.zip'] = idx(rows, 'quarterly')
    return build_pack(root, listings, bodies, repeats=16)


Q3 = (row('222222', 'Third', '2026-07-01', 3),)
Q4 = (row('333333', 'Fourth', '2026-10-01', 4),)
LATE = row('444444', 'Late release', '20260415', 9)
DAILY_ROWS = (row('333333', 'Fourth', '20261001', 4), LATE)
LATE_KEY_IN_Q2 = (row('111111', 'Second', '2026-04-01', 2), (LATE[0], LATE[1], LATE[2], '2026-04-15', LATE[4]))


class PureRuleTests(unittest.TestCase):
    def setUp(self):
        self.api = tool()

    def test_inventory_comparison_allows_only_sqlite_state_to_change(self):
        recorded = {'files': [{'relative_path': 'state.sqlite3', 'sha256': 'a', 'byte_count': 1},
                              {'relative_path': 'objects/x', 'sha256': 'b', 'byte_count': 1},
                              {'relative_path': 'objects/gone', 'sha256': 'c', 'byte_count': 1}]}
        actual = {'files': [{'relative_path': 'state.sqlite3', 'sha256': 'z', 'byte_count': 2},
                            {'relative_path': 'objects/x', 'sha256': 'b', 'byte_count': 2},
                            {'relative_path': 'objects/new', 'sha256': 'd', 'byte_count': 1}]}
        self.assertEqual(self.api['compare_inventory'](recorded, actual),
                         {'missing': ['objects/gone'], 'added': ['objects/new'],
                          'changed_immutable': ['objects/x'], 'changed_state': ['state.sqlite3']})

    def test_sqlite_journal_files_may_come_and_go_but_the_database_may_not(self):
        def entry(path):
            return {'relative_path': path, 'sha256': 'a', 'byte_count': 1}
        compare = self.api['compare_inventory']
        journaled = {'files': [entry('state.sqlite3'), entry('state.sqlite3-shm'), entry('state.sqlite3-wal')]}
        closed = {'files': [entry('state.sqlite3')]}
        # SQLite deletes its WAL and shared-memory files when the last connection closes cleanly.
        self.assertEqual(compare(journaled, closed),
                         {'missing': [], 'added': [], 'changed_immutable': [],
                          'changed_state': ['state.sqlite3-shm', 'state.sqlite3-wal']})
        self.assertEqual(compare(closed, journaled),
                         {'missing': [], 'added': [], 'changed_immutable': [],
                          'changed_state': ['state.sqlite3-shm', 'state.sqlite3-wal']})
        self.assertEqual(compare(journaled, {'files': [entry('state.sqlite3-wal')]}),
                         {'missing': ['state.sqlite3'], 'added': [], 'changed_immutable': [],
                          'changed_state': ['state.sqlite3-shm']})

    def test_recorded_inventory_reads_l12_evidence_and_files_reports(self):
        inventory = {'files': []}
        read = self.api['recorded_inventory']
        self.assertIs(read({'output_inventory': {'live_root': inventory}}), inventory)
        self.assertIs(read({'inventory': inventory}), inventory)
        self.assertIs(read(inventory), inventory)

    def test_unit_verdicts_never_treat_a_readable_quarter_as_coverage(self):
        verdict = self.api['unit_verdict']
        member = {'source_id': 's', 'outcome': 'success', 'status': 'complete', 'quarantined': False,
                  'quarters': [{'quarter': '2026Q3', 'outcome': 'published'}]}
        view = {'status': 'published', 'membership_source_id': 's', 'gate': 'clear',
                'row_count': 3, 'validated_rows': 3}
        self.assertEqual(verdict('2026Q3', '2026Q4', member, view, False), 'covered')
        self.assertEqual(verdict('2026Q4', '2026Q4', member, view, False), 'covered_open_quarter')
        self.assertEqual(verdict('2026Q3', '2026Q4', None, view, True), 'source_missing')
        self.assertEqual(verdict('2026Q3', '2026Q4', None, view, False), 'no_campaign_result')
        daily_only = {**view, 'membership_source_id': None}
        self.assertEqual(verdict('2026Q3', '2026Q4', member, daily_only, False), 'publication_mismatch')
        self.assertEqual(verdict('2026Q3', '2026Q4', member, {**view, 'validated_rows': 2}, False),
                         'publication_mismatch')
        refused = {**member, 'outcome': 'quarantined', 'status': 'failed', 'quarantined': True}
        self.assertEqual(verdict('2026Q3', '2026Q4', refused, daily_only, False), 'quarantined')
        gated = {**member, 'outcome': 'awaiting_approval', 'status': 'pending'}
        self.assertEqual(verdict('2026Q3', '2026Q4', gated, view, False), 'gated')
        self.assertEqual(verdict('2026Q3', '2026Q4', {**member, 'outcome': 'deferred', 'status': 'pending'},
                                 view, False), 'pending')
        self.assertEqual(verdict('2026Q3', '2026Q4', {**member, 'outcome': 'retry_exhausted', 'status': 'failed'},
                                 view, False), 'failed')

    def test_an_integrity_only_view_is_never_coverage(self):
        verdict = self.api['unit_verdict']
        member = {'source_id': 's', 'outcome': 'success', 'status': 'complete', 'quarantined': False,
                  'quarters': [{'quarter': '2026Q3', 'outcome': 'published'}]}
        unchecked = {'status': 'published', 'membership_source_id': 's', 'gate': 'clear',
                     'row_count': 3, 'validated_rows': None}
        self.assertEqual(verdict('2026Q3', '2026Q4', member, unchecked, False), 'published_unchecked')
        self.assertEqual(verdict('2026Q4', '2026Q4', member, unchecked, False), 'published_unchecked')
        self.assertEqual(verdict('2026Q3', '2026Q4', member, {**unchecked, 'membership_source_id': None}, False),
                         'publication_mismatch')
        self.assertEqual(verdict('2026Q3', '2026Q4', member, {**unchecked, 'row_count': 0}, False),
                         'publication_mismatch')

    def test_member_timings_join_children_by_attempt_and_time_each_wall(self):
        def attempt(run, command, attempt_id, start, end, outcome='success'):
            return {'context': {'run_id': run, 'command': command, 'attempt_id': attempt_id,
                                'started_at': '2026-11-02T10:' + start + '+00:00'},
                    'started_at': '2026-11-02T10:' + start + '+00:00',
                    'ended_at': None if end is None else '2026-11-02T10:' + end + '+00:00', 'outcome': outcome}
        values = [attempt('r1', 'collect', 'c1', '00:00', '00:02'), attempt('r1', 'transform', 't1', '00:02', '00:05'),
                  attempt('r1', 'publish', 'p1', '00:05', '00:10'), attempt('r1', 'publish', 'p1', '00:05', '00:06', 'received'),
                  attempt('r1', 'collect', 'c2', '00:12', '00:13'), attempt('r1', 'collect', 'c3', '00:20', None),
                  attempt('r1', 'discover', 'd1', '00:00', '00:01')]
        attempts = self.api['child_attempts'](values)
        self.assertEqual(sorted(attempts), [('r1', 'collect', 'c1'), ('r1', 'collect', 'c2'),
                                            ('r1', 'publish', 'p1'), ('r1', 'transform', 't1')])
        ref = lambda run, command, attempt_id: f'runs/sec/{run}/{command}/{attempt_id}/result.json'
        members = [
            {'source_id': 's1', 'kind': 'daily', 'period': '2026-10-01', 'outcome': 'success',
             'child_refs': [ref('r1', 'collect', 'c1'), ref('r1', 'transform', 't1'), ref('r1', 'publish', 'p1')]},
            {'source_id': 's1', 'kind': 'daily', 'period': '2026-10-01', 'outcome': 'unchanged', 'child_refs': []},
            {'source_id': 's2', 'kind': 'quarterly', 'period': '2026Q3', 'outcome': 'retry_exhausted',
             'child_refs': [ref('r0', 'collect', 'old'), ref('r1', 'collect', 'c2')]},
            {'source_id': 's2', 'kind': 'quarterly', 'period': '2026Q3', 'outcome': 'success',
             'child_refs': [ref('r1', 'publish', 'p1')]},
            {'source_id': 's3', 'kind': 'quarterly', 'period': '2026Q4', 'outcome': 'pending', 'child_refs': []}]
        rows = self.api['member_timings']('r1', [*members[:3], members[4]], attempts)
        # The last timed member's wall ends at its own last child; the finish step is the run's tail.
        self.assertEqual([(row['wall_seconds'], row['child_seconds'], row['engine_seconds'], row['b4'])
                          for row in rows], [(12.0, 10.0, 2.0, False), (None, 0, None, True),
                                             (1.0, 1.0, 0.0, False), (None, 0, None, False)])
        self.assertEqual(self.api['tail_seconds'](rows, '2026-11-02T10:00:30+00:00'), 17.0)
        self.assertIsNone(self.api['tail_seconds'](rows[1:2], '2026-11-02T10:00:30+00:00'))
        self.assertEqual(rows[0]['children']['publish'], {'outcome': 'success', 'seconds': 5.0,
                                                           'started_at': '2026-11-02T10:00:05+00:00',
                                                           'ended_at': '2026-11-02T10:00:10+00:00'})
        self.assertEqual(rows[2]['reused_children'], [ref('r0', 'collect', 'old')])
        summary = self.api['summarize_timings'](rows)
        self.assertEqual(summary, {'timed_members': 2, 'b4_members': 1, 'repeated_sources': [],
                                   'max_member_wall': {'source_id': 's1', 'kind': 'daily',
                                                       'period': '2026-10-01', 'wall_seconds': 12.0}})
        twice = self.api['member_timings']('r1', [members[0], members[3]], attempts)
        self.assertEqual(self.api['summarize_timings'](twice)['repeated_sources'], [])
        again = [members[0], {**members[0], 'child_refs': [ref('r1', 'collect', 'c2')]}]
        rows = self.api['member_timings']('r1', again, attempts)
        self.assertEqual(self.api['summarize_timings'](rows)['repeated_sources'], ['s1'])
        with self.assertRaises(ValueError):
            self.api['member_timings']('r1', [{**members[0], 'child_refs': [ref('r1', 'collect', 'c3')]}], attempts)

    def test_budget_breaches_name_each_exceeded_limit(self):
        budget = {'format_version': 'sec-baseline-campaign-budget-v1', 'max_invocations': 1,
                  'max_request_attempts': 10, 'max_request_attempts_per_invocation': 4,
                  'max_distinct_urls': 10, 'max_received_bytes': 100}
        quiet = {'attempts': 3, 'distinct_urls': 3, 'received_bytes': 50, 'access_denied': 0, 'uncertain': 0}
        check = self.api['check_budget']
        self.assertEqual(check({'runs': {'r1': quiet}, 'total': quiet}, budget), [])
        loud = {'attempts': 5, 'distinct_urls': 3, 'received_bytes': 101, 'access_denied': 1, 'uncertain': 0}
        fields = [(item['scope'], item['field'])
                  for item in check({'runs': {'r1': loud, 'r2': quiet}, 'total': loud}, budget)]
        self.assertEqual(fields, [('campaign', 'received_bytes'), ('r1', 'attempts'),
                                  ('campaign', 'invocations'), ('campaign', 'access_denied')])
        with self.assertRaises(ValueError):
            check({'runs': {}, 'total': quiet}, {**budget, 'format_version': 'other'})


class FixtureStoreTests(unittest.TestCase):
    def setUp(self):
        self.api = tool()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def harness(self, quarterly, daily_rows=DAILY_ROWS):
        settings = fixture_settings(backfill={'start_quarter': '2026Q2', 'end_quarter': 'open'},
            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
            http={'retry_base_seconds': 0.001, 'retry_cap_seconds': 0.001},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        h = CommandHarness(self.root, campaign_pack(self.root / 'pack', quarterly, daily_rows), settings)
        self.addCleanup(h.close)
        return h

    def run_tool(self, h, *argv):
        h.close()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.api['main'](list(argv))
        return code, json.loads(stdout.getvalue())

    def coverage(self, h, *refs, check=()):
        flags = [item for ref in refs for item in ('--result', ref)]
        return self.run_tool(h, 'coverage', '--config', str(h.config), *flags,
                             '--start', '2026Q2', '--end', '2026Q4', '--open-quarter', '2026Q4', *check)

    def test_integrity_coverage_reads_no_row_and_reports_no_coverage(self):
        conflict = (row('111111', 'Second', '2026-04-01', 2), row('111111', 'Changed', '2026-04-01', 2))
        h = self.harness({2: conflict, 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 3, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'], check=('--check', 'integrity'))
        self.assertEqual(code, 0)
        self.assertEqual(report['check'], 'integrity')
        self.assertEqual({unit['quarter']: unit['verdict'] for unit in report['units']},
                         {'2026Q2': 'quarantined', '2026Q3': 'published_unchecked',
                          '2026Q4': 'published_unchecked'})
        self.assertIsNone(report['units'][1]['filing_quarter']['validated_rows'])
        self.assertEqual(report['units'][1]['filing_quarter']['row_count'], 1)
        self.assertFalse(report['complete'])
        code, report = self.coverage(h, message['result_ref'])
        self.assertEqual((report['check'], report['units'][1]['verdict']), ('full', 'covered'))

    def test_timing_times_each_member_and_refuses_a_member_over_the_limit(self):
        h = self.harness({2: (row('111111', 'Second', '2026-04-01', 2),), 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        code, report = self.run_tool(h, 'timing', '--config', str(h.config), '--result', message['result_ref'])
        self.assertEqual(code, 0, report)
        self.assertNotIn('breaches', report)
        run = report['runs'][0]
        self.assertEqual((run['run_id'], run['timed_members'], run['b4_members'], run['repeated_sources']),
                         ('r1', 3, 0, []))
        self.assertIsNone(run['dispatch_cutoff'])
        self.assertGreaterEqual(run['tail_seconds'], 0)
        for member in run['members']:
            self.assertEqual(set(member['children']), {'collect', 'transform', 'publish'})
            self.assertGreaterEqual(member['wall_seconds'], member['child_seconds'])
            self.assertGreater(member['child_seconds'], 0)
            self.assertGreaterEqual(member['engine_seconds'], 0)
        self.assertGreaterEqual(report['child_call_rows'], 9)
        code, report = self.run_tool(h, 'timing', '--config', str(h.config), '--result', message['result_ref'],
                                     '--max-member-wall', '0')
        self.assertEqual(code, 1)
        self.assertEqual(sorted(item['period'] for item in report['breaches']), ['2026Q2', '2026Q3', '2026Q4'])
        self.assertTrue(all(item['limit'] == 0 for item in report['breaches']))

    def test_backfill_units_separate_quarantine_from_quarterly_coverage(self):
        conflict = (row('111111', 'Second', '2026-04-01', 2), row('111111', 'Changed', '2026-04-01', 2))
        h = self.harness({2: conflict, 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 3, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'])
        self.assertEqual(code, 0)
        verdicts = {unit['quarter']: unit['verdict'] for unit in report['units']}
        self.assertEqual(verdicts, {'2026Q2': 'quarantined', '2026Q3': 'covered',
                                    '2026Q4': 'covered_open_quarter'})
        self.assertFalse(report['complete'])
        self.assertEqual(report['units'][0]['filing_quarter']['status'], 'unpublished')
        self.assertIn('baseline_publication_missing', report['units'][0]['last_result_gaps'])

    def test_daily_only_generation_never_counts_for_a_quarantined_quarterly_source(self):
        conflict = (row('111111', 'Second', '2026-04-01', 2), row('111111', 'Changed', '2026-04-01', 2))
        h = self.harness({2: conflict, 3: Q3, 4: Q4})
        self.assertEqual(h.invoke('daily', run='d1', attempt='a1')[0], 0, h.calls[-1])
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 3, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'])
        unit = report['units'][0]
        # The engine's own baseline check sees a readable 2026Q2 and reports no missing publication.
        self.assertNotIn('baseline_publication_missing', unit['last_result_gaps'])
        self.assertEqual(unit['filing_quarter']['status'], 'published')
        self.assertIsNone(unit['filing_quarter']['membership_source_id'])
        self.assertEqual(unit['filing_quarter']['source_kinds'], {'daily': 1})
        self.assertEqual(unit['verdict'], 'quarantined')

    def test_closed_quarterly_missing_a_late_daily_key_is_gated_not_covered(self):
        h = self.harness({2: (row('111111', 'Second', '2026-04-01', 2),), 3: Q3, 4: Q4})
        code, daily = h.invoke('daily', run='d1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 10, h.calls[-1])
        code, report = self.coverage(h, daily['result_ref'], message['result_ref'])
        unit = report['units'][0]
        self.assertEqual(unit['verdict'], 'gated')
        self.assertIsNone(unit['filing_quarter']['membership_source_id'])
        self.assertEqual([item['period'] for item in report['daily_sources']], ['2026-10-01'])

    def test_closed_quarterly_that_lists_the_late_key_covers_the_quarter(self):
        h = self.harness({2: LATE_KEY_IN_Q2, 3: Q3, 4: Q4})
        self.assertEqual(h.invoke('daily', run='d1', attempt='a1')[0], 0, h.calls[-1])
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'])
        self.assertTrue(report['complete'])
        view = report['units'][0]['filing_quarter']
        self.assertEqual(view['source_kinds'], {'daily': 1, 'quarterly': 1})
        self.assertEqual((view['daily_rows_considered'], view['validated_rows']), (1, 2))

    def test_audit_counts_each_run_and_refuses_over_budget(self):
        h = self.harness({2: (row('111111', 'Second', '2026-04-01', 2),), 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        # Five full-index listings (root, year, three quarters) and three quarterly bodies.
        budget = self.root / 'budget.json'
        budget.write_text(json.dumps({'format_version': 'sec-baseline-campaign-budget-v1', 'max_invocations': 1,
            'max_request_attempts': 8, 'max_request_attempts_per_invocation': 8,
            'max_distinct_urls': 8, 'max_received_bytes': 10 ** 9}))
        code, report = self.run_tool(h, 'audit', '--config', str(h.config), '--run-id', 'r1',
                                     '--budget', str(budget))
        self.assertEqual(code, 0, report)
        run = report['runs']['r1']
        self.assertEqual((run['attempts'], run['distinct_urls'], run['max_ordinal']), (8, 8, 1))
        self.assertEqual((run['uncertain'], run['access_denied'], run['statuses']), (0, 0, {'200': 8}))
        self.assertGreater(run['received_bytes'], 0)
        budget.write_text(json.dumps({**json.loads(budget.read_text()), 'max_request_attempts': 7}))
        code, report = self.run_tool(h, 'audit', '--config', str(h.config), '--run-id', 'r1',
                                     '--budget', str(budget))
        self.assertEqual(code, 1)
        self.assertEqual(report['breaches'], [{'scope': 'campaign', 'field': 'attempts',
                                               'observed': 8, 'limit': 7}])

    def test_files_report_refuses_a_rewritten_immutable_object(self):
        root = self.root / 'store'
        (root / 'objects').mkdir(parents=True)
        (root / 'objects/manifest.json').write_bytes(b'{"a":1}')
        (root / 'state.sqlite3').write_bytes(b'one')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.api['main'](['files', '--root', str(root)]), 0)
        recorded = self.root / 'recorded.json'
        recorded.write_text(stdout.getvalue())
        (root / 'state.sqlite3').write_bytes(b'two')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.api['main'](['files', '--root', str(root), '--recorded', str(recorded)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())['comparison']['changed_state'], ['state.sqlite3'])
        (root / 'objects/manifest.json').write_bytes(b'{\n\t"a": 1\n}')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.api['main'](['files', '--root', str(root), '--recorded', str(recorded)]), 1)
        self.assertEqual(json.loads(stdout.getvalue())['comparison']['changed_immutable'], ['objects/manifest.json'])


if __name__ == '__main__':
    unittest.main()
