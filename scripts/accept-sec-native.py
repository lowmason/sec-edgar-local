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
        source = args[0] if args else kwargs.get('source')
        receipt = args[1] if len(args) > 1 else kwargs.get('receipt')
        write_once(budget.directory / 'validations' / (reservation + '.json'), canonical({
            'reservation_id': reservation, 'expanded_byte_count': result.expanded_byte_count,
            'source': source.to_mapping() if hasattr(source, 'to_mapping') else None,
            'received_sha256': getattr(receipt, 'sha256', None)}))
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


def ensure_native(args, *, verify_current=True):
    """Stdlib-only re-exec before importing any application package."""
    manifest = Path(args.release).resolve() if args.command == 'prepare' else Path(require_prepared(args.selection)['release']['path'])
    if manifest.is_dir():
        manifest = manifest / 'release.json'
    python = manifest.parent / 'venv/bin/python'
    if not sys.flags.isolated or Path(sys.executable).absolute() != python:
        os.execve(str(python), [str(python), '-I', '-B', '-X', 'pycache_prefix=' + os.devnull,
                               str(Path(__file__).resolve()), *sys.argv[1:]], scrub_environment())
    if not verify_current:
        return None
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


def supervise(argv, selection, *, environ=None, on_started=None):
    """Bound one process group by original UTC and a fresh remaining monotonic cap.

    Forced reap, cancellation and surviving descendants cannot prove a safe HTTP
    drain. Production CLI cancellation is given five seconds before forced reap.
    """
    import selectors
    remaining = remaining_seconds(selection)
    if remaining <= 0:
        raise AcceptanceLimit('original acceptance window expired before dispatch')
    start_mono = time.monotonic()
    stop_mono = start_mono + min(remaining, 3600)
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=scrub_environment() if environ is None else environ, start_new_session=True)
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
        if on_started is not None:
            on_started(process.pid)
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
                'stderr': bytes(buffers[process.stderr]), 'drained': not interrupted and group_gone and time.monotonic() < stop_mono,
                'pid': process.pid, 'argv': list(argv), 'monotonic_budget': min(remaining, 3600),
                'monotonic_elapsed': time.monotonic() - start_mono}
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
    from sec_edgar_ingest.config import load_config, pin_context
    rebuilt, _ = pin_context(load_config(Path(options['--config'])), context, context.pinned_on)
    if rebuilt != context:
        raise ValueError('retained result changes its exact selected effective configuration')
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
        launch_id = uuid.uuid4().hex
        launch = attempt / 'launches' / ('launch-' + launch_id)
        dispatch = {'format_version': 'sec-local-sec-dispatch-v1',
            'selection_sha256': self.budget.selection_sha256, 'call_path': str(existing),
            'call_sha256': digest(existing.read_bytes()), 'launch_path': str(launch),
            'argv': child_argv(self.selection, self.path, existing),
            'dispatched_utc': datetime.now(timezone.utc).isoformat()}
        write_once(launch / 'dispatch.json', canonical(dispatch))
        write_once(self.evidence / 'dispatches' / (launch_id + '.json'), canonical(dispatch))
        item = {'label': label, 'call_path': str(existing), 'call_sha256': dispatch['call_sha256'],
            'execution_path': str(launch / 'execution.json'), 'result_ref': None,
            'result_sha256': None, 'result_bytes': None, 'outcome': 'unfinished'}
        self.results.append(item)
        execution = supervise(dispatch['argv'], self.selection,
            on_started=lambda pid: write_once(launch / 'started.json', canonical({'pid': pid})))
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
        item.update(result_ref=reference, result_sha256=digest(body), result_bytes=len(body), outcome=result.outcome)
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



