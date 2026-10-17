"""Strict native-local settings and immutable local store binding contracts."""
import copy
import contextlib
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from sec_edgar_ingest.config import Settings, load_config, parse_config
from sec_edgar_ingest.models import canonical_json


def local_mapping(root="../data", *, mode="fixture"):
    """Standalone supplied JSON contract; no run context or command imports."""
    return {
        "config_version": "sec-local-config-v1",
        "backfill": {"start_quarter": "2015Q1", "end_quarter": "open"},
        "daily": {"start_date": "2026-10-01"},
        "sec": {"user_agent": "Lowell Mason sec-edgar-ingest mason.lowell@mac.com",
                "requests_per_second": 3, "max_active_collectors": 1},
        "http": {"max_attempts": 5, "retry_base_seconds": 2, "retry_cap_seconds": 120,
                 "connect_timeout_seconds": 15, "read_timeout_seconds": 60,
                 "exchange_deadline_seconds": 90, "max_received_bytes": 67108864,
                 "max_expanded_bytes": 536870912},
        "coordination": {"lease_seconds": 60, "renew_every_seconds": 20,
                         "namespace": "sec-owner-lowell-mason", "clock_uncertainty_seconds": 2},
        "storage": {"backend": "local", "root": str(root)},
        "acquisition": {"mode": mode},
        "runtime": {"kind": "fixture", "fixture_id": "local-contract-tests-v1"},
        "logging": {"root": "../logs"},
        "execution": {"max_run_seconds": 3600},
        "etl": {"parser_version": "sec-index-parser-v1", "schema_version": "sec-index-v1"},
        "reconciliation": {"require_withdrawal_approval": True},
    }


