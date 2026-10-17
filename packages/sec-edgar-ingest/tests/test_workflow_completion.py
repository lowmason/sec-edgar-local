from sec_edgar_ingest.models import to_mapping_value
# tests/test_workflow_completion.py
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from support_workflow_evidence import EvidenceFixture, quarterly_bytes
from sec_edgar_ingest.etl.contracts import decode_transformed
from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows.completion import (
    evaluate_member, resolve_repair, validate_capture, validate_resolution,
)


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = EvidenceFixture(Path(self.temp.name) / '.fixture-state')
        self.addCleanup(self.f.close)
        self.parser = self.f.workflow.parser_version
        self.schema = self.f.workflow.schema_version

    def evaluate(self):
        return evaluate_member(self.f.value, self.parser, self.schema,
                               self.f.store, self.f.objects)

    def transform(self, body, seconds=0):
        code, call, result = self.f.invoke('transform', self.f.snapshot_input(body, seconds))
        self.assertEqual(code, 0)
        return result.transformed_workset_ref

    def test_unsafe_evaluation_exception_text_is_recorded_as_one_line_gap(self):
        for name, exception, message in (
                ('empty', Conflict(''), 'Conflict'),
                ('multi-line', OSError('member blob unreadable\nRequestId: fixture'), 'member blob unreadable RequestId: fixture'),
                ('safe', Conflict('member projection differs'), 'member projection differs')):
            with self.subTest(name), patch('sec_edgar_ingest.workflows.completion.read_member', side_effect=exception):
                evaluation = self.evaluate()
                self.assertFalse(evaluation.complete)
                self.assertEqual([(gap.code, gap.message, gap.details['type']) for gap in evaluation.gaps],
                                 [('state_conflict', message, type(exception).__name__)])

    def test_unsafe_member_inventory_text_is_recorded_as_one_line_gap(self):
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        rows = len(tuple(self.f.store.scan('WorkflowMember', {})))
        for name, exception, message in (('empty', ValueError(''), 'ValueError'),
                                         ('multi-line', ValueError('member ref\nunreadable'), 'member ref unreadable')):
            with self.subTest(name), patch('sec_edgar_ingest.workflows.members.read_member', side_effect=exception):
                valid, gaps = WorkflowMembers(self.f.store, self.f.objects).inventory()
                self.assertEqual(valid, ())
                self.assertEqual([(gap.code, gap.message) for gap in gaps], [('legacy_member_unresolved', message)] * rows)

    def test_unsafe_legacy_member_text_is_recorded_as_one_line_gap(self):
        from sec_edgar_ingest.workflows.legacy import bootstrap_legacy
        for name, exception, message in (('empty', Conflict(''), 'Conflict'),
                                         ('multi-line', Conflict('member ref\nunreadable'), 'member ref unreadable')):
            with self.subTest(name), patch('sec_edgar_ingest.workflows.legacy.read_member', side_effect=exception):
                gaps = bootstrap_legacy(self.f.store, self.f.objects)
                self.assertEqual({(gap.details['record_kind'], gap.message) for gap in gaps}, {('WorkflowMember', message)})

    def test_formerly_affected_quarter_stays_unresolved(self):
        original = self.transform(quarterly_bytes('2026-07-01'))
        self.assertEqual(self.f.invoke('publish', original)[0], 0)
        state = EtlState(self.f.store)
        q3 = state.pointer('2026Q3')
        self.assertTrue(self.evaluate().complete)
        self.f.revised_member()
        replacement = self.transform(quarterly_bytes('2026-10-01'), seconds=1)
        code, call, result = self.f.invoke('publish', replacement)
        self.assertEqual(code, 7)
        self.assertEqual({q.quarter: q.outcome for q in result.quarters},
                         {'2026Q3': 'invalid_source', '2026Q4': 'published'})
        new = decode_transformed(self.f.objects.read(replacement)).observations[0]
        self.assertEqual(dict(new.quarter_counts), {'2026Q4': 1})
        self.assertFalse(self.evaluate().complete)
        self.assertEqual(state.pointer('2026Q3'), q3)
        self.assertEqual(len(list(read_quarter(capture_quarter('2026Q4', self.f.objects, state),
                                               self.f.objects))), 1)
        self.assertEqual(len(list(read_quarter(capture_quarter('2026Q3', self.f.objects, state),
                                               self.f.objects))), 1)

    def test_current_index_identity_is_decoded_not_assumed(self):
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        self.f.invoke('publish', transformed)
        row = next(self.f.store.scan('Processing', {}))
        value = row.to_mapping()['value']
        value['observation']['parser_version'] = 'fixture-index-parser-v2'
        self.f.store.replace('Processing', value['processing_key'], value, row.version)
        evaluation = self.evaluate()
        self.assertFalse(evaluation.complete)
        self.assertTrue(evaluation.gaps)

    def test_historical_capture_survives_pointer_advance(self):
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        self.f.invoke('publish', transformed)
        captured = self.evaluate().capture
        self.f.revised_member()
        changed = self.transform(quarterly_bytes('2026-07-01', 'Changed'), seconds=1)
        self.f.invoke('publish', changed)
        validate_capture(captured, self.f.objects)
        self.assertNotEqual(captured['quarters'][0]['generation_id'],
                            EtlState(self.f.store).pointer('2026Q3').value['generation_id'])

    def test_fresh_attempt_resolves_repair_without_rewriting_original_attempt(self):
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        original = EtlState._record_membership
        fired = []
        def fail_once(state, *args):
            if not fired:
                fired.append(True)
                raise Conflict('retained ordinary ancillary failure')
            return original(state, *args)
        with patch.object(EtlState, '_record_membership', fail_once):
            code, failed_call, result = self.f.invoke('publish', transformed)
        self.assertEqual(code, 9)
        self.assertIsNone(result)
        evaluation = self.evaluate()
        self.assertFalse(evaluation.complete)
        self.assertEqual(len(evaluation.obligations), 1)
        old_attempt = [r.to_mapping() for r in self.f.store.scan('Attempt', {})
                       if r.value['context']['attempt_id'] == failed_call['context']['attempt_id']]
        pointers = [r.to_mapping() for r in self.f.store.scan('QuarterPublication', {})]
        self.f.workflow = __import__('dataclasses').replace(self.f.workflow, attempt_id='fresh-workflow')
        code, fresh_call, result = self.f.invoke('publish', transformed)
        self.assertEqual(code, 0)
        self.assertEqual(result.quarters[0].outcome, 'unchanged')
        resolution = resolve_repair(evaluation.obligations[0], fresh_call,
                                    self.f.store, self.f.objects)
        validate_resolution(resolution, self.f.store, self.f.objects)
        self.assertTrue(self.evaluate().complete)
        self.assertEqual([r.to_mapping() for r in self.f.store.scan('QuarterPublication', {})], pointers)
        self.assertEqual([r.to_mapping() for r in self.f.store.scan('Attempt', {})
                          if r.value['context']['attempt_id'] == failed_call['context']['attempt_id']], old_attempt)

    def test_missing_result_after_deadline_requires_fresh_attempt(self):
        from dataclasses import replace
        from sec_edgar_ingest.state import attempt_key
        from sec_edgar_ingest.models import RunContext
        from sec_edgar_ingest.workflows.checked import Dispatcher
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        with patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary')):
            code, call, result = self.f.invoke('publish', transformed)
        obligation = self.evaluate().obligations[0]
        self.assertEqual(code, 9)
        actual_key = attempt_key(RunContext.from_mapping(call['context']))
        old_attempt = self.f.store.get('Attempt', actual_key).to_mapping()
        command_ref = call['result_ref'].rsplit('/', 1)[0] + '/command.json'
        command_body = self.f.objects.read(command_ref)
        clock = self.f.workflow.deadline + timedelta(seconds=1)
        dispatcher = Dispatcher(self.f.workflow, self.f.settings, self.f.pack,
                                self.f.root.parent, self.f.store, self.f.objects)
        with patch('sec_edgar_ingest.cli.Clock.now', return_value=clock), self.assertRaises(Conflict):
            dispatcher.execute('publish', call['step_id'], self.f.settings,
                               ('--workset', transformed))
        self.assertEqual(self.f.store.get('Attempt', actual_key).to_mapping(), old_attempt)
        self.assertEqual(self.f.objects.read(command_ref), command_body)
        self.assertFalse(self.evaluate().complete)
        self.f.workflow = replace(self.f.workflow, attempt_id='fresh-after-expiry',
                                  started_at=clock, deadline=clock + timedelta(seconds=3600))
        with patch('sec_edgar_ingest.cli.Clock.now', return_value=clock):
            code, fresh_call, result = self.f.invoke('publish', transformed)
        self.assertEqual(code, 0)
        resolve_repair(obligation, fresh_call, self.f.store, self.f.objects)
        self.assertTrue(self.evaluate().complete)
        self.assertEqual(self.f.store.get('Attempt', actual_key).to_mapping(), old_attempt)

    def test_ordinary_public_publish_failure_is_pending_in_fresh_workflow(self):
        import contextlib
        import io
        from dataclasses import replace
        from sec_edgar_ingest.cli import main
        from sec_edgar_ingest.models import RunContext, parse_json
        from sec_edgar_ingest.state import attempt_key
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        original_method = EtlState._record_membership
        failures = []
        def fail_once(state, *args):
            if not failures:
                failures.append(True)
                raise Conflict('ordinary legacy ancillary repair failure')
            return original_method(state, *args)
        stdout = io.StringIO()
        arguments = ['publish', '--config', str(self.f.config),
            '--run-id', 'ordinary-legacy-run', '--execution-id', 'ordinary-legacy-execution',
            '--attempt-id', 'ordinary-legacy-publish',
            '--deadline', self.f.workflow.deadline.isoformat(),
            '--state-dir', str(self.f.root.parent), '--today', '2026-10-06',
            '--workset', transformed]
        with patch.object(EtlState, '_record_membership', fail_once), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            code = main(arguments)
        self.assertEqual(code, 9)
        legacy_rows = [r for r in self.f.store.scan('Attempt', {})
                       if r.value['context']['run_id'] == 'ordinary-legacy-run']
        self.assertEqual(len(legacy_rows), 1)
        original_row = legacy_rows[0].to_mapping()
        context = RunContext.from_mapping(original_row['value']['context'])
        self.assertIsNone(original_row['value']['result'])
        result_ref = f'runs/sec/{context.run_id}/publish/{context.attempt_id}/result.json'
        command_ref = result_ref.rsplit('/', 1)[0] + '/command.json'
        original_command = self.f.objects.read(command_ref)
        with self.assertRaises(FileNotFoundError):
            self.f.objects.read(result_ref)
        self.assertFalse(any(row.value['context']['run_id'] == 'ordinary-legacy-run'
                             for row in self.f.store.scan('WorkflowChildCall', {})))
        pointers = [r.to_mapping() for r in self.f.store.scan('QuarterPublication', {})]
        self.f.workflow = replace(self.f.workflow, run_id='fresh-workflow-after-legacy',
                                  attempt_id='fresh-after-legacy', command='daily', priority='daily')
        evaluation = self.evaluate()
        self.assertFalse(evaluation.complete)
        self.assertEqual(len(evaluation.obligations), 1)
        payload = parse_json(self.f.objects.read(evaluation.obligations[0]['ref']))
        self.assertEqual(payload['call']['format_version'], 'sec-workflow-legacy-publish-v1')
        self.assertEqual(payload['call']['context'], context.to_mapping())
        self.assertEqual(payload['call']['input_ref'], transformed)
        code, fresh_call, repaired = self.f.invoke('publish', transformed)
        self.assertEqual(code, 0)
        self.assertEqual(repaired.quarters[0].outcome, 'unchanged')
        resolution = resolve_repair(evaluation.obligations[0], fresh_call,
                                    self.f.store, self.f.objects)
        validate_resolution(resolution, self.f.store, self.f.objects)
        self.assertTrue(self.evaluate().complete)
        self.assertEqual([r.to_mapping() for r in self.f.store.scan('QuarterPublication', {})], pointers)
        self.assertEqual(self.f.store.get('Attempt', attempt_key(context)).to_mapping(), original_row)
        self.assertEqual(self.f.objects.read(command_ref), original_command)
        with self.assertRaises(FileNotFoundError):
            self.f.objects.read(result_ref)
        from sec_edgar_ingest.workflows.completion import validate_resolution_capture
        self.f.revised_member()
        newer = self.transform(quarterly_bytes('2026-07-01', 'Changed'), seconds=1)
        self.assertEqual(self.f.invoke('publish', newer)[0], 0)
        validate_resolution_capture(resolution, self.f.objects)
        advanced = [r.to_mapping() for r in self.f.store.scan('QuarterPublication', {})]
        self.assertNotEqual(advanced, pointers)
        after_advance = self.evaluate()
        self.assertTrue(after_advance.complete)
        self.assertEqual(after_advance.obligations, ())
        self.assertEqual(self.f.store.get('Attempt', attempt_key(context)).to_mapping(), original_row)
        self.assertEqual(self.f.objects.read(command_ref), original_command)
    def test_copied_obligation_must_bind_original_command_and_exact_input(self):
        from copy import deepcopy
        import hashlib
        from sec_edgar_ingest.models import canonical_json, parse_json
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        with patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary repair')):
            code, original_call, result = self.f.invoke('publish', transformed)
        self.assertEqual(code, 9)
        obligation = self.evaluate().obligations[0]
        original = parse_json(self.f.objects.read(obligation['ref']))
        self.f.workflow = __import__('dataclasses').replace(self.f.workflow,
                                                           attempt_id='fresh-tamper-proof')
        code, fresh_call, result = self.f.invoke('publish', transformed)
        self.assertEqual(code, 0)
        variants = []
        changed = deepcopy(original)
        changed['context']['execution_id'] = 'copied-foreign-execution'
        variants.append(changed)
        changed = deepcopy(original)
        changed['call']['workflow_attempt_id'] = 'copied-foreign-workflow'
        variants.append(changed)
        changed = deepcopy(original)
        changed['transformed_ref'] = 'worksets/sec/transformed/sha256=' + 'f' * 64 + '/workset.json'
        variants.append(changed)
        changed = deepcopy(original)
        changed['sources'] = []
        variants.append(changed)
        changed = deepcopy(original)
        changed['affected_quarters'] = []
        variants.append(changed)
        resolutions_before = [row.to_mapping() for row in self.f.store.scan('WorkflowRepairResolution', {})]
        for variant in variants:
            body = canonical_json(to_mapping_value(variant))
            digest = hashlib.sha256(body).hexdigest()
            path = f'worksets/sec/workflow-repairs/sha256={digest}/evidence.json'
            self.f.objects.put_once(path, body)
            descriptor = {'ref': path, 'sha256': digest, 'bytes': len(body),
                          'format_version': 'sec-workflow-repair-obligation-v1'}
            with self.subTest(variant=variant), self.assertRaises((Conflict, ValueError, FileNotFoundError)):
                resolve_repair(descriptor, fresh_call, self.f.store, self.f.objects)
        self.assertEqual([row.to_mapping() for row in self.f.store.scan('WorkflowRepairResolution', {})],
                         resolutions_before)
        resolution = resolve_repair(obligation, fresh_call, self.f.store, self.f.objects)
        validate_resolution(resolution, self.f.store, self.f.objects)

    def test_old_failed_parent_remains_valid_after_same_session_directory_repair(self):
        from datetime import date
        from support import discovery_harness, listing_response, failed_response
        from sec_edgar_ingest.workflows.provenance import project_member
        from sec_edgar_ingest.workflows.completion import capture_member_provenance, validate_member_provenance
        with tempfile.TemporaryDirectory() as tmp:
            h = discovery_harness(Path(tmp), {
                '2026Q3': [failed_response(404), listing_response('2026Q3', [])],
                '2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                old = h.run('daily', date(2026, 10, 7), 'same-directory-session')
                self.assertFalse(old.discovery_complete)
                value = project_member(h.workset_path(old), old.members[0].source_id, h.store, h.objects)
                newer = h.run('daily', date(2026, 10, 7), 'same-directory-session')
                self.assertTrue(newer.discovery_complete)
                proof = capture_member_provenance(value, h.store, h.objects)
                validate_member_provenance(proof, h.objects)
                self.assertFalse(proof['parent']['discovery_complete'])
                failed = [p for p in proof['discovery']['progress']
                          if p['value']['outcome']['outcome'] == 'discovery_failed']
                self.assertEqual(len(failed), 1)
                self.assertEqual(failed[0]['value']['members'], [])
            finally:
                h.close()


    def test_historical_provenance_rejects_session_and_registry_corruption(self):
        from copy import deepcopy
        from sec_edgar_ingest.workflows.completion import (
            capture_member_provenance, validate_member_provenance,
        )
        proof = capture_member_provenance(self.f.value, self.f.store, self.f.objects)
        variants = []
        altered = deepcopy(proof)
        altered['discovery']['session']['registered'] = 'copied-registration'
        variants.append(altered)
        altered = deepcopy(proof)
        altered['member']['copied_registry_field'] = True
        variants.append(altered)
        for altered in variants:
            with self.subTest(altered=altered), self.assertRaises((Conflict, ValueError)):
                validate_member_provenance(altered, self.f.objects)

    def test_completion_capture_rejects_corrupt_session(self):
        from copy import deepcopy
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        self.assertEqual(self.f.invoke('publish', transformed)[0], 0)
        captured = deepcopy(self.evaluate().to_mapping()['capture'])
        captured['discovery']['session']['registered'] = 'copied-registration'
        with self.assertRaises((Conflict, ValueError)):
            validate_capture(captured, self.f.objects)

    def test_divergent_binding_winner_is_preserved_during_evaluation(self):
        from support import fixture_snapshot
        from sec_edgar_ingest.state import AcquisitionState
        from sec_edgar_ingest.workflows.provenance import transfer_binding
        self.f.snapshot_input(quarterly_bytes('2026-07-01'))
        state = AcquisitionState(self.f.store)
        key = self.f.value['member_id'] + ':' + self.f.source.source_id
        before = self.f.store.get('Binding', key).to_mapping()
        body = quarterly_bytes('2026-07-01', 'Divergent')
        divergent = fixture_snapshot(self.f.source, body)
        self.f.objects.put_once(divergent.raw_path, body)
        state.remember_snapshot(divergent)
        with self.assertRaises(Conflict):
            transfer_binding(self.f.value, divergent, self.f.store, self.f.objects)
        self.assertFalse(self.evaluate().complete)
        self.assertEqual(self.f.store.get('Binding', key).to_mapping(), before)

    def test_historical_capture_requires_every_immutable_file(self):
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        self.assertEqual(self.f.invoke('publish', transformed)[0], 0)
        capture = self.evaluate().to_mapping()['capture']
        paths = [capture['member']['parent_ref'], capture['member']['member_ref'],
                 capture['snapshot']['raw_path'], capture['observation']['manifest_ref'],
                 capture['quarters'][0]['manifest_ref']]
        paths += [entry['value']['evidence']['receipt_path']
                  for entry in capture['discovery']['progress']
                  if entry['value']['evidence'] is not None]
        for path in paths:
            target = self.f.objects.directory / path
            original = target.read_bytes()
            target.unlink()
            try:
                with self.subTest(path=path), self.assertRaises((Conflict, ValueError, OSError)):
                    validate_capture(capture, self.f.objects)
            finally:
                target.write_bytes(original)

    def test_validated_member_provenance_returns_exact_projection(self):
        from sec_edgar_ingest.workflows.completion import (
            capture_member_provenance, validate_member_provenance,
        )
        from sec_edgar_ingest.workflows.provenance import read_member
        proof = capture_member_provenance(self.f.value, self.f.store, self.f.objects)
        self.assertEqual(validate_member_provenance(proof, self.f.objects),
                         read_member(self.f.value, self.f.store, self.f.objects))

    def test_foreign_valid_resolution_cannot_discharge_another_original_call(self):
        import hashlib
        from sec_edgar_ingest.models import canonical_json, parse_json, to_mapping_value
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        with patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary')):
            self.assertEqual(self.f.invoke('publish', transformed)[0], 9)
            self.assertEqual(self.f.invoke('publish', transformed)[0], 9)
        obligations = self.evaluate().obligations
        self.assertEqual(len(obligations), 2)
        originals = [r.to_mapping() for r in self.f.store.scan('Attempt', {})]
        self.assertEqual(self.f.invoke('publish', transformed)[0], 0)
        resolution = resolve_repair(obligations[0], self.f.calls[-1], self.f.store, self.f.objects)
        self.assertEqual(len(self.evaluate().obligations), 1)
        second = parse_json(self.f.objects.read(obligations[1]['ref']))
        key = hashlib.sha256(canonical_json(to_mapping_value(second['call']))).hexdigest()
        self.f.store.insert('WorkflowRepairResolution', key, resolution)
        evaluation = self.evaluate()
        self.assertFalse(evaluation.complete)
        self.assertTrue(evaluation.gaps)
        for old in originals:
            from sec_edgar_ingest.models import RunContext
            from sec_edgar_ingest.state import attempt_key
            self.assertEqual(self.f.store.get('Attempt', attempt_key(
                RunContext.from_mapping(old['value']['context']))).to_mapping(), old)

    def test_corrupt_begun_checked_call_blocks_completion(self):
        from sec_edgar_ingest.models import RunContext
        from sec_edgar_ingest.state import attempt_key
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        with patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary')):
            code, call, _ = self.f.invoke('publish', transformed)
        self.assertEqual(code, 9)
        self.assertEqual(self.f.invoke('publish', transformed)[0], 0)
        command = call['result_ref'].rsplit('/', 1)[0] + '/command.json'
        attempt = self.f.store.get('Attempt', attempt_key(RunContext.from_mapping(call['context'])))
        for path in (command, transformed):
            target = self.f.objects.directory / path
            body = target.read_bytes()
            target.unlink()
            try:
                with self.subTest(path=path):
                    evaluated = self.evaluate()
                    self.assertFalse(evaluated.complete)
                    self.assertTrue(evaluated.gaps)
            finally:
                target.write_bytes(body)
        from sec_edgar_ingest.storage.contracts import identity, table_for
        original_key = attempt_key(RunContext.from_mapping(call['context']))
        partition, row_key = identity('Attempt', original_key)
        with self.f.store._connection() as connection:
            connection.execute('DELETE FROM records WHERE table_name=? AND partition=? AND key=?',
                               (table_for('Attempt'), partition, row_key))
            connection.commit()
        missing_attempt = self.evaluate()
        self.assertFalse(missing_attempt.complete)
        self.assertTrue(missing_attempt.gaps)
        restored = self.f.store.insert('Attempt', original_key, attempt.to_mapping()['value'])
        altered = attempt.to_mapping()['value']
        altered['context']['execution_id'] = 'corrupt-begun-execution'
        self.f.store.replace('Attempt', original_key, altered, restored.version)
        self.assertFalse(self.evaluate().complete)
        self.assertTrue(self.evaluate().gaps)

    def test_corrupt_begun_ordinary_call_blocks_completion(self):
        import contextlib
        import io
        from sec_edgar_ingest.cli import main
        from sec_edgar_ingest.models import RunContext
        from sec_edgar_ingest.results import result_path
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        arguments = ['publish', '--config', str(self.f.config),
            '--run-id', 'corrupt-ordinary-run', '--execution-id', 'corrupt-ordinary-execution',
            '--attempt-id', 'corrupt-ordinary-attempt', '--deadline', self.f.workflow.deadline.isoformat(),
            '--state-dir', str(self.f.root.parent), '--today', '2026-10-06', '--workset', transformed]
        with (patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary')),
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            self.assertEqual(main(arguments), 9)
        self.assertEqual(self.f.invoke('publish', transformed)[0], 0)
        row = next(r for r in self.f.store.scan('Attempt', {})
                   if r.value['context']['run_id'] == 'corrupt-ordinary-run')
        context = RunContext.from_mapping(row.to_mapping()['value']['context'])
        command = result_path(context).rsplit('/', 1)[0] + '/command.json'
        (self.f.objects.directory / command).unlink()
        evaluated = self.evaluate()
        self.assertFalse(evaluated.complete)
        self.assertTrue(evaluated.gaps)

    def test_valid_checked_call_before_begin_has_no_repair_obligation(self):
        from sec_edgar_ingest.workflows.checked import Dispatcher
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        self.assertEqual(self.f.invoke('publish', transformed)[0], 0)
        def before_begin(point):
            if point == 'workflow_child.after_call':
                raise Conflict('retained valid call before begin')
        dispatcher = Dispatcher(self.f.workflow, self.f.settings, self.f.pack,
                                self.f.root.parent, self.f.store, self.f.objects,
                                observer=before_begin)
        with self.assertRaises(Conflict):
            dispatcher.execute('publish', 'not-begun', self.f.settings, ('--workset', transformed))
        evaluated = self.evaluate()
        self.assertTrue(evaluated.complete)
        self.assertEqual(evaluated.obligations, ())
        self.assertEqual(evaluated.gaps, ())

    def test_copied_obligation_cannot_drop_only_formerly_affected_quarter(self):
        import hashlib
        import io
        import zipfile
        from copy import deepcopy
        from sec_edgar_ingest.models import canonical_json, parse_json, to_mapping_value
        from sec_edgar_ingest.workflows.completion import validate_resolution_capture
        with zipfile.ZipFile(io.BytesIO(quarterly_bytes('2026-07-01'))) as archive:
            body = archive.read('master.idx')
        body += b'123456|Former|10-K|2026-10-01|edgar/data/123456/b.txt\r\n'
        target = io.BytesIO()
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('master.idx', body)
        initial = self.transform(target.getvalue())
        self.assertEqual(self.f.invoke('publish', initial)[0], 0)
        self.f.revised_member()
        replacement = self.transform(quarterly_bytes('2026-07-01', 'Changed'), seconds=1)
        with patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary')):
            self.assertEqual(self.f.invoke('publish', replacement)[0], 9)
        obligation = self.evaluate().obligations[0]
        original = parse_json(self.f.objects.read(obligation['ref']))
        self.assertEqual(original['affected_quarters'], ['2026Q3', '2026Q4'])
        self.assertEqual(set(original['sources'][0]['quarter_counts']), {'2026Q3'})
        self.assertEqual(self.f.invoke('publish', replacement)[0], 0)
        fresh_call = self.f.calls[-1]
        copied = deepcopy(original)
        copied['affected_quarters'] = ['2026Q3']
        encoded = canonical_json(to_mapping_value(copied))
        digest = hashlib.sha256(encoded).hexdigest()
        path = f'worksets/sec/workflow-repairs/sha256={digest}/evidence.json'
        self.f.objects.put_once(path, encoded)
        forged = {'ref': path, 'sha256': digest, 'bytes': len(encoded),
                  'format_version': 'sec-workflow-repair-obligation-v1'}
        before = [r.to_mapping() for r in self.f.store.scan('WorkflowRepairResolution', {})]
        with self.assertRaises((Conflict, ValueError)):
            resolve_repair(forged, fresh_call, self.f.store, self.f.objects)
        self.assertEqual([r.to_mapping() for r in self.f.store.scan('WorkflowRepairResolution', {})], before)
        resolution = resolve_repair(obligation, fresh_call, self.f.store, self.f.objects)
        validate_resolution_capture(resolution, self.f.objects)

    def test_missing_obligation_index_recovers_original_immutable_anchor(self):
        import hashlib
        from sec_edgar_ingest.models import canonical_json, parse_json, to_mapping_value
        from sec_edgar_ingest.storage.contracts import identity, table_for
        from sec_edgar_ingest.workflows.completion import outstanding_repairs
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        with patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary')):
            self.assertEqual(self.f.invoke('publish', transformed)[0], 9)
        obligation = self.evaluate().obligations[0]
        original = parse_json(self.f.objects.read(obligation['ref']))
        self.f.revised_member()
        advanced = self.transform(quarterly_bytes('2026-07-01', 'Advanced'), seconds=1)
        self.assertEqual(self.f.invoke('publish', advanced)[0], 0)
        key = hashlib.sha256(canonical_json(to_mapping_value(original['call']))).hexdigest()
        partition, row_key = identity('WorkflowRepairObligation', key)
        with self.f.store._connection() as connection:
            connection.execute('DELETE FROM records WHERE table_name=? AND partition=? AND key=?',
                               (table_for('WorkflowRepairObligation'), partition, row_key))
            connection.commit()
        with patch('sec_edgar_ingest.workflows.completion._affected_quarters',
                   side_effect=AssertionError('must recover immutable original quarter set')):
            recovered = outstanding_repairs(self.f.value, self.f.store, self.f.objects)
            self.assertEqual(canonical_json(to_mapping_value(recovered)),
                             canonical_json(to_mapping_value((obligation,))))
        indexed = self.f.store.get('WorkflowRepairObligation', key).to_mapping()['value']['descriptor']
        self.assertEqual(canonical_json(to_mapping_value(indexed)),
                         canonical_json(to_mapping_value(obligation)))

    def test_original_anchor_precedes_index_and_corruption_cannot_redefine_it(self):
        import hashlib
        from sec_edgar_ingest.models import canonical_json, parse_json, to_mapping_value
        transformed = self.transform(quarterly_bytes('2026-07-01'))
        with patch.object(EtlState, '_record_membership', side_effect=Conflict('ancillary')):
            code, call, _ = self.f.invoke('publish', transformed)
        self.assertEqual(code, 9)
        key = hashlib.sha256(canonical_json(to_mapping_value(call))).hexdigest()
        path = f'worksets/sec/workflow-repair-authority/call-sha256={key}/obligation.json'
        insert = self.f.store.insert
        checked = []
        def anchor_before_index(kind, row_key, value):
            if kind == 'WorkflowRepairObligation':
                authority = parse_json(self.f.objects.read(path))
                self.assertEqual(authority, {'format_version': 'sec-workflow-repair-authority-v1',
                    'call_sha256': key, 'descriptor': value['descriptor']})
                checked.append(True)
            return insert(kind, row_key, value)
        with patch.object(self.f.store, 'insert', side_effect=anchor_before_index):
            obligation = self.evaluate().obligations[0]
        self.assertEqual(checked, [True])
        row = self.f.store.get('WorkflowRepairObligation', key)
        before = row.to_mapping()
        target = self.f.objects.directory / path
        original = target.read_bytes()
        target.unlink()
        try:
            self.assertFalse(self.evaluate().complete)
            self.assertTrue(self.evaluate().gaps)
            self.assertEqual(self.f.store.get('WorkflowRepairObligation', key).to_mapping(), before)
        finally:
            target.write_bytes(original)
        altered = row.to_mapping()['value']
        altered['descriptor'] = {**obligation, 'sha256': 'f' * 64}
        changed = self.f.store.replace('WorkflowRepairObligation', key, altered, row.version)
        evaluated = self.evaluate()
        self.assertFalse(evaluated.complete)
        self.assertTrue(evaluated.gaps)
        self.assertEqual(self.f.store.get('WorkflowRepairObligation', key), changed)
        self.assertEqual(target.read_bytes(), original)

        malformed = {**altered, 'descriptor': None}
        corrupted = self.f.store.replace('WorkflowRepairObligation', key, malformed, changed.version)
        evaluated = self.evaluate()
        self.assertFalse(evaluated.complete)
        self.assertTrue(evaluated.gaps)
        self.assertEqual(self.f.store.get('WorkflowRepairObligation', key), corrupted)
        self.assertEqual(target.read_bytes(), original)
