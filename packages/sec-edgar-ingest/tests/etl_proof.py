"""Offline retained-input, real-process and installed-distribution evidence driver."""
from __future__ import annotations
from network_guard import install
install()

import argparse
from collections.abc import Sequence
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from datetime import date
import hashlib
import importlib.metadata
import json
import multiprocessing
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

from support import fixture_settings, retained_path, store_bundle
from support_etl import etl_context, seed_observation
from sec_edgar_ingest.config import pin_context, Settings
from sec_edgar_ingest.models import RunContext
from sec_edgar_ingest.etl.contracts import ObservationRef
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.publication import publish_quarter
from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter
from sec_edgar_ingest.etl.manifest import read_manifest

ROOT = Path(__file__).resolve().parents[3]
JOIN_SECONDS = 60
TERMINATE_SECONDS = 10


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def digest(path):
    body = path.read_bytes()
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


def inventory(root):
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob('*'))
            if p.is_file() and p != root / 'sha256.json'}


def metadata():
    return {'argv': sys.argv, 'cwd': str(Path.cwd()), 'python': sys.version,
            'platform': platform.platform(), 'executable': sys.executable,
            'dependencies': {name: importlib.metadata.version(name) for name in
                 ('sec-edgar-ingest', 'pyarrow', 'requests')},
            'all22_stage7_checks': 'reserved', 'network_guard': True}


def row(number=1, name='Example', day='2026-10-01'):
    return f'123456|{name}|10-K|{day}|edgar/data/123456/0000123456-26-{number:06}.txt\n'.encode()


def contexts(root, closed=False):
    settings, context = etl_context(command='publish', root=root)
    settings = fixture_settings(root=root, etl={'parser_version': context.parser_version}, fixture={'allow_clock_override': True})
    context = pin_context(settings, replace(context, config_sha256=settings.config_sha256,
                          effective_config={}, pinned_on=None), date(2027, 1, 1) if closed else date(2026, 10, 7))[0]
    return settings, context


def capture_evidence(objects, state):
    capture = capture_quarter('2026Q4', objects, state)
    if capture is None:
        return None
    manifest = read_manifest(capture, objects)
    return {'capture': capture.to_mapping(), 'manifest': manifest.to_mapping(),
            'rows': [value.to_mapping() for value in read_quarter(capture, objects)]}


def race_child(root, label, ref, settings, context, barrier, winner_done, gate):
    """Observe actual store CAS; the barrier is used only on the first candidate."""
    install()
    root = Path(root)
    with (root / f'{label}.stdout').open('w') as out, (root / f'{label}.stderr').open('w') as err, redirect_stdout(out), redirect_stderr(err):
        events = []
        try:
            store, objects, leases = store_bundle(root / 'store')
            leases.close()
            state = EtlState(store)
            actual_commit = state.commit_pointer
            first = True
            def commit(quarter, value, previous):
                event = {'event': 'cas', 'base': previous.to_mapping() if previous else None, 'candidate': value}
                events.append(event)
                try:
                    result = actual_commit(quarter, value, previous)
                except Exception as error:
                    event['exception'] = type(error).__name__
                    raise
                event['version'] = result.version
                return result
            state.commit_pointer = commit
            def observe(point):
                nonlocal first
                events.append({'event': point})
                if point == 'publication.before_pointer' and first:
                    first = False
                    barrier.wait(JOIN_SECONDS)
                    if gate and label == 'loser':
                        assert winner_done.wait(JOIN_SECONDS)
                if point == 'publication.after_pointer' and label == 'winner':
                    winner_done.set()
            result = publish_quarter('2026Q4', (ObservationRef.from_mapping(ref),), RunContext.from_mapping(context),
                                     Settings.from_mapping(settings), objects, state, observer=observe)
            save(root / f'{label}.json', {**metadata(), 'pid': os.getpid(), 'events': events, 'result': result.to_mapping(),
                                         'final': capture_evidence(objects, state)})
            store.close()
        except BaseException:
            traceback.print_exc()
            save(root / f'{label}.failure.json', {'pid': os.getpid(), 'events': events})
            raise


