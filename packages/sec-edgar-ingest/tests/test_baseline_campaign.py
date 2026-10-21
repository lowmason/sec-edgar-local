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

    def coverage(self, h, *refs):
        flags = [item for ref in refs for item in ('--result', ref)]
        return self.run_tool(h, 'coverage', '--config', str(h.config), *flags,
                             '--start', '2026Q2', '--end', '2026Q4', '--open-quarter', '2026Q4')

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
