import hashlib
import copy
import importlib
import importlib.util
import unittest

from sec_edgar_ingest.models import canonical_json


class DescriptorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("sec_edgar_ingest.runtime"),
                             "Task 2 requires pure runtime descriptor contracts")
        self.runtime = importlib.import_module("sec_edgar_ingest.runtime")

    def test_fixture_descriptor_has_independently_hashed_identity(self):
        fixture_id = "local-contract-tests-v1"
        expected = hashlib.sha256(canonical_json({"fixture_id": fixture_id})).hexdigest()
        self.assertEqual(self.runtime.fixture_descriptor(fixture_id), {
            "format_version": "sec-fixture-runtime-v1", "kind": "fixture",
            "fixture_sha256": expected,
        })

    def test_native_descriptor_has_exact_fields(self):
        self.assertEqual(self.runtime.native_descriptor("a" * 64), {
            "format_version": "sec-native-runtime-v1", "kind": "native",
            "release_sha256": "a" * 64,
        })

    def test_descriptors_return_detached_copies(self):
        original = self.runtime.native_descriptor("a" * 64)
        validated = self.runtime.validate_descriptor(original)
        validated["kind"] = "changed"
        self.assertEqual(original["kind"], "native")

    def test_descriptor_kind_requires_known_string(self):
        for kind in ([], {}, True, None, 1, "other"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.runtime.validate_descriptor({"kind": kind})
        for value in ([], True, None, "native"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.runtime.validate_descriptor(value)

    def test_descriptor_fields_and_versions_are_closed(self):
        native = self.runtime.native_descriptor("a" * 64)
        invalid = [
            {"kind": "native", "release_sha256": "a" * 64},
            {key: value for key, value in native.items() if key != "release_sha256"},
            {**native, "extra": True},
            {**native, "format_version": "sec-fixture-runtime-v1"},
            {**native, "kind": "fixture"},
            {**self.runtime.fixture_descriptor("test-v1"), "kind": "native"},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.runtime.validate_descriptor(value)

    def test_hashes_require_lowercase_64_hex(self):
        for digest in ("", "a" * 63, "a" * 65, "A" * 64, "g" * 64,
                       "sha256:" + "a" * 64, [], {}, True, None):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                self.runtime.native_descriptor(digest)
            with self.subTest(fixture_digest=digest), self.assertRaises(ValueError):
                self.runtime.validate_descriptor({
                    "format_version": "sec-fixture-runtime-v1", "kind": "fixture",
                    "fixture_sha256": digest,
                })

    def test_fixture_id_is_safe_nonempty_opaque_text(self):
        for fixture_id in ("", " ", "bad\nlabel", "bad\x00label", "bad\x7flabel",
                           [], {}, True, None):
            with self.subTest(fixture_id=fixture_id), self.assertRaises(ValueError):
                self.runtime.fixture_descriptor(fixture_id)


def native_identity():
    return {
        "application": {"name": "sec-edgar-ingest", "version": "0.2.0",
                        "wheel_filename": "sec_edgar_ingest-0.2.0-py3-none-any.whl"},
        "git_revision": "1" * 40,
        "application_wheel_sha256": "a" * 64,
        "package_files": [
            {"path": "sec_edgar_ingest/__init__.py", "sha256": "b" * 64},
            {"path": "sec_edgar_ingest/runtime.py", "sha256": "c" * 64},
        ],
        "uv_lock_sha256": "d" * 64,
        "dependencies": [
            {"name": "pyarrow", "version": "25.0.1",
             "filename": "pyarrow-25.0.1-cp314-cp314-macosx_12_0_arm64.whl", "sha256": "e" * 64},
            {"name": "requests", "version": "2.34.2",
             "filename": "requests-2.34.2-py3-none-any.whl", "sha256": "f" * 64},
        ],
        "interpreter": {"implementation": "cpython", "version": "3.14.0",
                        "cache_tag": "cpython-314", "platform_tag": "macosx_11_0_arm64"},
    }


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.runtime = importlib.import_module("sec_edgar_ingest.runtime")
        self.assertTrue(callable(getattr(self.runtime, "release_id", None)),
                        "Task 2 requires canonical native release identity")
        self.assertTrue(callable(getattr(self.runtime, "validate_manifest", None)),
                        "Task 2 requires strict native release manifests")

    def manifest(self, identity=...):
        identity = native_identity() if identity is ... else identity
        return {"format_version": "sec-native-release-v1", "identity": identity,
                "release_id": hashlib.sha256(canonical_json(identity)).hexdigest()}

    def assert_invalid_identity(self, identity):
        with self.assertRaises(ValueError):
            self.runtime.release_id(identity)
        with self.assertRaises(ValueError):
            self.runtime.validate_manifest(self.manifest(identity))

    def test_manifest_matches_independent_identity_digest(self):
        manifest = self.manifest()
        self.assertEqual(self.runtime.release_id(manifest["identity"]), manifest["release_id"])
        self.assertEqual(self.runtime.validate_manifest(manifest), manifest)

    def test_object_key_order_does_not_change_identity(self):
        identity = native_identity()
        reversed_identity = {key: identity[key] for key in reversed(identity)}
        reversed_identity["application"] = dict(reversed(list(identity["application"].items())))
        self.assertEqual(self.runtime.release_id(identity), self.runtime.release_id(reversed_identity))

    def test_each_release_material_changes_identity(self):
        identity = native_identity()
        mutations = [
            ("application_wheel_sha256", "9" * 64), ("uv_lock_sha256", "9" * 64),
            ("git_revision", "2" * 40),
        ]
        variants = [{**identity, key: value} for key, value in mutations]
        for section, index, key, value in (
            ("package_files", 0, "sha256", "9" * 64),
            ("dependencies", 0, "sha256", "9" * 64),
        ):
            changed = copy.deepcopy(identity)
            changed[section][index][key] = value
            variants.append(changed)
        changed = copy.deepcopy(identity)
        changed["interpreter"]["version"] = "3.14.1"
        variants.append(changed)
        for changed in variants:
            with self.subTest(identity=changed):
                self.assertNotEqual(self.runtime.release_id(identity), self.runtime.release_id(changed))

    def test_manifest_validation_detaches_all_nested_containers(self):
        manifest = self.manifest()
        validated = self.runtime.validate_manifest(manifest)
        validated["identity"]["package_files"][0]["sha256"] = "9" * 64
        validated["identity"]["application"]["version"] = "changed"
        validated["identity"]["dependencies"].clear()
        validated["identity"]["interpreter"]["version"] = "changed"
        self.assertEqual(manifest, self.manifest())

    def test_manifest_has_exact_format_keys_and_digest(self):
        manifest = self.manifest()
        invalid = [[], {}, True, None, {**manifest, "extra": 1},
                   {**manifest, "format_version": "sec-native-release-v2"},
                   {**manifest, "release_id": "9" * 64},
                   {**manifest, "release_id": "A" * 64}]
        invalid.extend({key: item for key, item in manifest.items() if key != missing}
                       for missing in manifest)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.runtime.validate_manifest(value)

    def test_identity_and_nested_records_require_exact_object_shapes(self):
        identity = native_identity()
        for value in ([], True, None, {}, {**identity, "extra": 1}):
            with self.subTest(value=value):
                self.assert_invalid_identity(value)
        for field in identity:
            with self.subTest(missing=field):
                self.assert_invalid_identity({key: value for key, value in identity.items() if key != field})
        for field in ("application", "interpreter", "package_files", "dependencies"):
            for value in ([], {}, True, None):
                with self.subTest(field=field, value=value):
                    self.assert_invalid_identity({**identity, field: value})
        for section in ("application", "interpreter", "package_files", "dependencies"):
            original = identity[section][0] if isinstance(identity[section], list) else identity[section]
            for missing in (*original, None):
                changed = copy.deepcopy(identity)
                record = {key: value for key, value in original.items() if key != missing}
                if missing is None:
                    record["extra"] = True
                changed[section] = [record] if isinstance(identity[section], list) else record
                with self.subTest(section=section, missing=missing):
                    self.assert_invalid_identity(changed)

    def test_saved_application_version_need_not_equal_running_version(self):
        identity = native_identity()
        identity["application"]["version"] = "0.2.1"
        identity["application"]["wheel_filename"] = "sec_edgar_ingest-0.2.1-py3-none-any.whl"
        self.assertEqual(self.runtime.validate_manifest(self.manifest(identity)), self.manifest(identity))

    def test_application_name_version_and_wheel_must_agree(self):
        for field, value in (("name", "another-app"), ("name", "sec_edgar_ingest"),
                             ("version", ""), ("version", "01.2.0"),
                             ("version", "../0.2.0"), ("version", True),
                             ("version", "0.2.1"),
                             ("wheel_filename", "other-0.2.0-py3-none-any.whl"),
                             ("wheel_filename", "sec_edgar_ingest-0.2.0.tar.gz")):
            identity = native_identity()
            identity["application"][field] = value
            with self.subTest(field=field, value=value):
                self.assert_invalid_identity(identity)

    def test_application_versions_are_canonical_even_with_matching_filenames(self):
        for version in ("01.2.0", "0!0.2.0", "0.2.0+01", "v0.2.0", "0.2.0RC1"):
            identity = native_identity()
            identity["application"]["version"] = version
            identity["application"]["wheel_filename"] = f"sec_edgar_ingest-{version}-py3-none-any.whl"
            with self.subTest(version=version):
                self.assert_invalid_identity(identity)

    def test_application_wheel_tags_and_optional_build_tag_are_validated(self):
        identity = native_identity()
        identity["application"]["wheel_filename"] = "sec_edgar_ingest-0.2.0-1build-py3-none-any.whl"
        self.assertEqual(self.runtime.validate_manifest(self.manifest(identity)), self.manifest(identity))
        for tail in ("build-py3-none-any", "py3-none", "py3-none-", "py3-none-any-extra", "py3-none-any..bad"):
            identity = native_identity()
            identity["application"]["wheel_filename"] = f"sec_edgar_ingest-0.2.0-{tail}.whl"
            with self.subTest(tail=tail):
                self.assert_invalid_identity(identity)

    def test_artifact_hashes_and_git_revision_are_strict(self):
        for value in ("", "A" * 64, "g" * 64, "a" * 63, True, None, []):
            for field in ("application_wheel_sha256", "uv_lock_sha256"):
                with self.subTest(field=field, value=value):
                    self.assert_invalid_identity({**native_identity(), field: value})
            for field in ("package_files", "dependencies"):
                identity = native_identity()
                identity[field][0]["sha256"] = value
                with self.subTest(field=field, value=value):
                    self.assert_invalid_identity(identity)
        for value in ("", "main", "1" * 39, "A" * 40, True, None):
            with self.subTest(git_revision=value):
                self.assert_invalid_identity({**native_identity(), "git_revision": value})

    def test_package_paths_are_sorted_unique_safe_payload_paths(self):
        for path in ("/sec_edgar_ingest/a.py", "../sec_edgar_ingest/a.py",
                     "sec_edgar_ingest/../a.py", "sec_edgar_ingest//a.py",
                     "sec_edgar_ingest/./a.py", "sec_edgar_ingest\\a.py",
                     "other/a.py", "sec_edgar_ingest/__pycache__/a.pyc",
                     "sec_edgar_ingest/a.pyc", "sec_edgar_ingest/a.pyo",
                     "sec_edgar_ingest", "", True):
            identity = native_identity()
            identity["package_files"] = [{"path": path, "sha256": "a" * 64}]
            with self.subTest(path=path):
                self.assert_invalid_identity(identity)
        for records in (list(reversed(native_identity()["package_files"])),
                        [native_identity()["package_files"][0]] * 2):
            self.assert_invalid_identity({**native_identity(), "package_files": records})

    def test_dependencies_are_sorted_unique_normalized_distributions(self):
        for name in ("Requests", "charset_normalizer", "charset.normalizer", "bad--name",
                     "../bad", "", True):
            identity = native_identity()
            identity["dependencies"][0]["name"] = name
            with self.subTest(name=name):
                self.assert_invalid_identity(identity)
        for records in (list(reversed(native_identity()["dependencies"])),
                        [native_identity()["dependencies"][0]] * 2):
            self.assert_invalid_identity({**native_identity(), "dependencies": records})

    def test_artifact_names_exclude_install_paths_and_unsafe_text(self):
        for name in ("/tmp/artifact.whl", "../artifact.whl", "dir/artifact.whl",
                     "dir\\artifact.whl", ".", "..", "bad\nfile.whl", "", True):
            identity = native_identity()
            identity["application"]["wheel_filename"] = name
            with self.subTest(application_filename=name):
                self.assert_invalid_identity(identity)
            identity = native_identity()
            identity["dependencies"][0]["filename"] = name
            with self.subTest(dependency_filename=name):
                self.assert_invalid_identity(identity)

    def test_interpreter_requires_supported_native_contract(self):
        for field, values in {
            "implementation": ("pypy", "CPython", True),
            "version": ("3.13.9", "3.15.0", "3.14", "3.14.00", True),
            "cache_tag": ("cpython-313", "", True),
            "platform_tag": ("linux_aarch64", "macosx_11_0_x86_64", "/tmp/python", True),
        }.items():
            for value in values:
                identity = native_identity()
                identity["interpreter"][field] = value
                with self.subTest(field=field, value=value):
                    self.assert_invalid_identity(identity)

    def test_timestamps_and_host_paths_cannot_enter_identity(self):
        for field, value in (("created_at", "2026-10-17T00:00:00Z"),
                             ("venv", "/tmp/venv"), ("executable", "/tmp/python")):
            with self.subTest(field=field):
                self.assert_invalid_identity({**native_identity(), field: value})


if __name__ == "__main__":
    unittest.main()
