"""Exact immutable generation reads and bounded canonical file verification."""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow.parquet as pq

from ..models import canonical_json, parse_json, quarter_for, quarter_value, require_hash
from ..storage.contracts import Conflict, ObjectStore
from .contracts import (Candidate, FileRef, GenerationCapture, GenerationManifest, IndexRow,
                        ObservationRef, WithdrawalApproval, canonical_schema, change_schema)
from .transform import BATCH_ROWS, _file_identity, _read_manifest, read_observations


def generation_base(quarter: str, generation_id: str) -> str:
    year, ordinal = quarter_value(quarter)
    return f'curated/sec/filing_index/year={year}/quarter={ordinal}/generation={generation_id}'


def source_fingerprint(quarter: str, sources: tuple[ObservationRef, ...], *, mode: str,
                       membership_source: ObservationRef | None,
                       retained_from_generation: str | None) -> str:
    quarter_value(quarter)
    if mode not in ('open', 'closed'):
        raise ValueError('invalid quarter mode')
    payload = {'quarter': quarter, 'sources': [ref.to_mapping() for ref in sorted(sources, key=lambda ref: ref.source.source_id)],
               'mode': mode, 'membership_source': membership_source.to_mapping() if membership_source else None,
               'retained_from_generation': retained_from_generation}
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def generation_identity(quarter: str, base_generation_id: str | None, fingerprint: str) -> str:
    return hashlib.sha256(canonical_json({'quarter': quarter, 'base_generation_id': base_generation_id,
                                        'source_fingerprint': fingerprint})).hexdigest()


def gate_ref(manifest: GenerationManifest) -> str | None:
    if manifest.gate == 'awaiting_approval':
        return f'worksets/sec/candidates/sha256={manifest.generation_id}/candidate.json'
    return None


def gate_payload(candidate: Candidate) -> bytes:
    manifest = candidate.manifest
    return canonical_json({'quarter': manifest.quarter, 'generation_id': manifest.generation_id,
                           'base_generation_id': manifest.base_generation_id,
                           'source_fingerprint': manifest.source_fingerprint,
                           'quarterly_hash': manifest.membership_source.snapshot.sha256,
                           'manifest_ref': candidate.manifest_ref,
                           'change_ref': next(ref.path for ref in manifest.files if ref.role == 'changes'),
                           'gate': manifest.gate})


def approval_ref(quarter: str, generation_id: str) -> str:
    year, ordinal = quarter_value(quarter)
    require_hash(generation_id, 'generation_id')
    return f'approvals/sec/filing_index/year={year}/quarter={ordinal}/generation={generation_id}/approval.json'


def approval_for(candidate: Candidate, approver: str, approved_at: datetime) -> WithdrawalApproval:
    manifest = candidate.manifest
    if manifest.gate != 'awaiting_approval' or candidate.candidate_ref != gate_ref(manifest):
        raise ValueError('approval requires an exact awaiting-approval candidate')
    return WithdrawalApproval(manifest.quarter, manifest.generation_id, manifest.base_generation_id,
                              manifest.source_fingerprint, manifest.membership_source.snapshot.sha256,
                              candidate.candidate_ref, hashlib.sha256(gate_payload(candidate)).hexdigest(),
                              candidate.manifest_ref, candidate.manifest_sha256, candidate.manifest_bytes,
                              approver, approved_at)


def read_approval(candidate: Candidate, objects: ObjectStore) -> WithdrawalApproval:
    """Return the stored approval only when it names this exact candidate, base and source hash."""
    manifest = candidate.manifest
    body = objects.read(approval_ref(manifest.quarter, manifest.generation_id))
    approval = WithdrawalApproval.from_mapping(parse_json(body))
    if canonical_json(approval.to_mapping()) != body:
        raise ValueError('approval must use canonical JSON')
    if approval != approval_for(candidate, approval.approver, approval.approved_at):
        raise ValueError('approval is not bound to this exact candidate, base and source hash')
    return approval


