from network_guard import install
install()
from sec_edgar_ingest.models import to_mapping_value
import contextlib, io, json, tempfile, time, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from support import fixture_settings
from support_workflows import CommandHarness, simple_pack
from sec_edgar_ingest.cli import main
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows.results import read_workflow_result


def cli_call(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()


class WorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.h = CommandHarness(self.root, simple_pack(self.root / 'pack'))
        self.addCleanup(self.h.close)

    def report(self, message):
        return read_workflow_result(message['result_ref'], self.h.store, self.h.objects)

    def test_public_commands_inclusive_baseline_and_daily_reader(self):
        code, message = self.h.invoke('backfill', run='baseline')
        self.assertEqual(code, 0, self.h.calls[-1])
        report = self.report(message)
        self.assertEqual(report.requested_quarters, ('2026Q3', '2026Q4'))
        self.assertEqual(report.counts['complete_sources'], 2)
        self.assertEqual(report.counts['quarantined_sources'], 0)
        self.assertEqual(len(self.h.capture('2026Q3')[1]), 1)
        self.assertEqual(len(self.h.capture('2026Q4')[1]), 1)
        code, daily = self.h.invoke('daily', run='overlap')
        self.assertEqual(code, 0, self.h.calls[-1])
        self.assertEqual(self.report(daily).counts['complete_sources'], 1)
        self.assertEqual(len(self.h.capture('2026Q4')[1]), 1)

    def test_live_workflow_without_an_admitted_reserve_refuses_before_any_store(self):
        from support import local_config_mapping
        from sec_edgar_ingest.config import DISPATCH_RESERVE_FLOOR_SECONDS as floor
        value = local_config_mapping()
        value.pop('fixture', None)
        value['acquisition'] = {'mode': 'live'}
        value['etl']['parser_version'] = 'sec-index-parser-v1'
        value['runtime'] = {'kind': 'native', 'release_manifest': '/missing/releases/sha256=' + 'a' * 64 + '/release.json'}
        value['storage']['root'] = str(self.root / 'live-data')
        value['logging']['root'] = str(self.root / 'live-logs')
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat()
        config = self.root / 'live.json'
        argv = ['backfill', '--config', str(config), '--run-id', 'live', '--execution-id', 'manual',
                '--attempt-id', 'a', '--deadline', deadline]
        for execution, refused in (({}, True), ({'dispatch_reserve_seconds': floor - 1}, True),
                                   ({'dispatch_reserve_seconds': 3600}, True),
                                   ({'dispatch_reserve_seconds': floor}, False)):
            with self.subTest(execution=execution):
                value['execution'] = {'max_run_seconds': 3600, **execution}
                config.write_text(json.dumps(value))
                code, message, err = cli_call(argv)
                self.assertEqual(code, 2)
                self.assertIsNone(message)
                self.assertEqual(json.loads(err)['outcome'], 'configuration')
                # An admitted reserve passes on to preflight_current. This test interpreter is not isolated, so the
                # preflight refuses on interpreter isolation before it reads the release manifest.
                self.assertEqual('dispatch_reserve_seconds' in err, refused, err)
                self.assertFalse((self.root / 'live-data').exists())

    def test_completed_exact_replay_after_deadline_constructs_no_dispatcher(self):
        code, message = self.h.invoke('backfill')
        self.assertEqual(code, 0)
        saved = self.report(message)
        body = self.h.objects.read(message['result_ref'])
        cursors = tuple(r.to_mapping() for r in self.h.store.scan('FixtureResponseCursor', {}))
        with patch('sec_edgar_ingest.cli.Clock.now', return_value=saved.context.deadline + timedelta(days=1)), \
             patch('sec_edgar_ingest.cli.WorkflowDispatcher', side_effect=AssertionError('replay dispatched')):
            code, replay, _ = cli_call(self.h.calls[0]['argv'])
        self.assertEqual((code, replay), (0, message))
        self.assertEqual(self.h.objects.read(message['result_ref']), body)
        self.assertEqual(tuple(r.to_mapping() for r in self.h.store.scan('FixtureResponseCursor', {})), cursors)

    def test_changed_exact_invocation_is_conflict_and_report_stays_immutable(self):
        self.h.invoke('backfill')
        argv = self.h.calls[0]['argv']
        original = self.h.objects.read(self.h.calls[0]['stdout']['result_ref'])
        for flag, value in (('--execution-id', 'other'), ('--today', '2026-10-08'),
                            ('--deadline', (self.h.deadline + timedelta(seconds=1)).isoformat())):
            changed = list(argv)
            changed[changed.index(flag) + 1] = value
            code, message, _ = cli_call(changed)
            self.assertEqual(code, 9, message)
            self.assertIsNone(message['result_ref'])
        self.assertEqual(self.h.objects.read(self.h.calls[0]['stdout']['result_ref']), original)

    def test_omitted_today_reopens_saved_pin_before_next_day_validation(self):
        self.h.settings = fixture_settings(root=self.root / '.fixture-state',
            backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
            etl={'parser_version': 'fixture-index-parser-v1'},
            fixture={'allow_clock_override': True, 'allow_deadline_override': True})
        self.h.config.write_bytes(canonical_json(to_mapping_value(self.h.settings.to_mapping())))
        self.h.invoke('backfill', run='template')
        argv = list(self.h.calls[-1]['argv'])
        argv[argv.index('--run-id') + 1] = 'implicit-date'
        index = argv.index('--today')
        del argv[index:index + 2]
        first = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        mono_origin = time.monotonic()
        # Keep wall and monotonic elapsed time aligned during real fixture pacing.
        with patch('sec_edgar_ingest.cli.Clock.now',
                   side_effect=lambda: first + timedelta(seconds=time.monotonic() - mono_origin)):
            code, message, _ = cli_call(argv)
        self.assertEqual(code, 0)
        saved = self.report(message)
        with patch('sec_edgar_ingest.cli.Clock.now', return_value=first + timedelta(days=1)), \
             patch('sec_edgar_ingest.cli.WorkflowDispatcher', side_effect=AssertionError('replay dispatched')):
            code, again, _ = cli_call(argv)
        self.assertEqual((code, again), (0, message))
        self.assertEqual(saved.context.pinned_on.isoformat(), '2026-10-07')

    def test_invalid_input_precedes_backend_construction_and_child_flags_stay_private(self):
        self.h.invoke('backfill')
        argv = list(self.h.calls[0]['argv'])
        argv[argv.index('--run-id') + 1] = '../escape'
        with patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('invalid input opened stores')):
            self.assertEqual(cli_call(argv)[0], 2)
        for flags in (('--force',), ('--refresh',), ('--workset', 'x'), ('--mode', 'daily')):
            with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
                main([*self.h.calls[0]['argv'], *flags])
            self.assertEqual(caught.exception.code, 2)

    def test_failure_closes_all_opened_resources_and_writes_no_report(self):
        import sec_edgar_ingest.cli as cli
        original, closed = cli.open_stores, []
        class ClosingProxy:
            def __init__(self, resource): self.resource = resource
            def __getattr__(self, name): return getattr(self.resource, name)
            def close(self):
                closed.append(type(self.resource).__name__)
                if hasattr(self.resource, 'close'): self.resource.close()
        def open_checked(*args, **kwargs):
            return tuple(ClosingProxy(r) for r in original(*args, **kwargs))
        with patch.object(cli, 'open_stores', side_effect=open_checked), \
             patch.object(cli, 'run_workflow', side_effect=Conflict('retained state conflict')):
            code, message = self.h.invoke('daily', run='conflict')
        self.assertEqual(code, 9)
        self.assertIsNone(message['result_ref'])
        self.assertEqual(len(closed), 3)
        with self.assertRaises(FileNotFoundError):
            self.h.objects.read('runs/sec/conflict/daily/a/result.json')

    def test_unprintable_exception_text_still_reports_structured_errors(self):
        import sec_edgar_ingest.cli as cli
        from sec_edgar_ingest.models import require_text
        for run, text in (('empty', ''), ('multiline', 'first line\nsecond line')):
            with self.subTest(run), patch.object(cli, 'run_workflow', side_effect=RuntimeError(text)):
                code, message = self.h.invoke('daily', run=run)
                self.assertEqual((code, message['outcome'], message['result_ref']), (9, 'internal_error', None))
                event = json.loads(self.h.calls[-1]['stderr'].splitlines()[-1])
                self.assertEqual((event['event'], event['fields']['error']['details']), ('command_error', {'type': 'RuntimeError'}))
                require_text(event['fields']['error']['message'], 'message')

    def test_unfinished_expired_attempt_requires_new_attempt(self):
        with patch('sec_edgar_ingest.cli.run_workflow', side_effect=Conflict('interrupted')):
            code, message = self.h.invoke('backfill', run='expired')
        self.assertEqual(code, 9)
        before = [row.to_mapping() for row in self.h.store.scan('WorkflowAttempt', {})]
        with patch('sec_edgar_ingest.cli.Clock.now', return_value=self.h.deadline + timedelta(days=1)), \
                patch('sec_edgar_ingest.cli.WorkflowDispatcher', side_effect=AssertionError('expired attempt dispatched')):
            code, message, _ = cli_call(self.h.calls[-1]['argv'])
        self.assertEqual(code, 2, message)
        self.assertIsNone(message['result_ref'])
        self.assertEqual([row.to_mapping() for row in self.h.store.scan('WorkflowAttempt', {})], before)

    def test_distant_new_deadline_refuses_before_store_construction(self):
        args = ['backfill', '--config', str(self.h.config), '--run-id', 'too-long',
                '--execution-id', 'e', '--attempt-id', 'a',
                '--deadline', (self.h.deadline + timedelta(hours=2)).isoformat(),
                '--fixture-pack', str(self.h.pack)]
        with patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')) as opened:
            code, message, errors = cli_call(args)
        self.assertEqual((code, message), (2, None), errors)
        opened.assert_not_called()
