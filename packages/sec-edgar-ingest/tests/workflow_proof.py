from network_guard import install
install()
from sec_edgar_ingest.models import to_mapping_value
import contextlib, hashlib, json, multiprocessing, os, shutil
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from support import fixture_settings
from support_workflows import BASE, CommandHarness as BaseCommandHarness, listing, idx, simple_pack
from support_process import CheckedRunner, checked_dispatcher
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage import open_stores
from sec_edgar_ingest.workflows.results import read_workflow_result


class CommandHarness(BaseCommandHarness):
    def invoke(self, *args, **kwargs):
        import sec_edgar_ingest.cli as cli
        with patch.object(cli, 'WorkflowDispatcher', side_effect=checked_dispatcher):
            return super().invoke(*args, **kwargs)

FIXTURE_ROOT = Path(__file__).resolve().parent / 'fixtures/workflows/proof'
BODY_FILES = ('full-root.json', 'full-year.json', 'full-q3.json', 'full-q4.json',
              'full-q3.zip', 'full-q4.zip', 'daily-root.json', 'daily-year.json',
              'daily-q3.json', 'daily-q4.json', 'daily-q4.idx')
EXPECTED = {'2026Q3': [{'cik': '0000123456', 'company_name': 'Example', 'form_type': '10-K',
    'filing_date': '2026-09-30', 'archive_path': 'edgar/data/123456/0000123456-26-000003.txt'}],
    '2026Q4': [{'cik': '0000123456', 'company_name': 'Example', 'form_type': '10-K',
    'filing_date': '2026-10-01', 'archive_path': 'edgar/data/123456/0000123456-26-000004.txt'}]}


def write_proof_fixtures(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    responses, values = {}, {}
    for family, tag in (('full-index', 'full'), ('daily-index', 'daily')):
        base = BASE + family + '/'
        values[tag + '-root.json'] = (base + 'index.json', listing(base + 'index.json', [('2026', 'dir')]))
        values[tag + '-year.json'] = (base + '2026/index.json', listing(base + '2026/index.json', [('QTR3', 'dir'), ('QTR4', 'dir')]))
        for quarter in (3, 4):
            leaf = base + f'2026/QTR{quarter}/'
            name = 'master.zip' if family == 'full-index' else 'master.20261001.idx'
            children = [] if family == 'daily-index' and quarter == 3 else [(name, 'file')]
            values[tag + f'-q{quarter}.json'] = (leaf + 'index.json', listing(leaf + 'index.json', children))
            if children:
                day = '2026-09-30' if quarter == 3 else '2026-10-01'
                if family == 'daily-index': day = day.replace('-', '')
                rows = [('123456', 'Example', '10-K', day, EXPECTED[f'2026Q{quarter}'][0]['archive_path'])]
                extension = '.zip' if family == 'full-index' else '.idx'
                values[tag + f'-q{quarter}' + extension] = (leaf + name, idx(rows, 'quarterly' if family == 'full-index' else 'daily'))
    if set(values) != set(BODY_FILES):
        raise AssertionError('fixed proof fixture inventory differs')
    for name in BODY_FILES:
        url, body = values[name]
        (destination / name).write_bytes(body)
        spec = {'status': 200, 'headers': {'Content-Length': str(len(body)), 'X-Fixture': 'synthetic'},
                'body_path': name, 'body_sha256': hashlib.sha256(body).hexdigest()}
        responses[url] = [dict(spec) for _ in range(16)]
    (destination / 'manifest.json').write_bytes(canonical_json(to_mapping_value({
        'fixture_version': 'sec-acquisition-fixture-v1', 'provenance': 'synthetic', 'responses': responses})))
    (destination / 'expected.json').write_bytes(canonical_json(to_mapping_value(EXPECTED)))


def harness_files(root=None) -> tuple[Path, ...]:
    root = Path(__file__).resolve().parent if root is None else Path(root)
    fixed = ('support_workflows.py', 'workflow_proof.py', 'network_guard.py',
             'support.py', 'support_etl.py', 'locked_proof.py', 'support_process.py',
             'checked_child_bootstrap.py', 'fixtures/config/local.json')
    values = tuple(root / name for name in fixed) + tuple(
        root / 'fixtures/workflows/proof' / name for name in ('manifest.json', 'expected.json', *BODY_FILES))
    if any(not path.is_file() for path in values):
        raise ValueError('a fixed test-only harness file is missing')
    return values


def put_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical_json(to_mapping_value(value)))


def assert_rows(harness, quarter, expected):
    capture, rows = harness.capture(quarter)
    names = ('cik', 'company_name', 'form_type', 'filing_date', 'archive_path')
    actual = sorted(({name: row[name] for name in names} for row in rows),
                    key=lambda row: (row['archive_path'], row['filing_date']))
    wanted = sorted(expected, key=lambda row: (row['archive_path'], row['filing_date']))
    if actual != wanted or len(rows) != len(expected):
        raise AssertionError({'quarter': quarter, 'actual': actual, 'expected': wanted})
    return {'capture': capture.to_mapping(), 'rows': rows, 'logical_rows': len(rows)}