def _validate_identity(manifest: GenerationManifest) -> None:
    fingerprint = source_fingerprint(manifest.quarter, manifest.sources, mode=manifest.quarter_mode,
                                     membership_source=manifest.membership_source,
                                     retained_from_generation=manifest.retained_from_generation)
    if fingerprint != manifest.source_fingerprint or generation_identity(
            manifest.quarter, manifest.base_generation_id, fingerprint) != manifest.generation_id:
        raise ValueError('generation/source-set identity differs')
    if tuple(sorted(manifest.sources, key=lambda ref: ref.source.source_id)) != manifest.sources:
        raise ValueError('generation source set must be sorted')
    base = generation_base(manifest.quarter, manifest.generation_id)
    expected = {(base + '/part-00000.parquet', 'data'), (base + '/changes.parquet', 'changes')}
    if {(ref.path, ref.role) for ref in manifest.files} != expected or len(manifest.files) != 2:
        raise ValueError('generation files differ from exact layout')
    if manifest.gate != ('awaiting_approval' if manifest.quarter_mode == 'closed' and manifest.withdrawn else 'clear'):
        raise ValueError('generation gate differs from withdrawals/mode')
    if manifest.withdrawn and manifest.quarter_mode != 'closed':
        raise ValueError('open generation cannot withdraw')
    if manifest.retained_from_generation is not None and manifest.retained_from_generation != manifest.base_generation_id:
        raise ValueError('retained basis differs from exact base')
    authorities = [ref for ref in manifest.sources if ref.source.kind == 'quarterly' and ref.source.period == manifest.quarter]
    if len(authorities) > 1 or manifest.membership_source != (authorities[0] if authorities else None):
        raise ValueError('quarterly membership authority differs')
    if manifest.membership_source and not manifest.membership_source.quarter_counts.get(manifest.quarter):
        raise ValueError('empty quarterly membership is invalid_source')
    if not manifest.sources or any(not ref.source_row_count for ref in manifest.sources):
        raise ValueError('empty source is invalid_source')


def read_manifest(capture: GenerationCapture, objects: ObjectStore) -> GenerationManifest:
    expected = generation_base(capture.quarter, capture.generation_id) + '/manifest.json'
    if capture.manifest_ref != expected:
        raise ValueError('capture manifest address differs')
    body = objects.read(capture.manifest_ref)
    if (hashlib.sha256(body).hexdigest(), len(body)) != (capture.manifest_sha256, capture.manifest_bytes):
        raise Conflict('captured manifest hash or length differs')
    value = parse_json(body)
    manifest = GenerationManifest.from_mapping(value)
    if canonical_json(manifest.to_mapping()) != body:
        raise ValueError('generation manifest must use canonical JSON')
    if (manifest.quarter, manifest.generation_id) != (capture.quarter, capture.generation_id):
        raise ValueError('captured generation differs')
    _validate_identity(manifest)
    return manifest


def iter_file_rows(ref: FileRef, objects: ObjectStore) -> Iterator[dict[str, object]]:
    with TemporaryDirectory(prefix='sec-generation-read-') as directory:
        path = Path(directory) / 'rows.parquet'
        objects.materialize(ref.path, path)
        if _file_identity(path) != (ref.sha256, ref.byte_count):
            raise Conflict('generation file hash or length differs')
        expected = canonical_schema() if ref.role == 'data' else change_schema()
        with pq.ParquetFile(path) as parquet:
            if not parquet.schema_arrow.equals(expected, check_metadata=True):
                raise ValueError('generation Parquet schema differs')
            count = 0
            for batch in parquet.iter_batches(batch_size=BATCH_ROWS):
                for value in batch.to_pylist():
                    count += 1
                    yield value
            if count != ref.row_count:
                raise ValueError('generation file row count differs')


def _row(value, quarter):
    row = IndexRow(**value)
    if quarter_for(row.filing_date) != quarter:
        raise ValueError('row is in the wrong filing quarter')
    return row


