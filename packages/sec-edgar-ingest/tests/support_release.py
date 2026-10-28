"""Real, committed, offline proof environments shared by native integration tests."""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from sec_edgar_ingest.release import build_release, prepare_artifact_cache
from sec_edgar_ingest.runtime import VerifiedRelease, preflight
from locked_proof import assert_release_inventory, proof_catalog, proof_harness

_PROOFS: dict[tuple[str, str, str], tuple[VerifiedRelease, VerifiedRelease]] = {}
_TEMPORARIES: list[tempfile.TemporaryDirectory] = []


def _snapshot_files(project: Path) -> list[Path]:
    result = subprocess.run(['git', '-C', str(project), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                            check=True, capture_output=True)
    paths = []
    for name in result.stdout.decode().split('\0'):
        if not name:
            continue
        relative = Path(name)
        if relative.parts[0] in {'.sdd', 'data', 'fixture-data', 'logs', 'releases', 'dist', 'build'}:
            continue
        if relative.parts[:2] == ('specs', 'evidence') or '__pycache__' in relative.parts:
            continue
        path = project / relative
        if path.is_file():
            paths.append(relative)
    return sorted(set(paths))


def proof_releases(project: Path, cache: Path) -> tuple[VerifiedRelease, VerifiedRelease]:
    """Export the implementation snapshot into its own committed A/B repository.

    The source checkout may be dirty. Only its independent committed snapshots
    are built, so this factory cannot admit an uncommitted production release.
    """
    project = project.absolute()
    override = os.environ.get('SEC_LOCAL_PROOF_CACHE')
    cache = Path(override) if override else cache
    if not cache.is_absolute():
        raise ValueError('proof cache path must be absolute')
    catalog = proof_catalog()
    if catalog:
        from workflow_proof import harness_files
        harness_files(proof_harness(project / 'packages/sec-edgar-ingest/tests'))
        proofs = tuple(preflight(Path(catalog[name])) for name in ('a_manifest', 'b_manifest'))
        if proofs[0].release_id == proofs[1].release_id:
            raise ValueError('proof catalog must identify distinct real releases')
        for proof in proofs:
            assert_release_inventory(proof)
        return proofs
    prepare_artifact_cache(project / 'uv.lock', Path(sys.executable), cache, offline=True)
    paths = _snapshot_files(project)
    snapshot = hashlib.sha256()
    for relative in paths:
        snapshot.update(relative.as_posix().encode() + b'\0')
        snapshot.update((project / relative).read_bytes())
    key = str(project), str(cache), snapshot.hexdigest()
    if key in _PROOFS:
        return _PROOFS[key]
    temporary = tempfile.TemporaryDirectory(prefix='sec-native-proof-')
    _TEMPORARIES.append(temporary)
    root = Path(temporary.name)
    source = root / 'source'
    source.mkdir()
    for relative in paths:
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / relative, destination)
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    def commit(message):
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Native release proof',
                        '-c', 'user.email=proof@example.invalid', 'commit', '-qm', message], check=True)
    commit('Independent implementation snapshot A')
    releases = root / 'releases'
    a = preflight(build_release(source, releases, python=Path(sys.executable), artifact_cache=cache, offline=True) / 'release.json')
    (source / 'packages/sec-edgar-ingest/src/sec_edgar_ingest/proof_resource.txt').write_text('Harmless included resource for committed release B.\n')
    commit('Independent included-resource snapshot B')
    b = preflight(build_release(source, releases, python=Path(sys.executable), artifact_cache=cache, offline=True) / 'release.json')
    for proof in (a, b):
        assert_release_inventory(proof)
    _PROOFS[key] = a, b
    return a, b


ORIGIN_REVISION = '3ca50c78558bbf072a4eb75412af7d58a9e0f61b'  # source revision of release fc68adef…
D5_REVISION = 'd68787fe8602e9d81a26d2012feec9bfad5c52df'  # source revision of the D5 release aa8de1ac…
_ORIGINS: dict[tuple[str, str, str], VerifiedRelease] = {}


def origin_release(project: Path, cache: Path, revision: str = ORIGIN_REVISION) -> VerifiedRelease:
    """Build one source revision (default: that of fc68adef…) into its own committed repository and install it.

    Release identity covers the Git revision, so this release ID differs from fc68adef…; its
    application payload is that revision's. The checkout's later code never enters it.
    """
    project = project.absolute()
    override = os.environ.get('SEC_LOCAL_PROOF_CACHE')
    cache = Path(override) if override else cache
    if not cache.is_absolute():
        raise ValueError('proof cache path must be absolute')
    key = str(project), str(cache), revision
    if key in _ORIGINS:
        return _ORIGINS[key]
    temporary = tempfile.TemporaryDirectory(prefix='sec-native-origin-')
    _TEMPORARIES.append(temporary)
    root = Path(temporary.name)
    source = root / 'source'
    source.mkdir()
    archive = subprocess.run(['git', '-C', str(project), 'archive', '--format=tar', revision],
                             check=True, capture_output=True).stdout
    subprocess.run(['tar', '-x', '-C', str(source)], input=archive, check=True)
    # The origin revision's own lock, not the checkout's, decides which artifacts it needs.
    prepare_artifact_cache(source / 'uv.lock', Path(sys.executable), cache, offline=True)
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Native release proof',
                    '-c', 'user.email=proof@example.invalid', 'commit', '-qm',
                    'Origin source revision ' + revision], check=True)
    release = preflight(build_release(source, root / 'releases', python=Path(sys.executable),
                                      artifact_cache=cache, offline=True) / 'release.json')
    assert_release_inventory(release)
    _ORIGINS[key] = release
    return release


def _cleanup():
    for temporary in reversed(_TEMPORARIES):
        temporary.cleanup()


atexit.register(_cleanup)
