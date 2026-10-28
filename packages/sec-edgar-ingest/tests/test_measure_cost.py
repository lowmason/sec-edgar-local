"""Stage 1b §6 rules in scripts/measure-d5-drain.py: the C8 floor, the reserve and the fit gate."""
from network_guard import install
install()

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / 'scripts' / 'measure-d5-drain.py'


def load():
    spec = importlib.util.spec_from_file_location('measure_cost_script', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CostProposalTests(unittest.TestCase):
    def setUp(self):
        self.measure = load()

    def test_the_floor_stays_480_for_the_d5_finish_cost(self):
        value = self.measure.cost_proposal(152.15, 1000.0)
        self.assertEqual((value['p4_floor_seconds'], value['floor_seconds'], value['floor_changes']), (480, 480, False))
        self.assertEqual(value['reserve_seconds'], 1740)
        self.assertTrue(value['fit_gate_passes'])

    def test_a_larger_finish_cost_raises_the_floor(self):
        value = self.measure.cost_proposal(200.0, 600.0)
        self.assertEqual((value['p4_floor_seconds'], value['floor_seconds'], value['floor_changes']), (600, 600, True))

    def test_the_fit_gate_boundary_near_1250_seconds(self):
        self.assertTrue(self.measure.cost_proposal(150.0, 1240.0)['fit_gate_passes'])
        failing = self.measure.cost_proposal(150.0, 1250.0)
        self.assertEqual(failing['reserve_seconds'], 2100)
        self.assertFalse(failing['fit_gate_passes'])

    def test_summarize_names_incomplete_scenarios_and_proposes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'open-report.json').write_text(json.dumps({
                'status': 'failed', 'release_id': 'r', 'scenarios': {}, 'partial_walls': []}))
            summary = self.measure.summarize(work)
        self.assertEqual(summary['measures']['incomplete_scenarios'], ['open', 'closed', 'authority', 'finish'])
        self.assertIsNone(summary['proposal'])


def wall(period, seconds, kind='daily'):
    return {'kind': kind, 'period': period, 'wall_seconds': seconds, 'children': {'collect': 0.1}, 'outcome': 'success',
            'history': {'WorkflowChildCall': 1, 'Attempts': 1}, 'load_at_start': [1.0, 1.0, 1.0]}


def invocation(command, walls, *, exit=0, outcome='success', selected=None, finish=0.0):
    """One engine call of a scenario report. `selected` is the member count of its frozen selection."""
    return {'command': command, 'run_id': 'r', 'exit': exit, 'outcome': outcome, 'result_ref': 'x', 'seconds': 1.0,
            'selected_members': len(walls) if selected is None else selected,
            'timings': [{'label': 'summarize', 'seconds': finish},
                        {'label': 'child', 'command': 'publish', 'step_id': 's', 'seconds': 999.0}],
            'members': [], 'walls': walls}


