"""Explicit local failure boundaries retain authority and refuse unsafe progress."""
from network_guard import install
install()

import contextlib
import errno
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import Faults, fixture_context, fixture_settings, store_bundle
from support_approval import GateFixture, row
from support_checked import workflow_fixture
from support_fs import tree_snapshot
from support_process import CheckedRunner
from sec_edgar_ingest.etl.reader import read_quarter, capture_quarter, validated_manifest
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage.contracts import Conflict, REGISTRY_PATH


class BoundaryFailures(unittest.TestCase):
    def test_object_disk_full_before_link_keeps_previous_bytes_and_no_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, objects, leases = store_bundle(root)
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            objects.put_once('raw/sec/retained', b'first evidence')
            before = tree_snapshot(root)
            with patch('sec_edgar_ingest.storage.local.os.link', side_effect=OSError(errno.ENOSPC, 'disk full')):
                with self.assertRaises(OSError) as caught:
                    objects.put_once('raw/sec/new', b'new evidence')
            self.assertEqual(caught.exception.errno, errno.ENOSPC)
            self.assertEqual(objects.read('raw/sec/retained'), b'first evidence')
            with self.assertRaises(FileNotFoundError):
                objects.read('raw/sec/new')
            # Empty parent directories are permitted; no failed object or scratch becomes authority.
            self.assertEqual({k:v for k,v in tree_snapshot(root).items() if v != 'dir'},
                             {k:v for k,v in before.items() if v != 'dir'})
            objects.put_once('raw/sec/new', b'new evidence')
            self.assertEqual(objects.read('raw/sec/new'), b'new evidence')

    def test_archived_config_disk_full_prevents_launch_and_preserves_ambiguous_attempt(self):
        from sec_edgar_ingest.workflows.checked import Dispatcher
        with tempfile.TemporaryDirectory() as directory:
            settings, context, pack, store, objects = workflow_fixture(Path(directory))
            self.addCleanup(store.close)
            launches = []
            def runner(*args, **kwargs):
                launches.append(True)
                raise AssertionError('disk full must prevent launch')
            dispatcher = Dispatcher(context, settings, pack, Path(directory), store, objects, child_runner=runner)
            put = objects.put_once
            def fail_config(path, body):
                if path.endswith('/config.json'):
                    raise OSError(errno.ENOSPC, 'config archive full')
                return put(path, body)
            with patch.object(objects, 'put_once', side_effect=fail_config):
                with self.assertRaises(OSError):
                    dispatcher.execute('discover', 'disk-full', settings,
                        ('--mode', 'quarterly', '--discovery-id', 'full'))
            self.assertEqual(launches, [])
            attempts = tuple(store.scan('WorkflowChildExecution', {}))
            self.assertEqual(len(attempts), 1)
            self.assertIsNone(attempts[0].value['exit_ref'])
            before = tree_snapshot(Path(directory))
            with self.assertRaises((Conflict, FileNotFoundError)):
                dispatcher.execute('discover', 'disk-full', settings,
                    ('--mode', 'quarterly', '--discovery-id', 'full'))
            self.assertEqual(tree_snapshot(Path(directory)), before)
            self.assertEqual(tuple(store.scan('Attempt', {})), ())

    def test_event_sink_disk_full_never_changes_authoritative_durable_result(self):
        from sec_edgar_ingest.results import log_event, read_result, write_result
        from sec_edgar_ingest.state import AcquisitionState
        from test_cli import ResultTests
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, objects, leases = store_bundle(root)
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            result = ResultTests().result(root=root)
            state = AcquisitionState(store)
            state.begin_attempt(result.context)
            reference = write_result(result, objects, state)
            before = objects.read(reference)
            with patch('sec_edgar_ingest.results.sys.stderr.write', side_effect=OSError(errno.ENOSPC, 'event sink full')):
                with self.assertRaises(OSError):
                    log_event(result.context, 'command_finished', {'outcome': result.outcome, 'result_ref': reference})
            self.assertEqual(objects.read(reference), before)
            self.assertEqual(read_result(reference, objects), result)
            self.assertEqual(write_result(result, objects, state), reference)

    def test_foreign_binding_and_database_contract_refuse_without_mutation(self):
        from sec_edgar_ingest.storage import open_stores
        for damage in ('binding', 'version', 'shape', 'corrupt'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                settings = fixture_settings(root=root)
                opened = open_stores(settings)
                for resource in reversed(opened):
                    if hasattr(resource, 'close'): resource.close()
                if damage == 'binding':
                    (root / 'objects' / REGISTRY_PATH).write_bytes(b'{"format_version":"old-store-v1"}')
                elif damage == 'corrupt':
                    (root / 'state.sqlite3').write_bytes(b'foreign database bytes')
                else:
                    database = sqlite3.connect(root / 'state.sqlite3')
                    self.addCleanup(database.close)
                    if damage == 'version':
                        database.execute('PRAGMA user_version=999')
                    else:
                        database.execute('ALTER TABLE records ADD COLUMN unexpected TEXT')
                    database.commit()
                before = tree_snapshot(root)
                if damage != 'corrupt':
                    with contextlib.closing(sqlite3.connect(root / 'state.sqlite3')) as database:
                        contents = tuple(database.iterdump())
                for access in ('operator', 'worker'):
                    with self.assertRaises((Conflict, ValueError)):
                        open_stores(settings, access=access)
                    self.assertEqual(tree_snapshot(root), before)
                if damage != 'corrupt':
                    with contextlib.closing(sqlite3.connect(root / 'state.sqlite3')) as database:
                        self.assertEqual(tuple(database.iterdump()), contents)


class CorruptionFailures(GateFixture):
    def test_missing_approval_refuses_before_current_rows_are_exposed(self):
        from sec_edgar_ingest.etl.contracts import GenerationCapture
        _, _, candidate = self.gated()
        manifest = candidate.manifest
        capture = GenerationCapture(manifest.quarter, manifest.generation_id, candidate.manifest_ref,
                                    candidate.manifest_sha256, candidate.manifest_bytes)
        with self.assertRaisesRegex(ValueError, 'awaiting-approval generation cannot be current without its exact approval') as caught:
            validated_manifest(capture, self.objects)
        self.assertIsInstance(caught.exception.__cause__, FileNotFoundError)

    def test_rollback_index_failure_retains_immutable_record_and_original_pointer(self):
        from sec_edgar_ingest.etl.rollback import rollback
        self.assertEqual(self.publish(self.observation(rows=row()+row(number=2))).outcome, 'published')
        older = self.capture()
        self.assertEqual(self.publish(self.observation(rows=row('New')+row(number=2), seconds=1)).outcome, 'published')
        newer = self.capture()
        pointer = self.state.pointer('2026Q4')
        insert = self.store.insert
        def fail_index(kind, *args, **kwargs):
            if kind == 'QuarterRollback':
                raise OSError(errno.ENOSPC, 'rollback index full')
            return insert(kind, *args, **kwargs)
        with patch.object(self.store, 'insert', side_effect=fail_index), self.assertRaises(OSError):
            rollback('2026Q4', newer.generation_id, older.generation_id,
                     'Local operator', 'withdraw correction', self.objects, self.state)
        retained = list((self.objects.directory / 'approvals').rglob('rollback.json'))
        self.assertEqual(len(retained), 1)
        body = retained[0].read_bytes()
        self.assertEqual(self.state.pointer('2026Q4'), pointer)
        result = rollback('2026Q4', newer.generation_id, older.generation_id,
                          'Local operator', 'withdraw correction', self.objects, self.state)
        self.assertEqual(result.outcome, 'success')
        self.assertEqual(retained[0].read_bytes(), body)
        self.assertEqual(self.capture().generation_id, older.generation_id)


class HarnessIsolationTests(unittest.TestCase):
    def test_range_or_parser_settings_retain_actual_temporary_store_and_log_roots(self):
        from support_workflows import CommandHarness, simple_pack, set_harness_settings
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = CommandHarness(root, simple_pack(root / 'pack'))
            self.addCleanup(harness.close)
            expected = (harness.settings.storage.root, harness.settings.logging.root)
            set_harness_settings(harness, fixture_settings(
                backfill={'start_quarter': '2025Q2', 'end_quarter': '2025Q2'}))
            self.assertEqual((harness.settings.storage.root, harness.settings.logging.root), expected)
            self.assertEqual(json.loads(harness.config.read_bytes())['storage']['root'], expected[0])



class ProductionWindowMeasurements(unittest.TestCase):
    def test_default_three_per_second_child_start_progress_and_safe_expiry(self):
        import multiprocessing
        import os
        import time
        from support import LoopbackServer, loopback_sender, real_context, real_permit
        from sec_edgar_ingest.coordination import Clock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = fixture_settings(root=root / 'data')
            self.assertEqual(settings.sec.requests_per_second, 3)
            self.assertIsNone(settings.fixture)
            clock = Clock()
            samples = []
            for number in range(3):
                server = LoopbackServer(b'production-window measurement')
                try:
                    spool = root / str(number)
                    sender = loopback_sender(settings, clock, server.origin, spool=spool)
                    permit = real_permit(clock, 90, start_seconds=1/3)
                    receipt = sender.send(server.url, real_context(clock, settings), permit,
                        cancellation=multiprocessing.get_context('spawn').Event())
                    events = [json.loads(line) for line in (spool / 'transport.jsonl').read_text().splitlines()]
                    supervisor = next(event['monotonic'] for event in events if event['event']=='supervisor-start')
                    start = next((event['monotonic'] for event in events if event['event']=='socket-start'), None)
                    outcome = 'success' if receipt.complete else receipt.error.code
                    if outcome == 'permit_expired':
                        self.assertIsNone(start)
                        self.assertEqual(server.requests, [])
                    else:
                        self.assertEqual(outcome, 'success', receipt.to_mapping())
                        self.assertLessEqual(start, permit.start_before_mono)
                        self.assertEqual(receipt.temporary_path.read_bytes(), server.body)
                    samples.append({'outcome': outcome, 'dispatch_start_seconds': None if start is None else start-supervisor,
                        'receipt': receipt.to_mapping(), 'events': events, 'server_events': server.events})
                finally:
                    server.close()
            report = {'requests_per_second': 3, 'start_window_seconds': 1/3,
                'fixture_timing_allowances': False, 'samples': samples,
                'successes': sum(sample['outcome']=='success' for sample in samples),
                'safe_permit_expired': sum(sample['outcome']=='permit_expired' for sample in samples),
                'progress_failures': 0, 'invariant_violations': 0}
            destination = os.environ.get('SEC_EDGAR_TASK10_LATENCY_EVIDENCE')
            if destination:
                Path(destination).write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
            self.assertGreater(report['successes'], 0, 'bounded child progress failed at all production dispatch windows')
