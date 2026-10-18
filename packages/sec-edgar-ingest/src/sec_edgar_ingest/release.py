"""Explicit artifact setup and immutable native release installation.

Nothing in this module is called by ingestion preflight. Online work is confined
to the explicit cache preparation operation and uses locked public artifacts.
"""
from __future__ import annotations

import email.parser
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .models import canonical_json, parse_json
from .runtime import (
    _preflight, hash_file, interpreter_identity, isolated_environment,
    locked_dependencies, native_console_script, preflight, release_id, retained_release,
    validate_manifest, verify_requirements, wheel_payload,
)

BUILD_VERSION = '0.12.24'
BUILD_REQUIREMENT = 'uv_build>=0.12.15,<0.13.0'
CACHE_FORMAT = 'sec-native-artifact-cache-v1'


def _wheel_rank(filename: str, interpreter: dict[str, object]) -> tuple[int, int, int] | None:
    """Supported host wheel tags, with native CPython preferred to universal Python."""
    if not filename.endswith('.whl'):
        return None
    python_tag, abi_tag, platform_tag = filename[:-4].rsplit('-', 3)[-3:]
    python_tags, abi_tags = python_tag.split('.'), abi_tag.split('.')
    if 'cp314' in python_tags and 'cp314' in abi_tags:
        python_rank = 0
    elif 'py3' in python_tags and 'none' in abi_tags:
        python_rank = 1
    else:
        return None
    if platform_tag == 'any':
        return python_rank, 1, 0
    host = re.fullmatch(r'macosx_([0-9]+)_([0-9]+)_arm64', interpreter['platform_tag'])
    host_version = tuple(map(int, host.groups()))
    ranks = []
    for tag in platform_tag.split('.'):
        match = re.fullmatch(r'macosx_([0-9]+)_([0-9]+)_(arm64|universal2)', tag)
        if match and tuple(map(int, match.groups()[:2])) <= host_version:
            major, minor = map(int, match.groups()[:2])
            ranks.append((python_rank, 0 if match[3] == 'arm64' else 1, -(major * 100 + minor)))
    return min(ranks) if ranks else None


def _select_wheel(wheels: list[dict[str, object]], interpreter: dict[str, object]) -> dict[str, str]:
    compatible = []
    for artifact in wheels:
        filename = Path(urlsplit(artifact['url']).path).name
        rank = _wheel_rank(filename, interpreter)
        if rank is not None:
            compatible.append((rank, filename, artifact))
    if not compatible:
        raise ValueError('no compatible locked wheel for supported interpreter')
    _, filename, artifact = min(compatible, key=lambda item: (item[0], item[1]))
    return {'filename': filename, 'url': artifact['url'], 'sha256': artifact['hash'].removeprefix('sha256:')}


def _download(url: str, path: Path, sha256: str) -> None:
    if urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in {'pypi.org', 'files.pythonhosted.org'}:
        raise ValueError('setup permits only locked public package artifact hosts')
    with urllib.request.urlopen(url, timeout=60) as response, path.open('xb') as stream:
        shutil.copyfileobj(response, stream)
    if hash_file(path) != sha256:
        raise ValueError('downloaded artifact hash differs from locked identity')


def _cache_inventory(lock_body: bytes, interpreter: dict[str, object], cache: Path) -> dict[str, object]:
    path = cache / 'artifacts.json'
    if not path.is_file():
        raise ValueError('artifact cache absent: run explicit --prepare-cache-only setup first')
    inventory = parse_json(path.read_bytes())
    if (set(inventory) != {'format_version', 'uv_lock_sha256', 'interpreter', 'artifacts'}
            or inventory['format_version'] != CACHE_FORMAT
            or inventory['uv_lock_sha256'] != hashlib.sha256(lock_body).hexdigest()
            or inventory['interpreter'] != interpreter):
        raise ValueError('artifact cache lock/interpreter identity differs; run explicit setup')
    expected_runtime = [dict(_select_wheel(package['wheels'], interpreter), role='runtime')
                        for package in locked_dependencies(lock_body).values()]
    entries = inventory['artifacts']
    runtime = [item for item in entries if item.get('role') == 'runtime']
    build = [item for item in entries if item.get('role') == 'build']
    if (entries != sorted(entries, key=lambda item: (item['role'], item['filename']))
            or runtime != sorted(expected_runtime, key=lambda item: item['filename'])
            or len(build) != 1 or len(entries) != len(runtime) + 1):
        raise ValueError('artifact cache inventory differs from locked runtime/build selection')
    for item in entries:
        if (set(item) != {'filename', 'url', 'sha256', 'role'}
                or Path(urlsplit(item['url']).path).name != item['filename']
                or '/' in item['filename'] or '\\' in item['filename']
                or re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is None):
            raise ValueError('invalid artifact cache entry')
        if hash_file(cache / item['role'] / item['filename']) != item['sha256']:
            raise ValueError('cached artifact hash differs')
    if not build[0]['filename'].startswith(f'uv_build-{BUILD_VERSION}-'):
        raise ValueError('build backend differs from pinned resolved version')
    _wheel_metadata(cache / 'build' / build[0]['filename'], 'uv-build', BUILD_VERSION)
    return inventory