def sound_scenarios():
    """The four scenarios of a run that dispatched every member. The authority gate step exits 10 by design."""
    return {
        'open': [invocation('daily', [wall('2026-10-01', 4.0), wall('2026-10-02', 5.0)])],
        'closed': [invocation('backfill', [wall('2025Q1', 30.0, 'quarterly'), wall('2025Q2', 31.0, 'quarterly')],
                              finish=20.0),
                   invocation('daily', [wall('2026-12-01', 6.0), wall('2026-12-02', 7.0)], finish=10.0)],
        'authority': [invocation('daily', [wall('2026-07-01', 4.0), wall('2026-07-02', 5.0)]),
                      invocation('backfill', [wall('2026Q3', 900.0, 'quarterly')], exit=10,
                                 outcome='awaiting_approval')],
        'finish': [invocation('backfill', [wall('2026Q1', 8.0, 'quarterly')], finish=200.0)],
    }


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        self.measure = load()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)

    def summary(self, scenarios):
        for name, calls in scenarios.items():
            (self.work / f'{name}-report.json').write_text(json.dumps({
                'status': 'complete', 'release_id': 'r', 'scenarios': {name: {'invocations': calls}}}))
        return self.measure.summarize(self.work)

    def test_four_sound_scenarios_give_a_proposal(self):
        summary = self.summary(sound_scenarios())
        self.assertEqual(summary['measures']['incomplete_scenarios'], [])
        self.assertEqual(summary['measures']['incomplete_reasons'], {})
        self.assertEqual(summary['measures']['exits']['authority'], [0, 10])
        self.assertIsNotNone(summary['proposal'])

    def test_the_proposal_takes_the_largest_finish_cost_and_the_slowest_wall_of_all_scenarios(self):
        # Finish cost: closed 20 and 10, finish 200; the 999 s child timings are not finish labels.
        # Slowest wall: the authority quarterly member, 900 s, not the closed or open walls.
        proposal = self.summary(sound_scenarios())['proposal']
        self.assertEqual(proposal, self.measure.cost_proposal(200.0, 900.0))
        self.assertEqual((proposal['p4_floor_seconds'], proposal['reserve_seconds'],
                          proposal['slowest_member_wall_seconds']), (600, 1740, 900.0))

    def test_a_missing_member_wall_gives_no_proposal_and_names_the_scenario(self):
        for name, index in (('authority', 1), ('closed', 0), ('open', 0)):
            with self.subTest(scenario=name, step=index):
                scenarios = sound_scenarios()
                call = scenarios[name][index]
                scenarios[name][index] = {**call, 'walls': call['walls'][:-1], 'selected_members': len(call['walls'])}
                summary = self.summary(scenarios)
                self.assertEqual(summary['measures']['incomplete_scenarios'], [name])
                self.assertIn(f'step {index}', summary['measures']['incomplete_reasons'][name])
                self.assertIn('selected', summary['measures']['incomplete_reasons'][name])
                self.assertIsNone(summary['proposal'])

    def test_an_unexpected_exit_gives_no_proposal_and_names_the_scenario(self):
        cases = {
            'a failed finish step': ('finish', 0, {'exit': 20, 'outcome': 'failed'}),
            'a gate step that did not reach the gate': ('authority', 1, {'exit': 0, 'outcome': 'success'}),
            'a gate step with another outcome': ('authority', 1, {'outcome': 'failed'}),
            'the gate exit on the daily step': ('authority', 0, {'exit': 10, 'outcome': 'awaiting_approval'}),
        }
        for label, (name, index, changes) in cases.items():
            with self.subTest(label):
                scenarios = sound_scenarios()
                scenarios[name][index] = {**scenarios[name][index], **changes}
                summary = self.summary(scenarios)
                self.assertEqual(summary['measures']['incomplete_scenarios'], [name])
                self.assertIn(f'step {index}', summary['measures']['incomplete_reasons'][name])
                self.assertIsNone(summary['proposal'])

    def test_a_report_without_the_selected_member_count_gives_no_proposal(self):
        scenarios = sound_scenarios()
        scenarios['open'][0] = {key: value for key, value in scenarios['open'][0].items() if key != 'selected_members'}
        summary = self.summary(scenarios)
        self.assertEqual(summary['measures']['incomplete_scenarios'], ['open'])
        self.assertIsNone(summary['proposal'])

    def headed(self, changes=None):
        """Four sound reports with the same header, except `changes` for the `finish` report."""
        header = {'scale': 'smoke', 'release_id': 'r', 'inputs': {'quarterly_rows': 1000, 'daily_rows': 20},
                  'flags': {'isolated': 1, 'dont_write_bytecode': True, 'pycache_prefix': '/dev/null'}}
        for name, calls in sound_scenarios().items():
            report = {**header, 'status': 'complete', 'scenarios': {name: {'invocations': calls}}}
            if name == 'finish':
                report.update(changes or {})
            (self.work / f'{name}-report.json').write_text(json.dumps(report))
        return self.measure.summarize(self.work)

    def test_reports_with_one_header_give_a_proposal_and_name_their_scale(self):
        summary = self.headed()
        self.assertEqual((summary['scale'], summary['release_ids']), ('smoke', ['r']))
        self.assertIsNotNone(summary['proposal'])

    def test_reports_that_disagree_on_scale_release_flags_or_inputs_give_no_proposal(self):
        cases = {'scale': {'scale': 'full'}, 'release_id': {'release_id': 'other'},
                 'flags': {'flags': {'isolated': 0, 'dont_write_bytecode': True, 'pycache_prefix': '/dev/null'}},
                 'inputs': {'inputs': {'quarterly_rows': 370321, 'daily_rows': 20}}}
        for field, changes in cases.items():
            with self.subTest(field):
                summary = self.headed(changes)
                self.assertIsNone(summary['proposal'])
                self.assertEqual(summary['measures']['incomplete_scenarios'], ['open', 'closed', 'authority', 'finish'])
                for reason in summary['measures']['incomplete_reasons'].values():
                    self.assertIn(field, reason)


