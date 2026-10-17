"""Strict streaming parsing of the selected retained SEC index families."""
from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from ..models import Source, Snapshot, safe_relative_path
from ..validation import DAILY_HEADER, QUARTERLY_HEADER, INVALID_CONTROL, NON_ASCII
from .contracts import IndexRow, Observation

PARSER_VERSION = 'sec-index-parser-v1'
FIXTURE_PARSERS = frozenset(('fixture-index-parser-v1', 'fixture-index-parser-v2'))
SCHEMA_VERSION = 'sec-index-v1'
FIELD_COUNT = 5
PREAMBLE_LABELS = ('Description:', 'Last Data Received:', 'Comments:', 'Anonymous FTP:', 'Cloud HTTP:')


class ParseError(ValueError):
    def __init__(self, line_number: int, reason: str):
        self.line_number, self.reason = line_number, reason
        super().__init__(f'line {line_number}: {reason}')


def supported_parser(version: str, *, fixture: bool) -> None:
    if version != PARSER_VERSION and not (fixture and version in FIXTURE_PARSERS):
        raise ValueError(f'unsupported parser version: {version}')


def _versions(parser_version: str, schema_version: str) -> None:
    supported_parser(parser_version, fixture=True)
    if schema_version != SCHEMA_VERSION:
        raise ValueError(f'unsupported schema version: {schema_version}')


def parse_fields(fields: tuple[str, str, str, str, str], source: Source, snapshot: Snapshot,
                 *, line_number: int, parser_version: str, schema_version: str) -> Observation:
    _versions(parser_version, schema_version)
    if not isinstance(fields, tuple) or len(fields) != FIELD_COUNT or any(not isinstance(value, str) for value in fields):
        raise ParseError(line_number, 'expected exactly five string fields')
    original_fields = fields
    cik, company, form, text_date, path = (value.strip() for value in fields)
    if not re.fullmatch(r'[0-9]{1,10}', cik) or not company or not form:
        raise ParseError(line_number, 'invalid CIK or empty company/form')
    if any(NON_ASCII.search(value.encode('utf-8')) or INVALID_CONTROL.search(value.encode('utf-8'))
           or '\r' in value or '\n' in value or '\t' in value for value in fields):
        raise ParseError(line_number, 'invalid ASCII/control in fields or archive path')
    normalized_cik = cik.zfill(10)
    pattern = r'[0-9]{4}-[0-9]{2}-[0-9]{2}' if source.kind == 'quarterly' else r'[0-9]{8}'
    if not re.fullmatch(pattern, text_date):
        raise ParseError(line_number, 'unsupported filing-date spelling')
    try:
        filing_date = date.fromisoformat(text_date)
    except ValueError as error:
        raise ParseError(line_number, 'invalid calendar date') from error
    try:
        safe_relative_path(path, 'archive_path')
    except ValueError as error:
        raise ParseError(line_number, 'unsafe archive path') from error
    segments = path.split('/')
    if (len(segments) >= 4 and segments[:2] == ['edgar', 'data'] and
            re.fullmatch(r'[0-9]{1,10}', segments[2]) and segments[2].zfill(10) != normalized_cik):
        raise ParseError(line_number, 'archive path CIK mismatch')
    match = re.fullmatch(r'edgar/data/[0-9]{1,10}/([0-9]{10}-[0-9]{2}-[0-9]{6})\.txt', path)
    accession = match.group(1) if match else None
    try:
        row = IndexRow(normalized_cik, company, form, path, filing_date, accession,
                       source.source_id, snapshot.sha256, parser_version, schema_version)
        return Observation(row, original_fields, line_number)
    except (TypeError, ValueError) as error:
        raise ParseError(line_number, str(error)) from error


def _lines(stream, kind: str):
    for line_number, raw in enumerate(stream, 1):
        if NON_ASCII.search(raw):
            raise ParseError(line_number, 'non-ASCII text')
        if INVALID_CONTROL.search(raw):
            raise ParseError(line_number, 'invalid text control')
        if raw.endswith(b'\n'):
            ending = b'\r\n' if kind == 'quarterly' else b'\n'
            if not raw.endswith(ending):
                raise ParseError(line_number, 'invalid line endings')
            raw = raw[:-len(ending)]
        if b'\r' in raw:
            raise ParseError(line_number, 'invalid line endings')
        yield line_number, raw.decode('ascii')


def _parse_stream(stream, source, snapshot, parser_version, schema_version):
    header = (QUARTERLY_HEADER if source.kind == 'quarterly' else DAILY_HEADER).decode('ascii')
    state, count, last_line = 'preamble', 0, 0
    for line_number, text in _lines(stream, source.kind):
        last_line = line_number
        if state == 'preamble':
            if text == header:
                state = 'separator'
            elif '|' in text or (text.strip() and not text.startswith(PREAMBLE_LABELS)):
                raise ParseError(line_number, 'unexpected preamble or family header')
            continue
        if state == 'separator':
            if not re.fullmatch(r'-+', text):
                raise ParseError(line_number, 'invalid header separator')
            state = 'data'
            continue
        if not text.strip():
            raise ParseError(line_number, 'blank data row')
        if text in (DAILY_HEADER.decode('ascii'), QUARTERLY_HEADER.decode('ascii')):
            raise ParseError(line_number, 'repeated header')
        yield parse_fields(tuple(text.split('|')), source, snapshot, line_number=line_number,
                           parser_version=parser_version, schema_version=schema_version)
        count += 1
    if state == 'preamble':
        raise ParseError(last_line or 1, 'missing family header')
    if state == 'separator':
        raise ParseError(last_line + 1, 'missing header separator')
    if not count:
        raise ParseError(last_line + 1, 'source contains no rows')


def iter_observations(path: Path, source: Source, snapshot: Snapshot, *, parser_version: str,
                      schema_version: str) -> Iterator[Observation]:
    _versions(parser_version, schema_version)
    if source.representation == 'zip':
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != 'master.idx':
                raise ParseError(1, 'unsupported archive member')
            with archive.open(members[0]) as stream:
                yield from _parse_stream(stream, source, snapshot, parser_version, schema_version)
    else:
        with path.open('rb') as stream:
            yield from _parse_stream(stream, source, snapshot, parser_version, schema_version)
