"""Offline drain and per-member cost measurement (Stage 1a bounded-drain spec §6; Stage 1b spec §6).

Run with the installed release interpreter and -I -B -X pycache_prefix=/dev/null.
`count` opens the live store with operator access only, and counts the rows of retained bodies.
`run` builds fixture packs and fresh stores under --work, and drives the release's own workflow engine
in this process with native child processes. Fixture acquisition sends no request.

`scenario` runs one Stage 1b scenario in this process and always writes its report.
`summarize` combines the reports and applies the C8 floor and reserve rules.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

FORMAT = 'sec-d5-drain-measurement-v1'
BASE = 'https://www.sec.gov/Archives/edgar/'
TODAY = date(2026, 12, 31)
MAX_RUN_SECONDS = 21600
OPEN_MARKS = (1, 10, 40, 80)
FINISH_LABELS = ('baseline_gaps', 'source_revert_gaps', 'summarize', 'write_workflow_result', 'emit_summary')
# closed_quarters: the 14 closed quarters that the retained 2026-10-15 daily file back-dates into (findings §4.7).
SCALES = {
    'smoke': {'open_days': 3, 'finish_start': '2026Q1', 'finish_rows': 20, 'closed_start': '2025Q1',
              'closed_quarters': ('2025Q1', '2025Q2'), 'authority_days': 2},
    'full': {'open_days': 81, 'finish_start': '2015Q1', 'finish_rows': 50, 'closed_start': '2021Q1',
             'closed_quarters': ('2021Q1', '2021Q2', '2021Q3', '2021Q4', '2022Q1', '2022Q2', '2023Q3',
                                 '2024Q4', '2025Q1', '2025Q2', '2025Q3', '2025Q4', '2026Q1', '2026Q3'),
             'authority_days': 10},
}
TIMINGS: list[dict] = []
MEMBERS: list[dict] = []
COST_FORMAT = 'sec-1b-cost-measurement-v1'
COST_SCENARIOS = ('open', 'closed', 'authority', 'finish')
COST_MAX_RUN_SECONDS = 43200  # The closed baseline's 14 first publications can exceed 6 hours under load (plan 5, P7).
LAUNCHER_DEFAULT_SECONDS = 3300
FLOOR_MINIMUM_SECONDS = 480
RESERVE_FACTOR = 1.25
HISTORY_MARKS = (400, 1200)
WALLS: list[dict] = []
OPEN_MEMBER: dict = {}


def count_rows(body: bytes, kind: str) -> int:
    if kind == 'quarterly':
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            body = archive.read('master.idx')
    lines = body.decode('ascii').splitlines()
    start = next(index for index, line in enumerate(lines) if line and set(line) == {'-'}) + 1
    return sum(1 for line in lines[start:] if line.strip())


def count(config: Path, evidence: Path) -> dict:
    from sec_edgar_ingest.config import load_config
    from sec_edgar_ingest.state import AcquisitionState
    from sec_edgar_ingest.storage import open_stores
    selected = json.loads(evidence.read_text())['selected_sources']
    opened = open_stores(load_config(config.resolve()), access='operator')
    try:
        acquisition, objects, found = AcquisitionState(opened[0]), opened[1], {}
        for source in selected:
            snapshot = acquisition.snapshot(source['source_id'], source['snapshot']['sha256'])
            objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
            found[source['period']] = {'kind': source['kind'], 'sha256': snapshot.sha256,
                                       'bytes': snapshot.byte_count,
                                       'rows': count_rows(objects.read(snapshot.raw_path), source['kind'])}
        return {'format_version': FORMAT, 'kind': 'count', 'sources': found}
    finally:
        for resource in reversed(opened):
            if resource is not None and hasattr(resource, 'close'):
                resource.close()


def row(kind: str, cik: int, serial: int, filed: date) -> str:
    text = filed.isoformat() if kind == 'quarterly' else filed.strftime('%Y%m%d')
    accession = f'{cik:010d}-{filed.year % 100:02d}-{serial:06d}'
    return f'{cik}|Company {cik}|10-K|{text}|edgar/data/{cik}/{accession}.txt'


def body(kind: str, rows: list[str]) -> bytes:
    ending, title = ('\r\n', 'Filename') if kind == 'quarterly' else ('\n', 'File Name')
    text = ('Description:           Master Index of EDGAR Dissemination Feed' + ending
            + 'Last Data Received:    synthetic' + ending + ending
            + 'CIK|Company Name|Form Type|Date Filed|' + title + ending + '-' * 80 + ending
            + ending.join(rows) + ending)
    raw = text.encode('ascii')
    if kind == 'daily':
        return raw
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        info = zipfile.ZipInfo('master.idx', (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, raw)
    return output.getvalue()


def listing(url: str, children: list[tuple[str, str]]) -> bytes:
    from sec_edgar_ingest.models import canonical_json, to_mapping_value
    return canonical_json(to_mapping_value({'directory': {
        'name': url[len(BASE):-len('index.json')], 'parent-dir': '../',
        'item': [{'name': name, 'href': name + ('/' if kind == 'dir' else ''), 'type': kind,
                  'size': '1', 'last-modified': 'synthetic'} for name, kind in children]}}))


def build_pack(root: Path, leaves: dict, repeats: int = 4) -> Path:
    """leaves: {(family, year, quarter): [(filename, body), ...]}, every listed leaf directory."""
    from sec_edgar_ingest.models import canonical_json, to_mapping_value
    (root / 'bodies').mkdir(parents=True)
    documents = {}
    for family in ('full-index', 'daily-index'):
        base = BASE + family + '/'
        keys = sorted(key for key in leaves if key[0] == family)
        years = sorted({year for _, year, _ in keys})
        documents[base + 'index.json'] = listing(base + 'index.json', [(str(year), 'dir') for year in years])
        for year in years:
            url = base + f'{year}/index.json'
            documents[url] = listing(url, [(f'QTR{quarter}', 'dir') for _, y, quarter in keys if y == year])
        for _, year, quarter in keys:
            url = base + f'{year}/QTR{quarter}/index.json'
            files = leaves[family, year, quarter]
            documents[url] = listing(url, [(name, 'file') for name, _ in files])
            for name, payload in files:
                documents[base + f'{year}/QTR{quarter}/{name}'] = payload
    responses = {}
    for url, payload in sorted(documents.items()):
        digest = hashlib.sha256(payload).hexdigest()
        target = root / 'bodies' / (digest + '.body')
        if not target.exists():
            target.write_bytes(payload)
        spec = {'status': 200, 'headers': {'Content-Length': str(len(payload)), 'X-Fixture': 'synthetic'},
                'body_path': 'bodies/' + digest + '.body', 'body_sha256': digest}
        responses[url] = [dict(spec) for _ in range(repeats)]
    path = root / 'manifest.json'
    path.write_bytes(canonical_json(to_mapping_value({'fixture_version': 'sec-acquisition-fixture-v1',
                                                      'provenance': 'synthetic', 'responses': responses})))
    return path


def write_config(path: Path, root: Path, manifest: Path, *, start: str, end: str, daily_start: str,
                 max_run_seconds: int = MAX_RUN_SECONDS) -> Path:
    from sec_edgar_ingest.config import HTTP_POLICY, Settings
    from sec_edgar_ingest.models import canonical_json, to_mapping_value
    value = {
        'config_version': 'sec-local-config-v1',
        'backfill': {'start_quarter': start, 'end_quarter': end},
        'daily': {'start_date': daily_start},
        'sec': {'user_agent': 'Lowell Mason sec-edgar-ingest mason.lowell@mac.com',
                'requests_per_second': 3, 'max_active_collectors': 1},
        'http': dict(HTTP_POLICY),
        'coordination': {'lease_seconds': 60, 'renew_every_seconds': 20,
                         'namespace': 'sec-owner-lowell-mason', 'clock_uncertainty_seconds': 2},
        'storage': {'backend': 'local', 'root': str(root / 'store')},
        'acquisition': {'mode': 'fixture'},
        'runtime': {'kind': 'native', 'release_manifest': str(manifest)},
        'logging': {'root': str(root / 'logs')},
        'execution': {'max_run_seconds': max_run_seconds},
        'etl': {'parser_version': 'sec-index-parser-v1', 'schema_version': 'sec-index-v1'},
        'reconciliation': {'require_withdrawal_approval': True},
        'fixture': {'allow_clock_override': True, 'allow_deadline_override': False},
    }
    Settings.from_mapping(value)  # Refuse an invalid config before any store exists.
    path.write_bytes(canonical_json(to_mapping_value(value)))
    return path


def instrument() -> None:
    """Time the release's own engine steps in this process; children stay native processes."""
    from sec_edgar_ingest import cli
    from sec_edgar_ingest.workflows import checked, runner

    def timed(owner, name):
        original = getattr(owner, name)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                return original(*args, **kwargs)
            finally:
                TIMINGS.append({'label': name, 'seconds': time.monotonic() - start})
        setattr(owner, name, wrapper)

    for name in ('select_work', 'baseline_gaps', 'source_revert_gaps', 'summarize'):
        timed(runner, name)
    for name in ('write_workflow_result', 'emit_summary'):
        timed(cli, name)
    execute = checked.Dispatcher.execute
    def timed_execute(self, command, step_id, settings, flags):
        start = time.monotonic()
        try:
            return execute(self, command, step_id, settings, flags)
        finally:
            TIMINGS.append({'label': 'child', 'command': command, 'step_id': step_id,
                            'seconds': time.monotonic() - start})
    checked.Dispatcher.execute = timed_execute
    process = runner.process_member
    def timed_member(value, *args, **kwargs):
        start = time.monotonic()
        processed = process(value, *args, **kwargs)
        MEMBERS.append({'member_id': value['member_id'], 'kind': value['source']['kind'],
                        'period': value['source']['period'], 'seconds': time.monotonic() - start,
                        'outcome': processed.result.outcome,
                        'quarters': [{'quarter': q.quarter, 'outcome': q.outcome} for q in processed.result.quarters]})
        return processed
    runner.process_member = timed_member


