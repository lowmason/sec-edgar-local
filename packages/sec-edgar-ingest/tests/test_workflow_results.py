# tests/test_workflow_results.py
import hashlib
from contextlib import closing
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from support import CollectionCrash, store_bundle
from support_workflow_evidence import EvidenceFixture, quarterly_bytes
from sec_edgar_ingest.etl.reader import read_quarter
from sec_edgar_ingest.etl.contracts import GenerationCapture
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.models import Error, Source, canonical_json, parse_json, to_mapping_value
from sec_edgar_ingest.state import AcquisitionState
from sec_edgar_ingest.storage.contracts import Conflict, OwnershipLost, identity, table_for
from sec_edgar_ingest.worksets import decode_source_workset
from sec_edgar_ingest.workflows.checked import Dispatcher, ChildUnfinished
from sec_edgar_ingest.workflows.completion import (
    capture_member_provenance, capture_parent_provenance, validate_parent_provenance, evaluate_member,
)
from sec_edgar_ingest.workflows.contracts import (
    FORMAT_VERSION, MemberResult, WorkflowResult, summarize, workflow_path,
)
from sec_edgar_ingest.workflows.results import (
    freeze_workflow, freeze_selection, read_workflow_result,
    write_workflow_result, workflow_key,
)


class WorkflowResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = EvidenceFixture(Path(self.temp.name) / '.fixture-state', command='backfill')
        self.addCleanup(self.f.close)
        self.invocation = {'command': 'backfill', 'today': '2026-10-06',
                           'fixture_sha256': hashlib.sha256(self.f.pack.read_bytes()).hexdigest(),
                           'pinned_end_quarter': '2026Q4'}
        self.f.discovery_call = to_mapping_value(self.f.discovery_call)
        self.context = freeze_workflow(self.f.workflow, self.invocation,
                                       self.f.store, self.f.objects)
        self.f.snapshot_input(quarterly_bytes('2026-07-01'))
        _, self.collect_call, collected = self.invoke_member('collect', self.f.value['member_ref'])
        snapshot_ref = collected.snapshot_workset_ref
        _, self.transform_call, transformed = self.invoke_member('transform', snapshot_ref)
        _, self.publish_call, self.published = self.invoke_member('publish', transformed.transformed_workset_ref)
        self.snapshot_ref = snapshot_ref
        self.transformed_ref = transformed.transformed_workset_ref
        self.capture = to_mapping_value(evaluate_member(self.f.value, self.context.parser_version,
            self.context.schema_version, self.f.store, self.f.objects).capture)
        self.assertIsNotNone(self.capture)
        self.baseline_gap = Error('baseline_publication_missing',
            'valid empty Q4 listing remains an unresolved baseline unit', False, None,
            {'quarter': '2026Q4', 'coverage_cause': 'missing_source', 'source_ids': []})

    def invoke_member(self, command, input_ref):
        dispatcher = Dispatcher(self.context, self.f.settings, self.f.pack,
                                self.f.root.parent, self.f.store, self.f.objects)
        child = dispatcher.execute(command, command + '-' + self.f.value['member_id'],
                                   self.f.settings, ('--workset', input_ref))
        from sec_edgar_ingest.results import exit_code
        return exit_code(child.result.outcome), to_mapping_value(child.call), child.result

    def selection(self, *, skipped=False):
        parent = decode_source_workset(self.f.objects.read(self.f.parent_ref))
        session = AcquisitionState(self.f.store).discovery_session(parent.discovery_id).to_mapping()['value']
        members = [] if skipped else [self.f.value]
        parent_provenance = capture_parent_provenance(self.f.parent_ref, self.f.store, self.f.objects)
        return {'format_version': 'sec-workflow-selection-v2',
                'context': self.context.to_mapping(), 'invocation': self.invocation,
                'members': members,
                'jobs': [{'member': value, 'aliases': [value]} for value in members],
                'member_provenance': [capture_member_provenance(value, self.f.store, self.f.objects)
                                      for value in members],
                'already_complete': [self.capture] if skipped else [],
                'superseded': [],
                'discovery_call': self.f.discovery_call, 'discovery_error': None,
                'parent_ref': self.f.parent_ref,
                'parent_provenance': parent_provenance,
                'discovery_session': session,
                'required_units': session['frozen']['units'],
                'halted': False, 'requested_quarters': ['2026Q3', '2026Q4'],
                'directories': [d.to_mapping() for d in parent.directories],
                'boundary_before': None, 'gaps': [self.baseline_gap.to_mapping()],
                'discovered_sources': 1, 'unresolved_before': 0}

    def report(self, *, skipped=False):
        selection = freeze_selection(self.context, self.selection(skipped=skipped),
                                     self.f.store, self.f.objects)
        selection_path = workflow_path(self.context).rsplit('/', 1)[0] + '/selection.json'
        body = self.f.objects.read(selection_path)
        descriptor = {'ref': selection_path, 'sha256': hashlib.sha256(body).hexdigest(),
                      'bytes': len(body)}
        members = () if skipped else (MemberResult(
            self.f.value['member_id'], Source.from_mapping(self.f.value['source']),
            self.f.value['parent_ref'], self.snapshot_ref, self.transformed_ref,
            (self.collect_call['result_ref'], self.transform_call['result_ref'], self.publish_call['result_ref']),
            self.published.outcome, True, True, False, self.published.quarters, (),
            self.context.parser_version, self.context.schema_version),)
        already = (self.f.source.source_id,) if skipped else ()
        gaps = (self.baseline_gap,)
        outcome, counts = summarize(members, gaps, 1, 0, self.context.command, already)
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        receipts = []
        if members:
            evidence = {'format_version': 'sec-workflow-member-evidence-v1', 'member': self.f.value,
                        'calls': [self.collect_call, self.transform_call, self.publish_call],
                        'completion': self.capture, 'resolutions': [], 'terminal_error': None}
            receipts.append(WorkflowMembers(self.f.store, self.f.objects).record(members[0], self.context, evidence))
        intent = {'invocation': self.invocation, 'selection': descriptor,
                  'member_receipts': receipts,
                  'child_calls': [self.f.discovery_call] + ([] if skipped else
                                  [self.collect_call, self.transform_call, self.publish_call]),
                  'completion_captures': [self.capture], 'repair_resolutions': [],
                  'already_complete_sources': list(already),
                  'discovered_sources': 1, 'unresolved_before': 0}
        return WorkflowResult(FORMAT_VERSION, self.context, intent, self.f.parent_ref,
            ('2026Q3', '2026Q4'), tuple(selection['directories']), members, gaps,
            None, None, outcome, counts, self.published.ended_at.isoformat())

    def delete_index(self, kind, key):
        # Test-only isolated corruption. Production has no state deletion API.
        partition, _ = identity(kind, key)
        with closing(sqlite3.connect(self.f.store.database)) as db:
            db.execute('DELETE FROM records WHERE table_name=? AND partition=? AND key=?',
                       (table_for(kind), partition, key))
            db.commit()

    def test_historical_report_reads_original_capture_after_pointer_advance(self):
        report = self.report()
        path = write_workflow_result(report, self.f.store, self.f.objects)
        before = self.f.objects.read(path)
        self.f.revised_member()
        snapshot = self.f.snapshot_input(quarterly_bytes('2026-07-01', 'Changed'), seconds=1)
        _, _, transformed = self.f.invoke('transform', snapshot)
        self.f.invoke('publish', transformed.transformed_workset_ref)
        reread = read_workflow_result(path, self.f.store, self.f.objects)
        self.assertEqual(reread, report)
        self.assertEqual(self.f.objects.read(path), before)
        capture = GenerationCapture.from_mapping(self.capture['quarters'][0])
        self.assertEqual(list(read_quarter(capture, self.f.objects))[0].company_name, 'A')
        self.assertNotEqual(capture.generation_id, EtlState(self.f.store).pointer('2026Q3').value['generation_id'])

    def test_report_object_crash_reopens_and_repairs_exact_index(self):
        report = self.report()
        pointers = [r.to_mapping() for r in self.f.store.scan('QuarterPublication', {})]
        def crash(point):
            if point == 'workflow.after_report_object':
                raise CollectionCrash()
        with self.assertRaises(CollectionCrash):
            write_workflow_result(report, self.f.store, self.f.objects, crash)
        path = workflow_path(report.context)
        body = self.f.objects.read(path)
        self.assertIsNone(self.f.store.get('WorkflowAttempt', workflow_key(self.context)).value['result_ref'])
        self.f.close()
        store, objects, leases = store_bundle(self.f.root)
        self.addCleanup(store.close)
        self.addCleanup(leases.close)
        with patch('sec_edgar_ingest.cli.BoundedSender', side_effect=AssertionError('report replay sender')):
            self.assertEqual(read_workflow_result(path, store, objects), report)
        self.assertEqual(objects.read(path), body)
        self.assertEqual([r.to_mapping() for r in store.scan('QuarterPublication', {})], pointers)
        self.assertEqual(store.get('WorkflowAttempt', workflow_key(self.context)).value['result_ref']['sha256'],
                         hashlib.sha256(body).hexdigest())

    def test_missing_workflow_and_child_indexes_recover_from_immutable_authority(self):
        from sec_edgar_ingest.workflows.checked import call_key
        report = self.report()
        path = write_workflow_result(report, self.f.store, self.f.objects)
        expected = self.f.store.get('WorkflowAttempt', workflow_key(self.context)).to_mapping()['value']
        self.delete_index('WorkflowAttempt', workflow_key(self.context))
        for call in (self.f.discovery_call, self.collect_call, self.transform_call, self.publish_call):
            self.delete_index('WorkflowChildCall', call_key(call))
        self.assertEqual(read_workflow_result(path, self.f.store, self.f.objects), report)
        self.assertEqual(self.f.store.get('WorkflowAttempt', workflow_key(self.context)).to_mapping()['value'], expected)

    def test_existing_conflicting_report_index_refuses(self):
        report = self.report()
        path = write_workflow_result(report, self.f.store, self.f.objects)
        key = workflow_key(self.context)
        row = self.f.store.get('WorkflowAttempt', key)
        original = row.to_mapping()['value']
        for name, replacement in [('context', {**original['context'], 'execution_id': 'different'}),
                                  ('intent', {**original['intent'], 'today': '2026-10-07'}),
                                  ('selection_ref', {**original['selection_ref'], 'bytes': 1}),
                                  ('result_ref', {**original['result_ref'], 'sha256': 'f' * 64})]:
            current = self.f.store.get('WorkflowAttempt', key)
            bad = {**original, name: replacement}
            self.f.store.replace('WorkflowAttempt', key, bad, current.version)
            with self.subTest(name=name), self.assertRaises(Conflict):
                read_workflow_result(path, self.f.store, self.f.objects)
            current = self.f.store.get('WorkflowAttempt', key)
            self.f.store.replace('WorkflowAttempt', key, original, current.version)

    def test_exact_replay_after_deadline_and_changed_invocation_refusal(self):
        report = self.report()
        path = write_workflow_result(report, self.f.store, self.f.objects)
        after = self.context.deadline + timedelta(seconds=1)
        with patch('sec_edgar_ingest.workflows.results.datetime') as clock:
            clock.now.return_value = after
            self.assertEqual(freeze_workflow(self.context, self.invocation, self.f.store, self.f.objects), self.context)
        before = self.f.objects.read(path)
        changes = {'execution_id': 'other', 'image_digest': 'sha256:' + 'f' * 64,
                   'parser_version': 'fixture-index-parser-v2',
                   'deadline': self.context.deadline + timedelta(seconds=1)}
        for field, value in changes.items():
            with self.subTest(field=field), self.assertRaises((Conflict, ValueError)):
                freeze_workflow(replace(self.context, **{field: value}), self.invocation,
                                self.f.store, self.f.objects)
        with self.assertRaises(Conflict):
            freeze_workflow(self.context, {**self.invocation, 'fixture_sha256': 'f' * 64},
                            self.f.store, self.f.objects)
        self.assertEqual(self.f.objects.read(path), before)
        fresh = replace(self.context, attempt_id='unfinished-expired')
        with patch('sec_edgar_ingest.workflows.results.datetime') as clock:
            clock.now.return_value = after
            with self.assertRaises(TimeoutError):
                freeze_workflow(fresh, self.invocation, self.f.store, self.f.objects)

    def test_skipped_before_dispatch_capture_is_required_and_counted_once(self):
        report = self.report(skipped=True)
        self.assertEqual(report.counts['complete_sources'], 1)
        self.assertEqual(report.counts['failed_sources'], 0)
        path = write_workflow_result(report, self.f.store, self.f.objects)
        changed = replace(report, intent={**report.to_mapping()['intent'], 'completion_captures': []})
        with self.assertRaises(Conflict):
            write_workflow_result(changed, self.f.store, self.f.objects)
        self.assertEqual(read_workflow_result(path, self.f.store, self.f.objects), report)

    def test_selection_substitution_and_missing_evidence_refuse(self):
        selection = self.selection()
        freeze_selection(self.context, selection, self.f.store, self.f.objects)
        changed = {**selection, 'jobs': []}
        with self.assertRaises(Conflict):
            freeze_selection(self.context, changed, self.f.store, self.f.objects)
        report = self.report()
        corrupted = replace(report, intent={**report.to_mapping()['intent'],
                                           'child_calls': [self.f.discovery_call, self.transform_call]})
        with self.assertRaises(Conflict):
            write_workflow_result(corrupted, self.f.store, self.f.objects)
        capture = self.capture['quarters'][0]
        target = self.f.root / 'objects' / capture['manifest_ref']
        body = target.read_bytes()
        target.write_bytes(body[:-1])
        with self.assertRaises((Conflict, ValueError, FileNotFoundError)):
            write_workflow_result(report, self.f.store, self.f.objects)
        target.write_bytes(body)

    def test_a_new_selection_cannot_be_frozen_in_the_legacy_v1_format(self):
        path = workflow_path(self.context).rsplit('/', 1)[0] + '/selection.json'
        legacy = {**self.selection(), 'format_version': 'sec-workflow-selection-v1'}
        del legacy['superseded']
        with self.assertRaisesRegex(Conflict, 'new selection must use the current format'):
            freeze_selection(self.context, legacy, self.f.store, self.f.objects)
        with self.assertRaises(FileNotFoundError):
            self.f.objects.read(path)
        frozen = freeze_selection(self.context, self.selection(), self.f.store, self.f.objects)
        self.assertEqual(frozen['format_version'], 'sec-workflow-selection-v2')
        self.assertEqual(parse_json(self.f.objects.read(path))['format_version'], 'sec-workflow-selection-v2')

    def test_fatal_discovery_without_result_preserves_frozen_prior_jobs(self):
        dispatcher = Dispatcher(self.context, self.f.settings, self.f.pack,
                                self.f.root.parent, self.f.store, self.f.objects)
        with patch('sec_edgar_ingest.cli.discover', side_effect=OwnershipLost('fatal discovery ownership')):
            with self.assertRaises(ChildUnfinished) as failed:
                dispatcher.execute('discover', 'fatal-discovery', self.f.settings,
                                   ('--mode', 'quarterly', '--discovery-id', 'fatal-discovery-session'))
        error = Error(failed.exception.outcome, 'discovery has no durable source result',
                      False, None, failed.exception.details)
        selection = self.selection()
        selection.update(discovery_call=failed.exception.call, discovery_error=error.to_mapping(),
                         parent_ref=None, parent_provenance=None, discovery_session=None,
                         required_units=[], directories=[], halted=True,
                         gaps=[error.to_mapping()] + [gap.to_mapping() for gap in failed.exception.gaps],
                         discovered_sources=0, unresolved_before=1)
        freeze_selection(self.context, selection, self.f.store, self.f.objects)
        path = workflow_path(self.context).rsplit('/', 1)[0] + '/selection.json'
        body = self.f.objects.read(path)
        descriptor = {'ref': path, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
        member = MemberResult(self.f.value['member_id'], self.f.source, self.f.value['parent_ref'],
                              None, None, (), 'pending', False, False, False, (),
                              (Error('workflow_deferred', 'halt/deadline left source undispatched', True,
                                     self.f.source.source_id, {}),), self.context.parser_version, self.context.schema_version)
        gaps = tuple(Error.from_mapping(value) for value in selection['gaps']) + member.gaps
        outcome, counts = summarize((member,), gaps, 0, 1, 'backfill', ())
        intent = {'invocation': self.invocation, 'selection': descriptor,
                  'member_receipts': [None],
                  'child_calls': [failed.exception.call], 'completion_captures': [],
                  'repair_resolutions': [], 'already_complete_sources': [],
                  'discovered_sources': 0, 'unresolved_before': 1}
        result = WorkflowResult(FORMAT_VERSION, self.context, intent, None,
            ('2026Q3', '2026Q4'), (), (member,), gaps, None, None,
            outcome, counts, self.published.ended_at.isoformat())
        result_path = write_workflow_result(result, self.f.store, self.f.objects)
        self.assertEqual(read_workflow_result(result_path, self.f.store, self.f.objects), result)
        self.assertEqual(result.outcome, 'ownership_lost')
        self.assertEqual(result.counts['pending_sources'], 1)

    def test_parent_capture_retains_full_empty_discovery_authority(self):
        from support_workflows import simple_pack, CommandHarness
        from sec_edgar_ingest.workflows.checked import Dispatcher
        from sec_edgar_ingest.workflows.completion import capture_parent_provenance, validate_parent_provenance
        from sec_edgar_ingest.config import pin_context
        from datetime import date, datetime, timedelta, timezone
        from sec_edgar_ingest.models import RunContext
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack', empty=True))
            try:
                now = datetime.now(timezone.utc)
                context = RunContext('empty-parent-workflow', 'empty-parent-execution', 'backfill', 'empty-parent-attempt',
                    h.settings.worker.image_digest, h.settings.etl.parser_version, h.settings.etl.schema_version,
                    h.settings.config_sha256, now, now + timedelta(seconds=1800), 'backfill')
                context = pin_context(h.settings, context, date(2026, 10, 7))[0]
                invocation = {'command': 'backfill', 'today': '2026-10-07',
                              'fixture_sha256': hashlib.sha256(h.pack.read_bytes()).hexdigest(),
                              'pinned_end_quarter': '2026Q4'}
                context = freeze_workflow(context, invocation, h.store, h.objects)
                dispatcher = Dispatcher(context, h.settings, h.pack, h.root, h.store, h.objects)
                child = dispatcher.execute('discover', 'empty-discovery', h.settings,
                    ('--mode', 'quarterly', '--discovery-id', 'empty-parent-session'))
                proof = capture_parent_provenance(child.result.source_workset_ref, h.store, h.objects)
                parent = validate_parent_provenance(proof, h.objects)
                self.assertEqual(parent.members, ())
                self.assertTrue(parent.discovery_complete)
                self.assertGreater(len(proof['discovery']['progress']), 0)
                session = proof['discovery']['session']
                gaps = [Error('baseline_source_missing', 'valid empty listing leaves baseline source unresolved',
                              True, None, {'quarter': quarter}).to_mapping()
                        for quarter in ('2026Q3', '2026Q4')]
                selection = {'format_version': 'sec-workflow-selection-v2', 'context': context.to_mapping(),
                    'invocation': invocation, 'members': [], 'jobs': [], 'member_provenance': [],
                    'already_complete': [], 'superseded': [], 'discovery_call': child.call, 'discovery_error': None,
                    'parent_ref': child.result.source_workset_ref, 'parent_provenance': proof,
                    'discovery_session': session, 'required_units': session['frozen']['units'],
                    'halted': False, 'requested_quarters': ['2026Q3', '2026Q4'],
                    'directories': [d.to_mapping() for d in parent.directories], 'boundary_before': None,
                    'gaps': gaps, 'discovered_sources': 0, 'unresolved_before': 0}
                frozen = freeze_selection(context, selection, h.store, h.objects)
                self.assertEqual(frozen['parent_provenance'], proof)
                # Pure historical parent validation needs no surviving live session/index.
                validate_parent_provenance(proof, h.objects)
            finally:
                h.close()

    def test_empty_leaf_roles_bridge_and_listing_evidence_cannot_be_substituted(self):
        from copy import deepcopy
        from sec_edgar_ingest.workflows.completion import capture_parent_provenance, validate_parent_provenance
        from sec_edgar_ingest.models import parse_json, to_mapping_value
        selection = parse_json(canonical_json(to_mapping_value(self.selection(skipped=True))))
        proof = selection['parent_provenance']
        empty = next(value for value in proof['discovery']['progress']
                     if value['unit']['period'] == '2026Q4' and value['unit']['role'] == 'quarter')
        self.assertEqual(empty['value']['members'], [])
        variants = []
        changed = deepcopy(selection)
        next(unit for unit in changed['required_units'] if unit['role'] == 'root')['role'] = 'quarter'
        variants.append(changed)
        changed = deepcopy(selection)
        root = next(unit for unit in changed['required_units'] if unit['role'] == 'root')
        root['bridge_period'] = '2026Q3'; variants.append(changed)
        changed = deepcopy(selection); changed['parent_provenance'] = None; variants.append(changed)
        changed = deepcopy(selection); changed['discovery_session']['frozen']['end'] = '2026Q3'; variants.append(changed)
        changed = deepcopy(selection)
        captured = next(value for value in changed['parent_provenance']['discovery']['progress']
                        if value['unit']['period'] == '2026Q4' and value['unit']['role'] == 'quarter')
        captured['value']['evidence']['byte_count'] += 1; variants.append(changed)
        changed = deepcopy(selection)
        changed['already_complete'][0]['observation']['parser_version'] = 'fixture-index-parser-v2'
        variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises((Conflict, ValueError, FileNotFoundError)):
                freeze_selection(self.context, changed, self.f.store, self.f.objects)
        target = self.f.root / 'objects' / empty['value']['evidence']['body_path']
        original = target.read_bytes()
        target.write_bytes(original + b' ')
        try:
            with self.assertRaises((Conflict, ValueError, FileNotFoundError)):
                validate_parent_provenance(proof, self.f.objects)
        finally:
            target.write_bytes(original)

    def test_unfinished_discovery_retains_actual_frozen_session_ledger(self):
        from sec_edgar_ingest.state import AcquisitionState
        dispatcher = Dispatcher(self.context, self.f.settings, self.f.pack,
                                self.f.root.parent, self.f.store, self.f.objects)
        original = AcquisitionState.begin_discovery
        def stop_after_begin(state, *args, **kwargs):
            result = original(state, *args, **kwargs)
            raise OwnershipLost('ownership lost after required-unit registration')
        with patch.object(AcquisitionState, 'begin_discovery', stop_after_begin):
            with self.assertRaises(ChildUnfinished) as failed:
                dispatcher.execute('discover', 'begun-fatal-discovery', self.f.settings,
                    ('--mode', 'quarterly', '--discovery-id', 'begun-fatal-session'))
        session = AcquisitionState(self.f.store).discovery_session('begun-fatal-session').to_mapping()['value']
        self.assertTrue(session['registered'])
        self.assertIsNone(session['workset_id'])
        self.assertTrue(session['frozen']['units'])
        error = Error(failed.exception.outcome, 'discovery has no durable source result',
                      False, None, failed.exception.details)
        selection = self.selection()
        selection.update(discovery_call=failed.exception.call, discovery_error=error.to_mapping(),
            parent_ref=None, parent_provenance=None, discovery_session=session,
            required_units=session['frozen']['units'], directories=[], halted=True,
            gaps=[error.to_mapping()] + [gap.to_mapping() for gap in failed.exception.gaps],
            discovered_sources=0, unresolved_before=1)
        omitted_both = {**selection, 'discovery_session': None, 'required_units': []}
        with self.assertRaises(Conflict):
            freeze_selection(self.context, omitted_both, self.f.store, self.f.objects)
        frozen = freeze_selection(self.context, selection, self.f.store, self.f.objects)
        self.assertEqual(frozen['required_units'], session['frozen']['units'])
        self.assertIsNone(frozen['parent_ref'])
        self.assertTrue(frozen['halted'])
        self.delete_index('DiscoverySession', hashlib.sha256('begun-fatal-session'.encode()).hexdigest())
        self.assertIsNone(AcquisitionState(self.f.store).discovery_session('begun-fatal-session'))
        self.assertEqual(freeze_selection(self.context, selection, self.f.store, self.f.objects), frozen)
        from copy import deepcopy
        omitted = deepcopy(selection); omitted['required_units'] = []
        with self.assertRaises(Conflict):
            freeze_selection(self.context, omitted, self.f.store, self.f.objects)

    def test_valid_old_capture_cannot_discharge_current_parser_backlog(self):
        from support_workflows import simple_pack
        from sec_edgar_ingest.config import Settings, pin_context
        from sec_edgar_ingest.models import parse_json, to_mapping_value
        from sec_edgar_ingest.workflows.completion import capture_parent_provenance
        mapping = self.f.settings.to_mapping()
        mapping['etl']['parser_version'] = 'fixture-index-parser-v2'
        settings = Settings.from_mapping(mapping)
        context = pin_context(settings, replace(self.context,
            run_id='v2-empty-discovery', execution_id='v2-empty-execution', attempt_id='v2-empty-attempt',
            parser_version=settings.etl.parser_version, config_sha256=settings.config_sha256,
            effective_config={}, pinned_on=None), self.context.pinned_on)[0]
        pack = simple_pack(self.f.root.parent / 'v2-empty-pack', empty=True)
        invocation = {'command': 'backfill', 'today': self.context.pinned_on.isoformat(),
                      'fixture_sha256': hashlib.sha256(pack.read_bytes()).hexdigest(),
                      'pinned_end_quarter': '2026Q4'}
        context = freeze_workflow(context, invocation, self.f.store, self.f.objects)
        dispatcher = Dispatcher(context, settings, pack, self.f.root.parent, self.f.store, self.f.objects)
        child = dispatcher.execute('discover', 'discover-v2-empty', settings,
                                  ('--mode', 'quarterly', '--discovery-id', 'v2-empty-session'))
        proof = capture_parent_provenance(child.result.source_workset_ref, self.f.store, self.f.objects)
        parent = decode_source_workset(self.f.objects.read(child.result.source_workset_ref))
        self.assertEqual(parent.members, ())
        self.assertTrue(parent.discovery_complete)
        selection = parse_json(canonical_json(to_mapping_value(self.selection(skipped=True))))
        selection.update(context=context.to_mapping(), invocation=invocation,
            discovery_call=child.call, parent_ref=child.result.source_workset_ref,
            parent_provenance=proof, discovery_session=proof['discovery']['session'],
            required_units=proof['discovery']['session']['frozen']['units'],
            directories=[d.to_mapping() for d in parent.directories],
            discovered_sources=0, unresolved_before=1)
        self.assertEqual(selection['already_complete'][0]['observation']['parser_version'],
                         'fixture-index-parser-v1')
        with self.assertRaisesRegex(Conflict, 'skipped completion capture differs'):
            freeze_selection(context, selection, self.f.store, self.f.objects)

    def test_intent_object_crash_retains_begun_start_and_missing_index_recovers(self):
        current = replace(self.context, attempt_id='intent-crash')
        original = self.f.objects.put_once
        def crash(path, body):
            if path.endswith('/intent.json'):
                raise CollectionCrash()
            return original(path, body)
        with patch.object(self.f.objects, 'put_once', side_effect=crash):
            with self.assertRaises(CollectionCrash):
                freeze_workflow(current, self.invocation, self.f.store, self.f.objects)
        begun = self.f.store.get('WorkflowAttempt', workflow_key(current)).to_mapping()['value']
        self.assertEqual(begun['context'], current.to_mapping())
        resumed = replace(current, started_at=current.started_at + timedelta(seconds=1))
        saved = freeze_workflow(resumed, self.invocation, self.f.store, self.f.objects)
        self.assertEqual(saved, current)
        self.delete_index('WorkflowAttempt', workflow_key(current))
        self.assertEqual(freeze_workflow(resumed, self.invocation, self.f.store, self.f.objects), current)

    def test_selection_object_crash_repairs_only_exact_descriptor(self):
        selection = self.selection()
        original = self.f.store.replace
        def crash(kind, key, value, version):
            if kind == 'WorkflowAttempt' and value['selection_ref'] is not None:
                raise CollectionCrash()
            return original(kind, key, value, version)
        with patch.object(self.f.store, 'replace', side_effect=crash):
            with self.assertRaises(CollectionCrash):
                freeze_selection(self.context, selection, self.f.store, self.f.objects)
        self.assertIsNone(self.f.store.get('WorkflowAttempt', workflow_key(self.context)).value['selection_ref'])
        frozen = freeze_selection(self.context, selection, self.f.store, self.f.objects)
        self.assertEqual(frozen, selection)
        descriptor = self.f.store.get('WorkflowAttempt', workflow_key(self.context)).to_mapping()['value']['selection_ref']
        self.assertEqual(set(descriptor), {'ref', 'sha256', 'bytes'})
        with self.assertRaises(Conflict):
            freeze_selection(self.context, {**selection, 'unresolved_before': 1}, self.f.store, self.f.objects)

    def test_report_receipt_descriptor_extra_fields_refuse(self):
        report = self.report()
        intent = report.to_mapping()['intent']
        intent['member_receipts'][0]['invented'] = True
        with self.assertRaises(Conflict):
            write_workflow_result(replace(report, intent=intent), self.f.store, self.f.objects)

    def test_terminal_member_report_reopens_exact_original_attempt_capture(self):
        from sec_edgar_ingest.workflows.processing import process_member
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        current = replace(self.context, attempt_id='terminal-member')
        context = freeze_workflow(current, self.invocation, self.f.store, self.f.objects)
        selection = self.selection()
        selection.update(context=context.to_mapping(), discovery_call=None, discovery_error=Error(
            'internal_error', 'discovery stopped before dispatch', False, None, {}).to_mapping(),
            parent_ref=None, parent_provenance=None, discovery_session=None,
            required_units=[], directories=[], halted=True)
        selection['gaps'].append(selection['discovery_error'])
        frozen = freeze_selection(context, selection, self.f.store, self.f.objects)
        dispatcher = Dispatcher(context, self.f.settings, self.f.pack, self.f.root.parent, self.f.store, self.f.objects)
        with patch('sec_edgar_ingest.cli.collect', side_effect=RuntimeError('retained original collection failure')):
            processed = process_member(self.f.value, context, dispatcher, self.f.store, self.f.objects)
        receipt = WorkflowMembers(self.f.store, self.f.objects).record(processed.result, context, processed.evidence)
        path = workflow_path(context).rsplit('/', 1)[0] + '/selection.json'
        body = self.f.objects.read(path)
        gaps = tuple(Error.from_mapping(value) for value in selection['gaps']) + processed.result.gaps
        outcome, counts = summarize((processed.result,), gaps, 1, 0, context.command, ())
        evidence = to_mapping_value(processed.evidence)
        intent = {'invocation': self.invocation, 'selection': {'ref': path, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)},
            'member_receipts': [receipt], 'child_calls': evidence['calls'], 'completion_captures': [],
            'repair_resolutions': [], 'already_complete_sources': [], 'discovered_sources': 1, 'unresolved_before': 0}
        report = WorkflowResult(FORMAT_VERSION, context, intent, None, ('2026Q3', '2026Q4'), (),
            (processed.result,), gaps, None, None, outcome, counts, self.published.ended_at.isoformat())
        result_ref = write_workflow_result(report, self.f.store, self.f.objects)
        self.delete_index('WorkflowAttempt', workflow_key(context))
        self.assertEqual(read_workflow_result(result_ref, self.f.store, self.f.objects), report)
        terminal_ref = evidence['terminal_error']['call']['result_ref'].rsplit('/', 1)[0] + '/terminal.json'
        target = self.f.root / 'objects' / terminal_ref
        original = target.read_bytes()
        target.write_bytes(original + b' ')
        try:
            with self.assertRaises((Conflict, ValueError)):
                read_workflow_result(result_ref, self.f.store, self.f.objects)
        finally:
            target.write_bytes(original)

    def test_repaired_report_retains_original_immutable_repair_anchor(self):
        from sec_edgar_ingest.workflows.processing import process_member
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        with patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary repair')):
            code, original_call, child = self.f.invoke('publish', self.transformed_ref)
        self.assertEqual(code, 9)
        self.assertIsNone(child)
        initial = evaluate_member(self.f.value, self.context.parser_version,
                                  self.context.schema_version, self.f.store, self.f.objects)
        self.assertEqual(len(initial.obligations), 1)
        selection = freeze_selection(self.context, self.selection(), self.f.store, self.f.objects)
        dispatcher = Dispatcher(self.context, self.f.settings, self.f.pack,
                                self.f.root.parent, self.f.store, self.f.objects)
        processed = process_member(self.f.value, self.context, dispatcher, self.f.store, self.f.objects)
        evidence = to_mapping_value(processed.evidence)
        self.assertEqual(len(evidence['resolutions']), 1)
        receipt = WorkflowMembers(self.f.store, self.f.objects).record(processed.result, self.context, processed.evidence)
        path = workflow_path(self.context).rsplit('/', 1)[0] + '/selection.json'
        body = self.f.objects.read(path)
        gaps = (self.baseline_gap,) + processed.result.gaps
        outcome, counts = summarize((processed.result,), gaps, 1, 0, self.context.command, ())
        intent = {'invocation': self.invocation, 'selection': {'ref': path, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)},
            'member_receipts': [receipt], 'child_calls': [self.f.discovery_call] + evidence['calls'],
            'completion_captures': [evidence['completion']], 'repair_resolutions': evidence['resolutions'],
            'already_complete_sources': [], 'discovered_sources': 1, 'unresolved_before': 0}
        report = WorkflowResult(FORMAT_VERSION, self.context, intent, self.f.parent_ref,
            ('2026Q3', '2026Q4'), tuple(selection['directories']), (processed.result,), gaps,
            None, None, outcome, counts, self.published.ended_at.isoformat())
        result_ref = write_workflow_result(report, self.f.store, self.f.objects)
        self.delete_index('WorkflowAttempt', workflow_key(self.context))
        for row in tuple(self.f.store.scan('WorkflowRepairObligation', {})):
            self.delete_index('WorkflowRepairObligation', row.value['call_sha256'])
        self.assertEqual(read_workflow_result(result_ref, self.f.store, self.f.objects), report)
        call_sha = hashlib.sha256(canonical_json(to_mapping_value(original_call))).hexdigest()
        anchor_ref = 'worksets/sec/workflow-repair-authority/call-sha256=' + call_sha + '/obligation.json'
        target = self.f.root / 'objects' / anchor_ref
        original = target.read_bytes()
        target.write_bytes(original + b' ')
        try:
            with self.assertRaises((Conflict, ValueError)):
                read_workflow_result(result_ref, self.f.store, self.f.objects)
        finally:
            target.write_bytes(original)

    def test_discovered_parent_members_cannot_be_coherently_omitted(self):
        selection = self.selection()
        self.assertEqual(len(decode_source_workset(self.f.objects.read(self.f.parent_ref)).members), 1)
        selection.update(members=[], jobs=[], member_provenance=[], already_complete=[])
        with self.assertRaises(Conflict):
            freeze_selection(self.context, selection, self.f.store, self.f.objects)

    def test_discovered_count_must_match_actual_parent(self):
        selection = self.selection()
        selection['discovered_sources'] = 999
        with self.assertRaises(Conflict):
            freeze_selection(self.context, selection, self.f.store, self.f.objects)

    def test_transplanted_receipt_cannot_borrow_original_child_namespace(self):
        from sec_edgar_ingest.models import parse_json
        original = self.report()
        old_descriptor = original.to_mapping()['intent']['member_receipts'][0]
        receipt = parse_json(self.f.objects.read(old_descriptor['ref']))
        context = replace(self.context, attempt_id='transplanted-receipt')
        freeze_workflow(context, self.invocation, self.f.store, self.f.objects)
        selection = self.selection()
        selection.update(context=context.to_mapping(), discovery_call=None,
            discovery_error=Error('internal_error', 'discovery stopped', False, None, {}).to_mapping(),
            parent_ref=None, parent_provenance=None, discovery_session=None, required_units=[],
            directories=[], halted=True, discovered_sources=0)
        selection['gaps'].append(selection['discovery_error'])
        freeze_selection(context, selection, self.f.store, self.f.objects)
        receipt['context'] = context.to_mapping()
        receipt_ref = workflow_path(context).rsplit('/', 1)[0] + '/members/' + original.members[0].member_id + '/result.json'
        body = canonical_json(receipt)
        self.f.objects.put_once(receipt_ref, body)
        descriptor = {**old_descriptor, 'ref': receipt_ref, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
        selection_ref = workflow_path(context).rsplit('/', 1)[0] + '/selection.json'
        selection_body = self.f.objects.read(selection_ref)
        intent = original.to_mapping()['intent']
        intent.update(selection={'ref': selection_ref, 'sha256': hashlib.sha256(selection_body).hexdigest(), 'bytes': len(selection_body)},
            member_receipts=[descriptor], child_calls=receipt['evidence']['calls'], discovered_sources=0)
        gaps = tuple(Error.from_mapping(value) for value in selection['gaps'])
        outcome, counts = summarize(original.members, gaps, 0, 0, context.command, ())
        transplanted = replace(original, context=context, intent=intent, source_workset_ref=None,
                               directories=(), gaps=gaps, outcome=outcome, counts=counts)
        with self.assertRaises(Conflict):
            write_workflow_result(transplanted, self.f.store, self.f.objects)