def prepare_artifact_cache(lock: Path, python: Path, cache: Path, *, offline: bool = False) -> Path:
    """Select and hash-check all setup wheels; never requires a clean source tree."""
    lock, cache = lock.absolute(), cache.absolute()
    lock_body = lock.read_bytes()
    interpreter = interpreter_identity(python)
    if (cache / 'artifacts.json').exists() or offline:
        _cache_inventory(lock_body, interpreter, cache)
        return cache / 'artifacts.json'
    entries = [dict(_select_wheel(package['wheels'], interpreter), role='runtime')
               for package in locked_dependencies(lock_body).values()]
    with urllib.request.urlopen(f'https://pypi.org/pypi/uv_build/{BUILD_VERSION}/json', timeout=60) as response:
        metadata = json.load(response)
    wheels = [{'url': item['url'], 'hash': 'sha256:' + item['digests']['sha256']}
              for item in metadata['urls'] if item['packagetype'] == 'bdist_wheel']
    entries.append(dict(_select_wheel(wheels, interpreter), role='build'))
    cache.mkdir(parents=True, exist_ok=True)
    for item in entries:
        directory = cache / item['role']
        directory.mkdir(exist_ok=True)
        path = directory / item['filename']
        if not path.exists():
            _download(item['url'], path, item['sha256'])
        if hash_file(path) != item['sha256']:
            raise ValueError('cached artifact hash differs')
    inventory = {'format_version': CACHE_FORMAT, 'uv_lock_sha256': hashlib.sha256(lock_body).hexdigest(),
                 'interpreter': interpreter, 'artifacts': sorted(entries, key=lambda item: (item['role'], item['filename']))}
    (cache / 'artifacts.json').write_bytes(canonical_json(inventory))
    build = next(item for item in entries if item['role'] == 'build')
    constraints = f'uv_build=={BUILD_VERSION} --hash=sha256:{build["sha256"]}\n'
    (cache / 'build-requirements.txt').write_text(constraints)
    environment = isolated_environment()
    environment['UV_CACHE_DIR'] = str(cache / 'uv-build')
    # Populate the separate uv cache from the retained, verified wheel only.
    subprocess.run(['uv', 'pip', 'install', '--python', str(python), '--target', str(cache / 'build-tool'),
                    '--offline', '--no-index', '--no-deps', str(cache / 'build' / build['filename'])],
                   check=True, env=environment, capture_output=True, text=True)
    _cache_inventory(lock_body, interpreter, cache)
    return cache / 'artifacts.json'


def _wheel_metadata(wheel: Path, name: str, version: str) -> None:
    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [item for item in archive.namelist() if item.endswith('.dist-info/METADATA')]
        if len(metadata_paths) != 1:
            raise ValueError('wheel metadata is missing or ambiguous')
        metadata = email.parser.BytesParser().parsebytes(archive.read(metadata_paths[0]))
        normalized = re.sub(r'[-_.]+', '-', metadata['Name']).lower()
        if normalized != name or metadata['Version'] != version:
            raise ValueError('wheel distribution/version differs from expected application')
        wheel_metadata_path = metadata_paths[0].removesuffix('METADATA') + 'WHEEL'
        wheel_metadata = email.parser.BytesParser().parsebytes(archive.read(wheel_metadata_path))
        python_tag, abi_tag, platform_tag = wheel.name[:-4].rsplit('-', 3)[-3:]
        filename_tags = {f'{python}-{abi}-{platform}' for python in python_tag.split('.')
                         for abi in abi_tag.split('.') for platform in platform_tag.split('.')}
        if set(wheel_metadata.get_all('Tag', [])) != filename_tags:
            raise ValueError('wheel metadata tags differ from filename tags')