def invoke(config: Path, command: str, run_id: str, pack: Path, max_run_seconds: int = MAX_RUN_SECONDS) -> dict:
    from sec_edgar_ingest.cli import main
    deadline = datetime.now(timezone.utc) + timedelta(seconds=max_run_seconds - 600)
    argv = [command, '--config', str(config), '--run-id', run_id, '--execution-id', 'measure',
            '--attempt-id', 'a', '--deadline', deadline.isoformat(), '--today', TODAY.isoformat(),
            '--fixture-pack', str(pack)]
    out, err = io.StringIO(), io.StringIO()
    start = time.monotonic()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    seconds = time.monotonic() - start
    (config.parent / (run_id + '.stderr.jsonl')).write_text(err.getvalue())
    message = json.loads(out.getvalue().splitlines()[-1])
    return {'command': command, 'run_id': run_id, 'exit': code, 'outcome': message['outcome'],
            'result_ref': message['result_ref'], 'seconds': seconds}


def scenario(name: str, work: Path, manifest: Path, leaves, steps: list,
             max_run_seconds: int = MAX_RUN_SECONDS) -> dict:
    """`leaves` is one pack for every step, or a list with one pack for each step."""
    root = work / name
    root.mkdir(parents=True)
    packs = ([build_pack(root / 'pack', leaves)] * len(steps) if isinstance(leaves, dict)
             else [build_pack(root / f'pack-{index}', value) for index, value in enumerate(leaves)])
    invocations = []
    for index, (command, ranges) in enumerate(steps):
        config = write_config(root / f'config-{index}.json', root, manifest, max_run_seconds=max_run_seconds, **ranges)
        first_timing, first_member, first_wall = len(TIMINGS), len(MEMBERS), len(WALLS)
        call = invoke(config, command, f'measure-{name}-{index}', packs[index], max_run_seconds)
        timings = TIMINGS[first_timing:]
        members = MEMBERS[first_member:]
        walls = WALLS[first_wall:]
        for member in (*members, *walls):
            member['children'] = {t['command']: t['seconds'] for t in timings
                                  if t['label'] == 'child' and t['step_id'].endswith('-' + member['member_id'])}
        call.update(timings=timings, members=members, walls=walls)
        invocations.append(call)
    return {'invocations': invocations}