def join_children(children, *, timeout=None):
    """Reap every supplied owned child before reporting any deadline failure."""
    timeout = JOIN_SECONDS if timeout is None else timeout
    failures = []
    for child in children:
        try:
            child.join(timeout)
        except Exception as error:
            failures.append(f'child {child.pid} join failed: {error}')
        if child.is_alive():
            failures.append(f'own proof child {child.pid} exceeded finite deadline')
            try:
                child.terminate()
                child.join(TERMINATE_SECONDS)
            except Exception as error:
                failures.append(f'child {child.pid} terminate failed: {error}')
            if child.is_alive():
                try:
                    child.kill()
                    child.join(TERMINATE_SECONDS)
                except Exception as error:
                    failures.append(f'child {child.pid} kill failed: {error}')
            if child.is_alive():
                failures.append(f'child {child.pid} remains alive after bounded kill')
    if failures:
        raise AssertionError('; '.join(failures))
    return [child.exitcode for child in children]


def prove_race(root, initial=False, gate=False):
    root.mkdir(parents=True)
    store, objects, leases = store_bundle(root / 'store')
    leases.close()
    state = EtlState(store)
    settings, context = contexts(root / 'store', gate)
    if initial:
        publish_quarter('2026Q4', (seed_observation(objects, state, context, settings, kind='daily', period='2026-10-01'),),
                        context, settings, objects, state)
    refs = [seed_observation(objects, state, context, settings, kind='daily', period='2026-10-02', rows=row(1) + row(2) if gate else row(2)),
            seed_observation(objects, state, context, settings, kind='quarterly' if gate else 'daily',
                             period='2026Q4' if gate else '2026-10-03', rows=row(1 if gate else 3))]
    before = state.pointer('2026Q4')
    store.close()
    spawn = multiprocessing.get_context('spawn')
    barrier, done = spawn.Barrier(2), spawn.Event()
    children = [spawn.Process(target=race_child, args=(str(root), label, ref.to_mapping(), settings.to_mapping(),
                 context.to_mapping(), barrier, done, gate)) for label, ref in zip(('winner', 'loser'), refs)]
    try:
        for child in children:
            child.start()
    except BaseException as error:
        try:
            join_children([child for child in children if child.pid is not None], timeout=0)
        except AssertionError as cleanup_error:
            error.add_note(str(cleanup_error))
        raise
    exits = join_children(children)
    assert exits == [0, 0], exits
    reports = [json.loads((root / f'{label}.json').read_text()) for label in ('winner', 'loser')]
    attempts = [[e for e in report['events'] if e['event'] == 'cas'] for report in reports]
    assert attempts[0][0]['base'] == attempts[1][0]['base'] == (before.to_mapping() if before else None)
    assert reports[0]['pid'] != reports[1]['pid'] != os.getpid()
    assert sum(r['result']['conflicts'] for r in reports) == 1
    assert sum('exception' in e for events in attempts for e in events) == 1
    store, objects, leases = store_bundle(root / 'store')
    leases.close()
    final = capture_evidence(objects, EtlState(store))
    expected = {1, 2} if gate else ({1, 2, 3} if initial else {2, 3})
    assert {int(r['archive_path'].split('-')[-1].split('.')[0]) for r in final['rows']} == expected
    if gate:
        assert reports[1]['result']['outcome'] == 'awaiting_approval'
        assert len(list(store.scan('Candidate', {}))) == 1
    else:
        assert all(r['result']['outcome'] == 'published' for r in reports)
        assert {ref.source.source_id for ref in refs} <= {s['source']['source_id'] for s in final['manifest']['sources']}
    report = {'children': reports, 'exits': exits, 'final': final,
              'candidates': [v.to_mapping() for v in store.scan('Candidate', {})],
              'retained_files': inventory(root / 'store' / 'objects')}
    store.close()
    save(root / 'proof.json', report)
    return report


def cli_child(root, argv, boundary):
    install()
    from sec_edgar_ingest import cli
    root = Path(root)
    with (root / 'child.stdout').open('w') as out, (root / 'child.stderr').open('w') as err, redirect_stdout(out), redirect_stderr(err):
        def death(point):
            if point == boundary:
                save(root / 'death.json', {'pid': os.getpid(), 'boundary': point, 'exit': 73})
                out.flush()
                err.flush()
                os._exit(73)
        publish = cli.run_publish
        write = cli.write_etl_result
        with patch.object(cli, 'run_publish', side_effect=lambda *a, **kw: publish(*a, **kw, observer=death)), \
             patch.object(cli, 'write_etl_result', side_effect=lambda *a, **kw: write(*a, **kw, observer=death)):
            raise SystemExit(cli.main(argv))