def inspect_commands(selection_path, selection, objects):
    """Inventory frozen filesystem authority, never a report's chosen command list."""
    evidence = Path(selection['evidence'])
    calls = sorted(evidence.glob('commands/*/attempt-*/call.json'))
    registries = {path.stem: (path, read_json(path)) for path in (evidence / 'dispatches').glob('*.json')}
    for _, value in registries.values():
        exact(value, {'format_version', 'selection_sha256', 'call_path', 'call_sha256', 'launch_path', 'argv', 'dispatched_utc'}, 'dispatch registry')
    actual_launches = set(evidence.glob('commands/*/attempt-*/launches/*'))
    expected_launches = {Path(value['launch_path']) for _, value in registries.values()}
    if actual_launches != expected_launches:
        raise ValueError('frozen dispatch registry and launch inventory differ (including failed launches)')
    known_calls = {str(path) for path in calls}
    if any(value['call_path'] not in known_calls for _, value in registries.values()):
        raise ValueError('dispatch references missing frozen call')
    records, results = [], []
    for path in calls:
        call = validate_call(read_json(path), selection, selection_path)
        if path.read_bytes() != canonical(call):
            raise ValueError('frozen call bytes changed')
        launches = sorted([(registry, value) for registry, value in registries.values()
                           if value['call_path'] == str(path)], key=lambda item: item[1]['dispatched_utc'])
        if not launches:
            raise ValueError('frozen call lacks a retained dispatch')
        first_execution = None
        for registry, dispatch in launches:
            exact(dispatch, {'format_version', 'selection_sha256', 'call_path', 'call_sha256',
                'launch_path', 'argv', 'dispatched_utc'}, 'dispatch')
            launch = Path(dispatch['launch_path'])
            if (launch.parent != path.parent / 'launches' or launch.name != 'launch-' + registry.stem or
                    dispatch['format_version'] != 'sec-local-sec-dispatch-v1' or
                    dispatch['selection_sha256'] != digest(Path(selection_path).read_bytes()) or
                    dispatch['call_sha256'] != digest(path.read_bytes()) or
                    dispatch['argv'] != child_argv(selection, selection_path, path) or
                    (launch / 'dispatch.json').read_bytes() != canonical(dispatch)):
                raise ValueError('dispatch path/hash/native argv differs from frozen selection/call')
            dispatched = utc(dispatch['dispatched_utc'])
            if not utc(selection['window']['started_utc']) <= dispatched <= utc(selection['window']['deadline_utc']):
                raise ValueError('dispatch outside original acceptance window')
            execution = read_json(launch / 'execution.json')
            started = read_json(launch / 'started.json')
            if (execution['argv'] != dispatch['argv'] or type(execution['pid']) is not int or execution['pid'] <= 0 or
                    started != {'pid': execution['pid']} or type(execution['drained']) is not bool or
                    type(execution['returncode']) is not int):
                raise ValueError('launch execution/started receipt differs')
            if first_execution is None:
                first_execution = execution
            stdout, stderr = (launch / 'stdout').read_bytes(), (launch / 'stderr').read_bytes()
            if (execution['stdout_path'] != str(launch / 'stdout') or execution['stderr_path'] != str(launch / 'stderr') or
                    digest(stdout) != execution['stdout_sha256'] or digest(stderr) != execution['stderr_sha256']):
                raise ValueError('launch stream hashes or paths differ')
            item = {'label': path.parent.parent.name, 'call_path': str(path), 'call_sha256': digest(path.read_bytes()),
                'execution_path': str(launch / 'execution.json'), 'result_ref': None,
                'result_sha256': None, 'result_bytes': None, 'outcome': 'unfinished',
                'returncode': execution['returncode'], 'drained': execution['drained'],
                'pid': execution['pid'], 'dispatched_utc': dispatch['dispatched_utc']}
            options = dict(zip(call['argv'][1::2], call['argv'][2::2]))
            ref = f"runs/sec/{options['--run-id']}/{call['argv'][0]}/{options['--attempt-id']}/result.json"
            try:
                objects.read(ref)
            except FileNotFoundError:
                # Failed/limited launches have no authoritative result. Their
                # exact streams/exit remain inventoried and cannot prove success.
                pass
            else:
                result, reference = checked_result(call, {**execution, 'stdout': stdout}, objects)
                body = objects.read(reference)
                if (path.parent / 'result.json').read_bytes() != body:
                    raise ValueError('archived attempt result differs from durable result')
                item.update(result_ref=reference, result_sha256=digest(body), result_bytes=len(body), outcome=result.outcome)
                results.append({'record': item, 'call': call, 'result': result})
            records.append(item)
        if read_json(path.parent / 'execution.json') != first_execution:
            raise ValueError('first attempt execution receipt differs from complete launch inventory')
    records.sort(key=lambda item: (item['dispatched_utc'], item['execution_path']))
    return records, results