class LocalConfigTests(unittest.TestCase):
    def accepted(self, value=None):
        try:
            return Settings.from_mapping(local_mapping() if value is None else value)
        except ValueError as error:
            self.fail(f"Task 3 requires the strict independent local settings contract: {error}")

    def assert_invalid(self, value):
        with self.assertRaises(ValueError):
            Settings.from_mapping(value)

    def test_local_groups_are_exact_frozen_and_detached(self):
        settings = self.accepted()
        self.assertEqual(settings.config_version, "sec-local-config-v1")
        self.assertEqual(settings.acquisition.mode, "fixture")
        self.assertEqual(settings.storage.to_mapping(), {"backend": "local", "root": "../data"})
        self.assertEqual(settings.runtime.to_mapping(), {"kind": "fixture", "fixture_id": "local-contract-tests-v1"})
        mapping = settings.to_mapping()
        mapping["sec"]["user_agent"] = "changed"
        self.assertEqual(settings.sec.user_agent, local_mapping()["sec"]["user_agent"])
        with self.assertRaises(FrozenInstanceError):
            settings.acquisition.mode = "live"

    def test_version_is_independent_from_record_format(self):
        self.accepted()
        for version in ("sec-acquisition-v1", "sec-local-config-v2", "", None, True):
            with self.subTest(version=version):
                self.assert_invalid({**local_mapping(), "config_version": version})

    def test_strict_json_rejects_duplicates_unknown_nonfinite_and_non_utf8(self):
        self.accepted()
        body = json.dumps(local_mapping())
        invalid = [body.replace('"config_version":', '"config_version":"sec-local-config-v1","config_version":'),
                   body.replace('"requests_per_second": 3', '"requests_per_second": NaN'),
                   body.replace('"requests_per_second": 3', '"requests_per_second": Infinity'),
                   body.replace('"requests_per_second": 3', '"requests_per_second": -Infinity'),
                   'config_version: sec-local-config-v1', '[]', 'null',
                   json.dumps({**local_mapping(), "unknown": True})]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_config(text)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_bytes(body.encode("utf-16"))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_cloud_and_removed_groups_are_rejected(self):
        self.accepted()
        storage_keys = {"source_table": "SourceState", "account_name": "account",
                        "blob_endpoint": "https://example.test", "table_endpoint": "https://example.test",
                        "attempt_table": "Attempts", "blob_api_version": "version", "root_override": "elsewhere"}
        for key, value in storage_keys.items():
            with self.subTest(key=key):
                mapping = local_mapping()
                mapping["storage"][key] = value
                self.assert_invalid(mapping)
        for backend in ("azure", "local-fixture", "other", None):
            with self.subTest(backend=backend):
                mapping = local_mapping()
                mapping["storage"]["backend"] = backend
                self.assert_invalid(mapping)
        for key in ("worker", "jobs", "orchestration"):
            with self.subTest(group=key):
                self.assert_invalid({**local_mapping(), key: {}})

    def test_runtime_union_has_absent_opposite_fields(self):
        self.accepted()
        variants = [
            {"kind": "fixture", "fixture_id": "fixture-v1", "release_manifest": None},
            {"kind": "native", "release_manifest": "releases/sha256=" + "a" * 64 + "/release.json", "fixture_id": None},
            {"kind": "fixture"}, {"kind": "native"}, {"kind": "other"}, None,
            {"kind": "fixture", "fixture_id": ""}, {"kind": "fixture", "fixture_id": "bad\nlabel"},
        ]
        for variant in variants:
            with self.subTest(runtime=variant):
                self.assert_invalid({**local_mapping(), "runtime": variant})
        native = {"kind": "native", "release_manifest": "releases/sha256=" + "a" * 64 + "/release.json"}
        for mode in ("fixture", "live"):
            with self.subTest(mode=mode):
                self.assertEqual(self.accepted({**local_mapping(mode=mode), "runtime": native}).runtime.to_mapping(), native)
        self.assert_invalid(local_mapping(mode="live"))

    def test_native_manifest_path_requires_explicit_release_address(self):
        self.accepted()
        for path in ("releases/latest/release.json", "release.json", "releases/sha256=" + "A" * 64 + "/release.json",
                     "releases/sha256=" + "a" * 64 + "/manifest.json", "elsewhere/sha256=" + "a" * 64 + "/release.json"):
            with self.subTest(path=path):
                self.assert_invalid({**local_mapping(), "runtime": {"kind": "native", "release_manifest": path}})

    def test_fixture_overrides_are_individually_explicit_booleans(self):
        self.accepted()
        for overrides in ({}, {"allow_clock_override": True}, {"allow_deadline_override": False}):
            with self.subTest(overrides=overrides):
                self.accepted({**local_mapping(), "fixture": overrides})
        for overrides in (None, {"allow_clock_override": 1}, {"allow_deadline_override": "true"}, {"other": True}):
            with self.subTest(overrides=overrides):
                self.assert_invalid({**local_mapping(), "fixture": overrides})
        live = local_mapping(mode="live")
        live["runtime"] = {"kind": "native", "release_manifest": "releases/sha256=" + "a" * 64 + "/release.json"}
        for overrides in ({}, {"allow_clock_override": False}, {"allow_deadline_override": False}):
            with self.subTest(live_override=overrides):
                self.assert_invalid({**live, "fixture": overrides})

    def test_issuer_and_boundaries_are_explicit(self):
        self.accepted()
        cases = [("sec", "user_agent", "Other owner"), ("sec", "requests_per_second", 0),
                 ("sec", "requests_per_second", 3.1), ("sec", "max_active_collectors", 2),
                 ("coordination", "namespace", "other"), ("coordination", "lease_seconds", 0),
                 ("coordination", "renew_every_seconds", 60), ("coordination", "clock_uncertainty_seconds", 2.1),
                 ("execution", "max_run_seconds", 0), ("execution", "max_run_seconds", True),
                 ("http", "max_attempts", 6), ("http", "max_received_bytes", 67108865),
                 ("http", "max_expanded_bytes", 536870913), ("http", "exchange_deadline_seconds", 91),
                 ("reconciliation", "require_withdrawal_approval", False)]
        for section, field, invalid in cases:
            with self.subTest(field=f"{section}.{field}"):
                mapping = local_mapping()
                mapping[section][field] = invalid
                self.assert_invalid(mapping)
        for section in ("sec", "http", "coordination", "storage", "runtime", "execution", "logging"):
            mapping = local_mapping()
            del mapping[section]
            with self.subTest(missing=section):
                self.assert_invalid(mapping)
        slower = local_mapping()
        slower["sec"]["requests_per_second"] = .25
        self.accepted(slower)

    def test_live_policy_is_exact_while_fixture_limits_may_be_lower(self):
        self.accepted()
        live = local_mapping(mode="live")
        live["runtime"] = {"kind": "native", "release_manifest": "releases/sha256=" + "a" * 64 + "/release.json"}
        self.accepted(live)
        for section, field in [("http", name) for name in live["http"]] + [
                ("coordination", "lease_seconds"), ("coordination", "renew_every_seconds"),
                ("coordination", "clock_uncertainty_seconds"), ("execution", "max_run_seconds")]:
            with self.subTest(section=section, field=field):
                mapping = copy.deepcopy(live)
                mapping[section][field] -= 1
                self.assert_invalid(mapping)
        fixture = local_mapping()
        fixture["http"].update(exchange_deadline_seconds=.2, max_received_bytes=32, max_expanded_bytes=128)
        fixture["coordination"].update(lease_seconds=10, renew_every_seconds=2, clock_uncertainty_seconds=0)
        fixture["execution"]["max_run_seconds"] = 10
        fixture["etl"]["parser_version"] = "fixture-envelope-v1"
        self.accepted(fixture)
        live["etl"]["parser_version"] = "fixture-envelope-v1"
        self.assert_invalid(live)
        live["etl"]["parser_version"] = "different-parser-v1"
        self.assert_invalid(live)

    def test_filesystem_paths_accept_parent_absolute_and_home_but_not_empty(self):
        self.accepted()
        for field in ("storage", "logging"):
            for path in ("../outside", "/tmp/absolute", "~/sec-local"):
                with self.subTest(field=field, path=path):
                    mapping = local_mapping()
                    mapping[field]["root"] = path
                    self.accepted(mapping)
            for path in ("", " ", None, "bad\x00path"):
                mapping = local_mapping()
                mapping[field]["root"] = path
                with self.subTest(field=field, invalid=path):
                    self.assert_invalid(mapping)

    def test_paths_resolve_against_original_config_parent_from_any_cwd(self):
        self.accepted()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "conf/config.json"
            config.parent.mkdir()
            config.write_bytes(canonical_json(local_mapping()))
            snapshots = []
            for name in ("cwd-one", "other/deep/cwd-two"):
                cwd = root / name
                cwd.mkdir(parents=True)
                with contextlib.chdir(cwd):
                    snapshots.append(load_config(Path(os.path.relpath(config, cwd))))
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(snapshots[0].storage.root, str((config.parent / "../data").resolve()))
            self.assertEqual(snapshots[0].logging.root, str((config.parent / "../logs").resolve()))
            self.assertFalse((root / "data").exists())
            self.assertFalse((root / "logs").exists())

    def test_absolute_archive_replay_has_same_mapping_and_effective_hash(self):
        self.accepted()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "conf/config.json"
            config.parent.mkdir()
            config.write_bytes(canonical_json(local_mapping()))
            first = load_config(config)
            invocation_directory = root / "invocations/one"
            invocation_directory.mkdir(parents=True)
            archived = invocation_directory / "config.json"
            archived.write_bytes(canonical_json(first.to_mapping()))
            second = load_config(archived)
            self.assertEqual(first.storage.root, str((config.parent / "../data").resolve()))
            self.assertEqual(second.to_mapping(), first.to_mapping())
            self.assertEqual(second.config_sha256, first.config_sha256)
            self.assertEqual(first.config_sha256, hashlib.sha256(canonical_json(first.to_mapping())).hexdigest())
            self.assertNotEqual(hashlib.sha256(config.read_bytes()).hexdigest(), hashlib.sha256(archived.read_bytes()).hexdigest())
            alternate = root / "config-alternate.json"
            alternate.write_text(json.dumps(first.to_mapping(), indent=2) + "\n")
            self.assertEqual(load_config(alternate).config_sha256, first.config_sha256)
            self.assertNotEqual(hashlib.sha256(alternate.read_bytes()).hexdigest(), hashlib.sha256(archived.read_bytes()).hexdigest())

    def test_home_expansion_and_native_path_normalization_are_idempotent(self):
        self.accepted()
        from sec_edgar_ingest.config import normalize_paths
        mapping = local_mapping("~/sec-test-data")
        mapping["runtime"] = {"kind": "native", "release_manifest": "../releases/sha256=" + "a" * 64 + "/release.json"}
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "conf"
            settings = normalize_paths(Settings.from_mapping(mapping), parent)
            self.assertEqual(settings.storage.root, str((Path.home() / "sec-test-data").resolve()))
            self.assertEqual(settings.runtime.release_manifest, str((parent / mapping["runtime"]["release_manifest"]).resolve()))
            self.assertEqual(normalize_paths(settings, Path(temporary) / "other"), settings)


class LocalBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "data"
        try:
            self.settings = Settings.from_mapping(local_mapping(self.root))
        except ValueError as error:
            self.fail(f"Task 3 requires the strict local binding settings contract: {error}")

    def open(self, settings=None):
        from sec_edgar_ingest.storage import open_stores
        state, objects, leases = open_stores(settings or self.settings)
        self.addCleanup(state.close)
        self.addCleanup(leases.close)
        return state, objects, leases

    def test_binding_has_only_local_policy_identity(self):
        from sec_edgar_ingest.storage.contracts import deployment_binding
        binding = deployment_binding(self.settings)
        self.assertEqual(binding, {
            "binding_version": "sec-local-binding-v1", "root": str(self.root.resolve()),
            "acquisition_mode": "fixture", "namespace": "sec-owner-lowell-mason",
            "sec": self.settings.sec.to_mapping(), "coordination": self.settings.coordination.to_mapping(),
            "storage_contract": "sec-local-storage-v1",
        })
        self.assertEqual(deployment_binding(root=self.root), binding)
        with self.assertRaises(ValueError):
            deployment_binding()

    def test_pacing_and_coordination_changes_conflict_without_mutation(self):
        from sec_edgar_ingest.storage import open_stores
        from sec_edgar_ingest.storage.contracts import Conflict
        from support_fs import tree_snapshot
        self.open()
        before = tree_snapshot(self.root)
        for section, field, replacement in (("sec", "requests_per_second", 1),
                                             ("coordination", "renew_every_seconds", 19),
                                             ("coordination", "clock_uncertainty_seconds", 1)):
            value = self.settings.to_mapping()
            value[section][field] = replacement
            with self.subTest(field=field), self.assertRaises(Conflict):
                open_stores(Settings.from_mapping(value))
            self.assertEqual(tree_snapshot(self.root), before)
        value = self.settings.to_mapping()
        value["sec"]["user_agent"] = "different issuer"
        with self.assertRaises(ValueError):
            open_stores(Settings.from_mapping(value))
        self.assertEqual(tree_snapshot(self.root), before)

    def test_acquisition_mode_mismatch_and_moved_root_conflict(self):
        from sec_edgar_ingest.storage import open_stores
        from sec_edgar_ingest.storage.contracts import Conflict
        from support_fs import tree_snapshot
        self.open()
        before = tree_snapshot(self.root)
        value = self.settings.to_mapping()
        value["acquisition"]["mode"] = "live"
        value["runtime"] = {"kind": "native", "release_manifest": str(self.base / "releases" / ("sha256=" + "a" * 64) / "release.json")}
        with self.assertRaises(Conflict):
            open_stores(Settings.from_mapping(value))
        self.assertEqual(tree_snapshot(self.root), before)
        moved = self.base / "moved"
        shutil.copytree(self.root, moved)
        value = self.settings.to_mapping()
        value["storage"]["root"] = str(moved)
        moved_before = tree_snapshot(moved)
        with self.assertRaises(Conflict):
            open_stores(Settings.from_mapping(value))
        self.assertEqual(tree_snapshot(moved), moved_before)

    def test_range_parser_and_release_are_not_binding_identity(self):
        state, _, _ = self.open()
        state.insert("Source", "same", {"retained": True})
        value = self.settings.to_mapping()
        value["backfill"] = {"start_quarter": "2010Q1", "end_quarter": "2015Q1"}
        value["etl"]["parser_version"] = "different-fixture-parser-v1"
        value["runtime"] = {"kind": "native", "release_manifest": str(self.base / "releases" / ("sha256=" + "a" * 64) / "release.json")}
        reopened, _, _ = self.open(Settings.from_mapping(value))
        self.assertTrue(reopened.get("Source", "same").value["retained"])

    def test_factory_has_no_second_root_or_credentials_and_requires_normalized_root(self):
        from sec_edgar_ingest.storage import open_stores
        for kwargs in ({"base_path": self.base}, {"credential": object()}):
            with self.subTest(kwargs=tuple(kwargs)), self.assertRaises(TypeError):
                open_stores(self.settings, **kwargs)
        value = self.settings.to_mapping()
        value["storage"]["root"] = "relative"
        with self.assertRaisesRegex(ValueError, "absolute|normalized"):
            open_stores(Settings.from_mapping(value))
        self.assertEqual(list(self.base.iterdir()), [])

    def test_sqlite_groups_remain_explicit_local_categories(self):
        from sec_edgar_ingest.storage.contracts import table_for
        for kind, group in (("QuarterPublication", "ActivePointers"), ("WithdrawalApproval", "Approvals"),
                            ("Attempt", "Attempts"), ("TransportAttempt", "Attempts"),
                            ("Source", "SourceState"), ("Candidate", "SourceState")):
            with self.subTest(kind=kind):
                self.assertEqual(table_for(kind), group)

    def test_legacy_registry_is_refused_before_database_creation_without_rewrite(self):
        from sec_edgar_ingest.storage import open_stores
        from sec_edgar_ingest.storage.contracts import Conflict, REGISTRY_PATH
        from support_fs import tree_snapshot
        registry = self.root / "objects" / REGISTRY_PATH
        registry.parent.mkdir(parents=True)
        legacy = b'{"binding_version":"sec-owner-binding-v1","account":"old-account"}'
        registry.write_bytes(legacy)
        before = tree_snapshot(self.root)
        with self.assertRaises(Conflict):
            open_stores(self.settings)
        self.assertEqual(tree_snapshot(self.root), before)
        self.assertEqual(registry.read_bytes(), legacy)
        self.assertFalse((self.root / "state.sqlite3").exists())