def quarters(start: str, end: str) -> list[tuple[int, int]]:
    year, quarter = int(start[:4]), int(start[-1])
    stop = (int(end[:4]), int(end[-1]))
    found = []
    while (year, quarter) <= stop:
        found.append((year, quarter))
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return found


def start_report(format_version: str, kind: str, scale: str, manifest: Path, counts: dict | None = None,
                 **extra) -> dict:
    """The opening keys of every measurement report: interpreter flags, release id and inputs.

    With `counts`, `inputs` also holds `quarterly_rows` and `daily_rows`, the rows of a full-size
    quarterly and daily file. The caller reads them back from `inputs`.
    """
    inputs = dict(SCALES[scale])
    if counts is not None:
        sources = counts['sources']
        inputs = {'quarterly_rows': sources['2024Q1']['rows'] if scale == 'full' else 1000,
                  'daily_rows': max(v['rows'] for v in sources.values() if v['kind'] == 'daily')
                  if scale == 'full' else 20, **inputs}
    return {'format_version': format_version, 'kind': kind, 'scale': scale, 'python': sys.executable,
            'flags': {'isolated': sys.flags.isolated, 'dont_write_bytecode': sys.dont_write_bytecode,
                      'pycache_prefix': sys.pycache_prefix},
            'release_id': json.loads(manifest.read_text())['release_id'], 'inputs': inputs,
            'started_at': datetime.now(timezone.utc).isoformat(), 'scenarios': {}, **extra}


def open_leaves(sizes: dict, daily_rows: int) -> dict:
    days = [date(2026, 10, 1) + timedelta(days=index) for index in range(sizes['open_days'])]
    return {('full-index', 2026, 4): [], ('daily-index', 2026, 3): [], ('daily-index', 2026, 4): [
        (f'master.{day:%Y%m%d}.idx', body('daily', [row('daily', 300000 + index, serial, day)
                                                     for serial in range(daily_rows)]))
        for index, day in enumerate(days)]}


