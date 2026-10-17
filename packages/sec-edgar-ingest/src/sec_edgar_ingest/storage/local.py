"""SQLite CAS and durable write-once files for offline acquisition fixtures."""
from __future__ import annotations

import errno
import hashlib
import io
import math
import os
import sqlite3
import stat
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import LOCK_BLOB
from ..models import Versioned, parse_json, require_hash, require_number, require_text, require_utc, safe_relative_path
from .contracts import (AlreadyExists, BoundaryObserver, CAS_ATTEMPTS, ClockUncertain, Conflict, FILE_CHUNK_BYTES,
                        LeaseHandle, OwnershipLost, StoreMissing, TimeBounds, REGISTRY_PATH, SENTINEL_PATH,
                        deployment_binding, exact_version, identity, observe, payload_bytes, table_for,
                        validate_raw_address)

DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW
# Every state connection waits this long for a lock. Creating a store also retries its WAL switch until then,
# because SQLite returns BUSY for that switch at once instead of waiting.
SQLITE_BUSY_TIMEOUT_SECONDS = 5
SQLITE_INIT_FIRST_PAUSE_SECONDS = 0.001
SQLITE_INIT_MAX_PAUSE_SECONDS = 0.05


class LocalObjectStore:
    def __init__(self, root: Path, *, observer: BoundaryObserver | None = None, binding=None, create: bool = True):
        self.root = Path(root).resolve()
        self.directory = self.root / "objects"
        self.observer = observer
        expected = payload_bytes(binding or deployment_binding(root=self.root))
        if not create:
            # Operator opens never mkdir or write: a write-once probe would still leave a temp file behind.
            if not self.directory.is_dir() or self.directory.is_symlink():
                raise StoreMissing(f"no local store exists at {self.root}")
            try:
                registry = self.read(REGISTRY_PATH)
            except FileNotFoundError as error:
                raise StoreMissing(f"local store at {self.root} has no deployment binding") from error
            if registry != expected:
                raise Conflict("local store binding differs from this deployment")
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self.directory.mkdir(exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError("object root must not be a symlink")
        self._write_once(REGISTRY_PATH, io.BytesIO(expected), notify=False)

    @contextmanager
    def _parent(self, path: str, *, create: bool = False):
        segments = safe_relative_path(path, "object path").split("/")
        descriptor = os.open(self.directory, DIRECTORY_FLAGS)
        try:
            for segment in segments[:-1]:
                if create:
                    try:
                        os.mkdir(segment, dir_fd=descriptor)
                        os.fsync(descriptor)
                    except FileExistsError:
                        pass
                try:
                    child = os.open(segment, DIRECTORY_FLAGS, dir_fd=descriptor)
                except OSError as error:
                    if error.errno in (errno.ENOTDIR, errno.ELOOP):
                        raise ValueError("object parents must be real directories") from error
                    raise
                os.close(descriptor)
                descriptor = child
            yield descriptor, segments[-1]
        finally:
            os.close(descriptor)

    @contextmanager
    def _open(self, path: str):
        with self._parent(path) as (parent, name):
            try:
                descriptor = os.open(name, FILE_FLAGS, dir_fd=parent)
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise ValueError("object must not be a symlink") from error
                raise
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("object must be a regular file")
                yield stream

    def _write_once(self, path: str, stream, *, notify: bool = True) -> str:
        with self._parent(path, create=True) as (parent, name):
            temporary = ".pending-" + uuid.uuid4().hex
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            digest, byte_count = hashlib.sha256(), 0
            try:
                with os.fdopen(descriptor, "wb") as target:
                    while chunk := stream.read(FILE_CHUNK_BYTES):
                        target.write(chunk)
                        digest.update(chunk)
                        byte_count += len(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                if notify:
                    observe(self.observer, "object.after_fsync")
                    observe(self.observer, "object.before_link")
                try:
                    os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                except FileExistsError:
                    self.verify(path, digest.hexdigest(), byte_count)
                os.fsync(parent)
                if notify:
                    observe(self.observer, "object.after_link")
            finally:
                os.unlink(temporary, dir_fd=parent)
                os.fsync(parent)
        return path

    def put_once(self, path: str, body: bytes) -> str:
        if not isinstance(body, bytes):
            raise ValueError("immutable object body must be bytes")
        return self._write_once(path, io.BytesIO(body))

    def read(self, path: str) -> bytes:
        with self._open(path) as stream:
            return stream.read()

    def materialize(self, path: str, target: Path) -> None:
        target = Path(target)
        destination = target.open('xb')
        try:
            with destination, self._open(path) as source:
                while chunk := source.read(FILE_CHUNK_BYTES):
                    destination.write(chunk)
        except BaseException:
            target.unlink()
            raise

    def stage(self, path: str, body: Path) -> str:
        with Path(body).open("rb") as stream:
            return self._write_once(path, stream)

    def verify(self, path: str, sha256: str, byte_count: int) -> None:
        require_hash(sha256, "sha256")
        require_number(byte_count, "byte_count", integer=True)
        digest, actual_bytes = hashlib.sha256(), 0
        with self._open(path) as stream:
            while chunk := stream.read(FILE_CHUNK_BYTES):
                digest.update(chunk)
                actual_bytes += len(chunk)
        if digest.hexdigest() != sha256 or actual_bytes != byte_count:
            raise Conflict("immutable object differs from expected hash or length")

    def promote(self, temporary_ref: str, raw_path: str, sha256: str, byte_count: int) -> str:
        validate_raw_address(raw_path, sha256, byte_count)
        self.verify(temporary_ref, sha256, byte_count)
        observe(self.observer, "object.before_promote")
        with self._open(temporary_ref) as stream:
            reference = self._write_once(raw_path, stream)
        self.verify(reference, sha256, byte_count)
        observe(self.observer, "object.after_promote")
        return reference


class LocalStateStore:
    def __init__(self, root: Path, *, page_size: int = 128, observer: BoundaryObserver | None = None, binding=None,
                 create: bool = True):
        require_number(page_size, "page_size", positive=True, integer=True)
        self.root = Path(root).resolve()
        LocalObjectStore(self.root, binding=binding, create=create)
        self.database = self.root / "state.sqlite3"
        if self.database.is_symlink():
            raise ValueError("state database must not be a symlink")
        self.page_size = page_size
        self.observer = observer
        self._closed = False
        if not create:
            if not self.database.is_file():
                raise StoreMissing(f"local store at {self.root} has no state database")
            return
        deadline = time.monotonic() + SQLITE_BUSY_TIMEOUT_SECONDS
        pause = SQLITE_INIT_FIRST_PAUSE_SECONDS
        while True:
            try:
                with self._connection() as connection:
                    if connection.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                        mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                        if mode != "wal":
                            raise Conflict("local state did not confirm WAL mode")
                    connection.execute("CREATE TABLE IF NOT EXISTS records (table_name TEXT NOT NULL, partition TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, version TEXT NOT NULL, PRIMARY KEY(table_name, partition, key))")
                    connection.commit()
                break
            except sqlite3.OperationalError as error:
                # Switching to WAL upgrades a read lock, so SQLite returns BUSY at once, skipping the busy handler
                # to avoid deadlock, while another initializer holds RESERVED. Closing the losing connection
                # releases its read lock; pause, then retry until the busy timeout every other lock wait gets.
                if error.sqlite_errorcode & 0xff != sqlite3.SQLITE_BUSY or time.monotonic() + pause > deadline:
                    raise
            time.sleep(pause)
            pause = min(2 * pause, SQLITE_INIT_MAX_PAUSE_SECONDS)

    @contextmanager
    def _connection(self):
        if self._closed:
            raise ValueError("state client is closed")
        connection = sqlite3.connect(self.database, timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
        finally:
            connection.close()

    def close(self) -> None:
        self._closed = True

    def get(self, kind: str, key: str) -> Versioned | None:
        partition, key = identity(kind, key)
        with self._connection() as connection:
            row = connection.execute("SELECT value, version FROM records WHERE table_name=? AND partition=? AND key=?", (table_for(kind), partition, key)).fetchone()
        return None if row is None else Versioned(parse_json(row[0]), row[1])

    def insert(self, kind: str, key: str, value: dict[str, object]) -> Versioned:
        partition, key = identity(kind, key)
        body, version = payload_bytes(value).decode("utf-8"), uuid.uuid4().hex
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?)", (table_for(kind), partition, key, body, version))
                connection.commit()
        except sqlite3.IntegrityError as error:
            raise AlreadyExists("state identity already exists") from error
        observe(self.observer, "state.after_insert")
        return Versioned(parse_json(body), version)

    def replace(self, kind: str, key: str, value: dict[str, object], version: str) -> Versioned:
        exact_version(version)
        partition, key = identity(kind, key)
        body, next_version = payload_bytes(value).decode("utf-8"), uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute("UPDATE records SET value=?, version=? WHERE table_name=? AND partition=? AND key=? AND version=?", (body, next_version, table_for(kind), partition, key, version)).rowcount
            if count != 1:
                connection.rollback()
                raise Conflict("state row absent or revision changed")
            connection.commit()
        observe(self.observer, "state.after_replace")
        return Versioned(parse_json(body), next_version)

    def scan(self, kind: str, filters: dict[str, object]) -> Iterator[Versioned]:
        partition, _ = identity(kind, "scan")
        detached_filters = parse_json(payload_bytes(filters))
        last_key = ""
        while True:
            with self._connection() as connection:
                rows = connection.execute("SELECT key, value, version FROM records WHERE table_name=? AND partition=? AND key>? ORDER BY key LIMIT ?", (table_for(kind), partition, last_key, self.page_size)).fetchall()
            if not rows:
                return
            for key, body, version in rows:
                value = parse_json(body)
                if all(name in value and value[name] == expected for name, expected in detached_filters.items()):
                    yield Versioned(value, version)
                last_key = key


class _WallClock:
    precision_seconds = 0.000001

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


class LocalLeaseStore:
    def __init__(self, root: Path, *, clock=None, observer: BoundaryObserver | None = None, binding=None):
        self.store = LocalStateStore(root, observer=observer, binding=binding)
        self.objects = LocalObjectStore(root, binding=binding)
        try:
            self.objects.read(SENTINEL_PATH)
        except FileNotFoundError:
            try:
                self.objects.put_once(SENTINEL_PATH, b"{}")
            except Conflict:
                self.objects.read(SENTINEL_PATH)
        self.clock = clock or _WallClock()
        self.observer = observer
        # A private sentinel table shares the lease transaction, never a Table/StateStore pacing row.
        with self.store._connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS sentinel_journal (identity TEXT PRIMARY KEY, value TEXT NOT NULL, version TEXT NOT NULL)")
            connection.execute("INSERT OR IGNORE INTO sentinel_journal VALUES (?, ?, ?)",
                               (LOCK_BLOB, "{}", uuid.uuid4().hex))
            connection.commit()

    def close(self) -> None:
        self.store.close()

    def acquire(self, owner: str, seconds: int) -> LeaseHandle:
        require_text(owner, "owner")
        require_number(seconds, "lease seconds", positive=True, integer=True)
        for _ in range(CAS_ATTEMPTS):
            now = self.clock.now()
            require_utc(now, "clock.now")
            current = self.store.get("_Lease", LOCK_BLOB)
            if current is not None and datetime.fromisoformat(current.value["expires_at"]) > now:
                raise Conflict("fixed sentinel is already leased")
            lease_id = str(uuid.uuid4())
            until = now + timedelta(seconds=seconds)
            value = {"owner_id": owner, "lease_id": lease_id, "seconds": seconds, "expires_at": until.isoformat()}
            try:
                if current is None:
                    self.store.insert("_Lease", LOCK_BLOB, value)
                else:
                    self.store.replace("_Lease", LOCK_BLOB, value, current.version)
                observation = self.observe_time()
                observe(self.observer, "lease.after_acquire")
                return LeaseHandle(owner, lease_id, until, observation.upper, until, observation)
            except (AlreadyExists, Conflict):
                continue
        raise Conflict("lease acquisition exhausted conditional races")

    def _owned(self, handle: LeaseHandle) -> Versioned:
        now = self.clock.now()
        require_utc(now, "clock.now")
        row = self.store.get("_Lease", LOCK_BLOB)
        if (row is None or row.value["owner_id"] != handle.owner_id or row.value["lease_id"] != handle.lease_id
                or datetime.fromisoformat(row.value["expires_at"]) <= now):
            raise OwnershipLost("fixed sentinel lease is absent, expired, or replaced")
        return row

    def assert_owned(self, handle: LeaseHandle) -> None:
        self._owned(handle)

    def renew(self, handle: LeaseHandle) -> LeaseHandle:
        row = self._owned(handle)
        until = self.clock.now() + timedelta(seconds=row.value["seconds"])
        value = row.to_mapping()["value"]
        value["expires_at"] = until.isoformat()
        try:
            self.store.replace("_Lease", LOCK_BLOB, value, row.version)
        except Conflict as error:
            raise OwnershipLost("lease changed during renewal") from error
        observation = self.observe_time()
        observe(self.observer, "lease.after_renew")
        return LeaseHandle(handle.owner_id, handle.lease_id, until, handle.acquired_upper, until, observation)

    def release(self, handle: LeaseHandle) -> None:
        row = self._owned(handle)
        value = row.to_mapping()["value"]
        value["expires_at"] = self.clock.now().isoformat()
        try:
            self.store.replace("_Lease", LOCK_BLOB, value, row.version)
        except Conflict as error:
            raise OwnershipLost("lease changed during release") from error

        observe(self.observer, "lease.after_release")

    def observe_time(self, handle: LeaseHandle | None = None) -> TimeBounds:
        if handle is not None:
            self._owned(handle)
        monotonic = self.clock.monotonic if hasattr(self.clock, "monotonic") else time.monotonic
        before = monotonic()
        now = self.clock.now()
        after = monotonic()
        require_utc(now, "fixture server clock")
        elapsed = after - before
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ClockUncertain("local server paired sampling has invalid monotonic elapsed")
        precision = getattr(self.clock, "precision_seconds", 0)
        require_number(precision, "clock sample precision")
        upper = now + timedelta(microseconds=math.ceil((elapsed + precision)*1_000_000))
        return TimeBounds(now, upper, after)

    @contextmanager
    def _sentinel_transaction(self, handle: LeaseHandle):
        with self.store._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            partition, key = identity("_Lease", LOCK_BLOB)
            row = connection.execute("SELECT value FROM records WHERE table_name=? AND partition=? AND key=?",
                                     (table_for("_Lease"), partition, key)).fetchone()
            lease = parse_json(row[0]) if row is not None else None
            now = self.clock.now()
            require_utc(now, "fixture server clock")
            if (lease is None or lease["lease_id"] != handle.lease_id or lease["owner_id"] != handle.owner_id
                    or datetime.fromisoformat(lease["expires_at"]) <= now):
                connection.rollback()
                raise OwnershipLost("sentinel transaction has lost the actual lease")
            yield connection
            connection.commit()

    def read_journal(self, handle: LeaseHandle) -> Versioned:
        with self._sentinel_transaction(handle) as connection:
            body, version = connection.execute("SELECT value, version FROM sentinel_journal WHERE identity=?", (LOCK_BLOB,)).fetchone()
        observe(self.observer, "journal.after_read")
        return Versioned(parse_json(body), version)

    def write_journal(self, handle: LeaseHandle, value: dict[str, object], version: str) -> Versioned:
        exact_version(version)
        body, next_version = payload_bytes(value).decode(), uuid.uuid4().hex
        observe(self.observer, "journal.before_write")
        with self._sentinel_transaction(handle) as connection:
            changed = connection.execute("UPDATE sentinel_journal SET value=?, version=? WHERE identity=? AND version=?",
                                         (body, next_version, LOCK_BLOB, version)).rowcount
            if changed != 1:
                connection.rollback()
                raise Conflict("sentinel journal version changed")
        observe(self.observer, "journal.after_write")
        return Versioned(parse_json(body), next_version)


    def release_clean(self, handle: LeaseHandle, value: dict[str, object], version: str) -> Versioned:
        """Finalize a positively drained journal and finite lease in one durable sentinel transaction."""
        exact_version(version)
        if value.get("clean_release") is not True or value.get("owner_id") != handle.owner_id:
            raise ValueError("atomic clean release requires the positively drained owner journal")
        body, next_version = payload_bytes(value).decode(), uuid.uuid4().hex
        observe(self.observer, "lease.before_clean_release")
        with self._sentinel_transaction(handle) as connection:
            observe(self.observer, "journal.before_clean_release")
            changed = connection.execute("UPDATE sentinel_journal SET value=?, version=? WHERE identity=? AND version=?",
                                         (body, next_version, LOCK_BLOB, version)).rowcount
            if changed != 1:
                connection.rollback()
                raise Conflict("atomic release journal version changed")
            partition, key = identity("_Lease", LOCK_BLOB)
            lease_body = connection.execute("SELECT value FROM records WHERE table_name=? AND partition=? AND key=?",
                                            (table_for("_Lease"), partition, key)).fetchone()[0]
            lease = parse_json(lease_body)
            lease["expires_at"] = self.clock.now().isoformat()
            connection.execute("UPDATE records SET value=?, version=? WHERE table_name=? AND partition=? AND key=?",
                               (payload_bytes(lease).decode(), uuid.uuid4().hex, table_for("_Lease"), partition, key))
        return Versioned(parse_json(body), next_version)