def durable_report(harness, message):
    if not message.get('result_ref'):
        raise AssertionError('workflow command has no durable report')
    result = read_workflow_result(message['result_ref'], harness.store, harness.objects)
    if result.outcome != message['outcome'] or result.to_mapping()['counts'] != message['counts']:
        raise AssertionError('stdout differs from checked durable workflow report')
    return result


def sequence(output: Path, *, release_manifest=None) -> Mapping[str, object]:
    output = Path(output)
    if not output.is_dir() or any(output.iterdir()):
        raise ValueError('sequence requires an existing empty create-only output directory')
    expected = json.loads((FIXTURE_ROOT / 'expected.json').read_text())
    if expected != EXPECTED:
        raise AssertionError('checked fixture expected rows differ')
    fixture = output / 'fixture'
    shutil.copytree(FIXTURE_ROOT, fixture)
    work = output / 'work'
    work.mkdir()
    native_settings = None if release_manifest is None else fixture_settings(
        backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
        etl={'parser_version': 'fixture-index-parser-v1'},
        fixture={'allow_clock_override': True, 'allow_deadline_override': False})
    if native_settings is not None:
        from sec_edgar_ingest.config import Settings
        value = native_settings.to_mapping()
        value['runtime'] = {'kind': 'native', 'release_manifest': str(release_manifest)}
        native_settings = Settings.from_mapping(value)
    h = CommandHarness(work, fixture / 'manifest.json', native_settings)
    settings = h.settings
    guards = {'parser_version': settings.etl.parser_version, 'schema_version': settings.etl.schema_version,
              'exchange_deadline_seconds': settings.http.exchange_deadline_seconds,
              'max_received_bytes': settings.http.max_received_bytes,
              'max_expanded_bytes': settings.http.max_expanded_bytes}
    expected_guards = {'parser_version': 'fixture-index-parser-v1', 'schema_version': 'sec-index-v1',
                       'exchange_deadline_seconds': 90, 'max_received_bytes': 67108864,
                       'max_expanded_bytes': 536870912}
    if guards != expected_guards:
        h.close()
        raise AssertionError('proof configuration guards differ')
    put_json(output / 'checked-config.json', guards)
    reports, readers = {}, {}
    try:
        for command, run in (('backfill', 'proof-baseline'), ('daily', 'proof-overlap'),
                             ('backfill', 'proof-repeat')):
            code, message = h.invoke(command, run=run)
            if code != 0: raise AssertionError(h.calls[-1])
            result = durable_report(h, message)
            if result.counts['quarantined_sources'] != 0 or result.counts['pending_sources'] or result.counts['failed_sources']:
                raise AssertionError(result.to_mapping())
            if run == 'proof-baseline' and (result.requested_quarters != ('2026Q3', '2026Q4') or result.counts['complete_sources'] != 2):
                raise AssertionError('inclusive baseline source accounting differs')
            if run == 'proof-overlap' and result.counts['complete_sources'] != 1:
                raise AssertionError('daily overlap source accounting differs')
            if run == 'proof-repeat' and (result.outcome != 'unchanged' or result.counts['complete_sources'] != 2):
                raise AssertionError('fresh unchanged repeat differs')
            reports[run] = result.to_mapping()
            readers[run] = {quarter: assert_rows(h, quarter, expected[quarter]) for quarter in expected}
        original = h.calls[0]
        before = h.objects.read(original['stdout']['result_ref'])
        cursors = tuple(row.to_mapping() for row in h.store.scan('FixtureResponseCursor', {}))
        code, replay = h.invoke('backfill', run='proof-baseline')
        if code != 0 or replay != original['stdout'] or h.objects.read(replay['result_ref']) != before:
            raise AssertionError('exact command replay changed report authority')
        if tuple(row.to_mapping() for row in h.store.scan('FixtureResponseCursor', {})) != cursors:
            raise AssertionError('exact completed replay consumed a fixture response')
        put_json(output / 'commands.json', h.calls)
    finally:
        h.close()
    legacy = output / 'legacy'
    legacy.mkdir()
    old = CommandHarness(legacy, fixture / 'manifest.json', native_settings)
    try:
        code, found = old.invoke('discover', ('--mode', 'daily', '--discovery-id', 'old-child-only'), run='legacy-discover')
        if code != 0: raise AssertionError(old.calls[-1])
        code, collected = old.invoke('collect', ('--workset', found['source_workset_ref']), run='legacy-collect')
        if code != 0 or tuple(old.store.scan('WorkflowMember', {})):
            raise AssertionError('legacy setup must consist only of shipped child commands')
        code, message = old.invoke('daily', run='legacy-workflow')
        if code != 0: raise AssertionError(old.calls[-1])
        result = durable_report(old, message)
        if result.counts['complete_sources'] != 1 or result.counts['quarantined_sources']:
            raise AssertionError('legacy backlog source accounting differs')
        reports['legacy-workflow'] = result.to_mapping()
        readers['legacy-workflow'] = {'2026Q4': assert_rows(old, '2026Q4', expected['2026Q4'])}
        put_json(output / 'legacy-commands.json', old.calls)
    finally:
        old.close()
    put_json(output / 'checked-reports.json', reports)
    put_json(output / 'reader-captures.json', readers)
    return {'exit': 0, 'reports': reports, 'reader_captures': readers,
            'all22_stage7_checks': 'reserved/not_run'}

