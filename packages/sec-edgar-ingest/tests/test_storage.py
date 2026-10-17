import hashlib
import importlib
import importlib.util
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import Faults, FixtureClock, fixture_settings, fixture_snapshot, fixture_source, store_bundle


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("sec_edgar_ingest.storage"),
                             "Durable conditional stores must preserve restart and race semantics")
        self.contracts = importlib.import_module("sec_edgar_ingest.storage.contracts")
        self.local = importlib.import_module("sec_edgar_ingest.storage.local")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store, self.objects, self.leases = store_bundle(self.root)
        self.addCleanup(self.store.close)

    def test_create_conflict_preserves_first_value_and_reopens(self):
        first = self.store.insert("Source", "identity", {"nested": {"value": [1]}})
        with self.assertRaises(self.contracts.AlreadyExists):
            self.store.insert("Source", "identity", {"nested": {"value": [2]}})
        self.store.close()
        reopened = self.local.LocalStateStore(self.root)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get("Source", "identity"), first)
        exported = first.to_mapping()
        exported["value"]["nested"]["value"].append(2)
        self.assertEqual(reopened.get("Source", "identity").value["nested"]["value"], (1,))

    def test_stale_cas_and_missing_rows_cannot_replace(self):
        first = self.store.insert("Source", "identity", {"count": 1})
        other = self.local.LocalStateStore(self.root)
        self.addCleanup(other.close)
        current = other.replace("Source", "identity", {"count": 2}, first.version)
        self.assertNotEqual(first.version, current.version)
        with self.assertRaises(self.contracts.Conflict):
            self.store.replace("Source", "identity", {"count": 3}, first.version)
        with self.assertRaises(self.contracts.Conflict):
            self.store.replace("Source", "absent", {}, first.version)
        for version in ("", "*"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.store.replace("Source", "identity", {}, version)
        self.assertEqual(self.store.get("Source", "identity"), current)

    def test_scan_reads_all_pages_and_filters_detached_values(self):
        for ordinal in range(9):
            self.store.insert("Source", f"key-{ordinal}", {"ordinal": ordinal, "pending": ordinal % 2 == 0})
        self.store.insert("Attempt", "unrelated", {"pending": True})
        paged = self.local.LocalStateStore(self.root, page_size=2)
        self.addCleanup(paged.close)
        rows = tuple(paged.scan("Source", {"pending": True}))
        self.assertEqual([row.value["ordinal"] for row in rows], [0, 2, 4, 6, 8])
        self.assertEqual(tuple(paged.scan("Missing", {})), ())
        with self.assertRaises(TypeError):
            rows[0].value["ordinal"] = 10

    def test_write_once_same_bytes_are_idempotent_different_bytes_are_corruption(self):
        path = "worksets/source/identity.json"
        reference = self.objects.put_once(path, b"first")
        self.assertEqual(self.objects.put_once(path, b"first"), reference)
        with self.assertRaises(self.contracts.Conflict):
            self.objects.put_once(path, b"second")
        self.assertEqual(self.local.LocalObjectStore(self.root).read(path), b"first")
        self.objects.verify(path, hashlib.sha256(b"first").hexdigest(), 5)
        with self.assertRaises(self.contracts.Conflict):
            self.objects.verify(path, "0" * 64, 5)
        with self.assertRaises(self.contracts.Conflict):
            self.objects.verify(path, hashlib.sha256(b"first").hexdigest(), 4)

    def test_stage_promote_verified_bytes_before_raw_reference(self):
        body = b"staged bytes"
        source = self.root / "receipt"
        source.write_bytes(body)
        snapshot = fixture_snapshot(fixture_source(), body)
        temporary = self.objects.stage("raw/.staging/attempt/body", source)
        with self.assertRaises(self.contracts.Conflict):
            self.objects.promote(temporary, snapshot.raw_path, "0" * 64, len(body))
        self.assertEqual(self.objects.read(temporary), body)
        raw = self.objects.promote(temporary, snapshot.raw_path, snapshot.sha256, len(body))
        self.assertEqual(raw, snapshot.raw_path)
        self.objects.verify(raw, snapshot.sha256, len(body))
        self.assertEqual(self.objects.promote(temporary, raw, snapshot.sha256, len(body)), raw)

    def test_unsafe_paths_and_symlinks_cannot_escape_object_root(self):
        for path in ("../escape", "/absolute", "raw//empty", "raw/./dot", "raw/a\\b", "raw/a%2fb"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.objects.put_once(path, b"bad")
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "objects" / "raw").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.objects.put_once("raw/escape", b"bad")
        self.assertFalse((outside / "escape").exists())

    def test_object_fault_before_and_after_link_is_restart_safe(self):
        faults = Faults()
        objects = self.local.LocalObjectStore(self.root, observer=faults)
        def crash():
            raise RuntimeError("simulated crash")
        faults.at("object.before_link", crash)
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            objects.put_once("raw/before", b"bytes")
        with self.assertRaises(FileNotFoundError):
            self.objects.read("raw/before")
        faults.at("object.after_link", crash)
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            objects.put_once("raw/after", b"bytes")
        self.assertEqual(self.objects.read("raw/after"), b"bytes")
        self.assertEqual(objects.put_once("raw/after", b"bytes"), "raw/after")

    def test_committed_insert_survives_observer_exception(self):
        faults = Faults()
        store = self.local.LocalStateStore(self.root, observer=faults)
        self.addCleanup(store.close)
        def crash():
            raise RuntimeError("after durable insert")
        faults.at("state.after_insert", crash)
        with self.assertRaisesRegex(RuntimeError, "durable"):
            store.insert("Source", "first", {"value": 1})
        self.assertEqual(self.store.get("Source", "first").value["value"], 1)

    def test_shared_finite_lease_expiry_renewal_and_stale_handles(self):
        clock = FixtureClock()
        one = self.local.LocalLeaseStore(self.root, clock=clock)
        two = self.local.LocalLeaseStore(self.root, clock=clock)
        first = one.acquire("first", 60)
        with self.assertRaises(self.contracts.Conflict):
            two.acquire("second", 60)
        one.assert_owned(first)
        clock.advance(20)
        renewed = one.renew(first)
        self.assertGreater(renewed.observed_until, first.observed_until)
        clock.advance(61)
        second = two.acquire("second", 60)
        self.assertNotEqual(first.lease_id, second.lease_id)
        for operation in (one.assert_owned, one.renew, one.release):
            with self.subTest(operation=operation.__name__), self.assertRaises(self.contracts.OwnershipLost):
                operation(renewed)
        two.assert_owned(second)
        two.release(second)
        one.acquire("third", 60)
        for seconds in (0, -1, True):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                one.acquire("invalid", seconds)

    def test_fixed_registry_is_conditional_and_factory_shares_root_and_budget(self):
        storage = importlib.import_module("sec_edgar_ingest.storage")
        settings = fixture_settings(storage={"root": "shared"})
        first = storage.open_stores(settings, base_path=self.root)
        self.addCleanup(first[0].close)
        first[0].insert("Source", "same", {"value": 1})
        second = storage.open_stores(settings, base_path=self.root)
        self.addCleanup(second[0].close)
        self.assertEqual(second[0].get("Source", "same").value["value"], 1)
        registry = "locks/sec-owner-lowell-mason/binding.json"
        before = first[1].read(registry)
        conflicting = fixture_settings(storage={"root": "shared"}, sec={"requests_per_second": 1})
        with self.assertRaises(self.contracts.Conflict):
            storage.open_stores(conflicting, base_path=self.root)
        self.assertEqual(first[1].read(registry), before)
        lease = first[2].acquire("one", 60)
        with self.assertRaises(self.contracts.Conflict):
            second[2].acquire("two", 60)
        first[2].release(lease)
        self.assertTrue((self.root / "shared" / "objects" / "locks/sec-owner-lowell-mason/sentinel.json").is_file())

    def test_reopening_lease_client_preserves_existing_sentinel_journal(self):
        sentinel = self.root / "objects/locks/sec-owner-lowell-mason/sentinel.json"
        journal = b'{"epoch":12,"not_before":"2026-10-06T00:00:30+00:00"}'
        sentinel.write_bytes(journal)
        try:
            reopened = self.local.LocalLeaseStore(self.root)
        except self.contracts.Conflict as error:
            self.fail(f"Reopening a lease client must preserve the mutable sentinel journal: {error}")
        self.addCleanup(reopened.close)
        self.assertEqual(sentinel.read_bytes(), journal)

    def test_symlink_object_collision_cannot_follow_a_leaf_link(self):
        target = self.root / "outside-object-root"
        target.write_bytes(b"protected")
        parent = self.root / "objects/quarantine"
        parent.mkdir()
        link = parent / "leaf"
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            try:
                self.objects.put_once("quarantine/leaf", b"replacement")
            except OSError as error:
                self.fail(f"Symlink rejection must use the host errno and raise ValueError, got errno {error.errno}")
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_bytes(), b"protected")