def validate_files(manifest: GenerationManifest, objects: ObjectStore) -> None:
    """Read every emitted byte and row before creating the immutable manifest."""
    _validate_identity(manifest)
    counts = Counter()
    for ref in manifest.files:
        previous_key = None
        with closing(iter_file_rows(ref, objects)) as rows:
            for value in rows:
                key = (value['cik'], value['archive_path'])
                if ref.role == 'changes':
                    key += (value['change_type'],)
                if previous_key is not None and key <= previous_key:
                    raise ValueError('generation keys are duplicate or unsorted')
                previous_key = key
                if ref.role == 'data':
                    _row(value, manifest.quarter)
                    counts['data'] += 1
                    continue
                kind = value['change_type']
                if kind not in ('added', 'updated', 'withdrawn', 'unresolved_absence'):
                    raise ValueError('unknown change type')
                before, after = value['before'], value['after']
                if ((kind == 'added' and (before is not None or after is None)) or
                    (kind == 'withdrawn' and (before is None or after is not None)) or
                    (kind in ('updated', 'unresolved_absence') and (before is None or after is None))):
                    raise ValueError('change before/after shape differs')
                for payload in (before, after):
                    if payload is not None:
                        row = _row(payload, manifest.quarter)
                        if (row.cik, row.archive_path) != key[:2]:
                            raise ValueError('change logical key differs')
                if kind == 'unresolved_absence' and (before != after or not value['reason']):
                    raise ValueError('unresolved absence must retain original row and reason')
                counts[kind] += 1
    expected = {'data': manifest.row_count, 'added': manifest.added, 'updated': manifest.updated,
                'withdrawn': manifest.withdrawn, 'unresolved_absence': manifest.unresolved_absence}
    if any(counts[key] != value for key, value in expected.items()):
        raise ValueError('generation aggregate counts differ')


def retained_base(manifest: GenerationManifest, objects: ObjectStore) -> GenerationCapture | None:
    """The exact capture a generation was built against, from its immutable retained-base record."""
    if not manifest.base_generation_id:
        return None
    body = objects.read(generation_base(manifest.quarter, manifest.generation_id) + '/retained-base.json')
    retained = GenerationCapture.from_mapping(parse_json(body))
    if canonical_json(retained.to_mapping()) != body or (retained.quarter, retained.generation_id) != (
            manifest.quarter, manifest.base_generation_id):
        raise ValueError('exact base dependency differs')
    if retained.generation_id == manifest.generation_id:
        raise ValueError('self-referential base dependency')
    return retained


def _base_manifest(manifest, objects):
    if not manifest.base_generation_id and manifest.unresolved_absence:
        raise ValueError('unresolved absence requires an exact retained dependency')
    retained = retained_base(manifest, objects)
    if retained is None:
        return None
    previous = read_manifest(retained, objects)
    validate_files(previous, objects)
    return previous


