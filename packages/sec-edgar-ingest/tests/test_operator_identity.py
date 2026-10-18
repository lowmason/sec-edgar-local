"""Operator actors are explicit local audit labels; reads verify without writes."""
from network_guard import install
install()

import contextlib
import io
import json
from unittest.mock import patch

from support_approval import GateFixture, operator_cli, tree_snapshot


class OperatorIdentityTests(GateFixture):
    def setUp(self):
        super().setUp()
        self.base, self.revised, self.candidate = self.gated()
        self.config = self.write_config()

    def approve_argv(self, *extra):
        return ('approve', '--config', str(self.config), '--quarter', '2026Q4',
                '--generation', self.candidate.manifest.generation_id,
                '--quarterly-sha256', self.revised.snapshot.sha256, *extra)

    def rollback_argv(self, *extra):
        return ('rollback', '--config', str(self.config), '--quarter', '2026Q4',
                '--from-generation', self.candidate.manifest.generation_id,
                '--to-generation', self.base.generation_id, '--reason', 'bad correction', *extra)

    def test_local_actors_are_required_before_opening_stores(self):
        for args in (self.approve_argv(), self.rollback_argv()):
            with self.subTest(command=args[0]), \
                    patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')) as opened, \
                    self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
                operator_cli(*args)
            self.assertEqual(caught.exception.code, 2)
            opened.assert_not_called()
        self.assertIsNone(self.state.approval(self.candidate.manifest.generation_id))

    def test_approve_and_rollback_record_explicit_local_labels(self):
        code, message, _ = operator_cli(*self.approve_argv('--approver', 'Lowell Mason'))
        self.assertEqual((code, message['outcome'], message['approval']['approver']), (0, 'success', 'Lowell Mason'))
        code, message, _ = operator_cli(*self.rollback_argv('--operator', 'Local operator'))
        self.assertEqual((code, message['outcome'], message['rollback']['operator']), (0, 'success', 'Local operator'))

    def test_unsafe_actor_labels_refuse_before_stores(self):
        for label in ('', '  ', 'bad\nactor', 'bad\x7factor', 'x' * 257):
            for args in (self.approve_argv('--approver', label), self.rollback_argv('--operator', label)):
                with self.subTest(label=label, command=args[0]), \
                        patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')) as opened:
                    code, message, events = operator_cli(*args)
                self.assertEqual((code, message), (2, None))
                self.assertEqual(json.loads(events)['outcome'], 'configuration')
                opened.assert_not_called()

    def test_removed_state_override_creates_nothing(self):
        typo = self.root / 'typo'
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
            operator_cli('candidates', '--config', str(self.config), '--state-dir', str(typo))
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(typo.exists())

    def test_operator_reads_leave_the_store_unchanged(self):
        before = tree_snapshot(self.root)
        code, message, _ = operator_cli('candidates', '--config', str(self.config))
        self.assertEqual((code, [entry['status'] for entry in message['candidates']]), (0, ['pending']))
        code, message, _ = operator_cli('history', '--config', str(self.config), '--quarter', '2026Q4')
        self.assertEqual(code, 0, message)
        self.assertEqual(tree_snapshot(self.root), before)

    def test_unsafe_rollback_reason_refuses_before_stores(self):
        for reason in ('', 'bad\nreason', 'x' * 1025):
            args = list(self.rollback_argv('--operator', 'Local operator'))
            args[args.index('--reason') + 1] = reason
            with self.subTest(reason=reason), patch('sec_edgar_ingest.cli.open_stores', side_effect=AssertionError('opened stores')) as opened:
                code, message, events = operator_cli(*args)
            self.assertEqual((code, message), (2, None), events)
            opened.assert_not_called()
