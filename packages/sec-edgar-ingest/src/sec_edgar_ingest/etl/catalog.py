"""Deterministic, disk-backed quarter candidates without publication side effects."""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from ..config import Settings
from ..models import Error, RunContext, canonical_json, parse_json, quarter_for, quarter_value
from ..storage.contracts import BoundaryObserver, Conflict, ObjectStore, observe
from .contracts import Candidate, FileRef, GenerationCapture, GenerationManifest, IndexRow, ObservationRef, canonical_schema, change_schema
from .manifest import (gate_payload, gate_ref, generation_base, generation_identity, iter_file_rows,
                       read_manifest, source_fingerprint, validate_candidate, validate_candidate_content, validate_files)
from .state import EtlState
from .transform import BATCH_ROWS, PARQUET_VERSION, _check_deadline, _file_identity, _validate_context, read_observations, transform_member

BUSINESS_FIELDS = ('cik', 'company_name', 'form_type', 'archive_path', 'filing_date', 'accession_number')


def select_sources(existing: tuple[ObservationRef, ...], incoming: tuple[ObservationRef, ...]) -> tuple[ObservationRef, ...]:
    selected = {}
    for ref in (*existing, *incoming):
        identity = ref.source.source_id
        old = selected.get(identity)
        if old is None:
            selected[identity] = ref
            continue
        if old.source != ref.source:
            raise Conflict('source ID has conflicting source metadata')
        if old.snapshot.sha256 == ref.snapshot.sha256:
            if (old.parser_version, old.schema_version) == (ref.parser_version, ref.schema_version):
                if old.rows_sha256 != ref.rows_sha256:
                    raise Conflict('same processing identity has conflicting observations')
            continue
        if old.snapshot.received_at == ref.snapshot.received_at:
            raise Conflict('same receipt time has ambiguous distinct snapshots')
        if ref.snapshot.received_at > old.snapshot.received_at:
            selected[identity] = ref
    return tuple(selected[key] for key in sorted(selected))


def _candidate(manifest, body):
    return Candidate(manifest, generation_base(manifest.quarter, manifest.generation_id) + '/manifest.json',
                     hashlib.sha256(body).hexdigest(), len(body), gate_ref(manifest))


def _existing(quarter, generation_id, objects):
    path = generation_base(quarter, generation_id) + '/manifest.json'
    try:
        body = objects.read(path)
    except FileNotFoundError:
        return None
    capture = GenerationCapture(quarter, generation_id, path, hashlib.sha256(body).hexdigest(), len(body))
    candidate = _candidate(read_manifest(capture, objects), body)
    validate_candidate_content(candidate, objects)
    return candidate


def _database(path):
    db = sqlite3.connect(path)
    db.execute('PRAGMA temp_store=FILE')
    db.execute('CREATE TABLE observations(cik TEXT, path TEXT, payload BLOB, quarterly_preference INTEGER, source_period TEXT, received_at TEXT, source_id TEXT, member INTEGER)')
    for name in ('active', 'proposed'):
        db.execute(f'CREATE TABLE {name}(cik TEXT, path TEXT, payload BLOB, PRIMARY KEY(cik,path))')
    db.execute('CREATE TABLE changes(cik TEXT, path TEXT, change_type TEXT, payload BLOB, PRIMARY KEY(cik,path,change_type))')
    return db


def _load_observations(db, selected, quarter, membership, objects, context):
    for ref in selected:
        if not ref.source_row_count:
            raise ValueError('invalid_source: empty source observations')
        with closing(read_observations(ref, objects)) as rows:
            for obs in rows:
                if quarter_for(obs.row.filing_date) != quarter:
                    continue
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)',
                           (obs.row.cik, obs.row.archive_path, canonical_json(obs.row.to_mapping()),
                            int(ref.source.kind == 'quarterly'), ref.source.period,
                            ref.snapshot.received_at.isoformat(), ref.source.source_id, int(ref == membership)))
        _check_deadline(context)
    db.execute('CREATE INDEX ranked ON observations(cik,path,quarterly_preference DESC,source_period DESC,received_at DESC,source_id ASC)')
    previous_key = None
    for cik, path, payload in db.execute('SELECT cik,path,payload FROM observations ORDER BY cik,path,quarterly_preference DESC,source_period DESC,received_at DESC,source_id ASC'):
        if (cik, path) == previous_key:
            continue
        previous_key = cik, path
        db.execute('INSERT INTO proposed VALUES(?,?,?)', (cik, path, payload))


