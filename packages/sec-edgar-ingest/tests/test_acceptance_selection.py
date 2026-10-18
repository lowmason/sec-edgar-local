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


if __name__ == '__main__':
    unittest.main()