def inspect_budget(selection_path, selection, store):
    """Read-only reconciliation of every reservation, receipt and production admission."""
    evidence = Path(selection['evidence'])
    path = evidence / 'budget.sqlite3'
    if not path.is_file():
        raise ValueError('retained acceptance budget ledger is missing')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        metadata = [tuple(row) for row in db.execute('SELECT * FROM metadata')]
        if metadata != [(digest(Path(selection_path).read_bytes()), canonical(selection['limits']).decode())]:
            raise ValueError('ledger metadata differs from immutable selection/limits')
        totals_rows = [dict(row) for row in db.execute('SELECT * FROM totals')]
        requests = [dict(row) for row in db.execute('SELECT * FROM requests ORDER BY rowid')]
        reservations = [dict(row) for row in db.execute('SELECT * FROM reservations ORDER BY rowid')]
        urls = {row[0] for row in db.execute('SELECT url FROM urls')}
    kinds = ('attempts', 'received_bytes', 'expanded_bytes')
    if {row['kind']: row['limit_value'] for row in totals_rows} != {kind: selection['limits'][kind] for kind in kinds}:
        raise ValueError('ledger limits differ')
    by_request = {item['request_id']: item for item in requests}
    if (len(by_request) != len(requests) or urls != {item['url'] for item in requests} or
            not urls <= permitted_urls(selection) or len(urls) > selection['limits']['distinct_urls'] or
            any(sum(item['url'] == url for item in requests) > selection['limits']['attempts_per_url'] for url in urls)):
        raise ValueError('ledger URL/request admission inventory differs or exceeds bounds')
    charged = {'attempts': len(requests), 'received_bytes': 0, 'expanded_bytes': 0}
    received, actual_sent, admissions = set(), 0, []
    transport_rows = {} if store is None else {row.value['request_id']: row.to_mapping()['value'] for row in store.scan('TransportAttempt', {})}
    for reservation in reservations:
        kind = reservation['kind']
        ceiling = RECEIVED_CEILING if kind == 'received_bytes' else EXPANDED_CEILING
        if (kind not in ('received_bytes', 'expanded_bytes') or reservation['ceiling'] != ceiling or
                reservation['status'] not in ('reserved', 'settled') or
                (reservation['status'] == 'reserved' and reservation['actual'] is not None) or
                (reservation['status'] == 'settled' and (type(reservation['actual']) is not int or not 0 <= reservation['actual'] <= ceiling))):
            raise ValueError('ledger reservation is not conservative/canonical')
        charged[kind] += ceiling if reservation['status'] == 'reserved' else reservation['actual']
        rid = reservation['reservation_id']
        if kind == 'expanded_bytes':
            if reservation['request_id'] is not None:
                raise ValueError('expanded reservation unexpectedly names a request')
            if reservation['status'] == 'settled':
                validation = read_json(evidence / 'validations' / (rid + '.json'))
                if validation['reservation_id'] != rid or validation['expanded_byte_count'] != reservation['actual']:
                    raise ValueError('expanded settlement lacks matching successful validation evidence')
            continue
        request_id = reservation['request_id']
        if request_id not in by_request or request_id in received:
            raise ValueError('received reservation differs from exact single request admission')
        received.add(request_id)
        request = by_request[request_id]
        if type(request['ordinal']) is not int or not 1 <= request['ordinal'] <= 5:
            raise ValueError('ledger request ordinal differs from production bounds')
        production = transport_rows.get(request_id)
        if production is None or type(production['ordinal']) is not int or (production['attempt_key'], production['url'], production['ordinal']) != (
                request['command_key'], request['url'], request['ordinal']):
            raise ValueError('ledger request differs from production TransportAttempt')
        directory = evidence / 'transports' / rid
        boundary = None
        files = {}
        if directory.exists():
            boundary = read_json(directory / 'boundary.json')
            exact(boundary, {'reservation_id', 'positive_drain', 'complete', 'byte_count', 'files'}, 'transport boundary')
            if (type(boundary['positive_drain']) is not bool or type(boundary['complete']) is not bool or
                    type(boundary['byte_count']) is not int or not 0 <= boundary['byte_count'] <= RECEIVED_CEILING):
                raise ValueError('transport boundary has invalid drain/count fields')
            if boundary['reservation_id'] != rid:
                raise ValueError('transport boundary differs from reservation')
            for ref in boundary['files']:
                exact(ref, {'path', 'sha256', 'bytes'}, 'transport file')
                if type(ref['bytes']) is not int or ref['bytes'] < 0:
                    raise ValueError('transport file byte count must be a bounded integer')
                local = Path(ref['path'])
                if local.parent != directory or local.name not in ('body', 'receipt.json', 'transport.jsonl') or local.name in files:
                    raise ValueError('transport file reference is not its exact retained boundary')
                body = local.read_bytes()
                if len(body) != ref['bytes'] or digest(body) != ref['sha256']:
                    raise ValueError('retained transport file hash/length differs')
                files[local.name] = body
            if {item.name for item in directory.iterdir()} != set(files) | {'boundary.json'}:
                raise ValueError('transport file inventory differs from retained hash references')
        events = [json.loads(line) for line in files.get('transport.jsonl', b'').splitlines()]
        sent = [item for item in events if item.get('event') == 'socket-start']
        if len(sent) > 1:
            raise ValueError('one admission contains multiple actual sends')
        for event in sent:
            if not utc(selection['window']['started_utc']) <= utc(event['utc']) <= utc(selection['window']['deadline_utc']):
                raise ValueError('actual socket start exceeded original acceptance window')
        actual_sent += len(sent)
        complete = False
        if boundary is not None and boundary['positive_drain'] is True and boundary['complete'] is True:
            metadata_value = json.loads(files.get('receipt.json', b'{}'))
            complete = (metadata_value.get('complete') is True and metadata_value.get('unsafe') is False and
                        metadata_value.get('error') is None and len(files.get('body', b'')) == boundary['byte_count'])
        if reservation['status'] == 'settled' and (not complete or reservation['actual'] != boundary['byte_count']):
            raise ValueError('received refund lacks complete positively drained matching receipt')
        admissions.append({'request': request, 'production': production, 'socket_started': len(sent) == 1,
                           'complete': complete, 'sha256': digest(files['body']) if 'body' in files else None})
    if received != set(by_request):
        raise ValueError('request admission lacks its full received reservation')
    totals = {row['kind']: row['charged'] for row in totals_rows}
    if totals != charged or any(type(value) is not int or value < 0 or value > selection['limits'][kind] for kind, value in charged.items()):
        raise ValueError('ledger charged totals differ from conservative reservations')
    known = {item['reservation_id'] for item in reservations if item['kind'] == 'received_bytes'}
    transport_directory = evidence / 'transports'
    if transport_directory.exists() and any(item.name not in known for item in transport_directory.iterdir()):
        raise ValueError('unaccounted retained transport')
    summary = {'selection_sha256': digest(Path(selection_path).read_bytes()), 'totals': totals,
        'requests': requests, 'reservations': reservations, 'distinct_urls': len(urls),
        'actual_sent_requests': actual_sent, 'actual_sent_scope': 'retained socket-start traces; uncertain crash traces may be unavailable'}
    return summary, admissions


