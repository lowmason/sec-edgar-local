"""Real committed native A/B installations are the upgrade integration oracle."""
from network_guard import install
install()

import tempfile
import os
import shutil
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
                self.assertTrue(case['a_child_under_b_parent'])
