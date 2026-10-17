from network_guard import install
install()

import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from support import Faults, CollectionCrash
from support_checked import workflow_fixture, dispatch_chain, cursor_values
from sec_edgar_ingest.config import Settings, pin_context
from sec_edgar_ingest.models import Binding, canonical_json, parse_json, to_mapping_value
from sec_edgar_ingest.state import AcquisitionState
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.workflows.checked import (
    Dispatcher, ChildUnfinished, call_ref, child_attempt_id, read_child,
)


class CheckedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings, self.context, self.pack, self.store, self.objects = workflow_fixture(self.root)
        self.addCleanup(self.store.close)
        self.dispatcher = Dispatcher(self.context, self.settings, self.pack, self.root,
                                     self.store, self.objects)

    def test_checked_record_freezes_call_and_rejects_result_reference_change(self):
        from sec_edgar_ingest.workflows.checked import CheckedChild
        child = self.dispatcher.execute('discover', 'record-discover', self.settings,
            ('--mode', 'quarterly', '--discovery-id', 'checked-record-session'))
        mutable = child.to_mapping()['call']
        value = CheckedChild(mutable, child.result_ref, child.result)
        original = value.call['intent']['discovery_id']
        mutable['intent']['discovery_id'] = 'changed-session'
        self.assertEqual(value.call['intent']['discovery_id'], original)
        with self.assertRaises(ValueError):
            CheckedChild(child.call, child.result_ref + '.changed', child.result)
        with self.assertRaises(ValueError):
            CheckedChild(child.call, child.result_ref, child.result.to_mapping())

    def test_boolean_call_flags_reject_integer_substitution(self):
        from sec_edgar_ingest.workflows.checked import make_call, child_attempt_id, call_ref
        for command, field, kwargs in (
                ('discover', 'refresh', {'mode': 'quarterly', 'discovery_id': 'strict-flag-session'}),
                ('transform', 'force', {})):
            with self.subTest(command=command):
                attempt = child_attempt_id(self.context.run_id, self.context.command,
                    self.context.attempt_id, 'typed-' + command, command)
                input_ref = None if command == 'discover' else 'worksets/sec/snapshot/sha256=' + 'a' * 64 + '/workset.json'
                from sec_edgar_ingest.download import FixturePack
                fixture_sha256 = FixturePack.load(self.pack).manifest_sha256 if command == 'discover' else None
                call = make_call(self.context, command, attempt, input_ref, fixture_sha256,
                    workflow_command=self.context.command, workflow_attempt_id=self.context.attempt_id,
                    step_id='typed-' + command, **kwargs)
                for number in (0, 1):
                    changed = parse_json(canonical_json(to_mapping_value(call)))
                    changed['intent'][field] = number
                    with self.assertRaises((Conflict, ValueError)):
                        call_ref(changed)

    def test_daily_discovery_collection_keeps_origin_priority_in_checked_context(self):
        parent = replace(self.context, command='daily', priority='daily')
        dispatcher = Dispatcher(parent, self.settings, self.pack, self.root, self.store, self.objects)
        found = dispatcher.execute('discover', 'daily-discover', self.settings,
            ('--mode', 'daily', '--discovery-id', 'checked-daily-discovery'))
        collected = dispatcher.execute('collect', 'daily-collect', self.settings,
            ('--workset', found.result.source_workset_ref))
        self.assertEqual(found.result.context.priority, 'daily')
        self.assertEqual(collected.result.context.priority, 'daily')
        self.assertEqual(collected.call['context']['priority'], 'daily')
        self.assertEqual(read_child(collected.call, self.store, self.objects), collected.result)
        transformed = dispatcher.execute('transform', 'daily-transform', self.settings,
            ('--workset', collected.result.snapshot_workset_ref))
        published = dispatcher.execute('publish', 'daily-publish', self.settings,
            ('--workset', transformed.result.transformed_workset_ref))
        self.assertEqual(transformed.result.context.priority, 'backfill')
        self.assertEqual(published.result.context.priority, 'backfill')
        self.assertEqual(published.result.outcome, 'success')

    def test_real_input_chain_and_retained_retry_prefix(self):
        self.store.close()
        self.settings, self.context, self.pack, self.store, self.objects = workflow_fixture(
            self.root, prefix=True)
        self.dispatcher = Dispatcher(self.context, self.settings, self.pack, self.root,
                                     self.store, self.objects)
        found, collected, transformed, published = dispatch_chain(self.dispatcher, self.settings)
        self.assertEqual(collected.result.outcome, 'success')
        self.assertEqual(collected.result.quarantined, 1)
        self.assertEqual(transformed.result.quarantined, 0)
        self.assertEqual(published.result.outcome, 'success')
        acquisition = AcquisitionState(self.store)
        source = next(iter(self.store.scan('Source', {}))).value['source']
        history = acquisition.request_history(collected.result.context, source['canonical_url'])
        self.assertEqual(len(history), 2)
        first = history[0].value
        base = (f'quarantine/sec/{self.context.run_id}/{source["source_id"]}/'
                f'{collected.result.context.attempt_id}/{first["request_id"]}')
        self.assertEqual(self.objects.read(base + '/body'), b'retained retry prefix')
        self.assertEqual(parse_json(self.objects.read(base + '/receipt.json'))['error']['code'], 'read_timeout')
        for child in (found, collected, transformed, published):
            self.assertEqual(read_child(child.call, self.store, self.objects), child.result)
        capture = capture_quarter('2026Q4', self.objects, EtlState(self.store))
        self.assertEqual(len(list(read_quarter(capture, self.objects))), 1)

    def test_parent_command_namespace_and_exact_replay(self):
        backfill = self.dispatcher.execute('discover', 'discover', self.settings,
            ('--mode', 'quarterly', '--discovery-id', 'checked-backfill'))
        daily_context = replace(self.context, command='daily', priority='daily')
        daily_dispatcher = Dispatcher(daily_context, self.settings, self.pack, self.root,
                                      self.store, self.objects)
        daily = daily_dispatcher.execute('discover', 'discover', self.settings,
            ('--mode', 'daily', '--discovery-id', 'checked-daily'))
        self.assertNotEqual(backfill.result_ref, daily.result_ref)
        before = cursor_values(self.store)
        self.assertEqual(self.dispatcher.execute('discover', 'discover', self.settings,
            ('--mode', 'quarterly', '--discovery-id', 'checked-backfill')).result, backfill.result)
        self.assertEqual(daily_dispatcher.execute('discover', 'discover', self.settings,
            ('--mode', 'daily', '--discovery-id', 'checked-daily')).result, daily.result)
        self.assertEqual(cursor_values(self.store), before)
        self.assertNotEqual(child_attempt_id(self.context.run_id, 'backfill', self.context.attempt_id,
            'discover', 'discover'), child_attempt_id(self.context.run_id, 'daily',
            self.context.attempt_id, 'discover', 'discover'))

    def test_changed_flags_or_canonical_call_refuse(self):
        child = self.dispatcher.execute('discover', 'discover', self.settings,
            ('--mode', 'quarterly', '--discovery-id', 'checked-discovery'))
        before = cursor_values(self.store)
        with self.assertRaises(Conflict):
            self.dispatcher.execute('discover', 'discover', self.settings,
                ('--mode', 'quarterly', '--discovery-id', 'changed-discovery'))
        altered = dict(child.call)
        altered['step_id'] = 'different-step'
        with self.assertRaises((Conflict, ValueError)):
            read_child(altered, self.store, self.objects)
        target = self.root / '.fixture-state/objects' / call_ref(child.call)
        target.write_bytes(target.read_bytes() + b' ')
        with self.assertRaises(Conflict):
            read_child(child.call, self.store, self.objects)
        self.assertEqual(cursor_values(self.store), before)

    def test_call_is_durable_before_dispatch_and_reopen_uses_it(self):
        faults = Faults()
        def crash():
            raise CollectionCrash()
        faults.at('workflow_child.after_call', crash)
        stopped = Dispatcher(self.context, self.settings, self.pack, self.root,
                             self.store, self.objects, observer=faults)
        before = cursor_values(self.store)
        with self.assertRaises(CollectionCrash):
            stopped.execute('discover', 'discover', self.settings,
                ('--mode', 'quarterly', '--discovery-id', 'checked-discovery'))
        self.assertEqual(cursor_values(self.store), before)
        self.assertEqual(len(list(self.store.scan('WorkflowChildCall', {}))), 1)
        child = self.dispatcher.execute('discover', 'discover', self.settings,
            ('--mode', 'quarterly', '--discovery-id', 'checked-discovery'))
        self.assertEqual(child.result.outcome, 'success')

    def test_post_cas_repair_keeps_child_unfinished_until_checked_retry(self):
        found = self.dispatcher.execute('discover', 'discover', self.settings,
            ('--mode', 'quarterly', '--discovery-id', 'checked-discovery'))
        collected = self.dispatcher.execute('collect', 'collect-one', self.settings,
            ('--workset', found.result.source_workset_ref))
        transformed = self.dispatcher.execute('transform', 'transform-one', self.settings,
            ('--workset', collected.result.snapshot_workset_ref))
        original = EtlState.record_publication
        failures = []
        def fail_once(state, manifest):
            if not failures:
                failures.append(True)
                raise OSError('ordinary ancillary failure after CAS')
            return original(state, manifest)
        with patch.object(EtlState, 'record_publication', fail_once):
            with self.assertRaises(ChildUnfinished) as raised:
                self.dispatcher.execute('publish', 'publish-one', self.settings,
                    ('--workset', transformed.result.transformed_workset_ref))
        error = raised.exception
        self.assertTrue(error.repair_pending)
        with self.assertRaises(FileNotFoundError):
            read_child(error.call, self.store, self.objects)
        pointers = [row.to_mapping() for row in self.store.scan('QuarterPublication', {})]
        child = self.dispatcher.execute('publish', 'publish-one', self.settings,
            ('--workset', transformed.result.transformed_workset_ref))
        self.assertEqual(child.result.outcome, 'unchanged')
        self.assertEqual([row.to_mapping() for row in self.store.scan('QuarterPublication', {})], pointers)
        self.assertEqual(len(list(self.store.scan('PublicationReceipt', {}))), 1)

    def test_input_binding_and_raw_tamper_are_refused(self):
        _, collected, transformed, published = dispatch_chain(self.dispatcher, self.settings)
        source_rows = list(self.store.scan('Binding', {}))
        binding = source_rows[0]
        value = binding.to_mapping()['value']
        value['snapshot_sha256'] = 'f' * 64
        binding_key = value['source_workset_id'] + ':' + value['source_id']
        self.store.replace('Binding', binding_key, value, binding.version)
        with self.assertRaises((Conflict, ValueError)):
            read_child(transformed.call, self.store, self.objects)
        self.store.replace('Binding', binding_key, binding.to_mapping()['value'],
                           self.store.get('Binding', binding_key).version)
        raw = next(iter(self.store.scan('Snapshot', {}))).value['raw_path']
        (self.root / '.fixture-state/objects' / raw).write_bytes(b'corrupt retained raw')
        with self.assertRaises((Conflict, ValueError)):
            read_child(published.call, self.store, self.objects)

    def test_changed_context_and_flags_refuse_before_new_transport(self):
        self.dispatcher.execute('discover', 'discover', self.settings,
            ('--mode', 'quarterly', '--discovery-id', 'checked-discovery'))
        before = cursor_values(self.store)
        changed_settings_value = self.settings.to_mapping()
        changed_settings_value['etl']['parser_version'] = 'fixture-index-parser-v2'
        changed_settings = Settings.from_mapping(changed_settings_value)
        variants = (
            (self.settings, replace(self.context, execution_id='different-execution')),
            (self.settings, replace(self.context, deadline=self.context.deadline.replace(year=2027))),
            (changed_settings, replace(self.context, parser_version=changed_settings.etl.parser_version,
                config_sha256=changed_settings.config_sha256, effective_config={}, pinned_on=None)),
        )
        for settings, context in variants:
            context = pin_context(settings, context, self.context.pinned_on)[0]
            different = Dispatcher(context, settings, self.pack, self.root, self.store, self.objects)
            with self.assertRaises(Conflict):
                different.execute('discover', 'discover', settings,
                    ('--mode', 'quarterly', '--discovery-id', 'checked-discovery'))
        for flags in (
            ('--mode', 'quarterly', '--discovery-id', 'x', '--force'),
            ('--mode', 'quarterly', '--mode', 'daily', '--discovery-id', 'x'),
            ('--mode', 'quarterly', '--discovery-id', '../escape'),
        ):
            with self.assertRaises(ValueError):
                self.dispatcher.execute('discover', 'invalid-flags', self.settings, flags)
        self.assertEqual(cursor_values(self.store), before)

    def test_origin_collection_and_current_parser_are_separate_exact_contexts(self):
        found = self.dispatcher.execute('discover', 'discover', self.settings,
            ('--mode', 'quarterly', '--discovery-id', 'checked-discovery'))
        original = self.dispatcher.execute('collect', 'collect-one', self.settings,
            ('--workset', found.result.source_workset_ref))
        value = self.settings.to_mapping()
        value['etl']['parser_version'] = 'fixture-index-parser-v2'
        current = Settings.from_mapping(value)
        context = replace(self.context, attempt_id='new-parser-attempt',
            parser_version=current.etl.parser_version, config_sha256=current.config_sha256,
            effective_config={}, pinned_on=None)
        context = pin_context(current, context, self.context.pinned_on)[0]
        dispatcher = Dispatcher(context, current, self.pack, self.root, self.store, self.objects)
        reused = dispatcher.execute('collect', 'collect-origin', self.settings,
            ('--workset', found.result.source_workset_ref))
        self.assertEqual(reused.result.context.parser_version, 'fixture-index-parser-v1')
        self.assertEqual(reused.result.snapshot_workset_ref, original.result.snapshot_workset_ref)
        transformed = dispatcher.execute('transform', 'transform-current', current,
            ('--workset', reused.result.snapshot_workset_ref))
        published = dispatcher.execute('publish', 'publish-current', current,
            ('--workset', transformed.result.transformed_workset_ref))
        self.assertEqual(transformed.result.context.parser_version, 'fixture-index-parser-v2')
        self.assertEqual(published.result.context.parser_version, 'fixture-index-parser-v2')

    def test_historical_capture_survives_missing_mutable_child_indexes(self):
        from sec_edgar_ingest.workflows.checked import read_child_capture
        _, _, _, published = dispatch_chain(self.dispatcher, self.settings)
        class NoState:
            def get(self, kind, key):
                raise AssertionError('historical capture consulted current state')
        self.assertEqual(read_child_capture(published.call, self.objects), published.result)
        # Current completion and dispatch still require exact repaired mutable readback.
        with self.assertRaises(AssertionError):
            read_child(published.call, NoState(), self.objects)

    def test_snapshot_chain_refuses_noncanonical_retained_source_bytes(self):
        from sec_edgar_ingest.workflows.checked import read_child_capture
        found, collected, transformed, published = dispatch_chain(self.dispatcher, self.settings)
        source_path = self.root / '.fixture-state/objects' / found.result.source_workset_ref
        source_path.write_bytes(source_path.read_bytes() + b' ')
        for child in (transformed, published):
            with self.subTest(command=child.result.context.command):
                with self.assertRaises((Conflict, ValueError)):
                    read_child(child.call, self.store, self.objects)
                with self.assertRaises((Conflict, ValueError)):
                    read_child_capture(child.call, self.objects)
        with patch('sec_edgar_ingest.cli.main', side_effect=AssertionError('changed source reached CLI')):
            with self.assertRaises((Conflict, ValueError)):
                self.dispatcher.execute('transform', 'tampered-source-transform', self.settings,
                    ('--workset', collected.result.snapshot_workset_ref))
