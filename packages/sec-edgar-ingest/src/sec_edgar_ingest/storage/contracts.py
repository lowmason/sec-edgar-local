"""Durable acquisition primitives and one deployment binding."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from ..config import ACCOUNT_NAME, BINDING_REGISTRY_BLOB, COORDINATION_NAMESPACE, LOCK_BLOB, Settings
from ..models import RAW_SNAPSHOT_PATH, Versioned, canonical_json, quarter_value, require_hash, require_number, require_text, require_utc, safe_relative_path, to_mapping_value

CAS_ATTEMPTS = 5
FILE_CHUNK_BYTES = 1024 * 1024
ATTEMPT_KINDS = frozenset({"Attempt", "TransportAttempt", "Failure"})
APPROVAL_KINDS = frozenset({"WithdrawalApproval", "QuarterRollback", "ApprovalActivation"})
REGISTRY_PATH = "locks/" + BINDING_REGISTRY_BLOB
SENTINEL_PATH = "locks/" + LOCK_BLOB
BoundaryObserver = Callable[[str], None]


class AlreadyExists(Exception):
    """An atomic create lost to an existing identity."""


class Conflict(Exception):
    """A stale version, immutable collision, or unresolved conditional race."""


class OwnershipLost(Exception):
    """The fixed sentinel no longer recognizes the lease handle."""


class ClockUncertain(Exception):
    """Storage server time could not be bounded by the configured uncertainty."""


class StoreMissing(LookupError):
    """An operator open found no store at the configured binding; nothing was created."""


@dataclass(frozen=True, slots=True)
class TimeBounds:
    """Server UTC at one monotonic observation; Date precision and RTT are included."""
    lower: datetime
    upper: datetime
    monotonic_at: float

    def __post_init__(self):
        require_utc(self.lower, "server lower")
        require_utc(self.upper, "server upper")
        require_number(self.monotonic_at, "observation monotonic")
        if self.upper < self.lower:
            raise ClockUncertain("server interval is reversed")

    def at(self, monotonic_now: float) -> "TimeBounds":
        require_number(monotonic_now, "monotonic_now")
        elapsed = monotonic_now - self.monotonic_at
        if elapsed < 0:
            raise ClockUncertain("monotonic clock moved backwards")
        delta = timedelta(seconds=elapsed)
        return TimeBounds(self.lower + delta, self.upper + delta, monotonic_now)


@dataclass(frozen=True, slots=True)
class LeaseHandle:
    owner_id: str
    lease_id: str
    observed_until: datetime
    acquired_upper: datetime | None = None
    ownership_until_upper: datetime | None = None
    observation: TimeBounds | None = None

    def __post_init__(self):
        require_text(self.owner_id, "owner_id")
        require_text(self.lease_id, "lease_id")
        require_utc(self.observed_until, "observed_until")
        for label in ("acquired_upper", "ownership_until_upper"):
            value = getattr(self, label)
            if value is not None:
                require_utc(value, label)
        if self.ownership_until_upper is not None and self.ownership_until_upper < self.observed_until:
            raise ClockUncertain("upper expiry cannot precede lower validity")
        if self.observation is not None and not isinstance(self.observation, TimeBounds):
            raise ValueError("lease observation must be TimeBounds")


class StateStore(Protocol):
    def get(self, kind: str, key: str) -> Versioned | None: ...
    def insert(self, kind: str, key: str, value: dict[str, object]) -> Versioned: ...
    def replace(self, kind: str, key: str, value: dict[str, object], version: str) -> Versioned: ...
    def scan(self, kind: str, filters: dict[str, object]) -> Iterator[Versioned]: ...


class ObjectStore(Protocol):
    def put_once(self, path: str, body: bytes) -> str: ...
    def read(self, path: str) -> bytes: ...
    def materialize(self, path: str, target: Path) -> None: ...
    def stage(self, path: str, body: Path) -> str: ...
    def promote(self, temporary_ref: str, raw_path: str, sha256: str, byte_count: int) -> str: ...
    def verify(self, path: str, sha256: str, byte_count: int) -> None: ...


class LeaseStore(Protocol):
    def acquire(self, owner: str, seconds: int) -> LeaseHandle: ...
    def renew(self, handle: LeaseHandle) -> LeaseHandle: ...
    def release(self, handle: LeaseHandle) -> None: ...
    def assert_owned(self, handle: LeaseHandle) -> None: ...
    def observe_time(self, handle: LeaseHandle | None = None) -> TimeBounds: ...
    def read_journal(self, handle: LeaseHandle) -> Versioned: ...
    def write_journal(self, handle: LeaseHandle, value: dict[str, object], version: str) -> Versioned: ...


def observe(observer: BoundaryObserver | None, point: str) -> None:
    if observer is not None:
        observer(point)


def exact_version(version: str) -> None:
    require_text(version, "version")
    if version == "*":
        raise ValueError("exact service ETag or local revision required")


def identity(kind: str, key: str) -> tuple[str, str]:
    require_text(kind, "kind")
    require_text(key, "key")
    return COORDINATION_NAMESPACE + ":" + kind, key


def table_for(kind: str) -> str:
    if kind == "QuarterPublication":
        return "ActivePointers"
    if kind in APPROVAL_KINDS:
        return "Approvals"
    return "Attempts" if kind in ATTEMPT_KINDS else "SourceState"


def payload_bytes(value: Mapping[str, object]) -> bytes:
    if not isinstance(value, Mapping):
        raise ValueError("state payload must be a mapping")
    return canonical_json(to_mapping_value(value))


def validate_raw_address(path: str, sha256: str, byte_count: int) -> None:
    safe_relative_path(path, "raw_path")
    require_hash(sha256, "sha256")
    require_number(byte_count, "byte_count", integer=True)
    address = RAW_SNAPSHOT_PATH.fullmatch(path)
    if address is None:
        raise ValueError("raw_path must use the approved snapshot address")
    if address[3] != sha256:
        raise Conflict("raw address hash differs from promoted content")
    expected_file = "master.zip" if address[1] == "quarterly" else "master.idx"
    if address[4] != expected_file:
        raise ValueError("raw kind and filename conflict")
    if address[1] == "quarterly":
        quarter_value(address[2])
    elif date.fromisoformat(address[2]).isoformat() != address[2]:
        raise ValueError("raw period must be a canonical date")


def deployment_binding(settings: Settings | None = None, *, root: Path | None = None) -> dict[str, object]:
    """Only shared issuer/storage policy participates, never a command or worker ID."""
    if settings is None:
        sec = {"user_agent": "Lowell Mason sec-edgar-ingest mason.lowell@mac.com", "requests_per_second": 3.0, "max_active_collectors": 1}
        coordination = {"lease_seconds": 60.0, "renew_every_seconds": 20.0, "namespace": COORDINATION_NAMESPACE, "clock_uncertainty_seconds": 2.0}
        storage = {"backend": "local-fixture", "source_table": "SourceState", "attempt_table": "Attempts",
                   "blob_api_version": "2026-04-06", "table_api_version": "2020-12-06",
                   "account_name": None, "blob_endpoint": None, "table_endpoint": None,
                   "raw_container": "raw", "workset_container": "worksets", "quarantine_container": "quarantine",
                   "lock_container": "locks", "lock_blob": LOCK_BLOB, "binding_registry_blob": BINDING_REGISTRY_BLOB}
    else:
        validated = Settings.from_mapping(settings.to_mapping())
        sec = validated.sec.to_mapping()
        coordination = validated.coordination.to_mapping()
        storage = validated.storage.to_mapping()
        storage.pop("root")
    storage["local_root"] = str(root.resolve()) if root is not None else None
    return {"binding_version": "sec-owner-binding-v1", "account": ACCOUNT_NAME,
            "namespace": COORDINATION_NAMESPACE, "sec": sec, "coordination": coordination, "storage": storage}


def blob_address(path: str) -> tuple[str, str]:
    safe_relative_path(path, 'object path')
    root, separator, tail = path.partition('/')
    if not separator:
        raise ValueError('object path requires a root and object key')
    if root in {'raw', 'worksets', 'quarantine', 'locks', 'results',
                'generations', 'manifests', 'approvals'}:
        return root, tail
    if root == 'staging':
        return 'raw', path
    if root == 'runs':
        return 'results', path
    if root in {'observations', 'curated'}:
        return ('manifests' if path.endswith('/manifest.json') else 'generations'), path
    raise ValueError('object path has no accepted Blob binding')
