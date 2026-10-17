"""Real immutable fixture setup for offline ETL tests."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sec_edgar_ingest.config import pin_context
from support import fixture_context, fixture_settings


def etl_context(parser_version='fixture-index-parser-v1', command='transform', attempt='etl1'):
    settings = fixture_settings(etl={'parser_version': parser_version})
    started = datetime.now(timezone.utc)
    context = replace(fixture_context(), command=command, attempt_id=attempt,
                      parser_version=parser_version, config_sha256=settings.config_sha256,
                      started_at=started, deadline=started + timedelta(seconds=3600),
                      effective_config={}, pinned_on=None)
    return settings, pin_context(settings, context, started.date())[0]


def seed_snapshot(root, source, body):
    from sec_edgar_ingest.models import Binding
    from sec_edgar_ingest.state import AcquisitionState
    from sec_edgar_ingest.worksets import encode_workset, make_snapshot_workset
    from support import fixture_snapshot, fixture_workset, store_bundle
    store, objects, leases = store_bundle(root)
    leases.close()
    source_set = fixture_workset(members=(source,))
    snapshot = fixture_snapshot(source, body)
    objects.put_once(snapshot.raw_path, body)
    objects.put_once(f'worksets/sec/source/sha256={source_set.workset_id}/workset.json',
                     encode_workset(source_set))
    acquisition = AcquisitionState(store)
    acquisition.remember_snapshot(snapshot)
    acquisition.bind_once(Binding(source_set.workset_id, source.source_id, snapshot.sha256))
    snapshot_set = make_snapshot_workset(source_set, (snapshot,))
    objects.put_once(f'worksets/sec/snapshot/sha256={snapshot_set.workset_id}/workset.json',
                     encode_workset(snapshot_set))
    return store, objects, snapshot_set


def seed_observation(objects, state, context, settings, *, period='2026Q4', kind='quarterly', rows=None, seconds=0):
    """Seed actual retained raw bytes and transform them for golden generations."""
    import io
    import re
    import zipfile
    from support import fixture_source, fixture_snapshot
    from sec_edgar_ingest.etl.transform import transform_member
    source = fixture_source(period, kind)
    body = b'CIK|Company Name|Form Type|Date Filed|File Name\n-----\n' + (
        b'123456|Example|10-K|2026-10-01|edgar/data/123456/0000123456-26-000001.txt\n' if rows is None else rows)
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
    objects.put_once(snapshot.raw_path, body)
    return transform_member(source, snapshot, context, settings, objects, state)
