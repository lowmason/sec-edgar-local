"""Offline invariants for the external bounded genuine-SEC acceptance harness."""
from network_guard import install
install()

import concurrent.futures
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest

PROJECT = Path(__file__).resolve().parents[3]
DRIVER = PROJECT / 'scripts/accept-sec-native.py'


def harness():
    if not DRIVER.exists():
        raise AssertionError('missing acceptance-only selection and reservation harness')
    return runpy.run_path(str(DRIVER))


def example_selection(api, root):
    release = root / ('releases/sha256=' + 'a' * 64) / 'release.json'
    release.parent.mkdir(parents=True)
    release.write_text(json.dumps({'release_id': 'a' * 64}))
    configs = {mode: {'path': str(root / (mode + '.json')), 'sha256': 'b' * 64,
                      'effective_sha256': 'c' * 64} for mode in ('quarterly', 'daily')}
    scope = {'root_existed': False, 'pending_sources': [], 'failed_directories': [],
             'daily_quarters': ['2026Q3', '2026Q4'],
             'quarterly_listing_urls': [api['BASE'] + 'full-index/index.json'],
             'daily_listing_urls': [api['BASE'] + 'daily-index/index.json']}
    return api['build_selection'](root / 'data', root, release, configs,
        {'path': str(root / 'input.json'), 'sha256': 'd' * 64},
        {'binding_version': 'sec-local-binding-v1', 'root': str(root / 'data'),
         'acquisition_mode': 'live', 'sec': {'user_agent': api['OWNER']}}, scope)


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.api = harness()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.selection = example_selection(self.api, self.root)
        self.path = self.root / 'selection.json'
        self.path.write_bytes(self.api['canonical'](self.selection))

    def ledger(self, value=None):
        if value is not None:
            self.selection = value
            self.path.write_bytes(self.api['canonical'](value))
        return self.api['Budget'](self.path)

    def test_selection_is_closed_and_requires_exact_core_case(self):
        validate = self.api['validate_selection']
        validate(self.selection)
        changes = [('quarterly_periods', ['2024Q2']), ('daily_dates', ['2026-10-14'] * 2),
                   ('daily_dates', ['2026-10-13', '2026-10-15']),
                   ('sole_issuer_confirmed', 1), ('unknown', True)]
        for key, value in changes:
            with self.subTest(key=key), self.assertRaises(ValueError):
                altered = copy.deepcopy(self.selection)
                altered[key] = value
                validate(altered)
        for key, value in [('attempts', 101), ('attempts', True), ('received_bytes', 134217729),
                           ('wall_seconds', 901), ('distinct_urls', 21)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                altered = copy.deepcopy(self.selection)
                altered['limits'][key] = value
                validate(altered)

    def test_window_and_scope_cannot_move_on_restart(self):
        validate = self.api['validate_selection']
        altered = copy.deepcopy(self.selection)
        altered['window']['deadline_utc'] = (datetime.fromisoformat(altered['window']['deadline_utc'])
                                               + timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            validate(altered)
        self.api['validate_daily_scope'](self.selection, ('2026Q3', '2026Q4'))
        with self.assertRaisesRegex(ValueError, 'revised selection'):
            self.api['validate_daily_scope'](self.selection, ('2027Q1', '2027Q2'))
        self.assertGreater(self.api['remaining_seconds'](self.selection), 0)
        self.assertEqual(self.api['remaining_seconds'](self.selection,
            now=datetime(2030, 1, 1, tzinfo=timezone.utc)), 0)

    def test_received_last_response_reserves_full_ceiling_before_send(self):
        budget = self.ledger()
        url = self.selection['sources'][0]['url']
        first = budget.reserve_send(url, 'command')
        second = budget.reserve_send(url, 'command')
        with self.assertRaises(self.api['AcceptanceLimit']):
            budget.reserve_send(url, 'command')
        budget.settle(first, 1)
        with self.assertRaises(self.api['AcceptanceLimit']):
            budget.reserve_send(url, 'command')
        budget.settle(second, 0)
        third = budget.reserve_send(url, 'command')
        self.assertEqual(budget.summary()['totals']['attempts'], 3)
        self.assertEqual(budget.summary()['totals']['received_bytes'], 67108865)
        self.assertIsInstance(third, str)

    def test_crash_reservations_survive_reopen_and_settlement_is_once(self):
        budget = self.ledger()
        first = budget.reserve_send(self.selection['sources'][0]['url'], 'command')
        reopened = self.api['Budget'](self.path)
        self.assertEqual(reopened.summary()['totals']['received_bytes'], 67108864)
        reopened.settle(first, 12)
        self.assertEqual(self.api['Budget'](self.path).summary()['totals']['received_bytes'], 12)
        with self.assertRaises(ValueError):
            reopened.settle(first, 0)
        self.assertEqual(reopened.summary()['totals']['attempts'], 1)

    def test_retry_ordinals_and_per_url_total_are_global(self):
        budget = self.ledger()
        url = self.selection['sources'][0]['url']
        for index in range(5):
            reservation = budget.reserve_send(url, 'command-' + str(index))
            budget.settle(reservation, 0)
        with self.assertRaises(self.api['AcceptanceLimit']):
            budget.reserve_send(url, 'restart')
        self.assertEqual([item['ordinal'] for item in budget.summary()['requests']], [1] * 5)
        self.assertEqual(budget.summary()['totals']['attempts'], 5)

    def test_changed_selection_or_limits_refuses_existing_ledger(self):
        budget = self.ledger()
        altered = copy.deepcopy(self.selection)
        altered['limits']['attempts'] = 99
        self.path.write_bytes(self.api['canonical'](altered))
        with self.assertRaises(ValueError):
            budget.reserve_send(self.selection['sources'][0]['url'], 'c')
        with self.assertRaises(ValueError):
            self.api['Budget'](self.path)

    def test_concurrent_reservations_cannot_overdraw(self):
        budget = self.ledger()
        url = self.selection['sources'][0]['url']
        def reserve(index):
            try:
                return self.api['Budget'](self.path).reserve_send(url, 'c' + str(index))
            except self.api['AcceptanceLimit']:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(reserve, range(12)))
        self.assertEqual(sum(value is not None for value in values), 2)
        self.assertEqual(budget.summary()['totals']['attempts'], 2)

    def test_unlisted_or_noncanonical_url_refuses_without_charge(self):
        budget = self.ledger()
        for url in ['https://example.com/index.json', self.selection['sources'][0]['url'] + '?x=1',
                    'https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/master.20261016.idx']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                budget.reserve_send(url, 'c')
        self.assertEqual(budget.summary()['totals']['attempts'], 0)

    def test_expanded_reservation_counts_revalidation_and_failed_validation(self):
        budget = self.ledger()
        reservation = budget.reserve_expanded()
        budget.settle(reservation, 11)
        second = budget.reserve_expanded()
        with self.assertRaises(self.api['AcceptanceLimit']):
            budget.reserve_expanded()
        budget.settle(second, 1)
        budget.reserve_expanded()
        self.assertEqual(budget.summary()['totals']['expanded_bytes'], 536870924)

    def test_wrapper_preserves_real_sender_and_counts_uncertain_drain(self):
        budget = self.ledger()
        context = SimpleNamespace(run_id='r', command='collect', attempt_id='a', execution_id='e')
        url = self.selection['sources'][0]['url']
        class Sender:
            def __init__(self, *args): pass
            def send(self, *args, **kwargs):
                raise RuntimeError('unconfirmed child')
        wrapped = self.api['budget_sender'](Sender, budget)
        with self.assertRaisesRegex(RuntimeError, 'unconfirmed child'):
            wrapped(None, None).send(url, context, None, cancellation=None)
        self.assertEqual(budget.summary()['totals']['received_bytes'], 67108864)
        self.assertEqual(budget.summary()['actual_sent_requests'], 0)

    def test_returned_incomplete_receipt_retains_full_charge(self):
        budget = self.ledger()
        spool = self.root / 'spool'
        spool.mkdir()
        (spool / 'body').write_bytes(b'abc')
        (spool / 'transport.jsonl').write_text(json.dumps({'event': 'socket-start'}) + '\n')
        class Sender:
            def __init__(self, *args): pass
            def send(self, *args, **kwargs):
                return SimpleNamespace(byte_count=3, temporary_path=spool / 'body', complete=False)
        context = SimpleNamespace(run_id='r', command='collect', attempt_id='a', execution_id='e')
        wrapped = self.api['budget_sender'](Sender, budget)
        wrapped(None, None).send(self.selection['sources'][0]['url'], context, None, cancellation=None)
        self.assertEqual(budget.summary()['totals']['received_bytes'], 67108864)
        self.assertEqual(budget.summary()['actual_sent_requests'], 1)

    def test_all_three_validation_references_use_same_retained_real_validator(self):
        budget = self.ledger()
        validated = []
        def real(*args):
            validated.append(True)
            return SimpleNamespace(expanded_byte_count=7)
        cli = SimpleNamespace(BoundedSender=object)
        collection, transform, download = SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
        self.api['install_wrappers'](budget, cli, collection, transform, real, download)
        download.validate_envelope(None, None, None)
        collection.validate_envelope(None, None, None)
        transform.validate_envelope(None, None, None)
        self.assertEqual(validated, [True, True, True])
        self.assertEqual(budget.summary()['totals']['expanded_bytes'], 21)

    def test_call_is_closed_hash_bound_and_forbids_workflow_or_date_override(self):
        call = self.api['make_call'](self.selection, self.path, ['discover', '--config',
            self.selection['configs']['quarterly']['path'], '--run-id', 'r', '--execution-id', 'e',
            '--attempt-id', 'a', '--deadline', self.selection['window']['deadline_utc'],
            '--mode', 'quarterly', '--discovery-id', 'd'])
        self.api['validate_call'](call, self.selection, self.path)
        for change in ({'extra': 1}, {'selection_sha256': 'f' * 64}):
            with self.assertRaises(ValueError):
                self.api['validate_call']({**call, **change}, self.selection, self.path)
        for argv in [['daily'], ['backfill'], ['collect', '--today', '2026-10-14']]:
            with self.assertRaises(ValueError):
                self.api['make_call'](self.selection, self.path, argv)

    def test_child_argv_fixed_signature_and_window_does_not_refresh(self):
        argv = self.api['child_argv'](self.selection, self.path, self.root / 'call.json')
        self.assertEqual(argv[:3], [self.selection['native_python'], '-I',
                                  str(PROJECT / 'scripts/sec-acceptance-child.py')])
        self.assertEqual(argv[3:], ['--selection', str(self.path), '--call', str(self.root / 'call.json')])

    def test_l12_requires_every_proof_and_at_least_one_validated_publication(self):
        evaluate = self.api['evaluate_l12']
        proof = {'genuine_native': True, 'persistence': True, 'restart_reuse': True,
                 'exact_replay': True, 'bounded': True, 'published_reads': [{'rows': 3, 'validated': True}]}
        self.assertEqual(evaluate(proof)['status'], 'pass')
        for key in ('genuine_native', 'persistence', 'restart_reuse', 'exact_replay', 'bounded'):
            with self.subTest(key=key):
                self.assertEqual(evaluate({**proof, key: False})['status'], 'incomplete')
        self.assertEqual(evaluate({**proof, 'published_reads': []})['status'], 'incomplete')


    def test_native_child_refuses_changed_call_before_budget_creation(self):
        import subprocess
        release = PROJECT / 'releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/release.json'
        if not release.exists():
            from support_release import proof_releases
            native, _ = proof_releases(PROJECT, PROJECT / 'releases/artifact-cache')
            release = native.directory / 'release.json'
        from sec_edgar_ingest.config import Settings
        from sec_edgar_ingest.storage.contracts import deployment_binding
        from sec_edgar_ingest.models import canonical_json, to_mapping_value
        from support import local_config_mapping
        value = local_config_mapping(root=self.root / 'data')
        value.pop('fixture', None)
        value['acquisition'] = {'mode': 'live'}
        value['runtime'] = {'kind': 'native', 'release_manifest': str(release)}
        value['etl'] = {'parser_version': 'sec-index-parser-v1', 'schema_version': 'sec-index-v1'}
        value['daily'] = {'start_date': '2026-10-01'}
        value['storage']['root'] = str(self.root / 'data')
        value['logging']['root'] = str(self.root / 'logs')
        configs = {}
        for mode in ('quarterly', 'daily'):
            value['backfill'] = {'start_quarter': '2024Q1', 'end_quarter': '2024Q1' if mode == 'quarterly' else 'open'}
            configured = Settings.from_mapping(value)
            path = self.root / (mode + '.json')
            path.write_bytes(canonical_json(to_mapping_value(configured.to_mapping())))
            configs[mode] = {'path': str(path), 'sha256': self.api['digest'](path.read_bytes()),
                             'effective_sha256': configured.config_sha256}
        input_path = self.root / 'input.json'
        input_path.write_bytes(canonical_json(to_mapping_value(configured.to_mapping())))
        selected = self.api['build_selection'](self.root / 'data', self.root, release, configs,
            {'path': str(input_path), 'sha256': self.api['digest'](input_path.read_bytes())},
            deployment_binding(configured), self.selection['inventory'])
        self.path.write_bytes(self.api['canonical'](selected))
        (self.root / 'prepared.json').write_bytes(self.api['canonical']({'format_version': 'sec-local-sec-prepared-v1',
            'selection_path': str(self.path), 'selection_sha256': self.api['digest'](self.path.read_bytes())}))
        call = self.root / 'call.json'
        call.write_text('{}')
        result = subprocess.run(self.api['child_argv'](selected, self.path, call),
                                capture_output=True, env=self.api['scrub_environment']())
        self.assertEqual(result.returncode, 2, result.stderr.decode())
        self.assertIn('call must have exactly', result.stderr.decode())
        self.assertFalse((self.root / 'budget.sqlite3').exists())
        self.assertFalse((self.root / 'data').exists())
        selected['harness']['driver']['sha256'] = '0' * 64
        self.path.write_bytes(self.api['canonical'](selected))
        (self.root / 'prepared.json').write_bytes(self.api['canonical']({'format_version': 'sec-local-sec-prepared-v1',
            'selection_path': str(self.path), 'selection_sha256': self.api['digest'](self.path.read_bytes())}))
        refused = subprocess.run(self.api['child_argv'](selected, self.path, call),
                                 capture_output=True, env=self.api['scrub_environment']())
        self.assertEqual(refused.returncode, 2, refused.stderr.decode())
        self.assertIn('harness bytes changed', refused.stderr.decode())
        self.assertFalse((self.root / 'budget.sqlite3').exists())
        self.assertFalse((self.root / 'data').exists())

    def test_local_process_supervisor_preserves_exit_and_positive_drain(self):
        import sys
        result = self.api['supervise']([sys.executable, '-I', '-c',
            'import sys;print("child-out");print("child-err",file=sys.stderr);sys.exit(7)'],
            self.selection)
        self.assertEqual(result['returncode'], 7)
        self.assertEqual(result['stdout'], b'child-out\n')
        self.assertEqual(result['stderr'], b'child-err\n')
        self.assertTrue(result['drained'])

    def test_local_process_supervisor_expired_window_never_dispatches(self):
        import sys
        selection = copy.deepcopy(self.selection)
        selection['window']['deadline_utc'] = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        with self.assertRaises(self.api['AcceptanceLimit']):
            self.api['supervise']([sys.executable, '-c', 'raise AssertionError("dispatched")'], selection)


    def test_global_attempt_and_distinct_url_limits_include_all_retries(self):
        selection = copy.deepcopy(self.selection)
        selection['inventory']['daily_listing_urls'] = [self.api['BASE'] + f'daily-index/{year}/index.json' for year in range(2000, 2017)]
        selection['inventory']['quarterly_listing_urls'] = []
        budget = self.ledger(selection)
        urls = sorted(self.api['permitted_urls'](selection))
        self.assertEqual(len(urls), 20)
        for url in urls:
            for _ in range(5):
                reservation = budget.reserve_send(url, 'same-command')
                budget.settle(reservation, 0)
        self.assertEqual(budget.summary()['totals']['attempts'], 100)
        with self.assertRaises(self.api['AcceptanceLimit']):
            budget.reserve_send(urls[0], 'new-process')
        self.assertEqual(budget.summary()['distinct_urls'], 20)

    def test_actual_validator_aliases_all_charge_and_restore_without_production_edits(self):
        from unittest.mock import patch
        from sec_edgar_ingest import cli, collection, download, validation
        from sec_edgar_ingest.etl import transform
        from sec_edgar_ingest.models import BodyReceipt, Source
        from support import fixture_settings
        from support_workflows import idx
        budget = self.ledger()
        body = idx([['123456', 'Offline example', '10-K', '20261014',
                     'edgar/data/123456/0000123456-26-000001.txt']], 'daily')
        path = self.root / 'body'
        path.write_bytes(body)
        url = self.selection['sources'][1]['url']
        source = Source(self.api['digest'](url.encode()), url, 'daily', '2026-10-14', 'idx')
        receipt = BodyReceipt(url, 200, {}, path, datetime.now(timezone.utc), len(body), self.api['digest'](body), True, None)
        settings = fixture_settings(root=self.root / 'fixture')
        real = validation.validate_envelope
        with patch.object(cli, 'BoundedSender'), patch.object(collection, 'validate_envelope'), \
                patch.object(transform, 'validate_envelope'), patch.object(download, 'validate_envelope'):
            self.api['install_wrappers'](budget, cli, collection, transform, real, download)
            for function in (download.validate_envelope, collection.validate_envelope, transform.validate_envelope):
                self.assertEqual(function(source, receipt, settings).expanded_byte_count, len(body))
        self.assertIs(validation.validate_envelope, real)
        self.assertEqual(budget.summary()['totals']['expanded_bytes'], 3 * len(body))

    def test_real_offline_projection_replay_transform_publication_capture_flow(self):
        from sec_edgar_ingest.models import canonical_json, to_mapping_value
        from support import fixture_settings
        from support_workflows import build_pack, idx, CommandHarness
        base = self.api['BASE']
        listings = {base + 'full-index/index.json': [('2024', 'dir')],
            base + 'full-index/2024/index.json': [('QTR1', 'dir')],
            base + 'full-index/2024/QTR1/index.json': [('master.zip', 'file')],
            base + 'daily-index/index.json': [('2026', 'dir')],
            base + 'daily-index/2026/index.json': [('QTR3', 'dir'), ('QTR4', 'dir')],
            base + 'daily-index/2026/QTR3/index.json': [],
            base + 'daily-index/2026/QTR4/index.json': [('master.20261014.idx', 'file'), ('master.20261015.idx', 'file')]}
        bodies = {self.selection['sources'][0]['url']: idx([['123456', 'Offline example', '10-K', '2024-03-01',
                     'edgar/data/123456/0000123456-24-000001.txt']], 'quarterly')}
        for index, source in enumerate(self.selection['sources'][1:], 1):
            bodies[source['url']] = idx([['123456', 'Offline example', '10-K', source['period'].replace('-', ''),
                     f'edgar/data/123456/0000123456-26-00000{index}.txt']], 'daily')
        pack = build_pack(self.root / 'pack', listings, bodies)
        (self.root / 'fixture').mkdir()
        command_harnesses = {}
        for mode in ('quarterly', 'daily'):
            settings = fixture_settings(root=self.root / 'fixture',
                backfill={'start_quarter': '2024Q1', 'end_quarter': '2024Q1' if mode == 'quarterly' else 'open'},
                daily={'start_date': '2026-10-01'}, etl={'parser_version': 'sec-index-parser-v1'},
                fixture={'allow_clock_override': True})
            command_harnesses[mode] = CommandHarness(self.root / 'fixture', pack, settings)
            self.addCleanup(command_harnesses[mode].close)
        selected = copy.deepcopy(self.selection)
        for mode in ('quarterly', 'daily'):
            selected['inventory'][mode + '_listing_urls'] = [url for url in listings if ('full-index' if mode == 'quarterly' else 'daily-index') in url]
        self.path.write_bytes(self.api['canonical'](selected))
        for mode, fixture_harness in command_harnesses.items():
            fixture_harness.config = fixture_harness.root / (mode + '-config.json')
            fixture_harness.deadline = datetime.fromisoformat(selected['window']['deadline_utc'])
            fixture_harness.config.write_bytes(canonical_json(to_mapping_value(fixture_harness.settings.to_mapping())))
            selected['configs'][mode] = {'path': str(fixture_harness.config),
                'sha256': self.api['digest'](fixture_harness.config.read_bytes()), 'effective_sha256': fixture_harness.settings.config_sha256}
        self.path.write_bytes(self.api['canonical'](selected))
        seen = []
        api = self.api
        class OfflineEngine(api['AcceptanceRun']):
            def invoke(engine, label, mode, command, flags, replay=False):
                harness = command_harnesses[mode]
                harness.config.write_bytes(canonical_json(to_mapping_value(harness.settings.to_mapping())))
                code, message = harness.invoke(command, flags, run='offlineaccept', attempt=label,
                                                today='2026-10-18')
                self.assertEqual(code, 0, (command, message))
                seen.append((label, command, replay))
                from sec_edgar_ingest.results import read_result
                from sec_edgar_ingest.etl.commands import read_etl_result
                result = (read_etl_result if command in ('transform', 'publish') else read_result)(message['result_ref'], harness.objects)
                import uuid
                frozen = harness.calls[-1]['argv']
                public = [frozen[0]]
                for name, value in zip(frozen[1::2], frozen[2::2]):
                    if name not in ('--today', '--fixture-pack'): public.extend((name, value))
                call = api['make_call'](selected, self.path, public)
                attempt = self.root / 'commands' / label / 'attempt-000'
                call_path = attempt / 'call.json'
                api['write_once'](call_path, api['canonical'](call))
                launch_id = uuid.uuid4().hex
                launch = attempt / 'launches' / ('launch-' + launch_id)
                argv = api['child_argv'](selected, self.path, call_path)
                dispatch = {'format_version': 'sec-local-sec-dispatch-v1',
                    'selection_sha256': api['digest'](self.path.read_bytes()), 'call_path': str(call_path),
                    'call_sha256': api['digest'](call_path.read_bytes()), 'launch_path': str(launch),
                    'argv': argv, 'dispatched_utc': datetime.now(timezone.utc).isoformat()}
                api['write_once'](launch / 'dispatch.json', api['canonical'](dispatch))
                api['write_once'](self.root / 'dispatches' / (launch_id + '.json'), api['canonical'](dispatch))
                stdout, stderr = api['canonical'](message) + b'\n', b'explicit offline fake process boundary\n'
                execution = {'pid': 10000 + len(seen), 'argv': argv, 'returncode': code, 'drained': True,
                    'stdout_sha256': api['digest'](stdout), 'stderr_sha256': api['digest'](stderr),
                    'stdout_path': str(launch / 'stdout'), 'stderr_path': str(launch / 'stderr')}
                for path, body in [(launch / 'started.json', api['canonical']({'pid': execution['pid']})),
                        (launch / 'stdout', stdout), (launch / 'stderr', stderr),
                        (launch / 'execution.json', api['canonical'](execution)),
                        (attempt / 'result.json', harness.objects.read(message['result_ref']))]:
                    api['write_once'](path, body)
                if not (attempt / 'execution.json').exists(): api['write_once'](attempt / 'execution.json', api['canonical'](execution))
                engine.results.append({'label': label})
                if replay: engine.replays.append({'label': label})
                return result
        engine = OfflineEngine(self.path, selected, {mode: harness.settings for mode, harness in command_harnesses.items()})
        self.api['execute_case'](engine)
        self.assertEqual(len(engine.acquisitions), 3)
        self.assertEqual(len(engine.reuse), 3)
        self.assertEqual(len(engine.replays), 3)
        self.assertGreaterEqual(len(engine.reads), 2)
        self.assertTrue(all(item['validated'] and item['rows'] > 0 for item in engine.reads))
        daily_position = next(i for i, item in enumerate(seen) if item[0] == 'daily-discover')
        quarterly_position = next(i for i, item in enumerate(seen) if item[0] == '2024Q1-collect')
        self.assertLess(quarterly_position, daily_position)
        self.assertEqual(len(list((self.root / 'members').glob('*.json'))), 3)
        records, launches = api['inspect_commands'](self.path, selected, command_harnesses['daily'].objects)
        self.assertEqual(len(records), len(seen))
        proof = api['derive_source_proof'](selected, launches, [], command_harnesses['daily'].store, command_harnesses['daily'].objects)
        self.assertEqual(len(proof['selected_acquired']), 3)
        self.assertEqual(len(proof['selected_reused']), 3)
        self.assertEqual(len(proof['selected_replayed']), 3)
        self.assertEqual(len(proof['selected_publications']), 3)
        self.assertFalse(proof['genuine_native'], 'explicit fixtures cannot establish genuine native acquisition')
        # Exercise the real FrozenMapping/native descriptor boundary with fake
        # transport receipts; the underlying publication fixture stays explicit.
        from dataclasses import replace
        from sec_edgar_ingest.models import RunContext
        from sec_edgar_ingest.runtime import native_descriptor
        from sec_edgar_ingest.state import attempt_key
        native_selection = copy.deepcopy(selected)
        native_selection['release_id'] = 'fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec'
        native_launches = []
        for item in launches:
            context = item['result'].context
            effective = context.to_mapping()['effective_config']
            effective.pop('fixture', None)
            effective['acquisition'] = {'mode': 'live'}
            effective['runtime'] = {'kind': 'native', 'release_manifest': str(PROJECT / 'releases' / ('sha256=' + native_selection['release_id']) / 'release.json')}
            native = replace(context, runtime=native_descriptor(native_selection['release_id']),
                effective_config=effective, config_sha256=api['digest'](api['canonical'](effective)))
            self.assertIsInstance(native, RunContext)
            self.assertEqual(type(native.runtime).__name__, 'FrozenMapping')
            native_launches.append({**item, 'result': replace(item['result'], context=native)})
        def admissions_for(items):
            admissions = []
            for source in selected['sources']:
                original = next(item for item in items if item['record']['label'] == source['period'] + '-collect')
                snapshot = api['read_json'](self.root / 'snapshots' / (source['source_id'] + '.json'))
                context = original['result'].context
                admissions.append({'production': {'context': context.to_mapping(), 'attempt_key': attempt_key(context)},
                    'request': {'url': source['url']}, 'sha256': snapshot['sha256'], 'socket_started': True, 'complete': True})
            return admissions
        admissions = admissions_for(native_launches)
        classified = api['derive_source_proof'](native_selection, native_launches, admissions,
            command_harnesses['daily'].store, command_harnesses['daily'].objects)
        self.assertEqual(classified['selected_native'], sorted(source['source_id'] for source in selected['sources']))
        self.assertEqual(len(classified['published_reads']), len(proof['selected_publications']))
        for variant in ('wrong-release', 'wrong-mode', 'context-mismatch'):
            changed = []
            for item in native_launches:
                context = item['result'].context
                if variant == 'wrong-release': context = replace(context, runtime=native_descriptor('f' * 64))
                if variant == 'wrong-mode':
                    effective = context.to_mapping()['effective_config']
                    effective['acquisition']['mode'] = 'fixture'
                    context = replace(context, effective_config=effective)
                changed.append({**item, 'result': replace(item['result'], context=context)})
            receipts = admissions_for(changed)
            if variant == 'context-mismatch':
                for admission in receipts:
                    context = RunContext.from_mapping(admission['production']['context'])
                    context = replace(context, started_at=context.started_at - timedelta(microseconds=1))
                    admission['production']['context'] = context.to_mapping()
            rejected = api['derive_source_proof'](native_selection, changed, receipts,
                command_harnesses['daily'].store, command_harnesses['daily'].objects)
            self.assertEqual(rejected['selected_native'], [], variant)
        no_replay = [item for item in launches if sum(other['record']['call_path'] == item['record']['call_path'] for other in launches[:launches.index(item)]) == 0]
        absent = api['derive_source_proof'](selected, no_replay, [], command_harnesses['daily'].store, command_harnesses['daily'].objects)
        self.assertEqual(absent['selected_replayed'], [])
        no_reuse = [item for item in launches if not item['record']['label'].endswith('-reuse')]
        absent = api['derive_source_proof'](selected, no_reuse, [], command_harnesses['daily'].store, command_harnesses['daily'].objects)
        self.assertEqual(absent['selected_reused'], [])
        removed = Path(records[0]['execution_path'])
        original = removed.read_bytes()
        removed.unlink()
        with self.assertRaises(OSError): api['inspect_commands'](self.path, selected, command_harnesses['daily'].objects)
        removed.write_bytes(original)
        # A complete fixture-backed archive is verifiable but remains L12 incomplete.
        commands, ledger, derived = api['derive_evidence'](self.path, selected, command_harnesses['daily'].store, command_harnesses['daily'].objects)
        worker = self.root / 'workers/offline-boundary'
        worker.mkdir(parents=True)
        started = datetime.now(timezone.utc)
        request = {'format_version': 'sec-local-sec-worker-v1', 'selection_sha256': api['digest'](self.path.read_bytes()),
            'selection_path': str(self.path), 'supervisor_pid': 1234}
        (worker / 'request.json').write_bytes(api['canonical'](request))
        (worker / 'started.json').write_bytes(api['canonical']({'pid': 2345}))
        (worker / 'stdout').write_bytes(b'explicit offline worker boundary\n')
        (worker / 'stderr').write_bytes(b'')
        report = {'format_version': 'sec-local-sec-acceptance-v1', 'selection_sha256': api['digest'](self.path.read_bytes()), 'release_id': selected['release_id'],
            'commands': commands, 'proof': derived, 'status': api['evaluate_l12'](derived), 'reason': None,
            'budget': ledger, 'ended_utc': datetime.now(timezone.utc).isoformat(),
            'worker_request': str(worker / 'request.json')}
        report_path = self.root / 'run-offline.json'
        report_path.write_bytes(api['canonical'](report))
        (worker / 'stdout').write_bytes(api['canonical']({'status': report['status'],
            'report': str(report_path), 'budget': report['budget']['totals']}) + b'\n')
        watch = {'selection_sha256': request['selection_sha256'], 'argv': api['worker_argv'](self.path, selected),
            'pid': 2345, 'drained': True, 'returncode': 12, 'outcome': 'completed',
            'started_utc': started.isoformat(), 'ended_utc': datetime.now(timezone.utc).isoformat(),
            'stdout_sha256': api['digest']((worker / 'stdout').read_bytes()), 'stderr_sha256': api['digest'](b''),
            'monotonic_budget': 800, 'monotonic_elapsed': 0.01}
        (worker / 'watchdog.json').write_bytes(api['canonical'](watch))
        self.assertEqual(api['verify_acceptance'](self.path, selected, engine.settings), api['LIMIT_EXIT'])
        # The same archive cannot omit a replay/reuse or alter budget totals.
        for change in ('replay', 'reuse', 'budget'):
            altered = copy.deepcopy(report)
            if change == 'budget': altered['budget']['totals']['attempts'] += 1
            elif change == 'reuse': altered['commands'] = [item for item in altered['commands'] if not item['label'].endswith('-reuse')]
            else:
                label = selected['sources'][0]['period'] + '-collect'
                replay = [item for item in altered['commands'] if item['label'] == label][-1]
                altered['commands'].remove(replay)
            report_path.write_bytes(api['canonical'](altered))
            with self.assertRaises(ValueError): api['verify_acceptance'](self.path, selected, engine.settings)
        report_path.write_bytes(api['canonical'](report))
        # Extra capture files remain unrelated even if an otherwise valid frozen
        # capture is copied into the evidence directory under another identity.
        capture_path = next(path for path in (self.root / 'captures').glob('*.json') if not path.name.endswith('.read.json'))
        unrelated = self.root / 'captures/unrelated-valid-capture.json'
        unrelated.write_bytes(capture_path.read_bytes())
        with self.assertRaisesRegex(ValueError, 'unrelated'):
            api['verify_acceptance'](self.path, selected, engine.settings)
        unrelated.unlink()
        # Supplemental analysis also accepts a fully consistent synthetic
        # original archive only as incomplete; runtime verification is an
        # explicit fake boundary here, never an acquisition path.
        from unittest.mock import patch
        analyzer = runpy.run_path(str(PROJECT / 'scripts/verify-sec-native-adjudication.py'))
        historical_directory = self.root / 'harness-original'
        historical_directory.mkdir()
        for record in selected['harness'].values():
            (historical_directory / Path(record['path']).name).write_bytes(Path(record['path']).read_bytes())
        historical = analyzer['historical_selection'](selected)
        verification_path = next(self.root.glob('verification-*.json'))
        output = self.root / 'adjudications/offline-synthetic.json'
        args = SimpleNamespace(selection=self.path, report=report_path,
            original_verification=verification_path, output=output)
        original_hash = api['digest'](report_path.read_bytes())
        with patch.dict(api, {'verify_runtime': lambda value: engine.settings}):
            code = analyzer['adjudicate'](api, args, selected, engine.settings, historical)
        self.assertEqual(code, api['LIMIT_EXIT'])
        supplement = api['read_json'](output)
        self.assertEqual(supplement['original']['driver_exit'], 12)
        self.assertEqual(supplement['original']['status']['status'], 'incomplete')
        self.assertEqual(supplement['independent_status']['status'], 'incomplete')
        self.assertFalse(supplement['acquisition_repeated'])
        self.assertEqual(api['digest'](report_path.read_bytes()), original_hash)


    def test_preparation_receipt_refuses_canonical_selection_edit_before_first_run(self):
        receipt = self.root / 'prepared.json'
        receipt.write_bytes(self.api['canonical']({'format_version': 'sec-local-sec-prepared-v1',
            'selection_path': str(self.path), 'selection_sha256': self.api['digest'](self.path.read_bytes())}))
        self.api['require_prepared'](self.path)
        selected = copy.deepcopy(self.selection)
        selected['limits']['attempts'] = 99
        self.path.write_bytes(self.api['canonical'](selected))
        with self.assertRaisesRegex(ValueError, 'prepared selection'):
            self.api['require_prepared'](self.path)

    def test_cross_process_crash_after_reservation_never_refunds_or_resets(self):
        import subprocess
        import sys
        code = ('import runpy,sys,os;api=runpy.run_path(sys.argv[1]);b=api["Budget"](sys.argv[2]);'
                'r=b.reserve_send(b.selection["sources"][0]["url"],"cross-process");'
                'print(r,flush=True);os._exit(23)')
        result = subprocess.run([sys.executable, '-I', '-c', code, str(DRIVER), str(self.path)],
                                capture_output=True, env=self.api['scrub_environment']())
        self.assertEqual(result.returncode, 23, result.stderr.decode())
        budget = self.api['Budget'](self.path)
        self.assertEqual(budget.summary()['totals']['attempts'], 1)
        self.assertEqual(budget.summary()['totals']['received_bytes'], 67108864)
        self.assertEqual(budget.summary()['actual_sent_requests'], 0)
        second = subprocess.run([sys.executable, '-I', '-c', code, str(DRIVER), str(self.path)],
                                capture_output=True, env=self.api['scrub_environment']())
        self.assertEqual(second.returncode, 23, second.stderr.decode())
        self.assertEqual(budget.summary()['totals']['attempts'], 2)
        with self.assertRaises(self.api['AcceptanceLimit']):
            budget.reserve_send(self.selection['sources'][0]['url'], 'restart')

    def test_validation_failure_retains_full_reservation(self):
        budget = self.ledger()
        def invalid(*args): raise ValueError('invalid source')
        cli = SimpleNamespace(BoundedSender=object)
        collection, transform = SimpleNamespace(), SimpleNamespace()
        self.api['install_wrappers'](budget, cli, collection, transform, invalid)
        with self.assertRaisesRegex(ValueError, 'invalid source'):
            collection.validate_envelope(None, None, None)
        self.assertEqual(budget.summary()['totals']['expanded_bytes'], 536870912)

    def test_completed_checked_result_requires_exact_streams_and_drain(self):
        from support_workflows import CommandHarness, simple_pack
        root = self.root / 'checked'
        root.mkdir()
        pack = simple_pack(root / 'pack')
        harness = CommandHarness(root, pack)
        self.addCleanup(harness.close)
        code, message = harness.invoke('discover', ['--mode', 'quarterly', '--discovery-id', 'checked'])
        self.assertEqual(code, 0)
        # Closed external call schema is tested separately. Here the real durable
        # fixture result is the fake process boundary's authority, never stdout.
        call = {'argv': harness.calls[-1]['argv'], 'config_sha256': harness.settings.config_sha256}
        execution = {'returncode': code, 'stdout': self.api['canonical'](message) + b'\n', 'drained': True}
        result, reference = self.api['checked_result'](call, execution, harness.objects)
        self.assertEqual(reference, message['result_ref'])
        for change in ({'stdout': b'{}\n'}, {'returncode': 9}, {'drained': False}):
            with self.assertRaisesRegex(ValueError, 'exit/stdout/drain'):
                self.api['checked_result'](call, {**execution, **change}, harness.objects)


    def test_discovery_rechecks_changed_pending_scope_before_dispatch(self):
        from unittest.mock import patch
        engine = self.api['AcceptanceRun'](self.path, self.selection, {})
        scope = copy.deepcopy(self.selection['inventory'])
        scope['daily_listing_urls'].append(self.api['BASE'] + 'daily-index/2025/QTR1/index.json')
        launched = []
        engine.invoke = lambda *args, **kwargs: launched.append(True)
        with patch.dict(self.api['AcceptanceRun'].discover.__globals__, {'inventory': lambda *args: scope}):
            with self.assertRaisesRegex(ValueError, 'scope changed'):
                engine.discover('daily')
        self.assertFalse(launched)

    def test_process_timeout_never_claims_positive_drain(self):
        import sys
        selected = copy.deepcopy(self.selection)
        selected['window']['deadline_utc'] = (datetime.now(timezone.utc) + timedelta(seconds=0.1)).isoformat()
        result = self.api['supervise']([sys.executable, '-I', '-c', 'import time;time.sleep(20)'], selected)
        self.assertFalse(result['drained'])
        self.assertLess(result['returncode'], 0)


    def test_wrapper_records_exact_production_request_identity_and_ordinal(self):
        budget = self.ledger()
        class Sender:
            def __init__(self, *args): pass
            def send(self, *args, **kwargs): raise RuntimeError('permit expired before HTTP')
        identity = lambda *args: {'request_id': 'production-permit-id', 'command_key': 'production-attempt-key', 'ordinal': 3}
        wrapped = self.api['budget_sender'](Sender, budget, identity)
        with self.assertRaisesRegex(RuntimeError, 'permit expired'):
            wrapped(None, None).send(self.selection['sources'][0]['url'], None, None, cancellation=None)
        request = budget.summary()['requests'][0]
        self.assertEqual(request['request_id'], 'production-permit-id')
        self.assertEqual(request['command_key'], 'production-attempt-key')
        self.assertEqual(request['ordinal'], 3)
        self.assertEqual(budget.summary()['totals']['attempts'], 1)
        self.assertEqual(budget.summary()['actual_sent_requests'], 0)


    def test_production_identity_reads_real_durable_transport_admission(self):
        from support import fixture_settings, fixture_context
        from sec_edgar_ingest.storage import open_stores
        from sec_edgar_ingest.state import AcquisitionState, attempt_key
        settings = fixture_settings(root=self.root / 'identity')
        context = fixture_context(settings=settings)
        opened = open_stores(settings)
        for resource in opened:
            if hasattr(resource, 'close'): self.addCleanup(resource.close)
        url = self.selection['sources'][0]['url']
        AcquisitionState(opened[0]).begin_request(context, url, self.selection['sources'][0]['source_id'], 'real-request-id', 1)
        identity = self.api['production_request_identity'](url, context, SimpleNamespace(request_id='real-request-id'))
        self.assertEqual(identity, {'request_id': 'real-request-id', 'command_key': attempt_key(context), 'ordinal': 1})
        with self.assertRaisesRegex(ValueError, 'exact production'):
            self.api['production_request_identity'](url, context, SimpleNamespace(request_id='substituted'))

    def test_overall_watchdog_interrupts_direct_blocking_capture_in_c(self):
        import ctypes
        import time
        from unittest.mock import patch
        selected = copy.deepcopy(self.selection)
        deadline = datetime.now(timezone.utc) + timedelta(seconds=0.1)
        selected['window'] = {'started_utc': (deadline - timedelta(seconds=900)).isoformat(), 'deadline_utc': deadline.isoformat()}
        engine = SimpleNamespace(budget=SimpleNamespace(selection_sha256='a' * 64,
            summary=lambda: {'actual_sent_requests': 0, 'reservations': [], 'totals': {}}),
            reuse=[], replays=[], reads=[], results=[], acquisitions=[], parents=[])
        marker = self.root / 'capture-finished'
        def blocked_capture(engine):
            ctypes.PyDLL(None).usleep(750000)
            marker.write_text('late capture finished')
        scope = self.selection['inventory']
        import sys
        code = 'import ctypes,pathlib;ctypes.PyDLL(None).usleep(750000);pathlib.Path(' + repr(str(marker)) + ').write_text("late capture finished")'
        updates = {'inventory': lambda *args: scope, 'AcceptanceRun': lambda *args: engine, 'execute_case': blocked_capture,
                   'worker_argv': lambda *args: [sys.executable, '-I', '-c', code]}
        started = time.monotonic()
        with patch.dict(self.api['run_acceptance'].__globals__, updates):
            result = self.api['run_acceptance'](self.path, selected, {})
        self.assertEqual(result, self.api['LIMIT_EXIT'])
        self.assertLess(time.monotonic() - started, 0.5, 'overall bound only detected after blocking C capture returned')
        self.assertFalse(marker.exists(), 'blocked capture completed past the immutable boundary')
        receipts = list((self.root / 'workers').glob('*/watchdog.json'))
        self.assertEqual(len(receipts), 1)
        receipt = self.api['read_json'](receipts[0])
        self.assertFalse(receipt['drained'])
        self.assertEqual(receipt['outcome'], 'acceptance_limit')

    def test_verifier_rejects_report_only_pass_and_omitted_evidence(self):
        from unittest.mock import patch
        budget = self.ledger()
        dummy_read = {'quarter': '1999Q1', 'generation_id': 'e' * 64, 'rows': 1, 'validated': True}
        capture = {'quarter': '1999Q1', 'generation_id': 'e' * 64,
            'manifest_ref': 'etl/sec/1999Q1/manifest.json', 'manifest_sha256': 'f' * 64, 'manifest_bytes': 1}
        captures = self.root / 'captures'
        captures.mkdir()
        (captures / ('1999Q1-' + 'e' * 64 + '.json')).write_bytes(self.api['canonical'](capture))
        proof = {'genuine_native': True, 'persistence': True, 'restart_reuse': True, 'exact_replay': True,
                 'bounded': True, 'published_reads': [dummy_read]}
        report = {'selection_sha256': self.api['digest'](self.path.read_bytes()), 'release_id': self.selection['release_id'],
                  'commands': [], 'proof': proof, 'status': {'status': 'pass', 'reasons': []},
                  'budget': budget.summary(), 'ended_utc': datetime.now(timezone.utc).isoformat()}
        path = self.root / 'run-forged.json'
        for variant in ('omitted-replay', 'omitted-reuse', 'missing-failed-launch', 'inconsistent-budget', 'unrelated-capture'):
            altered = copy.deepcopy(report)
            if variant == 'inconsistent-budget': altered['budget']['totals']['attempts'] = 99
            if variant == 'missing-failed-launch':
                dispatches = self.root / 'dispatches'
                dispatches.mkdir(exist_ok=True)
                (dispatches / 'missing.json').write_text('{}')
            path.write_bytes(self.api['canonical'](altered))
            with self.subTest(variant=variant), patch('sec_edgar_ingest.storage.open_stores', return_value=(None, None, None)), \
                    patch.dict(self.api['verify_acceptance'].__globals__, {'validate_read': lambda *args: dummy_read}):
                try:
                    result = self.api['verify_acceptance'](self.path, self.selection, {'daily': None})
                except (ValueError, OSError):
                    continue
                self.assertNotEqual(result, 0, 'verifier accepted report claims without selected acquisition/replay/reuse evidence')

    def test_ledger_verifier_reconciles_crash_charge_refund_and_transport_hashes(self):
        import sqlite3
        budget = self.ledger()
        url = self.selection['sources'][0]['url']
        rid = budget.reserve_send(url, 'actual-attempt', request_id='actual-request', ordinal=1)
        row = SimpleNamespace(value={'request_id': 'actual-request'}, to_mapping=lambda: {'value': {
            'request_id': 'actual-request', 'attempt_key': 'actual-attempt', 'url': url, 'ordinal': 1}})
        store = SimpleNamespace(scan=lambda *args: [row])
        summary, admissions = self.api['inspect_budget'](self.path, self.selection, store)
        self.assertEqual(summary['totals']['received_bytes'], 67108864)
        self.assertFalse(admissions[0]['socket_started'])
        with sqlite3.connect(budget.path) as db:
            db.execute("UPDATE totals SET charged=0 WHERE kind='received_bytes'")
        db.close()
        with self.assertRaisesRegex(ValueError, 'conservative reservations'):
            self.api['inspect_budget'](self.path, self.selection, store)
        with sqlite3.connect(budget.path) as db:
            db.execute("UPDATE totals SET charged=67108864 WHERE kind='received_bytes'")
        db.close()
        spool = self.root / 'fake-receipt'
        spool.mkdir()
        (spool / 'body').write_bytes(b'abc')
        (spool / 'receipt.json').write_text(json.dumps({'complete': True, 'unsafe': False, 'error': None}))
        (spool / 'transport.jsonl').write_text(json.dumps({'event': 'socket-start',
            'utc': datetime.now(timezone.utc).isoformat()}) + '\n')
        budget.retain_transport(rid, SimpleNamespace(temporary_path=spool / 'body', complete=True, byte_count=3), confirmed=True)
        budget.settle(rid, 3)
        summary, admissions = self.api['inspect_budget'](self.path, self.selection, store)
        self.assertEqual(summary, budget.summary())
        self.assertEqual(admissions[0]['sha256'], self.api['digest'](b'abc'))
        (self.root / 'transports' / rid / 'body').write_bytes(b'xyz')
        with self.assertRaisesRegex(ValueError, 'hash/length'):
            self.api['inspect_budget'](self.path, self.selection, store)

    def test_ledger_verifier_refuses_unconfirmed_recovery_refund(self):
        budget = self.ledger()
        url = self.selection['sources'][0]['url']
        rid = budget.reserve_send(url, 'actual-attempt', request_id='actual-request', ordinal=1)
        budget.settle(rid, 0)
        row = SimpleNamespace(value={'request_id': 'actual-request'}, to_mapping=lambda: {'value': {
            'request_id': 'actual-request', 'attempt_key': 'actual-attempt', 'url': url, 'ordinal': 1}})
        store = SimpleNamespace(scan=lambda *args: [row])
        with self.assertRaisesRegex(ValueError, 'refund lacks complete'):
            self.api['inspect_budget'](self.path, self.selection, store)

    def test_failed_limited_launch_is_inventoried_and_cannot_be_removed(self):
        import shutil
        call_path = self.root / 'commands/failure/attempt-000/call.json'
        public = ['discover', '--config', self.selection['configs']['quarterly']['path'],
            '--run-id', 'r', '--execution-id', 'e', '--attempt-id', 'failure',
            '--deadline', self.selection['window']['deadline_utc'], '--mode', 'quarterly', '--discovery-id', 'd']
        call = self.api['make_call'](self.selection, self.path, public)
        self.api['write_once'](call_path, self.api['canonical'](call))
        launch = call_path.parent / 'launches/launch-negative'
        argv = self.api['child_argv'](self.selection, self.path, call_path)
        dispatch = {'format_version': 'sec-local-sec-dispatch-v1', 'selection_sha256': self.api['digest'](self.path.read_bytes()),
            'call_path': str(call_path), 'call_sha256': self.api['digest'](call_path.read_bytes()),
            'launch_path': str(launch), 'argv': argv, 'dispatched_utc': datetime.now(timezone.utc).isoformat()}
        for path in (launch / 'dispatch.json', self.root / 'dispatches/negative.json'):
            self.api['write_once'](path, self.api['canonical'](dispatch))
        stdout, stderr = b'', b'acceptance limit refused before send\n'
        execution = {'argv': argv, 'pid': 12345, 'returncode': 12, 'drained': True,
            'stdout_path': str(launch / 'stdout'), 'stderr_path': str(launch / 'stderr'),
            'stdout_sha256': self.api['digest'](stdout), 'stderr_sha256': self.api['digest'](stderr)}
        for path, body in [(launch / 'started.json', self.api['canonical']({'pid': 12345})),
                (launch / 'stdout', stdout), (launch / 'stderr', stderr),
                (launch / 'execution.json', self.api['canonical'](execution)),
                (call_path.parent / 'execution.json', self.api['canonical'](execution))]:
            self.api['write_once'](path, body)
        def absent(ref): raise FileNotFoundError(ref)
        records, launches = self.api['inspect_commands'](self.path, self.selection, SimpleNamespace(read=absent))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['returncode'], 12)
        self.assertIsNone(records[0]['result_ref'])
        self.assertEqual(launches, [])
        shutil.rmtree(launch)
        with self.assertRaisesRegex(ValueError, 'including failed launches'):
            self.api['inspect_commands'](self.path, self.selection, SimpleNamespace(read=absent))


    def test_adjudication_validates_exact_archived_historical_harness(self):
        path = PROJECT / 'scripts/verify-sec-native-adjudication.py'
        self.assertTrue(path.exists(), 'missing separately versioned offline-only adjudicator')
        api = runpy.run_path(str(path))
        archive = self.root / 'harness-original'
        archive.mkdir()
        for record in self.selection['harness'].values():
            (archive / Path(record['path']).name).write_bytes(Path(record['path']).read_bytes())
        original = copy.deepcopy(self.selection)
        historical = api['historical_selection'](self.selection)
        self.assertEqual(self.selection, original)
        for role, record in historical['harness'].items():
            self.assertEqual(Path(record['path']).parent, archive)
            self.assertEqual(record['sha256'], original['harness'][role]['sha256'])
        driver = archive / 'accept-sec-native.py'
        driver.write_bytes(driver.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'archived original harness'):
            api['historical_selection'](self.selection)

    def test_adjudication_keeps_original_incomplete_separate_from_corrected_status(self):
        path = PROJECT / 'scripts/verify-sec-native-adjudication.py'
        self.assertTrue(path.exists(), 'missing separately versioned offline-only adjudicator')
        api = runpy.run_path(str(path))
        original = {'genuine_native': False, 'persistence': False, 'restart_reuse': False,
            'exact_replay': False, 'bounded': True, 'published_reads': [], 'selected_native': [],
            'selected_acquired': ['a'], 'selected_reused': ['a'], 'selected_replayed': ['a']}
        corrected = {**original, 'genuine_native': True, 'persistence': True, 'restart_reuse': True,
            'exact_replay': True, 'selected_native': ['a'], 'published_reads': [{'rows': 1, 'validated': True}]}
        result = api['proof_delta'](original, corrected)
        self.assertEqual(result['original_status'], 'incomplete')
        self.assertEqual(result['corrected_status'], 'pass')
        self.assertEqual(original['selected_native'], [])
        with self.assertRaisesRegex(ValueError, 'outside runtime representation'):
            api['proof_delta'](original, {**corrected, 'bounded': False})


if __name__ == '__main__':
    unittest.main()