def _committed_revision(project: Path) -> str:
    status = subprocess.run(['git', '-C', str(project), 'status', '--porcelain', '--untracked-files=all'],
                            check=True, capture_output=True, text=True)
    if status.stdout:
        raise ValueError('release build requires a clean committed source tree, including untracked implementation files')
    revision = subprocess.run(['git', '-C', str(project), 'rev-parse', 'HEAD'],
                              check=True, capture_output=True, text=True).stdout.strip()
    return revision


def _install(manifest: dict[str, object], releases: Path, retained: Path, python: Path, setup: dict[str, object]) -> Path:
    directory = releases.resolve() / ('sha256=' + manifest['release_id'])
    if directory.exists():
        try:
            verified = preflight(directory / 'release.json')
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise ValueError('existing release is incomplete or conflicting; it was not modified') from error
        if verified.manifest != manifest:
            raise ValueError('existing release identity conflicts')
        return directory
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir()
    for name in ('wheels', 'artifacts'):
        shutil.copytree(retained / name, directory / name)
    for name in ('uv.lock', 'runtime-requirements.txt', 'release.json'):
        shutil.copyfile(retained / name, directory / name)
    (directory / 'setup.json').write_bytes(canonical_json(setup))
    # Recheck every retained artifact before the first installation operation.
    retained_release(directory / 'release.json')
    environment = isolated_environment()
    environment['UV_CACHE_DIR'] = str(directory / 'setup-uv-cache')
    venv = directory / 'venv'
    subprocess.run(['uv', 'venv', '--python', str(python), str(venv)], check=True,
                   env=environment, capture_output=True, text=True)
    subprocess.run(['uv', 'pip', 'install', '--python', str(venv / 'bin/python'),
                    '--offline', '--no-index', '--find-links', str(directory / 'artifacts'),
                    '--require-hashes', '-r', str(directory / 'runtime-requirements.txt')],
                   check=True, env=environment, capture_output=True, text=True)
    identity = manifest['identity']
    wheel = directory / 'wheels' / identity['application']['wheel_filename']
    if hash_file(wheel) != identity['application_wheel_sha256']:
        raise ValueError('application wheel hash differs before installation')
    subprocess.run(['uv', 'pip', 'install', '--python', str(venv / 'bin/python'),
                    '--offline', '--no-deps', str(wheel)], check=True,
                   env=environment, capture_output=True, text=True)
    console = venv / 'bin/sec-edgar-ingest'
    console.write_bytes(native_console_script(venv / 'bin/python'))
    console.chmod(0o755)
    _preflight(directory / 'release.json', require_receipt=False)
    (directory / 'installation.json').write_bytes(canonical_json({
        'format_version': 'sec-native-installation-v1', 'release_id': manifest['release_id'],
        'python': str(venv / 'bin/python')}))
    return directory


