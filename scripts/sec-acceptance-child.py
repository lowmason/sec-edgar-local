#!/usr/bin/env python3
"""Installed native acceptance entry point; no checkout application import path."""
import os
import sys

# Fixed public child argv uses -I; establish equivalent native cache policy before
# loading either the stdlib harness or the first installed application module.
sys.dont_write_bytecode = True
sys.pycache_prefix = os.devnull

import argparse
from pathlib import Path
import runpy
import signal


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--selection', required=True, type=Path)
    parser.add_argument('--call', required=True, type=Path)
    args = parser.parse_args()
    api = runpy.run_path(str(Path(__file__).resolve().with_name('accept-sec-native.py')))
    budget = None
    try:
        selection = api['require_prepared'](args.selection)
        api['verify_runtime'](selection)
        call = api['validate_call'](api['read_json'](args.call), selection, args.selection)
        if args.call.read_bytes() != api['canonical'](call):
            raise ValueError('call bytes must be canonical and immutable')
        remaining = api['remaining_seconds'](selection)
        if remaining <= 0:
            raise api['AcceptanceLimit']('original acceptance UTC window expired before child import')
        from sec_edgar_ingest import cli, collection, download, validation
        from sec_edgar_ingest.etl import transform
        budget = api['Budget'](args.selection)
        api['install_wrappers'](budget, cli, collection, transform, validation.validate_envelope, download)
        def expired(signum, frame):
            budget.limit_failed = True
            raise api['AcceptanceLimit']('acceptance original UTC/monotonic watchdog expired')
        previous = signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, remaining)
        try:
            result = cli.main(call['argv'])
            return api['LIMIT_EXIT'] if budget.limit_failed else result
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
    except api['AcceptanceLimit'] as error:
        print(api['canonical']({'outcome': 'acceptance_limit', 'status': 'incomplete', 'error': str(error)}).decode(), file=sys.stderr)
        return api['LIMIT_EXIT']
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(api['canonical']({'outcome': 'configuration', 'error': str(error)}).decode(), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
