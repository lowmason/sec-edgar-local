"""Transform pinned retained bytes into verified immutable source observations."""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from ..config import Settings, pin_context
from ..models import (BodyReceipt, Error, IMAGE_PATTERN, RunContext, Snapshot, Source,
                      canonical_json, error_text, parse_json, quarter_for)
from ..state import AcquisitionState
from ..storage.contracts import BoundaryObserver, Conflict, FILE_CHUNK_BYTES, ObjectStore, observe
from ..validation import validate_envelope
from ..worksets import decode_snapshot_workset, decode_source_workset, make_snapshot_workset
from .contracts import (TRANSFORMED_FORMAT, IndexRow, Observation, ObservationRef, TransformedWorkset,
                        decode_transformed, encode_transformed, observation_base, observation_schema,
                        processing_key, transformed_ref)
from .parser import ParseError, iter_observations, parse_fields, supported_parser
from .state import EtlState

BATCH_ROWS = 8192
OBSERVATION_FORMAT = 'sec-observation-v1'
PARQUET_VERSION = '2.6'
HTTP_OK = 200
RETAINED_ENTITY_HEADERS = frozenset({'content-type', 'content-encoding', 'etag', 'last-modified'})


def observation_mapping(obs: Observation) -> dict[str, object]:
    return {**obs.row.to_mapping(), 'filing_date': obs.row.filing_date,
            'original_fields': list(obs.original_fields), 'line_number': obs.line_number}


def _file_identity(path: Path) -> tuple[str, int]:
    digest, byte_count = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(FILE_CHUNK_BYTES):
            digest.update(chunk)
            byte_count += len(chunk)
    return digest.hexdigest(), byte_count


def _seen_database(path: Path):
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE seen (cik TEXT, path TEXT, payload BLOB, PRIMARY KEY (cik, path))')
    return connection


def _remember_observation(db, obs: Observation) -> None:
    key = (obs.row.cik, obs.row.archive_path)
    normalized = canonical_json(obs.row.to_mapping())
    old = db.execute('SELECT payload FROM seen WHERE cik=? AND path=?', key).fetchone()
    if old is not None and old[0] != normalized:
        raise ParseError(obs.line_number, 'conflicting duplicate logical key')
    if old is None:
        db.execute('INSERT INTO seen(cik,path,payload) VALUES(?,?,?)', (*key, normalized))


def _parquet_observations(path: Path) -> Iterator[Observation]:
    with pq.ParquetFile(path) as parquet:
        if not parquet.schema_arrow.equals(observation_schema(), check_metadata=True):
            raise ValueError('observation Parquet schema differs')
        for batch in parquet.iter_batches(batch_size=BATCH_ROWS):
            for value in batch.to_pylist():
                original = tuple(value.pop('original_fields'))
                line_number = value.pop('line_number')
                yield Observation(IndexRow(**value), original, line_number)


def _verify_parquet(path: Path, ref: ObservationRef, database: Path) -> None:
    if _file_identity(path) != (ref.rows_sha256, ref.rows_bytes):
        raise Conflict('observation bytes differ from manifest hash or length')
    quarters, count, previous_line = Counter(), 0, 0
    with closing(_seen_database(database)) as db, closing(_parquet_observations(path)) as rows:
        for obs in rows:
            expected = parse_fields(obs.original_fields, ref.source, ref.snapshot,
                                    line_number=obs.line_number, parser_version=ref.parser_version,
                                    schema_version=ref.schema_version)
            if obs != expected or obs.line_number <= previous_line:
                raise ValueError('observation row/provenance/physical line differs')
            _remember_observation(db, obs)
            previous_line = obs.line_number
            quarters[quarter_for(obs.row.filing_date)] += 1
            count += 1
        distinct = db.execute('SELECT COUNT(*) FROM seen').fetchone()[0]
    if (count, distinct, dict(quarters)) != (ref.source_row_count, ref.distinct_key_count, dict(ref.quarter_counts)):
        raise ValueError('observation readback counts differ')


def read_observations(ref: ObservationRef, objects: ObjectStore) -> Iterator[Observation]:
    with TemporaryDirectory(prefix='sec-observation-read-') as directory:
        root = Path(directory)
        path = root / 'rows.parquet'
        objects.materialize(ref.rows_ref, path)
        _verify_parquet(path, ref, root / 'verify.sqlite')
        with closing(_parquet_observations(path)) as rows:
            yield from rows


def _read_manifest(path: str, objects: ObjectStore) -> tuple[ObservationRef, bytes]:
    body = objects.read(path)
    value = parse_json(body)
    if (not isinstance(value, dict) or set(value) != {'format_version', 'observation', 'image_digest'}
            or value['format_version'] != OBSERVATION_FORMAT or canonical_json(value) != body
            or not isinstance(value['image_digest'], str) or IMAGE_PATTERN.fullmatch(value['image_digest']) is None):
        raise ValueError('invalid observation manifest')
    ref = ObservationRef.from_mapping(value['observation'])
    if ref.manifest_ref != path:
        raise ValueError('observation manifest address differs')
    with closing(read_observations(ref, objects)) as rows:
        for _ in rows:
            pass
    return ref, body