class ConfiguredDescriptorTests(unittest.TestCase):
    def setUp(self):
        from sec_edgar_ingest import runtime
        self.runtime = runtime
        self.assertTrue(callable(getattr(runtime, "configured_descriptor", None)),
                        "Task 3 requires a configured runtime descriptor without install/network/store work")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def write_release(self):
        from test_runtime import native_identity
        identity = native_identity()
        digest = hashlib.sha256(canonical_json(identity)).hexdigest()
        path = self.base / "releases" / ("sha256=" + digest) / "release.json"
        path.parent.mkdir(parents=True)
        manifest = {"format_version": "sec-native-release-v1", "release_id": digest, "identity": identity}
        path.write_bytes(canonical_json(manifest))
        value = local_mapping(self.base / "data")
        value["runtime"] = {"kind": "native", "release_manifest": str(path)}
        return path, manifest, Settings.from_mapping(value)

    def test_fixture_descriptor_hashes_only_fixture_id_without_effects(self):
        settings = Settings.from_mapping(local_mapping(self.base / "missing-data"))
        before = tuple(self.base.iterdir())
        self.assertEqual(self.runtime.configured_descriptor(settings), {
            "format_version": "sec-fixture-runtime-v1", "kind": "fixture",
            "fixture_sha256": hashlib.sha256(canonical_json({"fixture_id": "local-contract-tests-v1"})).hexdigest(),
        })
        self.assertEqual(tuple(self.base.iterdir()), before)

    def test_native_descriptor_validates_identity_and_directory_digest(self):
        path, manifest, settings = self.write_release()
        from support_fs import tree_snapshot
        before = tree_snapshot(self.base)
        self.assertEqual(self.runtime.configured_descriptor(settings), {
            "format_version": "sec-native-runtime-v1", "kind": "native", "release_sha256": manifest["release_id"],
        })
        self.assertEqual(tree_snapshot(self.base), before)
        self.assertFalse(Path(settings.storage.root).exists())
        self.assertEqual(path.read_bytes(), canonical_json(manifest))

    def test_native_descriptor_rejects_changed_identity_and_wrong_directory(self):
        path, manifest, settings = self.write_release()
        manifest["identity"]["git_revision"] = "2" * 40
        path.write_bytes(canonical_json(manifest))
        with self.assertRaises(ValueError):
            self.runtime.configured_descriptor(settings)
        manifest["release_id"] = hashlib.sha256(canonical_json(manifest["identity"])).hexdigest()
        path.write_bytes(canonical_json(manifest))
        with self.assertRaisesRegex(ValueError, "directory|address|release"):
            self.runtime.configured_descriptor(settings)

    def test_native_descriptor_rejects_duplicate_unknown_non_utf8_and_missing_manifests(self):
        path, manifest, settings = self.write_release()
        text = canonical_json(manifest).decode()
        for body in (text.replace('"release_id":', '"release_id":"' + manifest["release_id"] + '","release_id":').encode(),
                     canonical_json({**manifest, "extra": True}), text.encode("utf-16"), b'null'):
            with self.subTest(body=body[:60]), self.assertRaises(ValueError):
                path.write_bytes(body)
                self.runtime.configured_descriptor(settings)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.runtime.configured_descriptor(settings)

    def test_native_descriptor_requires_normalized_manifest_path(self):
        value = local_mapping()
        value["runtime"] = {"kind": "native", "release_manifest": "releases/sha256=" + "a" * 64 + "/release.json"}
        with self.assertRaisesRegex(ValueError, "absolute|normalized"):
            self.runtime.configured_descriptor(Settings.from_mapping(value))

    def test_native_manifest_address_is_checked_after_symlink_resolution(self):
        path, manifest, settings = self.write_release()
        outside = self.base / "outside/release.json"
        outside.parent.mkdir()
        outside.write_bytes(canonical_json(manifest))
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "directory|address|release"):
            self.runtime.configured_descriptor(settings)


if __name__ == "__main__":
    unittest.main()
