"""CLI/result contracts use actual parsing, separate processes and durable objects."""
import contextlib
import hashlib
import importlib
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from support import cli_harness, fixture_context, store_bundle
from support_azure import WORKER_CLIENT_ID
from sec_edgar_ingest.models import CommandResult, canonical_json
from sec_edgar_ingest.storage.identity import WORKER_CLIENT_ID_ENV


class ResultTests(unittest.TestCase):
    def results(self):
        try:
            return importlib.import_module('sec_edgar_ingest.results')
        except ModuleNotFoundError:
            self.fail('Task 8 must implement durable results')

    def result(self):
        ctx = fixture_context()
        return CommandResult(ctx, 'success', None, None, 0, 0, 0, 0, 0, 0, (), ctx.started_at, ctx.started_at)

    def test_canonical_result_codec_is_strict_and_roundtrips(self):
        result = self.result()
        self.assertTrue(hasattr(result, 'to_json'), 'CommandResult needs canonical JSON codec')
        body = result.to_json()
        self.assertEqual(body, canonical_json(result.to_mapping()))
        self.assertEqual(CommandResult.from_json(body), result)
        for invalid in (body.replace(b'"success"', b'"success","outcome":"success"'), b'[]', b'{"outcome":NaN}'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                CommandResult.from_json(invalid)

    def test_result_precedes_attempt_and_conflicting_bytes_refuse(self):
        results = self.results()
        from sec_edgar_ingest.state import AcquisitionState, attempt_key
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as temporary:
            store, objects, leases = store_bundle(Path(temporary))
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            state = AcquisitionState(store)
            result = self.result()
            state.begin_attempt(result.context)
            finish = state.finish_attempt
            def observed_finish(value):
                path = f'runs/sec/{value.context.run_id}/collect/{value.context.attempt_id}/result.json'
                self.assertEqual(objects.read(path), value.to_json())
                finish(value)
            state.finish_attempt = observed_finish
            path = results.write_result(result, objects, state)
            self.assertEqual(results.read_result(path, objects), result)
            self.assertEqual(results.write_result(result, objects, state), path)
            with self.assertRaises(Conflict):
                results.write_result(replace(result, downloaded=1), objects, state)
            self.assertEqual(store.get('Attempt', attempt_key(result.context)).value['outcome'], 'success')

    def test_result_reader_refuses_wrong_path_correlation(self):
        results = self.results()
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as temporary:
            store, objects, leases = store_bundle(Path(temporary))
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            objects.put_once('runs/sec/wrong/collect/attempt/result.json', self.result().to_json())
            with self.assertRaises((Conflict, ValueError)):
                results.read_result('runs/sec/wrong/collect/attempt/result.json', objects)

    def test_exact_exit_mapping_and_structured_event(self):
        results = self.results()
        expected = {'success': 0, 'no_new_sources': 0, 'configuration': 2,
                    'discovery_failed': 3, 'incomplete': 3, 'pending': 4, 'retry_exhausted': 5,
                    'deferred': 5, 'throttled': 5, 'access_blocked': 6, 'quarantined': 7,
                    'invalid_source': 7, 'ownership_lost': 8, 'state_conflict': 9, 'internal_error': 9}
        self.assertEqual({name: results.exit_code(name) for name in expected}, expected)
        with self.assertRaises(KeyError):
            results.exit_code('transform_complete')
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            results.log_event(self.result().context, 'finished', {'pending': 1})
        event = json.loads(output.getvalue())
        self.assertEqual(event['event'], 'finished')
        self.assertEqual(event['context'], self.result().context.to_mapping())
        self.assertEqual(event['fields'], {'pending': 1})


class CliTests(unittest.TestCase):
    def harness(self, fixture='valid-quarter-and-daily', **kwargs):
        h = cli_harness(fixture, **kwargs)
        self.addCleanup(h.close)
        return h

    def test_failed_discovery_is_not_empty_success(self):
        h = self.harness('failed-earlier-quarter')
        completed = h.discover()
        self.assertEqual(completed.returncode, 3, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result['outcome'], 'discovery_failed')
        self.assertIsNone(result['snapshot_workset_ref'])
        self.assertTrue(h.read_durable_result(result['result_ref']).gaps)
        self.assertIsNotNone(result['source_workset_ref'])

    def test_missing_identity_creates_no_external_clients(self):
        h = self.harness(missing_user_agent=True)
        completed = h.discover()
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(h.external_client_constructions, 0)
        self.assertFalse(h.state_root.exists())
        self.assertEqual(json.loads(completed.stderr)['outcome'], 'configuration')

    def test_unsafe_identifiers_refuse_before_backend_construction(self):
        for name in ('--run-id', '--execution-id', '--attempt-id', '--discovery-id'):
            for invalid in ('', 'a/b', '../other', '/absolute', 'a\\b', 'a:b', 'a%20b', 'a?b', 'a#b'):
                with self.subTest(name=name, invalid=invalid):
                    h = self.harness()
                    args = ['--mode', 'quarterly', '--discovery-id', 'discovery', '--execution-id', 'execution', '--attempt-id', 'attempt', name, invalid]
                    done = h.invoke('discover', args)
                    self.assertEqual(done.returncode, 2)
                    self.assertEqual(h.external_client_constructions, 0)

    def test_fixture_pack_required_and_overrides_rejected_in_azure_before_clients(self):
        h = self.harness()
        common = list(h.common)
        position = common.index('--fixture-pack')
        del common[position:position + 2]
        self.assertEqual(h.invoke('discover', ['--mode', 'quarterly', '--discovery-id', 'd', '--execution-id', 'e', '--attempt-id', 'a'], common=common).returncode, 2)
        self.assertEqual(h.external_client_constructions, 0)

    def test_valid_empty_and_help_offer_all_four_commands(self):
        h = self.harness('valid-empty')
        done = h.discover()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['outcome'], 'no_new_sources')
        from sec_edgar_ingest.cli import main
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([]), 0)
        self.assertIn('discover', output.getvalue())
        self.assertIn('collect', output.getvalue())
        self.assertIn('transform', output.getvalue())
        self.assertIn('publish', output.getvalue())

    def test_collection_outcomes_are_named_and_non_success(self):
        expected = {'pending': (4, 'pending'), 'retry-exhausted': (5, 'retry_exhausted'),
                    'access-blocked': (6, 'access_blocked'), 'quarantined': (7, 'quarantined'),
                    'ownership-lost': (8, 'ownership_lost'), 'deferred': (5, 'deferred')}
        for fixture, (code, outcome) in expected.items():
            with self.subTest(fixture=fixture):
                h = self.harness(fixture)
                discovered = h.discover()
                self.assertEqual(discovered.returncode, 0, discovered.stderr)
                done = h.collect(json.loads(discovered.stdout)['source_workset_ref'])
                self.assertEqual(done.returncode, code, done.stderr)
                record = h.read_durable_result(json.loads(done.stdout)['result_ref'])
                self.assertEqual(record.outcome, outcome)
                self.assertTrue(record.gaps)
                self.assertIsNone(record.snapshot_workset_ref)

    def test_success_result_current_context_hash_and_replay_no_requests(self):
        h = self.harness()
        discovered = json.loads(h.discover().stdout)
        done = h.collect(discovered['source_workset_ref'])
        self.assertEqual(done.returncode, 0, done.stderr)
        value = json.loads(done.stdout)
        record = h.read_durable_result(value['result_ref'])
        self.assertEqual((record.context.run_id, record.context.execution_id, record.context.command, record.context.attempt_id),
                         ('cli-run', 'cli-collect', 'collect', 'collect-1'))
        from sec_edgar_ingest.config import load_config
        self.assertEqual(record.context.config_sha256, load_config(h.config_path).config_sha256)
        replay = h.collect(discovered['source_workset_ref'])
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(json.loads(replay.stdout), value)
        self.assertEqual(h.read_durable_result(value['result_ref']), record)
        different = h.collect(discovered['source_workset_ref'], execution='wrong-execution')
        self.assertEqual(different.returncode, 9, different.stderr)
        self.assertEqual(h.read_durable_result(value['result_ref']), record)

    def test_unknown_and_missing_workset_refuse_without_false_completion(self):
        for ref in ('worksets/sec/source/sha256=' + 'a' * 64 + '/workset.json', 'unknown.json', '../escape'):
            with self.subTest(ref=ref):
                h = self.harness()
                done = h.collect(ref)
                self.assertIn(done.returncode, (2, 9), done.stderr)
                self.assertNotEqual(json.loads(done.stdout or done.stderr).get('outcome'), 'success')

    def test_completed_attempt_cannot_change_config_deadline_mode_refresh_or_workset(self):
        for variation in ('config', 'deadline', 'mode', 'refresh', 'discovery'):
            with self.subTest(variation=variation):
                h = self.harness()
                first = h.discover()
                self.assertEqual(first.returncode, 0, first.stderr)
                common = list(h.common)
                args = ['--mode', 'quarterly', '--discovery-id', 'cli-discovery', '--execution-id', 'cli-discover', '--attempt-id', 'discover-1']
                if variation == 'config':
                    cfg = json.loads(h.config_path.read_text())
                    cfg['etl']['parser_version'] = 'fixture-version-two'
                    h.config_path.write_text(json.dumps(cfg))
                elif variation == 'deadline':
                    common[common.index('--deadline') + 1] = '2098-01-01T00:00:00Z'
                elif variation == 'mode':
                    args[args.index('--mode') + 1] = 'daily'
                elif variation == 'refresh':
                    args.append('--refresh')
                else:
                    args[args.index('--discovery-id') + 1] = 'different'
                done = h.invoke('discover', args, common=common)
                self.assertIn(done.returncode, (2, 9), done.stderr)
                self.assertNotEqual(done.stdout, first.stdout)