def _existing(source, snapshot, context, objects, state):
    base = observation_base(source.source_id, snapshot.sha256, context.parser_version, context.schema_version)
    key = processing_key(source.source_id, snapshot.sha256, context.parser_version, context.schema_version)
    accepted = state.store.get('Processing', key)
    try:
        ref, body = _read_manifest(base + '/manifest.json', objects)
    except FileNotFoundError:
        if accepted is not None:
            raise Conflict('accepted observation manifest or data is missing')
        # A manifest that exists but references missing rows must also fail closed.
        try:
            objects.read(base + '/manifest.json')
        except FileNotFoundError:
            return None
        raise Conflict('observation manifest references missing data')
    if (ref.source, ref.snapshot, ref.parser_version, ref.schema_version) != (
            source, snapshot, context.parser_version, context.schema_version):
        raise Conflict('observation manifest processing identity differs')
    if accepted is not None and accepted.to_mapping()['value']['observation'] != ref.to_mapping():
        raise Conflict('accepted processing differs from observation manifest')
    return ref, body


def _validate_context(context: RunContext, settings: Settings) -> None:
    if context.pinned_on is None or pin_context(settings, context, context.pinned_on)[0] != context:
        raise ValueError('transform requires its exact pinned effective configuration')
    supported_parser(context.parser_version, fixture=settings.storage.backend == 'local-fixture')
    _check_deadline(context)


def _check_deadline(context: RunContext) -> None:
    if datetime.now(timezone.utc) >= context.deadline:
        raise TimeoutError('transform deadline exceeded')


def _validate_raw(source, snapshot, context, settings, objects, path):
    expected = f'raw/sec/indexes/kind={source.kind}/period={source.period}/sha256={snapshot.sha256}/master.{source.representation}'
    if snapshot.source_id != source.source_id or snapshot.raw_path != expected or snapshot.representation != source.representation:
        raise ValueError('raw snapshot differs from exact source member')
    objects.materialize(snapshot.raw_path, path)
    headers = {key: value for key, value in snapshot.validators.items() if key.lower() in RETAINED_ENTITY_HEADERS}
    receipt = BodyReceipt(source.canonical_url, HTTP_OK, headers, path, snapshot.received_at,
                          snapshot.byte_count, snapshot.sha256, True, None)
    validated = validate_envelope(source, receipt, settings)
    if validated.envelope_version != snapshot.envelope_version:
        raise ValueError('retained raw envelope version differs')
    _check_deadline(context)


def _write_rows(raw, root, source, snapshot, context):
    path = root / 'rows.parquet'
    count, quarters, batch = 0, Counter(), []
    with (closing(_seen_database(root / 'seen.sqlite')) as db,
          closing(iter_observations(raw, source, snapshot, parser_version=context.parser_version,
                                    schema_version=context.schema_version)) as rows,
          pq.ParquetWriter(path, observation_schema(), version=PARQUET_VERSION,
                           compression='snappy', use_dictionary=False, use_compliant_nested_type=False) as writer):
        for obs in rows:
            _remember_observation(db, obs)
            batch.append(observation_mapping(obs))
            count += 1
            quarters[quarter_for(obs.row.filing_date)] += 1
            if len(batch) == BATCH_ROWS:
                _check_deadline(context)
                writer.write_table(pa.Table.from_pylist(batch, schema=observation_schema()))
                batch.clear()
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=observation_schema()))
        distinct = db.execute('SELECT COUNT(*) FROM seen').fetchone()[0]
    digest, byte_count = _file_identity(path)
    base = observation_base(source.source_id, snapshot.sha256, context.parser_version, context.schema_version)
    ref = ObservationRef(source, snapshot, context.parser_version, context.schema_version,
                         base + '/rows.parquet', base + '/manifest.json', digest, byte_count,
                         count, distinct, dict(sorted(quarters.items())))
    _verify_parquet(path, ref, root / 'readback.sqlite')
    _check_deadline(context)
    return path, ref


def _failure(error, source, snapshot, context) -> Error:
    return Error('state_conflict' if isinstance(error, Conflict) else 'transform_failed', error_text(error),
                 False, source.source_id, {'line_number': getattr(error, 'line_number', None),
                 'reason': getattr(error, 'reason', str(error)), 'raw_sha256': snapshot.sha256,
                 'parser_version': context.parser_version, 'schema_version': context.schema_version})


