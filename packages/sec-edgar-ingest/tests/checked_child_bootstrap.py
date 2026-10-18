"""Isolated test stage entry: stdlib, copied guard, then application hooks."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
sys.pycache_prefix = os.devnull
ROOT = Path(__file__).absolute().parent
spec = importlib.util.spec_from_file_location('network_guard', ROOT / 'network_guard.py')
guard = importlib.util.module_from_spec(spec)
sys.modules['network_guard'] = guard
spec.loader.exec_module(guard)
guard.install()
# Only a copied test harness directory is admitted, never an application checkout.
sys.path.insert(0, str(ROOT))


def payload(path):
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict) or set(value) != {'version', 'origins', 'fault', 'clock', 'pid_log', 'sentinel', 'checkout_policy'}:
        raise ValueError('checked harness payload requires exact fields')
    if value['version'] != 'sec-checked-harness-v1':
        raise ValueError('unsupported checked harness payload')
    if not isinstance(value['origins'], list) or any(not isinstance(origin, str) for origin in value['origins']):
        raise ValueError('checked harness origins must be text')
    for key in ('pid_log', 'sentinel'):
        if value[key] is not None and (not isinstance(value[key], str) or not Path(value[key]).is_absolute()):
            raise ValueError('checked harness paths must be absolute')
    fault = value['fault']
    if fault is not None:
        if not isinstance(fault, dict) or set(fault) != {'point', 'action', 'marker', 'ack'}:
            raise ValueError('checked fault requires exact fields')
        points = {'collection.after_binding', 'publication.after_pointer',
                  'publication.after_repair', 'etl_result.after_object', 'publication.record_failure',
                  'publication.membership_failure', 'discovery.finish_failure',
                  'collection.entry_failure', 'discovery.entry_ownership_lost', 'discovery.after_begin_failure'}
        if fault['point'] not in points or fault['action'] not in ('crash', 'raise'):
            raise ValueError('unsupported named checked fault')
        for key in ('marker', 'ack'):
            if not isinstance(fault[key], str) or not Path(fault[key]).is_absolute():
                raise ValueError('fault synchronization paths must be absolute')
    return value


def boundary(value, name):
    fault = value['fault']
    if fault is None or fault['point'] != name:
        return
    marker = Path(fault['marker'])
    if marker.exists():
        return
    with marker.open('x') as stream:
        json.dump({'point': name, 'pid': os.getpid()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    until = time.monotonic() + 15
    while not Path(fault['ack']).is_file():
        if time.monotonic() >= until:
            raise RuntimeError('named checked fault acknowledgment timed out')
        time.sleep(0.01)
    if fault['action'] == 'crash':
        os._exit(91)
    if name == 'discovery.entry_ownership_lost':
        from sec_edgar_ingest.storage.contracts import OwnershipLost
        raise OwnershipLost('acknowledged discovery ownership failure')
    if name.startswith(('discovery.', 'collection.entry')):
        raise RuntimeError('acknowledged retained command failure')
    raise OSError('acknowledged ordinary ancillary publication failure')


def run(value):
    early_guard = guard.checkout_evidence() if guard.checkout_policy() is not None else None
    if value['sentinel']:
        sentinel_spec = importlib.util.spec_from_file_location('network_import_sentinel', value['sentinel'])
        sentinel_spec.loader.exec_module(importlib.util.module_from_spec(sentinel_spec))
    import sec_edgar_ingest.cli as cli
    from sec_edgar_ingest.etl.state import EtlState
    from sec_edgar_ingest.workflows.checked import Dispatcher
    from support_process import CheckedRunner
    from unittest.mock import patch
    actual_publish, actual_result = cli.run_publish, cli.write_etl_result
    actual_collect, actual_discover = cli.collect, cli.discover
    actual_record = EtlState.record_publication
    actual_membership = EtlState._record_membership
    from sec_edgar_ingest.state import AcquisitionState
    actual_finish_discovery = AcquisitionState.finish_discovery
    actual_begin_discovery = AcquisitionState.begin_discovery
    def dispatch(*args, **kwargs):
        kwargs['child_runner'] = CheckedRunner(fault=value['fault'],
            pid_log=value['pid_log'], sentinel=value['sentinel'], clock=value['clock'])
        return Dispatcher(*args, **kwargs)
    def publish(*args, **kwargs):
        kwargs['observer'] = lambda name: boundary(value, name)
        return actual_publish(*args, **kwargs)
    def result(*args, **kwargs):
        kwargs['observer'] = lambda name: boundary(value, name)
        return actual_result(*args, **kwargs)
    def record(state, manifest):
        boundary(value, 'publication.record_failure')
        return actual_record(state, manifest)
    def collect(*args, **kwargs):
        boundary(value, 'collection.entry_failure')
        return actual_collect(*args, **kwargs)
    def discover(*args, **kwargs):
        boundary(value, 'discovery.entry_ownership_lost')
        return actual_discover(*args, **kwargs)
    def begin_discovery(state, *args, **kwargs):
        result = actual_begin_discovery(state, *args, **kwargs)
        boundary(value, 'discovery.after_begin_failure')
        return result
    def membership(state, *args, **kwargs):
        boundary(value, 'publication.membership_failure')
        return actual_membership(state, *args, **kwargs)
    def finish_discovery(state, *args, **kwargs):
        boundary(value, 'discovery.finish_failure')
        return actual_finish_discovery(state, *args, **kwargs)
    if value['pid_log']:
        with Path(value['pid_log']).open('a') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'python': sys.executable,
                'origin': cli.__file__, 'argv': sys.argv[2:], 'checkout_guard': early_guard}) + '\n')
    if value['clock'] is not None:
        from datetime import datetime
        instant = datetime.fromisoformat(value['clock'])
        clock_patch = contextlib.ExitStack()
        clock_patch.enter_context(patch.object(cli.Clock, 'now', return_value=instant))
        checked_clock = clock_patch.enter_context(patch('sec_edgar_ingest.workflows.checked.datetime', wraps=datetime))
        checked_clock.now.return_value = instant
    else:
        clock_patch = contextlib.nullcontext()
    with clock_patch, patch.object(cli, 'WorkflowDispatcher', dispatch), \
         patch.object(cli, 'run_publish', publish), patch.object(cli, 'write_etl_result', result), \
         patch.object(cli._NoFaults, 'hit', lambda self, name: boundary(value, 'collection.' + name)), \
         patch.object(EtlState, 'record_publication', record), \
         patch.object(EtlState, '_record_membership', membership), \
         patch.object(AcquisitionState, 'finish_discovery', finish_discovery), \
         patch.object(AcquisitionState, 'begin_discovery', begin_discovery), \
         patch.object(cli, 'collect', collect), patch.object(cli, 'discover', discover):
        return cli.main(sys.argv[2:])


if __name__ in ('__main__', '__mp_main__'):
    _payload = payload(sys.argv[1])
    guard.restore_checkout_policy(_payload['checkout_policy'])
    if guard.checkout_policy() != _payload['checkout_policy']:
        raise ValueError('checked payload differs from copied checkout policy')
    _origins = contextlib.ExitStack()
    for _origin in _payload['origins']:
        _origins.enter_context(guard.selected_origin(_origin))
if __name__ == '__main__':
    try:
        raise SystemExit(run(_payload))
    finally:
        _origins.close()