def build_release(project: Path, releases: Path, *, python: Path, artifact_cache: Path, offline: bool = False) -> Path:
    project, python, artifact_cache = project.absolute(), python.absolute(), artifact_cache.absolute()
    revision = _committed_revision(project)
    environment = isolated_environment()
    environment['UV_PYTHON'] = str(python)
    environment['UV_CACHE_DIR'] = str(artifact_cache / 'uv-build')
    subprocess.run(['uv', 'lock', '--check', '--offline'], cwd=project, check=True,
                   env=environment, capture_output=True, text=True)
    lock_body = (project / 'uv.lock').read_bytes()
    interpreter = interpreter_identity(python)
    prepare_artifact_cache(project / 'uv.lock', python, artifact_cache, offline=offline)
    inventory = _cache_inventory(lock_body, interpreter, artifact_cache)
    package = tomllib.loads((project / 'packages/sec-edgar-ingest/pyproject.toml').read_text())
    if (package['project']['version'] != __version__ or __version__ != '0.2.0'
            or package['build-system'] != {'requires': [BUILD_REQUIREMENT], 'build-backend': 'uv_build'}):
        raise ValueError('application or build backend metadata differs from required current release')
    with tempfile.TemporaryDirectory(prefix='sec-native-setup-') as temporary:
        setup = Path(temporary)
        wheels = setup / 'wheels'
        build_entry = next(item for item in inventory['artifacts'] if item['role'] == 'build')
        constraints = setup / 'build-requirements.txt'
        constraints.write_text(f'uv_build=={BUILD_VERSION} --hash=sha256:{build_entry["sha256"]}\n')
        build_result = subprocess.run(['uv', 'build', '--offline', '--package', 'sec-edgar-ingest', '--wheel', '--sdist',
            '--force-pep517', '--python', str(python), '--out-dir', str(wheels), '--no-create-gitignore',
            '--no-index', '--find-links', str(artifact_cache / 'build'), '--build-constraints', str(constraints),
            '--require-build-hashes', '--preview-features', 'build-dependency-hashes'], cwd=project, check=True, env=environment, capture_output=True, text=True)
        requirements = setup / 'runtime-requirements.txt'
        export_result = subprocess.run(['uv', 'export', '--offline', '--locked', '--package', 'sec-edgar-ingest',
            '--no-dev', '--no-emit-workspace', '--format', 'requirements.txt', '--output-file', str(requirements)],
            cwd=project, check=True, env=environment, capture_output=True, text=True)
        locked = verify_requirements(lock_body, requirements.read_bytes())
        application_wheels = list(wheels.glob('*.whl'))
        if len(application_wheels) != 1:
            raise ValueError('build must produce exactly one application wheel')
        wheel = application_wheels[0]
        if _wheel_rank(wheel.name, interpreter) is None:
            raise ValueError('application wheel tags do not support target interpreter')
        _wheel_metadata(wheel, 'sec-edgar-ingest', __version__)
        dependencies = []
        (setup / 'artifacts').mkdir()
        for name, dependency in locked.items():
            artifact = _select_wheel(dependency['wheels'], interpreter)
            shutil.copyfile(artifact_cache / 'runtime' / artifact['filename'], setup / 'artifacts' / artifact['filename'])
            dependencies.append({'name': name, 'version': dependency['version'],
                                 'filename': artifact['filename'], 'sha256': artifact['sha256']})
        identity = {'application': {'name': 'sec-edgar-ingest', 'version': __version__, 'wheel_filename': wheel.name},
            'git_revision': revision, 'application_wheel_sha256': hash_file(wheel), 'package_files': wheel_payload(wheel),
            'uv_lock_sha256': hashlib.sha256(lock_body).hexdigest(), 'dependencies': dependencies, 'interpreter': interpreter}
        manifest = validate_manifest({'format_version': 'sec-native-release-v1', 'release_id': release_id(identity), 'identity': identity})
        (setup / 'release.json').write_bytes(canonical_json(manifest))
        (setup / 'uv.lock').write_bytes(lock_body)
        # Build tools/logs are setup evidence and never participate in runtime identity.
        version = subprocess.run(['uv', '--version'], check=True, capture_output=True, text=True).stdout.strip()
        if _committed_revision(project) != revision:
            raise ValueError('source changed during release build')
        return _install(manifest, releases, setup, python, {'operation': 'build', 'uv': version,
            'build_backend': {'name': 'uv_build', 'version': BUILD_VERSION, 'artifact': build_entry},
            'interpreter': interpreter, 'build_argv': build_result.args, 'build_stdout': build_result.stdout,
            'build_stderr': build_result.stderr, 'export_argv': export_result.args})


def reconstruct_release(manifest: Path, destination_releases: Path, *, python: Path) -> Path:
    """Create a fresh venv from retained artifacts, directly at its final address."""
    validated, retained = retained_release(manifest)
    python = python.absolute()
    if interpreter_identity(python) != validated['identity']['interpreter']:
        raise ValueError('reconstruction interpreter differs from release identity')
    version = subprocess.run(['uv', '--version'], check=True, capture_output=True, text=True).stdout.strip()
    return _install(validated, destination_releases, retained, python, {'operation': 'reconstruct', 'uv': version,
        'interpreter': validated['identity']['interpreter'], 'source_release_id': validated['release_id']})
