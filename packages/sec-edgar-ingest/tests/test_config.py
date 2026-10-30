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
from sec_edgar_ingest.runtime import fixture_descriptor


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
        with patch("requests.Session") as transport:
            with self.assertRaises(ValueError):
                self.config.Settings.from_mapping(value)
            transport.assert_not_called()

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
            ("absent fixture id", "runtime.fixture_id", None),
            ("malformed runtime", "runtime.kind", "container"),
            ("zero rate", "sec.requests_per_second", 0),
            ("target at ten", "sec.requests_per_second", 10),
            ("negative attempts", "http.max_attempts", -1),
            ("too many attempts", "http.max_attempts", 6),
            ("NaN", "http.read_timeout_seconds", float("nan")),
            ("infinity", "http.exchange_deadline_seconds", float("inf")),
            ("zero received", "http.max_received_bytes", 0),
            ("negative expanded", "http.max_expanded_bytes", -1),
            ("empty root", "storage.root", ""),
            ("invalid root", "storage.root", 123),
            ("bad namespace", "coordination.namespace", "independent-lane"),
            ("renew after lease", "coordination.renew_every_seconds", 60),
            ("old retries", "jobs", {"replica_retry_limit": 1}),
            ("old replays", "orchestration", {"transient_replays": 2}),
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

    def live_value(self):
        value = fixture_settings().to_mapping()
        value['acquisition'] = {'mode': 'live'}
        value['runtime'] = {'kind': 'native', 'release_manifest':
            '/tmp/releases/sha256=' + 'a' * 64 + '/release.json'}
        value['etl']['parser_version'] = 'sec-index-parser-v1'
        return value

    def test_native_live_binding_and_explicit_runtime(self):
        valid = self.live_value()
        settings = self.config.Settings.from_mapping(valid)
        self.assertEqual(settings.storage.backend, 'local')
        self.assertEqual(settings.runtime.kind, 'native')
        cases = [
            ('absent runtime', 'runtime', None),
            ('unaddressed release', 'runtime.release_manifest', '/tmp/release.json'),
            ('legacy image', 'worker', {'image_digest': 'sha256:' + '1' * 64}),
            ('provider backend', 'storage.backend', 'azure'),
            ('different namespace', 'coordination.namespace', 'othernamespace'),
            ('too high budget', 'sec.requests_per_second', 4),
            ('fixture runtime', 'runtime', {'kind': 'fixture', 'fixture_id': 'test'}),
            ('fixture parser', 'etl.parser_version', 'fixture-envelope-v1'),
            ('fixture-only cap', 'http.max_received_bytes', 32),
            ('fixture-only override', 'fixture', {'allow_deadline_override': True}),
        ]
        for name, dotted, replacement in cases:
            with self.subTest(name=name):
                value = copy.deepcopy(valid)
                parts = dotted.split('.')
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
            expected = self.config.normalize_paths(self.config.parse_config(path.read_text()), path.resolve().parent)
            self.assertEqual(self.config.load_config(path), expected)
            self.assertEqual(expected.storage.root, str((path.parent / ".fixture-state").resolve()))
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
            ("unbound runtime", fixture_settings(), replace(context, runtime=fixture_descriptor("different"))),
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

    def test_local_deadlines_and_two_callers_share_one_namespace(self):
        settings = fixture_settings()
        context = fixture_context(settings=settings)
        self.assertEqual(self.config.pin_context(settings, context, date(2026, 10, 6))[1], '2026Q4')
        for name, start, end in [
            ('over allowance', context.started_at, context.started_at + timedelta(seconds=3601)),
            ('at start', context.started_at, context.started_at),
            ('before start', context.started_at, context.started_at - timedelta(seconds=1)),
            ('non-UTC', context.started_at.replace(tzinfo=None), context.deadline),
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                candidate = replace(context, started_at=start, deadline=end)
                self.config.pin_context(settings, candidate, date(2026, 10, 6))
        contender = settings.to_mapping()
        contender['coordination']['namespace'] = 'backfill-independent'
        with self.assertRaisesRegex(ValueError, 'namespace'):
            self.config.Settings.from_mapping(contender)
        bounded = fixture_settings(execution={'max_run_seconds': 10})
        with self.assertRaisesRegex(ValueError, 'execution.max_run_seconds'):
            self.config.pin_context(bounded, fixture_context(settings=bounded), date(2026, 10, 6))

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


import json

PROJECT = Path(__file__).resolve().parents[3]
# conf/sec-edgar-local.json normalized in the main checkout (plan 4 F-P5); embedded so worktrees hash the same.
LIVE_EFFECTIVE = {
    "config_version": "sec-local-config-v1",
    "backfill": {"start_quarter": "2015Q1", "end_quarter": "open"},
    "daily": {"start_date": "2026-10-01"},
    "sec": {"user_agent": "Lowell Mason sec-edgar-ingest mason.lowell@mac.com",
            "requests_per_second": 3.0, "max_active_collectors": 1},
    "http": {"max_attempts": 5, "retry_base_seconds": 2.0, "retry_cap_seconds": 120.0,
             "connect_timeout_seconds": 15.0, "read_timeout_seconds": 60.0,
             "exchange_deadline_seconds": 90.0, "max_received_bytes": 67108864,
             "max_expanded_bytes": 536870912},
    "coordination": {"lease_seconds": 60.0, "renew_every_seconds": 20.0,
                     "namespace": "sec-owner-lowell-mason", "clock_uncertainty_seconds": 2.0},
    "storage": {"backend": "local", "root": "/Users/lowell/Projects/sec-edgar-local/data"},
    "acquisition": {"mode": "live"},
    "runtime": {"kind": "native", "release_manifest": "/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/release.json"},
    "logging": {"root": "/Users/lowell/Projects/sec-edgar-local/logs"},
    "execution": {"max_run_seconds": 3600},
    "etl": {"parser_version": "sec-index-parser-v1", "schema_version": "sec-index-v1"},
    "reconciliation": {"require_withdrawal_approval": True},
}
LIVE_SHA256 = "088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d"
L12_QUARTERLY_SHA256 = "32b4da638464758c2926fc9040e207696a081d452b2af3813ddd36d179441740"


class DispatchReserveConfigTests(unittest.TestCase):
    def live(self, **execution):
        value = copy.deepcopy(LIVE_EFFECTIVE)
        value["execution"].update(execution)
        return value

    def test_absent_key_leaves_every_effective_hash_unchanged(self):
        from sec_edgar_ingest.config import Settings
        settings = Settings.from_mapping(self.live())
        self.assertIsNone(settings.execution.dispatch_reserve_seconds)
        self.assertNotIn("dispatch_reserve_seconds", settings.to_mapping()["execution"])
        self.assertEqual(settings.config_sha256, LIVE_SHA256)
        quarterly = self.live()
        quarterly["backfill"] = {"start_quarter": "2024Q1", "end_quarter": "2024Q1"}
        self.assertEqual(Settings.from_mapping(quarterly).config_sha256, L12_QUARTERLY_SHA256)

    def test_present_key_round_trips_and_changes_the_hash(self):
        from sec_edgar_ingest.config import DISPATCH_RESERVE_FLOOR_SECONDS, Settings
        settings = Settings.from_mapping(self.live(dispatch_reserve_seconds=DISPATCH_RESERVE_FLOOR_SECONDS))
        self.assertEqual(settings.to_mapping()["execution"]["dispatch_reserve_seconds"],
                         DISPATCH_RESERVE_FLOOR_SECONDS)
        self.assertEqual(Settings.from_mapping(settings.to_mapping()), settings)
        self.assertNotEqual(settings.config_sha256, LIVE_SHA256)

    def test_key_is_a_positive_integer_and_never_null(self):
        from sec_edgar_ingest.config import Settings
        for bad in (None, 0, -1, 1.5, True, "600"):
            with self.subTest(value=bad), self.assertRaisesRegex(ValueError, "dispatch_reserve_seconds|invalid type"):
                Settings.from_mapping(self.live(dispatch_reserve_seconds=bad))

    def test_admission_requires_the_key_in_range_for_live_work_only(self):
        from sec_edgar_ingest.config import DISPATCH_RESERVE_FLOOR_SECONDS as floor, Settings, admit_dispatch_reserve
        with self.assertRaisesRegex(ValueError, "dispatch_reserve_seconds"):
            admit_dispatch_reserve(Settings.from_mapping(self.live()))
        for bad in (floor - 1, 3600, 3601):
            with self.subTest(value=bad), self.assertRaisesRegex(ValueError, "dispatch_reserve_seconds"):
                admit_dispatch_reserve(Settings.from_mapping(self.live(dispatch_reserve_seconds=bad)))
        for good in (floor, 3599):
            with self.subTest(value=good):
                self.assertEqual(admit_dispatch_reserve(Settings.from_mapping(self.live(dispatch_reserve_seconds=good))), good)
        self.assertIsNone(admit_dispatch_reserve(fixture_settings()))

    def test_fc68adef_origin_live_child_contexts_validate_without_the_key(self):
        from sec_edgar_ingest.config import Settings
        from sec_edgar_ingest.models import RunContext
        evidence = json.loads((PROJECT / "specs/evidence/local-port/sec-acceptance.json").read_text())
        contexts = [source[step]["context"] for source in evidence["selected_sources"]
                    for step in ("transform", "publish")]
        self.assertEqual(len(contexts), 6)
        for value in contexts:
            with self.subTest(run=value["run_id"], command=value["command"]):
                context = RunContext.from_mapping(value)
                self.assertNotIn("dispatch_reserve_seconds", value["effective_config"]["execution"])
                self.assertEqual(Settings.from_mapping(value["effective_config"]).config_sha256, context.config_sha256)
