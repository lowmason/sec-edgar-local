"""Stage 1b §6 rules in scripts/measure-d5-drain.py: the C8 floor, the reserve and the fit gate."""
from network_guard import install
install()

import importlib.util
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


if __name__ == '__main__':
    unittest.main()