def _validate_row_origins(manifest, objects):
    base_manifest = _base_manifest(manifest, objects)
    with TemporaryDirectory(prefix='sec-candidate-verify-') as directory, closing(sqlite3.connect(Path(directory) / 'verify.sqlite')) as db:
        db.execute('PRAGMA temp_store=FILE')
        db.execute('CREATE TABLE allowed(payload BLOB PRIMARY KEY)')
        db.execute('CREATE TABLE ranked(cik TEXT, path TEXT, payload BLOB, preference INTEGER, period TEXT, receipt TEXT, source TEXT)')
        db.execute('CREATE TABLE winners(cik TEXT, path TEXT, payload BLOB, PRIMARY KEY(cik,path))')
        db.execute('CREATE TABLE membership(cik TEXT, path TEXT, PRIMARY KEY(cik,path))')
        db.execute('CREATE TABLE base_rows(cik TEXT, path TEXT, payload BLOB, PRIMARY KEY(cik,path))')
        db.execute('CREATE TABLE output(cik TEXT, path TEXT, payload BLOB, PRIMARY KEY(cik,path))')
        db.execute('CREATE TABLE unresolved(cik TEXT, path TEXT, PRIMARY KEY(cik,path))')
        db.execute('CREATE TABLE actual_changes(cik TEXT, path TEXT, payload BLOB, PRIMARY KEY(cik,path))')
        for ref in manifest.sources:
            durable, _ = _read_manifest(ref.manifest_ref, objects)
            if durable != ref:
                raise ValueError('selected source differs from immutable observation manifest')
            with closing(read_observations(ref, objects)) as rows:
                for obs in rows:
                    if quarter_for(obs.row.filing_date) == manifest.quarter:
                        payload = canonical_json(obs.row.to_mapping())
                        db.execute('INSERT OR IGNORE INTO allowed VALUES(?)', (payload,))
                        db.execute('INSERT INTO ranked VALUES(?,?,?,?,?,?,?)',
                                   (obs.row.cik, obs.row.archive_path, payload, int(ref.source.kind == 'quarterly'),
                                    ref.source.period, ref.snapshot.received_at.isoformat(), ref.source.source_id))
                        if ref == manifest.membership_source:
                            db.execute('INSERT OR IGNORE INTO membership VALUES(?,?)', (obs.row.cik, obs.row.archive_path))
        db.execute('INSERT OR IGNORE INTO winners SELECT cik,path,payload FROM ranked ORDER BY cik,path,preference DESC,period DESC,receipt DESC,source ASC')
        if base_manifest:
            for ref in base_manifest.files:
                if ref.role == 'data':
                    with closing(iter_file_rows(ref, objects)) as rows:
                        for value in rows:
                            row = _row(value, manifest.quarter)
                            db.execute('INSERT INTO base_rows VALUES(?,?,?)', (row.cik, row.archive_path, canonical_json(row.to_mapping())))
        for ref in manifest.files:
            if ref.role == 'data':
                with closing(iter_file_rows(ref, objects)) as rows:
                    for value in rows:
                        row = _row(value, manifest.quarter)
                        payload = canonical_json(row.to_mapping())
                        key = row.cik, row.archive_path
                        allowed = db.execute('SELECT 1 FROM allowed WHERE payload=?', (payload,)).fetchone()
                        old = db.execute('SELECT payload FROM base_rows WHERE cik=? AND path=?', key).fetchone()
                        if not allowed and (old is None or old[0] != payload):
                            raise ValueError('canonical row is not a selected observation or exact retained row')
                        db.execute('INSERT INTO output VALUES(?,?,?)', (*key, payload))
        for ref in manifest.files:
            if ref.role == 'changes':
                with closing(iter_file_rows(ref, objects)) as rows:
                    for value in rows:
                        key = value['cik'], value['archive_path']
                        normalized = dict(value)
                        for field in ('before', 'after'):
                            if normalized[field] is not None:
                                normalized[field] = _row(normalized[field], manifest.quarter).to_mapping()
                        if db.execute('SELECT 1 FROM actual_changes WHERE cik=? AND path=?', key).fetchone():
                            raise ValueError('delta has multiple changes for one logical key')
                        db.execute('INSERT INTO actual_changes VALUES(?,?,?)', (*key, canonical_json(normalized)))
                        after = value['after']
                        output = db.execute('SELECT payload FROM output WHERE cik=? AND path=?', key).fetchone()
                        if after is not None:
                            if output is None or output[0] != canonical_json(_row(after, manifest.quarter).to_mapping()):
                                raise ValueError('change after row differs from canonical output')
                        elif output is not None:
                            raise ValueError('withdrawn key remains in canonical output')
                        if value['change_type'] == 'unresolved_absence':
                            old = db.execute('SELECT payload FROM base_rows WHERE cik=? AND path=?', key).fetchone()
                            if old is None or old[0] != output[0]:
                                raise ValueError('unresolved row differs from exact retained base')
                            db.execute('INSERT INTO unresolved VALUES(?,?)', key)
                        if value['change_type'] == 'updated':
                            fields = ('company_name', 'form_type', 'filing_date', 'accession_number')
                            if all(value['before'][field] == after[field] for field in fields):
                                raise ValueError('provenance-only difference is not a business update')
        wrong_rank = db.execute('SELECT 1 FROM output o LEFT JOIN winners w ON o.cik=w.cik AND o.path=w.path LEFT JOIN unresolved u ON o.cik=u.cik AND o.path=u.path WHERE u.cik IS NULL AND (w.payload IS NULL OR w.payload != o.payload) LIMIT 1').fetchone()
        if wrong_rank:
            raise ValueError('canonical row violates selected source ranking precedence')
        if manifest.quarter_mode == 'closed' and manifest.membership_source:
            missing = db.execute('SELECT cik,path FROM membership EXCEPT SELECT cik,path FROM output').fetchone()
            extra = db.execute('SELECT cik,path FROM output EXCEPT SELECT cik,path FROM membership').fetchone()
            if missing or extra:
                raise ValueError('closed canonical keys differ from authoritative membership')
        else:
            missing = db.execute('SELECT cik,path FROM winners EXCEPT SELECT cik,path FROM output').fetchone()
            if missing:
                raise ValueError('canonical output is missing selected observation keys')
        if manifest.base_generation_id is None and (manifest.added != manifest.row_count or manifest.updated or manifest.withdrawn or manifest.unresolved_absence or manifest.provenance_refreshed):
            raise ValueError('first-generation changes differ from canonical rows')
        _validate_deltas(db, manifest)
        if bool(manifest.retained_from_generation) != bool(manifest.unresolved_absence):
            raise ValueError('retained basis and unresolved count disagree')