class HistoryCountsTests(unittest.TestCase):
    def setUp(self):
        self.measure = load()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        from sec_edgar_ingest.storage.local import LocalStateStore
        self.store = LocalStateStore(Path(directory.name))
        self.addCleanup(self.store.close)

    def test_workflow_child_calls_are_counted_in_their_own_partition(self):
        self.assertEqual(self.measure.history_counts(self.store.database), {'WorkflowChildCall': 0, 'Attempts': 0})
        self.store.insert('WorkflowChildCall', 'call-1', {'step': 'collect'})
        self.store.insert('WorkflowChildExecution', 'call-1', {'sequence': 0})
        self.store.insert('TransportAttempt', 'ordinal', {'outcome': 'uncertain'})
        self.assertEqual(self.measure.history_counts(self.store.database), {'WorkflowChildCall': 1, 'Attempts': 1})

    def test_a_child_call_row_of_another_namespace_is_not_counted(self):
        import sqlite3
        from contextlib import closing
        self.store.insert('WorkflowChildCall', 'call-1', {'step': 'collect'})
        with closing(sqlite3.connect(self.store.database)) as connection, connection:
            connection.execute("INSERT INTO records VALUES ('SourceState', 'other-namespace:WorkflowChildCall', 'k', '{}', 'v')")
        self.assertEqual(self.measure.history_counts(self.store.database)['WorkflowChildCall'], 1)

    def test_the_script_namespace_is_the_package_namespace(self):
        from sec_edgar_ingest.config import COORDINATION_NAMESPACE
        self.assertEqual(self.measure.COORDINATION_NAMESPACE, COORDINATION_NAMESPACE)


class RunScenarioReportTests(unittest.TestCase):
    """`run_scenario` writes its report whatever fails, with the engine stubbed out."""

    def setUp(self):
        self.measure = load()
        self.measure.instrument = lambda: None
        self.measure.instrument_members = lambda state: None
        self.measure.scenario = lambda *args, **kwargs: {'invocations': []}
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.manifest = self.work / 'release.json'
        self.manifest.write_text(json.dumps({'release_id': 'r'}))

    def report(self, name='open'):
        return json.loads((self.work / f'{name}-report.json').read_text())

    def test_a_normal_run_keeps_its_report_fields(self):
        self.measure.run_scenario('open', self.manifest, self.work, {'sources': {}}, 'smoke')
        report = self.report()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(sorted(report), [
            'ended_at', 'flags', 'format_version', 'inputs', 'kind', 'max_run_seconds', 'python', 'release_id',
            'scale', 'scenario', 'scenarios', 'started_at', 'status'])

    def test_a_failure_while_building_the_plan_leaves_a_failed_report(self):
        def broken(*args):
            raise RuntimeError('plan broke')
        self.measure.open_leaves = broken
        with self.assertRaises(RuntimeError):
            self.measure.run_scenario('open', self.manifest, self.work, {'sources': {}}, 'smoke')
        report = self.report()
        self.assertEqual((report['status'], report['release_id']), ('failed', 'r'))
        self.assertIn('plan broke', report['error'])

    def test_only_the_scenario_that_runs_builds_its_leaves(self):
        def broken(*args):
            raise RuntimeError('built a leaf set that this scenario does not use')
        self.measure.closed_leaves = self.measure.authority_leaves = self.measure.finish_leaves = broken
        self.measure.run_scenario('open', self.manifest, self.work, {'sources': {}}, 'smoke')
        self.assertEqual(self.report()['status'], 'complete')

    def test_a_failure_in_the_instrumentation_leaves_a_failed_report(self):
        def broken():
            raise RuntimeError('instrument broke')
        self.measure.instrument = broken
        with self.assertRaises(RuntimeError):
            self.measure.run_scenario('closed', self.manifest, self.work, {'sources': {}}, 'smoke')
        self.assertEqual(self.report('closed')['status'], 'failed')

    def test_a_failure_in_the_report_header_leaves_a_minimal_failed_report(self):
        with self.assertRaises(FileNotFoundError):
            self.measure.run_scenario('finish', self.work / 'missing.json', self.work, {'sources': {}}, 'smoke')
        report = self.report('finish')
        self.assertEqual((report['status'], report['kind'], report['scenario']), ('failed', 'scenario', 'finish'))
        self.assertIn('FileNotFoundError', report['error'])
        with self.assertRaises(KeyError):
            self.measure.run_scenario('authority', self.manifest, self.work, {}, 'smoke')
        self.assertEqual(self.report('authority')['status'], 'failed')


