"""Checked stage process, provenance and conservative authority contracts."""
from network_guard import install
install()

import os
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_checked import workflow_fixture
from support_process import CheckedRunner, write_import_sentinel
from sec_edgar_ingest.workflows.checked import Dispatcher


class NativeDispatchTests(unittest.TestCase):
    def test_fixture_stage_never_calls_cli_in_parent_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings, context, pack, store, objects = workflow_fixture(root)
            self.addCleanup(store.close)
            dispatcher = Dispatcher(context, settings, pack, root, store, objects, child_runner=CheckedRunner())
            with patch('sec_edgar_ingest.cli.main', side_effect=AssertionError(
                    'checked stage executed in parent PID ' + str(os.getpid()))):
                child = dispatcher.execute('discover', 'isolated-discover', settings,
                    ('--mode', 'quarterly', '--discovery-id', 'isolated-session'))
            self.assertEqual(child.result.outcome, 'success')

    def fixture(self, root, runner):
        settings, context, pack, store, objects = workflow_fixture(root)
        self.addCleanup(store.close)
        return settings, store, objects, Dispatcher(context, settings, pack, root,
                                                   store, objects, child_runner=runner)

    def test_finished_call_replay_does_not_launch_again(self):
        launches = []
        actual = CheckedRunner()
        def once(*args, **kwargs):
            launches.append(True)
            if len(launches) > 1:
                raise AssertionError('finished child relaunched')
            return actual(*args, **kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            settings, store, objects, dispatcher = self.fixture(Path(temporary), once)
            flags = ('--mode', 'quarterly', '--discovery-id', 'replay-session')
            child = dispatcher.execute('discover', 'replay', settings, flags)
            self.assertEqual(dispatcher.execute('discover', 'replay', settings, flags), child)
            self.assertEqual(len(launches), 1)

    def test_ambiguous_child_crash_retains_call_and_never_relaunches(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        launches = []
        def crash(*args, **kwargs):
            launches.append(True)
            raise RuntimeError('stage supervisor crashed after launch')
        with tempfile.TemporaryDirectory() as temporary:
            settings, store, objects, dispatcher = self.fixture(Path(temporary), crash)
            flags = ('--mode', 'quarterly', '--discovery-id', 'crash-session')
            with self.assertRaisesRegex(RuntimeError, 'supervisor crashed'):
                dispatcher.execute('discover', 'crash', settings, flags)
            self.assertEqual(len(tuple(store.scan('WorkflowChildCall', {}))), 1)
            with self.assertRaisesRegex(Conflict, 'ambiguous'):
                dispatcher.execute('discover', 'crash', settings, flags)
            self.assertEqual(len(launches), 1)

    def test_stdout_alone_and_uncertain_drain_never_authorize_success(self):
        from sec_edgar_ingest.runtime import ChildExit
        from sec_edgar_ingest.storage.contracts import Conflict
        variants = (ChildExit(0, b'{"outcome":"success","result_ref":"invented"}', b'', True),
                    ChildExit(0, b'{}', b'', False), ChildExit(-9, b'', b'crashed', True))
        for index, response in enumerate(variants):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                launches = []
                def runner(*args, **kwargs):
                    launches.append(True)
                    return response
                settings, store, objects, dispatcher = self.fixture(Path(temporary), runner)
                flags = ('--mode', 'quarterly', '--discovery-id', 'missing-session')
                with self.assertRaises(Conflict):
                    dispatcher.execute('discover', 'missing', settings, flags)
                with self.assertRaises(Conflict):
                    dispatcher.execute('discover', 'missing', settings, flags)
                self.assertEqual(len(launches), 1)

    def test_actual_exit_and_exact_stdout_must_match_durable_result(self):
        from dataclasses import replace
        from sec_edgar_ingest.storage.contracts import Conflict
        actual = CheckedRunner()
        variants = (lambda value: replace(value, stdout=b'not-json'),
                    lambda value: replace(value, returncode=9),
                    lambda value: replace(value, stdout=value.stdout + value.stdout),
                    lambda value: replace(value, stdout=b'{"outcome":"success","result_ref":"wrong"}'),
                    lambda value: replace(value, stdout=value.stdout[:-2] + b',"extra":true}\n'))
        for index, change in enumerate(variants):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                launches = []
                def runner(*args, **kwargs):
                    launches.append(True)
                    return change(actual(*args, **kwargs))
                settings, store, objects, dispatcher = self.fixture(Path(temporary), runner)
                flags = ('--mode', 'quarterly', '--discovery-id', 'mismatch-session')
                with self.assertRaises(Conflict):
                    dispatcher.execute('discover', 'mismatch', settings, flags)
                with self.assertRaises(Conflict):
                    dispatcher.execute('discover', 'mismatch', settings, flags)
                self.assertEqual(len(launches), 1)

    def test_replayed_execution_receipt_must_still_match_checked_result(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as temporary:
            settings, store, objects, dispatcher = self.fixture(Path(temporary), CheckedRunner())
            flags = ('--mode', 'quarterly', '--discovery-id', 'receipt-session')
            dispatcher.execute('discover', 'receipt', settings, flags)
            record = next(iter(store.scan('WorkflowChildExecution', {})))
            changed = record.to_mapping()['value']
            changed['returncode'] = 9
            from sec_edgar_ingest.workflows.checked import call_key
            call = next(iter(store.scan('WorkflowChildCall', {}))).to_mapping()['value']
            store.replace('WorkflowChildExecution', call_key(call), changed, record.version)
            with self.assertRaisesRegex(Conflict, 'execution receipt'):
                dispatcher.execute('discover', 'receipt', settings, flags)

    def test_invalid_execution_index_refuses_without_mutating_any_existing_authority(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        from sec_edgar_ingest.workflows.checked import call_key
        with tempfile.TemporaryDirectory() as temporary:
            settings, store, objects, dispatcher = self.fixture(Path(temporary), CheckedRunner())
            flags = ('--mode', 'quarterly', '--discovery-id', 'strict-execution-session')
            child = dispatcher.execute('discover', 'strict-execution', settings, flags)
            key = call_key(child.call)
            row = store.get('WorkflowChildExecution', key)
            altered = row.to_mapping()['value']
            altered['unexpected'] = True
            store.replace('WorkflowChildExecution', key, altered, row.version)
            before = store.get('WorkflowChildExecution', key).to_mapping()
            with self.assertRaisesRegex(Conflict, 'execution receipt'):
                dispatcher.execute('discover', 'strict-execution', settings, flags)
            self.assertEqual(store.get('WorkflowChildExecution', key).to_mapping(), before)

    def test_replay_refuses_changed_archived_execution_config(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings, store, objects, dispatcher = self.fixture(root, CheckedRunner())
            flags = ('--mode', 'quarterly', '--discovery-id', 'config-authority')
            dispatcher.execute('discover', 'config-authority', settings, flags)
            snapshot = next((root / '.fixture-state/objects').rglob('executions/0/config.json'))
            snapshot.write_bytes(snapshot.read_bytes() + b' ')
            before = tuple(row.to_mapping() for row in store.scan('WorkflowChildExecution', {}))
            with self.assertRaisesRegex(Conflict, 'execution receipt'):
                dispatcher.execute('discover', 'config-authority', settings, flags)
            self.assertEqual(tuple(row.to_mapping() for row in store.scan('WorkflowChildExecution', {})), before)


class PinnedNativeDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support_release import proof_releases
        project = Path(__file__).resolve().parents[3]
        cls.a, cls.b = proof_releases(project, project / 'releases/artifact-cache')

    def test_origin_collection_saved_repair_and_new_processing_select_exact_installed_release(self):
        import json
        from dataclasses import replace
        from sec_edgar_ingest.config import Settings, pin_context
        from sec_edgar_ingest.runtime import configured_descriptor
        from sec_edgar_ingest.workflows.checked import ChildUnfinished
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings, context, pack, store, objects = workflow_fixture(root)
            self.addCleanup(store.close)
            def configured(release):
                value = settings.to_mapping()
                value['runtime'] = {'kind': 'native', 'release_manifest': str(release.directory / 'release.json')}
                return Settings.from_mapping(value)
            a, b = configured(self.a), configured(self.b)
            def parent(selected, attempt):
                value = replace(context, attempt_id=attempt, runtime=configured_descriptor(selected),
                    config_sha256=selected.config_sha256, effective_config={}, pinned_on=None)
                return pin_context(selected, value, context.pinned_on)[0]
            log = root / 'pids.jsonl'
            sentinel = root / 'sentinel.py'
            sentinel_log = root / 'sentinel.jsonl'
            write_import_sentinel(sentinel, sentinel_log)
            runner = CheckedRunner(pid_log=log, sentinel=sentinel)
            first = Dispatcher(parent(a, 'release-a'), a, pack, root, store, objects, child_runner=runner)
            current = Dispatcher(parent(b, 'release-b'), b, pack, root, store, objects, child_runner=runner)
            found = first.execute('discover', 'discover-a', a,
                ('--mode', 'quarterly', '--discovery-id', 'native-origin'))
            collected = current.execute('collect', 'collect-a', a,
                ('--workset', found.result.source_workset_ref))
            transformed_a = first.execute('transform', 'transform-a', a,
                ('--workset', collected.result.snapshot_workset_ref))
            marker = root / 'ordinary-failure.json'
            first.child_runner = CheckedRunner(fault={'point': 'publication.record_failure', 'action': 'raise',
                'marker': str(marker), 'ack': str(marker.with_suffix('.ack'))}, pid_log=log, sentinel=sentinel)
            with self.assertRaises(ChildUnfinished):
                first.execute('publish', 'publish-a', a,
                    ('--workset', transformed_a.result.transformed_workset_ref))
            repaired = current.execute('publish', 'repair-a', a,
                ('--workset', transformed_a.result.transformed_workset_ref))
            transformed = current.execute('transform', 'transform-b', b,
                ('--workset', collected.result.snapshot_workset_ref))
            published = current.execute('publish', 'publish-b', b,
                ('--workset', transformed.result.transformed_workset_ref))
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual([record['python'] for record in records],
                             [str(self.a.python)] * 5 + [str(self.b.python)] * 2)
            self.assertTrue(all(record['pid'] != os.getpid() for record in records))
            self.assertEqual(collected.result.context.runtime, found.result.context.runtime)
            self.assertEqual(repaired.result.context.runtime, found.result.context.runtime)
            self.assertEqual(published.result.context.runtime, transformed.result.context.runtime)
            self.assertNotEqual(published.result.context.runtime, repaired.result.context.runtime)
            self.assertEqual(len(sentinel_log.read_text().splitlines()), 7)
            before = tuple(row.to_mapping() for row in store.scan('WorkflowChildCall', {}))
            original = self.a.directory
            moved = original.with_name(original.name + '-missing')
            original.rename(moved)
            try:
                with self.assertRaises(FileNotFoundError):
                    current.execute('collect', 'missing-a', a,
                        ('--workset', found.result.source_workset_ref))
            finally:
                moved.rename(original)
            self.assertEqual(tuple(row.to_mapping() for row in store.scan('WorkflowChildCall', {})), before)

    def test_installed_parent_supervises_same_release_stages_in_distinct_processes(self):
        import json
        from sec_edgar_ingest.config import Settings
        from sec_edgar_ingest.models import canonical_json, to_mapping_value
        from sec_edgar_ingest.runtime import native_python_argv, isolated_environment
        for release in (self.a, self.b):
            with self.subTest(release=release.release_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                settings, context, pack, store, objects = workflow_fixture(root)
                store.close()
                value = settings.to_mapping()
                value['runtime'] = {'kind': 'native', 'release_manifest': str(release.directory / 'release.json')}
                selected = Settings.from_mapping(value)
                config = root / 'native-config.json'
                config.write_bytes(canonical_json(to_mapping_value(selected.to_mapping())))
                log = root / 'native-pids.jsonl'
                sentinel_log = root / 'native-sentinel.jsonl'
                sentinel = write_import_sentinel(root / 'network_import_sentinel.py', sentinel_log)
                audit_log = root / 'checkout-sentinel.jsonl'
                with sentinel.open('a') as stream:
                    stream.write("from network_guard import checkout_evidence\n"
                        + "with Path(" + repr(str(audit_log)) + ").open('a') as stream: stream.write(json.dumps(checkout_evidence())+'\\n')\n")
                runner = CheckedRunner(pid_log=log, sentinel=sentinel,
                    policy={'version': 'sec-checkout-policy-v1', 'releases': [str(release.directory)]})
                argv = [*native_python_argv(release.python), '-m', 'sec_edgar_ingest', 'backfill',
                    '--config', str(config), '--run-id', 'installed-parent', '--execution-id', 'manual',
                    '--attempt-id', 'a', '--deadline', context.deadline.isoformat(),
                    '--fixture-pack', str(pack), '--today', context.pinned_on.isoformat()]
                with contextlib.chdir(root):
                    result = runner(release.python, argv, deadline=context.deadline, environ=isolated_environment())
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertTrue(result.drained)
                records = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertGreaterEqual(len(records), 5, 'installed parent must supervise and guard every stage')
                self.assertTrue(all(record['python'] == str(release.python) for record in records))
                self.assertEqual(len({record['pid'] for record in records}), len(records))
                self.assertEqual(len(sentinel_log.read_text().splitlines()), len(records))
                audits = [json.loads(line) for line in audit_log.read_text().splitlines()]
                self.assertEqual([item['pid'] for item in audits], [item['pid'] for item in records])
                self.assertTrue(all(not item['application_imported'] for item in audits), audits)
                self.assertTrue(all(item['denied'] == [True] * 6 for item in audits), audits)
                self.assertTrue(all(item['policy']['releases'] == [str(release.directory)] for item in audits))
                destination = os.environ.get('SEC_EDGAR_TASK14_NATIVE_EVIDENCE')
                if destination:
                    import shutil
                    shutil.copytree(root, Path(destination) / release.release_id)


class SupervisedProcessTests(unittest.TestCase):
    def test_environment_is_scrubbed_and_output_is_bytes(self):
        import json
        import sys
        from datetime import datetime, timedelta, timezone
        from sec_edgar_ingest.runtime import run_child, native_python_argv
        python = Path(sys.executable).absolute()
        result = run_child(python, [*native_python_argv(python), '-c',
            'import os,json; print(json.dumps(dict(os.environ)))'],
            deadline=datetime.now(timezone.utc) + timedelta(seconds=10),
            environ={**os.environ, 'PYTHONPATH': '/untrusted', 'PYTHONHOME': '/untrusted',
                     'PYTHONSTARTUP': '/untrusted', 'VIRTUAL_ENV': '/untrusted'})
        self.assertTrue(result.drained)
        self.assertEqual(result.returncode, 0)
        environment = json.loads(result.stdout)
        self.assertFalse(any(key.startswith('PYTHON') for key in environment))
        self.assertNotIn('VIRTUAL_ENV', environment)

    def test_deadline_terminates_entire_group_and_refuses_safe_drain_claim(self):
        import json
        import sys
        from datetime import datetime, timedelta, timezone
        from sec_edgar_ingest.runtime import run_child, native_python_argv
        python = Path(sys.executable).absolute()
        code = ('import subprocess,sys,time,os,json; '
                'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                'print(json.dumps({"pid":os.getpid(),"group":os.getpgrp(),"child":child.pid}),flush=True); '
                'time.sleep(60)')
        result = run_child(python, [*native_python_argv(python), '-c', code],
            deadline=datetime.now(timezone.utc) + timedelta(seconds=0.5), environ=os.environ)
        self.assertFalse(result.drained)
        self.assertLess(result.returncode, 0)
        proof = json.loads(result.stdout)
        self.assertNotEqual(proof['group'], os.getpgrp())
        self.assertEqual(proof['pid'], proof['group'])
        with self.assertRaises(ProcessLookupError):
            os.kill(proof['child'], 0)

    def test_output_overflow_is_bounded_and_never_safe_completion(self):
        import sys
        from datetime import datetime, timedelta, timezone
        from sec_edgar_ingest.runtime import run_child, native_python_argv, CHILD_OUTPUT_LIMIT
        python = Path(sys.executable).absolute()
        result = run_child(python, [*native_python_argv(python), '-c',
            'import os; os.write(1,b"x"*2097152)'],
            deadline=datetime.now(timezone.utc) + timedelta(seconds=10), environ=os.environ)
        self.assertFalse(result.drained)
        self.assertEqual(len(result.stdout), CHILD_OUTPUT_LIMIT)

    def test_overflow_survives_a_parent_that_reads_slowly(self):
        # Reproduces the macOS race: a late SIGTERM reaches a dead child group and gets EPERM.
        import sys
        import time
        from datetime import datetime, timedelta, timezone
        from sec_edgar_ingest.runtime import run_child, native_python_argv, CHILD_OUTPUT_LIMIT
        python = Path(sys.executable).absolute()
        real_read = os.read
        total = 0

        def slow_read(fd, count):
            nonlocal total
            data = real_read(fd, count)
            total += len(data)
            if total > CHILD_OUTPUT_LIMIT:
                time.sleep(0.05)
            return data

        with patch('os.read', slow_read):
            result = run_child(python, [*native_python_argv(python), '-c',
                'import os; os.write(1,b"x"*2097152)'],
                deadline=datetime.now(timezone.utc) + timedelta(seconds=10), environ=os.environ)
        self.assertFalse(result.drained)
        self.assertEqual(len(result.stdout), CHILD_OUTPUT_LIMIT)