def _load_active(db, previous, objects):
    if previous is None:
        return
    for ref in previous.files:
        if ref.role == 'data':
            with closing(iter_file_rows(ref, objects)) as rows:
                for value in rows:
                    row = IndexRow(**value)
                    db.execute('INSERT INTO active VALUES(?,?,?)', (row.cik, row.archive_path, canonical_json(row.to_mapping())))


def _change(db, key, kind, before, after, reason=None):
    value = {'change_type': kind, 'cik': key[0], 'archive_path': key[1],
             'before': before, 'after': after, 'reason': reason}
    db.execute('INSERT INTO changes VALUES(?,?,?,?)', (*key, kind, canonical_json(value)))


def _resolve(db, mode, membership):
    counts = Counter()
    if mode == 'closed' and membership:
        db.execute('DELETE FROM proposed WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.cik=proposed.cik AND o.path=proposed.path AND o.member=1)')
    for cik, path, payload in db.execute('SELECT cik,path,payload FROM active ORDER BY cik,path'):
        key, before = (cik, path), parse_json(payload)
        proposed = db.execute('SELECT payload FROM proposed WHERE cik=? AND path=?', key).fetchone()
        member = membership is not None and db.execute('SELECT 1 FROM observations WHERE cik=? AND path=? AND member=1 LIMIT 1', key).fetchone() is not None
        absent = proposed is None or (mode == 'open' and membership is not None and not member)
        if absent:
            if mode == 'closed' and membership:
                _change(db, key, 'withdrawn', before, None, 'absent from closed quarterly membership')
                counts['withdrawn'] += 1
            else:
                db.execute('INSERT OR REPLACE INTO proposed VALUES(?,?,?)', (*key, payload))
                _change(db, key, 'unresolved_absence', before, before, 'absence is not authoritative withdrawal evidence')
                counts['unresolved_absence'] += 1
                counts['retained'] += 1
            continue
        after = parse_json(proposed[0])
        if any(before[name] != after[name] for name in BUSINESS_FIELDS):
            _change(db, key, 'updated', before, after)
            counts['updated'] += 1
        elif before != after:
            counts['provenance_refreshed'] += 1
    for cik, path, payload in db.execute('SELECT p.cik,p.path,p.payload FROM proposed p LEFT JOIN active a ON p.cik=a.cik AND p.path=a.path WHERE a.cik IS NULL ORDER BY p.cik,p.path'):
        _change(db, (cik, path), 'added', None, parse_json(payload))
        counts['added'] += 1
    counts['data'] = db.execute('SELECT COUNT(*) FROM proposed').fetchone()[0]
    return counts


def _arrow_row(value):
    return {**value, 'filing_date': IndexRow.from_mapping(value).filing_date}


def _write_parquet(db, root, base, role, context):
    name = 'part-00000.parquet' if role == 'data' else 'changes.parquet'
    schema = canonical_schema() if role == 'data' else change_schema()
    sql = ('SELECT payload FROM proposed ORDER BY cik,path' if role == 'data' else
           'SELECT payload FROM changes ORDER BY cik,path,change_type')
    batch, count, path = [], 0, root / name
    with pq.ParquetWriter(path, schema, version=PARQUET_VERSION, compression='snappy',
                          use_dictionary=False, use_compliant_nested_type=False) as writer:
        for (payload,) in db.execute(sql):
            value = parse_json(payload)
            if role == 'data':
                value = _arrow_row(value)
            else:
                for field in ('before', 'after'):
                    if value[field] is not None:
                        value[field] = _arrow_row(value[field])
            batch.append(value)
            count += 1
            if len(batch) == BATCH_ROWS:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                batch.clear()
                _check_deadline(context)
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
    digest, byte_count = _file_identity(path)
    return path, FileRef(base + '/' + name, digest, byte_count, count, role)


def _stage_gate(candidate, objects, state):
    if candidate.candidate_ref:
        body = gate_payload(candidate)
        objects.put_once(candidate.candidate_ref, body)
        objects.verify(candidate.candidate_ref, hashlib.sha256(body).hexdigest(), len(body))
        if objects.read(candidate.candidate_ref) != body:
            raise Conflict('candidate gate readback differs')
        validate_candidate(candidate, objects)
        state.record_candidate(candidate)


