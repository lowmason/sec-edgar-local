#!/usr/bin/env python3
"""Verify an installed native release with a copied offline test harness."""
import argparse
import json
from pathlib import Path
import sys
import os


def main():
    # Establish cache policy before the first application import, including when
    # invoked through a stdlib-only test bootstrap.
    sys.dont_write_bytecode = True
    sys.pycache_prefix = os.devnull
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
    from network_guard import install, install_checkout_policy
    install()
    manifest = args.release / 'release.json' if args.release.is_dir() else args.release
    # The invoking setup/proof controller has selected this release via preflight.
    # Install its exact scope before importing the application to confirm identity.
    install_checkout_policy((str(manifest.parent),))
    from locked_proof import verify_native_release
    from sec_edgar_ingest.runtime import preflight_current
    report = verify_native_release(preflight_current(manifest), args.harness, args.evidence)
    print(json.dumps({'exit': report['exit'], 'release_id': report['release_id'],
                      'evidence': str(args.evidence)}))
    return report['exit']


if __name__ == '__main__':
    raise SystemExit(main())
