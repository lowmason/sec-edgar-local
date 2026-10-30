"""Stage 1c M1–M4: the legacy publish inventory, the completion conflict text and the stop before dispatch."""
from network_guard import install
install()

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from support_workflow_evidence import EvidenceFixture, quarterly_bytes
from sec_edgar_ingest.cli import main
from sec_edgar_ingest.etl.commands import PublicationRepairPending
from sec_edgar_ingest.etl.contracts import decode_transformed
from sec_edgar_ingest.models import RunContext, canonical_json, to_mapping_value
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows import completion
from sec_edgar_ingest.workflows.completion import evaluate_member
from sec_edgar_ingest.workflows.contracts import LOCAL_CONTRACT
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from support_process import checked_clock, checked_dispatcher, checked_fault
from support_workflows import CommandHarness, simple_pack
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.models import Error, error_text, require_text
from sec_edgar_ingest.runtime import configured_descriptor
from sec_edgar_ingest.workflows.contracts import CompletionEvaluation
from sec_edgar_ingest.workflows.processing import process_member
from sec_edgar_ingest.workflows.provenance import project_member
from sec_edgar_ingest.worksets import decode_source_workset

INVENTORY = 'ordinary publication authority inventory uncertain: '
REFUSAL = 'legacy unfinished publication has no complete publishable input'
STOCK = 'child completion lacks all affected quarter/repair evidence'