class FixturePackTests(unittest.TestCase):
    def pack_class(self):
        import sec_edgar_ingest.download as download
        self.assertTrue(hasattr(download, 'FixturePack'), 'download must implement an explicit validated fixture pack')
        return download.FixturePack

    def test_pack_validates_hash_provenance_url_path_and_never_falls_back(self):
        from support import ACQUISITION_PACK
        cls = self.pack_class()
        self.assertIsNotNone(cls.load(ACQUISITION_PACK))
        original = json.loads(ACQUISITION_PACK.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            import shutil
            root = Path(temporary)
            shutil.copytree(ACQUISITION_PACK.parent / 'bodies', root / 'bodies')
            for variation in ('provenance', 'hash', 'path', 'url', 'status', 'fault'):
                value = json.loads(json.dumps(original))
                url, specs = next(iter(value['responses'].items()))
                if variation == 'provenance': value['provenance'] = 'live'
                elif variation == 'hash': specs[0]['body_sha256'] = '0' * 64
                elif variation == 'path': specs[0]['body_path'] = '../escape'
                elif variation == 'url': value['responses']['https://example.com/index.json'] = value['responses'].pop(url)
                elif variation == 'status': specs[0]['status'] = True
                else: specs[0]['fault'] = {'untyped': 'fault'}
                path = root / 'manifest.json'
                path.write_text(json.dumps(value))
                with self.subTest(variation=variation), self.assertRaises(ValueError):
                    cls.load(path)


class ResultProcessTests(unittest.TestCase):
    def test_actual_result_and_attempt_crashes_repair_same_context_without_http(self):
        import os
        import subprocess
        import sys
        from sec_edgar_ingest.state import attempt_key
        from sec_edgar_ingest.storage.local import LocalStateStore
        from support import retain_acquisition_proof
        for point in ('before_result_object', 'after_result_object', 'before_attempt_finish', 'after_attempt_finish'):
            with self.subTest(point=point):
                h = cli_harness('valid-quarter-and-daily')
                self.addCleanup(h.close)
                discovery = h.discover()
                self.assertEqual(discovery.returncode, 0, discovery.stderr)
                ref = json.loads(discovery.stdout)['source_workset_ref']
                arguments = ['collect', *h.common, '--workset', ref, '--execution-id', 'cli-collect', '--attempt-id', 'collect-1']
                argv = [sys.executable, '-c', 'import sys; from support import result_crash_entry; result_crash_entry(*sys.argv[1:])', point, *arguments]
                done = subprocess.run(argv, cwd=h.root, env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent), 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True, timeout=30)
                self.assertEqual(done.returncode, 74, done.stderr)
                store = LocalStateStore(h.state_root)
                rows = [row.to_mapping()['value'] for row in store.scan('Attempt', {}) if row.value['context']['command'] == 'collect']
                self.assertEqual(len(rows), 1)
                before = rows[0]
                result_path = 'runs/sec/cli-run/collect/collect-1/result.json'
                body_path = h.state_root / 'objects' / result_path
                before_body = body_path.read_bytes() if body_path.exists() else None
                if point != 'before_result_object': self.assertIsNotNone(before_body)
                self.assertEqual(before['outcome'], 'success' if point == 'after_attempt_finish' else 'in_progress')
                transport_before = [row.to_mapping() for row in store.scan('TransportAttempt', {})]
                store.close()
                replay = h.collect(ref)
                self.assertEqual(replay.returncode, 0, replay.stderr)
                result = h.read_durable_result(result_path)
                self.assertEqual(result.context.to_mapping(), before['context'])
                if before_body is not None: self.assertEqual(body_path.read_bytes(), before_body)
                store = LocalStateStore(h.state_root)
                self.assertEqual([row.to_mapping() for row in store.scan('TransportAttempt', {})], transport_before)
                finished = store.get('Attempt', attempt_key(result.context)).to_mapping()['value']
                self.assertEqual(finished['result'], result.to_mapping())
                store.close()
                retain_acquisition_proof('result-crash-' + point, {'argv': argv, 'crash': {'exit': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr},
                    'before_attempt': before, 'before_result_hex': before_body.hex() if before_body else None,
                    'after_result_hex': body_path.read_bytes().hex(), 'after_attempt': finished,
                    'transport_before': transport_before, 'replay': h.calls[-1], 'original_root': str(h.root)})

    def test_unexpected_error_is_nine_and_retains_attempt_without_result(self):
        import os
        import subprocess
        import sys
        from sec_edgar_ingest.storage.local import LocalStateStore
        h = cli_harness('valid-quarter-and-daily')
        self.addCleanup(h.close)
        ref = json.loads(h.discover().stdout)['source_workset_ref']
        argv = [sys.executable, '-c', 'import sys; from support import result_crash_entry; result_crash_entry(*sys.argv[1:])',
                'unexpected_error', 'collect', *h.common, '--workset', ref, '--execution-id', 'cli-collect', '--attempt-id', 'collect-1']
        done = subprocess.run(argv, cwd=h.root, env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent)}, capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 9, done.stderr)
        self.assertEqual(json.loads(done.stdout)['outcome'], 'internal_error')
        self.assertFalse((h.state_root / 'objects/runs/sec/cli-run/collect/collect-1/result.json').exists())
        store = LocalStateStore(h.state_root)
        self.addCleanup(store.close)
        rows = [row.to_mapping()['value'] for row in store.scan('Attempt', {}) if row.value['context']['command'] == 'collect']
        self.assertEqual(rows[0]['outcome'], 'internal_error')
        self.assertIsNone(rows[0]['result'])
        self.assertEqual(rows[0]['structured_errors'][0]['details']['type'], 'RuntimeError')