def process_worker(config, pack, state_dir, argv, point, marker):
    import sec_edgar_ingest.cli as cli
    from sec_edgar_ingest.workflows.checked import Dispatcher
    from sec_edgar_ingest.workflows.runner import run_workflow as actual_runner
    from sec_edgar_ingest.workflows.results import write_workflow_result as actual_report
    import sec_edgar_ingest.workflows.results as workflow_results
    actual_index = workflow_results._index
    from sec_edgar_ingest.etl.commands import run_publish as actual_publish, write_etl_result as actual_etl_result
    def boundary(name):
        if name != point: return
        with Path(marker).open('xb') as stream:
            stream.write(canonical_json(to_mapping_value({'point': name, 'pid': os.getpid()})))
            stream.flush()
            os.fsync(stream.fileno())
        acknowledgment = Path(marker).with_suffix('.ack')
        until = time.monotonic() + 15
        while not acknowledgment.is_file():
            if time.monotonic() >= until:
                raise AssertionError('named workflow boundary acknowledgment timed out')
            time.sleep(0.01)
        os._exit(91)
    def dispatch(*args, **kwargs):
        kwargs['observer'] = boundary
        stage_points = {'collection.after_binding', 'publication.after_pointer',
                        'publication.after_repair', 'etl_result.after_object'}
        fault = {'point': point, 'action': 'crash', 'marker': str(marker),
                 'ack': str(Path(marker).with_suffix('.ack'))} if point in stage_points else None
        kwargs['child_runner'] = CheckedRunner(fault=fault, die_with_child=True)
        return Dispatcher(*args, **kwargs)
    def runner(*args, **kwargs):
        kwargs['observer'] = boundary
        return actual_runner(*args, **kwargs)
    def report(*args, **kwargs):
        kwargs['observer'] = boundary
        return actual_report(*args, **kwargs)
    def publish(*args, **kwargs):
        kwargs['observer'] = boundary
        return actual_publish(*args, **kwargs)
    def etl_result(*args, **kwargs):
        kwargs['observer'] = boundary
        return actual_etl_result(*args, **kwargs)
    def begun_index(*args, **kwargs):
        result = actual_index(*args, **kwargs)
        boundary('workflow.after_attempt_begin')
        return result
    with patch.object(cli, 'WorkflowDispatcher', side_effect=dispatch), \
         patch.object(cli, 'run_workflow', side_effect=runner), \
         patch.object(cli, 'write_workflow_result', side_effect=report), \
         patch.object(cli, 'run_publish', side_effect=publish), \
         patch.object(cli, 'write_etl_result', side_effect=etl_result), \
         patch.object(workflow_results, '_index', side_effect=begun_index), \
         patch.object(cli._NoFaults, 'hit', lambda self, name: boundary('collection.' + name)):
        with Path(marker).with_suffix('.stdout').open('x', buffering=1) as stdout, \
             Path(marker).with_suffix('.stderr').open('x', buffering=1) as stderr, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
    put_json(Path(marker).with_suffix('.unexpected.json'), {'exit': code, 'point': point})
    raise SystemExit(92)


PROCESS_POINTS = ('workflow.after_attempt_begin', 'workflow_child.after_call', 'collection.after_binding',
    'workflow_child.after_result', 'workflow.after_selection',
    'publication.after_pointer', 'publication.after_repair', 'etl_result.after_object',
    'workflow.after_member_processing', 'workflow.after_member_receipt',
    'workflow.after_report_object', 'workflow.after_attempt_finish')


