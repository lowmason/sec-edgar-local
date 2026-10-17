import copy
import importlib
import importlib.util
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from support import FIXTURE_CONFIG, fixture_context, fixture_settings


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("sec_edgar_ingest.config"),
                             "Settings validation must exist before acquisition I/O")
        self.config = importlib.import_module("sec_edgar_ingest.config")

    def test_second_collector_is_refused(self):
        value = fixture_settings().to_mapping()
        value["sec"]["max_active_collectors"] = 2
        with self.assertRaisesRegex(ValueError, "max_active_collectors"):
            self.config.Settings.from_mapping(value)

    def test_invalid_configuration_precedes_external_factories(self):
        value = fixture_settings().to_mapping()
        value["sec"]["max_active_collectors"] = 2
        with patch("azure.identity.DefaultAzureCredential") as credential, \
             patch("azure.storage.blob.BlobServiceClient") as client, \
             patch("requests.Session") as transport:
            with self.assertRaises(ValueError):
                self.config.Settings.from_mapping(value)
            for factory in (credential, client, transport):
                factory.assert_not_called()

    def test_rejects_configuration_matrix(self):
        cases = [
            ("missing identity", "sec.user_agent", None),
            ("missing range", "backfill.start_quarter", None),
            ("missing endpoint", "backfill.end_quarter", None),
            ("missing handoff", "daily.start_date", None),
            ("reversed quarters", "backfill.end_quarter", "2014Q4"),
            ("unsupported config", "config_version", "v2"),
            ("unsupported schema", "etl.schema_version", "sec-index-v2"),
            ("absent parser", "etl.parser_version", None),
            ("absent image", "worker.image_digest", None),
            ("malformed image", "worker.image_digest", "latest"),
            ("zero rate", "sec.requests_per_second", 0),
            ("target at ten", "sec.requests_per_second", 10),
            ("negative attempts", "http.max_attempts", -1),
            ("too many attempts", "http.max_attempts", 6),
            ("NaN", "http.read_timeout_seconds", float("nan")),
            ("infinity", "http.exchange_deadline_seconds", float("inf")),
            ("zero received", "http.max_received_bytes", 0),
            ("negative expanded", "http.max_expanded_bytes", -1),
            ("unsafe path", "storage.root", "../outside"),
            ("absolute output path", "storage.root", "/tmp/outside"),
            ("bad namespace", "coordination.namespace", "independent-lane"),
            ("renew after lease", "coordination.renew_every_seconds", 60),
            ("bad retries", "jobs.replica_retry_limit", 1),
            ("bad replays", "orchestration.transient_replays", 2),
            ("no withdrawal gate", "reconciliation.require_withdrawal_approval", False),
            ("unknown nested key", "http.burst", 3),
            ("unknown root key", "unexpected", True),
        ]
        for name, dotted, replacement in cases:
            with self.subTest(name=name):
                value = fixture_settings().to_mapping()
                path = dotted.split(".")
                target = value
                for key in path[:-1]:
                    target = target[key]
                if replacement is None:
                    target.pop(path[-1])
                else:
                    target[path[-1]] = replacement
                with self.assertRaises(ValueError):
                    self.config.Settings.from_mapping(value)

    def azure_value(self):
        value = fixture_settings().to_mapping()
        value["storage"] = {
            "backend": "azure", "account_name": "secedgardevb8617",
            "blob_endpoint": "https://secedgardevb8617.blob.core.windows.net",
            "table_endpoint": "https://secedgardevb8617.table.core.windows.net",
            "raw_container": "raw", "workset_container": "worksets",
            "quarantine_container": "quarantine", "lock_container": "locks",
            "lock_blob": "sec-owner-lowell-mason/sentinel.json",
            "binding_registry_blob": "sec-owner-lowell-mason/binding.json",
            "source_table": "SourceState", "attempt_table": "Attempts",
            "blob_api_version": "2026-04-06", "table_api_version": "2020-12-06",
        }
        value["worker"] = {"image_digest": "sha256:" + "1" * 64,
                           "provenance": "immutable-image"}
        value["etl"]["parser_version"] = "accepted-parser-v1"
        return value

    def test_azure_explicit_binding_and_credential_free_endpoints(self):
        valid = self.azure_value()
        settings = self.config.Settings.from_mapping(valid)
        self.assertEqual(settings.storage.lock_container, "locks")
        self.assertEqual(settings.storage.account_name, "secedgardevb8617")
        cases = [
            ("missing Azure endpoint", "storage.blob_endpoint", None),
            ("credentials in endpoint", "storage.blob_endpoint",
             "https://user:secret@secedgardevb8617.blob.core.windows.net"),
            ("query credential", "storage.table_endpoint",
             "https://secedgardevb8617.table.core.windows.net?sig=hidden"),
            ("foreign account", "storage.account_name", "otheraccount"),
            ("foreign endpoint", "storage.table_endpoint", "https://other.table.core.windows.net"),
            ("different sentinel", "storage.lock_blob", "independent-sentinel"),
            ("different namespace", "coordination.namespace", "othernamespace"),
            ("different budget", "sec.requests_per_second", 2),
            ("synthetic image", "worker.image_digest", "sha256:" + "0" * 64),
            ("fixture marker", "worker.provenance", "synthetic-fixture"),
            ("fixture parser", "etl.parser_version", "fixture-envelope-v1"),
            ("fixture-only cap", "http.max_received_bytes", 32),
            ("fixture-only override", "fixture", {"allow_deadline_override": True}),
        ]
        for name, dotted, replacement in cases:
            with self.subTest(name=name):
                value = copy.deepcopy(valid)
                parts = dotted.split(".")
                target = value if len(parts) == 1 else value[parts[0]]
                if replacement is None:
                    target.pop(parts[-1])
                else:
                    target[parts[-1]] = replacement
                with self.assertRaises(ValueError):
                    self.config.Settings.from_mapping(value)

    def test_mapping_is_detached_and_typed_settings_are_frozen(self):
        settings = fixture_settings()
        detached = settings.to_mapping()
        detached["sec"]["user_agent"] = "changed"
        self.assertEqual(settings.sec.user_agent, "Lowell Mason sec-edgar-ingest mason.lowell@mac.com")
        with self.assertRaises(FrozenInstanceError):
            settings.sec.user_agent = "changed"
        with self.assertRaises(FrozenInstanceError):
            settings.config_version = "changed"
        self.assertEqual(settings.config_sha256, fixture_settings().config_sha256)
        self.assertNotEqual(settings.config_sha256,
                            fixture_settings(http={"read_timeout_seconds": 59}).config_sha256)

    def test_json_yaml_subset_loads_without_creating_fixture_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            path.write_bytes(FIXTURE_CONFIG.read_bytes())
            self.assertEqual(self.config.load_config(path), fixture_settings())
            self.assertFalse((Path(temporary) / ".fixture-state").exists())
            path.write_text("config_version: sec-acquisition-v1")
            with self.assertRaisesRegex(ValueError, "JSON"):
                self.config.load_config(path)

    def test_fixture_overrides_are_explicit_and_validated(self):
        settings = fixture_settings(http={"exchange_deadline_seconds": .2,
                                          "max_received_bytes": 32, "max_expanded_bytes": 128},
                                    fixture={"allow_clock_override": True,
                                             "allow_deadline_override": True})
        self.assertEqual(settings.http.max_received_bytes, 32)
        context = replace(fixture_context(), config_sha256=settings.config_sha256,
                          deadline=datetime(2026, 10, 6, tzinfo=timezone.utc) + timedelta(seconds=4000))
        pinned, end = self.config.pin_context(settings, context, date(2026, 10, 6))
        self.assertEqual(end, "2026Q4")
        self.assertEqual(pinned.effective_config["fixture"]["allow_deadline_override"], True)

    def test_pin_context_checks_range_identity_and_deadline(self):
        context = fixture_context()
        cases = [
            ("future endpoint", fixture_settings(backfill={"end_quarter": "2027Q1"}), context),
            ("unbound config", fixture_settings(), replace(context, config_sha256="f" * 64)),
            ("unbound image", fixture_settings(), replace(context, image_digest="sha256:" + "f" * 64)),
            ("unbound parser", fixture_settings(), replace(context, parser_version="other-v1")),
            ("too long", fixture_settings(), replace(context, deadline=context.started_at + timedelta(seconds=3601))),
        ]
        for name, settings, candidate in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.config.pin_context(settings, candidate, date(2026, 10, 6))
        self.assertEqual(self.config.pin_context(fixture_settings(), context, date(2026, 10, 6))[1], "2026Q4")
        for day, quarter in [(date(2024, 2, 29), "2024Q1"), (date(2024, 3, 31), "2024Q1"),
                             (date(2024, 4, 1), "2024Q2"), (date(2025, 1, 1), "2025Q1")]:
            with self.subTest(day=day):
                settings = fixture_settings()
                started = datetime.combine(day, datetime.min.time(), timezone.utc)
                dated = replace(context, started_at=started, deadline=started + timedelta(seconds=3600))
                self.assertEqual(self.config.pin_context(settings, dated, day)[1], quarter)

    def test_clock_override_is_fixture_only_and_explicit(self):
        context = fixture_context()
        with self.assertRaisesRegex(ValueError, "clock"):
            self.config.pin_context(fixture_settings(), context, date(2026, 10, 5))
        settings = fixture_settings(fixture={"allow_clock_override": True})
        context = replace(context, config_sha256=settings.config_sha256)
        pinned, quarter = self.config.pin_context(settings, context, date(2026, 10, 5))
        self.assertEqual(quarter, "2026Q4")
        self.assertTrue(pinned.effective_config["fixture"]["allow_clock_override"])

    def test_azure_deadlines_and_two_callers_share_one_binding(self):
        settings = self.config.Settings.from_mapping(self.azure_value())
        original = fixture_context()
        context = replace(original, image_digest=settings.worker.image_digest,
                          parser_version=settings.etl.parser_version,
                          config_sha256=settings.config_sha256)
        self.assertEqual(self.config.pin_context(settings, context, date(2026, 10, 6))[1], "2026Q4")
        for name, start, end in [
            ("over allowance", context.started_at, context.started_at + timedelta(seconds=3601)),
            ("at start", context.started_at, context.started_at),
            ("before start", context.started_at, context.started_at - timedelta(seconds=1)),
            ("non-UTC", context.started_at.replace(tzinfo=None), context.deadline),
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                candidate = replace(context, started_at=start, deadline=end)
                self.config.pin_context(settings, candidate, date(2026, 10, 6))
        contender = self.azure_value()
        contender["coordination"]["namespace"] = "backfill-independent"
        with self.assertRaisesRegex(ValueError, "namespace"):
            self.config.Settings.from_mapping(contender)
        self.assertEqual(settings.storage.lock_blob, fixture_settings().storage.lock_blob)

    def test_config_parser_rejects_duplicate_keys_and_non_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            body = FIXTURE_CONFIG.read_text()
            for name, malformed in [
                ("duplicate keys", body.replace('"config_version":', '"config_version":"sec-acquisition-v1","config_version":').encode()),
                ("non-UTF8", body.encode("utf-16")),
            ]:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    path.write_bytes(malformed)
                    self.config.load_config(path)

    def test_pinning_retains_exact_date_without_changing_run_start(self):
        original = fixture_context()
        settings = fixture_settings(fixture={"allow_clock_override": True})
        context = replace(original, config_sha256=settings.config_sha256)
        pinning_date = date(2026, 7, 15)
        pinned, endpoint = self.config.pin_context(settings, context, pinning_date)
        self.assertEqual(endpoint, "2026Q3")
        self.assertEqual(pinned.started_at, context.started_at)
        self.assertEqual(pinned.deadline, context.deadline)
        self.assertEqual(getattr(pinned, "pinned_on", None), pinning_date,
                         "the actual labelled fixture pinning date must be retained")
        self.assertEqual(type(pinned).from_mapping(pinned.to_mapping()), pinned)
        self.assertEqual(pinned.to_mapping()["pinned_on"], "2026-07-15")
        with self.assertRaises(FrozenInstanceError):
            pinned.pinned_on = date(2026, 7, 16)
