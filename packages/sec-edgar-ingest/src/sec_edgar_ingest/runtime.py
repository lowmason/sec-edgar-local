"""Runtime descriptors, canonical release identity, and read-only configured provenance."""

from __future__ import annotations

from collections.abc import Mapping
import ast
from dataclasses import dataclass
import importlib.metadata
import importlib.util
import json
import os
import platform
import subprocess
import sys
import tomllib
import zipfile
from pathlib import PurePosixPath
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


# The parent verifies application bytes before this isolated interpreter probe.
# The probe checks import origin before importing the module for its version.
INSTALLATION_PROBE = r'''
import importlib.metadata as metadata, importlib.util, json, platform, re, sys
from pathlib import Path
inventory = {}
for distribution in metadata.distributions():
    name = re.sub(r'[-_.]+', '-', distribution.metadata['Name']).lower()
    if name in inventory:
        raise ValueError('duplicate installed distribution')
    inventory[name] = distribution.version
    direct = distribution.read_text('direct_url.json')
    if direct and json.loads(direct).get('dir_info', {}).get('editable'):
        raise ValueError('editable installation refused')
origin = Path(importlib.util.find_spec('sec_edgar_ingest').origin)
expected = Path(sys.prefix) / 'lib/python3.14/site-packages/sec_edgar_ingest/__init__.py'
if origin != expected or not origin.resolve().is_relative_to(Path(sys.prefix).resolve()):
    raise ValueError('application import origin escapes the referenced installation')
import sec_edgar_ingest
major, minor, *_ = platform.mac_ver()[0].split('.')
print(json.dumps({'interpreter': {'implementation': sys.implementation.name,
    'version': platform.python_version(), 'cache_tag': sys.implementation.cache_tag,
    'platform_tag': f'macosx_{major}_{minor}_{platform.machine()}'},
    'inventory': inventory, 'prefix': sys.prefix, 'executable': sys.executable,
    'origin': sec_edgar_ingest.__file__, 'application_version': sec_edgar_ingest.__version__}))
'''


@dataclass(frozen=True)
class VerifiedRelease:
    release_id: str
    manifest: Mapping[str, object]
    directory: Path
    python: Path


def hash_file(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def interpreter_identity(python: Path) -> dict[str, object]:
    code = ('import json,sys,platform; '
            'v=platform.mac_ver()[0].split("."); '
            'print(json.dumps({"implementation":sys.implementation.name,'
            '"version":platform.python_version(),"cache_tag":sys.implementation.cache_tag,'
            '"platform_tag":"macosx_"+"_".join(v[:2])+"_"+platform.machine()}))')
    result = subprocess.run([str(python), '-I', '-c', code], check=True, capture_output=True, text=True,
                            env=isolated_environment())
    return _interpreter(json.loads(result.stdout))


def isolated_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('PYTHON', 'UV_')) and key not in {'VIRTUAL_ENV', 'CONDA_PREFIX'}}
    environment.update(UV_OFFLINE='1', UV_PYTHON_DOWNLOADS='never', UV_LINK_MODE='copy')
    return environment


def wheel_payload(wheel: Path) -> list[dict[str, str]]:
    """Inventory all package bytes, refusing ambiguous or escaping ZIP entries."""
    records, names = [], set()
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            name = member.filename
            path = PurePosixPath(name)
            if (name in names or name.startswith('/') or '\\' in name
                    or any(part in ('', '.', '..') for part in name.rstrip('/').split('/'))):
                raise ValueError('unsafe or duplicate wheel member')
            names.add(name)
            if member.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError('wheel symlink members are refused')
            if not member.is_dir() and path.parts[0] == 'sec_edgar_ingest':
                records.append({'path': name, 'sha256': hashlib.sha256(archive.read(member)).hexdigest()})
    return _package_files(sorted(records, key=lambda item: item['path']))


