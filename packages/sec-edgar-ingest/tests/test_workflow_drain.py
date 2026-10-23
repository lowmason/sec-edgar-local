"""Stage 1a: the dispatch cutoff (B3) and the sibling-completion skip (B4-B6)."""
from network_guard import install
install()

import hashlib, json, tempfile, unittest
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from support import fixture_settings
from support_process import checked_dispatcher as Dispatcher
from support_workflows import CommandHarness, quarter_pack, simple_pack
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.etl.reader import capture_quarter
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.models import Error, RunContext, canonical_json, to_mapping_value
from sec_edgar_ingest.runtime import configured_descriptor
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows.contracts import COMPLETE, LOCAL_CONTRACT, workflow_path
from sec_edgar_ingest.workflows.members import WorkflowMembers
from sec_edgar_ingest.workflows.results import freeze_workflow, read_workflow_result, write_workflow_result
from sec_edgar_ingest.workflows.runner import run_workflow

RESERVE = 600
TODAY = date(2026, 10, 7)


class MemberBudget:
    """Stands in for runner.datetime.now: the first `allowed` checks see the start, later ones the cutoff."""
    def __init__(self, context, allowed, reserve=RESERVE):
        self.start, self.cutoff = context.started_at, context.deadline - timedelta(seconds=reserve)
        self.allowed, self.calls = allowed, 0

    def now(self, tz=None):
        self.calls += 1
        return self.start if self.calls <= self.allowed else self.cutoff


def harness(root, pack, reserve=RESERVE, start='2026Q3'):
    execution = {'max_run_seconds': 3600}
    if reserve is not None:
        execution['dispatch_reserve_seconds'] = reserve
    settings = fixture_settings(root=root / '.fixture-state',
        backfill={'start_quarter': start, 'end_quarter': 'open'},
        etl={'parser_version': 'fixture-index-parser-v1'},
        fixture={'allow_clock_override': True, 'allow_deadline_override': False},
        execution=execution)
    return CommandHarness(root, pack, settings)


def widen(pack, times):
    """Repeat every fixture response, so many discoveries can read the same listings."""
    manifest = json.loads(pack.read_text())
    manifest['responses'] = {url: responses * times for url, responses in manifest['responses'].items()}
    pack.write_bytes(canonical_json(to_mapping_value(manifest)))
    return pack


def run(h, run_id, allowed):
    now = datetime.now(timezone.utc)
    context = RunContext(run_id, 'manual', 'backfill', 'a', h.settings.etl.parser_version,
        h.settings.etl.schema_version, h.settings.config_sha256, now, now + timedelta(seconds=1800), 'backfill',
        runtime=configured_descriptor(h.settings), format_version='sec-local-run-context-v1')
    context = pin_context(h.settings, context, TODAY)[0]
    intent = {'contract_version': LOCAL_CONTRACT, 'command': 'backfill', 'today': TODAY.isoformat(),
              'fixture_sha256': hashlib.sha256(h.pack.read_bytes()).hexdigest(), 'pinned_end_quarter': '2026Q4'}
    context = freeze_workflow(context, intent, h.store, h.objects)
    dispatcher = Dispatcher(context, h.settings, h.pack, h.root, h.store, h.objects)
    budget, steps = MemberBudget(context, allowed), []
    execute = dispatcher.execute
    def counted(command, step_id, settings, flags):
        steps.append(step_id)
        return execute(command, step_id, settings, flags)
    with patch('sec_edgar_ingest.workflows.runner.datetime', wraps=datetime) as clock, \
            patch.object(dispatcher, 'execute', side_effect=counted):
        clock.now.side_effect = budget.now
        report = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
    path = write_workflow_result(report, h.store, h.objects)
    if read_workflow_result(path, h.store, h.objects) != report:
        raise AssertionError('written workflow result does not read back')
    return report, steps


class CutoffTests(unittest.TestCase):
    def test_members_after_the_cutoff_defer_and_the_result_is_written_before_the_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, simple_pack(root / 'pack'))
            try:
                report, steps = run(h, 'cutoff', allowed=1)
                first, second = report.members
                # The first member's children run while the cutoff passes; the member still completes.
                self.assertIn(first.outcome, COMPLETE)
                self.assertEqual(second.outcome, 'pending')
                self.assertEqual([gap.code for gap in second.gaps], ['workflow_deferred'])
                self.assertEqual(second.child_refs, ())
                self.assertFalse(any(step.endswith(second.member_id) for step in steps))
                self.assertLess(datetime.fromisoformat(report.ended_at), report.context.deadline)
                self.assertEqual(report.outcome, 'incomplete')
            finally:
                h.close()

    def test_a_missing_reserve_keeps_the_deadline_as_the_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, simple_pack(root / 'pack'), reserve=None)
            try:
                # The budget reports deadline - RESERVE after its first check: still before a deadline cutoff.
                report, _ = run(h, 'no-reserve', allowed=1)
                self.assertTrue(all(member.outcome in COMPLETE for member in report.members))
            finally:
                h.close()


