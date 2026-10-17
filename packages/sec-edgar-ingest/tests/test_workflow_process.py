from network_guard import install
install()
import tempfile, unittest
from pathlib import Path
from workflow_proof import PROCESS_POINTS, process_case, sequence, harness_files

class WorkflowProcessTests(unittest.TestCase):
    def test_public_native_sequence_uses_explicit_test_only_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = sequence(Path(tmp))
            self.assertEqual(report['exit'], 0)
            self.assertEqual(set(report['reports']),
                {'proof-baseline', 'proof-overlap', 'proof-repeat', 'legacy-workflow'})
            self.assertTrue(all(path.is_relative_to(Path(__file__).resolve().parent) for path in harness_files()))

    def test_real_process_death_reopens_each_durable_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            for point in PROCESS_POINTS:
                with self.subTest(point=point):
                    result = process_case(Path(tmp) / point.replace('.', '-'), point)
                    self.assertEqual(result['worker_exit'], 91)
                    self.assertEqual(result['exit'], 0)