class LocalStateInitTests(unittest.TestCase):
    """A fresh store's WAL switch must wait out another initializer, within the connection busy timeout."""

    def setUp(self):
        self.local = importlib.import_module("sec_edgar_ingest.storage.local")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def hold_reserved(self):
        # Act as another initializer between its RESERVED and EXCLUSIVE locks. SQLite then refuses the
        # store's read-lock upgrade at once, without its busy handler: the race seen in parallel test runs.
        holder = sqlite3.connect(self.root / "state.sqlite3", isolation_level=None, check_same_thread=False)
        self.addCleanup(holder.close)
        holder.execute("BEGIN IMMEDIATE")
        return holder

    def test_init_waits_out_a_competing_wal_switch(self):
        holder = self.hold_reserved()
        release = threading.Timer(0.3, holder.execute, ("COMMIT",))
        started = time.monotonic()
        release.start()
        self.addCleanup(release.join)
        store = self.local.LocalStateStore(self.root)
        self.addCleanup(store.close)
        self.assertGreaterEqual(time.monotonic() - started, 0.25)
        with store._connection() as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_init_gives_up_when_the_busy_timeout_expires(self):
        self.hold_reserved()
        with patch.object(self.local, "SQLITE_BUSY_TIMEOUT_SECONDS", 0.2):
            started = time.monotonic()
            with self.assertRaises(sqlite3.OperationalError) as raised:
                self.local.LocalStateStore(self.root)
        self.assertGreaterEqual(time.monotonic() - started, 0.15)
        self.assertEqual(raised.exception.sqlite_errorcode & 0xFF, sqlite3.SQLITE_BUSY)
