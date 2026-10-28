"""Stage 1b C4 and C5: rebuild an eligible quarter from its base tables and its delta rows.

Plan 5's locality proof names the keys that an eligible addition can change: the touched keys and,
in an open quarter with a membership authority, base `added` keys that the authority does not list.
Every other data row and re-emitted absence is copied from the base generation's columns.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..models import RunContext, canonical_json, parse_json
from ..storage.contracts import ObjectStore
from .columnar import (KEY_SEPARATOR, Key, generation_table, key_column, key_mask, quarter_key_column,
                       quarter_observations, table_keys)
from .contracts import (ABSENCE_REASON, BUSINESS_FIELDS, WITHDRAWAL_REASON, GenerationManifest, IndexRow,
                        ObservationRef, arrow_row, canonical_schema, change_schema)
from .transform import BATCH_ROWS, PARQUET_VERSION, _check_deadline

Rank = tuple[int, str, str]


@dataclass(frozen=True)
class Delta:
    """The sorted candidate tables and `catalog._resolve`-shaped counts."""
    data: pa.Table
    changes: pa.Table
    counts: Counter


def eligible(active: GenerationManifest | None, incoming: tuple[ObservationRef, ...],
             selected: tuple[ObservationRef, ...], membership: ObservationRef | None, mode: str,
             context: RunContext) -> bool:
    """C4: new sources added to a clear generation of the same mode, versions and membership authority."""
    if active is None or active.gate != 'clear' or active.quarter_mode != mode:
        return False
    if (active.parser_version, active.schema_version) != (context.parser_version, context.schema_version):
        return False
    base_ids = {ref.source.source_id for ref in active.sources}
    if any(ref.source.source_id in base_ids for ref in incoming) or not all(ref in selected for ref in active.sources):
        return False
    return membership == active.membership_source


def _rank(ref: ObservationRef) -> Rank:
    return int(ref.source.kind == 'quarterly'), ref.source.period, ref.snapshot.received_at.isoformat()


def _best(candidates: list[tuple[Rank, str, bytes]]) -> bytes:
    """`_load_observations`' winner: preference, period and receipt descending, then source_id ascending."""
    by_source = sorted(candidates, key=lambda item: item[1])
    return sorted(by_source, key=lambda item: item[0], reverse=True)[0][2]


def _change(key: Key, kind: str, before, after, reason=None) -> dict:
    return {'change_type': kind, 'cik': key[0], 'archive_path': key[1],
            'before': None if before is None else arrow_row(before),
            'after': None if after is None else arrow_row(after), 'reason': reason}


def _resolve_touched(key: Key, base: bytes | None, unresolved: set[Key], delta: list[tuple[Rank, str, bytes]],
                     rank_of: dict[str, Rank], member: bool, mode: str, has_membership: bool,
                     counts: Counter) -> tuple[bytes | None, dict | None]:
    """`catalog._resolve`'s rules for one touched key: (output row or None, change row or None)."""
    candidates = list(delta)
    if base is not None and key not in unresolved:
        source_id = parse_json(base)['source_id']
        candidates.append((rank_of[source_id], source_id, base))
    proposed = _best(candidates) if candidates else None
    if mode == 'closed' and has_membership and not member:
        proposed = None
    if base is None:
        if proposed is None:
            return None, None
        counts['added'] += 1
        return proposed, _change(key, 'added', None, parse_json(proposed))
    before = parse_json(base)
    if proposed is None or (mode == 'open' and has_membership and not member):
        if mode == 'closed' and has_membership:
            counts['withdrawn'] += 1
            return None, _change(key, 'withdrawn', before, None, WITHDRAWAL_REASON)
        counts['unresolved_absence'] += 1
        counts['retained'] += 1
        return base, _change(key, 'unresolved_absence', before, before, ABSENCE_REASON)
    after = parse_json(proposed)
    if any(before[name] != after[name] for name in BUSINESS_FIELDS):
        counts['updated'] += 1
        return proposed, _change(key, 'updated', before, after)
    if before != after:
        counts['provenance_refreshed'] += 1
    return proposed, None


def _change_keys(table: pa.Table, kind: str) -> tuple[pa.Table, set[Key]]:
    rows = table.filter(pc.equal(table['change_type'], kind))
    return rows, table_keys(rows)


