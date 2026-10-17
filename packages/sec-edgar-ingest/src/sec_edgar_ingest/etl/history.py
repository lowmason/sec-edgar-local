"""Read-only withdrawal approval requests and per-quarter generation lineage."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing

from ..models import quarter_value
from ..state import AcquisitionState
from ..storage.contracts import Conflict, ObjectStore
from .approval import superseding
from .contracts import Candidate, FileRef, GenerationCapture, GenerationManifest, IndexRow
from .manifest import gate_payload, gate_ref, iter_file_rows, read_approval, read_manifest, retained_base
from .reader import capture_from_pointer, capture_quarter
from .state import EtlState

COUNTS = ('row_count', 'added', 'updated', 'withdrawn', 'unresolved_absence', 'provenance_refreshed')


def _changes(manifest: GenerationManifest) -> FileRef:
    return next(ref for ref in manifest.files if ref.role == 'changes')


def lineage(capture: GenerationCapture | None,
            objects: ObjectStore) -> Iterator[tuple[GenerationCapture, GenerationManifest]]:
    """Newest-first (capture, manifest) pairs through each generation's exact retained base."""
    seen = set()
    while capture is not None:
        if capture.generation_id in seen:
            raise Conflict('generation lineage repeats a generation')
        seen.add(capture.generation_id)
        manifest = read_manifest(capture, objects)
        yield capture, manifest
        capture = retained_base(manifest, objects)


def quarter_history(quarter: str, objects: ObjectStore, state: EtlState) -> tuple[dict[str, object], ...]:
    """Newest-first lineage from the active pointer, with the approval of each approved gated generation."""
    entries = []
    for capture, manifest in lineage(capture_quarter(quarter, objects, state), objects):
        approval = None
        if manifest.gate == 'awaiting_approval':
            candidate = Candidate(manifest, capture.manifest_ref, capture.manifest_sha256,
                                  capture.manifest_bytes, gate_ref(manifest))
            approval = read_approval(candidate, objects).to_mapping()
        entries.append({'generation_id': manifest.generation_id, 'base_generation_id': manifest.base_generation_id,
                        'manifest_ref': capture.manifest_ref, 'quarter_mode': manifest.quarter_mode,
                        'gate': manifest.gate, **{name: getattr(manifest, name) for name in COUNTS},
                        'membership_sha256': (manifest.membership_source.snapshot.sha256
                                              if manifest.membership_source else None),
                        'changes': _changes(manifest).to_mapping(), 'approval': approval})
    return tuple(entries)


def withdrawal_candidates(objects: ObjectStore, state: EtlState) -> tuple[dict[str, object], ...]:
    """Each recorded gated candidate as an approval request with its current status."""
    acquisition, entries = AcquisitionState(state.store), []
    for row in state.store.scan('Candidate', {}):
        candidate = Candidate.from_mapping(row.to_mapping()['value'])
        manifest = candidate.manifest
        capture = GenerationCapture(manifest.quarter, manifest.generation_id, candidate.manifest_ref,
                                    candidate.manifest_sha256, candidate.manifest_bytes)
        if (read_manifest(capture, objects) != manifest or candidate.candidate_ref != gate_ref(manifest)
                or objects.read(candidate.candidate_ref) != gate_payload(candidate)):
            raise Conflict('candidate index differs from its immutable manifest and gate record')
        pointer = state.pointer(manifest.quarter)
        active = None if pointer is None else capture_from_pointer(pointer).generation_id
        source = manifest.membership_source
        observed = acquisition.get_source(source.source.source_id)
        observed = None if observed is None else observed.to_mapping()['value']
        status = ('active' if active == manifest.generation_id
                  else 'stale' if active != manifest.base_generation_id
                  else 'superseded' if superseding(candidate, observed) is not None else 'pending')
        changes = _changes(manifest)
        with closing(iter_file_rows(changes, objects)) as rows:
            withdrawn = [IndexRow(**value['before']).to_mapping() for value in rows
                         if value['change_type'] == 'withdrawn']
        entries.append({'quarter': manifest.quarter, 'generation_id': manifest.generation_id,
                        'base_generation_id': manifest.base_generation_id,
                        'quarterly_sha256': source.snapshot.sha256, 'candidate_ref': candidate.candidate_ref,
                        'changes': changes.to_mapping(), 'withdrawn': withdrawn, 'status': status,
                        'approved': state.approval(manifest.generation_id) is not None,
                        'latest_observed_sha256': None if observed is None else observed['latest_downloaded_snapshot'],
                        'latest_observed_at': None if observed is None else observed['latest_received_at']})
    return tuple(sorted(entries, key=lambda entry: (quarter_value(entry['quarter']), entry['generation_id'])))