def closed_leaves(sizes: dict, quarterly_rows: int, daily_rows: int) -> dict:
    """A quarterly baseline from closed_start to 2026Q3, the back-dated quarters full size, then two daily files:
    one back-dates one row into one closed quarter (measure 1), the other one row into each (findings §4.7)."""
    heavy = sizes['closed_quarters']
    leaves = {('full-index', 2026, 4): [], ('daily-index', 2026, 4): []}
    for index, (year, quarter) in enumerate(quarters(sizes['closed_start'], '2026Q3')):
        size = quarterly_rows if f'{year}Q{quarter}' in heavy else sizes['finish_rows']
        first = date(year, (quarter - 1) * 3 + 1, 2)
        leaves['full-index', year, quarter] = [('master.zip', body('quarterly', [
            row('quarterly', 100000 + index * 50000 + serial % 40000, serial, first) for serial in range(size)]))]
        leaves['daily-index', year, quarter] = []

    def back_date(label: str) -> date:
        return date(int(label[:4]), (int(label[-1]) - 1) * 3 + 1, 12)

    single = [row('daily', 310000, serial, date(2026, 12, 1)) for serial in range(daily_rows)]
    single.append(row('daily', 900001, 1, back_date(heavy[0])))
    fanout = [row('daily', 320000, serial, date(2026, 12, 2)) for serial in range(daily_rows)]
    fanout.extend(row('daily', 900100 + index, 1, back_date(label)) for index, label in enumerate(heavy))
    leaves['daily-index', 2026, 4] = [('master.20261201.idx', body('daily', single)),
                                      ('master.20261202.idx', body('daily', fanout))]
    return leaves


def finish_leaves(sizes: dict) -> dict:
    leaves = {}
    for index, (year, quarter) in enumerate(quarters(sizes['finish_start'], '2026Q4')):
        first = date(year, (quarter - 1) * 3 + 1, 1)
        leaves['full-index', year, quarter] = [('master.zip', body('quarterly', [
            row('quarterly', 400000 + serial, index * 1000 + serial, first) for serial in range(sizes['finish_rows'])]))]
        leaves['daily-index', year, quarter] = []
    return leaves


def run(manifest: Path, work: Path, counts: dict, scale: str) -> dict:
    sizes = SCALES[scale]
    instrument()
    report = start_report(FORMAT, 'run', scale, manifest, counts)
    quarterly_rows, daily_rows = report['inputs']['quarterly_rows'], report['inputs']['daily_rows']
    report['scenarios']['open'] = scenario('open', work, manifest, open_leaves(sizes, daily_rows),
        [('daily', {'start': '2026Q4', 'end': 'open', 'daily_start': '2026-10-01'})])
    report['scenarios']['closed'] = scenario(
        'closed', work, manifest, closed_leaves(sizes, quarterly_rows, daily_rows), [
            ('backfill', {'start': sizes['closed_start'], 'end': '2026Q3', 'daily_start': '2026-12-01'}),
            ('daily', {'start': sizes['closed_start'], 'end': 'open', 'daily_start': '2026-12-01'})])
    run_finish(report, work, manifest, sizes)
    report['ended_at'] = datetime.now(timezone.utc).isoformat()
    report['measures'] = measures(report)
    report['proposal'] = proposal(report['measures'])
    return report


def run_finish(report: dict, work: Path, manifest: Path, sizes: dict) -> None:
    report['scenarios']['finish'] = scenario('finish', work, manifest, finish_leaves(sizes),
        [('backfill', {'start': sizes['finish_start'], 'end': 'open', 'daily_start': '2026-12-31'})])


def run_finish_only(manifest: Path, work: Path, scale: str) -> dict:
    """The finish scenario alone (owner decision D2, 2026-10-23): the floor needs only the finish step's cost."""
    sizes = SCALES[scale]
    instrument()
    report = start_report(FORMAT, 'run-finish-only', scale, manifest)
    run_finish(report, work, manifest, sizes)
    report['ended_at'] = datetime.now(timezone.utc).isoformat()
    call = report['scenarios']['finish']['invocations'][0]
    labelled = {label: sum(t['seconds'] for t in call['timings'] if t['label'] == label) for label in FINISH_LABELS}
    report['measures'] = {'finish_seconds': sum(labelled.values()), 'finish_label_seconds': labelled,
                          'finish_members': len(call['members']), 'invocation_seconds': call['seconds'],
                          'exits': {'finish': [call['exit']]}}
    return report


