"""Read-only Stage 2 baseline-campaign evidence: file inventory, transport audit and coverage.

Run under the selected release interpreter with -I -B -X pycache_prefix=/dev/null. The tool opens
the store with operator access, sends no request and writes nothing under the store root. It uses
release fc68adef... internals (workflow result validation, ETL readers); re-verify it before use
with any other release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

FORMAT = 'sec-baseline-campaign-evidence-v1'
BUDGET_FORMAT = 'sec-baseline-campaign-budget-v1'
MUTABLE_STATE = frozenset({'state.sqlite3', 'state.sqlite3-wal', 'state.sqlite3-shm'})
# SQLite creates and deletes its WAL and shared-memory files itself; the database file stays strict.
TRANSIENT_STATE = MUTABLE_STATE - {'state.sqlite3'}
COVERED = frozenset({'covered', 'covered_open_quarter'})
RANK = {'complete': 0, 'pending': 1, 'failed': 2}
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
            or view['gate'] != 'clear' or view['row_count'] == 0 or view['validated_rows'] != view['row_count']):
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


def quarter_view(quarter: str, objects, state) -> dict:
    from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter, validated_manifest
    try:
        capture = capture_quarter(quarter, objects, state)
        if capture is None:
            return {'quarter': quarter, 'status': 'unpublished'}
        manifest = validated_manifest(capture, objects)
        rows = sum(1 for _ in read_quarter(capture, objects))
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


def coverage(store, objects, refs: list[str], start: str, end: str, open_quarter: str | None) -> dict:
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
    views = {quarter: quarter_view(quarter, objects, state) for quarter in sorted({*requested, *published})}
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
    return {'format_version': FORMAT, 'kind': 'coverage', 'requested': {'start': start, 'end': end,
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
        value = coverage(opened[0], opened[1], args.result, args.start, args.end, args.open_quarter)
        sys.stdout.write(dumps(value))
        return 0
    finally:
        _close(opened)


if __name__ == '__main__':
    raise SystemExit(main())