def invoke(argv, root, label):
    from sec_edgar_ingest.cli import main
    from io import StringIO
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err), \
         patch('sec_edgar_ingest.cli.Coordinator', side_effect=AssertionError('collector forbidden')), \
         patch('sec_edgar_ingest.cli.BoundedSender', side_effect=AssertionError('transport forbidden')), \
         patch('sec_edgar_ingest.cli.RequestClient', side_effect=AssertionError('request forbidden')):
        code = main(argv)
    record = {**metadata(), 'argv': argv, 'exit': code, 'stdout': out.getvalue(), 'stderr': err.getvalue()}
    save(root / (label + '.json'), record)
    return code, json.loads(out.getvalue())


def prove_death(root, boundary):
    from support import fixture_source
    from support_etl import seed_snapshot
    root.mkdir(parents=True)
    settings, context = contexts(root / '.fixture-state')
    config = root / 'config.json'
    save(config, settings.to_mapping())
    body = b'CIK|Company Name|Form Type|Date Filed|File Name\n-----\n' + row(2).replace(b'2026-10-01', b'20261001')
    store, objects, snapshots = seed_snapshot(root / '.fixture-state', fixture_source('2026-10-02', 'daily'), body)
    state = EtlState(store)
    publish_quarter('2026Q4', (seed_observation(objects, state, context, settings),), context, settings, objects, state)
    before = capture_evidence(objects, state)
    def args(command, ref):
        return [command, '--config', str(config), '--run-id', 'death', '--execution-id', 'fixed', '--attempt-id', command,
                '--deadline', context.deadline.isoformat(), '--workset', ref]
    code, transformed = invoke(args('transform', f'worksets/sec/snapshot/sha256={snapshots.workset_id}/workset.json'), root, 'transform')
    assert code == 0
    argv = args('publish', transformed['transformed_workset_ref'])
    store.close()
    child = multiprocessing.get_context('spawn').Process(target=cli_child, args=(str(root), argv, boundary))
    child.start()
    assert join_children([child]) == [73]
    store, objects, leases = store_bundle(root / '.fixture-state')
    leases.close()
    state = EtlState(store)
    killed = capture_evidence(objects, state)
    post = boundary in ('publication.after_pointer', 'etl_result.after_object')
    assert (killed != before) == post
    pointer = state.pointer('2026Q4')
    intents = {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('command.json')}
    code, resumed = invoke(argv, root, 'resumed')
    assert code == 0
    if post:
        assert state.pointer('2026Q4') == pointer
    final_pointer = state.pointer('2026Q4')
    assert invoke(argv, root, 'repeat')[0] == 0
    assert state.pointer('2026Q4') == final_pointer
    assert intents == {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('command.json')}
    final = capture_evidence(objects, state)
    assert len(final['rows']) == 2
    report = {'boundary': boundary, 'pid': child.pid, 'exit': child.exitcode, 'before': before, 'after_death': killed,
              'final': final, 'same_frozen_intents': intents, 'resumed': resumed,
              'records': {kind: [v.to_mapping() for v in store.scan(kind, {})] for kind in
                          ('Attempt', 'Processing', 'PublicationReceipt', 'QuarterPublication')}}
    store.close()
    save(root / 'proof.json', report)
    return report


def process_proof(root):
    races = [prove_race(root / name, initial=initial, gate=gate) for name, initial, gate in
             (('insert', False, False), ('replace', True, False), ('gate', False, True))]
    deaths = [prove_death(root / boundary, boundary) for boundary in
              ('candidate.after_data', 'publication.before_pointer', 'publication.after_pointer', 'etl_result.after_object')]
    return {'races': races, 'deaths': deaths}