def authority_leaves(sizes: dict, quarterly_rows: int, daily_rows: int) -> list[dict]:
    """Findings §2: a closed quarter (2026Q3) with a daily-only generation gains its quarterly authority.

    Step 1 publishes `authority_days` full-size daily files. Step 2's quarterly file lists 90% of their keys
    and its own rows up to the full quarterly size, so the full rebuild loads the active rows, withdraws the
    rest and stops at the gate.
    """
    days = [date(2026, 7, 1) + timedelta(days=index) for index in range(sizes['authority_days'])]
    keys = [(500000 + index, serial, day) for index, day in enumerate(days) for serial in range(daily_rows)]
    daily = [(f'master.{day:%Y%m%d}.idx', body('daily', [row('daily', cik, serial, filed)
                                                          for cik, serial, filed in keys if filed == day]))
             for day in days]
    listed = [key for position, key in enumerate(keys) if position % 10]
    rows = [row('quarterly', cik, serial, filed) for cik, serial, filed in listed]
    rows.extend(row('quarterly', 600000 + serial % 40000, serial, date(2026, 7, 2))
                for serial in range(quarterly_rows - len(listed)))
    first = {('full-index', 2026, 3): [], ('full-index', 2026, 4): [],
             ('daily-index', 2026, 3): daily, ('daily-index', 2026, 4): []}
    return [first, {**first, ('full-index', 2026, 3): [('master.zip', body('quarterly', rows))]}]


def history_counts(state: Path) -> dict:
    """Rows of the history tables that `_obligations` and `reuse_exact_binding` scan (S4)."""
    import sqlite3
    if not state.exists():
        return {'WorkflowChildCall': 0, 'Attempts': 0}
    connection = sqlite3.connect('file:' + str(state) + '?mode=ro', uri=True)
    def tally(where: str) -> int:
        return connection.execute('select count(*) from records where ' + where).fetchone()[0]

    try:
        # A record kind is the suffix of `partition`, and its table is `table_for(kind)` (storage.contracts).
        return {'WorkflowChildCall': tally("table_name = 'SourceState' and partition like '%:WorkflowChildCall'"),
                'Attempts': tally("table_name = 'Attempts'")}
    finally:
        connection.close()


def instrument_members(state: Path) -> None:
    """Member wall (§6): from the member's `sibling_completion` call to the return of its durable receipt.

    Machine load and the history row counts are sampled at each member boundary.
    """
    from sec_edgar_ingest.workflows import members, runner
    sibling, record = runner.sibling_completion, members.WorkflowMembers.record

    def entered(value, *args, **kwargs):
        OPEN_MEMBER.clear()
        OPEN_MEMBER.update(member_id=value['member_id'], kind=value['source']['kind'],
                           period=value['source']['period'], started=time.monotonic(),
                           load_at_start=list(os.getloadavg()), history=history_counts(state))
        return sibling(value, *args, **kwargs)

    def recorded(self, result, context, evidence):
        descriptor = record(self, result, context, evidence)
        if OPEN_MEMBER.get('member_id') == result.member_id:
            WALLS.append({**OPEN_MEMBER, 'wall_seconds': time.monotonic() - OPEN_MEMBER['started'],
                          'load_at_end': list(os.getloadavg()), 'outcome': result.outcome})
            OPEN_MEMBER.clear()
        return descriptor

    runner.sibling_completion = entered
    members.WorkflowMembers.record = recorded


def run_scenario(name: str, manifest: Path, work: Path, counts: dict, scale: str) -> dict:
    """One Stage 1b scenario in this process. Its report is written even when the run fails."""
    sizes = SCALES[scale]
    report = start_report(COST_FORMAT, 'scenario', scale, manifest, counts, scenario=name,
                          max_run_seconds=COST_MAX_RUN_SECONDS, status='running')
    quarterly_rows, daily_rows = report['inputs']['quarterly_rows'], report['inputs']['daily_rows']
    instrument()
    instrument_members(work / name / 'store' / 'state.sqlite3')
    plans = {
        'open': (open_leaves(sizes, daily_rows),
                 [('daily', {'start': '2026Q4', 'end': 'open', 'daily_start': '2026-10-01'})]),
        'closed': (closed_leaves(sizes, quarterly_rows, daily_rows),
                   [('backfill', {'start': sizes['closed_start'], 'end': '2026Q3', 'daily_start': '2026-12-01'}),
                    ('daily', {'start': sizes['closed_start'], 'end': 'open', 'daily_start': '2026-12-01'})]),
        'authority': (authority_leaves(sizes, quarterly_rows, daily_rows),
                      [('daily', {'start': '2026Q3', 'end': 'open', 'daily_start': '2026-07-01'}),
                       ('backfill', {'start': '2026Q3', 'end': '2026Q3', 'daily_start': '2026-07-01'})]),
        'finish': (finish_leaves(sizes),
                   [('backfill', {'start': sizes['finish_start'], 'end': 'open', 'daily_start': '2026-12-31'})]),
    }
    leaves, steps = plans[name]
    try:
        report['scenarios'][name] = scenario(name, work, manifest, leaves, steps, COST_MAX_RUN_SECONDS)
        report['status'] = 'complete'
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = repr(error)
        report['partial_walls'], report['partial_timings'] = WALLS, TIMINGS
        raise
    finally:
        report['ended_at'] = datetime.now(timezone.utc).isoformat()
        (work / f'{name}-report.json').write_text(json.dumps(report, sort_keys=True, indent=1) + '\n')
    return report


