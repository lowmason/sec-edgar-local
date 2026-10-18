"""Pure strict local acquisition codecs and provenance regressions."""
import unittest
from dataclasses import fields, replace
from datetime import timedelta
from pathlib import Path
import multiprocessing
import os
import tempfile
import hashlib

from support import fixture_context, fixture_settings, fixture_snapshot, fixture_source, fixture_workset
from sec_edgar_ingest.models import CommandResult, RunContext, canonical_json, parse_json
from sec_edgar_ingest.runtime import fixture_descriptor
from sec_edgar_ingest.state import attempt_key
from sec_edgar_ingest.worksets import (
    decode_snapshot_workset, decode_source_workset, encode_workset, make_snapshot_workset,
)


def admission_process(root, mapping, intent, barrier=None, results=None, crash=False):
    """Exercise independent local stores; synchronize the first immutable write."""
    from support import store_bundle
    from sec_edgar_ingest.cli import _existing_context, _existing_etl_context
    from sec_edgar_ingest.state import AcquisitionState
    from sec_edgar_ingest.storage.contracts import Conflict
    store, objects, leases = store_bundle(Path(root))
    state = AcquisitionState(store)
    context = RunContext.from_mapping(mapping)
    if barrier is not None:
        original_get, original_scan = store.get, store.scan
        looked_up = False
        def rendezvous(kind):
            nonlocal looked_up
            if kind == 'Attempt' and not looked_up:
                looked_up = True
                barrier.wait(timeout=30)
        def get(kind, key):
            row = original_get(kind, key)
            rendezvous(kind)
            return row
        def scan(kind, filters):
            rows = list(original_scan(kind, filters))
            rendezvous(kind)
            return iter(rows)
        store.get, store.scan = get, scan
        original = objects.put_once
        first = True
        def synchronized(path, body):
            nonlocal first
            if first:
                first = False
                barrier.wait(timeout=30)
            return original(path, body)
        objects.put_once = synchronized
    if crash:
        state.begin_attempt = lambda context: os._exit(74)
    try:
        reader = _existing_etl_context if context.command in ('transform', 'publish') else _existing_context
        admitted, _ = reader(context, state, objects, intent, False)
        if results is not None:
            results.put(('admitted', admitted.to_mapping(), intent))
    except Conflict as error:
        if results is not None:
            results.put(('conflict', str(error)))
        else:
            raise
    finally:
        leases.close()
        store.close()


