from network_guard import install
install()
from sec_edgar_ingest.models import to_mapping_value
import hashlib, json, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from support_workflows import BASE, CommandHarness, simple_pack
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.models import RunContext, canonical_json
from sec_edgar_ingest.worksets import decode_source_workset
from sec_edgar_ingest.workflows.checked import Dispatcher
from sec_edgar_ingest.workflows.provenance import project_member
from sec_edgar_ingest.workflows.processing import process_member

class ProcessingTests(unittest.TestCase):
    def test_retry_prefix_is_retained_without_source_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = simple_pack(root / 'pack')
            manifest = json.loads(pack.read_text())
            url = BASE + 'daily-index/2026/QTR4/master.20261001.idx'
            prefix = b'retained truncated prefix'
            sha = hashlib.sha256(prefix).hexdigest()
            (pack.parent / 'bodies' / (sha + '.body')).write_bytes(prefix)
            manifest['responses'][url].insert(0, {
                'status': 200, 'headers': {'X-Fixture': 'partial'}, 'fault': 'read_timeout',
                'body_path': 'bodies/' + sha + '.body', 'body_sha256': sha})
            pack.write_bytes(canonical_json(to_mapping_value(manifest)))
            h = CommandHarness(root, pack)
            try:
                now = datetime.now(timezone.utc)
                context = RunContext('processing', 'manual', 'daily', 'a',
                    h.settings.worker.image_digest, h.settings.etl.parser_version,
                    h.settings.etl.schema_version, h.settings.config_sha256,
                    now, now + timedelta(seconds=1800), 'daily')
                context = pin_context(h.settings, context, date(2026, 10, 7))[0]
                dispatcher = Dispatcher(context, h.settings, pack, root, h.store, h.objects)
                discovered = dispatcher.execute('discover', 'discover', h.settings,
                    ('--mode', 'daily', '--discovery-id', 'processing-daily'))
                parent = decode_source_workset(h.objects.read(discovered.result.source_workset_ref))
                value = project_member(discovered.result.source_workset_ref,
                    parent.members[0].source_id, h.store, h.objects)
                processed = process_member(value, context, dispatcher, h.store, h.objects)
                self.assertFalse(processed.result.quarantined)
                self.assertEqual(processed.result.outcome, 'success')
                self.assertTrue(processed.result.transformed)
                self.assertEqual(len(processed.result.child_refs), 3)
                self.assertTrue(any(p.read_bytes() == prefix for p in
                    (root / '.fixture-state/objects/quarantine/sec').rglob('body')))
                capture, rows = h.capture('2026Q4')
                self.assertEqual(len(rows), 1)
            finally:
                h.close()
    def prepare(self, root, *, conflicting=False, pack_edit=None):
        pack = simple_pack(root / 'pack', conflicting=conflicting)
        if pack_edit is not None:
            pack_edit(pack)
        h = CommandHarness(root, pack)
        now = datetime.now(timezone.utc)
        context = RunContext('processing', 'manual', 'daily', 'a',
            h.settings.worker.image_digest, h.settings.etl.parser_version,
            h.settings.etl.schema_version, h.settings.config_sha256,
            now, now + timedelta(seconds=1800), 'daily')
        context = pin_context(h.settings, context, date(2026, 10, 7))[0]
        dispatcher = Dispatcher(context, h.settings, h.pack, root, h.store, h.objects)
        found = dispatcher.execute('discover', 'discover', h.settings,
            ('--mode', 'daily', '--discovery-id', 'processing-daily'))
        parent = decode_source_workset(h.objects.read(found.result.source_workset_ref))
        value = project_member(found.result.source_workset_ref, parent.members[0].source_id, h.store, h.objects)
        return h, context, dispatcher, value

    def test_genuine_conflicting_source_has_no_accepted_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp), conflicting=True)
            try:
                processed = process_member(value, context, dispatcher, h.store, h.objects)
                self.assertTrue(processed.result.quarantined)
                self.assertFalse(processed.result.transformed)
                self.assertEqual(processed.result.outcome, 'quarantined')
                self.assertEqual(tuple(h.store.scan('Processing', {})), ())
                self.assertEqual(tuple(h.store.scan('QuarterPublication', {})), ())
                self.assertTrue(any(g.details for g in processed.result.gaps))
            finally:
                h.close()

    def test_member_evidence_rejects_forged_version_ref_quarter_and_outcome(self):
        from dataclasses import replace
        from sec_edgar_ingest.storage.contracts import Conflict
        from sec_edgar_ingest.workflows.processing import validate_member_evidence
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp))
            try:
                processed = process_member(value, context, dispatcher, h.store, h.objects)
                result = processed.result
                variants = (replace(result, parser_version='fixture-index-parser-v2'),
                            replace(result, snapshot_ref='worksets/sec/snapshot/sha256=' + '0' * 64 + '/workset.json'),
                            replace(result, quarters=()), replace(result, outcome='unchanged'))
                for changed in variants:
                    with self.subTest(changed=changed):
                        with self.assertRaises((Conflict, ValueError, OSError, KeyError)):
                            validate_member_evidence(changed, processed.evidence, h.objects)
            finally:
                h.close()

    def test_member_receipt_is_content_first_and_replays_identically(self):
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp))
            try:
                processed = process_member(value, context, dispatcher, h.store, h.objects)
                registry = WorkflowMembers(h.store, h.objects)
                first = registry.record(processed.result, context, processed.evidence)
                retained = h.objects.read(first['ref'])
                self.assertEqual(registry.record(processed.result, context, processed.evidence), first)
                self.assertEqual(h.objects.read(first['ref']), retained)
                self.assertEqual(registry.completed(value, context.parser_version, context.schema_version),
                                 processed.evidence['completion'])
            finally:
                h.close()

    def test_refusal_retains_exact_line_and_raw_details(self):
        from sec_edgar_ingest.workflows.checked import read_child_capture
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp), conflicting=True)
            try:
                processed = process_member(value, context, dispatcher, h.store, h.objects)
                child = read_child_capture(processed.evidence['calls'][-1], h.objects)
                self.assertEqual(child.outcome, 'invalid_source')
                self.assertEqual(child.quarantined, 1)
                self.assertEqual(child.transformed, 0)
                self.assertEqual(child.gaps, processed.result.gaps)
                self.assertEqual(child.gaps[0].details['line_number'], 4)
                self.assertEqual(child.gaps[0].details['reason'], 'conflicting duplicate logical key')
                self.assertEqual(len(child.gaps[0].details['raw_sha256']), 64)
                self.assertEqual(tuple(h.store.scan('Processing', {})), ())
                self.assertEqual(tuple(h.store.scan('QuarterPublication', {})), ())
                self.assertFalse(any((Path(tmp) / '.fixture-state/objects/observations').rglob('*.parquet')))
            finally:
                h.close()

    def test_tampering_refuses_before_record(self):
        from dataclasses import replace
        from copy import deepcopy
        from sec_edgar_ingest.storage.contracts import Conflict
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp))
            try:
                processed = process_member(value, context, dispatcher, h.store, h.objects)
                result = processed.result
                variants = []
                for path, changed in (
                    (('calls', 0, 'result_ref'), result.child_refs[-1]),
                    (('completion', 'snapshot', 'sha256'), '0' * 64),
                    (('completion', 'quarters', 0, 'manifest_sha256'), '0' * 64),
                    (('calls', 1, 'context', 'parser_version'), 'fixture-index-parser-v2'),
                    (('calls', 0, 'step_id'), 'collect-other'),
                    (('terminal_error',), {'call': {}, 'outcome': 'internal_error', 'gaps': []}),
                ):
                    evidence = deepcopy(to_mapping_value(processed.evidence))
                    target = evidence
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = changed
                    variants.append((result, evidence))
                for changed in (replace(result, downloaded=False),
                                replace(result, quarantined=False, transformed=False),
                                replace(result, child_refs=result.child_refs[1:]),
                                replace(result, quarters=())):
                    variants.append((changed, processed.evidence))
                registry = WorkflowMembers(h.store, h.objects)
                for changed, evidence in variants:
                    with self.subTest(changed=changed, evidence=evidence):
                        with self.assertRaises((Conflict, ValueError, OSError, KeyError, TypeError)):
                            registry.record(changed, context, evidence)
                self.assertEqual(tuple(h.store.scan('WorkflowMemberResult', {})), ())
            finally:
                h.close()

    def test_receipt_replay_repairs_missing_index_without_dispatch(self):
        from unittest.mock import patch
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp))
            try:
                processed = process_member(value, context, dispatcher, h.store, h.objects)
                registry = WorkflowMembers(h.store, h.objects)
                with patch('sec_edgar_ingest.workflows.members.immutable', side_effect=Conflict('index interruption')):
                    with self.assertRaises(Conflict):
                        registry.record(processed.result, context, processed.evidence)
                self.assertEqual(tuple(h.store.scan('WorkflowMemberResult', {})), ())
                with patch.object(dispatcher, 'execute', side_effect=AssertionError('receipt replay dispatched')):
                    replay = process_member(value, context, dispatcher, h.store, h.objects)
                self.assertEqual(replay, processed)
                self.assertEqual(len(tuple(h.store.scan('WorkflowMemberResult', {}))), 1)
                self.assertEqual(registry.completed(value, context.parser_version, context.schema_version),
                                 processed.evidence['completion'])
            finally:
                h.close()

    def test_receipt_context_and_index_correlation_are_authoritative(self):
        from dataclasses import replace
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp))
            try:
                processed = process_member(value, context, dispatcher, h.store, h.objects)
                registry = WorkflowMembers(h.store, h.objects)
                with self.assertRaises(Conflict):
                    registry.record(processed.result, replace(context, attempt_id='foreign'), processed.evidence)
                with self.assertRaises(Conflict):
                    registry.record(processed.result, replace(context, config_sha256='0' * 64), processed.evidence)
                first = registry.record(processed.result, context, processed.evidence)
                row = next(h.store.scan('WorkflowMemberResult', {}))
                corrupted = dict(first, bytes=first['bytes'] + 1)
                import hashlib
                key = hashlib.sha256(canonical_json(to_mapping_value([context.run_id, context.command,
                    context.attempt_id, value['member_id'], context.parser_version, context.schema_version]))).hexdigest()
                h.store.replace('WorkflowMemberResult', key, corrupted, row.version)
                with self.assertRaises((Conflict, OSError, ValueError)):
                    registry.completed(value, context.parser_version, context.schema_version)
                with self.assertRaises(Conflict):
                    registry.record(processed.result, context, processed.evidence)
            finally:
                h.close()

    def test_origin_acquisition_and_current_parser_replay_do_not_borrow_versions(self):
        from dataclasses import replace
        from sec_edgar_ingest.config import Settings
        from sec_edgar_ingest.workflows.checked import read_child_capture
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp))
            try:
                first = process_member(value, context, dispatcher, h.store, h.objects)
                registry = WorkflowMembers(h.store, h.objects)
                registry.record(first.result, context, first.evidence)
                settings = Settings.from_mapping({**h.settings.to_mapping(), 'etl': {
                    **h.settings.to_mapping()['etl'], 'parser_version': 'fixture-index-parser-v2'}})
                current = pin_context(settings, replace(context, attempt_id='v2',
                    parser_version=settings.etl.parser_version, config_sha256=settings.config_sha256,
                    effective_config={}, pinned_on=None), date(2026, 10, 7))[0]
                fresh = Dispatcher(current, settings, h.pack, Path(tmp), h.store, h.objects)
                self.assertIsNone(registry.completed(value, current.parser_version, current.schema_version))
                second = process_member(value, current, fresh, h.store, h.objects)
                self.assertEqual(second.result.outcome, 'success')
                self.assertEqual(read_child_capture(second.evidence['calls'][0], h.objects).context.parser_version,
                                 'fixture-index-parser-v1')
                self.assertEqual(read_child_capture(second.evidence['calls'][1], h.objects).context.parser_version,
                                 'fixture-index-parser-v2')
                self.assertEqual(second.result.snapshot_ref, first.result.snapshot_ref)
                self.assertNotEqual(second.result.transformed_ref, first.result.transformed_ref)
                registry.record(second.result, current, second.evidence)
                self.assertEqual(registry.completed(value, current.parser_version, current.schema_version),
                                 second.evidence['completion'])
                found = fresh.execute('discover', 'fresh-discovery', settings,
                                     ('--mode', 'daily', '--discovery-id', 'fresh-parent', '--refresh'))
                new_value = project_member(found.result.source_workset_ref, value['source']['source_id'],
                                           h.store, h.objects)
                self.assertNotEqual(new_value['member_id'], value['member_id'])
                self.assertIsNone(registry.completed(new_value, current.parser_version, current.schema_version))
                self.assertEqual(registry.completed(value, context.parser_version, context.schema_version),
                                 first.evidence['completion'])
            finally:
                h.close()

    def test_malformed_source_has_no_accepted_observation_or_pointer(self):
        def malformed(pack):
            manifest = json.loads(pack.read_text())
            url = BASE + 'daily-index/2026/QTR4/master.20261001.idx'
            body = (pack.parent / manifest['responses'][url][0]['body_path']).read_bytes()
            body = body.replace(b'123456|Example', b'invalid|Example')
            sha = hashlib.sha256(body).hexdigest()
            relative = 'bodies/' + sha + '.body'
            (pack.parent / relative).write_bytes(body)
            manifest['responses'][url] = [dict(manifest['responses'][url][0],
                body_path=relative, body_sha256=sha, headers={'Content-Length': str(len(body))})] * 8
            pack.write_bytes(canonical_json(to_mapping_value(manifest)))
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp), pack_edit=malformed)
            try:
                result = process_member(value, context, dispatcher, h.store, h.objects).result
                self.assertEqual(result.outcome, 'quarantined')
                self.assertTrue(result.quarantined)
                self.assertFalse(result.transformed)
                self.assertEqual(result.gaps[0].details['line_number'], 3)
                self.assertEqual(tuple(h.store.scan('Processing', {})), ())
                self.assertEqual(tuple(h.store.scan('QuarterPublication', {})), ())
            finally:
                h.close()

    def test_fatal_collection_stops_before_etl_and_retains_all_child_gaps(self):
        def blocked(pack):
            manifest = json.loads(pack.read_text())
            url = BASE + 'daily-index/2026/QTR4/master.20261001.idx'
            manifest['responses'][url] = [dict(manifest['responses'][url][0], status=403)] * 8
            pack.write_bytes(canonical_json(to_mapping_value(manifest)))
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp), pack_edit=blocked)
            try:
                processed = process_member(value, context, dispatcher, h.store, h.objects)
                self.assertEqual(processed.result.outcome, 'access_blocked')
                self.assertFalse(processed.result.transformed)
                self.assertFalse(processed.result.quarantined)
                self.assertEqual(len(processed.evidence['calls']), 1)
                self.assertTrue(processed.result.gaps)
                self.assertEqual(tuple(h.store.scan('Processing', {})), ())
                registry = WorkflowMembers(h.store, h.objects)
                registry.record(processed.result, context, processed.evidence)
                self.assertIsNone(registry.completed(value, context.parser_version, context.schema_version))
            finally:
                h.close()

    def test_partial_q3_q4_and_gate_preserve_exact_child_outcomes(self):
        from support_workflow_evidence import EvidenceFixture, quarterly_bytes
        from sec_edgar_ingest.etl.state import EtlState
        from sec_edgar_ingest.workflows.checked import read_child_capture
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        for gate in (False, True):
            with self.subTest(gate=gate), tempfile.TemporaryDirectory() as tmp:
                f = EvidenceFixture(Path(tmp) / '.fixture-state')
                try:
                    old = quarterly_bytes('2026-07-01')
                    if gate:
                        from support_workflows import idx
                        old = idx((('123456', 'A', '10-K', '2026-07-01', 'edgar/data/123456/a.txt'),
                                   ('123456', 'B', '10-K', '2026-07-02', 'edgar/data/123456/b.txt')), 'quarterly')
                    snap = f.snapshot_input(old)
                    _, _, transformed = f.invoke('transform', snap)
                    self.assertEqual(f.invoke('publish', transformed.transformed_workset_ref)[0], 0)
                    prior = EtlState(f.store).pointer('2026Q3')
                    f.revised_member()
                    f.snapshot_input(quarterly_bytes('2026-07-01' if gate else '2026-10-01'), seconds=1)
                    dispatcher = Dispatcher(f.workflow, f.settings, f.pack, f.root.parent, f.store, f.objects)
                    processed = process_member(f.value, f.workflow, dispatcher, f.store, f.objects)
                    child = read_child_capture(processed.evidence['calls'][-1], f.objects)
                    self.assertEqual(processed.result.quarters, child.quarters)
                    self.assertEqual(processed.result.gaps, child.gaps)
                    self.assertEqual(processed.result.outcome, 'awaiting_approval' if gate else 'invalid_source')
                    self.assertEqual([q.outcome for q in child.quarters],
                                     ['awaiting_approval'] if gate else ['invalid_source', 'published'])
                    self.assertEqual(EtlState(f.store).pointer('2026Q3'), prior)
                    self.assertIsNone(processed.evidence['completion'])
                    registry = WorkflowMembers(f.store, f.objects)
                    registry.record(processed.result, f.workflow, processed.evidence)
                    self.assertIsNone(registry.completed(f.value, f.workflow.parser_version, f.workflow.schema_version))
                finally:
                    f.close()

    def test_expired_original_is_repaired_fresh_without_pointer_advance(self):
        from dataclasses import replace
        from unittest.mock import patch
        from support_workflow_evidence import EvidenceFixture, quarterly_bytes
        from sec_edgar_ingest.etl.state import EtlState
        from sec_edgar_ingest.models import RunContext
        from sec_edgar_ingest.state import attempt_key
        from sec_edgar_ingest.workflows.completion import evaluate_member, outstanding_repairs
        with tempfile.TemporaryDirectory() as tmp:
            f = EvidenceFixture(Path(tmp) / '.fixture-state')
            try:
                _, _, transformed = f.invoke('transform', f.snapshot_input(quarterly_bytes('2026-07-01')))
                with patch.object(EtlState, '_record_membership', side_effect=__import__(
                        'sec_edgar_ingest.storage.contracts', fromlist=['Conflict']).Conflict('ancillary')):
                    code, original_call, result = f.invoke('publish', transformed.transformed_workset_ref)
                self.assertEqual(code, 9)
                self.assertIsNone(result)
                self.assertEqual(len(evaluate_member(f.value, f.workflow.parser_version,
                    f.workflow.schema_version, f.store, f.objects).obligations), 1)
                key = attempt_key(RunContext.from_mapping(original_call['context']))
                original_attempt = f.store.get('Attempt', key).to_mapping()
                command = original_call['result_ref'].rsplit('/', 1)[0] + '/command.json'
                command_bytes = f.objects.read(command)
                pointers = [r.to_mapping() for r in f.store.scan('QuarterPublication', {})]
                clock = f.workflow.deadline + timedelta(seconds=1)
                fresh = replace(f.workflow, attempt_id='fresh-repair', started_at=clock,
                                deadline=clock + timedelta(seconds=3600))
                dispatcher = Dispatcher(fresh, f.settings, f.pack, f.root.parent, f.store, f.objects)
                with patch('sec_edgar_ingest.cli.Clock.now', return_value=clock):
                    processed = process_member(f.value, fresh, dispatcher, f.store, f.objects)
                self.assertIn(processed.result.outcome, ('success', 'unchanged'))
                self.assertEqual(len(processed.evidence['resolutions']), 1)
                self.assertEqual(f.objects.read(command), command_bytes)
                self.assertEqual(f.store.get('Attempt', key).to_mapping(), original_attempt)
                with self.assertRaises(FileNotFoundError):
                    f.objects.read(original_call['result_ref'])
                self.assertEqual([r.to_mapping() for r in f.store.scan('QuarterPublication', {})], pointers)
                self.assertTrue(tuple(f.store.scan('PublicationReceipt', {})))
                self.assertEqual(outstanding_repairs(f.value, f.store, f.objects), ())
            finally:
                f.close()

    def test_unfinished_terminal_error_binds_original_attempt_and_replays_receipt(self):
        from unittest.mock import patch
        from copy import deepcopy
        from sec_edgar_ingest.storage.contracts import Conflict
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        with tempfile.TemporaryDirectory() as tmp:
            h, context, dispatcher, value = self.prepare(Path(tmp))
            try:
                with patch('sec_edgar_ingest.cli.collect', side_effect=RuntimeError('retained execution failure')):
                    processed = process_member(value, context, dispatcher, h.store, h.objects)
                self.assertEqual(processed.result.outcome, 'internal_error')
                self.assertFalse(processed.result.downloaded)
                self.assertEqual(processed.result.child_refs, ())
                terminal = processed.evidence['terminal_error']
                self.assertIsNotNone(terminal)
                self.assertEqual(terminal['call'], processed.evidence['calls'][0])
                self.assertEqual(tuple(g.to_mapping() for g in processed.result.gaps),
                                 tuple(to_mapping_value(g) for g in terminal['gaps']))
                registry = WorkflowMembers(h.store, h.objects)
                for field, altered in (('outcome', 'access_blocked'), ('gaps', []), ('call', {})):
                    evidence = deepcopy(to_mapping_value(processed.evidence))
                    evidence['terminal_error'][field] = altered
                    with self.subTest(field=field), self.assertRaises((Conflict, ValueError, KeyError)):
                        registry.record(processed.result, context, evidence)
                registry.record(processed.result, context, processed.evidence)
                with patch.object(dispatcher, 'execute', side_effect=AssertionError('completed terminal replay dispatched')):
                    self.assertEqual(process_member(value, context, dispatcher, h.store, h.objects), processed)
                self.assertIsNone(registry.completed(value, context.parser_version, context.schema_version))
            finally:
                h.close()
