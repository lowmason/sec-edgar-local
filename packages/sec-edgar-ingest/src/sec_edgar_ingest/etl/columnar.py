"""Hash-checked columnar reads for the incremental build (C5) and its equivalence check (C6).

Under S1 a file is trusted by its exact SHA-256 and length once a full check accepted it, so these
readers never re-parse rows. They hold no merge logic, so C5 and C6 stay independent of each other.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..models import quarter_value
from ..storage.contracts import Conflict, ObjectStore
from .contracts import (FileRef, IndexRow, Observation, ObservationRef, canonical_schema, change_schema,
                        observation_schema)
from .transform import _file_identity

Key = tuple[str, str]
KEY_SEPARATOR = '\x1f'  # Never inside a CIK or an archive path.


def _read_table(path: str, sha256: str, byte_count: int, objects: ObjectStore, schema: pa.Schema,
                hash_message: str, schema_message: str) -> pa.Table:
    with TemporaryDirectory(prefix='sec-columnar-read-') as directory:
        target = Path(directory) / 'rows.parquet'
        objects.materialize(path, target)
        if _file_identity(target) != (sha256, byte_count):
            raise Conflict(hash_message)
        with pq.ParquetFile(target) as parquet:
            if not parquet.schema_arrow.equals(schema, check_metadata=True):
                raise ValueError(schema_message)
            return parquet.read()


def generation_table(ref: FileRef, objects: ObjectStore) -> pa.Table:
    """One generation file as an Arrow table, after its exact hash, length, schema and row count."""
    table = _read_table(ref.path, ref.sha256, ref.byte_count, objects,
                        canonical_schema() if ref.role == 'data' else change_schema(),
                        'generation file hash or length differs', 'generation Parquet schema differs')
    if table.num_rows != ref.row_count:
        raise ValueError('generation file row count differs')
    return table


def key_column(table: pa.Table) -> pa.ChunkedArray:
    return pc.binary_join_element_wise(table['cik'], table['archive_path'], KEY_SEPARATOR)


def key_mask(table: pa.Table, keys: Iterable[Key]) -> pa.ChunkedArray:
    """True for each row whose (cik, archive_path) is one of `keys`."""
    value_set = pa.array(sorted(cik + KEY_SEPARATOR + path for cik, path in keys), pa.string())
    return pc.is_in(key_column(table), value_set=value_set)


def table_keys(table: pa.Table) -> set[Key]:
    return set(zip(table['cik'].to_pylist(), table['archive_path'].to_pylist()))


def _quarter_bounds(quarter: str) -> tuple[date, date]:
    year, ordinal = quarter_value(quarter)
    start = date(year, 3 * ordinal - 2, 1)
    return start, date(year + 1, 1, 1) if ordinal == 4 else date(year, 3 * ordinal + 1, 1)


def quarter_observations(ref: ObservationRef, objects: ObjectStore, quarter: str,
                         keys: Iterable[Key] | None = None) -> Iterator[Observation]:
    """One source's rows filed in `quarter` (only `keys` when given), in file order, after the rows file hash."""
    table = _read_table(ref.rows_ref, ref.rows_sha256, ref.rows_bytes, objects, observation_schema(),
                        'observation bytes differ from manifest hash or length', 'observation Parquet schema differs')
    if table.num_rows != ref.source_row_count:
        raise ValueError('observation readback counts differ')
    start, end = _quarter_bounds(quarter)
    mask = pc.and_(pc.greater_equal(table['filing_date'], pa.scalar(start, pa.date32())),
                   pc.less(table['filing_date'], pa.scalar(end, pa.date32())))
    if keys is not None:
        mask = pc.and_(mask, key_mask(table, keys))
    for value in table.filter(mask).to_pylist():
        original = tuple(value.pop('original_fields'))
        line_number = value.pop('line_number')
        yield Observation(IndexRow(**value), original, line_number)