def specimen_path(evidence, item, inspection):
    """Resolve imported listing bytes without requiring historical specimen aliases."""
    if any(item[name] != inspection[name] for name in ('evidence_id', 'url', 'original_bytes', 'original_sha256')):
        raise ValueError('specimen matrix and inspection identities differ')
    listing = retained_path(evidence + f"/listings/{item['evidence_id']}.body")
    expected = {'bytes': item['original_bytes'], 'sha256': item['original_sha256']}
    if digest(listing) != expected:
        raise ValueError('retained listing differs from the original matrix/inspection bytes')
    historical_name = evidence + '/' + inspection['original_path']
    try:
        historical = retained_path(historical_name)
    except KeyError as error:
        if error.args != (historical_name,):
            raise
        historical = listing
    if historical.read_bytes() != listing.read_bytes():
        raise ValueError('historical specimen alias differs from the mapped listing bytes')
    return listing


def specimens(output):
    """Scan complete original receipts and apply the production duplicate policy."""
    from collections import Counter
    from datetime import datetime, timezone
    from sec_edgar_ingest.models import Source, Snapshot, url_source_id
    from sec_edgar_ingest.etl.parser import iter_observations, PARSER_VERSION, SCHEMA_VERSION, ParseError
    from sec_edgar_ingest.etl.transform import _seen_database, _remember_observation
    evidence = 'specs/evidence/sec-filing-index-ingestion/stage-1'
    receipts = []
    for item in json.loads(retained_path(evidence + '/specimens/matrix.json').read_text())['matrix']:
        inspection = json.loads(retained_path(evidence + '/' + item['inspection']).read_text())
        path = specimen_path(evidence, item, inspection)
        actual = digest(path)
        assert actual == {'bytes': item['original_bytes'], 'sha256': item['original_sha256']}
        assert actual == {'bytes': inspection['original_bytes'], 'sha256': inspection['original_sha256']}
        assert path.read_bytes() == retained_path(evidence + f"/listings/{item['evidence_id']}.body").read_bytes()
        kind = 'quarterly' if item['text_family'] == 'quarterly ISO-date master' else 'daily'
        url = item['url']
        alias = url.endswith('/full-index/master.zip')
        if alias:
            url = 'https://www.sec.gov/Archives/edgar/full-index/2026/QTR4/master.zip'
        period = url.split('/')[-3] + 'Q' + url.split('/')[-2][-1] if kind == 'quarterly' else datetime.strptime(url.split('/')[-1][7:15], '%Y%m%d').date().isoformat()
        rep = 'zip' if kind == 'quarterly' else 'idx'
        source = Source(url_source_id(url), url, kind, period, rep)
        snapshot = Snapshot(source.source_id, actual['sha256'],
                            f"raw/sec/indexes/kind={kind}/period={period}/sha256={actual['sha256']}/master.{rep}",
                            actual['bytes'], datetime.now(timezone.utc), {}, rep, 'sec-' + kind + '-envelope-v1')
        selected = set(inspection['observations'].get('date_bound_raw_rows', {}).values()) | set(inspection['observations'].get('representative_raw_rows', {}).values())
        database_path = output / (item['evidence_id'] + '.sqlite')
        database = _seen_database(database_path)
        count = duplicates = 0
        quarters, bounds, conflicts, selected_rows = Counter(), [], [], []
        for observation in iter_observations(path, source, snapshot, parser_version=PARSER_VERSION, schema_version=SCHEMA_VERSION):
            count += 1
            day = observation.row.filing_date
            if not bounds:
                bounds = [day, day]
            bounds = [min(bounds[0], day), max(bounds[1], day)]
            quarters[f'{day.year}Q{(day.month - 1) // 3 + 1}'] += 1
            prior = database.execute('SELECT payload FROM seen WHERE cik=? AND path=?', (observation.row.cik, observation.row.archive_path)).fetchone()
            try:
                _remember_observation(database, observation)
            except ParseError as error:
                conflicts.append({'physical_line': error.line_number, 'reason': error.reason,
                                  'original_fields': observation.original_fields, 'row': observation.row.to_mapping(),
                                  'first_payload': json.loads(prior[0])})
            else:
                duplicates += prior is not None
            raw = '|'.join(observation.original_fields)
            if raw in selected:
                selected_rows.append({'line': observation.line_number, 'original_fields': observation.original_fields,
                                      'row': observation.row.to_mapping()})
                selected.remove(raw)
        distinct = database.execute('SELECT COUNT(*) FROM seen').fetchone()[0]
        database.close()
        database_path.unlink()
        expected = [datetime.strptime(v, '%Y%m%d').date().isoformat() if len(v) == 8 else v for v in item['filing_date_bounds']]
        assert count == item['row_count'] and [d.isoformat() for d in bounds] == expected and not selected
        receipt = {'evidence_id': item['evidence_id'], 'original_path': str(path), **actual, 'source': source.to_mapping(),
                   'root_alias_matching_quarter_context': alias, 'selected_family': item['text_family'], 'rows': count,
                   'date_bounds': expected, 'quarter_counts': dict(quarters), 'selected_rows': selected_rows,
                   'identical_duplicate_keys': duplicates, 'conflicts': conflicts, 'distinct_keys': distinct,
                   'source_acceptance': 'blocked' if conflicts else 'accepted'}
        receipts.append(receipt)
        save(output / (item['evidence_id'] + '.json'), receipt)
    return {'receipts': receipts, 'exit': int(any(r['conflicts'] for r in receipts)),
            'scope': 'ten complete retained receipts only; synthetic legacy goldens are separate tests'}


