"""Operator approval of one exact gated withdrawal candidate, committed by pointer CAS."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from ..models import Error, Record, canonical_json, parse_json, quarter_value, require_hash, validate_record_fields
from ..state import AcquisitionState
from ..storage.contracts import AlreadyExists, BoundaryObserver, CAS_ATTEMPTS, Conflict, ObjectStore, observe
from .contracts import (MAX_OPERATOR_CHARS, ApprovalActivation, Candidate, GenerationCapture, PublicationResult,
                        WithdrawalApproval, require_line)
from .manifest import (approval_for, approval_ref, gate_ref, generation_base, read_approval, read_manifest,
                       validate_candidate)
from .publication import pointer_value
from .reader import capture_from_pointer
from .state import EtlState

APPROVAL_OUTCOMES = ('success', 'unchanged', 'approval_refused', 'approval_stale')


class ApprovalRefused(ValueError):
    """The request does not name a valid gated candidate; nothing was written."""


@dataclass(frozen=True, slots=True)
class ApprovalOutcome(Record):
    outcome: str
    publication: PublicationResult | None
    approval: WithdrawalApproval | None
    error: Error | None
    activation: ApprovalActivation | None = None

    def __post_init__(self):
        validate_record_fields(self)
        if self.outcome not in APPROVAL_OUTCOMES:
            raise ValueError('unsupported approval outcome')
        committed = self.outcome in ('success', 'unchanged')
        if committed != (self.publication is not None and self.approval is not None and self.error is None):
            raise ValueError('approval outcome evidence differs from its outcome')
        if not committed and (self.error is None or self.error.code != self.outcome):
            raise ValueError('refused or stale approval requires its matching error')
        if (self.activation is not None) != (self.outcome == 'success'):
            raise ValueError('exactly a successful approval carries the activation that moved the pointer')


def _now() -> datetime:
    """Patchable UTC approval clock."""
    return datetime.now(timezone.utc)


def superseding(candidate: Candidate, observed: Mapping[str, object] | None) -> dict[str, str] | None:
    """The source's latest download (its SourceState value) when strictly later than, and different from,
    the candidate's membership snapshot.

    Such a candidate withdraws rows on the evidence of bytes the SEC no longer serves.
    """
    if observed is None:
        return None
    membership = candidate.manifest.membership_source.snapshot
    latest, at = observed['latest_downloaded_snapshot'], observed['latest_received_at']
    if latest is None or at is None or latest == membership.sha256 or datetime.fromisoformat(at) <= membership.received_at:
        return None
    return {'latest_observed_sha256': latest, 'latest_observed_at': at}


def superseding_download(candidate: Candidate, store) -> dict[str, str] | None:
    """`superseding` against the source's current SourceState row."""
    row = AcquisitionState(store).get_source(candidate.manifest.membership_source.source.source_id)
    return superseding(candidate, None if row is None else row.to_mapping()['value'])


def _refused(message: str) -> ApprovalOutcome:
    return ApprovalOutcome('approval_refused', None, None, Error('approval_refused', message, False, None, {}))


def _committed(outcome: str, candidate: Candidate, approval: WithdrawalApproval, conflicts: int,
               activation: ApprovalActivation | None = None) -> ApprovalOutcome:
    publication = PublicationResult(candidate.manifest.quarter, 'published' if outcome == 'success' else 'unchanged',
                                    candidate.manifest.generation_id, candidate.manifest_ref, None, conflicts)
    return ApprovalOutcome(outcome, publication, approval, None, activation)


def load_candidate(quarter: str, generation_id: str, objects: ObjectStore) -> Candidate:
    """Read one gated candidate from its exact immutable address and validate all of its evidence."""
    manifest_ref = generation_base(quarter, generation_id) + '/manifest.json'
    try:
        body = objects.read(manifest_ref)
    except FileNotFoundError as error:
        raise ApprovalRefused('no generation exists at the exact candidate address') from error
    capture = GenerationCapture(quarter, generation_id, manifest_ref, hashlib.sha256(body).hexdigest(), len(body))
    manifest = read_manifest(capture, objects)
    if manifest.gate != 'awaiting_approval':
        raise ApprovalRefused('generation is not an awaiting-approval candidate')
    candidate = Candidate(manifest, manifest_ref, capture.manifest_sha256, capture.manifest_bytes, gate_ref(manifest))
    validate_candidate(candidate, objects)
    return candidate