def cost_proposal(finish_seconds: float, slowest_seconds: float) -> dict:
    """C8 floor and the §6 reserve rule. The owner sets the committed values at the checkpoint."""
    p4_floor = max(60, math.ceil(3 * finish_seconds / 30) * 30)
    floor = max(FLOOR_MINIMUM_SECONDS, p4_floor)
    reserve = math.ceil((RESERVE_FACTOR * slowest_seconds + floor) / 60) * 60
    return {'p4_floor_seconds': p4_floor, 'floor_seconds': floor, 'floor_changes': floor != FLOOR_MINIMUM_SECONDS,
            'reserve_seconds': reserve, 'slowest_member_wall_seconds': slowest_seconds,
            'fit_gate_passes': slowest_seconds <= LAUNCHER_DEFAULT_SECONDS - reserve}


def history_fit(walls: list[dict]) -> dict | None:
    """Per-member engine seconds (wall minus children) against `WorkflowChildCall` rows at member start (S4)."""
    points = [(w['history']['WorkflowChildCall'], w['wall_seconds'] - sum(w['children'].values())) for w in walls]
    if len({x for x, _ in points}) < 2:
        return None
    fit = linear_fit(points)
    slope, intercept = fit['slope_seconds_per_source'], fit['intercept_seconds']
    return {'slope_seconds_per_child_call': slope, 'intercept_seconds': intercept, 'points': fit['points'],
            'projected_engine_seconds': {str(mark): intercept + slope * mark for mark in HISTORY_MARKS}}


def summarize(work: Path) -> dict:
    """Combine the scenario reports into the §6 measures and the C8 and reserve proposal."""
    reports = {name: json.loads((work / f'{name}-report.json').read_text()) for name in COST_SCENARIOS
               if (work / f'{name}-report.json').exists()}
    calls = {name: report['scenarios'][name]['invocations'] for name, report in reports.items()
             if report['status'] == 'complete'}

    def walls(name: str, index: int) -> list[dict]:
        return calls[name][index]['walls'] if name in calls and index < len(calls[name]) else []

    def finish(call: dict) -> float:
        return sum(t['seconds'] for t in call['timings'] if t['label'] in FINISH_LABELS)

    every = [wall for value in calls.values() for call in value for wall in call['walls']]
    open_walls, closed_daily = walls('open', 0), walls('closed', 1)
    finish_seconds = {f'{name}-{index}': finish(call) for name in ('closed', 'finish') if name in calls
                      for index, call in enumerate(calls[name])}
    slowest = max(every, key=lambda wall: wall['wall_seconds']) if every else None
    measures = {
        'incomplete_scenarios': [name for name in COST_SCENARIOS if name not in calls],
        'open_member_wall_seconds': {str(mark): open_walls[mark]['wall_seconds'] for mark in OPEN_MARKS
                                     if mark < len(open_walls)},
        'closed_first_publication_wall_seconds': {wall['period']: wall['wall_seconds'] for wall in walls('closed', 0)
                                                  if wall['kind'] == 'quarterly'},
        'closed_measure_1_wall_seconds': closed_daily[0]['wall_seconds'] if closed_daily else None,
        'closed_fanout_wall_seconds': closed_daily[1]['wall_seconds'] if len(closed_daily) > 1 else None,
        'authority_wall_seconds': next((wall['wall_seconds'] for wall in walls('authority', 1)
                                        if wall['kind'] == 'quarterly'), None),
        'finish_seconds': finish_seconds,
        'slowest_member': None if slowest is None else {key: slowest[key] for key in
                                                        ('kind', 'period', 'wall_seconds', 'children', 'outcome')},
        'history': {name: history_fit([wall for call in value for wall in call['walls']]) for name, value in calls.items()},
        'load_at_start': {name: [min(w['load_at_start'][0] for w in ws), max(w['load_at_start'][0] for w in ws)]
                          for name, ws in ((n, [w for c in v for w in c['walls']]) for n, v in calls.items()) if ws},
        'exits': {name: [call['exit'] for call in value] for name, value in calls.items()},
    }
    complete = not measures['incomplete_scenarios'] and finish_seconds and slowest is not None
    proposal = cost_proposal(max(finish_seconds.values()), slowest['wall_seconds']) if complete else None
    return {'format_version': COST_FORMAT, 'kind': 'summary', 'work': str(work),
            'release_ids': sorted({report['release_id'] for report in reports.values()}),
            'measures': measures, 'proposal': proposal}