def sequence(output):
    """Exercise real command codecs and durable stores, followed by process races."""
    from support import fixture_source
    from support_etl import seed_snapshot
    from sec_edgar_ingest.etl.contracts import decode_transformed
    root = output / 'raw-sequence'
    root.mkdir()
    settings, context = contexts(root / '.fixture-state')
    config = root / 'config.json'
    save(config, settings.to_mapping())
    body = b'CIK|Company Name|Form Type|Date Filed|File Name\n-----\n' + (row(1) + row(2, day='2026-09-30')).replace(b'2026-10-01', b'20261001').replace(b'2026-09-30', b'20260930')
    store, objects, snapshots = seed_snapshot(root / '.fixture-state', fixture_source('2026-10-01', 'daily'), body)
    snapshot_ref = f'worksets/sec/snapshot/sha256={snapshots.workset_id}/workset.json'
    origin_before = objects.read(snapshot_ref)
    raw_before = {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('master.idx')}
    def argv(command, ref, attempt):
        return [command, '--config', str(config), '--run-id', 'sequence', '--execution-id', 'fixed', '--attempt-id', attempt,
                '--deadline', context.deadline.isoformat(), '--workset', ref]
    code, transformed = invoke(argv('transform', snapshot_ref, 'transform-v1'), root, 'transform-v1')
    assert code == 0
    old = decode_transformed(objects.read(transformed['transformed_workset_ref']))
    publish_args = argv('publish', transformed['transformed_workset_ref'], 'publish-v1')
    assert invoke(publish_args, root, 'publish-v1')[0] == 0
    before_rows = {q: [r.to_mapping() for r in read_quarter(capture_quarter(q, objects, EtlState(store)), objects)]
                   for q in ('2026Q3', '2026Q4')}
    pointers = [v.to_mapping() for v in store.scan('QuarterPublication', {})]
    assert len(pointers) == 2
    assert invoke(publish_args, root, 'repeat-v1')[0] == 0
    assert invoke(argv('publish', transformed['transformed_workset_ref'], 'noop-v1'), root, 'noop-v1')[1]['outcome'] == 'unchanged'
    assert [v.to_mapping() for v in store.scan('QuarterPublication', {})] == pointers
    changed = settings.to_mapping()
    changed['etl']['parser_version'] = 'fixture-index-parser-v2'
    save(config, changed)
    code, replay = invoke(argv('transform', snapshot_ref, 'transform-v2') + ['--force'], root, 'transform-v2')
    assert code == 0
    new = decode_transformed(objects.read(replay['transformed_workset_ref']))
    assert old.origin_context == new.origin_context
    assert old.context.parser_version != new.context.parser_version
    assert invoke(argv('publish', replay['transformed_workset_ref'], 'publish-v2'), root, 'publish-v2')[0] == 0
    assert objects.read(snapshot_ref) == origin_before
    assert raw_before == {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('master.idx')}
    state = EtlState(store)
    captures = {q: {'capture': capture_quarter(q, objects, state).to_mapping(),
                    'rows': [r.to_mapping() for r in read_quarter(capture_quarter(q, objects, state), objects)]}
                for q in ('2026Q3', '2026Q4')}
    business = lambda rows: [{k: v for k, v in r.items() if k not in ('parser_version', 'schema_version', 'source_id', 'source_sha256')} for r in rows]
    assert all(business(before_rows[q]) == business(captures[q]['rows']) for q in before_rows)
    assert len(list(store.scan('TransportAttempt', {}))) == 0
    save(root / 'state.json', {kind: [v.to_mapping() for v in store.scan(kind, {})] for kind in
                             ('Attempt', 'Binding', 'Processing', 'QuarterPublication', 'PublicationReceipt')})
    store.close()
    # Open and closed membership use the same actual publication API as commands.
    membership = output / 'membership'
    store, objects, leases = store_bundle(membership)
    leases.close()
    state = EtlState(store)
    settings, context = contexts(membership)
    initial = seed_observation(objects, state, context, settings, rows=row(1) + row(2))
    publish_quarter('2026Q4', (initial,), context, settings, objects, state)
    revised = seed_observation(objects, state, context, settings, rows=row(1), seconds=1)
    assert publish_quarter('2026Q4', (revised,), context, settings, objects, state).outcome == 'published'
    opened = capture_evidence(objects, state)
    assert opened['manifest']['unresolved_absence'] == 1 and len(opened['rows']) == 2
    closed_settings, closed_context = contexts(membership, True)
    gated = publish_quarter('2026Q4', (revised,), closed_context, closed_settings, objects, state)
    assert gated.outcome == 'awaiting_approval'
    assert capture_evidence(objects, state) == opened
    gate_records = [v.to_mapping() for v in store.scan('Candidate', {})]
    store.close()
    return {'exit': 0, 'raw_hashes_unchanged': raw_before, 'origin_context': old.origin_context.to_mapping(),
            'before_replay_rows': before_rows, 'captures': captures, 'open_absence': opened, 'closed_gate': gated.to_mapping(), 'gate_records': gate_records,
            'processes': process_proof(output / 'processes')}


