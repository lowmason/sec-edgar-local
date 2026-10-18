#!/usr/bin/env python3
"""Verify an installed native release with a copied offline test harness."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True, type=Path)
    parser.add_argument('--harness', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    if not all(path.is_absolute() for path in (args.release, args.harness, args.evidence)):
        parser.error('release, harness, and evidence must be absolute paths')
    # The harness admits only test support. Application imports use the selected
    # installed interpreter; the verifier never adds an application source path.
    sys.path.insert(0, str(args.harness))
    from network_guard import install
    install()
    from locked_proof import verify_native_release
    from sec_edgar_ingest.runtime import preflight
    manifest = args.release / 'release.json' if args.release.is_dir() else args.release
    report = verify_native_release(preflight(manifest), args.harness, args.evidence)
    print(json.dumps({'exit': report['exit'], 'release_id': report['release_id'],
                      'evidence': str(args.evidence)}))
    return report['exit']


if __name__ == '__main__':
    raise SystemExit(main())
