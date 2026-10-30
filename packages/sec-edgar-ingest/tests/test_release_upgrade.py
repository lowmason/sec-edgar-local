"""Real committed native A/B installations are the upgrade integration oracle."""
from network_guard import install
install()

import tempfile
import os
import shutil
import json
import unittest
from pathlib import Path


class ReleaseUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support_release import proof_releases
        project = Path(__file__).resolve().parents[3]
        cls.a, cls.b = proof_releases(project, project / 'releases/artifact-cache')

    def test_selected_installed_release_runs_independent_native_verifier(self):
        import locked_proof
        self.assertTrue(callable(getattr(locked_proof, 'verify_native_release', None)),
                        'native verifier must exercise selected installed Python outside the checkouts')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = locked_proof.verify_native_release(self.b, Path(__file__).parent, root / 'evidence')
            self.assertEqual(report['exit'], 0)
            self.assertEqual(report['release_id'], self.b.release_id)
            self.assertFalse(report['pythonpath_present'])
            self.assertEqual(report['sequence']['exit'], 0)
            self.assertIn('checkout_guard', report)
            guard = report['checkout_guard']
            self.assertEqual(guard['policy']['releases'], [str(self.b.directory)])
            self.assertFalse(guard['application_imported'])
            self.assertEqual(guard['denied'], [True] * 6)

    def test_installed_http_spawn_guards_main_before_transport_class_unpickle(self):
        import subprocess
        from workflow_proof import harness_files
        from network_guard import write_checkout_policy
        from sec_edgar_ingest.runtime import native_python_argv, isolated_environment
        with tempfile.TemporaryDirectory(prefix='sec-installed-http-audit-') as directory:
            root = Path(directory)
            harness = root / 'harness'
            for source in harness_files():
                target = harness / source.relative_to(Path(__file__).parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            write_checkout_policy(harness, {'version': 'sec-checkout-policy-v1',
                                           'releases': [str(self.b.directory)]})
            script = root / 'http_probe.py'
            script.write_text('import sys;sys.path.insert(0,' + repr(str(harness)) + ')\n' + '''
from network_guard import install,checkout_evidence,checkout_policy
install()
import json,os,pathlib
root=pathlib.Path(__file__).parent
def record(value):
    with (root/'order.jsonl').open('a') as stream:stream.write(json.dumps(value)+'\\n')
record({'event':'main-before-application',**checkout_evidence()})
def exchange(transport,cancellation,channel):
    import sec_edgar_ingest.download as download
    record({'event':'http-target','pid':os.getpid(),'policy':checkout_policy(),'origin':download.__file__})
    return download._child_exchange(transport,cancellation,channel)
if __name__=='__main__':
    import multiprocessing
    from sec_edgar_ingest.coordination import Clock
    from support import LoopbackServer,fixture_settings,loopback_sender,real_context,real_permit,SPAWN_ALLOWANCE_SECONDS
    settings=fixture_settings();clock=Clock();server=LoopbackServer(b'audited installed HTTP')
    try:
        sender=loopback_sender(settings,clock,server.origin,target=exchange,spool=root/'spool')
        receipt=sender.send(server.url,real_context(clock,settings),
            real_permit(clock,SPAWN_ALLOWANCE_SECONDS+1,start_seconds=SPAWN_ALLOWANCE_SECONDS),
            cancellation=multiprocessing.get_context('spawn').Event())
        print(json.dumps({'complete':receipt.complete,'body':receipt.temporary_path.read_text(),
            'requests':len(server.requests),'records':[json.loads(line) for line in (root/'order.jsonl').read_text().splitlines()]}))
    finally:server.close()
''')
            done = subprocess.run([*native_python_argv(self.b.python), str(script)], cwd=root,
                                  env=isolated_environment(), capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            proof = json.loads(done.stdout)
            self.assertTrue(proof['complete'], proof)
            self.assertEqual(proof['body'], 'audited installed HTTP')
            self.assertEqual(proof['requests'], 1)
            main, child, target = proof['records']
            self.assertEqual([item['event'] for item in proof['records']],
                             ['main-before-application', 'main-before-application', 'http-target'])
            self.assertNotEqual(main['pid'], child['pid'])
            self.assertEqual(child['pid'], target['pid'])
            self.assertFalse(main['application_imported'])
            self.assertFalse(child['application_imported'])
            self.assertEqual(child['denied'], [True] * 6)
            self.assertEqual(target['policy']['releases'], [str(self.b.directory)])
            self.assertTrue(Path(target['origin']).is_relative_to(self.b.directory))
            destination = os.environ.get('SEC_EDGAR_TASK14_HTTP_EVIDENCE')
            if destination:
                shutil.copytree(root, destination)

    def test_installed_adapter_rejects_real_wrong_transitive_with_direct_pins_intact(self):
        import locked_proof
        from workflow_proof import installed
        self.assertTrue(callable(getattr(locked_proof, 'verify_wrong_transitive', None)),
                        'installed proof must retain an actual wrong-transitive rejection oracle')
        accepted_before = {release.release_id: locked_proof.inventory(release.directory)
                           for release in (self.a, self.b)}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report = installed(output)
            self.assertEqual([item['release_id'] for item in report['releases']],
                             [self.a.release_id, self.b.release_id])
            refusal = report['wrong_transitive']
            self.assertEqual(refusal['direct_pins'], {'requests': '2.34.2', 'pyarrow': '25.0.1'})
            self.assertEqual(refusal['actual_transitive'], '0.0.0')
            self.assertNotEqual(refusal['expected_transitive'], refusal['actual_transitive'])
            self.assertNotEqual(refusal['inventory_probe']['exit'], 0)
            self.assertNotEqual(refusal['native_verifier']['exit'], 0)
            self.assertEqual(refusal['outcome'], 'refused')
            from sec_edgar_ingest.runtime import preflight
            for accepted in (self.a, self.b):
                self.assertEqual(preflight(accepted.directory / 'release.json'), accepted)
            accepted_after = {release.release_id: locked_proof.inventory(release.directory)
                              for release in (self.a, self.b)}
            self.assertEqual(accepted_after, accepted_before,
                             'installed proofs changed accepted A/B release content')
            (output / 'accepted-content-inventories.json').write_text(json.dumps(
                {'before': accepted_before, 'after': accepted_after}, sort_keys=True, indent=2) + '\n')
            destination = os.environ.get('SEC_EDGAR_TASK10_FIX_EVIDENCE')
            if destination:
                shutil.copytree(output, destination)

    def test_installed_b_workflow_continues_a_origin_pending_and_repairs(self):
        from workflow_proof import upgrade_sequence
        with tempfile.TemporaryDirectory() as directory:
            report = upgrade_sequence(Path(directory), self.a.directory / 'release.json',
                                      self.b.directory / 'release.json')
            self.assertEqual(report['exit'], 0)
            destination = os.environ.get('SEC_EDGAR_TASK10_UPGRADE_EVIDENCE')
            if destination:
                shutil.copytree(Path(directory), destination)
            for case in report['cases']:
                self.assertEqual(case['b_exit'], 0)
                self.assertGreater(case['rows'], 0)
                # Member order (plan Decisions R2, fallback; see workflow_proof.order_aware_children).
                # repair always runs its saved A publication under A. pending runs an A child only
                # when the A-origin member sorts before its B sibling; otherwise B4 completes it with
                # no child and every continue-b process is B.
                self.assertEqual(case['a_child_expected'],
                                 case['scenario'] == 'repair' or any(case['a_first'].values()))
                self.assertEqual(case['a_child_under_b_parent'], case['a_child_expected'])
                records = [case['parent'], *case['children']]
                selected = sorted({str(Path(item['python']).parents[2]) for item in records})
                expected = (case['release_directories'] if case['a_child_expected']
                            else [str(Path(case['parent']['python']).parents[2])])
                self.assertEqual(selected, expected, 'upgrade must exercise actual A-origin and B processes')
                for record in records:
                    guard = record['checkout_guard']
                    self.assertEqual(guard['pid'], record['pid'])
                    self.assertFalse(guard['application_imported'])
                    self.assertEqual(guard['denied'], [True] * 6)
                    self.assertEqual(guard['policy']['releases'], case['release_directories'])
