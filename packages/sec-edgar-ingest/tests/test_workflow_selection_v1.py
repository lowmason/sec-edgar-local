# tests/test_workflow_selection_v1.py
"""Stored `sec-workflow-selection-v1` selections stay readable (plan 8).

The plan-5 proof bundle committed under specs/evidence holds real v1 selections, reports and
the state rows that index them. Every test opens a temporary copy: reading a report repairs
index rows, and opening the local store sets WAL mode, so the committed bundle must stay untouched.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from sec_edgar_ingest.config import Settings
from sec_edgar_ingest.models import RunContext, parse_json
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.storage.local import LocalObjectStore, LocalStateStore
from sec_edgar_ingest.workflows.results import freeze_selection, read_workflow_result
from sec_edgar_ingest.workflows.runner import run_workflow

EVIDENCE = (Path(__file__).resolve().parents[3] / 'specs/evidence/sec-filing-index-ingestion/stage-4/plan5-execution'
            '/final-verification-refresh/installed/installed-sequence/work/.fixture-state')
V1, V2 = 'sec-workflow-selection-v1', 'sec-workflow-selection-v2'
# (run, command, outcome the stored report recorded): proof workflows with a member run, a daily
# overlap, and a repeat whose two members were already complete.
RUNS = (('proof-baseline', 'backfill', 'success'), ('proof-overlap', 'daily', 'success'),
        ('proof-repeat', 'backfill', 'unchanged'))


class StoredV1SelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name) / '.fixture-state'
        shutil.copytree(EVIDENCE, root)
        # The saved owner binding names the bundle's original root, so reopen the copy under that binding.
        binding = json.loads(next((root / 'objects/locks').glob('**/binding.json')).read_bytes())
        self.store, self.objects = LocalStateStore(root, binding=binding), LocalObjectStore(root, binding=binding)
        self.addCleanup(self.store.close)

    def stored(self, run, command):
        base = f'runs/sec/{run}/{command}/a/'
        intent = parse_json(self.objects.read(base + 'intent.json'))
        body = self.objects.read(base + 'selection.json')
        return base, RunContext.from_mapping(intent['context']), intent['intent'], body

    def test_the_bundle_holds_v1_selections_without_superseded(self):
        for run, command, _ in RUNS:
            with self.subTest(run=run):
                selection = parse_json(self.stored(run, command)[3])
                self.assertEqual(selection['format_version'], V1)
                self.assertNotIn('superseded', selection)

    def test_stored_v1_reports_are_readable(self):
        for run, command, outcome in RUNS:
            with self.subTest(run=run):
                base = self.stored(run, command)[0]
                self.assertEqual(read_workflow_result(base + 'result.json', self.store, self.objects).outcome, outcome)

    def test_stored_v1_selection_replays_without_rewriting_it(self):
        for run, command, outcome in RUNS:
            with self.subTest(run=run):
                base, context, intent, body = self.stored(run, command)
                frozen = freeze_selection(context, parse_json(body), self.store, self.objects)
                self.assertEqual(frozen, parse_json(body))
                # Every member already has its receipt (or the selection has none), so nothing dispatches.
                settings = Settings.from_mapping(context.to_mapping()['effective_config'])
                replayed = run_workflow(context, settings, intent, None, self.store, self.objects)
                self.assertEqual(replayed.outcome, outcome)
                self.assertEqual(self.objects.read(base + 'selection.json'), body)

    def test_a_v1_selection_may_not_carry_superseded(self):
        base, context, _, body = self.stored('proof-repeat', 'backfill')
        with self.assertRaisesRegex(Conflict, 'selection differs from frozen workflow intent'):
            freeze_selection(context, {**parse_json(body), 'superseded': []}, self.store, self.objects)
        self.assertEqual(self.objects.read(base + 'selection.json'), body)

    def test_a_v2_selection_must_carry_superseded(self):
        base, context, _, body = self.stored('proof-repeat', 'backfill')
        with self.assertRaisesRegex(Conflict, 'selection differs from frozen workflow intent'):
            freeze_selection(context, {**parse_json(body), 'format_version': V2}, self.store, self.objects)
        self.assertEqual(self.objects.read(base + 'selection.json'), body)

    def test_unknown_formats_are_refused(self):
        _, context, _, body = self.stored('proof-repeat', 'backfill')
        for label, version in (('future', 'sec-workflow-selection-v3'), ('not a string', ['v1']), ('missing', None)):
            with self.subTest(label):
                selection = {**parse_json(body), 'format_version': version}
                if version is None:
                    del selection['format_version']
                with self.assertRaisesRegex(Conflict, 'selection differs from frozen workflow intent'):
                    freeze_selection(context, selection, self.store, self.objects)


if __name__ == '__main__':
    unittest.main()
