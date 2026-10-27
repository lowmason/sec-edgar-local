"""C6: an incremental candidate equals the full rebuild on every key that the delta can change.

The recomputed keys are resolved by the full path's own code (`catalog._load_observations` and
`catalog._resolve`) over every selected source, limited to those keys. Every other row must equal its
base row, column by column. Nothing here reuses the incremental build (C5); both share only the
hash-checked readers in `columnar`.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow.compute as pc

from ..models import RunContext, canonical_json
from ..storage.contracts import ObjectStore
from .columnar import generation_table, key_mask, quarter_observations, table_keys
from .contracts import Candidate, GenerationCapture, IndexRow
from .manifest import _row, check_candidate_integrity
from .reader import checked_manifest
from .transform import checked_observation

CHANGE_FIELDS = ('change_type', 'cik', 'archive_path', 'before', 'after', 'reason')


def _change_payload(value, quarter) -> bytes:
    for field in ('before', 'after'):
        if value[field] is not None:
            value[field] = _row(value[field], quarter).to_mapping()
    return canonical_json({name: value[name] for name in CHANGE_FIELDS})


def _strictly_sorted(table) -> None:
    keys = list(zip(table['cik'].to_pylist(), table['archive_path'].to_pylist()))
    if any(left >= right for left, right in zip(keys, keys[1:])):
        raise ValueError('generation keys are duplicate or unsorted')


def _recomputed_keys(manifest, delta, base_data, objects) -> set:
    keys = {(obs.row.cik, obs.row.archive_path) for ref in delta
            for obs in quarter_observations(ref, objects, manifest.quarter)}
    if manifest.quarter_mode == 'open' and manifest.membership_source is not None:
        # Locality exception (A1): any base key the authority does not list may become absent.
        members = {(obs.row.cik, obs.row.archive_path)
                   for obs in quarter_observations(manifest.membership_source, objects, manifest.quarter)}
        keys |= table_keys(base_data) - members
    return keys


def _expected(manifest, base_data, keys, context, objects):
    from .catalog import _database, _load_observations, _resolve
    quarter = manifest.quarter
    with TemporaryDirectory(prefix='sec-equivalence-') as directory, \
            closing(_database(Path(directory) / 'expected.sqlite')) as db:
        _load_observations(db, manifest.sources, quarter, manifest.membership_source, objects, context,
                           read=lambda ref, objects: quarter_observations(ref, objects, quarter, keys))
        for value in base_data.filter(key_mask(base_data, keys)).to_pylist():
            row = IndexRow(**value)
            db.execute('INSERT INTO active VALUES(?,?,?)', (row.cik, row.archive_path, canonical_json(row.to_mapping())))
        counts = _resolve(db, manifest.quarter_mode, manifest.membership_source)
        rows = {(cik, path): payload for cik, path, payload in db.execute('SELECT cik,path,payload FROM proposed')}
        changes = {(cik, path): payload for cik, path, payload in db.execute('SELECT cik,path,payload FROM changes')}
    return rows, changes, counts


def validate_incremental_candidate(candidate: Candidate, previous: GenerationCapture, context: RunContext,
                                   objects: ObjectStore) -> None:
    manifest, quarter = candidate.manifest, candidate.manifest.quarter
    check_candidate_integrity(candidate, objects)
    base = checked_manifest(previous, objects)
    if (manifest.base_generation_id != previous.generation_id or base.quarter != quarter or base.gate != 'clear'
            or (base.quarter_mode, base.membership_source, base.parser_version, base.schema_version)
            != (manifest.quarter_mode, manifest.membership_source, manifest.parser_version, manifest.schema_version)
            or not all(ref in manifest.sources for ref in base.sources)):
        raise ValueError('incremental candidate differs from its eligible base')
    base_ids = {ref.source.source_id for ref in base.sources}
    delta = [ref for ref in manifest.sources if ref.source.source_id not in base_ids]
    for ref in delta:
        if checked_observation(ref.manifest_ref, objects) != ref:
            raise ValueError('incremental source differs from its immutable observation manifest')
    files, base_files = ({ref.role: ref for ref in value.files} for value in (manifest, base))
    data, changes = generation_table(files['data'], objects), generation_table(files['changes'], objects)
    base_data, base_changes = generation_table(base_files['data'], objects), generation_table(base_files['changes'], objects)
    _strictly_sorted(data)
    _strictly_sorted(changes)
    keys = _recomputed_keys(manifest, delta, base_data, objects)
    expected_rows, expected_changes, counts = _expected(manifest, base_data, keys, context, objects)
    actual_rows = {}
    for value in data.filter(key_mask(data, keys)).to_pylist():
        row = _row(value, quarter)
        actual_rows[row.cik, row.archive_path] = canonical_json(row.to_mapping())
    if actual_rows != expected_rows:
        raise ValueError('incremental rows differ from the full resolution of their keys')
    actual_changes = {(value['cik'], value['archive_path']): _change_payload(value, quarter)
                      for value in changes.filter(key_mask(changes, keys)).to_pylist()}
    if actual_changes != expected_changes:
        raise ValueError('incremental change rows differ from the full resolution of their keys')
    outside = lambda table: table.filter(pc.invert(key_mask(table, keys)))
    if not outside(data).equals(outside(base_data)):
        raise ValueError('incremental candidate changes a data row outside its recomputed keys')
    re_emitted = outside(base_changes.filter(pc.equal(base_changes['change_type'], 'unresolved_absence')))
    if not outside(changes).equals(re_emitted):
        raise ValueError('incremental change rows outside its recomputed keys differ from re-emitted absences')
    expected = {'row_count': data.num_rows, 'added': counts['added'], 'updated': counts['updated'],
                'withdrawn': counts['withdrawn'], 'provenance_refreshed': counts['provenance_refreshed'],
                'unresolved_absence': counts['unresolved_absence'] + re_emitted.num_rows}
    if any(getattr(manifest, name) != value for name, value in expected.items()):
        raise ValueError('incremental counts differ from the full resolution')
    retained = previous.generation_id if manifest.unresolved_absence else None
    gate = 'awaiting_approval' if manifest.quarter_mode == 'closed' and manifest.withdrawn else 'clear'
    if (manifest.retained_from_generation, manifest.gate) != (retained, gate):
        raise ValueError('incremental retained basis or gate differs')