def derive_source_proof(selection, launches, admissions, store, objects):
    """Derive selected persistence/replay/reuse and publication from production refs."""
    from sec_edgar_ingest.models import RunContext
    from sec_edgar_ingest.state import attempt_key
    from sec_edgar_ingest.runtime import native_descriptor
    from sec_edgar_ingest.worksets import decode_snapshot_workset
    from sec_edgar_ingest.workflows.provenance import read_member, read_parent
    from sec_edgar_ingest.etl.contracts import decode_transformed, GenerationCapture
    by_key = {}
    for item in launches:
        context = item['result'].context
        by_key[attempt_key(context)] = item
    native_admissions = []
    for admission in admissions:
        production = admission['production']
        context = RunContext.from_mapping(production['context'])
        item = by_key.get(production['attempt_key'])
        if item is None:
            # A failed command may have no result; its context is still bound to
            # the frozen call by the complete command inventory below.
            continue
        if (context != item['result'].context or context.to_mapping()['runtime'] != native_descriptor(selection['release_id']) or
                context.to_mapping()['effective_config']['acquisition']['mode'] != 'live'):
            continue
        if admission['socket_started'] and admission['complete']:
            native_admissions.append(admission)
    acquired, reused, replayed, selected_snapshots = {}, set(), set(), {}
    for source in selection['sources']:
        identity = source['source_id']
        members_path = Path(selection['evidence']) / 'members' / (identity + '.json')
        if not members_path.exists():
            continue
        member_value = read_json(members_path)
        member = read_member(member_value, store, objects)
        if len(member.members) != 1 or member.members[0].source_id != identity or member.members[0].canonical_url != source['url']:
            raise ValueError('archived projection differs from exact selected source')
        parent = read_parent(member_value['parent_ref'], store, objects)
        if not parent.discovery_complete:
            raise ValueError('selected acquisition parent is incomplete')
        matching = [item for item in launches if item['call']['argv'][0] == 'collect' and
                    dict(zip(item['call']['argv'][1::2], item['call']['argv'][2::2])).get('--workset') == member_value['member_ref']]
        for item in matching:
            result = item['result']
            if result.snapshot_workset_ref is None:
                continue
            snapshot_set = decode_snapshot_workset(objects.read(result.snapshot_workset_ref))
            if len(snapshot_set.snapshots) != 1 or snapshot_set.snapshots[0].source_id != identity:
                raise ValueError('selected collection result does not contain exact singleton snapshot')
            snapshot = snapshot_set.snapshots[0]
            objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
            if result.downloaded == 1:
                acquired[identity] = item
                selected_snapshots[identity] = snapshot
        original = acquired.get(identity)
        if original is None:
            continue
        snapshot = selected_snapshots[identity]
        same = [item for item in matching if item['record']['call_path'] == original['record']['call_path'] and
                item['record']['result_sha256'] == original['record']['result_sha256']]
        if len({item['record']['pid'] for item in same}) >= 2:
            replayed.add(identity)
        for item in matching:
            result = item['result']
            if result.downloaded != 0 or result.unchanged != 1 or result.snapshot_workset_ref is None:
                continue
            reused_set = decode_snapshot_workset(objects.read(result.snapshot_workset_ref))
            if (reused_set.snapshots == (snapshot,) and item['record']['call_path'] != original['record']['call_path'] and
                    item['record']['pid'] != original['record']['pid']):
                reused.add(identity)
    published, seen, published_sources = [], set(), {}
    for item in launches:
        result = item['result']
        if result.context.command != 'publish':
            continue
        transformed = decode_transformed(objects.read(result.input_ref))
        producers = [entry for entry in launches if entry['result'].context.command == 'transform' and
                     entry['result'].transformed_workset_ref == result.input_ref]
        if not producers:
            raise ValueError('published workset lacks retained selected transform command')
        selected = {obs.source.source_id for obs in transformed.observations if obs.source.source_id in selected_snapshots and
                    obs.snapshot == selected_snapshots[obs.source.source_id]}
        if not selected:
            continue
        if transformed.snapshot_workset_ref not in {entry['result'].snapshot_workset_ref for entry in acquired.values()} or not any(producer['result'].input_ref == transformed.snapshot_workset_ref for producer in producers):
            raise ValueError('publication transform does not bind selected snapshot workset')
        for quarter in result.quarters:
            if quarter.outcome not in ('published', 'unchanged') or quarter.generation_id is None:
                continue
            key = quarter.quarter, quarter.generation_id
            if key in seen:
                continue
            seen.add(key)
            capture_path = Path(selection['evidence']) / 'captures' / (quarter.quarter + '-' + quarter.generation_id + '.json')
            capture = GenerationCapture.from_mapping(read_json(capture_path))
            if (capture.quarter, capture.generation_id, capture.manifest_ref) != (quarter.quarter, quarter.generation_id, quarter.manifest_ref):
                raise ValueError('capture differs from exact selected published generation')
            read = validate_read(capture, objects)
            pairs = {(obs['source']['source_id'], obs['snapshot']['sha256']) for obs in read['sources']}
            if not any((identity, selected_snapshots[identity].sha256) in pairs for identity in selected):
                raise ValueError('capture has no exact selected source snapshot provenance')
            if read_json(capture_path.with_suffix('.read.json')) != read:
                raise ValueError('archived read differs from independently validated selected capture')
            published.append(read)
            published_sources[(read['quarter'], read['generation_id'])] = selected
    native_selected = {identity for identity, snapshot in selected_snapshots.items() if any(
        item['request']['url'] == next(source['url'] for source in selection['sources'] if source['source_id'] == identity) and
        item['sha256'] == snapshot.sha256 for item in native_admissions)}
    qualified = native_selected & reused & replayed
    proven_reads = [read for read in published if published_sources[(read['quarter'], read['generation_id'])] & qualified]
    return {'genuine_native': bool(native_selected), 'persistence': bool(native_selected),
        'restart_reuse': bool(native_selected & reused), 'exact_replay': bool(native_selected & replayed),
        'published_reads': proven_reads, 'selected_publications': published, 'selected_acquired': sorted(acquired), 'selected_reused': sorted(reused),
        'selected_replayed': sorted(replayed), 'selected_native': sorted(native_selected)}


