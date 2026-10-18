"""Local workflows require file configuration and explicit native correlation IDs."""
from network_guard import install
install()

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_workflows import CommandHarness, simple_pack
from sec_edgar_ingest.cli import main


class LocalConfigSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.h = CommandHarness(self.root, simple_pack(self.root / 'pack'))
        self.addCleanup(self.h.close)

    def argv(self):
        return ['backfill', '--config', str(self.h.config), '--run-id', 'explicit',
                '--execution-id', 'manual', '--attempt-id', 'a', '--deadline', self.h.deadline.isoformat(),
                '--today', '2026-10-07', '--fixture-pack', str(self.h.pack)]

    def test_file_settings_are_preserved_through_every_child(self):
        code, message = self.h.invoke('backfill')
        self.assertEqual((code, message['outcome']), (0, 'success'), self.h.calls[-1])
        results = [json.loads(path.read_bytes()) for path in (self.h.objects.directory / 'runs').rglob('result.json')]
        self.assertGreater(len(results), 1)
        self.assertEqual({result['context']['config_sha256'] for result in results}, {self.h.settings.config_sha256})
        self.assertEqual({result['context']['execution_id'] for result in results}, {'manual'})

    def test_environment_cannot_supply_missing_config_or_execution_id(self):
        for flag in ('--config', '--execution-id'):
            args = self.argv()
            index = args.index(flag)
            del args[index:index + 2]
            with self.subTest(flag=flag), patch.dict(os.environ, {
                    'SEC_EDGAR_INGEST_CONFIG': self.h.config.read_text(),
                    'CONTAINER_APP_JOB_EXECUTION_NAME': 'cloud-job'}), \
                    patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')) as opened, \
                    self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
                main(args)
            self.assertEqual(caught.exception.code, 2)
            opened.assert_not_called()

    def test_removed_config_and_provider_options_are_unrecognized_before_stores(self):
        for flag in ('--config-env', '--state-dir', '--credential', '--worker-client-id', '--tenant-id'):
            with self.subTest(flag=flag), \
                    patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')) as opened, \
                    self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
                main([*self.argv(), flag, 'unsupported'])
            self.assertEqual(caught.exception.code, 2)
            opened.assert_not_called()