class DailyCliTests(unittest.TestCase):
    def test_open_daily_fixture_persists_delayed_cursor_and_old_pin_no_http(self):
        from sec_edgar_ingest.storage.local import LocalStateStore
        from sec_edgar_ingest.worksets import decode_snapshot_workset
        h = cli_harness('valid-quarter-and-daily')
        self.addCleanup(h.close)
        cfg = json.loads(h.config_path.read_text())
        cfg['backfill']['end_quarter'] = 'open'
        h.config_path.write_text(json.dumps(cfg))
        done = h.invoke('discover', ['--mode', 'daily', '--discovery-id', 'daily', '--execution-id', 'daily-discover', '--attempt-id', 'daily-discover'])
        self.assertEqual(done.returncode, 0, done.stderr)
        ref = json.loads(done.stdout)['source_workset_ref']
        first = h.collect(ref)
        self.assertEqual(first.returncode, 3, first.stderr)
        failed = h.read_durable_result(json.loads(first.stdout)['result_ref'])
        self.assertEqual((failed.outcome, failed.downloaded, failed.pending), ('incomplete', 1, 1))
        store = LocalStateStore(h.state_root)
        pins_before = [row.to_mapping()['value'] for row in store.scan('Binding', {})]
        transports_before = [row.to_mapping()['value'] for row in store.scan('TransportAttempt', {})]
        store.close()
        replay = h.collect(ref)
        self.assertEqual(replay.stdout, first.stdout)
        second = h.collect(ref, attempt='daily-collect-2', execution='daily-retry')
        self.assertEqual(second.returncode, 0, second.stderr)
        result = h.read_durable_result(json.loads(second.stdout)['result_ref'])
        self.assertEqual((result.downloaded, result.unchanged, result.pending), (1, 1, 0))
        self.assertEqual(result.context.priority, 'daily')
        store = LocalStateStore(h.state_root)
        self.addCleanup(store.close)
        pins_after = [row.to_mapping()['value'] for row in store.scan('Binding', {})]
        self.assertTrue(all(pin in pins_after for pin in pins_before))
        self.assertEqual(len(tuple(store.scan('TransportAttempt', {}))), len(transports_before) + 1)
        snapshot = decode_snapshot_workset((h.state_root / 'objects' / result.snapshot_workset_ref).read_bytes())
        self.assertEqual(snapshot.context.command, 'discover')
        third = h.collect(ref, attempt='daily-collect-3', execution='daily-offline')
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertEqual(json.loads(third.stdout)['snapshot_workset_ref'], result.snapshot_workset_ref)
        self.assertEqual(len(tuple(store.scan('TransportAttempt', {}))), len(transports_before) + 1)

    def test_fixture_mapping_exhaustion_and_missing_url_never_network(self):
        from threading import Event
        from sec_edgar_ingest.download import FixtureError, FixturePack
        from support import ACQUISITION_PACK, real_permit
        from sec_edgar_ingest.coordination import Clock
        with tempfile.TemporaryDirectory() as temporary:
            store, objects, leases = store_bundle(Path(temporary))
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            pack = FixturePack.load(ACQUISITION_PACK)
            sender = pack.sender(store)
            self.addCleanup(sender.close)
            clock = Clock()
            url = next(iter(pack.responses))
            sender.send(url, fixture_context(), real_permit(clock), cancellation=Event())
            sender.close()
            restarted = pack.sender(store)
            self.addCleanup(restarted.close)
            with self.assertRaises(FixtureError):
                restarted.send(url, fixture_context(), real_permit(clock), cancellation=Event())
            with self.assertRaises(FixtureError):
                restarted.send('https://www.sec.gov/Archives/edgar/full-index/2016/index.json', fixture_context(), real_permit(clock), cancellation=Event())