def _retain_failure(error, source, snapshot, context, objects):
    failure = _failure(error, source, snapshot, context)
    base = f'quarantine/sec/{context.run_id}/{source.source_id}/transform/{context.attempt_id}'
    body = canonical_json(failure.to_mapping())
    try:
        objects.put_once(base + '/error.json', body)
    except Conflict:
        objects.put_once(base + '/error-' + hashlib.sha256(body).hexdigest() + '.json', body)


def transform_member(source: Source, snapshot: Snapshot, context: RunContext, settings: Settings,
                     objects: ObjectStore, state: EtlState, *, force: bool = False,
                     observer: BoundaryObserver | None = None) -> ObservationRef:
    try:
        _validate_context(context, settings)
        with TemporaryDirectory(prefix='sec-transform-') as directory:
            root = Path(directory)
            raw = root / ('master.' + source.representation)
            _validate_raw(source, snapshot, context, settings, objects, raw)
            existing = _existing(source, snapshot, context, objects, state)
            if existing is not None and not force:
                state.accept_transform(existing[0])
                observe(observer, 'transform.after_processing')
                return existing[0]
            path, ref = _write_rows(raw, root, source, snapshot, context)
            if existing is not None and existing[0] != ref:
                raise Conflict('forced transform differs from immutable observation')
            objects.stage(ref.rows_ref, path)
            objects.verify(ref.rows_ref, ref.rows_sha256, ref.rows_bytes)
            observe(observer, 'transform.after_rows')
            manifest = canonical_json({'format_version': OBSERVATION_FORMAT, 'observation': ref.to_mapping(),
                                       'image_digest': context.image_digest})
            if existing is not None:
                manifest = existing[1]
            try:
                objects.put_once(ref.manifest_ref, manifest)
            except Conflict:
                winner, _ = _read_manifest(ref.manifest_ref, objects)
                if winner != ref:
                    raise Conflict('concurrent observation winner differs')
            verified, _ = _read_manifest(ref.manifest_ref, objects)
            if verified != ref:
                raise Conflict('durable observation differs after upload')
            observe(observer, 'transform.after_manifest')
            state.accept_transform(verified)
            observe(observer, 'transform.after_processing')
            return verified
    except Exception as error:
        _retain_failure(error, source, snapshot, context, objects)
        raise


def _pinned_members(snapshot_ref, objects, acquisition):
    snapshots = decode_snapshot_workset(objects.read(snapshot_ref))
    if snapshot_ref != f'worksets/sec/snapshot/sha256={snapshots.workset_id}/workset.json':
        raise ValueError('snapshot reference differs from immutable workset identity')
    source_ref = f'worksets/sec/source/sha256={snapshots.source_workset_id}/workset.json'
    sources = decode_source_workset(objects.read(source_ref))
    if sources.workset_id != snapshots.source_workset_id or make_snapshot_workset(sources, snapshots.snapshots) != snapshots:
        raise ValueError('snapshot workset differs from pinned source membership/context')
    by_source = {source.source_id: source for source in sources.members}
    for snapshot in snapshots.snapshots:
        binding = acquisition.binding(sources.workset_id, snapshot.source_id)
        if binding is None or (binding.source_workset_id, binding.source_id, binding.snapshot_sha256) != (
                sources.workset_id, snapshot.source_id, snapshot.sha256):
            raise ValueError('exact acquisition binding is missing or differs')
        if acquisition.snapshot(snapshot.source_id, snapshot.sha256) != snapshot:
            raise ValueError('remembered acquisition metadata differs')
    return snapshots, by_source


def transform_workset(snapshot_ref: str, context: RunContext, settings: Settings, objects: ObjectStore,
                      state: EtlState, acquisition: AcquisitionState, *, force: bool = False,
                      observer: BoundaryObserver | None = None) -> TransformedWorkset:
    _validate_context(context, settings)
    snapshots, sources = _pinned_members(snapshot_ref, objects, acquisition)
    observations, failures = [], []
    for snapshot in snapshots.snapshots:
        source = sources[snapshot.source_id]
        try:
            observations.append(transform_member(source, snapshot, context, settings, objects, state,
                                                 force=force, observer=observer))
        except Exception as error:
            failures.append(_failure(error, source, snapshot, context))
    result = TransformedWorkset('0' * 64, snapshot_ref, snapshots.context, context,
                                tuple(observations), tuple(failures), not failures)
    identity = {'format_version': TRANSFORMED_FORMAT, **result.to_mapping()}
    identity.pop('workset_id')
    result = replace(result, workset_id=hashlib.sha256(canonical_json(identity)).hexdigest())
    body = encode_transformed(result)
    path = transformed_ref(result)
    objects.put_once(path, body)
    objects.verify(path, hashlib.sha256(body).hexdigest(), len(body))
    if decode_transformed(objects.read(path)) != result:
        raise Conflict('transformed workset readback differs')
    observe(observer, 'transform.after_workset')
    return result
