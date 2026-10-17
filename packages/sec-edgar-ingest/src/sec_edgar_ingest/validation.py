"""Validate selected acquisition envelopes while retaining the original entity bytes."""
from __future__ import annotations

import hashlib
import re
import stat
import struct
import zipfile
import zlib

from .config import Settings
from .models import BodyReceipt, DAILY_ENVELOPE_VERSION, QUARTERLY_ENVELOPE_VERSION, Source, ValidatedBody

STREAM_BYTES = 65536
LOCAL_FILE_HEADER = struct.Struct("<4s5H3I2H")
DAILY_HEADER = b"CIK|Company Name|Form Type|Date Filed|File Name"
QUARTERLY_HEADER = b"CIK|Company Name|Form Type|Date Filed|Filename"
DENIAL_MARKERS = (b"your request originates from an undeclared automated tool",
                  b"request rate threshold exceeded", b"access denied")
NON_ASCII = re.compile(rb"[\x80-\xff]")
INVALID_CONTROL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ValidationError(ValueError):
    def __init__(self, code: str, receipt: BodyReceipt):
        self.code, self.receipt = code, receipt
        super().__init__(code)


def header_value(headers, name: str) -> str | None:
    values = [value for key, value in headers.items() if key.lower() == name.lower()]
    if len(set(values)) > 1:
        raise ValueError("conflicting response header values")
    return values[0] if values else None


def advertised_length(headers) -> int | None:
    value = header_value(headers, "Content-Length")
    if value is None:
        return None
    if re.fullmatch(r"[0-9]+", value.strip()) is None:
        raise ValueError("invalid Content-Length")
    return int(value.strip())


def is_denial(receipt: BodyReceipt) -> bool:
    if receipt.status == 403:
        return True
    with receipt.temporary_path.open("rb") as stream:
        prefix = stream.read(STREAM_BYTES).lower()
    return b"<" in prefix and any(marker in prefix for marker in DENIAL_MARKERS)


class _TextEnvelope:
    """Remember envelope facts, never accumulate or normalize row contents."""
    def __init__(self, kind: str, receipt: BodyReceipt):
        self.kind, self.receipt = kind, receipt
        self.header = QUARTERLY_HEADER if kind == "quarterly" else DAILY_HEADER
        self.header_seen = self.data_seen = False
        self._reset_line()

    def _reset_line(self):
        self.prefix = bytearray()
        self.line_length = 0
        self.has_content = False
        self.only_separator = True
        self.pending_cr = False

    def feed(self, body: bytes) -> None:
        if NON_ASCII.search(body):
            raise ValidationError("non_ascii", self.receipt)
        if INVALID_CONTROL.search(body):
            raise ValidationError("invalid_text_control", self.receipt)
        pieces = body.split(b"\n")
        for ordinal, piece in enumerate(pieces):
            ended = ordinal < len(pieces)-1
            if self.pending_cr and piece:
                raise ValidationError("invalid_line_endings", self.receipt)
            if b"\r" in piece:
                if self.kind == "daily" or not piece.endswith(b"\r") or piece.count(b"\r") != 1:
                    raise ValidationError("invalid_line_endings", self.receipt)
                piece = piece[:-1]
                self.pending_cr = True
            self.prefix.extend(piece[:max(0, len(self.header)+1-len(self.prefix))])
            self.line_length += len(piece)
            self.has_content |= bool(piece.strip(b" \t"))
            self.only_separator &= not bool(piece.strip(b"- \t"))
            if ended:
                if self.kind == "quarterly" and not self.pending_cr:
                    raise ValidationError("invalid_line_endings", self.receipt)
                self._finish_line()

    def _finish_line(self):
        if self.line_length == len(self.header) and self.prefix == self.header:
            if self.header_seen:
                raise ValidationError("duplicate_header", self.receipt)
            self.header_seen = True
        elif self.header_seen and self.has_content and not self.only_separator:
            self.data_seen = True
        self._reset_line()

    def finish(self):
        if self.pending_cr:
            raise ValidationError("invalid_line_endings", self.receipt)
        if self.line_length:
            self._finish_line()
        if not self.header_seen:
            raise ValidationError("missing_header", self.receipt)
        if not self.data_seen:
            raise ValidationError("header_without_data", self.receipt)


