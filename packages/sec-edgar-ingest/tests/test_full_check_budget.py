"""Stage 1b §5 item 2, split by process (plan 5, P2).

Workflow children are native processes, so a patch here sees the engine only. The engine test proves
that the engine runs no full check and no observation readback, and that `read_quarter` still runs the
full check. The publish tests call `publish_quarter` in this process.
"""
from network_guard import install
install()

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from support_catalog import Lane, row
from support_workflows import CommandHarness, simple_pack
from sec_edgar_ingest.etl import manifest as generation
from sec_edgar_ingest.etl import transform
from sec_edgar_ingest.etl.commands import _affected_quarters
from sec_edgar_ingest.etl.publication import publish_quarter
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


class PublishBudgetTests(unittest.TestCase):
    def setUp(self):
        self.lane = Lane(command='publish')
        self.addCleanup(self.lane.close)

    def publish(self, *refs):
        return publish_quarter('2026Q4', tuple(refs), self.lane.context, self.lane.settings,
                               self.lane.objects, self.lane.state)

    def counted(self, *refs):
        with patch.object(generation, '_validate_row_origins', wraps=generation._validate_row_origins) as full:
            result = self.publish(*refs)
        return result, full.call_count

    def test_a_first_publication_is_fully_checked_once(self):
        result, count = self.counted(self.lane.observation(rows=row() + row(number=2)))
        self.assertEqual((result.outcome, count), ('published', 1))

    def test_an_unchanged_quarter_is_not_fully_checked(self):
        ref = self.lane.observation()
        self.publish(ref)
        result, count = self.counted(ref)
        self.assertEqual((result.outcome, count), ('unchanged', 0))

    def test_a_replacement_rebuild_is_fully_checked_once(self):
        self.publish(self.lane.observation('2026-10-01', 'daily', row() + row(number=2)))
        replacement = self.lane.observation('2026-10-01', 'daily', row('Changed'), seconds=1)
        result, count = self.counted(replacement)
        self.assertEqual((result.outcome, count), ('published', 1))

    def test_a_gated_rebuild_is_fully_checked_once(self):
        self.publish(self.lane.observation(rows=row() + row(number=2)))
        revised = self.lane.observation(rows=row('Revised'), seconds=1)
        self.publish(revised)
        self.lane.pin(date(2027, 1, 1))
        result, count = self.counted(revised)
        self.assertEqual((result.outcome, count), ('awaiting_approval', 1))

    def test_an_incremental_rebuild_is_not_fully_checked(self):
        self.publish(self.lane.observation('2026-10-01', 'daily', row()))
        result, count = self.counted(self.lane.observation('2026-10-02', 'daily', row(number=2)))
        self.assertEqual((result.outcome, count), ('published', 0))

    def test_a_replayed_incremental_candidate_is_fully_checked_once(self):
        # A replayed or crash-recovered candidate skips C6, so `_existing`'s full check is its only check (C3, S1).
        base = self.lane.build([self.lane.observation('2026-10-01', 'daily', row())])
        daily = self.lane.observation('2026-10-02', 'daily', row(number=2))
        counts = []
        for _ in range(2):  # No pointer commits between the two builds.
            with patch.object(generation, '_validate_row_origins', wraps=generation._validate_row_origins) as full:
                candidate = self.lane.build([daily], base)
            counts.append((candidate.manifest_ref, full.call_count))
        self.assertEqual(counts, [(counts[0][0], 0), (counts[0][0], 1)])


if __name__ == '__main__':
    unittest.main()