def build_incremental(quarter: str, active: GenerationManifest, selected: tuple[ObservationRef, ...],
                      membership: ObservationRef | None, mode: str, context: RunContext,
                      objects: ObjectStore) -> Delta:
    """C5: the full rebuild's tables, computed from the base tables and the delta rows only."""
    files = {ref.role: ref for ref in active.files}
    base_data, base_changes = generation_table(files['data'], objects), generation_table(files['changes'], objects)
    rank_of = {ref.source.source_id: _rank(ref) for ref in selected}
    base_ids = {ref.source.source_id for ref in active.sources}
    delta: dict[Key, list[tuple[Rank, str, bytes]]] = {}
    for ref in selected:
        if ref.source.source_id in base_ids:
            continue
        for obs in quarter_observations(ref, objects, quarter):
            delta.setdefault((obs.row.cik, obs.row.archive_path), []).append(
                (rank_of[ref.source.source_id], ref.source.source_id, canonical_json(obs.row.to_mapping())))
        _check_deadline(context)
    touched = set(delta)
    unresolved_rows, unresolved = _change_keys(base_changes, 'unresolved_absence')
    members, flips = set(), set()
    if membership is not None:
        # The authority's keys stay in Arrow, so only touched keys and flips become Python keys.
        listed = quarter_key_column(membership, objects, quarter).combine_chunks()
        ordered = sorted(touched)
        hits = pc.is_in(pa.array([cik + KEY_SEPARATOR + path for cik, path in ordered], pa.string()), value_set=listed)
        members = {key for key, hit in zip(ordered, hits.to_pylist()) if hit}
        if mode == 'open':  # Locality exception (A1): untouched base `added` keys that the authority does not list.
            added = base_changes.filter(pc.equal(base_changes['change_type'], 'added'))
            untouched = added.filter(pc.invert(key_mask(added, touched)))
            flips = table_keys(untouched.filter(pc.invert(pc.is_in(key_column(untouched), value_set=listed))))
    base_rows = {}
    for value in base_data.filter(key_mask(base_data, touched | flips)).to_pylist():
        row = IndexRow(**value)
        base_rows[row.cik, row.archive_path] = canonical_json(row.to_mapping())
    counts, outputs, changes = Counter(), [], []
    for key in sorted(touched):
        output, change = _resolve_touched(key, base_rows.get(key), unresolved, delta[key], rank_of,
                                          key in members, mode, membership is not None, counts)
        if output is not None:
            outputs.append(arrow_row(parse_json(output)))
        if change is not None:
            changes.append(change)
    for key in sorted(flips):
        before = parse_json(base_rows[key])
        changes.append(_change(key, 'unresolved_absence', before, before, ABSENCE_REASON))
        counts['unresolved_absence'] += 1
        counts['retained'] += 1
    re_emitted = unresolved_rows.filter(pc.invert(key_mask(unresolved_rows, touched)))
    counts['unresolved_absence'] += re_emitted.num_rows
    counts['retained'] += re_emitted.num_rows
    kept = base_data.filter(pc.invert(key_mask(base_data, touched))).cast(canonical_schema())
    data = pa.concat_tables([kept, pa.Table.from_pylist(outputs, schema=canonical_schema())]).sort_by(
        [('cik', 'ascending'), ('archive_path', 'ascending')])
    change_table = pa.concat_tables([re_emitted.cast(change_schema()),
                                     pa.Table.from_pylist(changes, schema=change_schema())]).sort_by(
        [('cik', 'ascending'), ('archive_path', 'ascending'), ('change_type', 'ascending')])
    counts['data'] = data.num_rows
    return Delta(data, change_table, counts)


def write_table(table: pa.Table, path: Path, schema: pa.Schema, context: RunContext) -> None:
    """`catalog._write_parquet`'s layout: the same writer settings and 8,192-row single-chunk slices (P5)."""
    with pq.ParquetWriter(path, schema, version=PARQUET_VERSION, compression='snappy',
                          use_dictionary=False, use_compliant_nested_type=False) as writer:
        for start in range(0, table.num_rows, BATCH_ROWS):
            writer.write_table(table.slice(start, BATCH_ROWS).combine_chunks())
            _check_deadline(context)