def run_logged(argv, cwd, output, label, env=None, *, timeout=300):
    started = time.monotonic()
    environment = os.environ if env is None else env
    record = {**metadata(), 'argv': [str(v) for v in argv], 'cwd': str(cwd),
              'timeout_seconds': timeout, 'environment': {
                  'pythonpath_present': 'PYTHONPATH' in environment,
                  'uv_python_downloads': environment.get('UV_PYTHON_DOWNLOADS')}}
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        record.update(outcome='timeout', exit=None, runtime_seconds=time.monotonic() - started)
        for stream, captured in (('stdout', error.stdout), ('stderr', error.stderr)):
            if isinstance(captured, bytes):
                path = output / f'{label}.{stream}.bin'
                path.write_bytes(captured)
                record[stream + '_raw_file'] = path.name
                record[stream + '_raw'] = digest(path)
                record[stream] = captured.decode('utf-8', errors='backslashreplace')
            else:
                record[stream] = captured or ''
        save(output / (label + '.json'), record)
        raise
    record.update(outcome='completed', exit=result.returncode, stdout=result.stdout, stderr=result.stderr,
                  runtime_seconds=time.monotonic() - started)
    save(output / (label + '.json'), record)
    assert result.returncode == 0, record
    return record


def installed(output):
    from workflow_proof import installed as native_installed
    return native_installed(output)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('specimens', 'sequence', 'installed'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = metadata()
    try:
        with (output / 'stdout.txt').open('w') as out, (output / 'stderr.txt').open('w') as err, redirect_stdout(out), redirect_stderr(err):
            report.update({'specimens': specimens, 'sequence': sequence, 'installed': installed}[args.mode](output))
    except BaseException:
        report.update(exit=1, traceback=traceback.format_exc())
    report['runtime_seconds'] = time.monotonic() - started
    save(output / 'report.json', report)
    save(output / 'sha256.json', inventory(output))
    print(json.dumps({'report': str(output / 'report.json'), 'exit': report['exit'], 'all22_stage7_checks': 'reserved'}))
    return report['exit']


if __name__ == '__main__':
    raise SystemExit(main())