class ValidationBoundaryTests(unittest.TestCase):
    def test_fractional_lease_and_closed_daily_endpoint_refuse_before_clients(self):
        for case in ('fractional-lease', 'closed-daily'):
            with self.subTest(case=case):
                h = cli_harness('valid-quarter-and-daily')
                self.addCleanup(h.close)
                cfg = json.loads(h.config_path.read_text())
                if case == 'fractional-lease':
                    cfg['coordination']['lease_seconds'] = 59.5
                    h.config_path.write_text(json.dumps(cfg))
                done = h.invoke('discover', ['--mode', 'daily' if case == 'closed-daily' else 'quarterly', '--discovery-id', 'd', '--execution-id', 'e', '--attempt-id', 'a'])
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(h.external_client_constructions, 0)

    def test_azure_fixture_arguments_and_distant_deadline_refuse_before_clients(self):
        h = cli_harness('valid-quarter-and-daily')
        self.addCleanup(h.close)
        cfg = json.loads(h.config_path.read_text())
        cfg.pop('fixture')
        cfg['http']['retry_base_seconds'], cfg['http']['retry_cap_seconds'] = 2, 120
        cfg['worker'] = {'image_digest': 'sha256:' + 'a' * 64, 'provenance': 'immutable-image'}
        cfg['etl']['parser_version'] = 'envelope-v1'
        storage = cfg['storage']
        storage.pop('root')
        storage.update({'backend': 'azure', 'account_name': 'secedgardevb8617',
                        'blob_endpoint': 'https://secedgardevb8617.blob.core.windows.net',
                        'table_endpoint': 'https://secedgardevb8617.table.core.windows.net',
                        'raw_container': 'raw', 'workset_container': 'worksets', 'quarantine_container': 'quarantine', 'lock_container': 'locks',
                        'lock_blob': 'sec-owner-lowell-mason/sentinel.json', 'binding_registry_blob': 'sec-owner-lowell-mason/binding.json'})
        h.config_path.write_text(json.dumps(cfg))
        args = ['--mode', 'quarterly', '--discovery-id', 'd', '--execution-id', 'e', '--attempt-id', 'a']
        self.assertEqual(h.invoke('discover', args).returncode, 2)
        common = ['--config', str(h.config_path), '--run-id', 'cli-run', '--deadline', '2099-01-01T00:00:00Z']
        with patch.dict(os.environ, {WORKER_CLIENT_ID_ENV: WORKER_CLIENT_ID}):
            distant = h.invoke('discover', args, common=common)
        self.assertEqual(distant.returncode, 2)
        self.assertIn('3600-second worker allowance', distant.stderr)
        self.assertEqual(h.external_client_constructions, 0)

    def test_missing_valid_workset_retains_failed_attempt(self):
        from sec_edgar_ingest.storage.local import LocalStateStore
        h = cli_harness('valid-quarter-and-daily')
        self.addCleanup(h.close)
        done = h.collect('worksets/sec/source/sha256=' + 'a' * 64 + '/workset.json')
        self.assertEqual(done.returncode, 9)
        store = LocalStateStore(h.state_root)
        self.addCleanup(store.close)
        attempts = list(store.scan('Attempt', {}))
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].value['outcome'], 'state_conflict')
        self.assertIsNone(attempts[0].value['result'])


