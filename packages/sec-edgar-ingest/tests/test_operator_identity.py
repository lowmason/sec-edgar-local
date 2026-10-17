"""Azure operators are their signed-in principal; local operators name themselves; reads write nothing."""
from network_guard import install
install()

import contextlib
import json
import unittest
from unittest.mock import patch

from support_approval import GateFixture, operator_cli, tree_snapshot
from support_azure import OBJECT_ID, TENANT_ID, FailingCredential, FakeCredential, jwt, write_azure_config
from sec_edgar_ingest.storage import open_stores

PRINCIPAL = f'entra:{TENANT_ID}/{OBJECT_ID} lowell@example.com'


class OperatorIdentityTests(GateFixture):
    def setUp(self):
        super().setUp()
        self.base, self.revised, self.candidate = self.gated()
        self.local_config = self.write_config()
        self.azure_config = write_azure_config(self.root / 'azure.json')
        self.credential = FakeCredential(jwt(tid=TENANT_ID, oid=OBJECT_ID, upn='lowell@example.com'))

    def approve_argv(self, config, *extra):
        return ('approve', '--config', str(config), '--quarter', '2026Q4',
                '--generation', self.candidate.manifest.generation_id,
                '--quarterly-sha256', self.revised.snapshot.sha256, *extra)

    def rollback_argv(self, config, *extra):
        return ('rollback', '--config', str(config), '--quarter', '2026Q4',
                '--from-generation', self.candidate.manifest.generation_id,
                '--to-generation', self.base.generation_id, '--reason', 'bad correction', *extra)

    @contextlib.contextmanager
    def azure(self, credential=None):
        """Azure configuration and sign-in, with this fixture's local stores standing in for Azure's."""
        def local(*args, **kwargs):
            return open_stores(self.settings, base_path=self.root, access='operator')
        with patch('sec_edgar_ingest.storage.azure.operator_credential',
                   return_value=credential or self.credential), \
                patch('sec_edgar_ingest.cli.open_stores', side_effect=local) as opened:
            yield opened

    def assert_configuration(self, result):
        code, message, events = result
        self.assertEqual((code, message), (2, None))
        self.assertEqual(json.loads(events.splitlines()[-1])['outcome'], 'configuration')

    def test_local_actors_are_required_free_text(self):
        self.assert_configuration(operator_cli(*self.approve_argv(self.local_config, '--state-dir', str(self.root))))
        self.assertIsNone(self.state.approval(self.candidate.manifest.generation_id))
        self.assert_configuration(operator_cli(*self.rollback_argv(self.local_config, '--state-dir', str(self.root))))

    def test_azure_approve_and_rollback_record_the_signed_in_principal(self):
        with self.azure() as opened:
            code, message, _ = operator_cli(*self.approve_argv(self.azure_config))
            self.assertEqual((code, message['outcome'], message['approval']['approver']), (0, 'success', PRINCIPAL))
            code, message, _ = operator_cli(*self.rollback_argv(self.azure_config))
            self.assertEqual((code, message['outcome'], message['rollback']['operator']), (0, 'success', PRINCIPAL))
        self.assertEqual(opened.call_args.kwargs, {'base_path': None, 'access': 'operator',
                                                   'credential': self.credential})
        self.assertEqual(self.credential.scopes, [('https://storage.azure.com/.default',)] * 2)

    def test_azure_refuses_free_text_and_unusable_sign_ins_before_opening_stores(self):
        cases = {'free text': (self.credential, ('--approver', 'Lowell Mason')),
                 'no object id': (FakeCredential(jwt(tid=TENANT_ID)), ()),
                 'not signed in': (FailingCredential(), ())}
        for label, (credential, extra) in cases.items():
            with self.subTest(label), \
                    patch('sec_edgar_ingest.storage.azure.operator_credential', return_value=credential), \
                    patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')):
                self.assert_configuration(operator_cli(*self.approve_argv(self.azure_config, *extra)))

    def test_azure_candidates_need_no_actor(self):
        with self.azure():
            code, message, _ = operator_cli('candidates', '--config', str(self.azure_config))
        self.assertEqual((code, [entry['status'] for entry in message['candidates']]), (0, ['pending']))

    def test_a_mistyped_state_dir_creates_nothing(self):
        typo = self.root / 'typo'
        self.assert_configuration(operator_cli('candidates', '--config', str(self.local_config),
                                               '--state-dir', str(typo)))
        self.assertFalse(typo.exists())

    def test_operator_reads_leave_the_store_unchanged(self):
        before = tree_snapshot(self.root)
        code, _, _ = operator_cli('candidates', '--config', str(self.local_config), '--state-dir', str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(tree_snapshot(self.root), before)


if __name__ == '__main__':
    unittest.main()
