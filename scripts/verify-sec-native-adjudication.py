#!/usr/bin/env python3
"""Supplement an immutable incomplete SEC run by offline evidence adjudication.

This analyzer performs no acquisition and never changes a selection, budget,
original report, watchdog or frozen original harness. Its output is separately
versioned and retains the original exit/status alongside the corrected analysis.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True
sys.pycache_prefix = os.devnull

METHOD = 'native-runtime-mapping-comparison-v1'
DRIVER = Path(__file__).resolve().with_name('accept-sec-native.py')
RUNTIME_PROOF_FIELDS = {'genuine_native', 'persistence', 'restart_reuse', 'exact_replay',
                        'selected_native', 'published_reads'}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def historical_selection(selection):
    """Relocate only byte verification to exact archived original script files.

    The immutable selected document itself is never rewritten. Standard run and
    verify continue checking their original current-script paths and will refuse
    the changed driver. Only this offline analyzer reads archived harness bytes.
    """
    historical = copy.deepcopy(selection)
    directory = Path(selection['evidence']) / 'harness-original'
    for role, filename in [('driver', 'accept-sec-native.py'), ('child', 'sec-acceptance-child.py')]:
        record = historical['harness'][role]
        if Path(record['path']).name != filename:
            raise ValueError('archived original harness filename differs')
        archived = directory / filename
        if not archived.is_file() or sha256(archived) != record['sha256']:
            raise ValueError('archived original harness bytes differ from selected SHA256')
        record['path'] = str(archived)
    return historical


def proof_delta(original, corrected):
    """Permit only the known false-negative fields to change in the supplement."""
    if set(original) != set(corrected) or any(original[key] != corrected[key]
            for key in original if key not in RUNTIME_PROOF_FIELDS):
        raise ValueError('adjudication changes evidence outside runtime representation correction')
    if (any(original.get(key) is not False for key in
            ('genuine_native', 'persistence', 'restart_reuse', 'exact_replay')) or
            original.get('selected_native') != [] or original.get('published_reads') != []):
        raise ValueError('original proof is not the recorded native-runtime false-negative case')
    def status(proof):
        complete = all(proof.get(key) is True for key in
            ('genuine_native', 'persistence', 'restart_reuse', 'exact_replay', 'bounded'))
        nonempty = any(item.get('validated') is True and type(item.get('rows')) is int and item['rows'] > 0
                       for item in proof.get('published_reads', []))
        return 'pass' if complete and nonempty else 'incomplete'
    return {'original_status': status(original), 'corrected_status': status(corrected),
            'changed_fields': sorted(key for key in original if original[key] != corrected[key])}


def native_bootstrap(selection):
    python = Path(selection['native_python'])
    if not sys.flags.isolated or Path(sys.executable).absolute() != python:
        environment = {key: value for key, value in os.environ.items()
            if not key.startswith(('PYTHON', 'UV_')) and key not in ('VIRTUAL_ENV', 'CONDA_PREFIX')}
        os.execve(str(python), [str(python), '-I', '-B', '-X', 'pycache_prefix=' + os.devnull,
            str(Path(__file__).resolve()), *sys.argv[1:]], environment)


def verify_original_watchdogs(api, selection_path, selection, report_path, report, original_verification):
    evidence = Path(selection['evidence'])
    workers = set((evidence / 'workers').glob('*'))
    refs = original_verification['watchdogs']
    if not workers or {Path(ref['path']).parent for ref in refs} != workers:
        raise ValueError('original verification omits full-run watchdog evidence')
    selected_worker = Path(report['worker_request']).parent
    selected_watch = None
    for ref in refs:
        worker = Path(ref['path']).parent
        if Path(ref['path']) != worker / 'watchdog.json' or sha256(ref['path']) != ref['sha256']:
            raise ValueError('original watchdog hash/path differs')
        watch = api['read_json'](ref['path'])
        request = api['read_json'](worker / 'request.json')
        if (request['selection_sha256'] != sha256(selection_path) or request['selection_path'] != str(selection_path) or
                watch['selection_sha256'] != request['selection_sha256'] or
                watch['argv'] != api['worker_argv'](selection_path, selection) or
                api['read_json'](worker / 'started.json') != {'pid': watch['pid']} or
                sha256(worker / 'stdout') != watch['stdout_sha256'] or sha256(worker / 'stderr') != watch['stderr_sha256']):
            raise ValueError('original native worker identity/streams differ')
        if (watch['drained'] is not True or watch['outcome'] != 'completed' or watch.get('cancelled_cli_groups') or
                not 0 <= watch['monotonic_elapsed'] < watch['monotonic_budget'] <= selection['limits']['wall_seconds'] or
                not api['utc'](selection['window']['started_utc']) <= api['utc'](watch['started_utc']) <=
                    api['utc'](watch['ended_utc']) <= api['utc'](selection['window']['deadline_utc'])):
            raise ValueError('original driver did not positively complete inside unchanged bounds')
        if worker == selected_worker:
            selected_watch = watch
            if (watch['returncode'] != api['LIMIT_EXIT'] or
                    not api['utc'](watch['started_utc']) <= api['utc'](report['ended_utc']) <= api['utc'](watch['ended_utc'])):
                raise ValueError('original driver exit/interval differs from immutable incomplete run')
            message = json.loads((worker / 'stdout').read_bytes())
            if message != {'status': report['status'], 'report': str(report_path), 'budget': report['budget']['totals']}:
                raise ValueError('original worker stdout differs from original incomplete report')
    if selected_watch is None:
        raise ValueError('original report has no exact worker watchdog')
    return refs, selected_watch['returncode']


def adjudicate(api, args, selection, settings, historical):
    """Read existing objects only; write one new supplemental analysis record."""
    from sec_edgar_ingest.storage import open_stores
    evidence = Path(selection['evidence'])
    report_path, verification_path, output = args.report.resolve(), args.original_verification.resolve(), args.output.resolve()
    if (report_path.parent != evidence or not report_path.name.startswith('run-') or
            verification_path.parent != evidence or not verification_path.name.startswith('verification-') or
            output.parent != evidence / 'adjudications' or not output.name.endswith('.json')):
        raise ValueError('original records and supplemental output must use their distinct evidence directories')
    immutable = [Path(args.selection), report_path, verification_path, DRIVER, Path(__file__).resolve(),
                 *(Path(record['path']) for record in historical['harness'].values())]
    before = {str(path): sha256(path) for path in immutable}
    report, original_verification = api['read_json'](report_path), api['read_json'](verification_path)
    if (report['format_version'] != 'sec-local-sec-acceptance-v1' or report['selection_sha256'] != sha256(args.selection) or
            report['release_id'] != selection['release_id'] or report['reason'] is not None or
            report['status'] != api['evaluate_l12'](report['proof']) or report['status']['status'] != 'incomplete' or
            report['proof']['bounded'] is not True):
        raise ValueError('original report is not the unchanged bounded incomplete run')
    if (original_verification['format_version'] != 'sec-local-sec-verification-v1' or
            original_verification['latest_report'] != str(report_path) or
            original_verification['status'] != report['status'] or original_verification['proof'] != report['proof'] or
            original_verification['commands'] != report['commands'] or original_verification['budget'] != report['budget'] or
            not any(item == {'path': str(report_path), 'sha256': sha256(report_path)} for item in original_verification['reports'])):
        raise ValueError('original incomplete verification does not bind exact original report')
    watchdogs, original_exit = verify_original_watchdogs(api, args.selection, selection, report_path, report, original_verification)
    opened = open_stores(settings['daily'], access='operator')
    try:
        commands, budget, derived = api['derive_evidence'](args.selection, selection, opened[0], opened[1])
    finally:
        api['close_stores'](opened)
    if commands != report['commands'] or budget != report['budget']:
        raise ValueError('independent command/transport/ledger evidence differs from original run snapshot')
    current = {item['execution_path']: item for item in commands}
    for ref in original_verification['reports']:
        if sha256(ref['path']) != ref['sha256']:
            raise ValueError('historical report hash differs')
        prior = api['read_json'](ref['path'])
        if prior['selection_sha256'] != sha256(args.selection) or prior['release_id'] != selection['release_id']:
            raise ValueError('historical report selection/release differs')
        if any(current.get(item['execution_path']) != item for item in prior['commands']):
            raise ValueError('historical report omits or changes actual launch evidence')
    delta = proof_delta(report['proof'], derived)
    status = api['evaluate_l12'](derived)
    if status['status'] != delta['corrected_status']:
        raise ValueError('supplemental status differs from unchanged L12 criteria')
    api['verify_runtime'](historical)
    if before != {str(path): sha256(path) for path in immutable}:
        raise ValueError('original inputs or corrected analyzer changed during offline adjudication')
    result = {'format_version': 'sec-local-sec-offline-adjudication-v1', 'method': METHOD,
        'selection': {'path': str(args.selection), 'sha256': sha256(args.selection)},
        'release_id': selection['release_id'], 'acquisition_repeated': False,
        'original': {'report': {'path': str(report_path), 'sha256': sha256(report_path)},
            'status': report['status'], 'driver_exit': original_exit,
            'verification': {'path': str(verification_path), 'sha256': sha256(verification_path), 'status': original_verification['status']},
            'harness': {role: {'selected_path': selection['harness'][role]['path'], 'archived_path': record['path'], 'sha256': record['sha256']}
                        for role, record in historical['harness'].items()}, 'watchdogs': watchdogs},
        'analyzer': {'path': str(Path(__file__).resolve()), 'sha256': sha256(__file__),
            'corrected_driver': {'path': str(DRIVER), 'sha256': sha256(DRIVER)}},
        'independent_status': status, 'proof_delta': delta, 'derived_proof': derived,
        'budget': budget, 'command_count': len(commands), 'adjudicated_utc': datetime.now(timezone.utc).isoformat()}
    api['write_once'](output, api['canonical'](result))
    print(api['canonical']({'original_status': report['status'], 'original_driver_exit': original_exit,
        'independent_status': status, 'supplement': str(output)}).decode())
    return 0 if status['status'] == 'pass' else api['LIMIT_EXIT']


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ('selection', 'report', 'original-verification', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    args.selection = args.selection.resolve()
    api = runpy.run_path(str(DRIVER))
    try:
        selection = api['require_prepared'](args.selection)
        native_bootstrap(selection)
        historical = historical_selection(selection)
        settings = api['verify_runtime'](historical)
        return adjudicate(api, args, selection, settings, historical)
    except Exception as error:
        print(api['canonical']({'status': 'incomplete', 'outcome': 'adjudication_refused', 'error': str(error)}).decode(), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
