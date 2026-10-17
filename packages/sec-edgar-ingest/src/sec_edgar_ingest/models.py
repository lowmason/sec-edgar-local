"""Deeply immutable acquisition records and strict detached mapping conversion."""
from __future__ import annotations

import json
import math
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, MISSING, field
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal, Union, get_args, get_origin, get_type_hints

from .urls import canonical_source_url, canonical_listing_url, source_id as url_source_id

FORMAT_VERSION = "sec-acquisition-v1"
SCHEMA_VERSION = "sec-index-v1"
QUARTERLY_ENVELOPE_VERSION = "sec-quarterly-envelope-v1"
DAILY_ENVELOPE_VERSION = "sec-daily-envelope-v1"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
QUARTER_PATTERN = re.compile(r"([0-9]{4})Q([1-4])\Z")
RAW_SNAPSHOT_PATH = re.compile(
    r"raw/sec/indexes/kind=(quarterly|daily)/period=([^/]+)/sha256=([0-9a-f]{64})/(master\.(?:zip|idx))\Z"
)
Priority = Literal["daily", "backfill", "reconciliation"]
Representation = Literal["zip", "idx"]


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value):
    raise ValueError(f"nonfinite JSON constant: {value}")


def parse_json(body: bytes | str) -> object:
    try:
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        return json.loads(body, object_pairs_hook=_unique_json_object,
                          parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
        raise ValueError("invalid UTF-8 JSON document") from error


def require_text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{label} must be a nonempty safe string")


def error_text(exception: BaseException) -> str:
    """The exception's text as one line that `require_text` accepts, for a structured `Error.message`.

    Multi-line SDK errors keep every line, joined by single spaces; empty text falls back to the type name.
    """
    text = "".join(char if char.isprintable() else " " for char in str(exception))
    return " ".join(text.split()) or type(exception).__name__


def require_hash(value: object, label: str) -> None:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lower-case SHA-256 hash")


def require_utc(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be timezone-aware UTC")


def require_number(value: object, label: str, *, minimum: float = 0, positive: bool = False, integer: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if integer and not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if value < minimum or (positive and value <= minimum):
        raise ValueError(f"{label} is outside its allowed range")


def quarter_value(value: str) -> tuple[int, int]:
    match = QUARTER_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if match is None or int(match[1]) == 0:
        raise ValueError("quarter must have YYYYQ1..YYYYQ4 form")
    return int(match[1]), int(match[2])


def quarter_for(day: date) -> str:
    return f"{day.year:04d}Q{(day.month - 1) // 3 + 1}"


def safe_relative_path(value: object, label: str) -> str:
    require_text(value, label)
    path = PurePosixPath(value)
    segments = value.split("/")
    if path.is_absolute() or any(segment in ("", ".", "..") for segment in segments) or any(char in value for char in "\\:%?#"):
        raise ValueError(f"{label} must be a safe relative POSIX path")
    return value


@dataclass(frozen=True, slots=True)
class FrozenMapping(Mapping[str, object]):
    _items: Mapping[str, object]

    def __post_init__(self):
        object.__setattr__(self, "_items", types.MappingProxyType(dict(self._items)))

    def __getitem__(self, key):
        return self._items[key]

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __deepcopy__(self, memo):
        return self


def freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("mapping keys must be strings")
        return FrozenMapping({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("nested values must be finite JSON values")


def to_mapping_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: to_mapping_value(item) for key, item in value.items()}
    if is_dataclass(value):
        return {item.name: to_mapping_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [to_mapping_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _decode_value(annotation: object, value: object, label: str, require_all: bool) -> object:
    origin, arguments = get_origin(annotation), get_args(annotation)
    if annotation is object:
        return freeze(value)
    if origin in (Union, types.UnionType):
        for option in arguments:
            try:
                return _decode_value(option, value, label, require_all)
            except (ValueError, TypeError):
                pass
        raise ValueError(f"{label} has an invalid type")
    if origin is Literal:
        if value not in arguments or not isinstance(value, type(arguments[0])):
            raise ValueError(f"{label} has an unsupported value")
        return value
    if origin is Mapping:
        if not isinstance(value, Mapping):
            raise ValueError(f"{label} must be an object")
        return FrozenMapping({_decode_value(arguments[0], key, label, require_all):
                              _decode_value(arguments[1], item, label, require_all) for key, item in value.items()})
    if origin is tuple:
        if not isinstance(value, (tuple, list)):
            raise ValueError(f"{label} must be an array")
        return tuple(_decode_value(arguments[0], item, label, require_all) for item in value)
    if annotation in (date, datetime):
        if not isinstance(value, str):
            raise ValueError(f"{label} must be an ISO string")
        try:
            return annotation.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a valid ISO string") from error
    if annotation is Path:
        require_text(value, label)
        return Path(value)
    if is_dataclass(annotation):
        return record_from_mapping(annotation, value, require_all=require_all)
    if annotation is type(None):
        if value is not None:
            raise ValueError(f"{label} must be null")
    elif annotation is float:
        require_number(value, label, minimum=-float("inf"))
        return float(value)
    elif type(value) is not annotation:
        raise ValueError(f"{label} has an invalid type")
    return value


def record_from_mapping(record_type: type, value: object, *, require_all: bool = True):
    if not isinstance(value, Mapping):
        raise ValueError(f"{record_type.__name__} must be an object")
    record_fields = {item.name: item for item in fields(record_type)}
    unknown = set(value) - set(record_fields)
    if unknown:
        raise ValueError(f"{record_type.__name__} unknown keys: {sorted(unknown)}")
    required = set(record_fields) if require_all else {
        name for name, item in record_fields.items() if item.default is MISSING and item.default_factory is MISSING
    }
    if required - set(value):
        raise ValueError(f"{record_type.__name__} missing keys: {sorted(required - set(value))}")
    annotations = get_type_hints(record_type)
    return record_type(**{key: _decode_value(annotations[key], item, key, require_all) for key, item in value.items()})


def _typed_value(annotation: object, value: object, label: str) -> object:
    origin, arguments = get_origin(annotation), get_args(annotation)
    if annotation is object:
        return freeze(value)
    if origin in (Union, types.UnionType):
        for option in arguments:
            try:
                return _typed_value(option, value, label)
            except ValueError:
                pass
        raise ValueError(f"{label} has an invalid type")
    if origin is Literal:
        if value not in arguments or not isinstance(value, type(arguments[0])):
            raise ValueError(f"{label} has an unsupported value")
    elif origin is Mapping:
        if not isinstance(value, Mapping):
            raise ValueError(f"{label} must be a mapping")
        return FrozenMapping({_typed_value(arguments[0], key, label): _typed_value(arguments[1], item, label)
                              for key, item in value.items()})
    elif origin is tuple:
        if not isinstance(value, (tuple, list)):
            raise ValueError(f"{label} must be a tuple")
        return tuple(_typed_value(arguments[0], item, label) for item in value)
    elif is_dataclass(annotation):
        if type(value) is not annotation:
            raise ValueError(f"{label} must be {annotation.__name__}")
    elif annotation is float:
        require_number(value, label, minimum=-float("inf"))
        return float(value)
    elif annotation is Path:
        if not isinstance(value, Path):
            raise ValueError(f"{label} must be a Path")
    elif type(value) is not annotation:
        raise ValueError(f"{label} has an invalid type")
    return value


def validate_record_fields(record: object) -> None:
    annotations = get_type_hints(type(record))
    for item in fields(record):
        object.__setattr__(record, item.name, _typed_value(annotations[item.name], getattr(record, item.name), item.name))


def require_envelope(representation: str, envelope_version: str) -> None:
    expected = {"zip": QUARTERLY_ENVELOPE_VERSION, "idx": DAILY_ENVELOPE_VERSION}
    if representation not in expected or envelope_version != expected[representation]:
        raise ValueError("unsupported representation/envelope_version combination")


class Record:
    def __post_init__(self):
        validate_record_fields(self)

    def to_mapping(self) -> dict[str, object]:
        return {item.name: to_mapping_value(getattr(self, item.name)) for item in fields(self)}

    @classmethod
    def from_mapping(cls, value: dict[str, object]):
        return record_from_mapping(cls, value)


@dataclass(frozen=True, slots=True)
class Source(Record):
    source_id: str
    canonical_url: str
    kind: Literal["quarterly", "daily"]
    period: str
    representation: Representation

    def __post_init__(self):
        validate_record_fields(self)
        if self.kind not in ("quarterly", "daily"):
            raise ValueError("unsupported source kind")
        url = canonical_source_url(self.canonical_url, self.kind)
        if url != self.canonical_url or url_source_id(url) != self.source_id:
            raise ValueError("source identity does not match canonical URL")
        expected_representation = "zip" if self.kind == "quarterly" else "idx"
        if self.representation != expected_representation:
            raise ValueError("source representation does not match kind")
        if self.kind == "quarterly":
            year, quarter = quarter_value(self.period)
            if f"/{year}/QTR{quarter}/" not in url:
                raise ValueError("source period does not match URL")
        else:
            try:
                day = date.fromisoformat(self.period)
            except (ValueError, TypeError) as error:
                raise ValueError("daily period must be an ISO date") from error
            if day.isoformat() != self.period or not url.endswith(f"/master.{day:%Y%m%d}.idx"):
                raise ValueError("source date does not match URL")


@dataclass(frozen=True, slots=True)
class RunContext(Record):
    run_id: str
    execution_id: str
    command: str
    attempt_id: str
    image_digest: str
    parser_version: str
    schema_version: str
    config_sha256: str
    started_at: datetime
    deadline: datetime
    priority: Priority
    effective_config: Mapping[str, object] = field(default_factory=dict)
    pinned_on: date | None = None

    def __post_init__(self):
        validate_record_fields(self)
        for label in ("run_id", "execution_id", "command", "attempt_id", "parser_version"):
            require_text(getattr(self, label), label)
        if IMAGE_PATTERN.fullmatch(self.image_digest) is None:
            raise ValueError("image_digest must be immutable sha256")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        require_hash(self.config_sha256, "config_sha256")
        require_utc(self.started_at, "started_at")
        require_utc(self.deadline, "deadline")
        if self.deadline <= self.started_at:
            raise ValueError("deadline must be after started_at")
        if self.priority not in ("daily", "backfill", "reconciliation"):
            raise ValueError("unsupported priority")
        object.__setattr__(self, "effective_config", freeze(self.effective_config))


@dataclass(frozen=True, slots=True)
class Error(Record):
    code: str
    message: str
    retryable: bool
    source_id: str | None
    details: Mapping[str, object]

    def __post_init__(self):
        validate_record_fields(self)
        require_text(self.code, "code")
        require_text(self.message, "message")
        if type(self.retryable) is not bool:
            raise ValueError("retryable must be boolean")
        if self.source_id is not None:
            require_hash(self.source_id, "source_id")
        object.__setattr__(self, "details", freeze(self.details))


@dataclass(frozen=True, slots=True)
class DirectoryOutcome(Record):
    url: str
    period: str
    outcome: Literal["available", "no_new_sources", "discovery_failed"]
    listing_sha256: str | None
    source_ids: tuple[str, ...]
    error: Error | None

    def __post_init__(self):
        validate_record_fields(self)
        if canonical_listing_url(self.url) != self.url:
            raise ValueError("directory URL must be canonical")
        require_text(self.period, "period")
        if self.outcome not in ("available", "no_new_sources", "discovery_failed"):
            raise ValueError("unsupported directory outcome")
        if self.listing_sha256 is not None:
            require_hash(self.listing_sha256, "listing_sha256")
        for identity in self.source_ids:
            require_hash(identity, "source_id")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("duplicate directory source IDs")
        object.__setattr__(self, "source_ids", tuple(sorted(self.source_ids)))
        if self.outcome == "discovery_failed":
            if self.error is None or self.source_ids or self.listing_sha256 is not None:
                raise ValueError("failed discovery requires error and no accepted listing")
        elif self.error is not None or self.listing_sha256 is None:
            raise ValueError("successful discovery requires a listing hash and no error")


@dataclass(frozen=True, slots=True)
class SourceWorkset(Record):
    workset_id: str
    context: RunContext
    pinned_end_quarter: str
    discovery_id: str
    members: tuple[Source, ...]
    directories: tuple[DirectoryOutcome, ...]
    discovery_complete: bool
    overlap_from: date
    acquisition_mode: Literal["reuse_accepted", "refresh"]

    def __post_init__(self):
        validate_record_fields(self)
        object.__setattr__(self, "members", tuple(self.members))
        object.__setattr__(self, "directories", tuple(self.directories))


@dataclass(frozen=True, slots=True)
class Snapshot(Record):
    source_id: str
    sha256: str
    raw_path: str
    byte_count: int
    received_at: datetime
    validators: Mapping[str, str]
    representation: Representation
    envelope_version: str

    def __post_init__(self):
        validate_record_fields(self)
        require_hash(self.source_id, "source_id")
        require_hash(self.sha256, "sha256")
        safe_relative_path(self.raw_path, "raw_path")
        address = RAW_SNAPSHOT_PATH.fullmatch(self.raw_path)
        if address is None or address[3] != self.sha256:
            raise ValueError("raw_path must use the approved index layout and exact snapshot hash")
        expected_kind = "quarterly" if self.representation == "zip" else "daily"
        if address[1] != expected_kind or address[4] != f"master.{self.representation}":
            raise ValueError("raw_path kind/file conflicts with representation")
        if address[1] == "quarterly":
            quarter_value(address[2])
        else:
            try:
                period = date.fromisoformat(address[2])
            except ValueError as error:
                raise ValueError("raw_path daily period must be a valid ISO date") from error
            if period.isoformat() != address[2]:
                raise ValueError("raw_path daily period must be a canonical ISO date")
        require_number(self.byte_count, "byte_count", integer=True)
        require_utc(self.received_at, "received_at")
        if self.representation not in ("zip", "idx"):
            raise ValueError("unsupported representation")
        require_envelope(self.representation, self.envelope_version)
        if self.raw_path.endswith((".zip", ".idx")) and not self.raw_path.endswith("." + self.representation):
            raise ValueError("raw_path extension conflicts with representation")
        if not isinstance(self.validators, Mapping) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in self.validators.items()):
            raise ValueError("validators must be string mappings")
        object.__setattr__(self, "validators", freeze(self.validators))


@dataclass(frozen=True, slots=True)
class Binding(Record):
    source_workset_id: str
    source_id: str
    snapshot_sha256: str

    def __post_init__(self):
        validate_record_fields(self)
        for label in ("source_workset_id", "source_id", "snapshot_sha256"):
            require_hash(getattr(self, label), label)


@dataclass(frozen=True, slots=True)
class SnapshotWorkset(Record):
    workset_id: str
    source_workset_id: str
    context: RunContext
    snapshots: tuple[Snapshot, ...]
    pinned_end_quarter: str
    directories: tuple[DirectoryOutcome, ...]
    overlap_from: date
    acquisition_mode: Literal["reuse_accepted", "refresh"] = "reuse_accepted"

    def __post_init__(self):
        validate_record_fields(self)
        object.__setattr__(self, "snapshots", tuple(self.snapshots))
        object.__setattr__(self, "directories", tuple(self.directories))


@dataclass(frozen=True, slots=True)
class CommandResult(Record):
    context: RunContext
    outcome: str
    source_workset_ref: str | None
    snapshot_workset_ref: str | None
    discovered: int
    downloaded: int
    unchanged: int
    pending: int
    failed: int
    quarantined: int
    gaps: tuple[Error, ...]
    started_at: datetime
    ended_at: datetime

    def __post_init__(self):
        validate_record_fields(self)
        require_text(self.outcome, "outcome")
        for label in ("discovered", "downloaded", "unchanged", "pending", "failed", "quarantined"):
            require_number(getattr(self, label), label, integer=True)
        require_utc(self.started_at, "started_at")
        require_utc(self.ended_at, "ended_at")
        if self.ended_at < self.started_at:
            raise ValueError("ended_at precedes started_at")
        object.__setattr__(self, "gaps", tuple(self.gaps))

    def to_json(self) -> bytes:
        return canonical_json(self.to_mapping())

    @classmethod
    def from_json(cls, body: bytes) -> CommandResult:
        if not isinstance(body, bytes):
            raise ValueError("result body must be bytes")
        return cls.from_mapping(parse_json(body))


@dataclass(frozen=True, slots=True)
class Versioned(Record):
    value: Mapping[str, object]
    version: str

    def __post_init__(self):
        validate_record_fields(self)
        require_text(self.version, "version")
        if self.version == "*":
            raise ValueError("version must be an actual opaque revision")
        object.__setattr__(self, "value", freeze(self.value))


@dataclass(frozen=True, slots=True)
class QueueTicket(Record):
    ticket_id: str
    owner_id: str
    priority: Priority
    enqueued_at: datetime
    expires_at: datetime

    def __post_init__(self):
        validate_record_fields(self)
        require_text(self.ticket_id, "ticket_id")
        require_text(self.owner_id, "owner_id")
        if self.priority not in ("daily", "backfill", "reconciliation"):
            raise ValueError("unsupported queue priority")
        require_utc(self.enqueued_at, "enqueued_at")
        require_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.enqueued_at:
            raise ValueError("queue ticket must have a finite positive lifetime")


@dataclass(frozen=True, slots=True)
class Permit(Record):
    owner_id: str
    epoch: int
    request_id: str
    must_start_before: datetime
    must_end_by: datetime
    takeover_after: datetime
    start_before_mono: float
    deadline_mono: float
    next_allowed_at: datetime | None = None

    def __post_init__(self):
        validate_record_fields(self)
        require_text(self.owner_id, "owner_id")
        require_text(self.request_id, "request_id")
        require_number(self.epoch, "epoch", integer=True)
        for label in ("must_start_before", "must_end_by", "takeover_after"):
            require_utc(getattr(self, label), label)
        if not self.must_start_before <= self.must_end_by <= self.takeover_after:
            raise ValueError("permit ownership windows are reversed")
        if self.next_allowed_at is not None:
            require_utc(self.next_allowed_at, "next_allowed_at")
        require_number(self.start_before_mono, "start_before_mono")
        require_number(self.deadline_mono, "deadline_mono")
        if self.deadline_mono < self.start_before_mono:
            raise ValueError("permit monotonic windows are reversed")


@dataclass(frozen=True, slots=True)
class BodyReceipt(Record):
    url: str
    status: int
    headers: Mapping[str, str]
    temporary_path: Path
    received_at: datetime
    byte_count: int
    sha256: str
    complete: bool
    error: Error | None

    def __post_init__(self):
        validate_record_fields(self)
        require_text(self.url, "url")
        require_number(self.status, "status", integer=True)
        if self.status != 0 and not 100 <= self.status <= 599:
            raise ValueError("status must be an HTTP status or zero for no response")
        require_number(self.byte_count, "byte_count", integer=True)
        require_hash(self.sha256, "sha256")
        require_utc(self.received_at, "received_at")
        if type(self.complete) is not bool:
            raise ValueError("complete must be boolean")
        if not isinstance(self.headers, Mapping) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in self.headers.items()):
            raise ValueError("headers must be string mappings")
        object.__setattr__(self, "headers", freeze(self.headers))
        object.__setattr__(self, "temporary_path", Path(self.temporary_path))


@dataclass(frozen=True, slots=True)
class ValidatedBody(Record):
    receipt: BodyReceipt
    representation: Representation
    envelope_version: str
    expanded_byte_count: int

    def __post_init__(self):
        validate_record_fields(self)
        if self.representation not in ("zip", "idx"):
            raise ValueError("unsupported representation")
        require_envelope(self.representation, self.envelope_version)
        require_number(self.expanded_byte_count, "expanded_byte_count", integer=True)
        if not self.receipt.complete or self.receipt.error is not None:
            raise ValueError("validated body requires a complete receipt")