def _check_transport(receipt: BodyReceipt, settings: Settings, kind: str) -> None:
    if receipt.status != 200 or not receipt.complete or receipt.error is not None:
        raise ValidationError("incomplete_transport", receipt)
    if receipt.byte_count == 0:
        raise ValidationError("empty_body", receipt)
    try:
        encoding = header_value(receipt.headers, "Content-Encoding")
        length = advertised_length(receipt.headers)
        transfer = header_value(receipt.headers, "Transfer-Encoding")
        content_type = header_value(receipt.headers, "Content-Type")
    except ValueError as error:
        raise ValidationError("invalid_content_length" if "Content-Length" in str(error) else "conflicting_headers", receipt) from error
    if encoding and encoding.strip().lower() != "identity":
        raise ValidationError("unsupported_content_encoding", receipt)
    if transfer and transfer.strip().lower() != "chunked":
        raise ValidationError("unsupported_transfer_encoding", receipt)
    if transfer and length is not None:
        raise ValidationError("ambiguous_transfer_framing", receipt)
    allowed_types = {"application/octet-stream", "application/zip", "application/x-zip-compressed"} if kind == "quarterly" else {"application/octet-stream", "text/plain"}
    if content_type:
        media_type, *parameters = content_type.lower().split(";")
        if media_type.strip() not in allowed_types or any(parameter.strip() not in ("charset=us-ascii", "charset=ascii") for parameter in parameters):
            raise ValidationError("unsupported_content_type", receipt)
    if receipt.byte_count > settings.http.max_received_bytes or (length is not None and length > settings.http.max_received_bytes):
        raise ValidationError("received_limit", receipt)
    count, digest = 0, hashlib.sha256()
    with receipt.temporary_path.open("rb") as stream:
        prefix = stream.read(STREAM_BYTES)
        chunk = prefix
        while chunk:
            count += len(chunk)
            if count > settings.http.max_received_bytes:
                raise ValidationError("received_limit", receipt)
            digest.update(chunk)
            chunk = stream.read(STREAM_BYTES)
    if count != receipt.byte_count or digest.hexdigest() != receipt.sha256:
        raise ValidationError("receipt_mismatch", receipt)
    if length is not None and length != count:
        raise ValidationError("content_length_mismatch", receipt)
    lowered = prefix.lstrip().lower()
    if lowered.startswith((b"<!doctype", b"<html", b"<?xml")) or is_denial(receipt):
        raise ValidationError("unexpected_page", receipt)


def _scan_text(stream, source: Source, receipt: BodyReceipt, limit: int) -> int:
    scanner, count = _TextEnvelope(source.kind, receipt), 0
    while body := stream.read(min(STREAM_BYTES, limit-count+1)):
        count += len(body)
        if count > limit:
            raise ValidationError("expanded_limit", receipt)
        scanner.feed(body)
    scanner.finish()
    return count


def _scan_zip_member(archive, member, source: Source, receipt: BodyReceipt, limit: int) -> int:
    # ZipExtFile truncates at the advertised expanded size, so it cannot prove full DEFLATE EOF/CRC.
    with archive.open(member):
        pass  # Retain stdlib local-name, unsupported-flag and overlapping-member checks.
    scanner = _TextEnvelope(source.kind, receipt)
    decoder, count, checksum = zlib.decompressobj(-zlib.MAX_WBITS), 0, 0
    with receipt.temporary_path.open("rb") as stream:
        stream.seek(member.header_offset)
        header = stream.read(LOCAL_FILE_HEADER.size)
        if len(header) != LOCAL_FILE_HEADER.size:
            raise ValidationError("invalid_archive", receipt)
        (signature, _version, flags, method, _dos_time, _dos_date, _crc,
         _compressed, _expanded, name_size, extra_size) = LOCAL_FILE_HEADER.unpack(header)
        if signature != b"PK\x03\x04" or method != member.compress_type or flags != member.flag_bits:
            raise ValidationError("invalid_archive", receipt)
        stream.seek(name_size+extra_size, 1)
        if stream.tell()+member.compress_size > receipt.byte_count:
            raise ValidationError("invalid_archive", receipt)
        remaining, tail = member.compress_size, b""
        while True:
            chunk = tail
            if not chunk and remaining:
                chunk = stream.read(min(STREAM_BYTES, remaining))
                if not chunk:
                    raise ValidationError("invalid_archive", receipt)
                remaining -= len(chunk)
            body = decoder.decompress(chunk, min(STREAM_BYTES, limit-count+1))
            count += len(body)
            if count > limit:
                raise ValidationError("expanded_limit", receipt)
            checksum = zlib.crc32(body, checksum)
            scanner.feed(body)
            tail = decoder.unconsumed_tail
            if decoder.eof:
                if remaining or tail or decoder.unused_data:
                    raise ValidationError("invalid_archive", receipt)
                break
            if not chunk and not body:
                raise ValidationError("invalid_archive", receipt)
    if count != member.file_size or checksum != member.CRC:
        raise ValidationError("invalid_archive", receipt)
    scanner.finish()
    return count


def validate_envelope(source: Source, receipt: BodyReceipt, settings: Settings) -> ValidatedBody:
    if receipt.url != source.canonical_url:
        raise ValidationError("source_url_mismatch", receipt)
    _check_transport(receipt, settings, source.kind)
    if source.representation == "idx":
        with receipt.temporary_path.open("rb") as stream:
            count = _scan_text(stream, source, receipt, settings.http.max_expanded_bytes)
        return ValidatedBody(receipt, "idx", DAILY_ENVELOPE_VERSION, count)
    try:
        with zipfile.ZipFile(receipt.temporary_path) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise ValidationError("unsupported_archive", receipt)
            member = members[0]
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (member.filename != "master.idx" or member.orig_filename != "master.idx" or member.is_dir() or member.flag_bits & 1
                    or member.compress_type != zipfile.ZIP_DEFLATED or mode not in (0, stat.S_IFREG)):
                raise ValidationError("unsupported_archive", receipt)
            if member.file_size > settings.http.max_expanded_bytes:
                raise ValidationError("expanded_limit", receipt)
            count = _scan_zip_member(archive, member, source, receipt, settings.http.max_expanded_bytes)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, OSError) as error:
        raise ValidationError("invalid_archive", receipt) from error
    return ValidatedBody(receipt, "zip", QUARTERLY_ENVELOPE_VERSION, count)
