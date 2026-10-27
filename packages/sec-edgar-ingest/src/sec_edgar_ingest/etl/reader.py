"""Hash-bound quarter captures and fully validated, disk-backed readers."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from ..models import Versioned, canonical_json, parse_json, require_hash
from ..storage.contracts import Conflict, ObjectStore
from .contracts import Candidate, GenerationCapture, GenerationManifest, IndexRow
from .manifest import (check_candidate_integrity, gate_ref, generation_base, iter_file_rows, read_approval,
                       read_manifest, validate_candidate)
from .state import EtlState, POINTER_FIELDS


def capture_from_pointer(row: Versioned) -> GenerationCapture:
    value = row.to_mapping()['value']
    if set(value) != POINTER_FIELDS:
        raise ValueError('pointer must contain the exact quarter publication fields')
    require_hash(value['source_fingerprint'], 'source_fingerprint')
    capture = GenerationCapture.from_mapping({key: item for key, item in value.items() if key != 'source_fingerprint'})
    if capture.manifest_ref != generation_base(capture.quarter, capture.generation_id) + '/manifest.json':
        raise ValueError('pointer manifest address differs from exact generation')
    return capture


def _pinned_manifest(capture: GenerationCapture, objects: ObjectStore, check) -> GenerationManifest:
    manifest = read_manifest(capture, objects)
    candidate = Candidate(manifest, capture.manifest_ref, capture.manifest_sha256,
                          capture.manifest_bytes, gate_ref(manifest))
    if manifest.gate != 'clear':
        # Cheap binding check first; the check then proves the files and the gate record.
        try:
            read_approval(candidate, objects)
        except FileNotFoundError as error:
            raise ValueError('an awaiting-approval generation cannot be current without its exact approval') from error
    check(candidate, objects)
    return manifest


def validated_manifest(capture: GenerationCapture, objects: ObjectStore) -> GenerationManifest:
    """The full content check: public readers, approval and rollback keep it (C3)."""
    return _pinned_manifest(capture, objects, validate_candidate)


def checked_manifest(capture: GenerationCapture, objects: ObjectStore) -> GenerationManifest:
    """C1 for engine paths: exact manifest and file hashes, and the approval binding; no row is read."""
    return _pinned_manifest(capture, objects, check_candidate_integrity)


def capture_quarter(quarter: str, objects: ObjectStore, state: EtlState) -> GenerationCapture | None:
    pointer = state.pointer(quarter)
    if pointer is None:
        return None
    capture = capture_from_pointer(pointer)
    if capture.quarter != quarter:
        raise ValueError('pointer belongs to another quarter')
    manifest = checked_manifest(capture, objects)
    if manifest.source_fingerprint != pointer.value['source_fingerprint']:
        raise Conflict('pointer source fingerprint differs from captured manifest')
    return capture


def read_quarter(capture: GenerationCapture, objects: ObjectStore) -> Iterator[IndexRow]:
    manifest = validated_manifest(capture, objects)
    # Finish all remote reads before exposing a row, including late count failures.
    # The disk spool keeps this guarantee independent of quarter size.
    with TemporaryDirectory(prefix='sec-quarter-read-') as directory, closing(sqlite3.connect(Path(directory) / 'rows.sqlite')) as db:
        db.execute('CREATE TABLE rows(payload BLOB)')
        for ref in manifest.files:
            if ref.role == 'data':
                with closing(iter_file_rows(ref, objects)) as rows:
                    for value in rows:
                        db.execute('INSERT INTO rows VALUES(?)', (canonical_json(IndexRow(**value).to_mapping()),))
        for (payload,) in db.execute('SELECT payload FROM rows ORDER BY rowid'):
            yield IndexRow.from_mapping(parse_json(payload))
