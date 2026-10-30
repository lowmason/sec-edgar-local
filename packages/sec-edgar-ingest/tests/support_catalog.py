"""One fresh store with the catalog test fixtures (Stage 1b tests share it; it holds no test cases)."""
import io
import re
import tempfile
import zipfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from support import fixture_snapshot, fixture_settings, fixture_source, store_bundle
from support_etl import etl_context
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.etl.catalog import build_candidate
from sec_edgar_ingest.etl.contracts import GenerationCapture
from sec_edgar_ingest.etl.manifest import iter_file_rows
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.transform import transform_member

HEADER = b'CIK|Company Name|Form Type|Date Filed|File Name\n-----\n'


def row(name='Example', number=1, day='2026-10-01', form='10-K', cik=123456):
    return f'{cik}|{name}|{form}|{day}|edgar/data/{cik}/{cik:010d}-26-{number:06}.txt\n'.encode()


def capture(candidate):
    return GenerationCapture(candidate.manifest.quarter, candidate.manifest.generation_id,
                             candidate.manifest_ref, candidate.manifest_sha256, candidate.manifest_bytes)


class Lane:
    """A store, its ETL state and a pinned context. Call `close` when done."""

    def __init__(self, day=date(2026, 10, 7), command='transform'):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store, self.objects, leases = store_bundle(self.root)
        leases.close()
        self.state = EtlState(self.store)
        self.settings, self.context = etl_context(command=command, root=self.root)
        self.pin(day)

    def close(self):
        self.store.close()
        self.temp.cleanup()

    def pin(self, day):
        self.settings = fixture_settings(etl={'parser_version': self.context.parser_version},
                                         fixture={'allow_clock_override': True}, root=self.root)
        context = replace(self.context, config_sha256=self.settings.config_sha256, pinned_on=None, effective_config={})
        self.context = pin_context(self.settings, context, day)[0]

    def observation(self, period='2026Q4', kind='quarterly', rows=None, seconds=0):
        source = fixture_source(period, kind)
        body = HEADER + (row() if rows is None else rows)
        if kind == 'quarterly':
            target = io.BytesIO()
            with zipfile.ZipFile(target, 'w') as archive:
                info = zipfile.ZipInfo('master.idx', (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, body.replace(b'File Name', b'Filename').replace(b'\n', b'\r\n'))
            body = target.getvalue()
        else:
            body = re.sub(rb'\|(\d{4})-(\d{2})-(\d{2})\|', rb'|\1\2\3|', body)
        snapshot = fixture_snapshot(source, body)
        snapshot = replace(snapshot, received_at=snapshot.received_at + timedelta(seconds=seconds))
        self.objects.put_once(snapshot.raw_path, body)
        return transform_member(source, snapshot, self.context, self.settings, self.objects, self.state)

    def build(self, refs, previous=None, quarter='2026Q4'):
        return build_candidate(quarter, capture(previous) if previous else None, tuple(refs),
                               self.context, self.settings, self.objects, self.state)

    def rows(self, candidate, role='data'):
        return [value for ref in candidate.manifest.files if ref.role == role
                for value in iter_file_rows(ref, self.objects)]

    def path(self, name):
        return self.root / 'objects' / name