def _validate_deltas(db, manifest):
    """Recompute every change from the captured base, never trust supplied counts."""
    counts = Counter()
    keys = db.execute('SELECT cik,path FROM base_rows UNION SELECT cik,path FROM output ORDER BY cik,path')
    for key in keys:
        before_record = db.execute('SELECT payload FROM base_rows WHERE cik=? AND path=?', key).fetchone()
        after_record = db.execute('SELECT payload FROM output WHERE cik=? AND path=?', key).fetchone()
        before = parse_json(before_record[0]) if before_record else None
        after = parse_json(after_record[0]) if after_record else None
        kind, reason = None, None
        if before is None:
            kind = 'added'
        elif after is None:
            if manifest.quarter_mode != 'closed' or manifest.membership_source is None:
                raise ValueError('delta removes a base key without closed membership authority')
            kind, reason = 'withdrawn', 'absent from closed quarterly membership'
        else:
            winner = db.execute('SELECT 1 FROM winners WHERE cik=? AND path=?', key).fetchone()
            member = db.execute('SELECT 1 FROM membership WHERE cik=? AND path=?', key).fetchone()
            unresolved = winner is None or (manifest.quarter_mode == 'open' and manifest.membership_source is not None and member is None)
            if unresolved:
                if before != after:
                    raise ValueError('delta unresolved absence must preserve the exact base row')
                kind, reason = 'unresolved_absence', 'absence is not authoritative withdrawal evidence'
            elif any(before[field] != after[field] for field in ('company_name', 'form_type', 'filing_date', 'accession_number')):
                kind = 'updated'
            elif before != after:
                counts['provenance_refreshed'] += 1
        actual = db.execute('SELECT payload FROM actual_changes WHERE cik=? AND path=?', key).fetchone()
        if kind is None:
            if actual is not None:
                raise ValueError('delta contains a change absent from exact base/output comparison')
            continue
        expected = canonical_json({'change_type': kind, 'cik': key[0], 'archive_path': key[1],
                                   'before': before, 'after': after, 'reason': reason})
        if actual is None or actual[0] != expected:
            raise ValueError('delta differs from exact base/output before and after rows')
        counts[kind] += 1
    change_count = sum(counts[name] for name in ('added', 'updated', 'withdrawn', 'unresolved_absence'))
    if db.execute('SELECT COUNT(*) FROM actual_changes').fetchone()[0] != change_count:
        raise ValueError('delta includes keys outside exact base/output membership')
    for name in ('added', 'updated', 'withdrawn', 'unresolved_absence', 'provenance_refreshed'):
        if getattr(manifest, name) != counts[name]:
            raise ValueError('delta count differs from exact base/output comparison: ' + name)


def validate_candidate_content(candidate: Candidate, objects: ObjectStore) -> None:
    """Validate complete immutable output before the gate record/index can exist."""
    capture = GenerationCapture(candidate.manifest.quarter, candidate.manifest.generation_id,
                                candidate.manifest_ref, candidate.manifest_sha256, candidate.manifest_bytes)
    manifest = read_manifest(capture, objects)
    if manifest != candidate.manifest or candidate.candidate_ref != gate_ref(manifest):
        raise ValueError('candidate differs from exact manifest/gate identity')
    validate_files(manifest, objects)
    _validate_row_origins(manifest, objects)


def validate_candidate(candidate: Candidate, objects: ObjectStore) -> None:
    validate_candidate_content(candidate, objects)
    if candidate.candidate_ref and objects.read(candidate.candidate_ref) != gate_payload(candidate):
        raise Conflict('candidate gate record differs from exact generation/base/hash')
