"""Runtime descriptors, canonical release identity, and read-only configured provenance."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .models import canonical_json, parse_json, require_hash, require_text, safe_relative_path

if TYPE_CHECKING:
    from .config import Settings
    from .storage.contracts import ObjectStore


IDENTITY_FIELDS = {
    "application", "git_revision", "application_wheel_sha256", "package_files",
    "uv_lock_sha256", "dependencies", "interpreter",
}
CANONICAL_NUMBER = r"(?:0|[1-9][0-9]*)"
CANONICAL_LOCAL_SEGMENT = rf"(?:[a-z0-9]*[a-z][a-z0-9]*|{CANONICAL_NUMBER})"
VERSION_PATTERN = re.compile(
    rf"(?:[1-9][0-9]*!)?{CANONICAL_NUMBER}(?:\.{CANONICAL_NUMBER})*"
    rf"(?:(?:a|b|rc){CANONICAL_NUMBER})?(?:\.post{CANONICAL_NUMBER})?"
    rf"(?:\.dev{CANONICAL_NUMBER})?"
    rf"(?:\+{CANONICAL_LOCAL_SEGMENT}(?:\.{CANONICAL_LOCAL_SEGMENT})*)?\Z"
)
DISTRIBUTION_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
GIT_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
PLATFORM_TAG_PATTERN = re.compile(r"macosx_(?:[1-9][0-9]*)_(?:0|[1-9][0-9]*)_arm64\Z")
INTERPRETER_VERSION_PATTERN = re.compile(r"3\.14\.(?:0|[1-9][0-9]*)\Z")
ARTIFACT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+!-]*\Z")
WHEEL_TAG_PATTERN = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*\Z")


def validate_descriptor(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("runtime descriptor must be an object")
    variants = {
        "native": ("sec-native-runtime-v1", "release_sha256"),
        "fixture": ("sec-fixture-runtime-v1", "fixture_sha256"),
    }
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise ValueError("runtime kind must be a string")
    variant = variants.get(kind)
    if variant is None:
        raise ValueError("unsupported runtime kind")
    version, digest_key = variant
    if set(value) != {"format_version", "kind", digest_key}:
        raise ValueError("runtime descriptor requires exact fields")
    if value["format_version"] != version:
        raise ValueError("unsupported runtime descriptor version")
    require_hash(value[digest_key], digest_key)
    return dict(value)


def fixture_descriptor(fixture_id: str) -> dict[str, object]:
    require_text(fixture_id, "fixture_id")
    digest = hashlib.sha256(canonical_json({"fixture_id": fixture_id})).hexdigest()
    return validate_descriptor({
        "format_version": "sec-fixture-runtime-v1", "kind": "fixture",
        "fixture_sha256": digest,
    })


def native_descriptor(release_id: str) -> dict[str, object]:
    return validate_descriptor({
        "format_version": "sec-native-runtime-v1", "kind": "native",
        "release_sha256": release_id,
    })


def configured_descriptor(settings: Settings) -> dict[str, object]:
    """Read saved provenance without installation, network access, or opening a store."""
    from .config import Settings
    validated = Settings.from_mapping(settings.to_mapping())
    if validated.runtime.kind == "fixture":
        return fixture_descriptor(validated.runtime.fixture_id)
    path = Path(validated.runtime.release_manifest)
    if not path.is_absolute():
        raise ValueError("runtime.release_manifest must be normalized to an absolute filesystem path")
    path = path.resolve()
    if (path.name != "release.json" or path.parent.parent.name != "releases"
            or re.fullmatch(r"sha256=[0-9a-f]{64}", path.parent.name) is None):
        raise ValueError("resolved release manifest must use an explicit releases/sha256=<release-id>/release.json address")
    manifest = validate_manifest(parse_json(path.read_bytes()))
    if path.parent.name != "sha256=" + manifest["release_id"]:
        raise ValueError("release manifest identity differs from its release directory address")
    return native_descriptor(manifest["release_id"])


def _exact_object(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{label} requires an object with exact fields")
    return dict(value)


def _require_pattern(value: object, pattern: re.Pattern[str], label: str) -> None:
    require_text(value, label)
    if pattern.fullmatch(value) is None:
        raise ValueError(f"unsupported {label}")


def _artifact_basename(value: object, label: str) -> str:
    safe_relative_path(value, label)
    if "/" in value or ARTIFACT_NAME_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a safe artifact basename")
    return value


def _application(value: object) -> dict[str, object]:
    application = _exact_object(value, {"name", "version", "wheel_filename"}, "application")
    if application["name"] != "sec-edgar-ingest":
        raise ValueError("unsupported application distribution")
    version = application["version"]
    _require_pattern(version, VERSION_PATTERN, "application version")
    filename = _artifact_basename(application["wheel_filename"], "application wheel_filename")
    prefix = f"sec_edgar_ingest-{version}-"
    if not filename.startswith(prefix) or not filename.endswith(".whl"):
        raise ValueError("application wheel filename must match name/version")
    tags = filename[len(prefix):-len(".whl")].split("-")
    if len(tags) == 4:
        build_tag = tags.pop(0)
        if re.fullmatch(r"[0-9][A-Za-z0-9_]*", build_tag) is None:
            raise ValueError("invalid application wheel build tag")
    if len(tags) != 3 or any(WHEEL_TAG_PATTERN.fullmatch(tag) is None for tag in tags):
        raise ValueError("invalid application wheel tags")
    return application


def _package_files(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError("package_files must be a nonempty array")
    records = []
    for item in value:
        record = _exact_object(item, {"path", "sha256"}, "package file")
        path = safe_relative_path(record["path"], "package path")
        if not path.startswith("sec_edgar_ingest/") or "__pycache__" in path.split("/") or path.endswith((".pyc", ".pyo")):
            raise ValueError("package path must be application payload without bytecode caches")
        require_hash(record["sha256"], "package file sha256")
        records.append(record)
    paths = [record["path"] for record in records]
    if paths != sorted(set(paths)):
        raise ValueError("package paths must be sorted and unique")
    return records


def _dependencies(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError("dependencies must be a nonempty array")
    records = []
    for item in value:
        record = _exact_object(item, {"name", "version", "filename", "sha256"}, "dependency")
        _require_pattern(record["name"], DISTRIBUTION_PATTERN, "normalized dependency name")
        _require_pattern(record["version"], VERSION_PATTERN, "dependency version")
        _artifact_basename(record["filename"], "dependency filename")
        require_hash(record["sha256"], "dependency sha256")
        records.append(record)
    names = [record["name"] for record in records]
    if names != sorted(set(names)):
        raise ValueError("dependency names must be sorted and unique")
    return records


def _interpreter(value: object) -> dict[str, object]:
    interpreter = _exact_object(value, {"implementation", "version", "cache_tag", "platform_tag"}, "interpreter")
    if interpreter["implementation"] != "cpython" or interpreter["cache_tag"] != "cpython-314":
        raise ValueError("release requires CPython 3.14")
    _require_pattern(interpreter["version"], INTERPRETER_VERSION_PATTERN, "interpreter version")
    _require_pattern(interpreter["platform_tag"], PLATFORM_TAG_PATTERN, "macOS arm64 platform tag")
    return interpreter


def _identity(value: object) -> dict[str, object]:
    identity = _exact_object(value, IDENTITY_FIELDS, "release identity")
    identity["application"] = _application(identity["application"])
    _require_pattern(identity["git_revision"], GIT_REVISION_PATTERN, "Git revision")
    require_hash(identity["application_wheel_sha256"], "application_wheel_sha256")
    require_hash(identity["uv_lock_sha256"], "uv_lock_sha256")
    identity["package_files"] = _package_files(identity["package_files"])
    identity["dependencies"] = _dependencies(identity["dependencies"])
    identity["interpreter"] = _interpreter(identity["interpreter"])
    return identity


def release_id(identity: Mapping[str, object]) -> str:
    """Hash a validated identity; dictionary insertion order never affects it."""
    return hashlib.sha256(canonical_json(_identity(identity))).hexdigest()


def validate_manifest(value: Mapping[str, object]) -> dict[str, object]:
    """Validate saved release provenance independently of the executing release."""
    manifest = _exact_object(value, {"format_version", "release_id", "identity"}, "release manifest")
    if manifest["format_version"] != "sec-native-release-v1":
        raise ValueError("unsupported release manifest version")
    require_hash(manifest["release_id"], "release_id")
    manifest["identity"] = _identity(manifest["identity"])
    expected = hashlib.sha256(canonical_json(manifest["identity"])).hexdigest()
    if manifest["release_id"] != expected:
        raise ValueError("release_id does not match canonical release identity")
    return parse_json(canonical_json(manifest))


def validate_producer(runtime: Mapping[str, object], objects: ObjectStore) -> None:
    """Verify retained producer evidence without consulting the executing environment."""
    descriptor = validate_descriptor(runtime)
    if descriptor['kind'] == 'fixture':
        return
    release_id = descriptor['release_sha256']
    path = f'runtime/native/sha256={release_id}/release.json'
    body = objects.read(path)
    manifest = validate_manifest(parse_json(body))
    if manifest['release_id'] != release_id:
        raise ValueError('saved producer manifest differs from runtime release identity')
    if canonical_json(manifest) != body:
        raise ValueError('saved producer manifest must use canonical JSON')


def retain_manifest(objects: ObjectStore, manifest: Mapping[str, object]) -> str:
    """Retain verified native identity after preflight; historical readers never call this."""
    verified = validate_manifest(manifest)
    path = f"runtime/native/sha256={verified['release_id']}/release.json"
    objects.put_once(path, canonical_json(verified))
    validate_producer(native_descriptor(verified['release_id']), objects)
    return path