def derive_evidence(selection_path, selection, store, objects):
    commands, launches = inspect_commands(selection_path, selection, objects)
    budget, admissions = inspect_budget(selection_path, selection, store)
    # Every budget admission, including failures without results, must bind a
    # declared frozen call. Conversely an actual transport cannot be omitted.
    from sec_edgar_ingest.runtime import native_descriptor
    from sec_edgar_ingest.models import RunContext
    from sec_edgar_ingest.state import attempt_key
    from sec_edgar_ingest.config import load_config, pin_context
    calls = {item['call_path']: read_json(item['call_path']) for item in commands}
    allowed = {}
    for call in calls.values():
        options = dict(zip(call['argv'][1::2], call['argv'][2::2]))
        key = digest(canonical({name: value for name, value in {
            'run_id': options['--run-id'], 'execution_id': options['--execution-id'],
            'command': call['argv'][0], 'attempt_id': options['--attempt-id'],
            'runtime': native_descriptor(selection['release_id'])}.items()}))
        allowed[key] = (call, options)
    for item in admissions:
        request, production = item['request'], item['production']
        if request['command_key'] not in allowed:
            raise ValueError('budget admission lacks frozen native command')
        call, options = allowed[request['command_key']]
        context = RunContext.from_mapping(production['context'])
        rebuilt, _ = pin_context(load_config(Path(options['--config'])), context, context.pinned_on)
        if rebuilt != context:
            raise ValueError('transport admission changes its exact selected effective configuration')
        if (attempt_key(context) != request['command_key'] or context.config_sha256 != call['config_sha256'] or
                context.deadline.isoformat() != selection['window']['deadline_utc'] or
                context.to_mapping()['effective_config']['acquisition']['mode'] != 'live'):
            raise ValueError('transport admission context differs from selected live command')
    proof = derive_source_proof(selection, launches, admissions, store, objects)
    expected_captures = {item['quarter'] + '-' + item['generation_id'] + '.json' for item in proof['selected_publications']}
    actual_captures = {path.name for path in (Path(selection['evidence']) / 'captures').glob('*.json') if not path.name.endswith('.read.json')}
    if actual_captures != expected_captures:
        raise ValueError('capture inventory contains missing or unrelated selected publication evidence')
    proof['bounded'] = bool(commands) and all(item['drained'] and item['returncode'] != LIMIT_EXIT and item['outcome'] != 'unfinished' for item in commands) and not any(
        item['status'] == 'reserved' for item in budget['reservations'])
    return commands, budget, proof