def conflicting_bytes(day):
    """A quarterly body whose two rows share one key with different values, so its transform is quarantined."""
    body = ('CIK|Company Name|Form Type|Date Filed|Filename\r\n-----\r\n'
            f'123456|A|10-K|{day}|edgar/data/123456/a.txt\r\n'
            f'123456|B|10-K|{day}|edgar/data/123456/a.txt\r\n').encode()
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w') as archive:
        info = zipfile.ZipInfo('master.idx', (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, body)
    return target.getvalue()


def call_key(call):
    return hashlib.sha256(canonical_json(to_mapping_value(call))).hexdigest()


def expected_descriptor(context, objects):
    """The legacy descriptor as the 1b code builds it, from the persisted command (plan 6 P6 oracle)."""
    result_ref = f'runs/sec/{context.run_id}/publish/{context.attempt_id}/result.json'
    frozen = json.loads(objects.read(result_ref.rsplit('/', 1)[0] + '/command.json'))
    return {'contract_version': LOCAL_CONTRACT, 'format_version': 'sec-local-workflow-legacy-publish-v1',
            'context': context.to_mapping(), 'intent': frozen['intent'], 'input_ref': frozen['intent']['workset'],
            'result_ref': result_ref}


class Rewritten:
    """An object-store view that returns other bytes for one path."""

    def __init__(self, objects, path, body):
        self.objects, self.path, self.body = objects, path, body

    def read(self, path):
        return self.body if path == self.path else self.objects.read(path)

    def __getattr__(self, name):
        return getattr(self.objects, name)


class WithObligation:
    """A state-store view that holds a WorkflowRepairObligation row under one call key."""

    def __init__(self, store, key):
        self.store, self.key = store, key

    def get(self, kind, key):
        if (kind, key) == ('WorkflowRepairObligation', self.key):
            return object()
        return self.store.get(kind, key)

    def __getattr__(self, name):
        return getattr(self.store, name)


class LegacyInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = EvidenceFixture(Path(self.temp.name) / '.fixture-state')
        self.addCleanup(self.f.close)

    def evaluate(self):
        return evaluate_member(self.f.value, self.f.workflow.parser_version, self.f.workflow.schema_version,
                               self.f.store, self.f.objects)

    def transform(self, body, seconds=0):
        _, _, result = self.f.invoke('transform', self.f.snapshot_input(body, seconds))
        return result.transformed_workset_ref

    def standalone_publish(self, workset_ref, run_id, patches=()):
        """A public `publish` command outside any workflow: it leaves a legacy publish Attempt."""
        arguments = ['publish', '--config', str(self.f.config), '--run-id', run_id,
                     '--execution-id', run_id + '-execution', '--attempt-id', run_id + '-publish',
                     '--deadline', self.f.workflow.deadline.isoformat(), '--today', '2026-10-06',
                     '--workset', workset_ref]
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = main(arguments)
        row = next(r for r in self.f.store.scan('Attempt', {}) if r.value['context']['run_id'] == run_id)
        value = row.to_mapping()['value']
        return code, RunContext.from_mapping(value['context']), value

    def unfinished(self):
        return (patch('sec_edgar_ingest.cli.run_publish', side_effect=PublicationRepairPending([], [], [])),)

    def finished_incomplete(self):
        """The L12 2024Q1 shape: a finished publish whose input holds no observation."""
        ref = self.transform(conflicting_bytes('2026-07-01'))
        workset = decode_transformed(self.f.objects.read(ref))
        self.assertEqual((workset.complete, workset.observations), (False, ()))
        code, context, value = self.standalone_publish(ref, 'l12-shape')
        self.assertEqual((code, value['result']['outcome'], value['result']['quarters']), (3, 'incomplete', []))
        return ref, context

    def publish_member(self):
        """A later revision of the member publishes through the checked child, as invocation 1 did."""
        self.f.revised_member()
        ref = self.transform(quarterly_bytes('2026-07-01'), seconds=1)
        code, _, _ = self.f.invoke('publish', ref)
        self.assertEqual(code, 0)

    def test_the_descriptor_bytes_are_unchanged_for_accepted_attempts(self):
        """§5 item 2 (M1): for each accepted legacy shape, the builder's bytes and call key equal the 1b bytes."""
        complete = self.transform(quarterly_bytes('2026-07-01'))
        _, finished, _ = self.standalone_publish(complete, 'accepted-finished')
        self.f.revised_member()
        changed = self.transform(quarterly_bytes('2026-07-01', 'Changed'), seconds=1)
        _, unfinished, value = self.standalone_publish(changed, 'accepted-unfinished', self.unfinished())
        self.assertIsNone(value['result'])
        for context in (finished, unfinished):
            with self.subTest(run=context.run_id):
                expected = expected_descriptor(context, self.f.objects)
                built, workset = completion._legacy_publish_descriptor(context, self.f.objects)
                self.assertTrue(workset.complete)
                self.assertEqual(canonical_json(to_mapping_value(built)), canonical_json(to_mapping_value(expected)))
                self.assertEqual(call_key(built), call_key(expected))
                self.assertEqual(call_key(completion._legacy_publish_call(context, self.f.objects)), call_key(expected))

    def test_the_builder_does_not_refuse_an_incomplete_input(self):
        """M1: the builder builds the L12 shape. `_legacy_publish_call` still refuses it with today's message."""
        _, context = self.finished_incomplete()
        built, workset = completion._legacy_publish_descriptor(context, self.f.objects)
        self.assertFalse(workset.complete)
        self.assertEqual(canonical_json(to_mapping_value(built)),
                         canonical_json(to_mapping_value(expected_descriptor(context, self.f.objects))))
        with self.assertRaisesRegex(Conflict, f'^{REFUSAL}$'):
            completion._legacy_publish_call(context, self.f.objects)

    def test_a_finished_publish_with_an_incomplete_input_is_not_kept(self):
        """§5 item 3 (M2): the inventory builds it, does not keep it, and the member completes."""
        ref, _ = self.finished_incomplete()
        self.assertNotIn(ref, [call['input_ref'] for call in completion._publish_calls(self.f.store, self.f.objects)])
        self.publish_member()
        evaluation = self.evaluate()
        self.assertTrue(evaluation.complete, evaluation.gaps)
        self.assertEqual((evaluation.obligations, evaluation.gaps), ((), ()))

    def test_an_unfinished_publish_with_an_incomplete_input_is_kept_and_refused(self):
        """§5 item 3 and spec §4.3 item 1: a kept call with an incomplete input still raises today's message."""
        ref = self.transform(conflicting_bytes('2026-07-01'))
        _, _, value = self.standalone_publish(ref, 'unfinished-incomplete', self.unfinished())
        self.assertIsNone(value['result'])
        with self.assertRaisesRegex(Conflict, f'^{INVENTORY}{REFUSAL}$'):
            completion._publish_calls(self.f.store, self.f.objects)

    def test_a_repair_record_keeps_a_finished_incomplete_call_and_refuses_it(self):
        """§5 item 3: a WorkflowRepairObligation row or a repair authority keeps the call, and it is refused."""
        _, context = self.finished_incomplete()
        key = call_key(expected_descriptor(context, self.f.objects))
        with self.subTest('WorkflowRepairObligation row'), self.assertRaisesRegex(Conflict, f'^{INVENTORY}{REFUSAL}$'):
            completion._publish_calls(WithObligation(self.f.store, key), self.f.objects)

        def authority(call_sha256, objects):
            return {'call_sha256': call_sha256} if call_sha256 == key else None
        with self.subTest('repair authority'), patch.object(completion, '_read_repair_authority', side_effect=authority), \
                self.assertRaisesRegex(Conflict, f'^{INVENTORY}{REFUSAL}$'):
            completion._publish_calls(self.f.store, self.f.objects)

    def test_a_changed_command_or_input_address_is_still_uncertain(self):
        """§5 item 3 and spec §4.3 item 2: every other builder check still runs on a call that is not kept."""
        _, context = self.finished_incomplete()
        command_path = f'runs/sec/{context.run_id}/publish/{context.attempt_id}/command.json'
        frozen = json.loads(self.f.objects.read(command_path))
        workset_path = frozen['intent']['workset']
        frozen['intent']['force'] = 'changed'
        changed_command = Rewritten(self.f.objects, command_path, canonical_json(to_mapping_value(frozen)))
        with self.subTest('command'), \
                self.assertRaisesRegex(Conflict, f'^{INVENTORY}legacy publish frozen intent differs$'):
            completion._publish_calls(self.f.store, changed_command)
        self.f.revised_member()
        other = self.transform(quarterly_bytes('2026-07-01'), seconds=1)
        changed_input = Rewritten(self.f.objects, workset_path, self.f.objects.read(other))
        with self.subTest('input address'), \
                self.assertRaisesRegex(Conflict, f'^{INVENTORY}legacy publish transformed input address differs$'):
            completion._publish_calls(self.f.store, changed_input)


class ProcessMemberTests(unittest.TestCase):
    EVALUATE = 'sec_edgar_ingest.workflows.processing.evaluate_member'

    def scratch(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def prepare(self):
        """One fresh daily member, as in test_workflow_processing.ProcessingTests.prepare."""
        root = self.scratch()
        h = CommandHarness(root, simple_pack(root / 'pack'))
        self.addCleanup(h.close)
        now = datetime.now(timezone.utc)
        context = RunContext('processing', 'manual', 'daily', 'a', h.settings.etl.parser_version,
            h.settings.etl.schema_version, h.settings.config_sha256, now, now + timedelta(seconds=1800), 'daily',
            runtime=configured_descriptor(h.settings), format_version='sec-local-run-context-v1')
        context = pin_context(h.settings, context, date(2026, 10, 7))[0]
        dispatcher = checked_dispatcher(context, h.settings, h.pack, root, h.store, h.objects)
        found = dispatcher.execute('discover', 'discover', h.settings,
                                   ('--mode', 'daily', '--discovery-id', 'processing-daily'))
        parent = decode_source_workset(h.objects.read(found.result.source_workset_ref))
        value = project_member(found.result.source_workset_ref, parent.members[0].source_id, h.store, h.objects)
        return h, context, dispatcher, value

    def gap(self, code, message, retryable, value):
        return Error(code, message, retryable, value['source']['source_id'],
                     {'type': 'Conflict'} if code == 'state_conflict' else {})

    def test_the_completion_conflict_names_each_gap_in_order(self):
        """§5 item 5 (M3): one line, the stock text, then each gap's code and message in order."""
        h, context, dispatcher, value = self.prepare()
        gaps = (self.gap('publication_pending', 'affected quarter has no publication', True, value),
                self.gap('state_conflict', INVENTORY + REFUSAL, False, value))
        seen = []

        def second_incomplete(*args):
            seen.append(args)
            return evaluate_member(*args) if len(seen) == 1 else CompletionEvaluation(False, None, (), gaps)
        with patch(self.EVALUATE, side_effect=second_incomplete), self.assertRaises(Conflict) as raised:
            process_member(value, context, dispatcher, h.store, h.objects)
        expected = (f'{STOCK}: publication_pending: affected quarter has no publication; '
                    f'state_conflict: {INVENTORY}{REFUSAL}')
        self.assertIs(type(raised.exception), Conflict)
        self.assertEqual(str(raised.exception), expected)
        self.assertEqual(error_text(raised.exception), expected)
        require_text(expected, 'message')
        self.assertEqual(len(seen), 2)

    def test_a_non_retryable_gap_stops_the_member_before_dispatch(self):
        """§5 item 6 (M4): no child runs and no pointer moves. Only the non-retryable gaps are named."""
        h, context, dispatcher, value = self.prepare()
        gaps = (self.gap('state_conflict', 'first fixture conflict', False, value),
                self.gap('publication_pending', 'affected quarter has no publication', True, value),
                self.gap('state_conflict', 'second fixture conflict', False, value))
        dispatched = []
        with patch(self.EVALUATE, return_value=CompletionEvaluation(False, None, (), gaps)), \
                patch.object(dispatcher, 'execute', side_effect=lambda *args: dispatched.append(args)), \
                self.assertRaises(Conflict) as raised:
            process_member(value, context, dispatcher, h.store, h.objects)
        self.assertEqual(str(raised.exception),
                         f"member {value['member_id']} completion check cannot pass before dispatch: "
                         'state_conflict: first fixture conflict; state_conflict: second fixture conflict')
        self.assertEqual(dispatched, [])
        self.assertEqual(tuple(h.store.scan('QuarterPublication', {})), ())

    def test_retryable_gaps_dispatch_as_today(self):
        """§5 item 6 (M4): a member that starts with only retryable gaps runs its children."""
        h, context, dispatcher, value = self.prepare()
        pending = (self.gap('transform_pending', 'member has no current Processing identity', True, value),)
        seen = []

        def first_pending(*args):
            seen.append(args)
            return CompletionEvaluation(False, None, (), pending) if len(seen) == 1 else evaluate_member(*args)
        with patch(self.EVALUATE, side_effect=first_pending):
            processed = process_member(value, context, dispatcher, h.store, h.objects)
        self.assertEqual(processed.result.outcome, 'success')
        self.assertEqual(len(processed.result.child_refs), 3)

    def test_obligations_take_the_repair_path_even_with_a_non_retryable_gap(self):
        """§5 item 6, mixed case (M4): obligations repair as today; the :96 check stays the final guard."""
        with tempfile.TemporaryDirectory() as tmp:
            f = EvidenceFixture(Path(tmp) / '.fixture-state')
            try:
                _, _, transformed = f.invoke('transform', f.snapshot_input(quarterly_bytes('2026-07-01')))
                with checked_fault(f.root):
                    code, _, result = f.invoke('publish', transformed.transformed_workset_ref)
                self.assertEqual((code, result), (9, None))
                pointers = [r.to_mapping() for r in f.store.scan('QuarterPublication', {})]
                clock = f.workflow.deadline + timedelta(seconds=1)
                fresh = replace(f.workflow, attempt_id='fresh-repair', started_at=clock,
                                deadline=clock + timedelta(seconds=3600))
                dispatcher = checked_dispatcher(fresh, f.settings, f.pack, f.root.parent, f.store, f.objects)
                seen = []

                def mixed(*args):
                    evaluation = evaluate_member(*args)
                    if seen:
                        return evaluation
                    seen.append(evaluation)
                    self.assertEqual(len(evaluation.obligations), 1)
                    extra = Error('state_conflict', 'fixture non-retryable gap', False,
                                  f.value['source']['source_id'], {'type': 'Conflict'})
                    return replace(evaluation, gaps=evaluation.gaps + (extra,))
                with checked_clock(f.root, clock), patch('sec_edgar_ingest.cli.Clock.now', return_value=clock), \
                        patch(self.EVALUATE, side_effect=mixed):
                    processed = process_member(f.value, fresh, dispatcher, f.store, f.objects)
                self.assertIn(processed.result.outcome, ('success', 'unchanged'))
                self.assertEqual(len(processed.evidence['resolutions']), 1)
                self.assertEqual([r.to_mapping() for r in f.store.scan('QuarterPublication', {})], pointers)
            finally:
                f.close()


if __name__ == '__main__':
    unittest.main()
