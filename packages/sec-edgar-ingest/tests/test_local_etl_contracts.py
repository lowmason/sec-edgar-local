"""Offline ETL envelope and historical native producer identity contracts."""
import contextlib
import copy
import io
import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from support import fixture_source
from support_etl import etl_context, runtime_context, seed_snapshot
from test_runtime import native_identity
from sec_edgar_ingest import runtime
from sec_edgar_ingest.etl.catalog import build_candidate
from sec_edgar_ingest.etl.commands import read_etl_result, run_transform
from sec_edgar_ingest.etl.contracts import GenerationCapture, decode_transformed
from sec_edgar_ingest.etl.manifest import read_manifest
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.transform import _read_manifest, transform_member
from sec_edgar_ingest.models import canonical_json, parse_json, to_mapping_value
from sec_edgar_ingest.results import result_path
from sec_edgar_ingest.storage.contracts import Conflict


class LocalEtlContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings, self.context = etl_context(root=self.root)
        self.source = fixture_source('2026-10-01', 'daily')
        self.body = (b'CIK|Company Name|Form Type|Date Filed|File Name\n-----\n'
                     b'123456|Example|10-K|20261001|edgar/data/123456/0000123456-26-000001.txt\n')
        self.store, self.objects, self.snapshot_set = seed_snapshot(self.root, self.source, self.body)
        self.addCleanup(self.store.close)
        self.state = EtlState(self.store)
        self.snapshot = self.snapshot_set.snapshots[0]
        self.snapshot_ref = f'worksets/sec/snapshot/sha256={self.snapshot_set.workset_id}/workset.json'

    def transform(self):
        with contextlib.redirect_stderr(io.StringIO()):
            return run_transform(self.snapshot_ref, self.context, self.settings, self.objects, self.store)

    def use_native(self, manifest):
        path = self.root / 'releases' / ('sha256=' + manifest['release_id']) / 'release.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json(manifest))
        return runtime_context(self.settings, self.context,
                               {'kind': 'native', 'release_manifest': str(path)})

    def observation(self):
        return transform_member(self.source, self.snapshot, self.context, self.settings, self.objects, self.state)

    def generation(self):
        candidate = build_candidate('2026Q4', None, (self.observation(),), self.context,
                                    self.settings, self.objects, self.state)
        capture = GenerationCapture('2026Q4', candidate.manifest.generation_id, candidate.manifest_ref,
                                    candidate.manifest_sha256, candidate.manifest_bytes)
        return candidate, capture

    @staticmethod
    def native_manifest():
        identity = native_identity()
        # Saved release evidence must not be compared with the current environment.
        identity['application'] = {'name': 'sec-edgar-ingest', 'version': '0.1.0',
                                   'wheel_filename': 'sec_edgar_ingest-0.1.0-py3-none-any.whl'}
        identity['interpreter']['version'] = '3.14.1'
        return {'format_version': 'sec-native-release-v1', 'identity': identity,
                'release_id': hashlib.sha256(canonical_json(identity)).hexdigest()}

    def producer_api(self):
        self.assertTrue(callable(getattr(runtime, 'validate_producer', None)),
                        'historical ETL readers require saved native producer validation')
        self.assertTrue(callable(getattr(runtime, 'retain_manifest', None)),
                        'native producer manifests require explicit write-once retention')

    def save_native(self):
        self.producer_api()
        manifest = self.native_manifest()
        key = runtime.retain_manifest(self.objects, manifest)
        return manifest, key, runtime.native_descriptor(manifest['release_id'])

    def test_observation_uses_exact_local_envelope(self):
        ref = self.observation()
        body = self.objects.read(ref.manifest_ref)
        value = parse_json(body)
        self.assertEqual(set(value), {'format_version', 'observation', 'runtime'})
        self.assertEqual(value['format_version'], 'sec-local-observation-v1')
        self.assertEqual(value['runtime'], to_mapping_value(self.context.runtime))
        self.assertEqual(canonical_json(value), body)
        self.assertEqual(_read_manifest(ref.manifest_ref, self.objects), (ref, body))

    def test_observation_rejects_versions_runtime_fields_and_noncanonical_bytes(self):
        ref = self.observation()
        body = self.objects.read(ref.manifest_ref)
        original = parse_json(body)
        variants = [{**original, 'format_version': version}
                    for version in ('sec-observation-v1', 'future')]
        variants += [{key: value for key, value in original.items() if key != field}
                     for field in ('format_version', 'runtime')]
        variants += [{**original, 'runtime': descriptor} for descriptor in
                     ({}, {**original['runtime'], 'extra': True},
                      {key: value for key, value in original['runtime'].items() if key != 'fixture_sha256'})]
        variants.append({**original, 'image_digest': 'sha256:' + 'f' * 64})
        path = self.root / 'objects' / ref.manifest_ref
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                path.write_bytes(canonical_json(value))
                _read_manifest(ref.manifest_ref, self.objects)
        path.write_bytes(b' ' + body)
        with self.assertRaises(ValueError):
            _read_manifest(ref.manifest_ref, self.objects)

    def test_observation_refuses_wrong_own_address(self):
        ref = self.observation()
        wrong = 'observations/wrong/manifest.json'
        self.objects.put_once(wrong, self.objects.read(ref.manifest_ref))
        with self.assertRaisesRegex(ValueError, 'address'):
            _read_manifest(wrong, self.objects)

    def test_transformed_local_codec_hash_and_runtime_are_strict(self):
        result = self.transform()
        body = self.objects.read(result.transformed_workset_ref)
        value = parse_json(body)
        self.assertEqual(value['format_version'], 'sec-local-transformed-workset-v1')
        self.assertEqual(decode_transformed(body).context, self.context)
        identity = {key: item for key, item in value.items() if key != 'workset_id'}
        self.assertEqual(value['workset_id'], hashlib.sha256(canonical_json(identity)).hexdigest())
        variants = [{**value, 'format_version': version} for version in ('sec-transformed-workset-v1', 'future')]
        variants += [{key: item for key, item in value.items() if key != 'format_version'},
                     {**value, 'workset_id': 'f' * 64}, {**value, 'unknown': True}]
        for context_field in ('origin_context', 'context'):
            for mutation in ('missing', 'extra', 'digest'):
                changed = copy.deepcopy(value)
                descriptor = changed[context_field]['runtime']
                if mutation == 'missing': del changed[context_field]['runtime']
                elif mutation == 'extra': descriptor['extra'] = True
                else: descriptor['fixture_sha256'] = 'invalid'
                variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                decode_transformed(canonical_json(changed))
        with self.assertRaises(ValueError):
            decode_transformed(b' ' + body)

    def test_generation_local_codec_versions_runtime_hash_and_address_are_strict(self):
        candidate, capture = self.generation()
        original = self.objects.read(capture.manifest_ref)
        value = parse_json(original)
        self.assertEqual(value['format_version'], 'sec-local-generation-v1')
        self.assertEqual(value['runtime'], to_mapping_value(self.context.runtime))
        self.assertEqual(read_manifest(capture, self.objects), candidate.manifest)
        variants = [{**value, 'format_version': version} for version in ('sec-generation-v1', 'future')]
        variants += [{key: item for key, item in value.items() if key != field}
                     for field in ('format_version', 'runtime')]
        variants += [{**value, 'runtime': descriptor} for descriptor in
                     ({}, {**value['runtime'], 'unknown': True}, {'kind': 'fixture'})]
        variants += [{**value, 'generation_id': 'f' * 64}, {**value, 'unknown': True}]
        path = self.root / 'objects' / capture.manifest_ref
        for changed in variants:
            body = canonical_json(changed)
            path.write_bytes(body)
            changed_capture = replace(capture, manifest_sha256=hashlib.sha256(body).hexdigest(), manifest_bytes=len(body))
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                read_manifest(changed_capture, self.objects)
        body = b' ' + original
        path.write_bytes(body)
        with self.assertRaises(ValueError):
            read_manifest(replace(capture, manifest_sha256=hashlib.sha256(body).hexdigest(), manifest_bytes=len(body)), self.objects)
        path.write_bytes(original + b' ')
        with self.assertRaises(Conflict):
            read_manifest(capture, self.objects)
        with self.assertRaisesRegex(ValueError, 'address'):
            read_manifest(replace(capture, manifest_ref='curated/wrong/manifest.json'), self.objects)

    def test_result_local_codec_versions_context_runtime_canonical_and_address(self):
        result = self.transform()
        value = result.to_mapping()
        self.assertEqual(value['format_version'], 'sec-local-etl-result-v1')
        path = result_path(self.context)
        body = canonical_json(value)
        self.objects.put_once(path, body)
        self.assertEqual(read_etl_result(path, self.objects), result)
        variants = [{**value, 'format_version': version} for version in ('sec-etl-result-v1', 'future')]
        variants += [{key: item for key, item in value.items() if key != 'format_version'},
                     {**value, 'unknown': True}]
        for mutation in ('missing', 'extra', 'digest'):
            changed = copy.deepcopy(value)
            if mutation == 'missing': del changed['context']['runtime']
            elif mutation == 'extra': changed['context']['runtime']['extra'] = True
            else: changed['context']['runtime']['fixture_sha256'] = 'invalid'
            variants.append(changed)
        target = self.root / 'objects' / path
        for changed in variants:
            target.write_bytes(canonical_json(changed))
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                read_etl_result(path, self.objects)
        target.write_bytes(b' ' + body)
        with self.assertRaises(Conflict):
            read_etl_result(path, self.objects)
        wrong = 'results/wrong/result.json'
        self.objects.put_once(wrong, body)
        with self.assertRaises(Conflict):
            read_etl_result(wrong, self.objects)

    def test_retention_is_canonical_write_once_and_validates_digest(self):
        manifest, key, descriptor = self.save_native()
        self.assertEqual(key, f"runtime/native/sha256={manifest['release_id']}/release.json")
        body = self.objects.read(key)
        self.assertEqual(body, canonical_json(manifest))
        self.assertEqual(runtime.retain_manifest(self.objects, dict(reversed(list(manifest.items())))), key)
        self.assertEqual(self.objects.read(key), body)
        invalid = copy.deepcopy(manifest)
        invalid['identity']['git_revision'] = '2' * 40
        before = set((self.root / 'objects/runtime').rglob('release.json'))
        with self.assertRaises(ValueError):
            runtime.retain_manifest(self.objects, invalid)
        self.assertEqual(set((self.root / 'objects/runtime').rglob('release.json')), before)
        (self.root / 'objects' / key).write_bytes(b'corrupt')
        with self.assertRaises(Conflict):
            runtime.retain_manifest(self.objects, manifest)

    def test_historical_producer_validation_never_reads_current_environment_or_writes(self):
        manifest, key, descriptor = self.save_native()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with (patch.object(self.objects, 'put_once', side_effect=AssertionError('read wrote evidence')),
              patch.object(runtime, 'configured_descriptor', side_effect=AssertionError('current runtime read'))):
            runtime.validate_producer(descriptor, self.objects)
            runtime.validate_producer(runtime.fixture_descriptor('fixture'), self.objects)
        self.assertEqual({p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    def test_native_producer_refuses_missing_corrupt_noncanonical_or_wrong_saved_manifest(self):
        manifest, key, descriptor = self.save_native()
        target = self.root / 'objects' / key
        target.unlink()
        with self.assertRaises(FileNotFoundError):
            runtime.validate_producer(descriptor, self.objects)
        variants = [b'corrupt', b' ' + canonical_json(manifest)]
        invalid = copy.deepcopy(manifest)
        invalid['identity']['git_revision'] = '2' * 40
        variants.append(canonical_json(invalid))
        other = copy.deepcopy(invalid)
        other['release_id'] = hashlib.sha256(canonical_json(other['identity'])).hexdigest()
        variants.append(canonical_json(other))
        for body in variants:
            target.write_bytes(body)
            with self.subTest(body=body[:80]), self.assertRaises(ValueError):
                runtime.validate_producer(descriptor, self.objects)

    def test_observation_and_generation_historical_reads_validate_saved_native_producer(self):
        manifest, key, descriptor = self.save_native()
        candidate, capture = self.generation()
        observation = candidate.manifest.sources[0]
        for path in (observation.manifest_ref, capture.manifest_ref):
            value = parse_json(self.objects.read(path))
            value['runtime'] = descriptor
            (self.root / 'objects' / path).write_bytes(canonical_json(value))
        generation_body = self.objects.read(capture.manifest_ref)
        capture = replace(capture, manifest_sha256=hashlib.sha256(generation_body).hexdigest(), manifest_bytes=len(generation_body))
        with patch.object(self.objects, 'put_once', side_effect=AssertionError('verify wrote')):
            self.assertEqual(_read_manifest(observation.manifest_ref, self.objects)[0], observation)
            self.assertEqual(dict(read_manifest(capture, self.objects).runtime), descriptor)
        target = self.root / 'objects' / key
        other = copy.deepcopy(manifest)
        other['identity']['git_revision'] = '2' * 40
        other['release_id'] = hashlib.sha256(canonical_json(other['identity'])).hexdigest()
        target.write_bytes(canonical_json(other))
        with self.assertRaises(ValueError):
            _read_manifest(observation.manifest_ref, self.objects)
        with self.assertRaises(ValueError):
            read_manifest(capture, self.objects)

    def test_native_release_change_forced_cache_keeps_exact_original_producer(self):
        manifest, key, descriptor = self.save_native()
        first_settings, first_context = self.use_native(manifest)
        original = transform_member(self.source, self.snapshot, first_context, first_settings, self.objects, self.state)
        first_bytes = self.objects.read(original.manifest_ref)
        manifest['identity']['application_wheel_sha256'] = '9' * 64
        manifest['release_id'] = hashlib.sha256(canonical_json(manifest['identity'])).hexdigest()
        runtime.retain_manifest(self.objects, manifest)
        next_settings, next_context = self.use_native(manifest)
        self.assertNotEqual(first_context.runtime, next_context.runtime)
        for force in (False, True):
            with self.subTest(force=force):
                reused = transform_member(self.source, self.snapshot, next_context, next_settings,
                                          self.objects, self.state, force=force)
                self.assertEqual(reused, original)
                self.assertEqual(self.objects.read(reused.manifest_ref), first_bytes)
                self.assertEqual(parse_json(first_bytes)['runtime'], to_mapping_value(first_context.runtime))

    def test_native_release_only_generation_is_noop_with_original_bytes(self):
        manifest, key, descriptor = self.save_native()
        self.settings, self.context = self.use_native(manifest)
        first, capture = self.generation()
        original = self.objects.read(first.manifest_ref)
        manifest['identity']['application_wheel_sha256'] = '9' * 64
        manifest['release_id'] = hashlib.sha256(canonical_json(manifest['identity'])).hexdigest()
        runtime.retain_manifest(self.objects, manifest)
        self.settings, self.context = self.use_native(manifest)
        self.assertNotEqual(dict(self.context.runtime), descriptor)
        for previous in (None, capture):
            with self.subTest(previous=previous):
                reused = build_candidate('2026Q4', previous, first.manifest.sources, self.context,
                                         self.settings, self.objects, self.state)
                self.assertEqual(reused, first)
                self.assertEqual(self.objects.read(reused.manifest_ref), original)
                self.assertEqual(parse_json(original)['runtime'], descriptor)