class WorkGuardTests(unittest.TestCase):
    """The guard runs against a temporary project root, so a failing guard never writes into the real `data/`."""

    def setUp(self):
        self.measure = load()
        self.assertEqual(self.measure.PROJECT_ROOT, SCRIPT.parents[1])  # The real root is the directory above scripts/.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = self.measure.PROJECT_ROOT = Path(directory.name).resolve()

    def refused(self, command, work):
        argv = ['summarize', '--work', str(work)] if command == 'summarize' else [
            'scenario', '--name', 'open', '--release-manifest', 'm', '--work', str(work), '--counts', 'c',
            '--scale', 'smoke']
        with self.assertRaises(SystemExit) as raised:
            self.measure.main(argv)
        return str(raised.exception.code)

    def test_work_under_tmp_is_still_refused(self):
        for command in ('summarize', 'scenario'):
            self.assertIn('not /tmp', self.refused(command, '/tmp/s1b-work'))

    def test_work_outside_the_project_root_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            for command in ('summarize', 'scenario'):
                with self.subTest(command):
                    self.assertIn('inside ' + str(self.root), self.refused(command, directory))

    def test_work_inside_the_live_data_directory_is_refused(self):
        for command in ('summarize', 'scenario'):
            with self.subTest(command):
                self.assertIn('not inside ' + str(self.root / 'data'),
                              self.refused(command, self.root / 'data' / 'sec' / 'work'))

    def test_work_inside_the_live_data_directory_in_another_case_is_refused(self):
        # APFS is case-insensitive, so `DATA/` is the live `data/` directory.
        for name in ('DATA/sec/work', 'Data'):
            with self.subTest(name):
                self.assertIn('not inside ' + str(self.root / 'data'), self.refused('summarize', self.root / name))

    def test_a_minimal_failed_report_is_summarized_with_its_reason(self):
        measure = self.measure
        measure.instrument = lambda: None
        measure.instrument_members = lambda state: None
        work = self.root / 'scratch' / 'work'
        work.mkdir(parents=True)
        with self.assertRaises(FileNotFoundError):  # `start_report` never returns, so the report has no release id.
            measure.run_scenario('finish', self.root / 'missing.json', work, {'sources': {}}, 'smoke')
        with contextlib.redirect_stdout(io.StringIO()):
            code = measure.main(['summarize', '--work', str(work)])
        summary = json.loads((work / 'measurement.json').read_text())
        self.assertEqual((code, summary['proposal'], summary['release_ids'], summary['scale']), (1, None, [], 'smoke'))
        self.assertIn('FileNotFoundError', summary['measures']['incomplete_reasons']['finish'])

    def test_work_inside_the_project_root_but_outside_data_is_accepted(self):
        for name in ('fixture-data/s1b-smoke', 'scratch/work'):
            self.assertEqual(self.measure.measurement_work(self.root / name), self.root / name)


if __name__ == '__main__':
    unittest.main()
