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


if __name__ == '__main__':
    unittest.main()