class AttemptAdmissionTests(unittest.TestCase):
    def stop_child(self, child):
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)

    def bundle(self, command='discover'):
        from support import store_bundle
        from sec_edgar_ingest.state import AcquisitionState
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        store, objects, leases = store_bundle(root)
        self.addCleanup(store.close)
        self.addCleanup(leases.close)
        context = fixture_context(command=command, settings=fixture_settings(root=root))
        intent = ({'command': command, 'today': None, 'workset': 'input', 'force': False}
                  if command in ('transform', 'publish') else
                  {'command': command, 'today': None, 'fixture_sha256': '1' * 64,
                   'mode': 'quarterly', 'discovery_id': 'probe', 'refresh': False, 'workset': None})
        return root, AcquisitionState(store), objects, context, intent

    def admit(self, context, state, objects, intent):
        from sec_edgar_ingest.cli import _existing_context, _existing_etl_context
        reader = _existing_etl_context if context.command in ('transform', 'publish') else _existing_context
        return reader(context, state, objects, intent, False)

    def snapshot(self, state, objects):
        return ([row.to_mapping() for row in state.store.scan('Attempt', {})],
                {str(path.relative_to(objects.directory)): path.read_bytes()
                 for path in objects.directory.rglob('*') if path.is_file()})

    def variants(self, original, intent):
        settings = fixture_settings(root=Path(original.effective_config['storage']['root']))
        return (
            ('execution', replace(original, execution_id='replacement'), intent),
            ('runtime', fixture_context(command=original.command, settings=fixture_settings(
                root=Path(settings.storage.root), runtime={'fixture_id': 'replacement'})), intent),
            ('config', fixture_context(command=original.command, settings=fixture_settings(
                root=Path(settings.storage.root), sec={'requests_per_second': 1})), intent),
            ('deadline', replace(original, deadline=original.deadline - timedelta(seconds=1)), intent),
            ('intent', original, {**intent, 'today': '2026-10-06'}),
        )

    def test_pre_discovery_crash_rejects_substitutions_without_mutation(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        _, state, objects, original, intent = self.bundle()
        self.admit(original, state, objects, intent)
        self.assertIsNone(state.discovery_session('probe'))
        before = self.snapshot(state, objects)
        for label, current, inputs in self.variants(original, intent):
            with self.subTest(label=label), self.assertRaises(Conflict):
                self.admit(current, state, objects, inputs)
            self.assertEqual(self.snapshot(state, objects), before)
        later = replace(original, started_at=original.started_at + timedelta(seconds=10))
        self.assertEqual(self.admit(later, state, objects, intent), (original, None))
        self.assertEqual(self.snapshot(state, objects), before)

    def test_legacy_attempt_without_admission_rejects_before_claiming(self):
        from sec_edgar_ingest.results import result_path
        from sec_edgar_ingest.storage.contracts import Conflict
        for command in ('discover', 'collect', 'transform', 'publish'):
            _, state, objects, original, intent = self.bundle(command)
            state.begin_attempt(original)
            command_path = result_path(original).rsplit('/', 1)[0] + '/command.json'
            body = canonical_json({'context': original.to_mapping(), 'intent': intent}
                                  if command in ('transform', 'publish') else intent)
            objects.put_once(command_path, body)
            before = self.snapshot(state, objects)
            for label, current, inputs in self.variants(original, intent):
                with self.subTest(command=command, label=label), self.assertRaises(Conflict):
                    self.admit(current, state, objects, inputs)
                self.assertEqual(self.snapshot(state, objects), before)
            self.assertEqual(self.admit(original, state, objects, intent), (original, None))
            self.assertEqual(objects.read(command_path), body)
            self.assertEqual(self.snapshot(state, objects)[0], before[0])

    def test_process_death_after_admission_before_attempt_keeps_original_authority(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        for command in ('discover', 'transform'):
            root, state, objects, original, intent = self.bundle(command)
            child = multiprocessing.get_context('spawn').Process(target=admission_process,
                args=(str(root), original.to_mapping(), intent, None, None, True))
            child.start()
            self.addCleanup(self.stop_child, child)
            child.join(timeout=30)
            self.assertFalse(child.is_alive())
            self.assertEqual(child.exitcode, 74)
            self.assertEqual(tuple(state.store.scan('Attempt', {})), ())
            before = self.snapshot(state, objects)
            for label, current, inputs in self.variants(original, intent):
                with self.subTest(command=command, label=label), self.assertRaises(Conflict):
                    self.admit(current, state, objects, inputs)
                self.assertEqual(self.snapshot(state, objects), before)
            self.assertEqual(self.admit(original, state, objects, intent), (original, None))
            self.assertEqual(len(tuple(state.store.scan('Attempt', {}))), 1)
            from support import retain_acquisition_proof
            retain_acquisition_proof('admission-crash-' + command,
                {'command': command, 'pid': child.pid, 'exit': child.exitcode,
                 'boundary': 'after immutable admission before Attempt insertion',
                 'original_context': original.to_mapping(), 'original_intent': intent,
                 'attempts_at_crash': before[0],
                 'admission': parse_json(next(objects.directory.rglob('admission.json')).read_bytes()),
                 'attempts_after_exact_retry': [row.to_mapping() for row in state.store.scan('Attempt', {})],
                 'transport_attempts': [row.to_mapping() for row in state.store.scan('TransportAttempt', {})]})

    def test_independent_first_admissions_choose_one_context_and_intent(self):
        for command in ('discover', 'transform'):
            for variation in ('execution', 'runtime', 'intent', 'same'):
                with self.subTest(command=command, variation=variation):
                    root, state, objects, original, intent = self.bundle(command)
                    choices = {label: (current, inputs) for label, current, inputs in self.variants(original, intent)}
                    contender, inputs = (original, intent) if variation == 'same' else choices[variation]
                    spawn = multiprocessing.get_context('spawn')
                    barrier, results = spawn.Barrier(2), spawn.Queue()
                    children = [spawn.Process(target=admission_process,
                        args=(str(root), current.to_mapping(), supplied, barrier, results))
                        for current, supplied in ((original, intent), (contender, inputs))]
                    for child in children:
                        child.start()
                        self.addCleanup(self.stop_child, child)
                    for child in children:
                        child.join(timeout=30)
                        self.assertFalse(child.is_alive())
                        self.assertEqual(child.exitcode, 0)
                    outcomes = [results.get(timeout=5), results.get(timeout=5)]
                    results.close()
                    self.assertEqual(sorted(value[0] for value in outcomes),
                        ['admitted', 'admitted'] if variation == 'same' else ['admitted', 'conflict'])
                    attempts = list(state.store.scan('Attempt', {}))
                    self.assertEqual(len(attempts), 1)
                    winner = next(value[1] for value in outcomes if value[0] == 'admitted')
                    self.assertEqual(attempts[0].to_mapping()['value']['context'], winner)
                    if variation == 'same':
                        self.assertEqual(outcomes[0][1], outcomes[1][1])
                    self.assertEqual(tuple(state.store.scan('TransportAttempt', {})), ())
                    admissions = list(objects.directory.rglob('admission.json'))
                    self.assertEqual(len(admissions), 1)
                    body = admissions[0].read_bytes()
                    admission = parse_json(body)
                    self.assertEqual(admission['context'], winner)
                    self.assertEqual(admission['intent'], next(value[2] for value in outcomes if value[0] == 'admitted'))
                    from support import retain_acquisition_proof
                    retain_acquisition_proof('admission-race-' + command + '-' + variation,
                        {'command': command, 'variation': variation,
                         'rendezvous': 'both first Attempt lookups complete, then both first immutable writes',
                         'children': [{'pid': child.pid, 'exit': child.exitcode} for child in children],
                         'outcomes': outcomes, 'admission': admission,
                         'admission_sha256': hashlib.sha256(body).hexdigest(),
                         'attempts': [row.to_mapping() for row in attempts], 'transport_attempts': []})

    def test_legacy_begun_attempt_without_command_preserves_original_context(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        _, state, objects, original, intent = self.bundle()
        state.begin_attempt(original)
        before = self.snapshot(state, objects)
        for label, current, inputs in self.variants(original, intent)[:-1]:
            with self.subTest(label=label), self.assertRaises(Conflict):
                self.admit(current, state, objects, inputs)
            self.assertEqual(self.snapshot(state, objects), before)
        later = replace(original, started_at=original.started_at + timedelta(seconds=10))
        self.assertEqual(self.admit(later, state, objects, intent), (original, None))

    def test_ambiguous_legacy_attempts_refuse_without_claim_or_mutation(self):
        from sec_edgar_ingest.storage.contracts import Conflict
        _, state, objects, original, intent = self.bundle()
        state.begin_attempt(original)
        state.begin_attempt(replace(original, execution_id='second'))
        before = self.snapshot(state, objects)
        with self.assertRaises(Conflict):
            self.admit(original, state, objects, intent)
        self.assertEqual(self.snapshot(state, objects), before)

    def test_admission_real_readers_refuse_foreign_or_inexact_receipts_without_mutation(self):
        from sec_edgar_ingest.results import result_path
        from sec_edgar_ingest.storage.contracts import Conflict
        for command in ('discover', 'transform'):
            _, state, objects, original, intent = self.bundle(command)
            path = result_path(original).rsplit('/', 1)[0] + '/admission.json'
            receipt = {'contract_version': 'sec-local-contract-v1',
                       'format_version': 'sec-local-attempt-admission-v1',
                       'context': original.to_mapping(), 'intent': intent}
            bad_context = {**original.to_mapping(), 'runtime': {}}
            variants = [canonical_json({k: v for k, v in receipt.items() if k != field})
                        for field in receipt]
            variants += [canonical_json({**receipt, 'contract_version': 'foreign'}),
                         canonical_json({**receipt, 'format_version': 'foreign'}),
                         canonical_json({**receipt, 'unexpected': True}),
                         canonical_json({**receipt, 'context': bad_context}),
                         canonical_json({**receipt, 'context': replace(original, run_id='other').to_mapping()}),
                         canonical_json({**receipt, 'intent': {**intent, 'unexpected': True}}),
                         canonical_json(receipt) + b'\n']
            for number, body in enumerate(variants):
                with self.subTest(command=command, variation=number):
                    target = objects.directory / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
                    before = self.snapshot(state, objects)
                    with self.assertRaises((ValueError, Conflict)):
                        self.admit(original, state, objects, intent)
                    self.assertEqual(self.snapshot(state, objects), before)
            target.write_bytes(canonical_json(receipt))
            self.assertEqual(self.admit(original, state, objects, intent), (original, None))

    def test_admission_only_prefix_refuses_numeric_boolean_aliases_without_mutation(self):
        from sec_edgar_ingest.results import result_path
        from sec_edgar_ingest.storage.contracts import Conflict
        for command, flag in (('discover', 'refresh'), ('transform', 'force')):
            for expected, aliases in ((False, (0, 0.0)), (True, (1, 1.0))):
                for alias in aliases:
                    with self.subTest(command=command, expected=expected, alias=repr(alias)):
                        _, state, objects, context, intent = self.bundle(command)
                        intent = {**intent, flag: expected}
                        base = result_path(context).rsplit('/', 1)[0]
                        receipt = {'contract_version': 'sec-local-contract-v1',
                                   'format_version': 'sec-local-attempt-admission-v1',
                                   'context': context.to_mapping(), 'intent': {**intent, flag: alias}}
                        objects.put_once(base + '/admission.json', canonical_json(receipt))
                        self.assertEqual(tuple(state.store.scan('Attempt', {})), ())
                        with self.assertRaises(FileNotFoundError):
                            objects.read(base + '/command.json')
                        before = self.snapshot(state, objects)
                        with self.assertRaises(Conflict):
                            self.admit(context, state, objects, intent)
                        self.assertEqual(self.snapshot(state, objects), before)

    def test_admission_only_prefix_refuses_normalized_context_timestamps_without_mutation(self):
        from sec_edgar_ingest.results import result_path
        from sec_edgar_ingest.storage.contracts import Conflict
        for command in ('discover', 'transform'):
            for field in ('started_at', 'deadline'):
                with self.subTest(command=command, field=field):
                    _, state, objects, context, intent = self.bundle(command)
                    mapping = context.to_mapping()
                    mapping[field] = mapping[field].replace('+00:00', 'Z')
                    self.assertNotEqual(canonical_json(mapping), canonical_json(context.to_mapping()))
                    base = result_path(context).rsplit('/', 1)[0]
                    objects.put_once(base + '/admission.json', canonical_json({
                        'contract_version': 'sec-local-contract-v1',
                        'format_version': 'sec-local-attempt-admission-v1',
                        'context': mapping, 'intent': intent}))
                    self.assertEqual(tuple(state.store.scan('Attempt', {})), ())
                    with self.assertRaises(FileNotFoundError):
                        objects.read(base + '/command.json')
                    before = self.snapshot(state, objects)
                    with self.assertRaises(Conflict):
                        self.admit(context, state, objects, intent)
                    self.assertEqual(self.snapshot(state, objects), before)

    def test_legacy_etl_numeric_boolean_aliases_refuse_before_admission_mutation(self):
        from sec_edgar_ingest.results import result_path
        from sec_edgar_ingest.storage.contracts import Conflict
        for expected, aliases in ((False, (0, 0.0)), (True, (1, 1.0))):
            for alias in aliases:
                with self.subTest(expected=expected, alias=repr(alias)):
                    _, state, objects, context, intent = self.bundle('transform')
                    intent = {**intent, 'force': expected}
                    base = result_path(context).rsplit('/', 1)[0]
                    objects.put_once(base + '/command.json', canonical_json({
                        'context': context.to_mapping(), 'intent': {**intent, 'force': alias}}))
                    before = self.snapshot(state, objects)
                    with self.assertRaises(Conflict):
                        self.admit(context, state, objects, intent)
                    self.assertEqual(self.snapshot(state, objects), before)
                    valid = canonical_json({'context': context.to_mapping(), 'intent': intent})
                    (objects.directory / base / 'command.json').write_bytes(valid)
                    self.assertEqual(self.admit(context, state, objects, intent), (context, None))
                    self.assertEqual(objects.read(base + '/command.json'), valid)

    def test_legacy_etl_normalized_context_timestamps_refuse_before_admission_mutation(self):
        from sec_edgar_ingest.results import result_path
        from sec_edgar_ingest.storage.contracts import Conflict
        for command in ('transform', 'publish'):
            for field in ('started_at', 'deadline'):
                with self.subTest(command=command, field=field):
                    _, state, objects, context, intent = self.bundle(command)
                    if command == 'publish':
                        intent = {**intent, 'force': None}
                    mapping = context.to_mapping()
                    mapping[field] = mapping[field].replace('+00:00', 'Z')
                    base = result_path(context).rsplit('/', 1)[0]
                    objects.put_once(base + '/command.json', canonical_json({'context': mapping, 'intent': intent}))
                    before = self.snapshot(state, objects)
                    with self.assertRaises(Conflict):
                        self.admit(context, state, objects, intent)
                    self.assertEqual(self.snapshot(state, objects), before)


class LocalAcquisitionContracts(unittest.TestCase):
    def test_context_requires_local_runtime_and_format(self):
        names = {item.name for item in fields(RunContext)}
        self.assertIn('runtime', names)
        self.assertIn('format_version', names)
        self.assertNotIn('image_digest', names)

    def test_runtime_changes_attempt_key_and_roundtrips(self):
        first = replace(fixture_context(), runtime=fixture_descriptor('release-a'))
        second = replace(first, runtime=fixture_descriptor('release-b'))
        self.assertNotEqual(attempt_key(first), attempt_key(second))
        self.assertEqual(RunContext.from_mapping(first.to_mapping()), first)
        old = first.to_mapping()
        old.pop('format_version')
        old['image_digest'] = 'sha256:' + '1' * 64
        with self.assertRaises(ValueError):
            RunContext.from_mapping(old)

    def test_context_rejects_missing_unknown_and_nested_runtime_fields(self):
        context = fixture_context()
        for field in context.to_mapping():
            value = context.to_mapping()
            del value[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                RunContext.from_mapping(value)
        cases = [dict(context.to_mapping(), unexpected=True),
                 dict(context.to_mapping(), format_version='sec-acquisition-v1')]
        for runtime in ({}, {'kind': 'fixture'},
                        dict(fixture_descriptor('a'), unexpected=True),
                        dict(fixture_descriptor('a'), fixture_sha256={'nested': 'a' * 64}),
                        dict(fixture_descriptor('a'), format_version='wrong')):
            cases.append(dict(context.to_mapping(), runtime=runtime))
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                RunContext.from_mapping(value)

    def test_runtime_mapping_is_detached_and_frozen(self):
        context = fixture_context()
        mapping = context.to_mapping()
        mapping['runtime']['fixture_sha256'] = 'f' * 64
        mapping['effective_config']['runtime']['fixture_id'] = 'changed'
        self.assertEqual(dict(context.runtime), fixture_descriptor(fixture_settings().runtime.fixture_id))
        with self.assertRaises(TypeError):
            context.runtime['kind'] = 'native'

    def test_worksets_have_local_format_and_canonical_digest(self):
        source = fixture_source()
        workset = fixture_workset((source,))
        snapshot = make_snapshot_workset(workset, (fixture_snapshot(source, b'raw fixture'),))
        for item, decoder in ((workset, decode_source_workset), (snapshot, decode_snapshot_workset)):
            body = encode_workset(item)
            self.assertEqual(parse_json(body)['format_version'], 'sec-local-acquisition-v1')
            self.assertEqual(encode_workset(decoder(body)), body)
            for key in ('format_version', 'workset_id', 'context'):
                value = parse_json(body)
                value.pop(key)
                with self.subTest(missing=key), self.assertRaises(ValueError):
                    decoder(canonical_json(value))
            value = parse_json(body)
            value['context']['runtime']['fixture_sha256'] = 'f' * 64
            with self.assertRaises(ValueError):
                decoder(canonical_json(value))
            value = parse_json(body)
            value['unexpected'] = True
            with self.assertRaises(ValueError):
                decoder(canonical_json(value))

    def test_snapshot_workset_retains_acquisition_origin(self):
        origin = fixture_context(command='discover')
        source = fixture_source()
        workset = fixture_workset((source,), context=origin)
        collector = replace(origin, command='collect', attempt_id='collector')
        result = make_snapshot_workset(workset, (fixture_snapshot(source, b'raw'),))
        self.assertEqual(result.context, origin)
        self.assertNotEqual(result.context, collector)

    def test_command_result_version_and_strict_roundtrip(self):
        context = fixture_context()
        result = CommandResult(format_version='sec-local-command-result-v1', context=context,
            outcome='success', source_workset_ref=None, snapshot_workset_ref=None,
            discovered=0, downloaded=0, unchanged=0, pending=0, failed=0, quarantined=0,
            gaps=(), started_at=context.started_at, ended_at=context.started_at)
        self.assertEqual(CommandResult.from_json(result.to_json()), result)
        self.assertEqual(result.to_json(), canonical_json(result.to_mapping()))
        for key in result.to_mapping():
            value = result.to_mapping()
            value.pop(key)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                CommandResult.from_mapping(value)
        for value in (dict(result.to_mapping(), unexpected=True),
                      dict(result.to_mapping(), format_version='sec-acquisition-v1')):
            with self.assertRaises(ValueError):
                CommandResult.from_mapping(value)
        exported = result.to_mapping()
        exported['context']['runtime']['fixture_sha256'] = 'f' * 64
        self.assertNotEqual(exported, result.to_mapping())

    def test_completed_retry_refuses_only_runtime_change_with_same_ids(self):
        from sec_edgar_ingest.cli import _matching_context
        from sec_edgar_ingest.storage.contracts import Conflict
        context = fixture_context()
        changed = replace(context, runtime=fixture_descriptor('different-release'))
        self.assertEqual((context.run_id, context.execution_id, context.attempt_id),
                         (changed.run_id, changed.execution_id, changed.attempt_id))
        with self.assertRaises(Conflict):
            _matching_context(context, changed, explicit_today=False)

    def test_run_halt_and_request_history_include_detached_runtime_provenance(self):
        import tempfile
        from pathlib import Path
        from support import store_bundle
        from sec_edgar_ingest.models import Error
        from sec_edgar_ingest.state import AcquisitionState
        from sec_edgar_ingest.storage.contracts import Conflict
        with tempfile.TemporaryDirectory() as temporary:
            settings = fixture_settings(root=Path(temporary))
            context = fixture_context(settings=settings)
            other = replace(context, runtime=fixture_descriptor('different-release'))
            store, _, leases = store_bundle(Path(temporary))
            self.addCleanup(store.close)
            self.addCleanup(leases.close)
            state = AcquisitionState(store)
            url = fixture_source().canonical_url
            state.begin_request(context, url, None, 'request-1', 1)
            self.assertEqual(len(state.request_history(context, url)), 1)
            self.assertEqual(state.request_history(other, url), ())
            error = Error('access_blocked', 'saved halt', False, None, {})
            state.halt_run(context, error)
            self.assertEqual(state.run_halt(context), error)
            row = tuple(store.scan('RunHalt', {}))[0].to_mapping()['value']
            self.assertEqual(row['provenance']['runtime'], context.to_mapping()['runtime'])
            with self.assertRaises(Conflict):
                state.run_halt(other)

    def test_download_fixture_rejects_supplied_context_from_another_root(self):
        import tempfile
        from pathlib import Path
        from support import DownloadHarness
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'store'
            harness = None
            try:
                with self.assertRaisesRegex(ValueError, 'context'):
                    harness = DownloadHarness([], root=root, context=fixture_context())
            finally:
                if harness is not None:
                    harness.close()
            self.assertFalse(root.exists(), 'mismatched provenance must fail before opening stores')

    def test_download_fixture_rejects_later_context_replacement_without_rewriting_it(self):
        from support import DownloadHarness
        harness = DownloadHarness([])
        self.addCleanup(harness.close)
        original = harness.context
        wrong = replace(fixture_context(), deadline=fixture_context().started_at.replace(hour=1))
        with self.assertRaisesRegex(ValueError, 'context'):
            harness.context = wrong
        self.assertIs(harness.context, original)
        self.assertNotEqual(wrong.config_sha256, harness.settings.config_sha256)

    def test_download_fixture_preserves_root_aware_overridden_context(self):
        import tempfile
        from datetime import timedelta
        from pathlib import Path
        from support import DownloadHarness
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = fixture_settings(root=root)
            base = fixture_context(settings=settings)
            context = replace(base, execution_id='deadline-execution', attempt_id='deadline-attempt',
                              deadline=base.started_at + timedelta(seconds=100))
            harness = DownloadHarness([], root=root, settings=settings, context=context)
            try:
                self.assertIs(harness.context, context)
                self.assertEqual(harness.context.config_sha256, harness.settings.config_sha256)
                self.assertEqual(harness.context.effective_config['storage']['root'], str(root.resolve()))
                self.assertEqual((harness.context.execution_id, harness.context.attempt_id),
                                 ('deadline-execution', 'deadline-attempt'))
            finally:
                harness.close()

    def test_download_fixture_rejects_supplied_settings_for_another_root(self):
        import tempfile
        from pathlib import Path
        from support import DownloadHarness
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'store'
            harness = None
            try:
                with self.assertRaisesRegex(ValueError, 'root'):
                    harness = DownloadHarness([], root=root, settings=fixture_settings())
            finally:
                if harness is not None:
                    harness.close()
            self.assertFalse(root.exists())

    def test_etl_fixture_context_requires_explicit_actual_store_root(self):
        from support_etl import etl_context
        with self.assertRaises(TypeError):
            etl_context()

    def test_etl_fixture_context_and_seed_snapshot_archive_actual_root(self):
        import tempfile
        from pathlib import Path
        from support_etl import etl_context, seed_snapshot
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings, context = etl_context('fixture-index-parser-v2', attempt='processing-v2', root=root)
            store, _, workset = seed_snapshot(root, fixture_source(), b'root provenance fixture')
            self.addCleanup(store.close)
            for saved in (context, workset.context):
                self.assertEqual(saved.effective_config['storage']['root'], str(root.resolve()))
                self.assertEqual(saved.config_sha256,
                                 type(settings).from_mapping(saved.to_mapping()['effective_config']).config_sha256)
            self.assertEqual(context.config_sha256, settings.config_sha256)
            self.assertEqual((context.parser_version, context.attempt_id), ('fixture-index-parser-v2', 'processing-v2'))
