#!/usr/bin/env python3
"""Select an explicit native release using only the standard library.

This selector never imports application code; the installed launcher verifies the
full configured release and current process before creating invocation evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGURATION_EXIT = 2
RELEASE_DIRECTORY = re.compile(r'sha256=[0-9a-f]{64}\Z')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('nonfinite JSON constant: ' + value)


def _release_python(config_path: Path) -> Path:
    value = json.loads(config_path.read_text(encoding='utf-8'),
                       object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(value, dict) or value.get('config_version') != 'sec-local-config-v1':
        raise ValueError('unsupported configuration document')
    runtime = value.get('runtime')
    if not isinstance(runtime, dict) or set(runtime) != {'kind', 'release_manifest'} or runtime['kind'] != 'native':
        raise ValueError('launcher requires an explicit installed native release')
    raw = runtime['release_manifest']
    if not isinstance(raw, str) or not raw or any(ord(character) < 32 for character in raw):
        raise ValueError('release_manifest must be an explicit filesystem path')
    manifest = Path(raw).expanduser()
    if not manifest.is_absolute():
        manifest = config_path.parent / manifest
    manifest = manifest.resolve()
    directory = manifest.parent
    if manifest.name != 'release.json' or directory.parent.name != 'releases' or RELEASE_DIRECTORY.fullmatch(directory.name) is None:
        raise ValueError('release_manifest must name releases/sha256=<release-id>/release.json')
    python = directory / 'venv/bin/python'
    if not manifest.is_file() or not python.is_file():
        raise ValueError('native release is missing; perform explicit release setup before running')
    return python


def main(argv=None) -> int:
    original = list(sys.argv[1:] if argv is None else argv)
    try:
        if any(argument == '--project-root' or argument.startswith('--project-root=') for argument in original):
            raise ValueError('--project-root is an internal bootstrap argument')
        parser = argparse.ArgumentParser(prog='sec-edgar-local', allow_abbrev=False)
        parser.add_argument('command', choices=('backfill', 'daily', 'reconcile'))
        parser.add_argument('--config', type=Path, default=PROJECT_ROOT / 'conf/sec-edgar-local.json')
        parser.add_argument('--timeout-seconds', type=float, default=3300)
        try:
            args = parser.parse_args(original)
        except SystemExit as error:
            return int(error.code)
        config_path = args.config.expanduser().resolve()
        python = _release_python(config_path)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('PYTHON', 'UV_')) and key not in {'VIRTUAL_ENV', 'CONDA_PREFIX'}}
        # Match runtime.native_python_argv without importing the application from this bootstrap.
        native_argv = [str(python), '-I', '-B', '-X', 'pycache_prefix=' + os.devnull]
        os.execve(str(python), [*native_argv, '-m', 'sec_edgar_ingest.local_cli',
                               '--project-root', str(PROJECT_ROOT), *original], environment)
    except (OSError, ValueError, TypeError) as error:
        sys.stderr.write(json.dumps({'outcome': 'configuration', 'error': str(error)},
                                    sort_keys=True, separators=(',', ':')) + '\n')
        return CONFIGURATION_EXIT
    return 0  # os.execve only returns in tests.


if __name__ == '__main__':
    raise SystemExit(main())
