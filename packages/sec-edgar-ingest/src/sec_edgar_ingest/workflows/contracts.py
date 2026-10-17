"""Strict workflow captures and source-level coverage reduction."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from ..etl.commands import validate_workset_ref
from ..etl.contracts import PublicationResult
from ..models import (
    Error, Record, RunContext, Source, quarter_value, require_hash,
    require_number, require_utc, safe_relative_path, validate_record_fields,
)
from ..results import exit_code

COMPLETE = frozenset(('success', 'unchanged', 'no_new_sources'))
PENDING = frozenset(('pending', 'deferred', 'throttled', 'awaiting_approval'))
FATAL = ('access_blocked', 'ownership_lost', 'state_conflict', 'internal_error')
FORMAT_VERSION = 'sec-workflow-result-v1'
WORKFLOW_COMMANDS = ('backfill', 'daily', 'reconcile')
WORKFLOW_PRIORITY = {'backfill': 'backfill', 'daily': 'daily', 'reconcile': 'reconciliation'}
SUPPORTED_PARSERS = frozenset((
    'sec-index-parser-v1', 'fixture-index-parser-v1', 'fixture-index-parser-v2',
))
SOURCE_WORKSET_REF = re.compile(r'worksets/sec/source/sha256=[0-9a-f]{64}/workset\.json\Z')
CHILD_RESULT_REF = re.compile(r'runs/sec/[^/]+/(collect|transform|publish)/[^/]+/result\.json\Z')


@dataclass(frozen=True, slots=True)
class CompletionEvaluation(Record):
    complete: bool
    capture: Mapping[str, object] | None
    obligations: tuple[Mapping[str, object], ...]
    gaps: tuple[Error, ...]

    def __post_init__(self):
        validate_record_fields(self)
        if self.complete and (self.capture is None or self.obligations or self.gaps):
            raise ValueError('completion requires capture and no unresolved obligations/gaps')


@dataclass(frozen=True, slots=True)
class MemberResult(Record):
    member_id: str
    source: Source
    parent_ref: str
    snapshot_ref: str | None
    transformed_ref: str | None
    child_refs: tuple[str, ...]
    outcome: str
    downloaded: bool
    transformed: bool
    quarantined: bool
    quarters: tuple[PublicationResult, ...]
    gaps: tuple[Error, ...]
    parser_version: str
    schema_version: str

    def __post_init__(self):
        validate_record_fields(self)
        require_hash(self.member_id, 'member_id')
        member_status(self.outcome)
        if SOURCE_WORKSET_REF.fullmatch(self.parent_ref) is None:
            raise ValueError('invalid member parent reference')
        for ref, kind in ((self.snapshot_ref, 'snapshot'), (self.transformed_ref, 'transformed')):
            if ref is not None:
                validate_workset_ref(ref, kind)
        for ref in self.child_refs:
            if CHILD_RESULT_REF.fullmatch(ref) is None:
                raise ValueError('invalid child result reference')
            safe_relative_path(ref, 'child_ref')
        if self.schema_version != 'sec-index-v1' or self.parser_version not in SUPPORTED_PARSERS:
            raise ValueError('unsupported member processing versions')
        if len({quarter.quarter for quarter in self.quarters}) != len(self.quarters):
            raise ValueError('duplicate member quarter results')
        if self.outcome in COMPLETE and (
            not self.snapshot_ref or not self.transformed_ref
            or any(quarter.outcome not in ('published', 'unchanged') for quarter in self.quarters)
        ):
            raise ValueError('complete member lacks successful ETL/publication captures')
        if self.quarantined and (self.transformed or member_status(self.outcome) != 'failed'):
            raise ValueError('quarantined member requires failed status and no accepted transform')


@dataclass(frozen=True, slots=True)
class WorkflowResult(Record):
    format_version: str
    context: RunContext
    intent: Mapping[str, object]
    source_workset_ref: str | None
    requested_quarters: tuple[str, ...]
    directories: tuple[Mapping[str, object], ...]
    members: tuple[MemberResult, ...]
    gaps: tuple[Error, ...]
    boundary_before: str | None
    boundary_after: str | None
    outcome: str
    counts: Mapping[str, int]
    ended_at: str

    def __post_init__(self):
        validate_record_fields(self)
        if self.format_version != FORMAT_VERSION:
            raise ValueError('unsupported workflow result version')
        workflow_path(self.context)
        ended = datetime.fromisoformat(self.ended_at)
        require_utc(ended, 'ended_at')
        if ended < self.context.started_at:
            raise ValueError('workflow ended before start')
        if len({member.member_id for member in self.members}) != len(self.members):
            raise ValueError('duplicate workflow member IDs')
        if self.source_workset_ref is not None and SOURCE_WORKSET_REF.fullmatch(self.source_workset_ref) is None:
            raise ValueError('invalid workflow discovery reference')
        for key in ('discovered_sources', 'unresolved_before'):
            if key not in self.intent:
                raise ValueError(f'workflow intent lacks {key}')
            require_number(self.intent[key], key, integer=True)
        already = self.intent.get('already_complete_sources', ())
        if not isinstance(already, tuple):
            raise ValueError('already-complete sources must be an array')
        outcome, counts = summarize(
            self.members, self.gaps, self.intent['discovered_sources'],
            self.intent['unresolved_before'], self.context.command, already,
        )
        if self.outcome != outcome or self.to_mapping()['counts'] != counts:
            raise ValueError('workflow counters/outcome disagree with exact members/gaps')
        ordered = tuple(sorted(self.requested_quarters, key=quarter_value))
        if ordered != self.requested_quarters or len(set(ordered)) != len(ordered):
            raise ValueError('invalid requested quarter ordering')
        for value in (self.boundary_before, self.boundary_after):
            if value is not None and date.fromisoformat(value).isoformat() != value:
                raise ValueError('invalid discovery boundary date')


def member_status(outcome: str) -> str:
    exit_code(outcome)
    return 'complete' if outcome in COMPLETE else 'pending' if outcome in PENDING else 'failed'


def _gap_derived_from_quarantine(gap: Error, quarantined_ids: set[str]) -> bool:
    if gap.code != 'baseline_publication_missing' or gap.details.get('coverage_cause') != 'selected_source_quarantine':
        return False
    identities = gap.details.get('source_ids')
    if not isinstance(identities, tuple) or not identities or any(not isinstance(identity, str) for identity in identities):
        return False
    attributed = set(identities)
    return (
        len(attributed) == len(identities) and attributed <= quarantined_ids
        and (gap.source_id is None or gap.source_id in attributed)
    )


def summarize(
    members: tuple[MemberResult, ...], gaps: tuple[Error, ...], discovered_new: int,
    unresolved_before: int = 0, command: str = 'daily',
    already_complete_sources: tuple[str, ...] = (),
) -> tuple[str, dict[str, int]]:
    for identity in already_complete_sources:
        require_hash(identity, 'already_complete_source')
    if len(set(already_complete_sources)) != len(already_complete_sources) or set(already_complete_sources) & {member.source.source_id for member in members}:
        raise ValueError('already-complete identities overlap or duplicate selected sources')
    grouped = {identity: 'complete' for identity in already_complete_sources}
    rank = {'complete': 0, 'pending': 1, 'failed': 2}
    for member in members:
        identity = member.source.source_id
        status = member_status(member.outcome)
        if identity not in grouped or rank[status] > rank[grouped[identity]]:
            grouped[identity] = status
    states = Counter(grouped.values())
    counts = {name + '_sources': states[name] for name in ('complete', 'pending', 'failed')}
    quarantined_ids = {member.source.source_id for member in members if member.quarantined}
    counts.update(
        discovered_sources=discovered_new,
        downloaded_sources=len({member.source.source_id for member in members if member.downloaded}),
        transformed_sources=len({member.source.source_id for member in members if member.transformed}),
        quarantined_sources=len(quarantined_ids),
    )
    quarters = Counter(quarter.outcome for member in members for quarter in member.quarters)
    counts.update(
        published_quarters=quarters['published'], unchanged_quarters=quarters['unchanged'],
        awaiting_approval_quarters=quarters['awaiting_approval'],
    )
    outcomes = {member.outcome for member in members} | {gap.code for gap in gaps}
    fatal = next((outcome for outcome in FATAL if outcome in outcomes), None)
    if fatal:
        return fatal, counts
    all_quarantined = bool(members) and not already_complete_sources and all(
        member.quarantined and member_status(member.outcome) == 'failed' for member in members
    )
    # Retained baseline gaps may derive solely from checked whole-source refusals.
    if all_quarantined and all(_gap_derived_from_quarantine(gap, quarantined_ids) for gap in gaps):
        return 'quarantined', counts
    if gaps or states['failed']:
        return 'incomplete', counts
    if states['pending']:
        unresolved = {member.outcome for member in members if member_status(member.outcome) == 'pending'}
        # Gate-only unresolved work is the distinct gated outcome, even beside completed sources.
        if unresolved == {'awaiting_approval'}:
            return 'awaiting_approval', counts
        return ('incomplete' if states['complete'] else 'pending'), counts
    if not members:
        return ('no_new_sources' if command == 'daily' and not discovered_new and not unresolved_before else 'unchanged'), counts
    if command == 'daily' and not discovered_new and not unresolved_before and not counts['published_quarters']:
        return 'no_new_sources', counts
    return ('success' if counts['published_quarters'] else 'unchanged'), counts


def workflow_path(context: RunContext) -> str:
    if context.command not in WORKFLOW_COMMANDS:
        raise ValueError('workflow command required')
    for name in ('run_id', 'execution_id', 'attempt_id'):
        if '/' in safe_relative_path(getattr(context, name), name):
            raise ValueError('workflow IDs require one segment')
    return f'runs/sec/{context.run_id}/{context.command}/{context.attempt_id}/result.json'
