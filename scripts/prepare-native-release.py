#!/usr/bin/env python3
"""Explicit native setup entry point; never called during ingestion."""
import argparse
from pathlib import Path

from sec_edgar_ingest.release import build_release, prepare_artifact_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--releases', type=Path)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--artifact-cache', type=Path, required=True)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--prepare-cache-only', action='store_true')
    arguments = parser.parse_args()
    if arguments.prepare_cache_only:
        result = prepare_artifact_cache(arguments.project / 'uv.lock', arguments.python,
            arguments.artifact_cache, offline=arguments.offline)
    else:
        if arguments.releases is None:
            parser.error('--releases is required for a release build')
        result = build_release(arguments.project, arguments.releases, python=arguments.python,
            artifact_cache=arguments.artifact_cache, offline=arguments.offline)
    print(result)


if __name__ == '__main__':
    main()
