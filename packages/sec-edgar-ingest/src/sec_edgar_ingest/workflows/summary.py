"""Alerting telemetry for one fresh workflow result. It never changes the result, stdout or exit code."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from ..etl.history import withdrawal_candidates
from ..etl.state import EtlState
from ..models import canonical_json, error_text, parse_json, quarter_value
from ..results import exit_code, log_event
from ..storage.contracts import AlreadyExists, CAS_ATTEMPTS, Conflict, ObjectStore, StateStore
from .contracts import LOCAL_CONTRACT, WorkflowResult, member_status, require_contract, workflow_path

MILESTONE_KIND = 'WorkflowMilestone'
RECONCILE_MILESTONE = 'reconcile'
SUMMARY_FIELDS = frozenset({'result_ref', 'command', 'outcome', 'counts', 'member_outcomes', 'gap_codes',
                            'discovery_complete', 'boundary_after', 'oldest_unresolved_period',
                            'pending_approvals', 'last_successful_reconcile_at', 'summary_error'})


def _period_start(period: str) -> date:
    if 'Q' in period:
        year, ordinal = quarter_value(period)
        return date(year, 3 * ordinal - 2, 1)
    return date.fromisoformat(period)


def describe(result: WorkflowResult) -> dict[str, object]:
    """Counts by name and discovery facts, read from the result alone."""
    unresolved = [member.source.period for member in result.members if member_status(member.outcome) != 'complete']
    codes = Counter(gap.code for gap in result.gaps)
    codes.update(gap.code for member in result.members for gap in member.gaps)
    return {'member_outcomes': dict(sorted(Counter(member.outcome for member in result.members).items())),
            'gap_codes': dict(sorted(codes.items())),
            'discovery_complete': bool(result.directories) and all(
                directory['outcome'] != 'discovery_failed' for directory in result.directories),
            'oldest_unresolved_period': min(unresolved, key=_period_start, default=None)}


def _validated_milestone(value, store: StateStore, objects: ObjectStore) -> WorkflowResult:
    require_contract(value)
    if set(value) != {'contract_version', 'workflow', 'ended_at', 'result_ref'} or value['workflow'] != RECONCILE_MILESTONE:
        raise ValueError('reconcile milestone fields differ')
    reference = value['result_ref']
    if not isinstance(reference, str):
        raise ValueError('reconcile milestone reference must be text')
    from ..models import safe_relative_path
    safe_relative_path(reference, 'reconcile milestone reference')
    body = objects.read(reference)
    decoded = parse_json(body)
    if canonical_json(decoded) != body:
        raise ValueError('reconcile milestone result bytes are not canonical')
    result = WorkflowResult.from_mapping(decoded)
    if (workflow_path(result.context) != reference or result.context.command != 'reconcile'
            or exit_code(result.outcome) != 0 or result.ended_at != value['ended_at']):
        raise ValueError('reconcile milestone differs from successful local result')
    from .results import _validate_report
    _validate_report(result, store, objects)
    return result


def last_successful_reconcile(store: StateStore, objects: ObjectStore) -> str | None:
    row = store.get(MILESTONE_KIND, RECONCILE_MILESTONE)
    return None if row is None else _validated_milestone(row.to_mapping()['value'], store, objects).ended_at


def record_reconcile_success(result: WorkflowResult, reference: str, store: StateStore, objects: ObjectStore) -> None:
    """Advance the milestone only after validating its exact local result authority."""
    if result.context.command != 'reconcile' or exit_code(result.outcome) != 0:
        return
    value = {'contract_version': LOCAL_CONTRACT, 'workflow': RECONCILE_MILESTONE,
             'ended_at': result.ended_at, 'result_ref': reference}
    if _validated_milestone(value, store, objects) != result:
        raise ValueError('reconcile milestone proposed result differs from immutable authority')
    for _ in range(CAS_ATTEMPTS):
        current = store.get(MILESTONE_KIND, RECONCILE_MILESTONE)
        previous = None if current is None else _validated_milestone(current.to_mapping()['value'], store, objects)
        try:
            if current is None:
                store.insert(MILESTONE_KIND, RECONCILE_MILESTONE, value)
            elif datetime.fromisoformat(previous.ended_at) < datetime.fromisoformat(result.ended_at):
                store.replace(MILESTONE_KIND, RECONCILE_MILESTONE, value, current.version)
            return
        except (AlreadyExists, Conflict):
            continue
    raise Conflict('reconcile milestone exhausted conditional races')


def emit_summary(result: WorkflowResult, reference: str, objects: ObjectStore, store: StateStore) -> None:
    """Log one `workflow_summary`. A failure of any extra lands in `summary_error`, never in the outcome."""
    fields = {'result_ref': reference, 'command': result.context.command, 'outcome': result.outcome,
              'counts': dict(result.counts), 'member_outcomes': None, 'gap_codes': None,
              'discovery_complete': None, 'boundary_after': result.boundary_after,
              'oldest_unresolved_period': None, 'pending_approvals': None,
              'last_successful_reconcile_at': None, 'summary_error': None}
    try:
        fields.update(describe(result))
        record_reconcile_success(result, reference, store, objects)
        fields['last_successful_reconcile_at'] = last_successful_reconcile(store, objects)
        fields['pending_approvals'] = sum(entry['status'] == 'pending'
                                          for entry in withdrawal_candidates(objects, EtlState(store)))
    except Exception as error:
        fields['summary_error'] = {'type': type(error).__name__, 'message': error_text(error)}
    log_event(result.context, 'workflow_summary', fields)