def measures(report: dict) -> dict:
    scenarios = report['scenarios']
    open_members = scenarios['open']['invocations'][0]['members']
    single, fanout = scenarios['closed']['invocations'][1]['members']
    finish = scenarios['finish']['invocations'][0]
    every = [member for value in scenarios.values() for call in value['invocations'] for member in call['members']]
    slowest = max(every, key=lambda member: member['seconds'])
    return {'open_publish_seconds': {str(k): open_members[k]['children'].get('publish')
                                     for k in OPEN_MARKS if k < len(open_members)},
            'closed_rebuild_publish_seconds': single['children'].get('publish'),
            'closed_rebuild_quarters': single['quarters'],
            'closed_fanout_publish_seconds': fanout['children'].get('publish'),
            'closed_fanout_quarters': fanout['quarters'],
            'finish_seconds': sum(t['seconds'] for t in finish['timings'] if t['label'] in FINISH_LABELS),
            'finish_members': len(finish['members']),
            'slowest_member': {key: slowest[key] for key in ('kind', 'period', 'seconds', 'children', 'outcome')},
            'exits': {name: [call['exit'] for call in value['invocations']] for name, value in scenarios.items()}}


def proposal(values: dict) -> dict:
    """Plan 4 default P4. The owner sets the committed values (D2)."""
    floor = max(60, math.ceil(3 * values['finish_seconds'] / 30) * 30)
    slowest = values['slowest_member']['seconds']
    reserve = math.ceil((2 * slowest + floor) / 60) * 60
    return {'floor_seconds': floor, 'reserve_seconds': reserve,
            'slowest_fits_default_timeout': slowest <= 3300 - reserve}


def store_attempts(state: Path) -> list[dict]:
    """Read the durable `Attempts` records of one fixture store (read-only, stdlib only)."""
    import sqlite3
    connection = sqlite3.connect('file:' + str(state) + '?mode=ro&immutable=1', uri=True)
    found = []
    for _, value in connection.execute("select key, value from records where table_name = 'Attempts'"):
        record = json.loads(value)
        context = record['context']
        start = datetime.fromisoformat(record.get('started_at') or context['started_at'])
        end = datetime.fromisoformat(record['ended_at']) if record.get('ended_at') else None
        found.append({'run_id': context['run_id'], 'command': context['command'], 'attempt_id': context['attempt_id'],
                      'start': start, 'end': end, 'outcome': record.get('outcome'),
                      'deadline': context.get('deadline')})
    return sorted(found, key=lambda item: item['start'])


def rebuild_scenario(state: Path) -> dict:
    """Rebuild per-member child timings of one run from its store, for a run that ended without a report.

    A member is a `collect` attempt followed by the `transform` and `publish` attempts that start before the next
    `collect` (the runs are sequential, so order by start time identifies the member). Each attempt id appears
    in several records (the operation records have outcome `received`); the record with the attempt's own
    outcome is the one that is timed. `sources_in_quarter_before` is the member index, so it counts sources
    already in the quarter only for the `open` scenario. `gap_after_seconds` is the time from the end of the member's last child to
    the start of the next member's `collect`: it is engine time outside any child (evaluation, receipts, locks).
    """
    attempts = store_attempts(state)
    seconds = lambda item: (item['end'] - item['start']).total_seconds() if item['end'] else None
    discover = next((item for item in attempts if item['command'] == 'discover' and item['outcome'] != 'received'), None)
    members, order = {}, []
    for item in attempts:
        if item['command'] not in ('collect', 'transform', 'publish') or item['outcome'] == 'received':
            continue
        key = item['attempt_id']
        if item['command'] == 'collect':
            members[key] = {'collect_start': item['start'], 'collect_seconds': seconds(item)}
            order.append(key)
        else:
            members[order[-1]][item['command']] = item
    rows = []
    for index, key in enumerate(order):
        member = members[key]
        last = member.get('publish') or member.get('transform')
        following = members[order[index + 1]]['collect_start'] if index + 1 < len(order) else None
        row = {'sources_in_quarter_before': index, 'collect_start': member['collect_start'].isoformat(),
               'collect_seconds': member['collect_seconds']}
        for command in ('transform', 'publish'):
            child = member.get(command)
            row[command + '_seconds'] = seconds(child) if child else None
            row[command + '_outcome'] = child['outcome'] if child else None
        row['gap_after_seconds'] = (following - last['end']).total_seconds() if following and last and last['end'] else None
        row['member_wall_seconds'] = (following - member['collect_start']).total_seconds() if following else None
        rows.append(row)
    return {'run_id': attempts[0]['run_id'] if attempts else None,
            'run_started': attempts[0]['start'].isoformat() if attempts else None,
            'deadline': attempts[0]['deadline'] if attempts else None,
            'discover_seconds': seconds(discover) if discover else None,
            'members': rows}