class ErrorIntegrityTests(unittest.TestCase):
    def test_missing_fixture_sender_mapping_retains_error_and_returns_nine(self):
        h = cli_harness('valid-quarter-and-daily')
        self.addCleanup(h.close)
        ref = json.loads(h.discover().stdout)['source_workset_ref']
        manifest = json.loads(h.pack_path.read_text())
        from support import fixture_source
        manifest['responses'].pop(fixture_source().canonical_url)
        h.pack_path.write_text(json.dumps(manifest))
        done = h.collect(ref)
        self.assertEqual(done.returncode, 9, done.stderr)
        self.assertEqual(json.loads(done.stdout)['outcome'], 'state_conflict')
        self.assertIsNone(json.loads(done.stdout)['result_ref'])

    def test_result_writer_refuses_prior_different_attempt_result_before_object_write(self):
        from sec_edgar_ingest.results import write_result, result_path
        from sec_edgar_ingest.state import AcquisitionState, attempt_key
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as temporary:
            store, objects, leases = store_bundle(Path(temporary))
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            state = AcquisitionState(store)
            result = ResultTests().result()
            state.begin_attempt(result.context)
            state.finish_attempt(replace(result, downloaded=1))
            with self.assertRaises(Conflict):
                write_result(result, objects, state)
            with self.assertRaises(FileNotFoundError):
                objects.read(result_path(result.context))

    def test_unexpected_real_request_sender_error_is_nine_without_durable_result(self):
        import os
        import subprocess
        import sys
        from sec_edgar_ingest.storage.local import LocalStateStore
        h = cli_harness('valid-quarter-and-daily')
        self.addCleanup(h.close)
        ref = json.loads(h.discover().stdout)['source_workset_ref']
        argv = [sys.executable, '-c', 'import sys; from support import result_crash_entry; result_crash_entry(*sys.argv[1:])',
                'unexpected_sender', 'collect', *h.common, '--workset', ref, '--execution-id', 'cli-collect', '--attempt-id', 'collect-1']
        done = subprocess.run(argv, cwd=h.root, env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent)}, capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 9, done.stderr)
        self.assertEqual(json.loads(done.stdout)['outcome'], 'internal_error')
        self.assertIsNone(json.loads(done.stdout)['result_ref'])
        store = LocalStateStore(h.state_root)
        self.addCleanup(store.close)
        transport = list(store.scan('TransportAttempt', {}))
        self.assertEqual(len([row for row in transport if row.value['context']['command'] == 'collect']), 1)
        attempts = [row for row in store.scan('Attempt', {}) if row.value['context']['command'] == 'collect']
        self.assertEqual(attempts[0].value['outcome'], 'internal_error')
        self.assertIsNone(attempts[0].value['result'])


class CompletedDeadlineTests(unittest.TestCase):
    def test_completed_attempt_replays_after_deadline_without_fabricating_start(self):
        from datetime import datetime, timezone
        from unittest.mock import patch
        from sec_edgar_ingest.cli import main
        from sec_edgar_ingest.coordination import Clock
        h = cli_harness('valid-quarter-and-daily')
        self.addCleanup(h.close)
        first = h.discover()
        self.assertEqual(first.returncode, 0, first.stderr)
        record = h.read_durable_result(json.loads(first.stdout)['result_ref'])
        class LaterClock(Clock):
            def now(self): return datetime(2100, 1, 1, tzinfo=timezone.utc)
        output, errors = io.StringIO(), io.StringIO()
        args = ['discover', *h.common, '--mode', 'quarterly', '--discovery-id', 'cli-discovery', '--execution-id', 'cli-discover', '--attempt-id', 'discover-1']
        with patch('sec_edgar_ingest.cli.Clock', LaterClock), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(args)
        self.assertEqual(code, 0, errors.getvalue())
        self.assertEqual(output.getvalue(), first.stdout)
        self.assertEqual(h.read_durable_result(json.loads(first.stdout)['result_ref']), record)
