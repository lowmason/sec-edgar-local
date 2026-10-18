"""Pure strict local acquisition codecs and provenance regressions."""
import unittest
from dataclasses import fields, replace

from support import fixture_context, fixture_settings, fixture_snapshot, fixture_source, fixture_workset
from sec_edgar_ingest.models import CommandResult, RunContext, canonical_json, parse_json
from sec_edgar_ingest.runtime import fixture_descriptor
from sec_edgar_ingest.state import attempt_key
from sec_edgar_ingest.worksets import (
    decode_snapshot_workset, decode_source_workset, encode_workset, make_snapshot_workset,
)


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