def _invalid_membership(quarter, source, context, objects):
    error = Error('invalid_source', 'quarterly source has empty target-quarter membership', False,
                  source.source.source_id, {'quarter': quarter, 'raw_sha256': source.snapshot.sha256})
    body = canonical_json(error.to_mapping())
    path = f'quarantine/sec/{context.run_id}/{source.source.source_id}/catalog/{hashlib.sha256(body).hexdigest()}.json'
    objects.put_once(path, body)
    raise ValueError(error.message)


def build_candidate(quarter: str, previous: GenerationCapture | None, incoming: tuple[ObservationRef, ...],
                    context: RunContext, settings: Settings, objects: ObjectStore, state: EtlState, *,
                    observer: BoundaryObserver | None = None) -> Candidate:
    _validate_context(context, settings)
    if quarter_value(quarter) > quarter_value(quarter_for(context.pinned_on)):
        raise ValueError('future output quarter is not configured')
    mode = 'open' if quarter == quarter_for(context.pinned_on) else 'closed'
    if previous and previous.quarter != quarter:
        raise ValueError('previous generation belongs to another quarter')
    active = read_manifest(previous, objects) if previous else None
    if active:
        validate_candidate(Candidate(active, previous.manifest_ref, previous.manifest_sha256,
                                     previous.manifest_bytes, gate_ref(active)), objects)
    selected = select_sources(active.sources if active else (), incoming)
    selected = tuple(transform_member(ref.source, ref.snapshot, context, settings, objects, state)
                     if (ref.parser_version, ref.schema_version) != (context.parser_version, context.schema_version)
                     else ref for ref in selected)
    authorities = [ref for ref in selected if ref.source.kind == 'quarterly' and ref.source.period == quarter]
    if len(authorities) > 1:
        raise Conflict('multiple quarterly sources claim the same membership period')
    membership = authorities[0] if authorities else None
    if membership and not membership.quarter_counts.get(quarter):
        _invalid_membership(quarter, membership, context, objects)
    if not selected:
        raise ValueError('candidate requires nonempty sources')
    if active and source_fingerprint(quarter, selected, mode=mode, membership_source=membership,
                                    retained_from_generation=active.retained_from_generation) == active.source_fingerprint:
        candidate = Candidate(active, previous.manifest_ref, previous.manifest_sha256, previous.manifest_bytes, gate_ref(active))
        _stage_gate(candidate, objects, state)
        return candidate
    with TemporaryDirectory(prefix='sec-catalog-') as directory:
        root = Path(directory)
        with closing(_database(root / 'catalog.sqlite')) as db:
            _load_observations(db, selected, quarter, membership, objects, context)
            _load_active(db, active, objects)
            counts = _resolve(db, mode, membership)
            retained = previous.generation_id if counts['retained'] and previous else None
            fingerprint = source_fingerprint(quarter, selected, mode=mode, membership_source=membership,
                                             retained_from_generation=retained)
            generation_id = generation_identity(quarter, previous.generation_id if previous else None, fingerprint)
            existing = _existing(quarter, generation_id, objects)
            if existing:
                observe(observer, 'candidate.after_validation')
                _stage_gate(existing, objects, state)
                return existing
            base = generation_base(quarter, generation_id)
            files = []
            for role in ('data', 'changes'):
                path, ref = _write_parquet(db, root, base, role, context)
                objects.stage(ref.path, path)
                objects.verify(ref.path, ref.sha256, ref.byte_count)
                files.append(ref)
                observe(observer, 'candidate.after_' + role)
        manifest = GenerationManifest(quarter, generation_id, previous.generation_id if previous else None,
                                      fingerprint, context.parser_version, context.schema_version, context.image_digest,
                                      selected, tuple(files), counts['data'], counts['added'], counts['updated'],
                                      counts['withdrawn'], counts['unresolved_absence'], counts['provenance_refreshed'],
                                      mode, membership, retained,
                                      'awaiting_approval' if mode == 'closed' and counts['withdrawn'] else 'clear')
        validate_files(manifest, objects)
        if previous:
            objects.put_once(base + '/retained-base.json', canonical_json(previous.to_mapping()))
        body = canonical_json(manifest.to_mapping())
        candidate = _candidate(manifest, body)
        try:
            objects.put_once(candidate.manifest_ref, body)
        except Conflict:
            candidate = _existing(quarter, generation_id, objects)
            if candidate is None:
                raise Conflict('concurrent candidate vanished')
        observe(observer, 'candidate.after_manifest')
        validate_candidate_content(candidate, objects)
        observe(observer, 'candidate.after_validation')
        _stage_gate(candidate, objects, state)
        return candidate
