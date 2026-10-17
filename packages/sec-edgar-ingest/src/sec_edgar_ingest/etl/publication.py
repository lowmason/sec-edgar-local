"""Per-quarter publication by validated candidate and bounded pointer CAS."""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import Settings
from ..models import RunContext, quarter_for, quarter_value
from ..storage.contracts import AlreadyExists, BoundaryObserver, CAS_ATTEMPTS, Conflict, ObjectStore, observe
from .catalog import build_candidate, select_sources, source_fingerprint
from .contracts import Candidate, GenerationManifest, ObservationRef, PublicationResult
from .manifest import validate_candidate
from .reader import capture_from_pointer, capture_quarter, validated_manifest
from .state import EtlState
from .transform import _read_manifest, _validate_context


class PublicationRepairError(RuntimeError):
    """Ancillary work failed after this exact publication was already committed."""

    def __init__(self, result: PublicationResult, error: Exception):
        super().__init__(f'committed quarter {result.quarter} repair incomplete: {error}')
        self.result = result
        self.error = error


def _now() -> datetime:
    """Patchable UTC clock; production uses the context's real bounded deadline."""
    return datetime.now(timezone.utc)


def pointer_value(candidate: Candidate) -> dict[str, object]:
    return {'quarter': candidate.manifest.quarter, 'generation_id': candidate.manifest.generation_id,
            'manifest_ref': candidate.manifest_ref, 'manifest_sha256': candidate.manifest_sha256,
            'manifest_bytes': candidate.manifest_bytes, 'source_fingerprint': candidate.manifest.source_fingerprint}


def unchanged_inputs(quarter: str, existing: GenerationManifest | None,
                     incoming: tuple[ObservationRef, ...], context: RunContext) -> bool:
    if existing is None or (existing.parser_version, existing.schema_version) != (context.parser_version, context.schema_version):
        return False
    selected = select_sources(existing.sources, incoming)
    if any((ref.parser_version, ref.schema_version) != (context.parser_version, context.schema_version) for ref in selected):
        return False
    authorities = [ref for ref in selected if ref.source.kind == 'quarterly' and ref.source.period == quarter]
    if len(authorities) > 1:
        raise Conflict('multiple quarterly sources claim the same membership period')
    mode = 'open' if quarter == quarter_for(context.pinned_on) else 'closed'
    return source_fingerprint(quarter, selected, mode=mode,
                              membership_source=authorities[0] if authorities else None,
                              retained_from_generation=existing.retained_from_generation) == existing.source_fingerprint


def repair_publication(quarter: str, objects: ObjectStore, state: EtlState) -> None:
    capture = capture_quarter(quarter, objects, state)
    if capture is not None:
        state.record_publication(validated_manifest(capture, objects))


def _conflict_result(quarter: str, conflicts: int, candidate: Candidate | None = None) -> PublicationResult:
    # A conflict manifest names attempted evidence, never committed output.
    return PublicationResult(quarter, 'publication_conflict', None,
                             candidate.manifest_ref if candidate else None, None, conflicts)


def publish_quarter(quarter: str, incoming: tuple[ObservationRef, ...], context: RunContext,
                    settings: Settings, objects: ObjectStore, state: EtlState, *,
                    observer: BoundaryObserver | None = None) -> PublicationResult:
    quarter_value(quarter)
    if _now() >= context.deadline:
        return _conflict_result(quarter, 0)
    _validate_context(context, settings)
    if quarter_value(quarter) > quarter_value(quarter_for(context.pinned_on)):
        raise ValueError('future output quarter is not configured')
    for ref in incoming:
        durable, _ = _read_manifest(ref.manifest_ref, objects)
        if durable != ref:
            raise Conflict('incoming reference differs from immutable observation manifest')
    candidate = None
    for conflicts in range(CAS_ATTEMPTS):
        if conflicts and _now() >= context.deadline:
            return _conflict_result(quarter, conflicts, candidate)
        current = state.pointer(quarter)
        previous = capture_from_pointer(current) if current is not None else None
        if previous is not None and previous.quarter != quarter:
            raise ValueError('pointer belongs to another quarter')
        existing = validated_manifest(previous, objects) if previous else None
        if existing and existing.source_fingerprint != current.value['source_fingerprint']:
            raise Conflict('pointer source fingerprint differs from captured manifest')
        if unchanged_inputs(quarter, existing, incoming, context):
            result = PublicationResult(quarter, 'unchanged', previous.generation_id, previous.manifest_ref, None, conflicts)
            try:
                state.record_publication(existing)
            except Exception as error:
                raise PublicationRepairError(result, error) from error
            return result
        try:
            candidate = build_candidate(quarter, previous, incoming, context, settings, objects, state, observer=observer)
        except TimeoutError:
            if _now() >= context.deadline:
                return _conflict_result(quarter, conflicts, candidate)
            raise
        validate_candidate(candidate, objects)
        if candidate.manifest.gate == 'awaiting_approval':
            state.record_candidate(candidate)
            return PublicationResult(quarter, 'awaiting_approval', None, None, candidate.candidate_ref, conflicts)
        observe(observer, 'publication.before_pointer')
        if _now() >= context.deadline:
            return _conflict_result(quarter, conflicts, candidate)
        try:
            state.commit_pointer(quarter, pointer_value(candidate), current)
        except (AlreadyExists, Conflict):
            observe(observer, 'publication.cas_lost')
            continue
        result = PublicationResult(quarter, 'published', candidate.manifest.generation_id, candidate.manifest_ref, None, conflicts)
        try:
            observe(observer, 'publication.after_pointer')
            state.record_publication(candidate.manifest)
            observe(observer, 'publication.after_repair')
        except Exception as error:
            raise PublicationRepairError(result, error) from error
        return result
    return _conflict_result(quarter, CAS_ATTEMPTS, candidate)
