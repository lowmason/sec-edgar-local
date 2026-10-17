from sec_edgar_ingest.models import to_mapping_value
# tests/support_workflow_evidence.py
import contextlib
import hashlib
import io
import json
import zipfile
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from support import discovery_harness, fixture_snapshot, listing_response
from sec_edgar_ingest.cli import main
from sec_edgar_ingest.config import Settings, pin_context
from sec_edgar_ingest.etl.commands import read_etl_result
from sec_edgar_ingest.models import Binding, RunContext, canonical_json
from sec_edgar_ingest.state import AcquisitionState
from sec_edgar_ingest.worksets import encode_workset, make_snapshot_workset
from sec_edgar_ingest.workflows.provenance import project_member


def quarterly_bytes(day, name='A'):
    body = ('CIK|Company Name|Form Type|Date Filed|Filename\r\n-----\r\n'
            f'123456|{name}|10-K|{day}|edgar/data/123456/a.txt\r\n').encode()
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w') as archive:
        info = zipfile.ZipInfo('master.idx', (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, body)
    return target.getvalue()


class EvidenceFixture:
    def __init__(self, root, command='daily'):
        self.root = Path(root)
        self.h = discovery_harness(self.root, {
            '2026Q3': [listing_response('2026Q3', ['master.zip'], family='full-index'),
                       listing_response('2026Q3', ['master.zip'], family='full-index')],
        })
        self.h.settings = Settings.from_mapping({
            **self.h.settings.to_mapping(),
            'backfill': {'start_quarter': '2026Q3', 'end_quarter': 'open'},
        })
        self.h.coordinator.settings = self.h.settings
        self.h.client.settings = self.h.settings
        parent = self.h.run('quarterly', date(2026, 10, 6), 'completion-old')
        self.parent_ref = self.h.workset_path(parent)
        self.source = next(s for s in parent.members if s.period == '2026Q3')
        self.value = project_member(self.parent_ref, self.source.source_id,
                                    self.h.store, self.h.objects)
        self.store, self.objects = self.h.store, self.h.objects
        self.sequence = 0
        self.calls = []
        self.settings = Settings.from_mapping({**self.h.settings.to_mapping(),
            'etl': {**self.h.settings.to_mapping()['etl'],
                    'parser_version': 'fixture-index-parser-v1'}})
        self.config = self.root / 'etl-config.json'
        self.config.write_bytes(canonical_json(to_mapping_value(self.settings.to_mapping())))
        now = datetime.now(timezone.utc)
        origin = parent.context
        self.workflow = pin_context(self.settings, replace(
            origin, run_id='completion-workflow', execution_id='completion-execution',
            parser_version=self.settings.etl.parser_version,
            schema_version=self.settings.etl.schema_version,
            config_sha256=self.settings.config_sha256,
            command=command, attempt_id='workflow-a', started_at=now,
            deadline=now + timedelta(seconds=3600), effective_config={}, pinned_on=None,
        ), date(2026, 10, 6))[0]
        bodies = self.root.parent / 'listing-bodies'
        bodies.mkdir(exist_ok=True)
        responses = {}
        for directory in parent.directories:
            progress = self.h.state.directory_progress(parent.discovery_id, directory.url).to_mapping()['value']
            body = self.objects.read(progress['evidence']['body_path'])
            digest = hashlib.sha256(body).hexdigest()
            (bodies / (digest + '.body')).write_bytes(body)
            spec = {'status': 200, 'headers': {'Content-Length': str(len(body))},
                    'body_path': 'listing-bodies/' + digest + '.body', 'body_sha256': digest}
            responses[directory.url] = [spec for _ in range(4)]
        raw = quarterly_bytes('2026-07-01')
        raw_digest = hashlib.sha256(raw).hexdigest()
        (bodies / (raw_digest + '.body')).write_bytes(raw)
        responses[self.source.canonical_url] = [
            {'status': 200, 'headers': {'Content-Length': str(len(raw))},
             'body_path': 'listing-bodies/' + raw_digest + '.body', 'body_sha256': raw_digest}
            for _ in range(4)]
        self.pack = self.root.parent / 'listing-manifest.json'
        self.pack.write_bytes(canonical_json(to_mapping_value({'fixture_version': 'sec-acquisition-fixture-v1',
                            'provenance': 'synthetic', 'responses': responses})))
        from sec_edgar_ingest.workflows.checked import Dispatcher
        dispatcher = Dispatcher(self.workflow, self.settings, self.pack,
                                self.root.parent, self.store, self.objects)
        found = dispatcher.execute('discover', 'initial-discovery', self.settings,
                                   ('--mode', 'quarterly', '--discovery-id', 'checked-completion-parent'))
        self.discovery_call = found.call
        self.parent_ref = found.result.source_workset_ref
        self.value = project_member(self.parent_ref, self.source.source_id,
                                    self.store, self.objects)

    def close(self):
        self.h.close()

    def revised_member(self):
        from sec_edgar_ingest.workflows.checked import Dispatcher
        self.sequence += 1
        dispatcher = Dispatcher(self.workflow, self.settings, self.pack,
                                self.root.parent, self.store, self.objects)
        found = dispatcher.execute('discover', f'revised-discovery-{self.sequence}', self.settings,
                                   ('--mode', 'quarterly', '--discovery-id',
                                    f'completion-new-{self.sequence}', '--refresh'))
        value = project_member(found.result.source_workset_ref, self.source.source_id,
                               self.store, self.objects)
        self.value = value
        return value

    def snapshot_input(self, body, seconds=0):
        from sec_edgar_ingest.workflows.provenance import read_member
        source_set = read_member(self.value, self.store, self.objects)
        snap = fixture_snapshot(self.source, body)
        snap = replace(snap, received_at=snap.received_at + timedelta(seconds=seconds))
        self.objects.put_once(snap.raw_path, body)
        acquisition = AcquisitionState(self.store)
        acquisition.remember_snapshot(snap)
        winner = acquisition.bind_once(Binding(source_set.workset_id,
                                                self.source.source_id, snap.sha256))
        if winner.snapshot_sha256 != snap.sha256:
            raise AssertionError('fixture attempted to overwrite an existing pin')
        snapshot_set = make_snapshot_workset(source_set, (snap,))
        ref = f'worksets/sec/snapshot/sha256={snapshot_set.workset_id}/workset.json'
        self.objects.put_once(ref, encode_workset(snapshot_set))
        return ref

    def invoke(self, command, input_ref, *, deadline=None):
        from sec_edgar_ingest.workflows.checked import Dispatcher, ChildUnfinished
        self.sequence += 1
        workflow = self.workflow if deadline is None else replace(self.workflow, deadline=deadline)
        dispatcher = Dispatcher(workflow, self.settings, self.pack,
                                self.root.parent, self.store, self.objects)
        with contextlib.ExitStack() as guards:
            if command in ('transform', 'publish'):
                guards.enter_context(patch('sec_edgar_ingest.cli.Coordinator', side_effect=AssertionError('ETL acquisition')))
                guards.enter_context(patch('sec_edgar_ingest.cli.BoundedSender', side_effect=AssertionError('ETL sender')))
            try:
                child = dispatcher.execute(command, f'{command}-{self.sequence}', self.settings,
                                           ('--workset', input_ref))
            except ChildUnfinished as error:
                self.calls.append(error.call)
                return error.exit, error.call, None
        self.calls.append(child.call)
        from sec_edgar_ingest.results import exit_code
        return exit_code(child.result.outcome), child.call, child.result
