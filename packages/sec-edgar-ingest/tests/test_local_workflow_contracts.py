"""Local workflow envelopes reject foreign records before changing durable state."""
from network_guard import install
install()

import tempfile
import unittest
from pathlib import Path

from support_checked import workflow_fixture
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows.checked import make_call, child_attempt_id, _validated

LOCAL = 'sec-local-contract-v1'


class LocalWorkflowContractTests(unittest.TestCase):
    def test_child_call_writer_marks_contract_before_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            settings, context, pack, store, objects = workflow_fixture(Path(directory))
            self.addCleanup(store.close)
            attempt = child_attempt_id(context.run_id, context.command, context.attempt_id,
                                       'discover', 'discover')
            import hashlib
            call = make_call(context, 'discover', attempt, None,
                             hashlib.sha256(pack.read_bytes()).hexdigest(),
                             workflow_command=context.command,
                             workflow_attempt_id=context.attempt_id, step_id='discover',
                             today=context.pinned_on, mode='quarterly', discovery_id='local')
            self.assertEqual(call.get('contract_version'), LOCAL)
            self.assertEqual(call['format_version'], 'sec-local-workflow-child-call-v1')
            self.assertEqual(_validated(call)[0], call)
            for mutation in ({k: v for k, v in call.items() if k != 'contract_version'},
                             {**call, 'contract_version': 'foreign'},
                             {**call, 'unknown': True},
                             {**call, 'format_version': 'sec-workflow-child-call-v1'}):
                with self.subTest(mutation=mutation), self.assertRaises((ValueError, Conflict)):
                    _validated(mutation)

from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import hashlib
import json
import sqlite3
from contextlib import closing

from sec_edgar_ingest.models import canonical_json, parse_json, to_mapping_value
from sec_edgar_ingest.workflows import completion, provenance, processing, results, checked
from sec_edgar_ingest.workflows.members import WorkflowMembers
from sec_edgar_ingest.workflows.contracts import WorkflowResult, workflow_path


