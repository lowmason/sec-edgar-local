"""Stage 1c §5 items 1 and 4: the member-completion conflict on the 1b release, and its repair on the 1c code.

The store has the shape of the live store at invocation 1: a finished standalone publish Attempt whose
input workset is incomplete (the L12 2024Q1 shape), then a daily workflow member that publishes.
"""
from network_guard import install
install()

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from support import fixture_settings
from support_process import CheckedRunner
from support_workflows import BASE, CommandHarness, idx, replace_pack_body, simple_pack
from sec_edgar_ingest.config import Settings
from sec_edgar_ingest.etl.contracts import decode_transformed
from sec_edgar_ingest.models import canonical_json, to_mapping_value
from sec_edgar_ingest.runtime import isolated_environment, native_python_argv
from sec_edgar_ingest.workflows.completion import evaluate_member
from sec_edgar_ingest.workflows.contracts import COMPLETE
from sec_edgar_ingest.workflows.members import WorkflowMembers
from sec_edgar_ingest.workflows.results import read_workflow_result

TODAY = date(2026, 10, 7)


class MemberCompletionReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support_release import ONE_B_REVISION, origin_release, proof_releases
        from sec_edgar_ingest.runtime import preflight
        project = Path(__file__).resolve().parents[3]
        cache = project / 'releases/artifact-cache'
        # Plan 6 P2: the gate builds the 1b application from its revision. The evidence run sets
        # SEC_LOCAL_1B_RELEASE to the installed release.json of 9fa189a0… instead.
        installed = os.environ.get('SEC_LOCAL_1B_RELEASE')
        cls.one_b = preflight(Path(installed)) if installed else origin_release(project, cache, revision=ONE_B_REVISION)
        _, cls.current = proof_releases(project, cache)

    def scratch(self):
        """A temporary root whose cleanup runs after the harness stores close (addCleanup is LIFO)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def poisoned(self):
        """A store with a finished standalone publish whose input is incomplete, and a clean daily source."""
        root = self.scratch()
        pack = simple_pack(root / 'pack')
        for quarter, day in ((3, '2026-07-01'), (4, '2026-10-01')):
            archive = f'edgar/data/123456/0000123456-26-00000{quarter}.txt'
            rows = (('123456', 'Example', '10-K', day, archive), ('123456', 'Changed', '10-K', day, archive))
            replace_pack_body(pack, BASE + f'full-index/2026/QTR{quarter}/master.zip', idx(rows, 'quarterly'))
        settings = fixture_settings(backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        h = CommandHarness(root, pack, settings)
        self.addCleanup(h.close)
        code, found = h.invoke('discover', ('--mode', 'quarterly', '--discovery-id', 'l12-shape'), run='l12-find')
        self.assertEqual(code, 0, h.calls[-1])
        code, collected = h.invoke('collect', ('--workset', found['source_workset_ref']), run='l12-collect')
        self.assertEqual(code, 0, h.calls[-1])
        code, transformed = h.invoke('transform', ('--workset', collected['snapshot_workset_ref']), run='l12-transform')
        self.assertEqual((code, transformed['outcome']), (7, 'invalid_source'), h.calls[-1])
        ref = transformed['transformed_workset_ref']
        workset = decode_transformed(h.objects.read(ref))
        self.assertEqual((workset.complete, len(workset.observations)), (False, 0))
        code, published = h.invoke('publish', ('--workset', ref), run='l12-publish')
        self.assertEqual((code, published['outcome']), (3, 'incomplete'), h.calls[-1])
        attempt = next(r.to_mapping()['value'] for r in h.store.scan('Attempt', {})
                       if r.to_mapping()['value']['context']['run_id'] == 'l12-publish')
        self.assertEqual((attempt['result']['outcome'], attempt['result']['quarters']), ('incomplete', []))
        self.assertEqual(self.pointers(h), [])
        return h

    def release_run(self, h, release, run_id):
        """One `daily` workflow parent in the release's own installed interpreter."""
        value = h.settings.to_mapping()
        value['runtime'] = {'kind': 'native', 'release_manifest': str(release.directory / 'release.json')}
        config = h.root / (run_id + '.json')
        config.write_bytes(canonical_json(to_mapping_value(Settings.from_mapping(value).to_mapping())))
        deadline = datetime.now(timezone.utc) + timedelta(seconds=1800)
        argv = [*native_python_argv(release.python), '-m', 'sec_edgar_ingest', 'daily',
                '--config', str(config), '--run-id', run_id, '--execution-id', 'manual', '--attempt-id', 'a',
                '--deadline', deadline.isoformat(), '--today', TODAY.isoformat(), '--fixture-pack', str(h.pack)]
        result = CheckedRunner()(release.python, argv, deadline=deadline, environ=isolated_environment())
        return result.returncode, json.loads(result.stdout.decode().splitlines()[-1])

    def versions(self, h):
        return h.settings.etl.parser_version, h.settings.etl.schema_version

    def pointers(self, h):
        return [row.to_mapping() for row in h.store.scan('QuarterPublication', {})]

    def quarters(self, h):
        return sorted(row.to_mapping()['value']['quarter'] for row in h.store.scan('QuarterPublication', {}))

    def receipts(self, h, value):
        """Receipt rows, counted directly: `WorkflowMembers.completed` raises on a poisoned store (plan 6 F3)."""
        parser, schema = self.versions(h)
        return len(tuple(h.store.scan('WorkflowMemberResult', {'member_id': value['member_id'],
                                                               'parser_version': parser, 'schema_version': schema})))

    def daily_member(self, h):
        values = [v for v in WorkflowMembers(h.store, h.objects).inventory()[0] if v['source']['kind'] == 'daily']
        self.assertEqual(len(values), 1, values)
        return values[0]

    def test_the_1b_release_halts_after_its_publish_moves_a_pointer(self):
        """§5 item 1, first half: on the 1b release the member's publish moves 2026Q4, then the run halts."""
        h = self.poisoned()
        code, message = self.release_run(h, self.one_b, 'one-b')
        self.assertEqual((code, message['outcome'], message['result_ref']), (9, 'state_conflict', None), message)
        value = self.daily_member(h)
        self.assertEqual(self.quarters(h), ['2026Q4'])
        self.assertEqual(self.receipts(h, value), 0)

    def test_the_1c_code_completes_the_member_on_the_same_store(self):
        """§5 item 1, second half: the 1c code completes the member with all affected quarter evidence."""
        h = self.poisoned()
        code, message = self.release_run(h, self.current, 'one-c')
        self.assertNotEqual(code, 9, message)
        report = read_workflow_result(message['result_ref'], h.store, h.objects)
        value = self.daily_member(h)
        member = next(m for m in report.members if m.member_id == value['member_id'])
        self.assertIn(member.outcome, COMPLETE)
        self.assertEqual(self.receipts(h, value), 1)
        self.assertEqual(self.quarters(h), ['2026Q4'])
        capture = next(c for c in report.intent['completion_captures'] if c['member']['member_id'] == value['member_id'])
        self.assertEqual(list(capture['affected_quarters']), ['2026Q4'])
        self.assertEqual([q['quarter'] for q in capture['quarters']], ['2026Q4'])

    def test_a_1c_rerun_completes_the_halted_member_and_moves_no_pointer(self):
        """§5 item 4 and M5: the store that the 1b release left, re-run on the 1c code."""
        h = self.poisoned()
        code, _ = self.release_run(h, self.one_b, 'one-b')
        self.assertEqual(code, 9)
        value = self.daily_member(h)
        pointers = self.pointers(h)
        self.assertEqual(len(pointers), 1)
        self.assertEqual(self.receipts(h, value), 0)
        code, message = self.release_run(h, self.current, 'repair')
        self.assertNotEqual(code, 9, message)
        # M5: no pointer moves a second time, and the member's capture is under already_complete.
        self.assertEqual(self.pointers(h), pointers)
        report = read_workflow_result(message['result_ref'], h.store, h.objects)
        self.assertIn(value['source']['source_id'], report.intent['already_complete_sources'])
        selection = json.loads(h.objects.read(report.intent['selection']['ref']))
        self.assertIn(value['member_id'], [c['member']['member_id'] for c in selection['already_complete']])
        self.assertEqual(tuple(h.store.scan('WorkflowRepairObligation', {})), ())
        self.assertFalse((Path(h.settings.storage.root) / 'objects/worksets/sec/workflow-repair-authority').exists())
        self.assertTrue(evaluate_member(value, *self.versions(h), h.store, h.objects).complete)
        # Spec §4.2 path (plan 6 P7): the member is selected as complete, so no child runs and no receipt is written.
        self.assertNotIn(value['member_id'], [job['member']['member_id'] for job in selection['jobs']])
        self.assertNotIn(value['member_id'], [m.member_id for m in report.members])
        self.assertEqual(self.receipts(h, value), 0)


if __name__ == '__main__':
    unittest.main()