def process_case(output, point):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    pack = simple_pack(output / 'pack')
    settings = fixture_settings(backfill={'start_quarter': '2026Q4', 'end_quarter': 'open'},
        etl={'parser_version': 'fixture-index-parser-v1'},
        fixture={'allow_clock_override': True, 'allow_deadline_override': False})
    h = CommandHarness(output, pack, settings)
    settings = h.settings
    argv = ['backfill', '--config', str(h.config), '--run-id', 'process', '--execution-id', 'manual',
            '--attempt-id', 'a', '--deadline', h.deadline.isoformat(),
            '--fixture-pack', str(pack), '--today', '2026-10-07']
    h.close()
    marker = output / 'death.json'
    put_json(output / 'worker-command.json', {'argv': argv, 'point': point})
    child = multiprocessing.get_context('spawn').Process(target=process_worker,
        args=(h.config, pack, output, argv, point, marker))
    child.start()
    until = time.monotonic() + 30
    while not marker.is_file() and child.is_alive() and time.monotonic() < until:
        time.sleep(0.01)
    if marker.is_file():
        marker.with_suffix('.ack').touch(exist_ok=True)
    child.join(30)
    if child.is_alive():
        child.terminate(); child.join(5)
        raise AssertionError('worker did not reach durable boundary ' + point)
    if child.exitcode != 91 or not marker.is_file() or json.loads(marker.read_text())['point'] != point:
        raise AssertionError({'point': point, 'exit': child.exitcode})
    put_json(output / 'worker-exit.json', {'exit': child.exitcode, 'point': point})
    opened = open_stores(settings)
    store, objects, leases = opened
    try:
        before = [row.to_mapping() for row in store.scan('QuarterPublication', {})]
        result_ref = 'runs/sec/process/backfill/a/result.json'
        try: saved_body = objects.read(result_ref)
        except FileNotFoundError: saved_body = None
        if point == 'workflow.after_attempt_begin':
            begun = tuple(store.scan('WorkflowAttempt', {}))
            if len(begun) != 1 or begun[0].value['result_ref'] is not None:
                raise AssertionError('durable workflow start was not retained before intent write')
            try: objects.read('runs/sec/process/backfill/a/intent.json')
            except FileNotFoundError: pass
            else: raise AssertionError('before-intent interruption unexpectedly has intent bytes')
        if point in ('workflow.after_report_object', 'workflow.after_attempt_finish') and saved_body is None:
            raise AssertionError('report boundary has no immutable report')
        if point == 'publication.after_pointer':
            if len(before) != 1 or saved_body is not None:
                raise AssertionError('post-CAS setup lacks unfinished publication')
            publish_attempts = [row.to_mapping()['value'] for row in store.scan('Attempt', {})
                                if row.value['context']['command'] == 'publish']
            if len(publish_attempts) != 1 or publish_attempts[0]['result'] is not None:
                raise AssertionError('process death must retain begun publish without a result')
    finally:
        for resource in reversed(opened):
            if hasattr(resource, 'close'): resource.close()
    h = CommandHarness(output, pack, settings)
    h.deadline = datetime.fromisoformat(argv[argv.index('--deadline') + 1])
    try:
        code, message = h.invoke('backfill', run='process', attempt='a')
        exact_retry_exit = code
        ambiguous = point in {'collection.after_binding', 'publication.after_pointer',
                              'publication.after_repair', 'etl_result.after_object'}
        if ambiguous:
            if code == 0:
                raise AssertionError('ambiguous exact retry claimed success')
            code, message = h.invoke('backfill', run='process', attempt='continuation')
        if code != 0: raise AssertionError(h.calls[-1])
        result = durable_report(h, message)
        capture, rows = h.capture('2026Q4')
        if result.counts['complete_sources'] != 1 or result.counts['pending_sources'] or len(rows) != 1:
            raise AssertionError(result.to_mapping())
        after = [row.to_mapping() for row in h.store.scan('QuarterPublication', {})]
        if before and after != before:
            raise AssertionError('recovery advanced an already committed pointer')
        if saved_body is not None and h.objects.read(result_ref) != saved_body:
            raise AssertionError('completed historical report was rewritten during recovery')
        put_json(output / 'reopened.json', {'calls': h.calls, 'report': result.to_mapping(),
            'reader': capture.to_mapping(), 'rows': rows, 'pointers_before': before, 'pointers_after': after})
        return {'point': point, 'exit': 0, 'exact_retry_exit': exact_retry_exit,
                'worker_exit': child.exitcode, 'report': message['result_ref'],
                'acknowledged': marker.with_suffix('.ack').is_file()}
    finally:
        h.close()


def native(output: Path) -> Mapping[str, object]:
    output = Path(output)
    if not output.is_dir() or any(output.iterdir()):
        raise ValueError('native requires an existing empty create-only output directory')
    sequence_output = output / 'sequence'
    sequence_output.mkdir(exist_ok=False)
    result = sequence(sequence_output)
    recovered = [process_case(output / ('process-' + point.replace('.', '-')), point) for point in PROCESS_POINTS]
    put_json(output / 'process-recovery.json', recovered)
    return {'exit': 0, 'sequence': result, 'process_recovery': recovered,
            'all22_stage7_checks': 'reserved/not_run'}


import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
import tomllib
from pathlib import Path

from locked_proof import digest, inventory, requirement_blocks, verify_inventory, package_inventory


def _json_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')


