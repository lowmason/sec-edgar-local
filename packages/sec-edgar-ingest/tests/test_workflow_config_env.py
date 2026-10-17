"""Workflow commands read their config from an environment variable and, on Azure, their execution ID."""
from network_guard import install
install()

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from support_azure import WORKER_CLIENT_ID, azure_settings
from support_workflows import CommandHarness, simple_pack
from sec_edgar_ingest.cli import main
from sec_edgar_ingest.models import canonical_json, to_mapping_value
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.storage.identity import EXECUTION_NAME_ENV, WORKER_CLIENT_ID_ENV

CONFIG_ENV = 'SEC_EDGAR_INGEST_CONFIG'


def run(argv, environ=None, remove=()):
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, environ or {}):
        for name in remove:
            os.environ.pop(name, None)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
    return code, (json.loads(stdout.getvalue()) if stdout.getvalue() else None), stderr.getvalue()


class LocalConfigEnvTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.h = CommandHarness(self.root, simple_pack(self.root / 'pack'))
        self.addCleanup(self.h.close)

    def argv(self, *source, execution=('--execution-id', 'manual')):
        return ['backfill', *source, '--run-id', 'env', *execution, '--attempt-id', 'a',
                '--deadline', self.h.deadline.isoformat(), '--state-dir', str(self.root), '--today', '2026-10-07',
                '--fixture-pack', str(self.h.pack)]

    def test_config_env_runs_the_same_settings_through_every_child(self):
        code, message, _ = run(self.argv('--config-env', CONFIG_ENV), {CONFIG_ENV: self.h.config.read_text()})
        self.assertEqual((code, message['outcome']), (0, 'success'))
        results = [json.loads(path.read_bytes()) for path in (self.h.objects.directory / 'runs').rglob('result.json')]
        self.assertGreater(len(results), 1)
        self.assertEqual({result['context']['config_sha256'] for result in results}, {self.h.settings.config_sha256})

    def test_exactly_one_config_source_is_accepted(self):
        for source in (('--config', str(self.h.config), '--config-env', CONFIG_ENV), ()):
            with self.subTest(source=source), self.assertRaises(SystemExit) as caught, \
                    contextlib.redirect_stderr(io.StringIO()):
                main(self.argv(*source))
            self.assertEqual(caught.exception.code, 2)

    def test_an_unusable_config_env_is_a_configuration_error_before_stores(self):
        cases = {'unset': (CONFIG_ENV, None), 'empty': (CONFIG_ENV, ''), 'not json': (CONFIG_ENV, '{'),
                 'bad name': ('lower-case', self.h.config.read_text())}
        for label, (name, value) in cases.items():
            environ = {} if value is None else {name: value}
            with self.subTest(label), \
                    patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')):
                code, message, _ = run(self.argv('--config-env', name), environ, remove=(CONFIG_ENV,) if value is None else ())
                self.assertEqual((code, message), (2, None))

    def test_local_workflows_still_require_an_execution_id(self):
        with patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')):
            code, message, events = run(self.argv('--config', str(self.h.config), execution=()))
        self.assertEqual((code, message), (2, None))
        self.assertIn('--execution-id', json.loads(events.splitlines()[-1])['error'])


class AzureWorkflowIdentityTests(unittest.TestCase):
    def setUp(self):
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=1800)).isoformat()
        self.argv = ['daily', '--config-env', CONFIG_ENV, '--run-id', 'pipeline-run', '--attempt-id', 'launch-1',
                     '--deadline', deadline]
        self.environ = {CONFIG_ENV: canonical_json(to_mapping_value(azure_settings().to_mapping())).decode(),
                        WORKER_CLIENT_ID_ENV: WORKER_CLIENT_ID, EXECUTION_NAME_ENV: 'sec-edgar-ingest-job-abc123'}

    def test_the_execution_id_comes_from_the_job_execution(self):
        frozen = []

        def freeze(context, intent, store, objects):
            frozen.append(context)
            raise Conflict('stop once the context is built')
        objects, store = Mock(), Mock()
        objects.read.side_effect = FileNotFoundError
        store.get.return_value = None
        with patch('sec_edgar_ingest.cli.open_stores', return_value=(store, objects, Mock())), \
                patch('sec_edgar_ingest.cli.freeze_workflow', side_effect=freeze):
            code, message, _ = run(self.argv, self.environ)
        self.assertEqual((code, message['outcome']), (9, 'state_conflict'))
        self.assertEqual((frozen[0].execution_id, frozen[0].attempt_id, frozen[0].config_sha256),
                         ('sec-edgar-ingest-job-abc123', 'launch-1', azure_settings().config_sha256))

    def test_azure_refuses_a_supplied_execution_id_and_missing_job_variables(self):
        cases = {'supplied execution id': (('--execution-id', 'manual'), ()),
                 'no execution name': ((), (EXECUTION_NAME_ENV,)),
                 'no worker client id': ((), (WORKER_CLIENT_ID_ENV,))}
        for label, (extra, remove) in cases.items():
            with self.subTest(label), \
                    patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')):
                code, message, events = run([*self.argv, *extra], self.environ, remove)
                self.assertEqual((code, message), (2, None))
                self.assertEqual(json.loads(events.splitlines()[-1])['outcome'], 'configuration')


if __name__ == '__main__':
    unittest.main()
