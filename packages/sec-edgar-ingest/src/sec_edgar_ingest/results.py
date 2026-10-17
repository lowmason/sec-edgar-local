"""Immutable command results precede the ancillary, repairable Attempt record."""
from __future__ import annotations

import sys

from .models import CommandResult, RunContext, canonical_json, safe_relative_path
from .state import AcquisitionState, attempt_key
from .storage.contracts import Conflict, ObjectStore

EXIT_CODES = {
    'success': 0, 'no_new_sources': 0, 'unchanged': 0, 'configuration': 2,
    'approval_refused': 2, 'rollback_refused': 2, 'discovery_failed': 3, 'incomplete': 3, 'pending': 4,
    'retry_exhausted': 5, 'deferred': 5, 'throttled': 5,
    'access_blocked': 6, 'quarantined': 7, 'invalid_source': 7,
    'ownership_lost': 8, 'state_conflict': 9, 'internal_error': 9,
    'publication_conflict': 9, 'awaiting_approval': 10, 'approval_stale': 11, 'rollback_stale': 11,
}


def exit_code(outcome: str) -> int:
    return EXIT_CODES[outcome]


def result_path(context: RunContext) -> str:
    for name in ('run_id', 'command', 'attempt_id'):
        value = safe_relative_path(getattr(context, name), name)
        if '/' in value:
            raise ValueError(f'{name} must be a single path segment')
    if context.command not in ('discover', 'collect', 'transform', 'publish'):
        raise ValueError('results require a supported command')
    return f'runs/sec/{context.run_id}/{context.command}/{context.attempt_id}/result.json'


def write_result(result: CommandResult, objects: ObjectStore, state: AcquisitionState) -> str:
    exit_code(result.outcome)
    row = state.store.get('Attempt', attempt_key(result.context))
    if row is None or row.to_mapping()['value']['context'] != result.context.to_mapping():
        raise Conflict('result requires the exact begun Attempt context')
    finished = row.to_mapping()['value']['result']
    if finished is not None and finished != result.to_mapping():
        raise Conflict('result differs from an already completed Attempt')
    path = result_path(result.context)
    objects.put_once(path, result.to_json())
    state.finish_attempt(result)
    return path


def read_result(path: str, objects: ObjectStore) -> CommandResult:
    safe_relative_path(path, 'result path')
    body = objects.read(path)
    result = CommandResult.from_json(body)
    if result_path(result.context) != path or result.to_json() != body:
        raise Conflict('result bytes or path differ from their canonical command identity')
    exit_code(result.outcome)
    return result


def log_event(context: RunContext, event: str, fields: dict[str, object]) -> None:
    sys.stderr.write(canonical_json({'context': context.to_mapping(), 'event': event, 'fields': fields}).decode() + '\n')
