"""Read-only Stage 2 baseline-campaign evidence: file inventory, transport audit, coverage and timing.

Run under the selected release interpreter with -I -B -X pycache_prefix=/dev/null. The tool opens
the store with operator access, sends no request and writes nothing under the store root. It uses
release internals (workflow result validation, ETL readers, durable child attempts). It is verified
against releases fc68adef... and 9fa189a0...; re-verify it before use with any other release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

FORMAT = 'sec-baseline-campaign-evidence-v1'
BUDGET_FORMAT = 'sec-baseline-campaign-budget-v1'
MUTABLE_STATE = frozenset({'state.sqlite3', 'state.sqlite3-wal', 'state.sqlite3-shm'})
# SQLite creates and deletes its WAL and shared-memory files itself; the database file stays strict.
TRANSIENT_STATE = MUTABLE_STATE - {'state.sqlite3'}
COVERED = frozenset({'covered', 'covered_open_quarter'})
RANK = {'complete': 0, 'pending': 1, 'failed': 2}
CHECKS = ('full', 'integrity')
CHILD_COMMANDS = ('collect', 'transform', 'publish')
BUDGET_TOTALS = (('attempts', 'max_request_attempts'), ('distinct_urls', 'max_distinct_urls'),
                 ('received_bytes', 'max_received_bytes'))


def dumps(value) -> str:
    return json.dumps(value, sort_keys=True, indent=1) + '\n'


# ---- file inventory -------------------------------------------------------------------------

def file_inventory(root: Path) -> dict:
    files = []
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        files.append({'relative_path': path.relative_to(root).as_posix(), 'sha256': digest,
                      'byte_count': path.stat().st_size})
    return {'root': str(root), 'file_count': len(files),
            'byte_count': sum(item['byte_count'] for item in files), 'files': files}


def recorded_inventory(value: dict) -> dict:
    """Accept the L12 machine evidence, an earlier `files` report, or a bare inventory."""
    if 'output_inventory' in value:
        return value['output_inventory']['live_root']
    return value['inventory'] if 'inventory' in value else value


def compare_inventory(recorded: dict, actual: dict) -> dict:
    """Recorded files must survive byte-identical, except the SQLite state files.

    The WAL and shared-memory files may also appear or vanish; that is reported as a state change.
    """
    before = {item['relative_path']: item for item in recorded['files']}
    after = {item['relative_path']: item for item in actual['files']}
    changed = sorted(path for path in before.keys() & after.keys()
                     if (before[path]['sha256'], before[path]['byte_count'])
                     != (after[path]['sha256'], after[path]['byte_count']))
    journal = (before.keys() ^ after.keys()) & TRANSIENT_STATE
    return {'missing': sorted(before.keys() - after.keys() - TRANSIENT_STATE),
            'added': sorted(after.keys() - before.keys() - TRANSIENT_STATE),
            'changed_immutable': [path for path in changed if path not in MUTABLE_STATE],
            'changed_state': sorted({path for path in changed if path in MUTABLE_STATE} | journal)}


# ---- transport audit ------------------------------------------------------------------------

def summarize_attempts(values: list[dict]) -> dict:
    return {'attempts': len(values),
            'distinct_urls': len({value['url'] for value in values}),
            'received_bytes': sum(value['byte_count'] or 0 for value in values),
            'max_ordinal': max((value['ordinal'] for value in values), default=0),
            'uncertain': sum(value['outcome'] == 'uncertain' for value in values),
            'access_denied': sum(value['status'] == 403 for value in values),
            'statuses': dict(sorted(Counter(str(value['status']) for value in values).items())),
            'outcomes': dict(sorted(Counter(value['outcome'] for value in values).items()))}


def check_budget(audit: dict, budget: dict) -> list[dict]:
    if budget.get('format_version') != BUDGET_FORMAT:
        raise ValueError('unsupported campaign budget format')
    breaches = []
    total = audit['total']
    for field, limit in BUDGET_TOTALS:
        if total[field] > budget[limit]:
            breaches.append({'scope': 'campaign', 'field': field, 'observed': total[field], 'limit': budget[limit]})
    for run_id, summary in audit['runs'].items():
        if summary['attempts'] > budget['max_request_attempts_per_invocation']:
            breaches.append({'scope': run_id, 'field': 'attempts', 'observed': summary['attempts'],
                             'limit': budget['max_request_attempts_per_invocation']})
    if len(audit['runs']) > budget['max_invocations']:
        breaches.append({'scope': 'campaign', 'field': 'invocations', 'observed': len(audit['runs']),
                         'limit': budget['max_invocations']})
    for field in ('access_denied', 'uncertain'):
        if total[field]:
            breaches.append({'scope': 'campaign', 'field': field, 'observed': total[field], 'limit': 0})
    return breaches


def transport_audit(store, run_ids: list[str]) -> dict:
    rows = [row.to_mapping()['value'] for row in store.scan('TransportAttempt', {})]
    runs = {run_id: summarize_attempts([value for value in rows if value['context']['run_id'] == run_id])
            for run_id in run_ids}
    return {'runs': runs,
            'total': summarize_attempts([value for value in rows if value['context']['run_id'] in runs]),
            'store_total': summarize_attempts(rows)}


# ---- coverage -------------------------------------------------------------------------------

def unit_verdict(quarter: str, open_quarter: str | None, member: dict | None, view: dict,
                 source_missing: bool) -> str:
    """One G2 verdict for one requested quarterly source unit."""
    if member is None:
        return 'source_missing' if source_missing else 'no_campaign_result'
    if member['quarantined'] and member['status'] == 'failed':
        return 'quarantined'
    if member['outcome'] == 'awaiting_approval' or any(
            item['quarter'] == quarter and item['outcome'] == 'awaiting_approval' for item in member['quarters']):
        return 'gated'
    if member['status'] != 'complete':
        return member['status']
    if (view['status'] != 'published' or view['membership_source_id'] != member['source_id']
            or view['gate'] != 'clear' or view['row_count'] == 0):
        return 'publication_mismatch'
    if view['validated_rows'] is None:
        return 'published_unchecked'  # An integrity-only view never counts as coverage.
    if view['validated_rows'] != view['row_count']:
        return 'publication_mismatch'
    return 'covered_open_quarter' if quarter == open_quarter else 'covered'


def member_view(result, member) -> dict:
    from sec_edgar_ingest.workflows.contracts import member_status
    return {'source_id': member.source.source_id, 'kind': member.source.kind, 'period': member.source.period,
            'url': member.source.canonical_url, 'run_id': result.context.run_id,
            'attempt_id': result.context.attempt_id, 'outcome': member.outcome,
            'status': member_status(member.outcome), 'quarantined': member.quarantined,
            'downloaded': member.downloaded, 'transformed': member.transformed,
            'quarters': [{'quarter': item.quarter, 'outcome': item.outcome, 'generation_id': item.generation_id,
                          'candidate_ref': item.candidate_ref} for item in member.quarters],
            'gaps': [{'code': gap.code, 'message': gap.message} for gap in member.gaps]}


def latest_members(results) -> dict:
    """Later invocations supersede earlier ones; inside one result the worst member status wins."""
    latest = {}
    for result in results:
        mine = {}
        for member in result.members:
            view = member_view(result, member)
            held = mine.get(view['source_id'])
            if held is None or RANK[view['status']] > RANK[held['status']]:
                mine[view['source_id']] = view
        latest.update(mine)
    return latest


def quarter_view(quarter: str, objects, state, check: str = 'full') -> dict:
    """`full` reads every row through the release's full content check (once); `integrity` checks
    only the exact manifest and file hashes (C1) and reports `validated_rows` as null."""
    from sec_edgar_ingest.etl.reader import capture_quarter, checked_manifest, read_quarter
    if check not in CHECKS:
        raise ValueError('unknown quarter check: ' + check)
    try:
        capture = capture_quarter(quarter, objects, state)
        if capture is None:
            return {'quarter': quarter, 'status': 'unpublished'}
        rows = sum(1 for _ in read_quarter(capture, objects)) if check == 'full' else None
        manifest = checked_manifest(capture, objects)
    except Exception as error:  # Any refusal is evidence for this quarter, never a crash of the inventory.
        return {'quarter': quarter, 'status': 'capture_invalid', 'error': type(error).__name__ + ': ' + str(error)}
    membership = manifest.membership_source
    return {'quarter': quarter, 'status': 'published', 'capture': capture.to_mapping(),
            'quarter_mode': manifest.quarter_mode, 'gate': manifest.gate, 'row_count': manifest.row_count,
            'validated_rows': rows,
            'membership_source_id': None if membership is None else membership.source.source_id,
            'membership_snapshot_sha256': None if membership is None else membership.snapshot.sha256,
            'source_kinds': dict(sorted(Counter(ref.source.kind for ref in manifest.sources).items())),
            # Closed quarters with a quarterly membership publish only membership keys (catalog._resolve).
            'daily_rows_considered': sum(ref.quarter_counts.get(quarter, 0)
                                         for ref in manifest.sources if ref.source.kind == 'daily')}


def read_results(refs: list[str], store, objects) -> list:
    from sec_edgar_ingest.workflows.contracts import WorkflowResult, workflow_path
    from sec_edgar_ingest.workflows.results import _read, _validate_report
    results = []
    for ref in refs:
        value, _ = _read(ref, objects)
        result = WorkflowResult.from_mapping(value)
        if workflow_path(result.context) != ref:
            raise ValueError('workflow result path differs from its canonical identity: ' + ref)
        _validate_report(result, store, objects)
        results.append(result)
    return sorted(results, key=lambda result: (result.context.started_at, result.context.run_id))


def coverage(store, objects, refs: list[str], start: str, end: str, open_quarter: str | None,
             check: str = 'full') -> dict:
    from sec_edgar_ingest.discovery import quarter_span
    from sec_edgar_ingest.etl.state import EtlState
    requested = quarter_span(start, end)
    results = read_results(refs, store, objects)
    for result in results:
        if not set(result.requested_quarters) <= set(requested):
            raise ValueError('a result requested quarters outside the campaign range: ' + result.context.run_id)
    latest = latest_members(results)
    state = EtlState(store)
    published = sorted({row.to_mapping()['value']['quarter'] for row in store.scan('QuarterPublication', {})})
    views = {quarter: quarter_view(quarter, objects, state, check) for quarter in sorted({*requested, *published})}
    units = []
    for quarter in requested:
        quarterly = [view for view in latest.values() if view['kind'] == 'quarterly' and view['period'] == quarter]
        if len(quarterly) > 1:
            raise ValueError('more than one quarterly source claims ' + quarter)
        member = quarterly[0] if quarterly else None
        asked = [result for result in results if quarter in result.requested_quarters]
        last = asked[-1] if asked else None
        missing = last is not None and any(gap.code == 'baseline_source_missing' and gap.details.get('quarter') == quarter
                                           for gap in last.gaps)
        units.append({'quarter': quarter, 'verdict': unit_verdict(quarter, open_quarter, member, views[quarter], missing),
                      'source': member, 'filing_quarter': views[quarter],
                      'last_result_gaps': [] if last is None else sorted(
                          {gap.code for gap in last.gaps if gap.details.get('quarter') == quarter})})
    verdicts = Counter(unit['verdict'] for unit in units)
    return {'format_version': FORMAT, 'kind': 'coverage', 'check': check, 'requested': {'start': start, 'end': end,
            'open_quarter': open_quarter, 'quarters': len(requested)},
            'results': [{'run_id': result.context.run_id, 'attempt_id': result.context.attempt_id,
                         'command': result.context.command, 'outcome': result.outcome,
                         'counts': dict(result.counts)} for result in results],
            'verdicts': dict(sorted(verdicts.items())),
            'complete': bool(units) and set(verdicts) <= COVERED,
            'units': units,
            'other_filing_quarters': [views[quarter] for quarter in published if quarter not in requested],
            'daily_sources': sorted((view for view in latest.values() if view['kind'] == 'daily'),
                                    key=lambda view: (view['period'], view['source_id']))}


# ---- member timing --------------------------------------------------------------------------

def _time(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _seconds(start, end) -> float:
    return round((_time(end) - _time(start)).total_seconds(), 3)


def child_attempts(values: list[dict]) -> dict:
    """Finished child `Attempt` values keyed by (run_id, command, attempt_id); the latest end wins."""
    found = {}
    for value in values:
        context = value['context']
        if (context['command'] not in CHILD_COMMANDS or value.get('ended_at') is None
                or value.get('outcome') == 'received'):
            continue
        key = (context['run_id'], context['command'], context['attempt_id'])
        held = found.get(key)
        if held is None or _time(value['ended_at']) > _time(held['ended_at']):
            found[key] = value
    return found


def member_timings(run_id: str, members: list[dict], attempts: dict) -> list[dict]:
    """Per-member child seconds and wall for one workflow result.

    A member starts at its first child's start. Members run one at a time, so a member's wall runs to
    the next timed member's start. The last timed member's wall runs to its own last child's end, so no
    member's wall holds the finish step (see `tail_seconds`). Engine seconds are the wall minus the
    member's own child seconds. A child of another run (a reused child) is listed, not timed. A member
    that ends `unchanged` with no child ref is a B4 sibling completion. A member deferred at the cutoff
    has no child ref either, and is not B4.
    """
    rows = []
    for member in members:
        children, reused = {}, []
        for ref in member['child_refs']:
            _, _, ref_run, command, attempt_id, _ = ref.split('/')
            if ref_run != run_id:
                reused.append(ref)
                continue
            value = attempts.get((ref_run, command, attempt_id))
            if value is None:
                raise ValueError('child result has no finished attempt record: ' + ref)
            started = value.get('started_at') or value['context']['started_at']
            children[command] = {'outcome': value['outcome'], 'started_at': str(started),
                                 'ended_at': str(value['ended_at']), 'seconds': _seconds(started, value['ended_at'])}
        start = min((_time(child['started_at']) for child in children.values()), default=None)
        end = max((_time(child['ended_at']) for child in children.values()), default=None)
        rows.append({'source_id': member['source_id'], 'kind': member['kind'], 'period': member['period'],
                     'outcome': member['outcome'], 'b4': not member['child_refs'] and member['outcome'] == 'unchanged',
                     'ran_children': bool(member['child_refs']), 'reused_children': reused,
                     'children': children, 'child_seconds': round(sum(c['seconds'] for c in children.values()), 3),
                     'start': None if start is None else start.isoformat(),
                     'last_child_end': None if end is None else end.isoformat(),
                     'wall_seconds': None, 'engine_seconds': None})
    timed = sorted((row for row in rows if row['start'] is not None), key=lambda row: row['start'])
    for row, following in zip(timed, [*timed[1:], None]):
        end = row['last_child_end'] if following is None else following['start']
        row['wall_seconds'] = _seconds(row['start'], end)
        row['engine_seconds'] = round(row['wall_seconds'] - row['child_seconds'], 3)
    return rows


def tail_seconds(rows: list[dict], ended_at) -> float | None:
    """Seconds from the last child's end to the result's end: the finish step and deferral bookkeeping."""
    ends = [row['last_child_end'] for row in rows if row['last_child_end'] is not None]
    return None if not ends else _seconds(max(ends, key=_time), ended_at)


def summarize_timings(rows: list[dict]) -> dict:
    timed = [row for row in rows if row['wall_seconds'] is not None]
    sources = Counter(row['source_id'] for row in rows if row['ran_children'])
    slowest = max(timed, key=lambda row: row['wall_seconds'], default=None)
    return {'timed_members': len(timed), 'b4_members': sum(row['b4'] for row in rows),
            'repeated_sources': sorted(source for source, count in sources.items() if count > 1),
            'max_member_wall': None if slowest is None else {
                key: slowest[key] for key in ('source_id', 'kind', 'period', 'wall_seconds')}}


def run_timing(store, objects, refs: list[str], max_wall: float | None) -> dict:
    results = read_results(refs, store, objects)
    attempts = child_attempts([row.to_mapping()['value'] for row in store.scan('Attempt', {})])
    runs, breaches = [], []
    for result in results:
        context = result.context
        members = [{'source_id': member.source.source_id, 'kind': member.source.kind,
                    'period': member.source.period, 'outcome': member.outcome,
                    'child_refs': list(member.child_refs)} for member in result.members]
        rows = member_timings(context.run_id, members, attempts)
        reserve = context.effective_config.get('execution', {}).get('dispatch_reserve_seconds')
        deadline = _time(context.deadline)
        runs.append({'run_id': context.run_id, 'command': context.command, 'outcome': result.outcome,
                     'started_at': _time(context.started_at).isoformat(), 'deadline': deadline.isoformat(),
                     'dispatch_cutoff': None if reserve is None else (deadline - timedelta(seconds=reserve)).isoformat(),
                     'ended_at': _time(result.ended_at).isoformat(), 'tail_seconds': tail_seconds(rows, result.ended_at),
                     'members': rows, **summarize_timings(rows)})
        if max_wall is not None:
            breaches += [{'run_id': context.run_id, 'source_id': row['source_id'], 'period': row['period'],
                          'wall_seconds': row['wall_seconds'], 'limit': max_wall}
                         for row in rows if row['wall_seconds'] is not None and row['wall_seconds'] > max_wall]
    every = [row for run in runs for row in run['members']]
    value = {'format_version': FORMAT, 'kind': 'timing', 'runs': runs,
             'child_call_rows': sum(1 for _ in store.scan('WorkflowChildCall', {})),
             'max_member_wall': summarize_timings(every)['max_member_wall']}
    if max_wall is not None:
        value['breaches'] = breaches
    return value


# ---- command line ---------------------------------------------------------------------------

def _open(config: Path):
    from sec_edgar_ingest.config import load_config
    from sec_edgar_ingest.storage import open_stores
    settings = load_config(config.resolve())
    opened = open_stores(settings, access='operator')
    return settings, opened


def _close(opened) -> None:
    for resource in reversed(opened):
        if resource is not None and hasattr(resource, 'close'):
            resource.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='baseline-campaign')
    commands = parser.add_subparsers(dest='command', required=True)
    files = commands.add_parser('files')
    files.add_argument('--root', type=Path, required=True)
    files.add_argument('--recorded', type=Path)
    audit = commands.add_parser('audit')
    audit.add_argument('--config', type=Path, required=True)
    audit.add_argument('--run-id', action='append', default=[])
    audit.add_argument('--budget', type=Path)
    report = commands.add_parser('coverage')
    report.add_argument('--config', type=Path, required=True)
    report.add_argument('--result', action='append', default=[])
    report.add_argument('--start', required=True)
    report.add_argument('--end', required=True)
    report.add_argument('--open-quarter')
    report.add_argument('--check', choices=CHECKS, default='full')
    timing = commands.add_parser('timing')
    timing.add_argument('--config', type=Path, required=True)
    timing.add_argument('--result', action='append', default=[])
    timing.add_argument('--max-member-wall', type=float)
    args = parser.parse_args(argv)
    if args.command == 'files':
        actual = file_inventory(args.root.resolve())
        value = {'format_version': FORMAT, 'kind': 'files', 'inventory': actual}
        if args.recorded is not None:
            value['comparison'] = compare_inventory(recorded_inventory(json.loads(args.recorded.read_text())), actual)
        sys.stdout.write(dumps(value))
        return 1 if args.recorded is not None and (value['comparison']['missing']
                                                   or value['comparison']['changed_immutable']) else 0
    _, opened = _open(args.config)
    try:
        if args.command == 'audit':
            value = {'format_version': FORMAT, 'kind': 'audit', **transport_audit(opened[0], args.run_id)}
            breaches = None
            if args.budget is not None:
                breaches = check_budget(value, json.loads(args.budget.read_text()))
                value['breaches'] = breaches
            sys.stdout.write(dumps(value))
            return 1 if breaches else 0
        if args.command == 'timing':
            value = run_timing(opened[0], opened[1], args.result, args.max_member_wall)
            sys.stdout.write(dumps(value))
            return 1 if value.get('breaches') else 0
        value = coverage(opened[0], opened[1], args.result, args.start, args.end, args.open_quarter, args.check)
        sys.stdout.write(dumps(value))
        return 0
    finally:
        _close(opened)


if __name__ == '__main__':
    raise SystemExit(main())