def child_counts(h, steps):
    """Child sequences per (command, source), from dispatched step IDs."""
    source_of = {v['member_id']: v['source']['source_id'] for v in WorkflowMembers(h.store, h.objects).inventory()[0]}
    counts = Counter()
    for step in steps:
        command, _, member_id = step.partition('-')
        if command in ('collect', 'transform', 'publish'):
            counts[command, source_of[member_id]] += 1
    return counts, set(source_of.values())


class SiblingCompletionTests(unittest.TestCase):
    def pair(self, h, name):
        """Defer every member once, then run with room: each source has a retained and a new member."""
        run(h, name + '-0', allowed=0)
        return run(h, name + '-1', allowed=10)

    def test_pending_sources_drain_with_one_child_sequence_each(self):
        periods = ('2025Q1', '2025Q2', '2025Q3', '2025Q4', '2026Q1', '2026Q2', '2026Q3', '2026Q4')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, widen(quarter_pack(root / 'pack', periods), 4), start='2025Q1')
            try:
                first, steps = run(h, 'drain-0', allowed=0)
                self.assertEqual(steps, ['discover'])
                self.assertEqual(first.counts['pending_sources'], 8)
                runs = 1
                while True:
                    # An odd budget makes cutoffs fall inside same-source pairs (plan 4 F-P2).
                    report, more = run(h, f'drain-{runs}', allowed=5)
                    steps.extend(more)
                    runs += 1
                    if not any(gap.code == 'workflow_deferred' for member in report.members for gap in member.gaps):
                        break
                    self.assertLess(runs, 20, 'the drain made no progress')
                self.assertGreater(runs, 2)
                counts, sources = child_counts(h, steps)
                self.assertEqual(len(sources), 8)
                for source_id in sources:
                    for command in ('collect', 'transform', 'publish'):
                        with self.subTest(source=source_id, command=command):
                            self.assertEqual(counts[command, source_id], 1)
                for period in periods:
                    self.assertIsNotNone(capture_quarter(period, h.objects, EtlState(h.store)))
                self.assertIn(report.outcome, ('success', 'unchanged'))
            finally:
                h.close()

    def test_sibling_receipt_shape_capture_and_exact_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, widen(simple_pack(root / 'pack'), 4))
            try:
                report, steps = self.pair(h, 'pair')
                self.assertEqual(len(report.members), 4)
                skipped = [member for member in report.members if not member.child_refs]
                self.assertEqual(len(skipped), 2)
                registry = WorkflowMembers(h.store, h.objects)
                values = {v['member_id']: v for v in registry.inventory()[0]}
                receipts = {}
                for member in skipped:
                    self.assertEqual((member.outcome, member.snapshot_ref, member.transformed_ref),
                                     ('unchanged', None, None))
                    self.assertFalse(member.downloaded or member.transformed or member.quarantined or member.gaps)
                    self.assertTrue(member.quarters)
                    self.assertTrue(all(q.outcome == 'unchanged' and q.candidate_ref is None and q.conflicts == 0
                                        for q in member.quarters))
                    self.assertFalse(any(step.endswith(member.member_id) for step in steps))
                    capture = registry.completed(values[member.member_id], member.parser_version, member.schema_version)
                    self.assertEqual([(q['quarter'], q['generation_id']) for q in capture['quarters']],
                                     [(q.quarter, q.generation_id) for q in member.quarters])
                    path = registry._path(member.member_id, report.context)
                    receipts[path] = h.objects.read(path)
                    self.assertEqual(registry._read_receipt(path)[2]['calls'], [])
                dispatcher = Dispatcher(report.context, h.settings, h.pack, h.root, h.store, h.objects)
                with patch.object(dispatcher, 'execute', side_effect=AssertionError('replay dispatched a child')), \
                        patch('sec_edgar_ingest.workflows.runner.reuse_exact_binding',
                              side_effect=AssertionError('replay decided a skip again')):
                    replay = run_workflow(report.context, h.settings, to_mapping_value(report.intent['invocation']),
                                          dispatcher, h.store, h.objects)
                self.assertEqual((replay.intent, replay.members, replay.outcome, replay.counts),
                                 (report.intent, report.members, report.outcome, report.counts))
                for path, body in receipts.items():
                    self.assertEqual(h.objects.read(path), body)
                self.assertEqual(read_workflow_result(workflow_path(report.context), h.store, h.objects), report)
            finally:
                h.close()

    def test_sibling_receipt_shape_is_exact(self):
        from sec_edgar_ingest.workflows.processing import validate_member_evidence
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, widen(simple_pack(root / 'pack'), 4))
            try:
                report, _ = self.pair(h, 'shape')
                member = next(m for m in report.members if not m.child_refs)
                registry = WorkflowMembers(h.store, h.objects)
                result, _, evidence, _ = registry._read_receipt(registry._path(member.member_id, report.context))
                first = result.quarters[0]
                for change in ({'outcome': 'success'}, {'downloaded': True}, {'transformed': True},
                               {'quarters': (replace(first, outcome='published'),) + result.quarters[1:]}):
                    with self.subTest(result=change), self.assertRaises(ValueError):
                        replace(result, **change)
                evidence = to_mapping_value(evidence)
                tampered = (
                    ({'gaps': (Error('state_conflict', 'invented', False, result.source.source_id, {}),)}, {}),
                    ({'quarters': (replace(first, generation_id='0' * 64),) + result.quarters[1:]}, {}),
                    ({'quarters': (replace(first, conflicts=1),) + result.quarters[1:]}, {}),
                    ({}, {'completion': None}),
                    ({}, {'resolutions': [{'ref': 'invented'}]}),
                )
                for result_change, evidence_change in tampered:
                    with self.subTest(result=result_change, evidence=evidence_change), self.assertRaises(Conflict):
                        validate_member_evidence(replace(result, **result_change), {**evidence, **evidence_change}, h.objects)
            finally:
                h.close()

    def test_refusals_leave_the_member_to_its_child_sequence(self):
        from contextlib import nullcontext
        from sec_edgar_ingest.workflows import runner
        from sec_edgar_ingest.workflows.contracts import CompletionEvaluation
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, widen(simple_pack(root / 'pack'), 4))
            try:
                report, _ = self.pair(h, 'refuse')
                done = next(m for m in report.members if m.child_refs)
                other = next(m for m in report.members if m.source.source_id != done.source.source_id)
                values = WorkflowMembers(h.store, h.objects).inventory()[0]
                sibling = next(v for v in values
                               if v['source']['source_id'] == done.source.source_id and v['member_id'] != done.member_id)
                identity = done.source.source_id
                conflict = Error('state_conflict', 'corrupt sibling evidence', False, identity, {})
                unpinned = Error('acquisition_pending', 'member has no exact raw pin', True, identity, {})
                cases = {
                    'no preceding member, source not already complete': {'previous': None},
                    'preceding member of another source': {'previous': other},
                    'failed sibling': {'previous': replace(done, outcome='state_conflict')},
                    'pending sibling': {'previous': replace(done, outcome='pending')},
                    'binding gap': {'reuse': (conflict,)},
                    'divergent or missing binding': {'evaluation': CompletionEvaluation(False, None, (), (unpinned,))},
                    'repair obligation': {'evaluation': CompletionEvaluation(False, None, ({'ref': 'obligation'},), ())},
                    'corrupt evidence': {'evaluation': CompletionEvaluation(False, None, (), (conflict,))},
                }
                for name, case in cases.items():
                    evaluation = (patch.object(runner, 'evaluate_member', return_value=case['evaluation'])
                                  if 'evaluation' in case else nullcontext())
                    with self.subTest(case=name), evaluation, \
                            patch.object(runner, 'reuse_exact_binding', return_value=case.get('reuse', ())):
                        before = tuple(h.store.scan('WorkflowMemberResult', {}))
                        self.assertIsNone(runner.sibling_completion(sibling, case.get('previous', done), frozenset(),
                                                                    report.context, h.store, h.objects))
                        self.assertEqual(tuple(h.store.scan('WorkflowMemberResult', {})), before)
                # Positive controls: a complete preceding sibling, and a source already complete at selection.
                for previous, completed in ((done, frozenset()), (None, frozenset({identity}))):
                    with self.subTest(previous=previous is not None):
                        processed = runner.sibling_completion(sibling, previous, completed, report.context, h.store, h.objects)
                        self.assertEqual((processed.result.outcome, processed.result.child_refs), ('unchanged', ()))
            finally:
                h.close()


if __name__ == '__main__':
    unittest.main()
