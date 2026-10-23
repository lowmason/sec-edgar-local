"""Stage 1a §5 item 6: the current code continues fc68adef…-origin pending work, and fc68adef… meets a B4 receipt."""
from network_guard import install
install()

import hashlib, json, subprocess, tempfile, unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from support import fixture_settings
from support_process import CheckedRunner
from support_workflows import BASE, CommandHarness, simple_pack
from sec_edgar_ingest.config import Settings, pin_context
from sec_edgar_ingest.models import RunContext, canonical_json, to_mapping_value
from sec_edgar_ingest.runtime import configured_descriptor, isolated_environment, native_python_argv
from sec_edgar_ingest.workflows.checked import Dispatcher
from sec_edgar_ingest.workflows.contracts import COMPLETE, LOCAL_CONTRACT
from sec_edgar_ingest.workflows.members import WorkflowMembers
from sec_edgar_ingest.workflows.results import freeze_workflow, read_workflow_result, write_workflow_result
from sec_edgar_ingest.workflows.runner import run_workflow

TODAY = date(2026, 10, 7)
BLOCKED = BASE + 'full-index/2026/QTR3/master.zip'


class OriginReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support_release import origin_release, proof_releases
        project = Path(__file__).resolve().parents[3]
        cls.origin = origin_release(project, project / 'releases/artifact-cache')
        _, cls.current = proof_releases(project, project / 'releases/artifact-cache')

    def configured(self, h, release):
        value = h.settings.to_mapping()
        value['runtime'] = {'kind': 'native', 'release_manifest': str(release.directory / 'release.json')}
        return Settings.from_mapping(value)

    def origin_run(self, h, settings, run_id):
        """The whole backfill parent runs in the origin release's own installed interpreter."""
        config = h.root / (run_id + '.json')
        config.write_bytes(canonical_json(to_mapping_value(settings.to_mapping())))
        deadline = datetime.now(timezone.utc) + timedelta(seconds=1800)
        argv = [*native_python_argv(self.origin.python), '-m', 'sec_edgar_ingest', 'backfill',
                '--config', str(config), '--run-id', run_id, '--execution-id', 'manual', '--attempt-id', 'a',
                '--deadline', deadline.isoformat(), '--today', TODAY.isoformat(), '--fixture-pack', str(h.pack)]
        result = CheckedRunner()(self.origin.python, argv, deadline=deadline, environ=isolated_environment())
        return result.returncode, json.loads(result.stdout.decode().splitlines()[-1])

    def current_run(self, h, settings, run_id):
        now = datetime.now(timezone.utc)
        context = RunContext(run_id, 'manual', 'backfill', 'a', settings.etl.parser_version, settings.etl.schema_version,
            settings.config_sha256, now, now + timedelta(seconds=1800), 'backfill',
            runtime=configured_descriptor(settings), format_version='sec-local-run-context-v1')
        context = pin_context(settings, context, TODAY)[0]
        intent = {'contract_version': LOCAL_CONTRACT, 'command': 'backfill', 'today': TODAY.isoformat(),
                  'fixture_sha256': hashlib.sha256(h.pack.read_bytes()).hexdigest(), 'pinned_end_quarter': '2026Q4'}
        context = freeze_workflow(context, intent, h.store, h.objects)
        dispatcher = Dispatcher(context, settings, h.pack, h.root, h.store, h.objects, child_runner=CheckedRunner())
        steps, execute = [], dispatcher.execute
        def counted(command, step_id, child_settings, flags):
            steps.append((step_id, child_settings.runtime.release_manifest))
            return execute(command, step_id, child_settings, flags)
        dispatcher.execute = counted
        report = run_workflow(context, settings, intent, dispatcher, h.store, h.objects)
        path = write_workflow_result(report, h.store, h.objects)
        self.assertEqual(read_workflow_result(path, h.store, h.objects), report)
        return report, steps

    def continued(self, root):
        """The origin run halts on a 403 and leaves pending work; the current code then drains it.

        The current config carries no reserve key, so its receipts differ from the origin's only by
        the B4 shape (the key is tested separately below).
        """
        pack = simple_pack(root / 'pack')
        manifest = json.loads(pack.read_text())
        served = manifest['responses'][BLOCKED]
        manifest['responses'][BLOCKED] = [dict(response, status=403) for response in served]
        pack.write_bytes(canonical_json(to_mapping_value(manifest)))
        h = CommandHarness(root, pack)
        self.addCleanup(h.close)
        origin, current = self.configured(h, self.origin), self.configured(h, self.current)
        _, message = self.origin_run(h, origin, 'origin')
        self.assertEqual(message['outcome'], 'access_blocked', message)
        origin_members = {v['member_id'] for v in WorkflowMembers(h.store, h.objects).inventory()[0]}
        self.assertEqual(len(origin_members), 2)
        manifest['responses'][BLOCKED] = served
        pack.write_bytes(canonical_json(to_mapping_value(manifest)))
        report, steps = self.current_run(h, current, 'current')
        return h, origin, origin_members, report, steps

    def test_current_code_continues_origin_pending_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, _, origin_members, report, steps = self.continued(Path(tmp))
            self.assertIn(report.outcome, ('success', 'unchanged'))
            self.assertTrue(all(member.outcome in COMPLETE for member in report.members))
            self.assertTrue(origin_members <= {member.member_id for member in report.members})
            self.assertEqual(sum(1 for member in report.members if not member.child_refs), 2)
            source_of = {v['member_id']: v['source']['source_id'] for v in WorkflowMembers(h.store, h.objects).inventory()[0]}
            counts = Counter((step.partition('-')[0], source_of[step.partition('-')[2]]) for step, _ in steps
                             if step.partition('-')[0] in ('collect', 'transform', 'publish'))
            for source_id in set(source_of.values()):
                for command in ('collect', 'transform', 'publish'):
                    self.assertEqual(counts[command, source_id], 1, (command, source_id))
            origin_manifest = str(self.origin.directory / 'release.json')
            current_manifest = str(self.current.directory / 'release.json')
            for step, manifest in steps:
                command, _, member_id = step.partition('-')
                if command == 'collect':
                    # Collection stays bound to the release that discovered the member.
                    self.assertEqual(manifest, origin_manifest if member_id in origin_members else current_manifest)
                elif command in ('transform', 'publish'):
                    self.assertEqual(manifest, current_manifest)

    def test_origin_release_reports_a_b4_receipt_as_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, origin, _, report, _ = self.continued(Path(tmp))
            skipped = sorted(member.member_id for member in report.members if not member.child_refs)
            self.assertEqual(len(skipped), 2)
            code, message = self.origin_run(h, origin, 'origin-again')
            self.assertEqual((code, message['outcome']), (3, 'incomplete'), message)
            result = json.loads(h.objects.read(message['result_ref']))
            unresolved = sorted(gap['details']['member_id'] for gap in result['gaps']
                                if gap['code'] == 'legacy_member_unresolved')
            self.assertEqual(unresolved, skipped)

    def test_origin_settings_refuse_the_reserve_key(self):
        value = fixture_settings().to_mapping()
        value['execution']['dispatch_reserve_seconds'] = 600
        script = ('import json, sys\nfrom sec_edgar_ingest.config import Settings\n'
                  'Settings.from_mapping(json.loads(sys.argv[1]))\n')
        result = subprocess.run([*native_python_argv(self.origin.python), '-c', script, json.dumps(value)],
                                capture_output=True, text=True, env=isolated_environment())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown keys: ['dispatch_reserve_seconds']", result.stderr)


if __name__ == '__main__':
    unittest.main()
