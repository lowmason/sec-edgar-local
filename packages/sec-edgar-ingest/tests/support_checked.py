from network_guard import install
install()

from sec_edgar_ingest.models import to_mapping_value
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from support import fixture_settings, fixture_source, listing_response, store_bundle, zip_bytes
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.models import RunContext, canonical_json


def workflow_fixture(root: Path, *, command='backfill', prefix=False):
    root.mkdir(parents=True, exist_ok=True)
    settings = fixture_settings(
        backfill={'start_quarter': '2026Q4', 'end_quarter': 'open'},
        daily={'start_date': '2026-10-01'},
        etl={'parser_version': 'fixture-index-parser-v1'},
        http={'retry_base_seconds': 0.001, 'retry_cap_seconds': 0.001},
        fixture={'allow_clock_override': True, 'allow_deadline_override': True},
    )
    now = datetime.now(timezone.utc)
    context = RunContext('checked-run', 'checked-execution', command, 'checked-attempt',
        settings.worker.image_digest, settings.etl.parser_version, settings.etl.schema_version,
        settings.config_sha256, now, now + timedelta(seconds=3600), command)
    context = pin_context(settings, context, date(2026, 10, 8))[0]
    bodies = root / 'bodies'
    bodies.mkdir(exist_ok=True)
    responses = {}

    def response(body, *, fault=None):
        digest = hashlib.sha256(body).hexdigest()
        (bodies / (digest + '.body')).write_bytes(body)
        value = {'status': 200, 'headers': {'Content-Length': str(len(body))},
                 'body_path': 'bodies/' + digest + '.body', 'body_sha256': digest}
        if fault is not None:
            value['fault'] = fault
        return value

    def listing(family, period, names):
        if period == family:
            url = f'https://www.sec.gov/Archives/edgar/{family}/index.json'
        elif 'Q' in period:
            year, ordinal = period.split('Q')
            url = f'https://www.sec.gov/Archives/edgar/{family}/{year}/QTR{ordinal}/index.json'
        else:
            url = f'https://www.sec.gov/Archives/edgar/{family}/{period}/index.json'
        spec = listing_response(period, names, family=family)
        responses[url] = [response(spec.body) for _ in range(8)]

    listing('full-index', 'full-index', ['2026/'])
    listing('full-index', '2026', ['QTR4/'])
    listing('full-index', '2026Q4', ['master.zip'])
    listing('daily-index', 'daily-index', ['2026/'])
    listing('daily-index', '2026', ['QTR3/', 'QTR4/'])
    listing('daily-index', '2026Q3', [])
    listing('daily-index', '2026Q4', ['master.20261001.idx'])
    quarterly = zip_bytes(b'CIK|Company Name|Form Type|Date Filed|Filename\r\n-----\r\n'
        b'123456|Quarterly|10-K|2026-10-01|edgar/data/123456/0000123456-26-000001.txt\r\n')
    daily = (b'CIK|Company Name|Form Type|Date Filed|File Name\n-----\n'
        b'123456|Daily|10-K|20261001|edgar/data/123456/0000123456-26-000002.txt\n')
    for source, body in ((fixture_source('2026Q4'), quarterly),
                         (fixture_source('2026-10-01', 'daily'), daily)):
        sequence = [response(body) for _ in range(8)]
        if prefix:
            sequence.insert(0, response(b'retained retry prefix', fault='read_timeout'))
        responses[source.canonical_url] = sequence
    pack = root / 'manifest.json'
    pack.write_bytes(canonical_json(to_mapping_value({'fixture_version': 'sec-acquisition-fixture-v1',
        'provenance': 'synthetic', 'responses': responses})))
    store, objects, leases = store_bundle(root / '.fixture-state')
    leases.close()
    return settings, context, pack, store, objects


def cursor_values(store):
    return [row.to_mapping() for row in store.scan('FixtureResponseCursor', {})]


def dispatch_chain(dispatcher, settings, *, discovery_id='checked-discovery'):
    found = dispatcher.execute('discover', 'discover', settings,
        ('--mode', 'quarterly', '--discovery-id', discovery_id))
    collected = dispatcher.execute('collect', 'collect-one', settings,
        ('--workset', found.result.source_workset_ref))
    transformed = dispatcher.execute('transform', 'transform-one', settings,
        ('--workset', collected.result.snapshot_workset_ref))
    published = dispatcher.execute('publish', 'publish-one', settings,
        ('--workset', transformed.result.transformed_workset_ref))
    return found, collected, transformed, published