def _store_approval(approval: WithdrawalApproval, candidate: Candidate, objects: ObjectStore) -> WithdrawalApproval:
    try:
        objects.put_once(approval_ref(approval.quarter, approval.generation_id), canonical_json(approval.to_mapping()))
    except Conflict:
        pass  # The first approval wins; read_approval re-validates its exact binding.
    return read_approval(candidate, objects)


def activation_ref(record: ApprovalActivation) -> str:
    year, ordinal = quarter_value(record.quarter)
    return (f'approvals/sec/filing_index/year={year}/quarter={ordinal}/generation={record.generation_id}'
            f'/activation={record.activation_id}/activation.json')


def _store_activation(record: ApprovalActivation, objects: ObjectStore) -> ApprovalActivation:
    ref = activation_ref(record)
    try:
        objects.put_once(ref, canonical_json(record.to_mapping()))
    except Conflict:
        pass  # The first record of this exact attempted move wins; it is re-validated below.
    body = objects.read(ref)
    stored = ApprovalActivation.from_mapping(parse_json(body))
    if canonical_json(stored.to_mapping()) != body or activation_ref(stored) != ref or (
            stored.base_generation_id, stored.approval_ref, stored.approval_sha256) != (
            record.base_generation_id, record.approval_ref, record.approval_sha256):
        raise ValueError('stored activation differs from this exact pointer move')
    return stored


def approve(quarter: str, generation_id: str, quarterly_sha256: str, approver: str,
            objects: ObjectStore, state: EtlState, *, observer: BoundaryObserver | None = None) -> ApprovalOutcome:
    try:
        quarter_value(quarter)
        require_hash(generation_id, 'generation_id')
        require_hash(quarterly_sha256, 'quarterly_sha256')
        require_line(approver, 'approver', MAX_OPERATOR_CHARS)
    except ValueError as error:
        return _refused(str(error))
    try:
        candidate = load_candidate(quarter, generation_id, objects)
    except ApprovalRefused as error:
        return _refused(str(error))
    if candidate.manifest.membership_source.snapshot.sha256 != quarterly_sha256:
        return _refused('quarterly hash differs from the candidate membership snapshot')
    pending = approval_for(candidate, approver, _now())
    for conflicts in range(CAS_ATTEMPTS):
        current = state.pointer(quarter)
        active = None if current is None else capture_from_pointer(current).generation_id
        if active == generation_id:
            stored = read_approval(candidate, objects)
            state.record_approval(stored)
            return _committed('unchanged', candidate, stored, conflicts)
        if active != candidate.manifest.base_generation_id:
            return ApprovalOutcome('approval_stale', None, None, Error(
                'approval_stale', 'candidate base generation is no longer active', False, None,
                {'active_generation_id': active, 'base_generation_id': candidate.manifest.base_generation_id}))
        superseded = superseding_download(candidate, state.store)
        if superseded is not None:
            return ApprovalOutcome('approval_stale', None, None, Error(
                'approval_stale', 'a later download of the source supersedes the candidate', False, None,
                {'quarterly_sha256': quarterly_sha256, **superseded}))
        stored = _store_approval(pending, candidate, objects)
        state.record_approval(stored)
        activation = _store_activation(ApprovalActivation(
            quarter, generation_id, candidate.manifest.base_generation_id, current.version,
            approval_ref(quarter, generation_id), hashlib.sha256(canonical_json(stored.to_mapping())).hexdigest(),
            approver, _now()), objects)
        state.record_activation(activation)
        observe(observer, 'approval.before_pointer')
        try:
            state.commit_pointer(quarter, pointer_value(candidate), current)
        except (AlreadyExists, Conflict):
            observe(observer, 'approval.cas_lost')
            continue
        observe(observer, 'approval.after_pointer')
        return _committed('success', candidate, stored, conflicts, activation)
    raise Conflict('approval exhausted conditional pointer races')
