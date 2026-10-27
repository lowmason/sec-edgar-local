"""Stage 1b §5 item 2, split by process (plan 5, P2).

Workflow children are native processes, so a patch here sees the engine only. The engine test proves
that the engine runs no full check and no observation readback, and that `read_quarter` still runs the
full check. The publish tests call `publish_quarter` in this process.
"""
from network_guard import install
install()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_workflows import CommandHarness, simple_pack
from sec_edgar_ingest.etl import manifest as generation
from sec_edgar_ingest.etl import transform
from sec_edgar_ingest.etl.commands import _affected_quarters
from sec_edgar_ingest.etl.reader import capture_quarter, read_manifest
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.storage.contracts import Conflict


class EngineBudgetTests(unittest.TestCase):
    def harness(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        harness = CommandHarness(root, simple_pack(root / 'pack'))
        self.addCleanup(harness.close)  # Runs before the directory cleanup (LIFO).
        return harness

    def test_the_engine_runs_no_full_check_and_readers_still_do(self):
        h = self.harness()
        with patch.object(generation, '_validate_row_origins', wraps=generation._validate_row_origins) as full, \
                patch.object(transform, '_verify_parquet', wraps=transform._verify_parquet) as readback:
            code, message = h.invoke('backfill')
            self.assertEqual(code, 0, message)
            self.assertEqual((full.call_count, readback.call_count), (0, 0))
            h.capture('2026Q4')
            self.assertEqual(full.call_count, 1)

    def test_a_changed_generation_byte_is_a_conflict_on_engine_paths(self):
        h = self.harness()
        code, message = h.invoke('backfill')
        self.assertEqual(code, 0, message)
        state = EtlState(h.store)
        captured = capture_quarter('2026Q4', h.objects, state)
        data = next(ref for ref in read_manifest(captured, h.objects).files if ref.role == 'data')
        path = h.root / '.fixture-state/objects' / data.path
        path.write_bytes(path.read_bytes() + b'\0')
        with self.assertRaises(Conflict):
            capture_quarter('2026Q4', h.objects, state)
        sources = read_manifest(captured, h.objects).sources
        with self.assertRaises(Conflict):
            _affected_quarters(sources, h.objects, h.store)


if __name__ == '__main__':
    unittest.main()