def linear_fit(points: list[tuple[float, float]]) -> dict:
    count = len(points)
    mean_x, mean_y = sum(x for x, _ in points) / count, sum(y for _, y in points) / count
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sum((x - mean_x) ** 2 for x, _ in points)
    return {'slope_seconds_per_source': slope, 'intercept_seconds': mean_y - slope * mean_x, 'points': count}


def rebuild(work: Path) -> dict:
    report = {'format_version': FORMAT, 'kind': 'rebuilt-from-store', 'work': str(work), 'scenarios': {}}
    for name in ('open', 'closed', 'finish'):
        state = work / name / 'store' / 'state.sqlite3'
        if state.exists():
            report['scenarios'][name] = rebuild_scenario(state)
    members = report['scenarios']['open']['members']
    published = [(row['sources_in_quarter_before'], row['publish_seconds']) for row in members
                 if row['publish_seconds'] is not None and row['publish_outcome'] == 'success']
    walls = [(row['sources_in_quarter_before'], row['member_wall_seconds']) for row in members
             if row['member_wall_seconds'] is not None]
    report['open_fit'] = {'publish': linear_fit(published), 'member_wall': linear_fit(walls),
                          'measured_marks': {str(mark): next((y for x, y in published if x == mark), None)
                                             for mark in OPEN_MARKS},
                          'max_sources_before': max(x for x, _ in published)}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='measure-d5-drain')
    commands = parser.add_subparsers(dest='command', required=True)
    rebuilding = commands.add_parser('rebuild')
    rebuilding.add_argument('--work', type=Path, required=True)
    counting = commands.add_parser('count')
    counting.add_argument('--config', type=Path, required=True)
    counting.add_argument('--evidence', type=Path, required=True)
    running = commands.add_parser('run')
    running.add_argument('--release-manifest', type=Path, required=True)
    running.add_argument('--work', type=Path, required=True)
    running.add_argument('--counts', type=Path, required=True)
    running.add_argument('--scale', choices=sorted(SCALES), required=True)
    running.add_argument('--only', choices=['finish'], default=None)
    scenario_parser = commands.add_parser('scenario')
    scenario_parser.add_argument('--name', choices=COST_SCENARIOS, required=True)
    scenario_parser.add_argument('--release-manifest', type=Path, required=True)
    scenario_parser.add_argument('--work', type=Path, required=True)
    scenario_parser.add_argument('--counts', type=Path, required=True)
    scenario_parser.add_argument('--scale', choices=sorted(SCALES), required=True)
    summarizing = commands.add_parser('summarize')
    summarizing.add_argument('--work', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'rebuild':
        sys.stdout.write(json.dumps(rebuild(args.work.resolve()), sort_keys=True, indent=1) + '\n')
        return 0
    if args.command == 'count':
        sys.stdout.write(json.dumps(count(args.config, args.evidence), sort_keys=True, indent=1) + '\n')
        return 0
    if args.command in ('scenario', 'summarize'):
        work = args.work.resolve()
        if work.is_relative_to('/tmp') or work.is_relative_to('/private/tmp'):
            raise SystemExit('measurement work must be under the project, not /tmp')
        if args.command == 'summarize':
            summary = summarize(work)
            (work / 'measurement.json').write_text(json.dumps(summary, sort_keys=True, indent=1) + '\n')
            sys.stdout.write(json.dumps({'measures': summary['measures'], 'proposal': summary['proposal']},
                                        sort_keys=True, indent=1) + '\n')
            return 0 if summary['proposal'] is not None else 1
        work.mkdir(parents=True, exist_ok=True)
        report = run_scenario(args.name, args.release_manifest.resolve(), work,
                              json.loads(args.counts.read_text()), args.scale)
        sys.stdout.write(json.dumps({'scenario': args.name, 'status': report['status']}) + '\n')
        return 0
    work = args.work.resolve()
    if work.is_relative_to('/tmp') or work.is_relative_to('/private/tmp'):
        raise SystemExit('measurement work must be under the project, not /tmp')
    work.mkdir(parents=True, exist_ok=False)
    if args.only == 'finish':
        report = run_finish_only(args.release_manifest.resolve(), work, args.scale)
    else:
        report = run(args.release_manifest.resolve(), work, json.loads(args.counts.read_text()), args.scale)
    (work / 'measurement.json').write_text(json.dumps(report, sort_keys=True, indent=1) + '\n')
    sys.stdout.write(json.dumps({'measures': report['measures'], 'proposal': report.get('proposal')},
                                sort_keys=True, indent=1) + '\n')
    return 0 if all(code == 0 for codes in report['measures']['exits'].values() for code in codes) else 1


if __name__ == '__main__':
    raise SystemExit(main())