def _lock_marker(expression: str | None) -> bool:
    if expression is None:
        return True
    environment = {'implementation_name': 'cpython', 'platform_python_implementation': 'CPython'}
    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in environment:
            return environment[node.id]
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [evaluate(value) for value in node.values]
            if any(type(value) is not bool for value in values):
                raise ValueError('invalid lock marker boolean')
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left, right = evaluate(node.left), evaluate(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise ValueError('unsupported lock marker')
    result = evaluate(ast.parse(expression, mode='eval'))
    if type(result) is not bool:
        raise ValueError('invalid lock marker')
    return result


def locked_dependencies(lock_body: bytes) -> dict[str, dict[str, object]]:
    """Traverse the complete applicable graph, excluding the workspace distribution."""
    packages = {}
    for package in tomllib.loads(lock_body.decode())['package']:
        name = package['name']
        if name in packages:
            raise ValueError('ambiguous package alternatives in lock')
        packages[name] = package
    active, visited, queue = {}, set(), ['sec-edgar-ingest']
    while queue:
        name = queue.pop()
        if name in visited:
            continue
        visited.add(name)
        package = packages[name]
        if name != 'sec-edgar-ingest':
            if set(package['source']) != {'registry'}:
                raise ValueError('runtime dependencies require locked registry artifacts')
            active[name] = package
        queue.extend(item['name'] for item in package.get('dependencies', ()) if _lock_marker(item.get('marker')))
    return dict(sorted(active.items()))


def verify_requirements(lock_body: bytes, export_body: bytes) -> dict[str, dict[str, object]]:
    active = locked_dependencies(lock_body)
    packages = {item['name']: item for item in tomllib.loads(lock_body.decode())['package']}
    blocks, current = [], []
    for line in export_body.decode().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if re.match(r'^[A-Za-z0-9][A-Za-z0-9_.-]*==', line):
            if current:
                blocks.append(' '.join(current))
            current = []
        elif not current or not line.strip().startswith('--hash='):
            raise ValueError('requirements must contain external exact hashed pins only')
        current.append(line.strip().removesuffix('\\').strip())
    if current:
        blocks.append(' '.join(current))
    exported = {}
    for block in blocks:
        head, *hashes = block.split('--hash=')
        match = re.fullmatch(r'([a-z0-9]+(?:-[a-z0-9]+)*)==([^\s;]+)(?:\s*;\s*(.*))?\s*', head)
        if match is None:
            raise ValueError('invalid locked requirement')
        name, version, marker = match.groups()
        if name not in packages or name == 'sec-edgar-ingest' or version != packages[name]['version']:
            raise ValueError('requirements version differs from lock')
        expected = {item['hash'] for item in packages[name].get('wheels', ())}
        if packages[name].get('sdist'):
            expected.add(packages[name]['sdist']['hash'])
        if {item.strip() for item in hashes} != expected:
            raise ValueError('requirements artifact hashes differ from lock')
        if _lock_marker(marker):
            if name in exported:
                raise ValueError('duplicate requirement')
            exported[name] = version
    if exported != {name: item['version'] for name, item in active.items()}:
        raise ValueError('requirements differ from full transitive locked inventory')
    return active


def retained_release(manifest_path: Path) -> tuple[dict[str, object], Path]:
    """Verify portable retained evidence without executing or installing anything."""
    manifest_path = manifest_path.absolute()
    directory = manifest_path.parent
    body = manifest_path.read_bytes()
    manifest = validate_manifest(parse_json(body))
    if canonical_json(manifest) != body:
        raise ValueError('release manifest must use canonical JSON')
    if manifest_path.name != 'release.json' or directory.name != 'sha256=' + manifest['release_id']:
        raise ValueError('release directory differs from manifest identity')
    identity = manifest['identity']
    lock_body = (directory / 'uv.lock').read_bytes()
    if hashlib.sha256(lock_body).hexdigest() != identity['uv_lock_sha256']:
        raise ValueError('retained lock hash differs')
    locked = verify_requirements(lock_body, (directory / 'runtime-requirements.txt').read_bytes())
    dependencies = identity['dependencies']
    if {item['name']: item['version'] for item in dependencies} != {name: item['version'] for name, item in locked.items()}:
        raise ValueError('artifact identity differs from full transitive inventory')
    artifacts = directory / 'artifacts'
    if {path.name for path in artifacts.iterdir()} != {item['filename'] for item in dependencies}:
        raise ValueError('retained artifact inventory differs')
    for item in dependencies:
        matches = [wheel for wheel in locked[item['name']].get('wheels', ())
                   if Path(wheel['url']).name == item['filename'] and wheel['hash'] == 'sha256:' + item['sha256']]
        if len(matches) != 1 or hash_file(artifacts / item['filename']) != item['sha256']:
            raise ValueError('dependency artifact identity or hash differs')
    wheel = directory / 'wheels' / identity['application']['wheel_filename']
    if hash_file(wheel) != identity['application_wheel_sha256']:
        raise ValueError('application wheel hash differs')
    if wheel_payload(wheel) != identity['package_files']:
        raise ValueError('application wheel payload differs')
    return manifest, directory


def _verify_payload(directory: Path, identity: Mapping[str, object]) -> Path:
    sites = list((directory / 'venv/lib').glob('python3.14/site-packages'))
    if len(sites) != 1:
        raise ValueError('release installation site-packages is missing or ambiguous')
    site = sites[0]
    package = site / 'sec_edgar_ingest'
    expected_venv = directory.resolve() / 'venv'
    if not site.resolve().is_relative_to(expected_venv) or not package.resolve().is_relative_to(expected_venv):
        raise ValueError('application installation escapes the referenced release venv')
    actual = []
    for path in sorted(package.rglob('*')):
        if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
            continue
        if path.is_symlink():
            raise ValueError('application payload symlinks are refused')
        if path.is_file():
            actual.append({'path': path.relative_to(site).as_posix(), 'sha256': hash_file(path)})
    if actual != identity['package_files']:
        raise ValueError('installed application payload differs')
    return site


def _check_evidence(evidence: Mapping[str, object], directory: Path, identity: Mapping[str, object], python: Path) -> None:
    if (evidence['interpreter'] != identity['interpreter'] or Path(evidence['prefix']) != directory / 'venv'
            or Path(evidence['executable']).absolute() != python):
        raise ValueError('interpreter does not identify the referenced installation')
    origin = Path(evidence['origin'])
    site = directory / 'venv/lib/python3.14/site-packages'
    if origin != site / 'sec_edgar_ingest/__init__.py' or not origin.resolve().is_relative_to(directory.resolve() / 'venv'):
        raise ValueError('application import origin differs from referenced installation')
    if evidence['application_version'] != identity['application']['version']:
        raise ValueError('installed application module version differs from distribution version')
    expected = {item['name']: item['version'] for item in identity['dependencies']}
    expected[identity['application']['name']] = identity['application']['version']
    if evidence['inventory'] != expected:
        raise ValueError('installed dependency inventory differs from exact release inventory')


def _preflight(manifest_path: Path, *, executable: Path | None = None, require_receipt: bool = True) -> VerifiedRelease:
    manifest, directory = retained_release(manifest_path)
    python = directory / 'venv/bin/python'
    if executable is not None and executable.absolute() != python:
        raise ValueError('interpreter must be the referenced installation executable')
    identity = manifest['identity']
    _verify_payload(directory, identity)
    if require_receipt:
        receipt = parse_json((directory / 'installation.json').read_bytes())
        if receipt != {'format_version': 'sec-native-installation-v1', 'release_id': manifest['release_id'], 'python': str(python)}:
            raise ValueError('installation receipt differs from release')
    if not (directory / 'setup.json').is_file():
        raise ValueError('release setup evidence is incomplete')
    result = subprocess.run([str(python), '-I', '-c', INSTALLATION_PROBE], check=True,
                            capture_output=True, text=True, env=isolated_environment())
    _check_evidence(json.loads(result.stdout), directory, identity, python)
    return VerifiedRelease(manifest['release_id'], manifest, directory, python)


def preflight(manifest_path: Path, *, executable: Path | None = None) -> VerifiedRelease:
    """Read-only verification of retained and isolated installed release evidence."""
    return _preflight(manifest_path, executable=executable)


def preflight_current(manifest_path: Path) -> VerifiedRelease:
    """Also require this process and imported application to be that installation."""
    verified = preflight(manifest_path)
    major, minor, *_ = platform.mac_ver()[0].split('.')
    inventory = {}
    for distribution in importlib.metadata.distributions():
        name = re.sub(r'[-_.]+', '-', distribution.metadata['Name']).lower()
        if name in inventory:
            raise ValueError('duplicate executing installed distribution')
        inventory[name] = distribution.version
        direct = distribution.read_text('direct_url.json')
        if direct and json.loads(direct).get('dir_info', {}).get('editable'):
            raise ValueError('executing installation must not be editable')
    _check_evidence({'interpreter': {'implementation': sys.implementation.name,
        'version': platform.python_version(), 'cache_tag': sys.implementation.cache_tag,
        'platform_tag': f'macosx_{major}_{minor}_{platform.machine()}'},
        'prefix': sys.prefix, 'executable': sys.executable, 'inventory': inventory,
        'origin': sys.modules[__package__].__file__, 'application_version': sys.modules[__package__].__version__},
        verified.directory, verified.manifest['identity'], verified.python)
    return verified