def worker_argv(selection_path, selection):
    return [selection['native_python'], '-I', '-B', '-X', 'pycache_prefix=' + os.devnull,
            str(Path(__file__).resolve()), 'run', '--selection', str(selection_path)]


def run_acceptance(selection_path, selection, settings):
    """Supervise the complete verified driver, including local/C-level reads."""
    worker = os.environ.get('SEC_LOCAL_ACCEPTANCE_WORKER')
    selection_hash = digest(Path(selection_path).read_bytes())
    if worker:
        request = read_json(worker)
        if request != {'format_version': 'sec-local-sec-worker-v1',
            'selection_sha256': selection_hash, 'selection_path': str(selection_path),
            'supervisor_pid': os.getppid()}:
            raise ValueError('internal native worker admission differs')
        return _run_acceptance(selection_path, selection, settings)
    if remaining_seconds(selection) <= 0:
        raise AcceptanceLimit('original acceptance window expired before full driver dispatch')
    directory = Path(selection['evidence']) / 'workers' / uuid.uuid4().hex
    request = directory / 'request.json'
    write_once(request, canonical({'format_version': 'sec-local-sec-worker-v1',
        'selection_sha256': selection_hash, 'selection_path': str(selection_path),
        'supervisor_pid': os.getpid()}))
    started = datetime.now(timezone.utc)
    execution = supervise(worker_argv(selection_path, selection), selection,
        environ={**scrub_environment(), 'SEC_LOCAL_ACCEPTANCE_WORKER': str(request)},
        on_started=lambda pid: write_once(directory / 'started.json', canonical({'pid': pid})))
    # The CLI stages have their own process groups. A cancelled driver can leave
    # one pending; cancel every known unfinished group and never refund it.
    pending = []
    if not execution['drained']:
        for launch in Path(selection['evidence']).glob('commands/*/attempt-*/launches/*/started.json'):
            if not (launch.parent / 'execution.json').exists():
                pid = read_json(launch)['pid']
                try:
                    os.killpg(pid, signal.SIGKILL)
                    pending.append(pid)
                except ProcessLookupError:
                    pass
    write_once(directory / 'stdout', execution['stdout'])
    write_once(directory / 'stderr', execution['stderr'])
    record = {key: value for key, value in execution.items() if key not in ('stdout', 'stderr')}
    record.update(format_version='sec-local-sec-watchdog-v1', selection_sha256=selection_hash,
        started_utc=started.isoformat(), ended_utc=datetime.now(timezone.utc).isoformat(),
        stdout_sha256=digest(execution['stdout']), stderr_sha256=digest(execution['stderr']),
        outcome='completed' if execution['drained'] else 'acceptance_limit', cancelled_cli_groups=pending)
    write_once(directory / 'watchdog.json', canonical(record))
    if execution['stdout']:
        sys.stdout.write(execution['stdout'].decode('utf-8', errors='replace'))
    if execution['stderr']:
        sys.stderr.write(execution['stderr'].decode('utf-8', errors='replace'))
    return execution['returncode'] if execution['drained'] else LIMIT_EXIT

