from network_guard import install
install()
from sec_edgar_ingest.models import to_mapping_value
import hashlib, io, zipfile
from pathlib import Path
from sec_edgar_ingest.models import canonical_json
BASE = 'https://www.sec.gov/Archives/edgar/'

def listing(url, children):
    return canonical_json(to_mapping_value({'directory': {'name': url[len(BASE):-len('index.json')],
        'parent-dir': '../', 'item': [
            {'name': name, 'href': name + ('/' if kind == 'dir' else ''), 'type': kind,
             'size': '1', 'last-modified': 'synthetic'} for name, kind in children]}}))

def idx(rows, kind):
    ending, title = ('\r\n', 'Filename') if kind == 'quarterly' else ('\n', 'File Name')
    body = ('CIK|Company Name|Form Type|Date Filed|' + title + ending + '-----' + ending +
            ending.join('|'.join(row) for row in rows) + ending).encode('ascii')
    if kind == 'daily':
        return body
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        info = zipfile.ZipInfo('master.idx', (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, body)
    return output.getvalue()

def build_pack(root, listings, bodies, overrides=None, repeats=8):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    (root / 'bodies').mkdir()
    merged = {url: listing(url, children) for url, children in listings.items()}
    merged.update(bodies)
    responses = {}
    for url, body in sorted(merged.items()):
        digest = hashlib.sha256(body).hexdigest()
        relative = 'bodies/' + digest + '.body'
        target = root / relative
        if not target.exists():
            target.write_bytes(body)
        spec = {'status': 200, 'headers': {'Content-Length': str(len(body)), 'X-Fixture': 'synthetic'},
                'body_path': relative, 'body_sha256': digest}
        responses[url] = [dict(spec) for _ in range(repeats)]
    responses.update(overrides or {})
    path = root / 'manifest.json'
    path.write_bytes(canonical_json(to_mapping_value({'fixture_version': 'sec-acquisition-fixture-v1',
                                    'provenance': 'synthetic', 'responses': responses})))
    return path

from sec_edgar_ingest.models import to_mapping_value
import contextlib, io, json
from datetime import datetime, timedelta, timezone
from support import fixture_settings
from sec_edgar_ingest.cli import main
from sec_edgar_ingest.storage import open_stores
from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter
from sec_edgar_ingest.etl.state import EtlState

class CommandHarness:
    def __init__(self, root, pack, settings=None):
        self.root, self.pack = Path(root), Path(pack)
        self.settings = settings or fixture_settings(
            backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
            etl={'parser_version': 'fixture-index-parser-v1'},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        self.config = self.root / 'config.json'
        self.config.write_bytes(canonical_json(to_mapping_value(self.settings.to_mapping())))
        self.deadline = datetime.now(timezone.utc) + timedelta(seconds=1800)
        self.opened = open_stores(self.settings, base_path=self.root)
        self.store, self.objects, self.leases = self.opened
        self.calls = []

    def invoke(self, command, flags=(), run='r', attempt='a', today='2026-10-07', deadline=None):
        argv = [command, '--config', str(self.config), '--run-id', run, '--execution-id', 'manual',
                '--attempt-id', attempt, '--deadline', (deadline or self.deadline).isoformat(),
                '--state-dir', str(self.root), '--today', today, *flags]
        if command in ('discover', 'collect', 'backfill', 'daily', 'reconcile'):
            argv += ['--fixture-pack', str(self.pack)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        message = json.loads(stdout.getvalue())
        self.calls.append({'argv': argv, 'exit': code, 'stdout': message, 'stderr': stderr.getvalue()})
        return code, message

    def capture(self, quarter):
        value = capture_quarter(quarter, self.objects, EtlState(self.store))
        if value is None:
            raise AssertionError('expected published quarter ' + quarter)
        return value, tuple(row.to_mapping() for row in read_quarter(value, self.objects))

    def close(self):
        for resource in reversed(self.opened):
            if hasattr(resource, 'close'):
                resource.close()

def simple_pack(root, *, empty=False, conflicting=False):
    listings, bodies = {}, {}
    for family in ('full-index', 'daily-index'):
        base = BASE + family + '/'
        listings[base + 'index.json'] = [('2026', 'dir')]
        listings[base + '2026/index.json'] = [('QTR3', 'dir'), ('QTR4', 'dir')]
        for quarter in (3, 4):
            leaf = base + f'2026/QTR{quarter}/'
            listings[leaf + 'index.json'] = []
            if empty or (family == 'daily-index' and quarter == 3):
                continue
            kind = 'quarterly' if family == 'full-index' else 'daily'
            filename = 'master.zip' if kind == 'quarterly' else 'master.20261001.idx'
            listings[leaf + 'index.json'] = [(filename, 'file')]
            filed = ('2026-09-30' if quarter == 3 else '2026-10-01') if kind == 'quarterly' else '20261001'
            path = f'edgar/data/123456/0000123456-26-00000{quarter}.txt'
            row = ('123456', 'Example', '10-K', filed, path)
            rows = (row, ('123456', 'Changed', '10-K', filed, path)) if conflicting else (row,)
            bodies[leaf + filename] = idx(rows, kind)
    return build_pack(root, listings, bodies)

def quarter_pack(root, periods, *, empty_daily=False, failed_daily=(), moved=None, conflicting=()):
    periods = tuple(sorted(set(periods)))
    listings, bodies = {}, {}
    for family in ('full-index', 'daily-index'):
        base = BASE + family + '/'
        years = sorted({period[:4] for period in periods})
        listings[base + 'index.json'] = [(year, 'dir') for year in years]
        for year in years:
            listings[base + year + '/index.json'] = [
                ('QTR' + period[-1], 'dir') for period in periods if period.startswith(year)]
        for period in periods:
            year, quarter = period.split('Q')
            leaf = base + year + '/QTR' + quarter + '/'
            month = (int(quarter) - 1) * 3 + 1
            day = year + f'-{month:02d}-01'
            # Q4 must remain inside the overlap following a seed boundary of October 2.
            if period == '2026Q4': day = '2026-12-31'
            filename = 'master.zip' if family == 'full-index' else 'master.' + day.replace('-', '') + '.idx'
            listings[leaf + 'index.json'] = [] if family == 'daily-index' and empty_daily else [(filename, 'file')]
            filed = (moved or {}).get(period, day) if family == 'full-index' else day.replace('-', '')
            archive = 'edgar/data/123456/0000123456-' + year[-2:] + '-00000' + quarter + '.txt'
            row = ('123456', 'Example', '10-K', filed, archive)
            rows = (row, ('123456', 'Conflict', '10-K', filed, archive)) if period in conflicting else (row,)
            bodies[leaf + filename] = idx(rows, 'quarterly' if family == 'full-index' else 'daily')
    pack = build_pack(root, listings, bodies, repeats=16)
    if failed_daily:
        manifest = json.loads(pack.read_text())
        failure = b'fixture missing required directory'
        digest = hashlib.sha256(failure).hexdigest()
        (pack.parent / 'bodies' / (digest + '.body')).write_bytes(failure)
        for period in failed_daily:
            year, quarter = period.split('Q')
            url = BASE + 'daily-index/' + year + '/QTR' + quarter + '/index.json'
            response = {'status': 404, 'headers': {'Content-Length': str(len(failure))},
                        'body_path': 'bodies/' + digest + '.body', 'body_sha256': digest}
            manifest['responses'][url] = [dict(response) for _ in range(16)]
        pack.write_bytes(canonical_json(to_mapping_value(manifest)))
    return pack


def set_harness_settings(harness, settings):
    harness.settings = settings
    harness.config.write_bytes(canonical_json(to_mapping_value(settings.to_mapping())))


def prefix_response(pack, url, body=b'retained truncated retry prefix'):
    pack = Path(pack)
    manifest = json.loads(pack.read_text())
    digest = hashlib.sha256(body).hexdigest()
    (pack.parent / 'bodies' / (digest + '.body')).write_bytes(body)
    manifest['responses'][url].insert(0, {'status': 200,
        'headers': {'X-Fixture': 'partial'}, 'fault': 'read_timeout',
        'body_path': 'bodies/' + digest + '.body', 'body_sha256': digest})
    pack.write_bytes(canonical_json(to_mapping_value(manifest)))
    return body


def replace_pack_body(pack, url, body):
    pack = Path(pack)
    manifest = json.loads(pack.read_text())
    digest = hashlib.sha256(body).hexdigest()
    target = pack.parent / 'bodies' / (digest + '.body')
    if not target.exists(): target.write_bytes(body)
    response = {'status': 200, 'headers': {'Content-Length': str(len(body)), 'X-Fixture': 'synthetic'},
                'body_path': 'bodies/' + digest + '.body', 'body_sha256': digest}
    manifest['responses'][url] = [dict(response) for _ in range(16)]
    pack.write_bytes(canonical_json(to_mapping_value(manifest)))