def _logged(argv, cwd, output, label, environment, *, timeout=300):
    started = time.monotonic()
    record = {'argv': [str(value) for value in argv], 'cwd': str(cwd),
        'timeout_seconds': timeout, 'pythonpath_present': 'PYTHONPATH' in environment,
        'uv_python_downloads': environment.get('UV_PYTHON_DOWNLOADS')}
    try:
        completed = subprocess.run(argv, cwd=cwd, env=environment, capture_output=True,
                                   text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        record.update(exit=None, outcome='timeout', runtime_seconds=time.monotonic() - started)
        for name, value in (('stdout', error.stdout), ('stderr', error.stderr)):
            if isinstance(value, bytes):
                raw = output / (label + '.' + name + '.bin')
                with raw.open('xb') as stream:
                    stream.write(value)
                record[name + '_raw'] = {'path': raw.name, **digest(raw)}
                record[name] = value.decode('utf-8', errors='backslashreplace')
            else:
                record[name] = value or ''
        _json_once(output / (label + '.json'), record)
        raise
    record.update(exit=completed.returncode, outcome='completed', stdout=completed.stdout,
        stderr=completed.stderr, runtime_seconds=time.monotonic() - started)
    _json_once(output / (label + '.json'), record)
    if completed.returncode:
        raise RuntimeError('offline installed command failed: ' + label)
    return record


def _isolated_script(python, harness, script_name, *arguments):
    script = str(harness / script_name)
    bootstrap = ('import runpy,sys; sys.path.insert(0,' + repr(str(harness)) + '); '
                 'sys.argv=[' + repr(script) + ',*sys.argv[1:]]; '
                 'runpy.run_path(' + repr(script) + ',run_name="__main__")')
    return [str(python), '-I', '-c', bootstrap, *map(str, arguments)]


def installed(output):
    """Use current committed proof releases and the shared native verifier."""
    from support_release import proof_releases
    from locked_proof import proof_harness, verify_wrong_transitive
    from sec_edgar_ingest.runtime import native_python_argv, isolated_environment
    project = Path(__file__).resolve().parents[3]
    a, b = proof_releases(project, project / 'releases/artifact-cache')
    harness = proof_harness(Path(__file__).parent)
    reports = []
    for release in (a, b):
        evidence = output / release.release_id
        with tempfile.TemporaryDirectory(prefix='sec-proof-entry-') as directory:
            outside = Path(directory)
            entry = outside / 'verify-native-release.py'
            shutil.copy2(project / 'scripts/verify-native-release.py', entry)
            copied = outside / 'harness'
            for source in harness_files(harness):
                target = copied / source.relative_to(harness)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            argv = [*native_python_argv(release.python), str(entry),
                    '--release', str(release.directory), '--harness', str(copied), '--evidence', str(evidence)]
            done = subprocess.run(argv, cwd=directory, env=isolated_environment(),
                                  capture_output=True, text=True, timeout=660)
        if done.returncode:
            raise RuntimeError('standalone native verifier failed: ' + done.stderr)
        reports.append(json.loads((evidence / 'report.json').read_text()))
    return {'exit': 0, 'releases': reports,
        'wrong_transitive': verify_wrong_transitive(a, harness,
                                                   output / 'wrong-transitive')}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline workflow process and installed proof')
    parser.add_argument('mode', choices=('native', 'installed'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.output.is_absolute():
        parser.error('output must be an explicit absolute path')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {'mode': args.mode, 'exit': 0, 'all22_stage7_checks': 'reserved/not_run'}
    try:
        report.update(installed(output)
                      if args.mode == 'installed' else native(output))
    except BaseException:
        report.update(exit=1, traceback=traceback.format_exc())
    report['runtime_seconds'] = time.monotonic() - started
    _json_once(output / 'report.json', report)
    _json_once(output / 'sha256.json', inventory(output))
    verify_inventory(output)
    print(json.dumps({'exit': report['exit'], 'report': str(output / 'report.json'),
                      'all22_stage7_checks': 'reserved/not_run'}))
    return report['exit']


if __name__ == '__main__':
    raise SystemExit(main())


def upgrade_sequence(output, a_manifest, b_manifest):
    """Run upgrade assertions inside installed B, with copied test support only."""
    import tempfile
    from sec_edgar_ingest.release import reconstruct_release
    from sec_edgar_ingest.runtime import preflight, native_python_argv, isolated_environment
    output = Path(output).absolute()
    with tempfile.TemporaryDirectory(prefix='sec-upgrade-harness-') as directory:
        outside = Path(directory)
        # Missing-runtime probes rename A. Reconstruct both venvs at disposable
        # final addresses so catalog artifacts stay available to other proofs.
        a_manifest, b_manifest = (reconstruct_release(Path(manifest), outside / 'releases',
            python=Path(sys.executable)) / 'release.json' for manifest in (a_manifest, b_manifest))
        a, b = preflight(a_manifest), preflight(b_manifest)
        harness = outside / 'harness'
        harness.mkdir()
        from locked_proof import proof_harness
        source_root = proof_harness(Path(__file__).absolute().parent)
        for source in harness_files(source_root):
            target = harness / source.relative_to(source_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        from network_guard import write_checkout_policy
        write_checkout_policy(harness, {'version': 'sec-checkout-policy-v1',
                                       'releases': sorted([str(a.directory), str(b.directory)])})
        code = ('import sys,json;sys.path.insert(0,' + repr(str(harness)) + ');'
                'from network_guard import install;install();'
                'from workflow_proof import installed_upgrade_cases;'
                'print(json.dumps(installed_upgrade_cases(*sys.argv[1:]),sort_keys=True))')
        argv = [*native_python_argv(b.python), '-c', code, str(output), str(a_manifest), str(b_manifest)]
        done = subprocess.run(argv, cwd=outside, env=isolated_environment(),
                              capture_output=True, text=True, timeout=600)
        (output / 'upgrade-command.json').write_text(json.dumps({'argv': argv, 'exit': done.returncode,
            'stdout': done.stdout, 'stderr': done.stderr, 'cwd': str(outside)}, indent=2) + '\n')
        if done.returncode:
            raise RuntimeError('installed B upgrade proof failed: ' + done.stderr)
        return json.loads(done.stdout)


def order_aware_children(scenario, objects, result, checked, a_release_id, b_release_id):
    """Check each source's children in its frozen continue-b order; return {source_id: A-origin first}.

    A-origin first: that member collects under installed A, and the later B member gets the B4
    no-child receipt. B first: the B member collects under installed B, no A collect runs for the
    source, and the A-origin member gets the B4 no-child receipt (the D5 path).
    """
    from sec_edgar_ingest.workflows.contracts import COMPLETE
    selection = json.loads(objects.read('runs/sec/continue-b/backfill/a/selection.json'))
    jobs = {}
    for job in selection['jobs']:
        value = job['member']
        origin = json.loads(objects.read(value['member_ref']))['context']['run_id']
        jobs.setdefault(value['source']['source_id'], []).append((value, origin))
    receipts = {member.member_id: member for member in result.members}
    collects = [item['call'] for item in checked if item['call']['context']['command'] == 'collect']
    def collected(ref, release_id):
        return any(call['input_ref'] == ref and call['context']['runtime']['release_sha256'] == release_id
                   for call in collects)
    a_first = {}
    for source_id, ordered in jobs.items():
        if not any(origin == 'origin-a' for _, origin in ordered):
            continue
        (first, first_origin), later = ordered[0], ordered[1:]
        a_first[source_id] = first_origin == 'origin-a'
        if not collected(first['member_ref'], a_release_id if a_first[source_id] else b_release_id):
            raise AssertionError({'error': 'first member of a source did not collect under its origin release',
                                  'scenario': scenario, 'source_id': source_id, 'a_first': a_first[source_id]})
        for value, origin in later:
            if any(call['input_ref'] == value['member_ref'] for call in collects):
                raise AssertionError({'error': 'a later same-source member ran collect', 'scenario': scenario})
            receipt = receipts[value['member_id']]
            if (receipt.outcome not in COMPLETE or tuple(receipt.child_refs)
                    or receipt.snapshot_ref is not None or receipt.transformed_ref is not None):
                raise AssertionError({'error': 'later same-source member lacks the B4 no-child receipt',
                                      'scenario': scenario, 'member_id': value['member_id'], 'origin': origin})
    if not a_first:
        raise AssertionError({'error': 'continue-b selected no A-origin member', 'scenario': scenario})
    return a_first


def installed_upgrade_cases(output, a_manifest, b_manifest):
    """Actual B application checks A-origin backlog/repair and retained read authority."""
    import sys
    from datetime import date, timedelta, timezone
    from sec_edgar_ingest.config import Settings
    from sec_edgar_ingest.runtime import preflight, preflight_current, native_python_argv, isolated_environment
    from sec_edgar_ingest.workflows.checked import read_child_capture
    from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter
    from sec_edgar_ingest.etl.state import EtlState
    import sec_edgar_ingest
    output = Path(output)
    a, b = preflight(Path(a_manifest)), preflight_current(Path(b_manifest))
    cases = []
    for scenario in ('pending', 'repair'):
        root = output / scenario
        root.mkdir()
        pack = simple_pack(root / 'pack')
        if scenario == 'repair':
            from support_workflows import replace_pack_body
            original_rows = [('123456', 'Example', '10-K', '2026-09-30',
                'edgar/data/123456/0000123456-26-000003.txt'),
                ('123456', 'Second', '10-K', '2026-09-30',
                 'edgar/data/123456/0000123456-26-000099.txt')]
            replace_pack_body(pack, BASE + 'full-index/2026/QTR3/master.zip', idx(original_rows, 'quarterly'))
        if scenario == 'pending':
            value = json.loads(pack.read_text())
            url = BASE + 'full-index/2026/QTR3/master.zip'
            body = b'pending retained source'
            digest = hashlib.sha256(body).hexdigest()
            (pack.parent / 'bodies' / (digest + '.body')).write_bytes(body)
            value['responses'][url].insert(0, {'status': 404, 'headers': {},
                'body_path': 'bodies/' + digest + '.body', 'body_sha256': digest})
            pack.write_bytes(canonical_json(to_mapping_value(value)))
        base = fixture_settings(root=root / 'data',
            backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
            etl={'parser_version': 'fixture-index-parser-v1'},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        def settings(release):
            value = base.to_mapping()
            value['runtime'] = {'kind': 'native', 'release_manifest': str(release.directory / 'release.json')}
            return Settings.from_mapping(value)
        selected_a, selected_b = settings(a), settings(b)
        deadline = datetime.now(timezone.utc) + timedelta(seconds=1800)
        log = root / 'pids.jsonl'
        sentinel = root / 'sentinel.py'
        write_sentinel = __import__('support_process').write_import_sentinel
        write_sentinel(sentinel, root / 'sentinel.jsonl')
        def invoke(release, selected, run, fault=None, command='backfill', flags=()):
            config = root / (run + '-config.json')
            config.write_bytes(canonical_json(to_mapping_value(selected.to_mapping())))
            argv = [*native_python_argv(release.python), '-m', 'sec_edgar_ingest', command,
                '--config', str(config), *flags]
            if command == 'backfill':
                argv += ['--run-id', run, '--execution-id', 'manual', '--attempt-id', 'a',
                    '--deadline', deadline.isoformat(), '--fixture-pack', str(pack), '--today', '2026-10-07']
            result = CheckedRunner(fault=fault, pid_log=log, sentinel=sentinel)(release.python, argv,
                deadline=deadline, environ=isolated_environment())
            if not result.drained:
                raise AssertionError('upgrade command did not positively drain')
            return result.returncode, json.loads(result.stdout), result.stderr.decode()
        fault = None
        if scenario == 'repair':
            marker = root / 'fault.json'
            fault = {'point': 'publication.record_failure', 'action': 'raise',
                'marker': str(marker), 'ack': str(marker.with_suffix('.ack'))}
        a_exit, first, a_stderr = invoke(a, selected_a, 'origin-a', fault)
        if a_exit != (3 if scenario == 'pending' else 9):
            raise AssertionError({'scenario': scenario, 'a_exit': a_exit, 'message': first, 'stderr': a_stderr})
        records_before = len(log.read_text().splitlines())
        opened = open_stores(selected_b)
        store, objects, leases = opened
        try:
            original_results = {str(path.relative_to(objects.directory)): path.read_bytes()
                for path in (objects.directory / 'runs').rglob('result.json')}
            original_pointers = tuple(row.to_mapping() for row in store.scan('QuarterPublication', {}))
        finally:
            for resource in reversed(opened):
                if hasattr(resource, 'close'): resource.close()
        b_exit, message, b_stderr = invoke(b, selected_b, 'continue-b')
        if b_exit:
            raise AssertionError({'scenario': scenario, 'b_exit': b_exit, 'message': message, 'stderr': b_stderr})
        records = [json.loads(line) for line in log.read_text().splitlines()]
        continued = records[records_before:]
        if not continued or continued[0]['python'] != str(b.python):
            raise AssertionError('B workflow parent must execute installed B')
        a_children = [record for record in continued[1:] if record['python'] == str(a.python)]
        if not all('site-packages' in Path(record['origin']).parts for record in continued):
            raise AssertionError('B workflow children must import installed releases')
        if scenario == 'repair' and not any(record['argv'][0] == 'publish' for record in a_children):
            raise AssertionError('saved A publication was not repaired by installed A')
        opened = open_stores(selected_b, access='operator')
        store, objects, _ = opened
        try:
            result = read_workflow_result(message['result_ref'], store, objects)
            calls = [row.to_mapping()['value'] for row in store.scan('WorkflowChildCall', {})]
            checked = []
            for call in calls:
                if call['context']['run_id'] == 'continue-b':
                    child = read_child_capture(call, objects)
                    checked.append({'call': call, 'result': child.to_mapping()})
            # Member order (plan Decisions R2, fallback). select_work orders a source's members by
            # member_id, a hash over a workset whose context holds the discover child's wall-clock
            # started_at (cli.py: Clock().now() in the child process). The same hash also covers the
            # per-build runtime release_sha256 and the per-run config_sha256, so fixing started_at would
            # still leave one hash comparison to tune by hand: the order of an A-origin member and its B
            # sibling is not pinned. The first member of a source runs the child sequence; B4 completes
            # the later one with no child. Each branch is checked for what must hold in it.
            a_first = order_aware_children(scenario, objects, result, checked, a.release_id, b.release_id)
            a_child_expected = scenario == 'repair' or any(a_first.values())
            if bool(a_children) != a_child_expected:
                raise AssertionError({'error': 'B workflow did not use installed A origin/repair children',
                                      'a_first': a_first, 'a_children': len(a_children)})
            capture = capture_quarter('2026Q3', objects, EtlState(store))
            rows = list(read_quarter(capture, objects))
            if not rows or len({(row.cik, row.archive_path) for row in rows}) != len(rows):
                raise AssertionError('upgrade rows changed canonical uniqueness/count')
            for path, body in original_results.items():
                if objects.read(path) != body:
                    raise AssertionError('upgrade rewrote historical result authority')
            from sec_edgar_ingest.etl.history import quarter_history
            history_result = quarter_history('2026Q3', objects, EtlState(store))
            manifest_body = objects.read(capture.manifest_ref)
            from sec_edgar_ingest.etl.manifest import read_manifest
            manifest = read_manifest(capture, objects)
            observation = manifest.sources[0]
            before_observation = objects.read(observation.manifest_ref)
            current = capture_quarter('2026Q3', objects, EtlState(store))
            current_rows = list(read_quarter(current, objects))
            if len(current_rows) != len(rows) or objects.read(observation.manifest_ref) != before_observation:
                raise AssertionError('cached upgrade changed source bytes or current reader count')
            moved = a.directory.with_name(a.directory.name + '-missing')
            a.directory.rename(moved)
            try:
                if quarter_history('2026Q3', objects, EtlState(store)) != history_result:
                    raise AssertionError('historical read depends on the unavailable A interpreter')
                if list(read_quarter(capture, objects)) != rows:
                    raise AssertionError('historical capture changed with unavailable A interpreter')
                from sec_edgar_ingest.workflows.checked import Dispatcher
                before_calls = tuple(row.to_mapping() for row in store.scan('WorkflowChildCall', {}))
                dispatcher = Dispatcher(result.context, selected_b, pack, root, store, objects,
                                        child_runner=CheckedRunner())
                # When every A-origin member sorted after its B sibling, continue-b ran no A collect.
                # The probe then uses the A collect that origin-a ran for that same A-origin member.
                a_collects = [call for run_id in ('continue-b', 'origin-a') for call in calls
                              if call['context']['run_id'] == run_id and call['context']['command'] == 'collect'
                              and call['context']['runtime']['release_sha256'] == a.release_id]
                try:
                    dispatcher.execute('collect', 'missing-a-execution', selected_a,
                        ('--workset', a_collects[0]['input_ref']))
                except FileNotFoundError:
                    pass
                else:
                    raise AssertionError('missing A executable did not refuse execution')
                if tuple(row.to_mapping() for row in store.scan('WorkflowChildCall', {})) != before_calls:
                    raise AssertionError('missing old executable mutated child call authority')
            finally:
                moved.rename(a.directory)
            if scenario == 'repair':
                if json.loads(before_observation)['runtime']['release_sha256'] != a.release_id:
                    raise AssertionError('B cached transform must retain the original A producer')
                saved_manifest = objects.directory / f'runtime/native/sha256={a.release_id}/release.json'
                saved_body = saved_manifest.read_bytes()
                try:
                    saved_manifest.write_bytes(b'corrupt retained manifest')
                    try:
                        next(read_quarter(capture, objects))
                    except (ValueError, OSError):
                        pass
                    else:
                        raise AssertionError('corrupt saved A manifest exposed a historical row')
                    saved_manifest.unlink()
                    try:
                        next(read_quarter(capture, objects))
                    except (ValueError, OSError):
                        pass
                    else:
                        raise AssertionError('missing saved A manifest exposed a historical row')
                finally:
                    saved_manifest.write_bytes(saved_body)
            if objects.read(capture.manifest_ref) != manifest_body:
                raise AssertionError('historical reads rewrote generation manifest')
            operator_evidence = None
            if scenario == 'repair':
                from dataclasses import replace
                from support_etl import seed_observation
                from sec_edgar_ingest.etl.publication import publish_quarter
                from sec_edgar_ingest.etl.approval import approve
                from sec_edgar_ingest.etl.rollback import rollback
                state = EtlState(store)
                from sec_edgar_ingest.etl.transform import transform_member
                for force in (False, True):
                    reused = transform_member(observation.source, observation.snapshot,
                        result.context, selected_b, objects, state, force=force)
                    if reused != observation or objects.read(observation.manifest_ref) != before_observation:
                        raise AssertionError('B cached/forced reuse changed original A producer bytes')
                publishing = replace(result.context, command='publish', run_id='operator-b', attempt_id='withdraw')
                revised = seed_observation(objects, state, publishing, selected_b, period='2026Q3',
                    rows=b'123456|Example|10-K|2026-09-30|edgar/data/123456/0000123456-26-000003.txt\n',
                    seconds=(observation.snapshot.received_at - datetime(2026, 10, 6, tzinfo=timezone.utc)).total_seconds() + 10)
                candidate_result = publish_quarter('2026Q3', (revised,), publishing, selected_b, objects, state)
                if candidate_result.outcome != 'awaiting_approval':
                    raise AssertionError('closed A generation withdrawal did not preserve approval gate')
                from sec_edgar_ingest.etl.contracts import Candidate
                candidate_id = candidate_result.candidate_ref.split('sha256=')[1].split('/')[0]
                candidate = Candidate.from_mapping(store.get('Candidate', candidate_id).to_mapping()['value'])
                approval = approve('2026Q3', candidate_id, revised.snapshot.sha256, 'Local B approver', objects, state)
                if approval.outcome != 'success':
                    raise AssertionError('installed B could not approve exact candidate over A history')
                changed = capture_quarter('2026Q3', objects, state)
                if len(list(read_quarter(changed, objects))) != 1:
                    raise AssertionError('approved B capture count differs')
                rolled = rollback('2026Q3', changed.generation_id, capture.generation_id,
                    'Local B operator', 'restore original A generation', objects, state)
                if rolled.outcome != 'success' or list(read_quarter(capture_quarter('2026Q3', objects, state), objects)) != rows:
                    raise AssertionError('installed B could not roll back to original A capture')
                operator_evidence = {'approval': approval.to_mapping(), 'rollback': rolled.to_mapping(),
                    'approved_rows': 1, 'restored_rows': len(rows)}


            cases.append({'scenario': scenario, 'a_exit': a_exit, 'b_exit': b_exit,
                'a_child_under_b_parent': bool(a_children), 'a_child_expected': a_child_expected,
                'a_first': a_first, 'release_directories': sorted([str(a.directory), str(b.directory)]),
                'rows': len(rows), 'reader': capture.to_mapping(),
                'parent': continued[0], 'children': continued[1:], 'calls': checked,
                'workflow': result.to_mapping(), 'original_pointers': original_pointers,
                'history': history_result, 'missing_a_history': True, 'missing_a_execution_refused': True,
                'observation': observation.to_mapping(), 'observation_bytes_unchanged': True,
                'operator': operator_evidence})
        finally:
            store.close()
    report = {'exit': 0, 'pid': os.getpid(), 'python': sys.executable,
        'import_origin': sec_edgar_ingest.__file__, 'a_release_id': a.release_id,
        'b_release_id': b.release_id, 'cases': cases}
    put_json(output / 'upgrade-evidence.json', report)
    return report
