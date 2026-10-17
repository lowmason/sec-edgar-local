"""Alerting telemetry for one fresh workflow result. It never changes the result, stdout or exit code."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from ..etl.history import withdrawal_candidates
from ..etl.state import EtlState
from ..models import error_text, quarter_value
from ..results import exit_code, log_event
from ..storage.contracts import AlreadyExists, CAS_ATTEMPTS, Conflict, ObjectStore, StateStore
from .contracts import WorkflowResult, member_status

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


def last_successful_reconcile(store: StateStore) -> str | None:
    row = store.get(MILESTONE_KIND, RECONCILE_MILESTONE)
    return None if row is None else row.value['ended_at']


def record_reconcile_success(result: WorkflowResult, reference: str, store: StateStore) -> None:
    """Advance the reconcile milestone to an exit-0 reconcile result. It only moves forward and can be
    rebuilt from results."""
    if result.context.command != 'reconcile' or exit_code(result.outcome) != 0:
        return
    value = {'workflow': RECONCILE_MILESTONE, 'ended_at': result.ended_at, 'result_ref': reference}
    for _ in range(CAS_ATTEMPTS):
        current = store.get(MILESTONE_KIND, RECONCILE_MILESTONE)
        try:
            if current is None:
                store.insert(MILESTONE_KIND, RECONCILE_MILESTONE, value)
            elif datetime.fromisoformat(current.value['ended_at']) < datetime.fromisoformat(result.ended_at):
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
        record_reconcile_success(result, reference, store)
        fields['last_successful_reconcile_at'] = last_successful_reconcile(store)
        fields['pending_approvals'] = sum(entry['status'] == 'pending'
                                          for entry in withdrawal_candidates(objects, EtlState(store)))
    except Exception as error:
        fields['summary_error'] = {'type': type(error).__name__, 'message': error_text(error)}
    log_event(result.context, 'workflow_summary', fields)
