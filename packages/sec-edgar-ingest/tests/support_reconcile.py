"""Fixture packs and a command harness for reconcile workflow tests."""
from network_guard import install
install()

import hashlib
import tempfile
import unittest
from pathlib import Path

from support import fixture_settings
from support_workflows import BASE, CommandHarness, idx, quarter_pack, replace_pack_body
from sec_edgar_ingest.etl.contracts import Candidate
from sec_edgar_ingest.workflows.results import read_workflow_result

Q3_URL = BASE + 'full-index/2026/QTR3/master.zip'
Q4_URL = BASE + 'full-index/2026/QTR4/master.zip'
A = ('123456', 'A', '10-K', '2026-07-01', 'edgar/data/123456/0000123456-26-000031.txt')
B = ('123456', 'B', '10-K', '2026-07-02', 'edgar/data/123456/0000123456-26-000032.txt')
C = ('123456', 'C', '10-K', '2026-07-03', 'edgar/data/123456/0000123456-26-000033.txt')
X = ('123456', 'X', '10-K', '2026-10-01', 'edgar/data/123456/0000123456-26-000041.txt')
Y = ('123456', 'Y', '10-K', '2026-10-02', 'edgar/data/123456/0000123456-26-000042.txt')


def quarterly(rows):
    return idx(rows, 'quarterly')


def sha(rows):
    return hashlib.sha256(quarterly(rows)).hexdigest()


class ReconcileFixture(unittest.TestCase):
    """On the harness's pinned 2026-10-07, 2026Q3 is closed and 2026Q4 is open."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packs = 0

    def pack(self, q3_rows, q4_rows):
        # Each phase gets a fresh pack: a new manifest hash restarts every response cursor.
        self.packs += 1
        pack = quarter_pack(self.root / f'pack-{self.packs}', ('2026Q3', '2026Q4'), empty_daily=True)
        replace_pack_body(pack, Q3_URL, quarterly(q3_rows))
        replace_pack_body(pack, Q4_URL, quarterly(q4_rows))
        return pack

    def harness(self, q3_rows, q4_rows=(X, Y)):
        settings = fixture_settings(backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
            http={'retry_base_seconds': 0.001, 'retry_cap_seconds': 0.001},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        h = CommandHarness(self.root, self.pack(q3_rows, q4_rows), settings)
        self.addCleanup(h.close)
        return h

    def run_phase(self, h, command, run, q3_rows=None, q4_rows=(X, Y)):
        if q3_rows is not None:
            h.pack = self.pack(q3_rows, q4_rows)
        code, message = h.invoke(command, run=run)
        if message.get('result_ref') is None:
            self.fail(f'{command} {run!r} exited {code} without a report: {h.calls[-1]}')
        return code, message, read_workflow_result(message['result_ref'], h.store, h.objects)

    def names(self, h, quarter):
        return [value['company_name'] for value in h.capture(quarter)[1]]

    def candidates(self, h):
        return [Candidate.from_mapping(row.to_mapping()['value']) for row in h.store.scan('Candidate', {})]
