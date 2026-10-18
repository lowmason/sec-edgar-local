#!/usr/bin/env python3
"""Explicit, external, bounded genuine SEC acceptance; never part of default checks.

Prepare is offline. Run requires an unchanged prepared selection and the selected
installed interpreter. Verify reads retained evidence without making requests.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

# This policy precedes every application import, including runpy child bootstrap.
sys.dont_write_bytecode = True
sys.pycache_prefix = os.devnull

SELECTION_VERSION = 'sec-local-sec-selection-v1'
CALL_VERSION = 'sec-local-sec-call-v1'
BASE = 'https://www.sec.gov/Archives/edgar/'
OWNER = 'Lowell Mason sec-edgar-ingest mason.lowell@mac.com'
RECEIVED_CEILING = 67_108_864
EXPANDED_CEILING = 536_870_912
LIMITS = {'wall_seconds': 900, 'distinct_urls': 20, 'attempts': 100,
          'received_bytes': 134_217_728, 'expanded_bytes': 1_073_741_824,
          'attempts_per_url': 5, 'quarterly_bodies': 1, 'daily_bodies': 2}
LIMIT_EXIT = 12
HERE = Path(__file__).resolve().parent
CHILD = HERE / 'sec-acceptance-child.py'
SELECTION_KEYS = {'format_version', 'release', 'release_id', 'native_python', 'root',
    'issuer_binding', 'quarterly_periods', 'daily_dates', 'sources', 'configs',
    'input_config', 'window', 'sole_issuer_confirmed', 'sole_issuer_declaration',
    'limits', 'evidence', 'inventory', 'harness'}


class AcceptanceLimit(RuntimeError):
    """Distinct harness refusal: never reinterpret as parser quarantine/success."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key: ' + key)
        value[key] = item
    return value


