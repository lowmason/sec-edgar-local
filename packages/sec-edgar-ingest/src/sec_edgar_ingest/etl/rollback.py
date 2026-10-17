"""Explicit recorded rollback of one quarter pointer to an earlier generation in its exact lineage."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice

from ..models import Error, Record, canonical_json, parse_json, quarter_value, require_hash, validate_record_fields
from ..storage.contracts import AlreadyExists, BoundaryObserver, CAS_ATTEMPTS, Conflict, ObjectStore, observe
from .contracts import MAX_OPERATOR_CHARS, MAX_REASON_CHARS, GenerationCapture, QuarterRollback, require_line
from .history import lineage
from .reader import capture_from_pointer, validated_manifest
from .state import EtlState

ROLLBACK_OUTCOMES = ('success', 'unchanged', 'rollback_refused', 'rollback_stale')


class RollbackRefused(ValueError):
    """The target is not an earlier generation in the active lineage; nothing was written."""


@dataclass(frozen=True, slots=True)
class RollbackOutcome(Record):
    outcome: str
    active: GenerationCapture | None
    rollback: QuarterRollback | None
    error: Error | None

    def __post_init__(self):
        validate_record_fields(self)
        if self.outcome not in ROLLBACK_OUTCOMES:
            raise ValueError('unsupported rollback outcome')
        if self.outcome in ('success', 'unchanged'):
            valid = (self.active is not None and self.error is None
                     and (self.rollback is not None) == (self.outcome == 'success'))
        else:
            valid = (self.active is None and self.rollback is None
                     and self.error is not None and self.error.code == self.outcome)
        if not valid:
            raise ValueError('rollback outcome evidence differs from its outcome')


def _now() -> datetime:
    """Patchable UTC rollback clock."""
    return datetime.now(timezone.utc)


def _failed(outcome: str, message: str, **details: str) -> RollbackOutcome:
    return RollbackOutcome(outcome, None, None, Error(outcome, message, False, None, details))


def rollback_ref(record: QuarterRollback) -> str:
    year, ordinal = quarter_value(record.quarter)
    return f'approvals/sec/filing_index/year={year}/quarter={ordinal}/rollback={record.rollback_id}/rollback.json'


def _ancestor(active: GenerationCapture, generation_id: str, objects: ObjectStore) -> GenerationCapture:
    for capture, _ in islice(lineage(active, objects), 1, None):
        if capture.generation_id == generation_id:
            return capture
    raise RollbackRefused("target is not an earlier generation in this quarter's exact lineage")


def _store_rollback(record: QuarterRollback, objects: ObjectStore) -> QuarterRollback:
    ref = rollback_ref(record)
    try:
        objects.put_once(ref, canonical_json(record.to_mapping()))
    except Conflict:
        pass  # The first record of this exact attempted move wins; it is re-validated below.
    body = objects.read(ref)
    stored = QuarterRollback.from_mapping(parse_json(body))
    if canonical_json(stored.to_mapping()) != body or rollback_ref(stored) != ref or (
            stored.to_manifest_ref, stored.to_manifest_sha256, stored.to_manifest_bytes) != (
            record.to_manifest_ref, record.to_manifest_sha256, record.to_manifest_bytes):
        raise ValueError('stored rollback differs from this exact pointer move')
    return stored


def rollback(quarter: str, from_generation: str, to_generation: str, operator: str, reason: str,
             objects: ObjectStore, state: EtlState, *, observer: BoundaryObserver | None = None) -> RollbackOutcome:
    try:
        quarter_value(quarter)
        require_hash(from_generation, 'from_generation')
        require_hash(to_generation, 'to_generation')
        if from_generation == to_generation:
            raise ValueError('rollback requires two different generations')
        require_line(operator, 'operator', MAX_OPERATOR_CHARS)
        require_line(reason, 'reason', MAX_REASON_CHARS)
    except ValueError as error:
        return _failed('rollback_refused', str(error))
    for _ in range(CAS_ATTEMPTS):
        current = state.pointer(quarter)
        if current is None:
            return _failed('rollback_refused', 'quarter has no active generation')
        active = capture_from_pointer(current)
        if active.generation_id == to_generation:
            return RollbackOutcome('unchanged', active, None, None)
        if active.generation_id != from_generation:
            return _failed('rollback_stale', 'active generation is not the rollback source',
                           active_generation_id=active.generation_id, from_generation_id=from_generation)
        try:
            target = _ancestor(active, to_generation, objects)
        except RollbackRefused as error:
            return _failed('rollback_refused', str(error))
        manifest = validated_manifest(target, objects)
        stored = _store_rollback(QuarterRollback(
            quarter, from_generation, to_generation, current.version, target.manifest_ref,
            target.manifest_sha256, target.manifest_bytes, operator, reason, _now()), objects)
        state.record_rollback(stored)
        observe(observer, 'rollback.before_pointer')
        try:
            state.commit_pointer(quarter, {**target.to_mapping(), 'source_fingerprint': manifest.source_fingerprint},
                                 current)
        except (AlreadyExists, Conflict):
            observe(observer, 'rollback.cas_lost')
            continue
        observe(observer, 'rollback.after_pointer')
        return RollbackOutcome('success', target, stored, None)
    raise Conflict('rollback exhausted conditional pointer races')