def _run_acceptance(selection_path, selection, settings):
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
    commands = engine.results
    try:
        with engine.stores() as (store, objects):
            commands, budget, proof = derive_evidence(selection_path, selection, store, objects)
    except Exception as error:
        reason = reason or {'type': type(error).__name__, 'message': str(error)}
        proof = {'genuine_native': False, 'persistence': False, 'restart_reuse': False,
                 'exact_replay': False, 'bounded': False, 'published_reads': []}
    proof['bounded'] = proof['bounded'] and reason is None and remaining_seconds(selection) > 0
    result = {'format_version': 'sec-local-sec-acceptance-v1', 'selection_sha256': engine.budget.selection_sha256,
        'release_id': selection['release_id'], 'status': evaluate_l12(proof), 'proof': proof,
        'reason': reason, 'commands': commands, 'acquisitions': engine.acquisitions,
        'worker_request': os.environ.get('SEC_LOCAL_ACCEPTANCE_WORKER'),
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
    """Reconstruct the latest complete evidence snapshot independently, offline."""
    from sec_edgar_ingest.storage import open_stores
    evidence = Path(selection['evidence'])
    reports = [(path, read_json(path)) for path in evidence.glob('run-*.json')]
    if not reports:
        print(canonical({'status': 'incomplete', 'L12': 'incomplete',
            'reason': 'no complete genuine acceptance report; any retained worker/launch evidence remains incomplete'}).decode())
        return LIMIT_EXIT
    for path, report in reports:
        if (report['selection_sha256'] != digest(Path(selection_path).read_bytes()) or
                report['release_id'] != selection['release_id']):
            raise ValueError('acceptance report selection/release differs')
        utc(report['ended_utc'])
    reports.sort(key=lambda item: (item[1]['ended_utc'], str(item[0])))
    latest_path, latest = reports[-1]
    opened = open_stores(settings['daily'], access='operator')
    try:
        commands, budget, proof = derive_evidence(selection_path, selection, opened[0], opened[1])
    finally:
        close_stores(opened)
    if latest['commands'] != commands:
        raise ValueError('reported command inventory omits or changes frozen launches, including failed launches')
    if latest['budget'] != budget:
        raise ValueError('reported budget differs from reconciled conservative ledger/transport evidence')
    # All historical report snapshots must still name existing immutable launches.
    current = {item['execution_path']: item for item in commands}
    for _, report in reports:
        for command in report['commands']:
            if command['execution_path'] not in current or current[command['execution_path']] != command:
                raise ValueError('historical report names a missing or changed launch')
    workers = sorted((evidence / 'workers').glob('*'))
    if not workers:
        raise ValueError('full-run watchdog evidence is missing')
    watchdogs = []
    for worker in workers:
        request = read_json(worker / 'request.json')
        watch = read_json(worker / 'watchdog.json')
        if (request['selection_sha256'] != digest(Path(selection_path).read_bytes()) or
                request['selection_path'] != str(selection_path) or
                watch['selection_sha256'] != request['selection_sha256'] or
                watch['argv'] != worker_argv(selection_path, selection) or
                digest((worker / 'stdout').read_bytes()) != watch['stdout_sha256'] or
                digest((worker / 'stderr').read_bytes()) != watch['stderr_sha256'] or
                read_json(worker / 'started.json') != {'pid': watch['pid']}):
            raise ValueError('full-run watchdog/stream identity differs')
        if not utc(selection['window']['started_utc']) <= utc(watch['started_utc']) <= utc(selection['window']['deadline_utc']):
            raise ValueError('driver worker began outside original window')
        finished = (watch['drained'] is True and watch['outcome'] == 'completed' and
                    utc(watch['ended_utc']) <= utc(selection['window']['deadline_utc']) and
                    0 <= watch['monotonic_elapsed'] < watch['monotonic_budget'] <= selection['limits']['wall_seconds'])
        proof['bounded'] = proof['bounded'] and finished
        watchdogs.append({'path': str(worker / 'watchdog.json'), 'sha256': digest((worker / 'watchdog.json').read_bytes())})
    worker_request = Path(latest['worker_request']) if latest.get('worker_request') else None
    if worker_request is None or worker_request.parent not in workers:
        raise ValueError('latest report lacks exact full-run native watchdog binding')
    latest_watch = read_json(worker_request.parent / 'watchdog.json')
    if not utc(latest_watch['started_utc']) <= utc(latest['ended_utc']) <= utc(latest_watch['ended_utc']):
        raise ValueError('run report completion differs from full-run watchdog interval')
    if latest.get('reason') is not None:
        proof['bounded'] = False
    derived_status = evaluate_l12(proof)
    if latest['proof'] != proof or latest['status'] != derived_status:
        raise ValueError('reported L12 proof/status differs from independently derived selected evidence')
    if latest_watch['returncode'] != (0 if derived_status['status'] == 'pass' else LIMIT_EXIT):
        raise ValueError('full-run exit differs from independently derived L12 status')
    output = {'format_version': 'sec-local-sec-verification-v1',
        'reports': [{'path': str(path), 'sha256': digest(path.read_bytes())} for path, _ in reports],
        'latest_report': str(latest_path), 'status': derived_status, 'proof': proof, 'commands': commands,
        'budget': budget, 'watchdogs': watchdogs, 'verified_utc': datetime.now(timezone.utc).isoformat()}
    destination = evidence / ('verification-' + uuid.uuid4().hex + '.json')
    write_once(destination, canonical(output))
    print(canonical({'status': derived_status, 'verification': str(destination)}).decode())
    return 0 if derived_status['status'] == 'pass' else LIMIT_EXIT


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
        supervising = args.command == 'run' and not os.environ.get('SEC_LOCAL_ACCEPTANCE_WORKER')
        verified = ensure_native(args, verify_current=not supervising)
        if args.command == 'prepare':
            return prepare(args, verified)
        selection = load_selection(args.selection)
        if supervising:
            return run_acceptance(args.selection.resolve(), selection, {})
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
