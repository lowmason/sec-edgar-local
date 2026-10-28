"""Stage 1b §5 item 6: the 1b code continues D5-origin pending work, and D5 runs again on a store that 1b wrote.

The module imports `test_release_origin` as a module, so discovery does not collect plan 4's class a second time.
"""
from network_guard import install
install()

import unittest
from pathlib import Path

import test_release_origin as origin_tests


class D5OriginTests(origin_tests.OriginReleaseTests):
    """Plan 4's two-release proofs with the D5 release as origin. They stay order-aware (plan 4 R2)."""

    @classmethod
    def setUpClass(cls):
        from support_release import D5_REVISION, origin_release, proof_releases
        project = Path(__file__).resolve().parents[3]
        cls.origin = origin_release(project, project / 'releases/artifact-cache', revision=D5_REVISION)
        _, cls.current = proof_releases(project, project / 'releases/artifact-cache')

    # fc68adef…-only behaviours: D5 reads a sibling-completion receipt and accepts the reserve key.
    test_origin_release_reports_a_b4_receipt_as_unresolved = None
    test_origin_settings_refuse_the_reserve_key = None

    def test_d5_runs_again_on_a_store_that_1b_wrote(self):
        """§4.3 item 8: C7 changes no format, so D5 should read and continue a 1b-written store.

        An incremental generation is byte-identical to the full rebuild (§5 item 3), so D5's full checks
        see the same bytes either way.
        """
        h, origin, _, report, _ = self.continued(self.scratch())
        self.assertIn(report.outcome, ('success', 'unchanged'))
        code, message = self.origin_run(h, origin, 'd5-again')
        self.assertEqual(code, 0, message)
        self.assertIn(message['outcome'], ('success', 'unchanged'), message)


if __name__ == '__main__':
    unittest.main()