def durable_snapshot(store, objects):
    with closing(sqlite3.connect(store.database)) as database:
        logical = tuple(database.iterdump())
    tree = {str(path.relative_to(objects.directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in objects.directory.rglob('*') if path.is_file()}
    return tree, logical


class EnvelopeFamilyTests(unittest.TestCase):
    def fixture(self):
        import test_workflow_results as cases
        case = cases.WorkflowResultTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def check_mapping(self, family, value, reader, store, objects):
        value = to_mapping_value(value)
        self.assertEqual(value.get('contract_version'), LOCAL, family)
        reader(deepcopy(value))
        mutations = [('missing-marker', {k: v for k, v in value.items() if k != 'contract_version'}),
                     ('foreign-marker', {**value, 'contract_version': 'foreign'}),
                     ('unknown-field', {**value, 'unexpected_local_field': True})]
        if 'format_version' in value:
            mutations.append(('foreign-format', {**value, 'format_version': 'foreign-format'}))
        for label, changed in mutations:
            with self.subTest(family=family, mutation=label):
                before = durable_snapshot(store, objects)
                with self.assertRaises((ValueError, Conflict, OSError)):
                    reader(changed)
                self.assertEqual(durable_snapshot(store, objects), before)

    def check_object(self, family, path, reader, store, objects):
        target = objects.directory / path
        body = target.read_bytes()
        value = parse_json(body)
        def read_changed(changed):
            target.write_bytes(canonical_json(to_mapping_value(changed)))
            try:
                before = durable_snapshot(store, objects)
                try:
                    return reader()
                finally:
                    self.assertEqual(durable_snapshot(store, objects), before)
            finally:
                target.write_bytes(body)
        # check_mapping's outer snapshot includes the restored authoritative object.
        self.check_mapping(family, value, read_changed, store, objects)
        target.write_bytes(body + b' ')
        try:
            before = durable_snapshot(store, objects)
            with self.subTest(family=family, mutation='noncanonical-bytes'), self.assertRaises((ValueError, Conflict)):
                reader()
            self.assertEqual(durable_snapshot(store, objects), before)
        finally:
            target.write_bytes(body)

    def check_index(self, family, kind, key, reader, store, objects, field=None):
        original = store.get(kind, key).to_mapping()['value']
        def changed_index(value):
            row = store.get(kind, key)
            store.replace(kind, key, value if field is None else {**original, field: value}, row.version)
            try:
                before = durable_snapshot(store, objects)
                try:
                    return reader()
                finally:
                    self.assertEqual(durable_snapshot(store, objects), before)
            finally:
                row = store.get(kind, key)
                store.replace(kind, key, original, row.version)
        # Index injection/restoration intentionally advances CAS versions. Compare only the reader interval.
        envelope = original if field is None else original[field]
        self.assertEqual(envelope.get('contract_version'), LOCAL)
        reader()
        variants = [{k: v for k, v in envelope.items() if k != 'contract_version'},
                    {**envelope, 'contract_version': 'foreign'}, {**envelope, 'unexpected_local_field': True}]
        for changed in variants:
            with self.subTest(family=family, mutation=list(changed)):
                with self.assertRaises((ValueError, Conflict)):
                    changed_index(changed)

    def test_primary_family_real_readers_refuse_without_mutation(self):
        case = self.fixture()
        f, context = case.f, case.context
        store, objects = f.store, f.objects
        report = case.report()
        report_ref = results.write_workflow_result(report, store, objects)
        mapping = report.to_mapping()
        intent = mapping['intent']
        selection = case.selection()
        registry = WorkflowMembers(store, objects)
        receipt = intent['member_receipts'][0]
        evidence = parse_json(objects.read(receipt['ref']))['evidence']
        self.check_object('workflow-result', report_ref,
                          lambda: results.read_workflow_result(report_ref, store, objects), store, objects)
        self.check_object('workflow-selection', results._sibling(context, 'selection.json'),
                          lambda: results.freeze_selection(context, parse_json(objects.read(results._sibling(context, 'selection.json'))), store, objects), store, objects)
        self.check_object('member-receipt', receipt['ref'], lambda: registry._read_receipt(receipt['ref']), store, objects)
        self.check_object('workflow-intent', results._sibling(context, 'intent.json'),
                          lambda: results.freeze_workflow(context, case.invocation, store, objects), store, objects)
        from sec_edgar_ingest.cli import _workflow_frozen, _workflow_saved
        from types import SimpleNamespace
        intent_path = results._sibling(context, 'intent.json')
        self.check_object('workflow-intent-cli', intent_path,
                          lambda: _workflow_frozen(intent_path, objects), store, objects)
        intent_target = objects.directory / intent_path
        intent_body = intent_target.read_bytes()
        intent_target.unlink()
        try:
            args = SimpleNamespace(run_id=context.run_id, command=context.command, attempt_id=context.attempt_id)
            self.check_index('workflow-attempt-cli', 'WorkflowAttempt', results.workflow_key(context),
                             lambda: _workflow_saved(args, store, objects), store, objects)
            for field in ('selection_ref', 'result_ref'):
                self.check_index('workflow-document-descriptor-cli', 'WorkflowAttempt', results.workflow_key(context),
                                 lambda: _workflow_saved(args, store, objects), store, objects, field=field)
        finally:
            intent_target.write_bytes(intent_body)
        self.check_object('child-call-object', checked.call_ref(f.discovery_call),
                          lambda: checked._authority(f.discovery_call, store, objects), store, objects)
        self.check_mapping('child-call', f.discovery_call, checked._validated, store, objects)
        self.check_mapping('member-evidence', evidence,
                           lambda v: processing.validate_member_evidence(report.members[0], v, objects), store, objects)
        self.check_mapping('workflow-member', f.value, lambda v: provenance.read_member(v, store, objects), store, objects)
        self.check_mapping('parent-provenance', selection['parent_provenance'],
                           lambda v: completion.validate_parent_provenance(v, objects), store, objects)
        self.check_mapping('member-provenance', selection['member_provenance'][0],
                           lambda v: completion.validate_member_provenance(v, objects), store, objects)
        self.check_mapping('completion', case.capture, lambda v: completion.validate_capture(v, objects), store, objects)
        self.check_index('workflow-attempt', 'WorkflowAttempt', results.workflow_key(context),
                         lambda: results.freeze_workflow(context, case.invocation, store, objects), store, objects)
        for field in ('selection_ref', 'result_ref'):
            self.check_index('workflow-document-descriptor', 'WorkflowAttempt', results.workflow_key(context),
                lambda: results.read_workflow_result(report_ref, store, objects), store, objects, field=field)
        self.check_mapping('workflow-invocation', case.invocation,
                           lambda v: results.freeze_workflow(context, v, store, objects), store, objects)
        self.check_mapping('report-intent', intent,
                           lambda v: results.write_workflow_result(replace(report, intent=v), store, objects), store, objects)
        self.check_mapping('result-selection-descriptor', intent['selection'],
                           lambda v: results.write_workflow_result(replace(report, intent={**intent, 'selection': v}), store, objects), store, objects)
        self.check_index('member-result-descriptor', 'WorkflowMemberResult',
                         hashlib.sha256(canonical_json([LOCAL, context.run_id, context.command, context.attempt_id, report.members[0].member_id, context.parser_version, context.schema_version])).hexdigest(),
                         lambda: registry.completed(f.value, context.parser_version, context.schema_version), store, objects)
        for family, key, value in [('selection-job', 'jobs', selection['jobs'][0])]:
            self.check_mapping(family, value,
                lambda v: results._validate_selection({**selection, key: [v]}, context, case.invocation, store, objects), store, objects)
        discovery = selection['parent_provenance']['discovery']
        self.check_mapping('discovery-snapshot', discovery,
                           lambda v: completion._validate_discovery(provenance.read_source(f.parent_ref, objects), v, objects), store, objects)
        self.check_mapping('discovery-session', discovery['session'], completion.validate_discovery_session, store, objects)
        self.check_mapping('discovery-progress', discovery['progress'][0],
                           lambda v: completion._validate_discovery(provenance.read_source(f.parent_ref, objects),
                              {**discovery, 'progress': [v] + discovery['progress'][1:]}, objects), store, objects)

    def test_repair_and_recovery_family_real_readers_refuse_without_mutation(self):
        from sec_edgar_ingest.etl.state import EtlState
        from sec_edgar_ingest.state import AcquisitionState
        from sec_edgar_ingest.workflows.legacy import reconstruct_parent
        case = self.fixture()
        f, context = case.f, case.context
        store, objects = f.store, f.objects
        with patch.object(EtlState, '_record_membership', side_effect=Conflict('repair matrix')):
            code, call, child = f.invoke('publish', case.transformed_ref)
        self.assertEqual(code, 9)
        pending = completion.evaluate_member(f.value, context.parser_version, context.schema_version, store, objects)
        self.assertEqual(len(pending.obligations), 1)
        obligation = to_mapping_value(pending.obligations[0])
        code, repaired_call, child = f.invoke('publish', case.transformed_ref)
        self.assertEqual(code, 0)
        resolution = completion.resolve_repair(obligation, repaired_call, store, objects)
        original = parse_json(objects.read(obligation['ref']))
        digest = hashlib.sha256(canonical_json(to_mapping_value(original['call']))).hexdigest()
        self.check_mapping('repair-descriptor', obligation,
                           lambda v: completion._read_document(v, completion.OBLIGATION_FORMAT, objects), store, objects)
        self.check_object('repair-authority', completion._repair_authority_ref(digest),
                           lambda: completion._read_repair_authority(digest, objects), store, objects)
        # Re-address mutations so the document reader reaches schema validation rather than hash refusal.
        for family, descriptor, version in [('repair-obligation', obligation, completion.OBLIGATION_FORMAT),
                                             ('repair-resolution', resolution, completion.RESOLUTION_FORMAT)]:
            value = parse_json(objects.read(descriptor['ref']))
            def reader(changed, version=version):
                body = canonical_json(to_mapping_value(changed))
                identity = hashlib.sha256(body).hexdigest()
                namespace = 'workflow-repairs' if version == completion.OBLIGATION_FORMAT else 'workflow-repair-resolutions'
                path = f'worksets/sec/{namespace}/sha256={identity}/evidence.json'
                objects.put_once(path, body)
                desc = {'contract_version': LOCAL, 'ref': path, 'sha256': identity, 'bytes': len(body), 'format_version': version}
                # Creation is fixture injection, outside the refusal snapshot.
                before = durable_snapshot(store, objects)
                try:
                    return completion._read_document(desc, version, objects)
                finally:
                    self.assertEqual(durable_snapshot(store, objects), before)
            # Avoid check_mapping's outer snapshot including deliberately new mutation objects.
            self.assertEqual(value['contract_version'], LOCAL)
            completion._read_document(descriptor, version, objects)
            for field, replacement in [('contract_version', None), ('contract_version', 'foreign'),
                                       ('unexpected_local_field', True), ('format_version', 'foreign')]:
                changed = {**value, field: replacement}
                if replacement is None: del changed[field]
                with self.subTest(family=family, field=field, value=replacement), self.assertRaises((Conflict, ValueError)):
                    reader(changed)
            noncanonical = objects.read(descriptor['ref']) + b' '
            identity = hashlib.sha256(noncanonical).hexdigest()
            path = descriptor['ref'].replace(descriptor['sha256'], identity)
            objects.put_once(path, noncanonical)
            changed_descriptor = {**descriptor, 'ref': path, 'sha256': identity, 'bytes': len(noncanonical)}
            before = durable_snapshot(store, objects)
            with self.subTest(family=family, mutation='rehashed-noncanonical'), self.assertRaises(Conflict):
                completion._read_document(changed_descriptor, version, objects)
            self.assertEqual(durable_snapshot(store, objects), before)
        resolved = parse_json(objects.read(resolution['ref']))
        artifact = resolved['repair_artifacts'][0]
        def artifact_reader(changed):
            # The immutable result/obligation continue to be checked by the resolution reader.
            body_value = {**resolved, 'repair_artifacts': [changed] + resolved['repair_artifacts'][1:]}
            body = canonical_json(to_mapping_value(body_value))
            identity = hashlib.sha256(body).hexdigest()
            path = f'worksets/sec/workflow-repair-resolutions/sha256={identity}/evidence.json'
            objects.put_once(path, body)
            before = durable_snapshot(store, objects)
            try:
                completion.validate_resolution_capture({'contract_version': LOCAL, 'ref': path, 'sha256': identity,
                    'bytes': len(body), 'format_version': completion.RESOLUTION_FORMAT}, objects)
            finally:
                self.assertEqual(durable_snapshot(store, objects), before)
        for family, value, inject in [('repair-artifacts', artifact, lambda v: v),
                                     ('repair-artifact-record', artifact['records'][0],
                                      lambda v: {**artifact, 'records': [v] + artifact['records'][1:]})]:
            artifact_reader(inject(value))
            for changed in ({k: v for k, v in value.items() if k != 'contract_version'},
                            {**value, 'contract_version': 'foreign'}, {**value, 'unexpected_local_field': True}):
                with self.subTest(family=family), self.assertRaises((Conflict, ValueError)):
                    artifact_reader(inject(changed))
        self.check_index('repair-obligation-index', 'WorkflowRepairObligation', digest,
                         lambda: completion.outstanding_repairs(f.value, store, objects), store, objects)
        self.check_index('repair-resolution-index', 'WorkflowRepairResolution', digest,
                         lambda: completion.outstanding_repairs(f.value, store, objects), store, objects)
        parent = provenance.read_source(f.parent_ref, objects)
        session = AcquisitionState(store).discovery_session(parent.discovery_id).to_mapping()['value']
        recovered_ref = reconstruct_parent(session, store, objects)
        recovered = provenance.read_source(recovered_ref, objects)
        descriptor = store.get('WorkflowParentRecovery', recovered.workset_id).to_mapping()['value']
        self.check_mapping('parent-recovery-descriptor', descriptor,
                           lambda v: provenance.validate_parent_recovery(recovered_ref, v, objects), store, objects)
        self.check_object('parent-recovery', descriptor['ref'],
                           lambda: provenance.validate_parent_recovery(recovered_ref, descriptor, objects), store, objects)
        recovery = parse_json(objects.read(descriptor['ref']))
        for field, replacement in [('contract_version', None), ('contract_version', 'foreign'),
                                   ('unexpected_local_field', True), ('format_version', 'foreign')]:
            changed = {**recovery, field: replacement}
            if replacement is None:
                del changed[field]
            body = canonical_json(changed)
            identity = hashlib.sha256(body).hexdigest()
            path = descriptor['ref'].replace(descriptor['sha256'], identity)
            objects.put_once(path, body)
            changed_descriptor = {**descriptor, 'ref': path, 'sha256': identity, 'bytes': len(body)}
            before = durable_snapshot(store, objects)
            with self.subTest(family='parent-recovery', field=field), self.assertRaises((Conflict, ValueError)):
                provenance.validate_parent_recovery(recovered_ref, changed_descriptor, objects)
            self.assertEqual(durable_snapshot(store, objects), before)


    def test_terminal_and_ordinary_publish_family_readers_refuse_without_mutation(self):
        import contextlib
        import io
        from sec_edgar_ingest.cli import main
        from sec_edgar_ingest.etl.state import EtlState
        case = self.fixture()
        f, store, objects = case.f, case.f.store, case.f.objects
        context = replace(case.context, attempt_id='terminal-family')
        dispatcher = checked.Dispatcher(context, f.settings, f.pack, f.root.parent, store, objects)
        with patch('sec_edgar_ingest.cli.collect', side_effect=RuntimeError('terminal matrix')):
            processed = processing.process_member(f.value, context, dispatcher, store, objects)
        evidence = to_mapping_value(processed.evidence)
        terminal = evidence['terminal_error']
        terminal_ref = terminal['call']['result_ref'].rsplit('/', 1)[0] + '/terminal.json'
        self.check_mapping('child-unfinished-details', terminal,
            lambda v: processing.validate_member_evidence(processed.result, {**evidence, 'terminal_error': v}, objects), store, objects)
        self.check_object('terminal-capture', terminal_ref,
            lambda: processing.validate_member_evidence(processed.result, evidence, objects), store, objects)
        argv = ['publish', '--config', str(f.config), '--run-id', 'ordinary-family',
                '--execution-id', 'manual', '--attempt-id', 'ordinary-family',
                '--deadline', context.deadline.isoformat(), '--today', context.pinned_on.isoformat(),
                '--workset', case.transformed_ref]
        with (patch.object(EtlState, '_record_membership', side_effect=Conflict('ordinary repair matrix')),
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            self.assertEqual(main(argv), 9)
        ordinary = next(row for row in store.scan('Attempt', {}) if row.value['context']['run_id'] == 'ordinary-family')
        from sec_edgar_ingest.models import RunContext
        saved = RunContext.from_mapping(ordinary.to_mapping()['value']['context'])
        call = completion._legacy_publish_call(saved, objects)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(argv), 0)
        self.check_mapping('legacy-publish', call, lambda v: completion.read_legacy_publish(v, store, objects), store, objects)

    def test_supersession_proof_retains_current_download_semantics(self):
        from support_workflow_evidence import quarterly_bytes
        from support_workflows import replace_pack_body
        from sec_edgar_ingest.workflows.members import SourceDownloads
        case = self.fixture()
        f, context = case.f, case.context
        store, objects = f.store, f.objects
        context = replace(context, command='reconcile', priority='reconciliation')
        f.workflow = case.context = context
        case.invocation['command'] = 'reconcile'
        results.freeze_workflow(context, case.invocation, store, objects)
        f.revised_member()
        old = deepcopy(f.value)
        old_dispatcher = checked.Dispatcher(context, f.settings, f.pack, f.root.parent, store, objects)
        old_processed = processing.process_member(old, context, old_dispatcher, store, objects)
        WorkflowMembers(store, objects).record(old_processed.result, context, old_processed.evidence)
        f.revised_member()
        current = deepcopy(f.value)
        (f.pack.parent / 'bodies').mkdir(exist_ok=True)
        replace_pack_body(f.pack, f.source.canonical_url, quarterly_bytes('2026-07-01', 'Newer'))
        dispatcher = checked.Dispatcher(context, f.settings, f.pack, f.root.parent, store, objects)
        processed = processing.process_member(current, context, dispatcher, store, objects)
        WorkflowMembers(store, objects).record(processed.result, context, processed.evidence)
        proof = SourceDownloads((old, current), (current,), {f.source.source_id: old['source']}, store).supersession(old)
        self.assertIsNotNone(proof)
        selection = case.selection(skipped=True)
        parent = completion.capture_parent_provenance(current['parent_ref'], store, objects)
        discovery = next(row.to_mapping()['value'] for row in store.scan('WorkflowChildCall', {})
                         if row.value['context']['command'] == 'discover' and row.value['intent']['discovery_id'] == parent['parent']['discovery_id'])
        selection.update(parent_ref=current['parent_ref'], parent_provenance=parent,
                         discovery_session=parent['discovery']['session'],
                         directories=parent['parent']['directories'], discovery_call=discovery,
                         already_complete=[to_mapping_value(processed.evidence['completion'])], superseded=[proof])
        self.check_mapping('supersession-proof', proof,
            lambda v: results._validate_selection({**selection, 'superseded': [v]}, context, case.invocation, store, objects), store, objects)


class ContractInventoryTests(unittest.TestCase):
    def test_inventory_has_unique_complete_rows_and_real_test_references(self):
        path = Path(__file__).resolve().parents[3] / 'specs/evidence/local-port/contract-inventory.json'
        inventory = json.loads(path.read_text())
        self.assertEqual(inventory['contract_version'], LOCAL)
        rows = inventory['rows']
        self.assertEqual(len(rows), 34)
        self.assertEqual(len({row['family'] for row in rows}), len(rows))
        for row in rows:
            self.assertTrue({'family', 'writers', 'readers', 'hash_sites', 'equality_sites',
                             'positive_test', 'negative_test'} <= set(row))
            self.assertTrue(row['writers'])
            self.assertTrue(row['readers'])
            for reference in (row['positive_test'], row['negative_test']):
                module_name, class_name, method_name = reference.split('.')
                module = __import__(module_name)
                self.assertTrue(callable(getattr(getattr(module, class_name), method_name)), reference)


class ReviewRegressionTests(unittest.TestCase):
    fixture = EnvelopeFamilyTests.fixture

    def delete_workflow_index(self, context, store):
        from sec_edgar_ingest.storage.contracts import identity, table_for
        key = results.workflow_key(context)
        partition, _ = identity('WorkflowAttempt', key)
        with closing(sqlite3.connect(store.database)) as database:
            database.execute('DELETE FROM records WHERE table_name=? AND partition=? AND key=?',
                             (table_for('WorkflowAttempt'), partition, key))
            database.commit()

    def test_coherent_invocation_copies_refuse_at_every_shared_reader(self):
        from support_workflows import CommandHarness, simple_pack
        from sec_edgar_ingest.workflows.summary import _validated_milestone
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = CommandHarness(root, simple_pack(root / 'pack'))
            self.addCleanup(harness.close)
            self.assertEqual(harness.invoke('reconcile', run='coherent-invocation')[0], 0)
            store, objects = harness.store, harness.objects
            reference = harness.calls[-1]['stdout']['result_ref']
            report = results.read_workflow_result(reference, store, objects)
            context = report.context
            intent_path, selection_path = (results._sibling(context, name)
                                           for name in ('intent.json', 'selection.json'))
            original = {path: objects.read(path) for path in (intent_path, selection_path, reference)}
            invocation = report.to_mapping()['intent']['invocation']
            variants = [('missing-marker', {k: v for k, v in invocation.items() if k != 'contract_version'}),
                        ('foreign-marker', {**invocation, 'contract_version': 'foreign'}),
                        ('unknown-field', {**invocation, 'unexpected_local_field': True}),
                        ('missing-field', {k: v for k, v in invocation.items() if k != 'today'})]
            for name, altered in variants:
                intent = parse_json(original[intent_path])
                intent['intent'] = altered
                selection = parse_json(original[selection_path])
                selection['invocation'] = altered
                selection_body = canonical_json(selection)
                payload = report.to_mapping()
                payload['intent']['invocation'] = altered
                payload['intent']['selection'] = results._descriptor(selection_path, selection_body)
                changed = WorkflowResult.from_mapping(payload)
                (objects.directory / intent_path).write_bytes(canonical_json(intent))
                (objects.directory / selection_path).write_bytes(selection_body)
                (objects.directory / reference).write_bytes(canonical_json(payload))
                milestone = {'contract_version': LOCAL, 'workflow': 'reconcile',
                             'ended_at': report.ended_at, 'result_ref': reference}
                readers = [('_validate_report', lambda: results._validate_report(changed, store, objects)),
                           ('_validate_selection', lambda: results._validate_selection(selection, context, altered, store, objects)),
                           ('read_workflow_result', lambda: results.read_workflow_result(reference, store, objects)),
                           ('milestone', lambda: _validated_milestone(milestone, store, objects))]
                try:
                    for reader_name, reader in readers:
                        self.delete_workflow_index(context, store)
                        before = durable_snapshot(store, objects)
                        with self.subTest(mutation=name, reader=reader_name):
                            try:
                                with self.assertRaises((Conflict, ValueError)):
                                    reader()
                            finally:
                                self.assertEqual(durable_snapshot(store, objects), before)
                finally:
                    for path, body in original.items():
                        (objects.directory / path).write_bytes(body)
            self.delete_workflow_index(context, store)
            self.assertEqual(results.read_workflow_result(reference, store, objects), report)

    def test_invocation_refuses_before_new_workflow_dispatch(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from sec_edgar_ingest.workflows.runner import run_workflow, select_work
        case = self.fixture()
        store, objects = case.f.store, case.f.objects
        context = replace(case.context, attempt_id='invocation-dispatch-boundary')
        variants = [{k: v for k, v in case.invocation.items() if k != 'contract_version'},
                    {**case.invocation, 'contract_version': 'foreign'},
                    {**case.invocation, 'unexpected_local_field': True},
                    {k: v for k, v in case.invocation.items() if k != 'today'}]
        for altered in variants:
            for reader in (run_workflow, select_work):
                dispatcher = SimpleNamespace(execute=Mock(side_effect=AssertionError('unsupported invocation reached child dispatch')))
                before = durable_snapshot(store, objects)
                with self.subTest(reader=reader.__name__, fields=list(altered)):
                    refused = False
                    try:
                        reader(context, case.f.settings, altered, dispatcher, store, objects)
                    except (ValueError, Conflict):
                        refused = True
                    except AssertionError:
                        pass
                    self.assertTrue(refused, 'unsupported invocation was not refused at the workflow entry')
                    dispatcher.execute.assert_not_called()
                    self.assertEqual(durable_snapshot(store, objects), before)

    def test_coherent_terminal_details_refuse_independently_of_copy_equality(self):
        case = self.fixture()
        f, store, objects = case.f, case.f.store, case.f.objects
        context = replace(case.context, attempt_id='coherent-terminal')
        dispatcher = checked.Dispatcher(context, f.settings, f.pack, f.root.parent, store, objects)
        with patch('sec_edgar_ingest.cli.collect', side_effect=RuntimeError('coherent terminal')):
            processed = processing.process_member(f.value, context, dispatcher, store, objects)
        registry = WorkflowMembers(store, objects)
        descriptor = registry.record(processed.result, context, processed.evidence)
        terminal = to_mapping_value(processed.evidence['terminal_error'])
        terminal_path = terminal['call']['result_ref'].rsplit('/', 1)[0] + '/terminal.json'
        original_terminal = objects.read(terminal_path)
        original_receipt = objects.read(descriptor['ref'])
        key = hashlib.sha256(canonical_json([LOCAL, context.run_id, context.command, context.attempt_id,
                              processed.result.member_id, context.parser_version, context.schema_version])).hexdigest()
        variants = [('missing-marker', {k: v for k, v in terminal.items() if k != 'contract_version'}),
                    ('foreign-marker', {**terminal, 'contract_version': 'foreign'}),
                    ('unknown-field', {**terminal, 'unexpected_local_field': True}),
                    ('missing-field', {k: v for k, v in terminal.items() if k != 'stdout'}),
                    ('stdout-type', {**terminal, 'stdout': None}),
                    ('stderr-type', {**terminal, 'stderr': False}),
                    ('repair-pending-type', {**terminal, 'repair_pending': 0}),
                    ('resumable-type', {**terminal, 'resumable': 0})]
        for name, altered in variants:
            evidence = to_mapping_value(processed.evidence)
            evidence['terminal_error'] = altered
            retained = parse_json(original_terminal)
            retained['terminal_error'] = altered
            receipt = parse_json(original_receipt)
            receipt['evidence'] = evidence
            body = canonical_json(receipt)
            (objects.directory / terminal_path).write_bytes(canonical_json(retained))
            (objects.directory / descriptor['ref']).write_bytes(body)
            row = store.get('WorkflowMemberResult', key)
            changed_descriptor = registry._descriptor(processed.result, context, body)
            store.replace('WorkflowMemberResult', key, changed_descriptor, row.version)
            readers = [('member-evidence', lambda: processing.validate_member_evidence(processed.result, evidence, objects)),
                       ('member-receipt', lambda: registry._read_receipt(descriptor['ref'])),
                       ('member-index', lambda: registry.completed(f.value, context.parser_version, context.schema_version))]
            try:
                for reader_name, reader in readers:
                    before = durable_snapshot(store, objects)
                    with self.subTest(mutation=name, reader=reader_name):
                        try:
                            with self.assertRaises((Conflict, ValueError)):
                                reader()
                        finally:
                            self.assertEqual(durable_snapshot(store, objects), before)
            finally:
                (objects.directory / terminal_path).write_bytes(original_terminal)
                (objects.directory / descriptor['ref']).write_bytes(original_receipt)
                row = store.get('WorkflowMemberResult', key)
                store.replace('WorkflowMemberResult', key, descriptor, row.version)
        processing.validate_member_evidence(processed.result, processed.evidence, objects)
        self.assertEqual(registry._read_receipt(descriptor['ref'])[0], processed.result)

    def test_conflicting_frozen_selection_refuses_before_missing_index_repair(self):
        case = self.fixture()
        store, objects = case.f.store, case.f.objects
        original = results.freeze_selection(case.context, case.selection(), store, objects)
        self.delete_workflow_index(case.context, store)
        changed = {**original, 'boundary_before': '2026-10-02'}
        results._validate_selection(changed, case.context, case.invocation, store, objects)
        before = durable_snapshot(store, objects)
        try:
            with self.assertRaises(Conflict):
                results.freeze_selection(case.context, changed, store, objects)
        finally:
            self.assertEqual(durable_snapshot(store, objects), before)
        with patch.object(objects, 'put_once', wraps=objects.put_once) as put:
            self.assertEqual(results.freeze_selection(case.context, original, store, objects), original)
        self.assertTrue(put.called)
        self.assertIsNotNone(store.get('WorkflowAttempt', results.workflow_key(case.context)))