def read_json(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def write_once(path, body):
    """An exclusive immutable file; competing writers must supply identical bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != body:
            raise ValueError('immutable evidence differs: ' + str(path))


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + ' must have exactly the declared fields')


def utc(value):
    if not isinstance(value, str):
        raise ValueError('UTC timestamp must be text')
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() != timedelta(0) or result.isoformat() != value:
        raise ValueError('timestamp must use canonical aware UTC')
    return result


def absolute(value):
    if not isinstance(value, str) or not Path(value).is_absolute() or str(Path(value).resolve()) != value:
        raise ValueError('path must be normalized and absolute')
    return Path(value)


def source_records():
    urls = [BASE + 'full-index/2024/QTR1/master.zip',
            BASE + 'daily-index/2026/QTR4/master.20261014.idx',
            BASE + 'daily-index/2026/QTR4/master.20261015.idx']
    return [{'url': url, 'source_id': digest(url.encode()),
             'kind': 'quarterly' if '/full-index/' in url else 'daily',
             'period': period} for url, period in zip(urls, ['2024Q1', '2026-10-14', '2026-10-15'])]


def validate_selection(selection):
    exact(selection, SELECTION_KEYS, 'selection')
    if selection['format_version'] != SELECTION_VERSION:
        raise ValueError('unsupported selection format')
    if selection['quarterly_periods'] != ['2024Q1']:
        raise ValueError('quarterly selection differs from the recorded bounded case')
    if len(selection['daily_dates']) != 2 or len(set(selection['daily_dates'])) != 2:
        raise ValueError('acceptance requires two distinct explicit daily dates')
    if selection['daily_dates'] != ['2026-10-14', '2026-10-15'] or selection['sources'] != source_records():
        raise ValueError('selected source identity differs from the recorded bounded case')
    if selection['sole_issuer_confirmed'] is not True:
        raise ValueError('sole live issuer must be confirmed before acquisition')
    if selection['sole_issuer_declaration'] != 'Owner confirmed all other project-budget collectors remain stopped throughout this acceptance window.':
        raise ValueError('sole issuer declaration differs')
    exact(selection['limits'], LIMITS, 'limits')
    if selection['limits']['attempts'] > 100:
        raise ValueError('acceptance request budget exceeds the recorded bound')
    for kind, maximum in LIMITS.items():
        value = selection['limits'][kind]
        if type(value) is not int or not 0 < value <= maximum:
            raise ValueError('acceptance limit differs from recorded bounds: ' + kind)
    exact(selection['window'], {'started_utc', 'deadline_utc'}, 'window')
    duration = (utc(selection['window']['deadline_utc']) - utc(selection['window']['started_utc'])).total_seconds()
    if duration != selection['limits']['wall_seconds']:
        raise ValueError('acceptance window must retain its original exact duration')
    for key in ('root', 'evidence'):
        absolute(selection[key])
    if not Path(selection['native_python']).is_absolute() or str(Path(selection['native_python']).absolute()) != selection['native_python']:
        raise ValueError('native executable must retain its exact absolute installation spelling')
    exact(selection['release'], {'path', 'sha256'}, 'release')
    manifest = absolute(selection['release']['path'])
    if (not re.fullmatch('[0-9a-f]{64}', selection['release_id']) or
            manifest.name != 'release.json' or manifest.parent.name != 'sha256=' + selection['release_id'] or
            selection['native_python'] != str(manifest.parent / 'venv/bin/python')):
        raise ValueError('selected native installation identity differs')
    for record in [selection['release'], selection['input_config'], *selection['configs'].values(), *selection['harness'].values()]:
        absolute(record['path'])
        if not re.fullmatch('[0-9a-f]{64}', record['sha256']):
            raise ValueError('invalid retained SHA256')
    exact(selection['input_config'], {'path', 'sha256'}, 'input config')
    exact(selection['configs'], {'quarterly', 'daily'}, 'configs')
    for record in selection['configs'].values():
        exact(record, {'path', 'sha256', 'effective_sha256'}, 'config')
        if not re.fullmatch('[0-9a-f]{64}', record['effective_sha256']):
            raise ValueError('invalid effective config SHA256')
    exact(selection['harness'], {'driver', 'child'}, 'harness')
    for record in selection['harness'].values():
        exact(record, {'path', 'sha256'}, 'harness file')
    exact(selection['inventory'], {'root_existed', 'pending_sources', 'failed_directories',
                                  'daily_quarters', 'quarterly_listing_urls', 'daily_listing_urls'}, 'inventory')
    if type(selection['inventory']['root_existed']) is not bool:
        raise ValueError('root inventory flag must be boolean')
    validate_daily_scope(selection, selection['inventory']['daily_quarters'])
    permitted = permitted_urls(selection)
    if len(permitted) > selection['limits']['distinct_urls']:
        raise ValueError('declared discovery/body URL plan exceeds distinct URL limit')
    binding = selection['issuer_binding']
    if (binding.get('binding_version') != 'sec-local-binding-v1' or binding.get('root') != selection['root'] or
            binding.get('acquisition_mode') != 'live' or binding.get('sec', {}).get('user_agent') != OWNER):
        raise ValueError('selection requires same resolved live root/issuer binding')
    return selection


def validate_daily_scope(selection, quarters):
    for value in selection['daily_dates']:
        day = date.fromisoformat(value)
        if f'{day.year}Q{(day.month - 1) // 3 + 1}' not in quarters:
            raise ValueError('daily dates outside required production quarter scope; explicit revised selection required')


def remaining_seconds(selection, *, now=None):
    now = now or datetime.now(timezone.utc)
    return max(0.0, (utc(selection['window']['deadline_utc']) - now).total_seconds())


def permitted_urls(selection):
    urls = set(item['url'] for item in selection['sources'])
    for mode in ('quarterly', 'daily'):
        for url in selection['inventory'][mode + '_listing_urls']:
            if re.fullmatch(re.escape(BASE) + r'(?:full-index|daily-index)/(?:[1-9][0-9]{3}/(?:QTR[1-4]/)?)?index\.json', url) is None:
                raise ValueError('noncanonical declared listing URL')
            urls.add(url)
    return urls


def load_selection(path):
    path = Path(path)
    value = validate_selection(read_json(path))
    if path.read_bytes() != canonical(value):
        raise ValueError('selection bytes must be canonical and unchanged')
    return value


def require_prepared(selection_path):
    selection_path = Path(selection_path).resolve()
    selection = load_selection(selection_path)
    receipt = read_json(Path(selection['evidence']) / 'prepared.json')
    expected = {'format_version': 'sec-local-sec-prepared-v1',
                'selection_path': str(selection_path),
                'selection_sha256': digest(selection_path.read_bytes())}
    if receipt != expected or selection_path != Path(selection['evidence']) / 'selection.json':
        raise ValueError('prepared selection bytes/path changed before execution')
    return selection


class Budget:
    """SQLite admission authority shared by every retry, validation and restart."""
    def __init__(self, selection_path):
        self.selection_path = Path(selection_path)
        self.selection = load_selection(self.selection_path)
        self.selection_sha256 = digest(self.selection_path.read_bytes())
        self.limits_json = canonical(self.selection['limits']).decode()
        self.directory = Path(self.selection['evidence'])
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'budget.sqlite3'
        self.limit_failed = False
        with self.transaction(initializing=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata(selection_sha256 TEXT PRIMARY KEY, limits_json TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS totals(kind TEXT PRIMARY KEY, limit_value INTEGER NOT NULL, charged INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS urls(url TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY, url TEXT NOT NULL, command_key TEXT NOT NULL, ordinal INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reservations(reservation_id TEXT PRIMARY KEY, request_id TEXT, kind TEXT NOT NULL, ceiling INTEGER NOT NULL, actual INTEGER, status TEXT NOT NULL)')
            rows = db.execute('SELECT * FROM metadata').fetchall()
            if not rows:
                db.execute('INSERT INTO metadata VALUES(?,?)', (self.selection_sha256, self.limits_json))
                for kind in ('attempts', 'received_bytes', 'expanded_bytes'):
                    db.execute('INSERT INTO totals VALUES(?,?,0)', (kind, self.selection['limits'][kind]))
            self._check_metadata(db)

    @contextmanager
    def transaction(self, *, initializing=False):
        if digest(self.selection_path.read_bytes()) != self.selection_sha256:
            raise ValueError('selection changed after budget verification')
        with closing(sqlite3.connect(self.path, timeout=2.0, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA busy_timeout=2000')
            db.execute('BEGIN IMMEDIATE')
            try:
                if not initializing:
                    self._check_metadata(db)
                yield db
                if digest(self.selection_path.read_bytes()) != self.selection_sha256:
                    raise ValueError('selection changed during budget transaction')
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _check_metadata(self, db):
        rows = [tuple(row) for row in db.execute('SELECT * FROM metadata')]
        if rows != [(self.selection_sha256, self.limits_json)]:
            raise ValueError('budget selection hash/limits differ from immutable selection')
        totals = {row['kind']: row['limit_value'] for row in db.execute('SELECT * FROM totals')}
        if totals != {kind: self.selection['limits'][kind] for kind in ('attempts', 'received_bytes', 'expanded_bytes')}:
            raise ValueError('budget limits differ from immutable selection')

    def _charge(self, db, kind, ceiling):
        row = db.execute('SELECT charged,limit_value FROM totals WHERE kind=?', (kind,)).fetchone()
        if row['charged'] + ceiling > row['limit_value']:
            self.limit_failed = True
            raise AcceptanceLimit('acceptance cumulative ' + kind + ' admission refused')
        db.execute('UPDATE totals SET charged=charged+? WHERE kind=?', (ceiling, kind))

    def reserve_send(self, url, command_key, *, request_id=None, ordinal=None):
        if url not in permitted_urls(self.selection):
            raise ValueError('request outside canonical declared acceptance scope')
        request_id, reservation_id = request_id or uuid.uuid4().hex, uuid.uuid4().hex
        with self.transaction() as db:
            if remaining_seconds(self.selection) <= 0:
                self.limit_failed = True
                raise AcceptanceLimit('original acceptance UTC window expired')
            exists = db.execute('SELECT 1 FROM urls WHERE url=?', (url,)).fetchone()
            if exists is None and db.execute('SELECT count(*) FROM urls').fetchone()[0] >= self.selection['limits']['distinct_urls']:
                self.limit_failed = True
                raise AcceptanceLimit('acceptance distinct URL admission refused')
            if db.execute('SELECT count(*) FROM requests WHERE url=?', (url,)).fetchone()[0] >= self.selection['limits']['attempts_per_url']:
                self.limit_failed = True
                raise AcceptanceLimit('acceptance five total attempts per URL exhausted')
            self._charge(db, 'attempts', 1)
            self._charge(db, 'received_bytes', RECEIVED_CEILING)
            if ordinal is None:
                ordinal = 1 + db.execute('SELECT count(*) FROM requests WHERE url=? AND command_key=?', (url, command_key)).fetchone()[0]
            if type(ordinal) is not int or not 1 <= ordinal <= 5:
                raise ValueError('production request ordinal must be within five total attempts')
            db.execute('INSERT OR IGNORE INTO urls VALUES(?)', (url,))
            db.execute('INSERT INTO requests VALUES(?,?,?,?)', (request_id, url, command_key, ordinal))
            db.execute('INSERT INTO reservations VALUES(?,?,?,?,NULL,?)',
                       (reservation_id, request_id, 'received_bytes', RECEIVED_CEILING, 'reserved'))
        return reservation_id

    def reserve_expanded(self):
        reservation_id = uuid.uuid4().hex
        with self.transaction() as db:
            if remaining_seconds(self.selection) <= 0:
                self.limit_failed = True
                raise AcceptanceLimit('original acceptance UTC window expired')
            self._charge(db, 'expanded_bytes', EXPANDED_CEILING)
            db.execute('INSERT INTO reservations VALUES(?,NULL,?,?,NULL,?)',
                       (reservation_id, 'expanded_bytes', EXPANDED_CEILING, 'reserved'))
        return reservation_id

    def settle(self, reservation_id, actual):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM reservations WHERE reservation_id=?', (reservation_id,)).fetchone()
            if row is None or row['status'] != 'reserved' or type(actual) is not int or not 0 <= actual <= row['ceiling']:
                raise ValueError('settlement requires one unspent reservation and verified bounded integer bytes')
            db.execute('UPDATE totals SET charged=charged-? WHERE kind=?', (row['ceiling'] - actual, row['kind']))
            db.execute("UPDATE reservations SET actual=?,status='settled' WHERE reservation_id=?", (actual, reservation_id))

    def retain_transport(self, reservation_id, receipt, *, confirmed):
        """Keep actual send traces even when a receipt cannot authorize a refund."""
        directory = self.directory / 'transports' / reservation_id
        directory.mkdir(parents=True, exist_ok=True)
        path = Path(receipt.temporary_path)
        files = []
        for name in ('body', 'receipt.json', 'transport.jsonl'):
            source = path.parent / name
            if source.is_file():
                body = source.read_bytes()
                write_once(directory / name, body)
                files.append({'path': str(directory / name), 'sha256': digest(body), 'bytes': len(body)})
        write_once(directory / 'boundary.json', canonical({'reservation_id': reservation_id,
            'positive_drain': confirmed, 'complete': receipt.complete, 'byte_count': receipt.byte_count, 'files': files}))

    def summary(self):
        with self.transaction() as db:
            totals = {row['kind']: row['charged'] for row in db.execute('SELECT * FROM totals')}
            requests = [dict(row) for row in db.execute('SELECT * FROM requests ORDER BY rowid')]
            reservations = [dict(row) for row in db.execute('SELECT * FROM reservations ORDER BY rowid')]
        sent = 0
        for path in (self.directory / 'transports').glob('*/transport.jsonl'):
            sent += sum(read.get('event') == 'socket-start' for read in
                        (json.loads(line) for line in path.read_text().splitlines()))
        return {'selection_sha256': self.selection_sha256, 'totals': totals, 'requests': requests,
                'reservations': reservations, 'distinct_urls': len({item['url'] for item in requests}),
                'actual_sent_requests': sent, 'actual_sent_scope': 'retained socket-start traces; uncertain crash traces may be unavailable'}


def budget_sender(real_sender, budget, identity=None):
    class AcceptanceSender:
        def __init__(self, *args, **kwargs):
            self.sender = real_sender(*args, **kwargs)

        def send(self, url, context, permit, *, cancellation):
            if identity is None:
                command_key = canonical([context.run_id, context.execution_id, context.command, context.attempt_id]).decode()
                request = {'command_key': command_key}
            else:
                request = identity(url, context, permit)
            reservation = budget.reserve_send(url, **request)
            try:
                receipt = self.sender.send(url, context, permit, cancellation=cancellation)
            except BaseException as error:
                receipt = getattr(error, 'receipt', None)
                if receipt is not None:
                    budget.retain_transport(reservation, receipt, confirmed=False)
                raise
            # Real BoundedSender returns only after positive HTTP-child join. Its
            # SenderFailure path never settles, including a stale send permit.
            budget.retain_transport(reservation, receipt, confirmed=True)
            if receipt.complete:
                budget.settle(reservation, receipt.byte_count)
            return receipt

        def close(self):
            if hasattr(self.sender, 'close'):
                self.sender.close()
    return AcceptanceSender



def production_request_identity(url, context, permit):
    from sec_edgar_ingest.config import Settings
    from sec_edgar_ingest.state import AcquisitionState, attempt_key
    from sec_edgar_ingest.storage import open_stores
    configured = Settings.from_mapping(context.to_mapping()['effective_config'])
    opened = open_stores(configured, access='operator')
    try:
        rows = AcquisitionState(opened[0]).request_history(context, url)
        matches = [row.to_mapping()['value'] for row in rows if row.value['request_id'] == permit.request_id]
        if len(matches) != 1 or matches[0]['attempt_key'] != attempt_key(context):
            raise ValueError('sender lacks exact production TransportAttempt admission')
        return {'request_id': permit.request_id, 'command_key': matches[0]['attempt_key'], 'ordinal': matches[0]['ordinal']}
    finally:
        close_stores(opened)

def install_wrappers(budget, cli, collection, transform, real_validator, download=None):
    real_sender = cli.BoundedSender
    cli.BoundedSender = budget_sender(real_sender, budget, production_request_identity)
    def validate(*args, **kwargs):
        reservation = budget.reserve_expanded()
        result = real_validator(*args, **kwargs)
        budget.settle(reservation, result.expanded_byte_count)
        return result
    collection.validate_envelope = validate
    transform.validate_envelope = validate
    if download is not None:
        download.validate_envelope = validate


def validate_call(call, selection, selection_path):
    exact(call, {'format_version', 'selection_sha256', 'argv', 'config_sha256'}, 'call')
    if call['format_version'] != CALL_VERSION or call['selection_sha256'] != digest(Path(selection_path).read_bytes()):
        raise ValueError('call differs from unchanged selection')
    argv = call['argv']
    if not isinstance(argv, list) or not argv or any(not isinstance(value, str) for value in argv):
        raise ValueError('call argv must be exact public command argv')
    if argv[0] not in ('discover', 'collect', 'transform', 'publish') or any(
            value.split('=')[0] in ('--today', '--fixture-pack', '--force', '--config-env') for value in argv):
        raise ValueError('only selected canonical low-level acceptance commands are permitted')
    if len(argv[1:]) % 2 or len(set(argv[1::2])) != len(argv[1::2]):
        raise ValueError('call must have unique explicit option/value pairs')
    options = dict(zip(argv[1::2], argv[2::2]))
    common = {'--config', '--run-id', '--execution-id', '--attempt-id', '--deadline'}
    allowed = common | ({'--mode', '--discovery-id'} if argv[0] == 'discover' else {'--workset'})
    if set(options) != allowed:
        raise ValueError('call options differ from closed low-level command interface')
    records = selection['configs']
    config = next((record for record in records.values() if record['path'] == options['--config']), None)
    if config is None or call['config_sha256'] != config['effective_sha256']:
        raise ValueError('call config differs from selected effective config')
    if options['--deadline'] != selection['window']['deadline_utc']:
        raise ValueError('call cannot change original immutable deadline')
    for name in ('--run-id', '--execution-id', '--attempt-id'):
        if re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]*', options[name]) is None:
            raise ValueError('invalid explicit command identity')
    if argv[0] == 'discover':
        if options['--mode'] not in records or options['--config'] != records[options['--mode']]['path']:
            raise ValueError('discovery must use its recorded mode config')
    return call


def make_call(selection, selection_path, argv):
    options = dict(zip(argv[1::2], argv[2::2]))
    record = next((item for item in selection['configs'].values() if item['path'] == options.get('--config')), {})
    return validate_call({'format_version': CALL_VERSION, 'selection_sha256': digest(Path(selection_path).read_bytes()),
                         'argv': list(argv), 'config_sha256': record.get('effective_sha256')}, selection, selection_path)


def child_argv(selection, selection_path, call_path):
    return [selection['native_python'], '-I', str(CHILD), '--selection', str(Path(selection_path).resolve()),
            '--call', str(Path(call_path).resolve())]


def scrub_environment():
    return {key: value for key, value in os.environ.items()
            if not key.startswith(('PYTHON', 'UV_')) and key not in ('VIRTUAL_ENV', 'CONDA_PREFIX')}


def ensure_native(args):
    """Stdlib-only re-exec before importing any application package."""
    manifest = Path(args.release).resolve() if args.command == 'prepare' else Path(require_prepared(args.selection)['release']['path'])
    if manifest.is_dir():
        manifest = manifest / 'release.json'
    python = manifest.parent / 'venv/bin/python'
    if not sys.flags.isolated or Path(sys.executable).absolute() != python:
        os.execve(str(python), [str(python), '-I', '-B', '-X', 'pycache_prefix=' + os.devnull,
                               str(Path(__file__).resolve()), *sys.argv[1:]], scrub_environment())
    from sec_edgar_ingest.runtime import preflight_current
    return preflight_current(manifest)


def verify_runtime(selection):
    from sec_edgar_ingest.config import load_config
    from sec_edgar_ingest.runtime import preflight_current
    from sec_edgar_ingest.storage.contracts import deployment_binding
    verified = preflight_current(Path(selection['release']['path']))
    if verified.release_id != selection['release_id'] or str(verified.python) != selection['native_python']:
        raise ValueError('current native release differs from selection')
    for record in [selection['release'], selection['input_config'], *selection['configs'].values(), *selection['harness'].values()]:
        if digest(Path(record['path']).read_bytes()) != record['sha256']:
            raise ValueError('retained input/config/release/harness bytes changed: ' + record['path'])
    settings = {}
    for mode, record in selection['configs'].items():
        configured = load_config(Path(record['path']))
        if configured.config_sha256 != record['effective_sha256'] or deployment_binding(configured) != selection['issuer_binding']:
            raise ValueError('effective config or deployment binding changed')
        if (configured.acquisition.mode != 'live' or configured.etl.parser_version != 'sec-index-parser-v1' or
                configured.etl.schema_version != 'sec-index-v1' or configured.runtime.release_manifest != selection['release']['path'] or
                configured.http.max_received_bytes != RECEIVED_CEILING or configured.http.max_expanded_bytes != EXPANDED_CEILING or
                configured.execution.max_run_seconds != 3600):
            raise ValueError('selected production runtime/parser/byte policy differs')
        if mode == 'quarterly' and (configured.backfill.start_quarter, configured.backfill.end_quarter) != ('2024Q1', '2024Q1'):
            raise ValueError('quarterly config range changed')
        if mode == 'daily' and (configured.backfill.end_quarter, configured.daily.start_date.isoformat()) != ('open', '2026-10-01'):
            raise ValueError('daily production discovery config changed')
        settings[mode] = configured
    return settings


def inventory(settings, today):
    """Read only: never create a missing root or bind a fresh store in prepare."""
    from sec_edgar_ingest.discovery import _inventory, required_daily_quarters
    from sec_edgar_ingest.state import AcquisitionState
    from sec_edgar_ingest.storage import open_stores
    from sec_edgar_ingest.models import quarter_for
    opened = ()
    class Empty:
        def pending_sources(self): return ()
        def failed_directories(self): return ()
        def daily_boundary(self): return None
    try:
        existed = Path(settings['daily'].storage.root).exists()
        if existed:
            opened = open_stores(settings['daily'], access='operator')
            state = AcquisitionState(opened[0])
        else:
            state = Empty()
        pending, failed = state.pending_sources(), state.failed_directories()
        periods = tuple(quarter_for(date.fromisoformat(source.period)) if source.kind == 'daily' else source.period for source in pending)
        periods += tuple(item.period for item in failed if re.fullmatch(r'[1-9][0-9]{3}Q[1-4]', item.period))
        quarters = required_daily_quarters(today, settings['daily'].daily.start_date, state.daily_boundary(), periods)
        result = {'root_existed': existed, 'pending_sources': [item.to_mapping() for item in pending],
                  'failed_directories': [item.to_mapping() for item in failed], 'daily_quarters': list(quarters)}
        for mode in ('quarterly', 'daily'):
            end = '2024Q1' if mode == 'quarterly' else quarter_for(today)
            units, _ = _inventory(settings[mode], state, mode, today, end)
            result[mode + '_listing_urls'] = [item['url'] for item in units]
        return result
    finally:
        close_stores(opened)


def build_selection(root, evidence, release, configs, input_config, issuer_binding, scope, *, started=None):
    started = started or datetime.now(timezone.utc)
    manifest = read_json(release)
    return {'format_version': SELECTION_VERSION,
        'release': {'path': str(release), 'sha256': digest(Path(release).read_bytes())},
        'release_id': manifest['release_id'], 'native_python': str(Path(release).parent / 'venv/bin/python'),
        'root': str(root), 'issuer_binding': issuer_binding, 'quarterly_periods': ['2024Q1'],
        'daily_dates': ['2026-10-14', '2026-10-15'], 'sources': source_records(), 'configs': configs,
        'input_config': input_config, 'window': {'started_utc': started.isoformat(),
            'deadline_utc': (started + timedelta(seconds=LIMITS['wall_seconds'])).isoformat()},
        'sole_issuer_confirmed': True,
        'sole_issuer_declaration': 'Owner confirmed all other project-budget collectors remain stopped throughout this acceptance window.',
        'limits': dict(LIMITS), 'evidence': str(evidence), 'inventory': scope,
        'harness': {name: {'path': str(path), 'sha256': digest(path.read_bytes())}
                    for name, path in [('driver', Path(__file__).resolve()), ('child', CHILD)]}}


def prepare(args, verified):
    from sec_edgar_ingest.config import load_config, Settings
    from sec_edgar_ingest.models import canonical_json, to_mapping_value
    from sec_edgar_ingest.storage.contracts import deployment_binding
    root, evidence, config_path = args.root.resolve(), args.evidence.resolve(), args.config.resolve()
    settings = load_config(config_path)
    if settings.storage.root != str(root) or settings.runtime.release_manifest != str(verified.directory / 'release.json'):
        raise ValueError('explicit root/release must match the selected candidate config')
    if not args.sole_issuer_confirmed:
        raise ValueError('prepare requires the recorded external sole-issuer declaration')
    configs, configured = {}, {}
    for mode in ('quarterly', 'daily'):
        value = settings.to_mapping()
        value['backfill'] = {'start_quarter': '2024Q1', 'end_quarter': '2024Q1'} if mode == 'quarterly' else {'start_quarter': settings.backfill.start_quarter, 'end_quarter': 'open'}
        value['daily']['start_date'] = '2026-10-01'
        configured[mode] = Settings.from_mapping(value)
        body = canonical_json(to_mapping_value(configured[mode].to_mapping()))
        path = evidence / 'configs' / (mode + '.json')
        configs[mode] = {'path': str(path), 'sha256': digest(body), 'effective_sha256': configured[mode].config_sha256}
    scope = inventory(configured, datetime.now(timezone.utc).date())
    selection = build_selection(root, evidence, verified.directory / 'release.json', configs,
        {'path': str(config_path), 'sha256': digest(config_path.read_bytes())}, deployment_binding(settings), scope)
    validate_selection(selection)
    if args.selection and args.selection.resolve() != evidence / 'selection.json':
        raise ValueError('selection output must be evidence/selection.json')
    # All read-only inventory/selection refusals precede evidence writes.
    for mode, record in configs.items():
        write_once(record['path'], canonical_json(to_mapping_value(configured[mode].to_mapping())))
    path = evidence / 'selection.json'
    write_once(path, canonical(selection))
    verify_runtime(selection)
    write_once(evidence / 'prepared.json', canonical({'format_version': 'sec-local-sec-prepared-v1',
        'selection_path': str(path), 'selection_sha256': digest(path.read_bytes())}))
    print(canonical({'selection': str(path), 'selection_sha256': digest(path.read_bytes()),
                     'status': 'prepared_no_http', 'deadline_utc': selection['window']['deadline_utc']}).decode())
    return 0


def close_stores(opened):
    for resource in reversed(opened):
        if hasattr(resource, 'close'):
            resource.close()


def evaluate_l12(proof):
    missing = [key for key in ('genuine_native', 'persistence', 'restart_reuse', 'exact_replay', 'bounded') if proof.get(key) is not True]
    if not any(item.get('validated') is True and type(item.get('rows')) is int and item['rows'] > 0 for item in proof.get('published_reads', [])):
        missing.append('accepted genuine publication/capture/nonempty validated read')
    return {'status': 'incomplete' if missing else 'pass', 'reasons': missing}


def supervise(argv, selection):
    """Bound one process group by original UTC and a fresh remaining monotonic cap.

    Forced reap, cancellation and surviving descendants cannot prove a safe HTTP
    drain. Production CLI cancellation is given five seconds before forced reap.
    """
    import selectors
    remaining = remaining_seconds(selection)
    if remaining <= 0:
        raise AcceptanceLimit('original acceptance window expired before dispatch')
    stop_mono = time.monotonic() + min(remaining, 3600)
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=scrub_environment(), start_new_session=True)
    stopped = None
    interrupted = False
    buffers = {process.stdout: bytearray(), process.stderr: bytearray()}
    def forward(signum, frame=None):
        nonlocal stopped, interrupted
        interrupted = True
        stopped = stopped or time.monotonic()
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass
    handlers = {}
    if threading.current_thread() is threading.main_thread():
        handlers = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with selectors.DefaultSelector() as selector:
            for stream in buffers:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map() or process.poll() is None:
                if stopped is None and (time.monotonic() >= stop_mono or remaining_seconds(selection) <= 0):
                    forward(signal.SIGTERM)
                if stopped is not None and time.monotonic() - stopped >= 5:
                    forward(signal.SIGKILL)
                    break
                for key, _ in selector.select(0.05):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        target = buffers[key.fileobj]
                        target.extend(chunk[:max(0, 1_048_576 - len(target))])
                        if len(target) >= 1_048_576:
                            forward(signal.SIGTERM)
            process.wait(timeout=5)
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            group_gone = True
        else:
            group_gone = False
            forward(signal.SIGKILL)
        return {'returncode': process.returncode, 'stdout': bytes(buffers[process.stdout]),
                'stderr': bytes(buffers[process.stderr]), 'drained': not interrupted and group_gone,
                'pid': process.pid, 'argv': list(argv)}
    finally:
        if process.poll() is None:
            forward(signal.SIGKILL)
            process.wait(timeout=5)
        for stream in buffers:
            stream.close()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def checked_result(call, execution, objects):
    """Only the exact durable production result authorizes a child completion."""
    from sec_edgar_ingest.models import canonical_json
    from sec_edgar_ingest.results import read_result, exit_code
    from sec_edgar_ingest.etl.commands import read_etl_result
    argv = call['argv']
    options = dict(zip(argv[1::2], argv[2::2]))
    reference = f"runs/sec/{options['--run-id']}/{argv[0]}/{options['--attempt-id']}/result.json"
    etl = argv[0] in ('transform', 'publish')
    result = (read_etl_result if etl else read_result)(reference, objects)
    context = result.context
    if (context.run_id, context.execution_id, context.command, context.attempt_id, context.deadline.isoformat(), context.config_sha256) != (
            options['--run-id'], options['--execution-id'], argv[0], options['--attempt-id'], options['--deadline'], call['config_sha256']):
        raise ValueError('retained result differs from exact immutable call')
    message = {'outcome': result.outcome, 'result_ref': reference}
    if etl:
        message.update(input_ref=result.input_ref, transformed_workset_ref=result.transformed_workset_ref)
    else:
        message.update(source_workset_ref=result.source_workset_ref, snapshot_workset_ref=result.snapshot_workset_ref)
    if (execution['drained'] is not True or execution['returncode'] != exit_code(result.outcome) or
            execution['stdout'] != canonical_json(message) + b'\n'):
        raise ValueError('child exit/stdout/drain differs from exact durable result')
    return result, reference


class AcceptanceRun:
    def __init__(self, selection_path, selection, settings):
        self.path, self.selection, self.settings = Path(selection_path), selection, settings
        self.evidence = Path(selection['evidence'])
        self.budget = Budget(selection_path)
        self.results = []
        self.reads = []
        self.reuse = []
        self.replays = []
        self.parents = []
        self.acquisitions = []

    @contextmanager
    def stores(self, mode='daily'):
        from sec_edgar_ingest.storage import open_stores
        opened = open_stores(self.settings[mode], access='operator')
        try:
            yield opened[0], opened[1]
        finally:
            close_stores(opened)

    def invoke(self, label, mode, command, flags, *, replay=False):
        if remaining_seconds(self.selection) <= 0:
            raise AcceptanceLimit('original acceptance window exhausted')
        directory = self.evidence / 'commands' / label
        directory.mkdir(parents=True, exist_ok=True)
        attempts = sorted(directory.glob('attempt-*'))
        attempt = attempts[-1] if attempts else directory / 'attempt-000'
        existing = attempt / 'call.json'
        if existing.exists():
            call = validate_call(read_json(existing), self.selection, self.path)
            if (attempt / 'execution.json').exists():
                execution = read_json(attempt / 'execution.json')
                if execution['drained'] is not True:
                    raise ValueError('uncertain prior child drain requires operator resolution; no automatic retry')
                # A completed result is replayed with the identical call. A safely
                # finished incomplete command gets a new attempt only on restart.
                if not (attempt / 'result.json').exists():
                    if execution['returncode'] == LIMIT_EXIT:
                        raise AcceptanceLimit('prior invocation exhausted acceptance budget')
                    attempt = directory / ('attempt-' + f'{len(attempts):03d}')
                    existing = attempt / 'call.json'
            else:
                raise ValueError('ambiguous dispatched call has no confirmed execution receipt')
        identity = label + '-' + attempt.name
        config = self.selection['configs'][mode]
        argv = [command, '--config', config['path'], '--run-id', 'accept-' + self.budget.selection_sha256[:16],
                '--execution-id', identity, '--attempt-id', identity,
                '--deadline', self.selection['window']['deadline_utc'], *flags]
        call = make_call(self.selection, self.path, argv)
        if existing.exists() and existing.read_bytes() != canonical(call):
            raise ValueError('resumed invocation changed config/IDs/intent/deadline')
        write_once(existing, canonical(call))
        execution = supervise(child_argv(self.selection, self.path, existing), self.selection)
        # Every fresh process launch retains independent streams, including replay.
        launches = attempt / 'launches'
        launch = launches / ('launch-' + uuid.uuid4().hex)
        launch.mkdir(parents=True)
        write_once(launch / 'stdout', execution['stdout'])
        write_once(launch / 'stderr', execution['stderr'])
        record = {key: value for key, value in execution.items() if key not in ('stdout', 'stderr')}
        record.update(stdout_sha256=digest(execution['stdout']), stderr_sha256=digest(execution['stderr']),
                      stdout_path=str(launch / 'stdout'), stderr_path=str(launch / 'stderr'))
        write_once(launch / 'execution.json', canonical(record))
        if not (attempt / 'execution.json').exists():
            write_once(attempt / 'execution.json', canonical(record))
        if execution['returncode'] == LIMIT_EXIT:
            raise AcceptanceLimit('child refused acceptance admission or deadline')
        with self.stores(mode) as (_, objects):
            result, reference = checked_result(call, execution, objects)
            body = objects.read(reference)
            write_once(attempt / 'result.json', body)
        item = {'label': label, 'call_path': str(existing), 'call_sha256': digest(existing.read_bytes()),
                'execution_path': str(launch / 'execution.json'), 'result_ref': reference,
                'result_sha256': digest(body), 'result_bytes': len(body), 'outcome': result.outcome}
        self.results.append(item)
        if replay:
            self.replays.append(item)
        return result

    def discover(self, mode):
        current = inventory(self.settings, datetime.now(timezone.utc).date())
        validate_daily_scope(self.selection, current['daily_quarters'])
        if not set(current[mode + '_listing_urls']) <= set(self.selection['inventory'][mode + '_listing_urls']):
            raise ValueError('production discovery scope changed before dispatch; revised selection required')
        result = self.invoke(mode + '-discover', mode, 'discover',
                             ['--mode', mode, '--discovery-id', 'accept-' + self.budget.selection_sha256[:16] + '-' + mode])
        if result.source_workset_ref is None:
            raise ValueError('discovery has no retained immutable source workset')
        from sec_edgar_ingest.workflows.provenance import read_parent
        with self.stores(mode) as (store, objects):
            parent = read_parent(result.source_workset_ref, store, objects)
            allowed = set(self.selection['inventory'][mode + '_listing_urls'])
            if not parent.discovery_complete or any(item.url not in allowed for item in parent.directories):
                raise ValueError('discovery incomplete or outside retained declared listing inventory')
            requested = {item['source_id'] for item in self.selection['sources'] if item['kind'] == mode}
            self.parents.append({'mode': mode, 'ref': result.source_workset_ref,
                'sha256': digest(objects.read(result.source_workset_ref)),
                'selected': sorted(requested), 'pending_unselected': [item.to_mapping() for item in parent.members if item.source_id not in requested],
                'directories': [item.to_mapping() for item in parent.directories]})
        return result.source_workset_ref

    def collect(self, mode, parent_ref, source):
        from sec_edgar_ingest.workflows.provenance import project_member
        with self.stores(mode) as (store, objects):
            projected = project_member(parent_ref, source['source_id'], store, objects)
            if projected['source']['canonical_url'] != source['url']:
                raise ValueError('selected daily/quarterly source identity differs from retained parent')
            member_ref = projected['member_ref']
            write_once(self.evidence / 'members' / (source['source_id'] + '.json'), canonical(projected))
        label = source['period']
        result = self.invoke(label + '-collect', mode, 'collect', ['--workset', member_ref])
        self.acquisitions.append({'source': source, 'outcome': result.outcome,
            'downloaded': result.downloaded, 'unchanged': result.unchanged, 'pending': result.pending,
            'quarantined': result.quarantined, 'failed': result.failed, 'snapshot_ref': result.snapshot_workset_ref})
        if result.snapshot_workset_ref is None:
            return None
        from sec_edgar_ingest.worksets import decode_snapshot_workset
        with self.stores(mode) as (_, objects):
            snapshots = decode_snapshot_workset(objects.read(result.snapshot_workset_ref))
            if len(snapshots.snapshots) != 1 or snapshots.snapshots[0].source_id != source['source_id']:
                raise ValueError('collection did not retain exactly its selected singleton body')
            snapshot = snapshots.snapshots[0]
            objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
            write_once(self.evidence / 'snapshots' / (source['source_id'] + '.json'), canonical(snapshot.to_mapping()))
        original = self.invoke(label + '-collect', mode, 'collect', ['--workset', member_ref], replay=True)
        if original != result:
            raise ValueError('fresh process replay changed exact retained result')
        reopened = self.invoke(label + '-reuse', mode, 'collect', ['--workset', member_ref])
        if reopened.snapshot_workset_ref is None or reopened.unchanged != 1 or reopened.downloaded != 0:
            raise ValueError('fresh process did not reopen/reuse exact accepted source')
        with self.stores(mode) as (_, objects):
            reused = decode_snapshot_workset(objects.read(reopened.snapshot_workset_ref))
            if reused.snapshots != snapshots.snapshots:
                raise ValueError('reuse changed the retained immutable snapshot')
        self.reuse.append({'source_id': source['source_id'], 'original': result.snapshot_workset_ref,
                           'reopened': reopened.snapshot_workset_ref, 'sha256': snapshot.sha256})
        return result.snapshot_workset_ref

    def process(self, mode, source, snapshot_ref):
        transformed = self.invoke(source['period'] + '-transform', mode, 'transform', ['--workset', snapshot_ref])
        if transformed.transformed_workset_ref is None:
            return
        published = self.invoke(source['period'] + '-publish', mode, 'publish',
                                ['--workset', transformed.transformed_workset_ref])
        for quarter in published.quarters:
            if quarter.outcome in ('published', 'unchanged'):
                self.capture(quarter.quarter)

    def capture(self, quarter):
        from sec_edgar_ingest.etl.reader import capture_quarter
        from sec_edgar_ingest.etl.state import EtlState
        from sec_edgar_ingest.etl.contracts import GenerationCapture
        with self.stores() as (store, objects):
            pointer = EtlState(store).pointer(quarter)
            if pointer is None:
                return
            generation = pointer.value['generation_id']
            path = self.evidence / 'captures' / (quarter + '-' + generation + '.json')
            if path.exists():
                capture = GenerationCapture.from_mapping(read_json(path))
            else:
                capture = capture_quarter(quarter, objects, EtlState(store))
                if capture is None:
                    raise ValueError('published generation has no capture')
                write_once(path, canonical(capture.to_mapping()))
            read = validate_read(capture, objects)
            write_once(path.with_suffix('.read.json'), canonical(read))
            self.reads.append(read)


def validate_read(capture, objects):
    from sec_edgar_ingest.etl.reader import read_quarter, validated_manifest
    from sec_edgar_ingest.etl.contracts import canonical_schema
    manifest = validated_manifest(capture, objects)
    keys, count, sources = set(), 0, set()
    expected_fields = set(canonical_schema().names)
    for row in read_quarter(capture, objects):
        value = row.to_mapping()
        if set(value) != expected_fields or row.schema_version != 'sec-index-v1' or row.parser_version != 'sec-index-parser-v1':
            raise ValueError('validated row schema/parser differs from declared production schema')
        key = row.cik, row.archive_path
        if key in keys:
            raise ValueError('duplicate canonical publication key')
        keys.add(key)
        sources.add((row.source_id, row.source_sha256))
        count += 1
    if count <= 0 or count != manifest.row_count:
        raise ValueError('captured generation must have exact nonempty validated rows')
    expected_sources = {(item.source.source_id, item.snapshot.sha256) for item in manifest.sources}
    if not sources <= expected_sources:
        raise ValueError('row provenance differs from generation sources')
    return {'quarter': capture.quarter, 'generation_id': capture.generation_id, 'rows': count,
            'validated': True, 'source_count': len(manifest.sources), 'row_source_count': len(sources),
            'manifest_ref': capture.manifest_ref, 'manifest_sha256': capture.manifest_sha256,
            'manifest_bytes': capture.manifest_bytes, 'schema': str(canonical_schema()),
            'sources': [item.to_mapping() for item in manifest.sources],
            'files': [item.to_mapping() for item in manifest.files]}


def execute_case(engine):
    """Quarterly discovery/collection precedes daily inventory and exact projection."""
    for mode in ('quarterly', 'daily'):
        parent = engine.discover(mode)
        for source in engine.selection['sources']:
            if source['kind'] == mode:
                snapshot = engine.collect(mode, parent, source)
                if snapshot is not None:
                    engine.process(mode, source, snapshot)


def run_acceptance(selection_path, selection, settings):
    # Recheck current discovery scope before ledger/root mutation. A changed
    # backlog may narrow after the selected quarterly collect, never widen here.
    scope = inventory(settings, datetime.now(timezone.utc).date())
    validate_daily_scope(selection, scope['daily_quarters'])
    for mode in ('quarterly', 'daily'):
        if not set(scope[mode + '_listing_urls']) <= set(selection['inventory'][mode + '_listing_urls']):
            raise ValueError('current pending/failed inventory exceeds unchanged selection; revised record required')
    if remaining_seconds(selection) <= 0:
        raise AcceptanceLimit('original acceptance window expired')
    engine = AcceptanceRun(selection_path, selection, settings)
    reason = None
    try:
        execute_case(engine)
    except Exception as error:
        reason = {'type': type(error).__name__, 'message': str(error)}
    budget = engine.budget.summary()
    proof = {'genuine_native': budget['actual_sent_requests'] > 0,
        'persistence': bool(engine.reuse), 'restart_reuse': bool(engine.reuse),
        'exact_replay': bool(engine.replays),
        'bounded': reason is None and remaining_seconds(selection) > 0 and not any(
            item['status'] == 'reserved' for item in budget['reservations']),
        'published_reads': engine.reads}
    result = {'format_version': 'sec-local-sec-acceptance-v1', 'selection_sha256': engine.budget.selection_sha256,
        'release_id': selection['release_id'], 'status': evaluate_l12(proof), 'proof': proof,
        'reason': reason, 'commands': engine.results, 'acquisitions': engine.acquisitions,
        'parents': engine.parents, 'restart_reuse': engine.reuse, 'exact_replays': engine.replays,
        'budget': budget, 'ended_utc': datetime.now(timezone.utc).isoformat()}
    try:
        result['pending_remainder'] = inventory(settings, datetime.now(timezone.utc).date())
    except Exception as error:
        result['pending_remainder'] = {'inspection_error': type(error).__name__ + ': ' + str(error)}
        result['proof']['bounded'] = False
        result['status'] = evaluate_l12(result['proof'])
    path = Path(selection['evidence']) / ('run-' + uuid.uuid4().hex + '.json')
    write_once(path, canonical(result))
    print(canonical({'status': result['status'], 'report': str(path), 'budget': budget['totals']}).decode())
    return 0 if result['status']['status'] == 'pass' else LIMIT_EXIT


def verify_acceptance(selection_path, selection, settings):
    """Offline durable verification, including every archived capture generation."""
    from sec_edgar_ingest.storage import open_stores
    from sec_edgar_ingest.etl.contracts import GenerationCapture
    reports = sorted(Path(selection['evidence']).glob('run-*.json'))
    if not reports:
        print(canonical({'status': 'not_run', 'L12': 'incomplete', 'reason': 'no genuine acceptance result retained'}).decode())
        return LIMIT_EXIT
    opened = open_stores(settings['daily'], access='operator')
    store, objects, _ = opened
    verified = []
    try:
        for path in reports:
            report = read_json(path)
            if report['selection_sha256'] != digest(Path(selection_path).read_bytes()) or report['release_id'] != selection['release_id']:
                raise ValueError('acceptance report selection/release differs')
            for item in report['commands']:
                call = validate_call(read_json(item['call_path']), selection, selection_path)
                if digest(Path(item['call_path']).read_bytes()) != item['call_sha256']:
                    raise ValueError('archived command bytes changed')
                record = read_json(item['execution_path'])
                stdout, stderr = Path(record['stdout_path']).read_bytes(), Path(record['stderr_path']).read_bytes()
                if digest(stdout) != record['stdout_sha256'] or digest(stderr) != record['stderr_sha256']:
                    raise ValueError('archived command streams changed')
                result, ref = checked_result(call, {**record, 'stdout': stdout}, objects)
                body = objects.read(ref)
                if ref != item['result_ref'] or digest(body) != item['result_sha256'] or len(body) != item['result_bytes']:
                    raise ValueError('retained result differs from archived command evidence')
            for item in report['proof']['published_reads']:
                capture_path = Path(selection['evidence']) / 'captures' / (item['quarter'] + '-' + item['generation_id'] + '.json')
                capture = GenerationCapture.from_mapping(read_json(capture_path))
                if validate_read(capture, objects) != item:
                    raise ValueError('validated read differs from archived captured generation')
            if evaluate_l12(report['proof']) != report['status']:
                raise ValueError('reported L12 differs from independent criteria')
            verified.append({'path': str(path), 'sha256': digest(path.read_bytes()), 'status': report['status']})
    finally:
        close_stores(opened)
    # Reading the ledger cannot refund uncertain/crashed reservations.
    if not (Path(selection['evidence']) / 'budget.sqlite3').is_file():
        raise ValueError('retained acceptance budget ledger is missing')
    budget = Budget(selection_path).summary()
    output = {'format_version': 'sec-local-sec-verification-v1', 'reports': verified,
              'budget': budget, 'verified_utc': datetime.now(timezone.utc).isoformat()}
    destination = Path(selection['evidence']) / ('verification-' + uuid.uuid4().hex + '.json')
    write_once(destination, canonical(output))
    print(canonical({'reports': verified, 'verification': str(destination)}).decode())
    return 0 if any(item['status']['status'] == 'pass' for item in verified) else LIMIT_EXIT

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare', allow_abbrev=False)
    for name in ('release', 'root', 'evidence', 'config'):
        prep.add_argument('--' + name, type=Path, required=True)
    prep.add_argument('--sole-issuer-confirmed', action='store_true')
    prep.add_argument('--selection', type=Path)
    for command in ('run', 'verify'):
        sub.add_parser(command, allow_abbrev=False).add_argument('--selection', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        verified = ensure_native(args)
        if args.command == 'prepare':
            return prepare(args, verified)
        selection = load_selection(args.selection)
        settings = verify_runtime(selection)
        return (run_acceptance if args.command == 'run' else verify_acceptance)(args.selection.resolve(), selection, settings)
    except AcceptanceLimit as error:
        print(canonical({'status': 'incomplete', 'outcome': 'acceptance_limit', 'error': str(error)}).decode())
        return LIMIT_EXIT
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        print(canonical({'status': 'incomplete', 'outcome': 'configuration', 'error': str(error)}).decode(), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
