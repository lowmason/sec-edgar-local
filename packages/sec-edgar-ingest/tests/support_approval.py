"""Real gated-candidate fixtures shared by approval, history and operator CLI tests."""
from network_guard import install
install()

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from support import fixture_settings
from support_etl import etl_context, seed_observation
from sec_edgar_ingest.cli import main
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.etl.contracts import Candidate
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.models import canonical_json, to_mapping_value
from sec_edgar_ingest.storage import open_stores


def row(name='Example', number=1, day='2026-10-01'):
    return f'123456|{name}|10-K|{day}|edgar/data/123456/0000123456-26-{number:06}.txt\n'.encode()


def operator_cli(*argv):
    """Run one operator command through the console entry point; stdout is empty on usage errors."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(argv))
    return code, (json.loads(stdout.getvalue()) if stdout.getvalue() else None), stderr.getvalue()


class GateFixture(unittest.TestCase):
    """Stores open exactly as the CLI opens them, so operator commands see the same state."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings, self.context = etl_context(command='publish')
        self.pin(date(2026, 10, 7))
        self.store, self.objects, leases = open_stores(self.settings, base_path=self.root)
        leases.close()
        self.addCleanup(self.store.close)
        self.state = EtlState(self.store)

    def pin(self, day):
        self.settings = fixture_settings(etl={'parser_version': self.context.parser_version},
                                         fixture={'allow_clock_override': True})
        self.context = pin_context(self.settings, replace(self.context, config_sha256=self.settings.config_sha256,
                                   effective_config={}, pinned_on=None), day)[0]

    def observation(self, **kwargs):
        return seed_observation(self.objects, self.state, self.context, self.settings, **kwargs)

    def publish(self, *refs, quarter='2026Q4', **kwargs):
        from sec_edgar_ingest.etl.publication import publish_quarter
        return publish_quarter(quarter, refs, self.context, self.settings, self.objects, self.state, **kwargs)

    def capture(self, quarter='2026Q4'):
        from sec_edgar_ingest.etl.reader import capture_quarter
        return capture_quarter(quarter, self.objects, self.state)

    def rows(self, capture=None):
        """(row number, company) pairs of a fully validated quarter read."""
        from sec_edgar_ingest.etl.reader import read_quarter
        return [(int(item.archive_path.rsplit('-', 1)[1].removesuffix('.txt')), item.company_name)
                for item in read_quarter(capture or self.capture(), self.objects)]

    def candidate(self, candidate_ref):
        generation_id = candidate_ref.split('sha256=', 1)[1].split('/', 1)[0]
        return Candidate.from_mapping(self.store.get('Candidate', generation_id).to_mapping()['value'])

    def gated(self):
        """Publish rows 1 and 2 while 2026Q4 is open, then stage the closed withdrawal of row 2."""
        initial = self.observation(rows=row() + row(number=2))
        self.assertEqual(self.publish(initial).outcome, 'published')
        base = self.capture()
        revised = self.observation(rows=row(), seconds=1)
        self.pin(date(2027, 1, 1))
        result = self.publish(revised)
        self.assertEqual(result.outcome, 'awaiting_approval')
        return base, revised, self.candidate(result.candidate_ref)

    def object_path(self, ref):
        return self.objects.directory / ref

    def write_config(self):
        path = self.root / 'config.json'
        path.write_bytes(canonical_json(to_mapping_value(self.settings.to_mapping())))
        return path


def tree_snapshot(root: Path) -> dict[str, str]:
    """Every directory and file under root, files by content hash. SQLite's transient WAL files are
    excluded: a reader creates and removes them without changing stored state."""
    entries = {}
    for path in sorted(Path(root).rglob('*')):
        if path.name.endswith(('-wal', '-shm')):
            continue
        entries[str(path.relative_to(root))] = 'dir' if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return entries
