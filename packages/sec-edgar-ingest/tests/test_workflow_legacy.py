from network_guard import install
install()
from sec_edgar_ingest.models import to_mapping_value
import hashlib, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from support_workflows import BASE, CommandHarness, simple_pack
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage.local import LocalObjectStore, LocalStateStore
from sec_edgar_ingest.state import AcquisitionState
from sec_edgar_ingest.workflows.legacy import bootstrap_legacy
from sec_edgar_ingest.workflows.provenance import read_member, read_parent

class Crash(BaseException):
    pass

class LegacyTests(unittest.TestCase):
    def test_old_downloaded_unit_keeps_parent_and_exact_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                code, discovery = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'legacy'))
                self.assertEqual(code, 0)
                code, collection = h.invoke('collect', ('--workset', discovery['source_workset_ref']))
                self.assertEqual(code, 0)
                acquisition = AcquisitionState(h.store)
                parent = read_parent(discovery['source_workset_ref'], h.store, h.objects)
                original_pin = acquisition.binding(parent.workset_id, parent.members[0].source_id)
                self.assertIsNotNone(original_pin)
                self.assertEqual(tuple(h.store.scan('WorkflowMember', {})), ())
                self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                values = tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {}))
                self.assertEqual(len(values), 1)
                member = read_member(values[0], h.store, h.objects)
                self.assertEqual(values[0]['parent_ref'], discovery['source_workset_ref'])
                self.assertEqual(acquisition.binding(member.workset_id, parent.members[0].source_id).snapshot_sha256,
                                 original_pin.snapshot_sha256)
                for repeat in range(3):
                    self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                    self.assertEqual(tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {})), values)
                self.assertFalse(any(value['parent_ref'] in {v['member_ref'] for v in values} for value in values))
            finally:
                h.close()

    def test_crash_before_parent_write_recovers_all_original_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            original_put = LocalObjectStore.put_once
            def stop_parent(objects, path, body):
                if path.startswith('worksets/sec/source/'):
                    raise Crash('before original parent-object write')
                return original_put(objects, path, body)
            try:
                with patch.object(LocalObjectStore, 'put_once', stop_parent):
                    with self.assertRaises(Crash):
                        h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'interrupted'))
                acquisition = AcquisitionState(h.store)
                before = acquisition.discovery_session('interrupted').to_mapping()
                self.assertIsNone(before['value']['workset_id'])
                self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                self.assertEqual(acquisition.discovery_session('interrupted').to_mapping(), before)
                values = tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {}))
                self.assertEqual(len(values), 1)
                recovered = read_parent(values[0]['parent_ref'], h.store, h.objects)
                self.assertEqual({d.url for d in recovered.directories},
                                 {u['url'] for u in before['value']['frozen']['units']})
                self.assertNotIn(recovered.workset_id, {before['value']['workset_id'], before['value']['predecessor_workset_id']})
                self.assertNotIn(recovered.workset_id, {item['workset_id'] for item in before['value']['history']})
                self.assertTrue(recovered.discovery_complete)
                self.assertIsNotNone(h.store.get('WorkflowParentRecovery', recovered.workset_id))
                self.assertEqual(read_member(values[0], h.store, h.objects).members, recovered.members)
            finally:
                h.close()

    def test_missing_progress_is_failed_and_does_not_invent_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            original_insert = LocalStateStore.insert
            missing = BASE + 'daily-index/2026/QTR4/index.json'
            def stop_unit(store, kind, key, value):
                if kind == 'DirectoryProgress' and value['outcome']['url'] == missing:
                    raise Crash('before successful quarter progress write')
                return original_insert(store, kind, key, value)
            try:
                with patch.object(LocalStateStore, 'insert', stop_unit):
                    with self.assertRaises(Crash):
                        h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'missing'))
                before = AcquisitionState(h.store).discovery_session('missing').to_mapping()
                self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                captures = tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowParentRecovery', {}))
                self.assertEqual(len(captures), 1)
                from sec_edgar_ingest.models import parse_json
                recovery = parse_json(h.objects.read(captures[0]['ref']))
                parent = read_parent(recovery['parent_ref'], h.store, h.objects)
                self.assertFalse(parent.discovery_complete)
                self.assertEqual(parent.members, ())
                self.assertEqual(next(d for d in parent.directories if d.url == missing).error.code, 'discovery_pending')
                self.assertEqual(AcquisitionState(h.store).discovery_session('missing').to_mapping(), before)
            finally:
                h.close()

    def test_corrupt_parent_is_isolated_from_valid_sibling_and_never_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                code, bad = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'bad'), run='bad')
                self.assertEqual(code, 0)
                code, good = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'good'), run='good')
                self.assertEqual(code, 0)
                target = h.objects.directory / bad['source_workset_ref']
                original = target.read_bytes()
                target.write_bytes(original + b' ')
                try:
                    gaps = bootstrap_legacy(h.store, h.objects)
                    self.assertTrue(any(g.code == 'legacy_member_unresolved' for g in gaps))
                    self.assertTrue(all('record_sha256' in g.details for g in gaps))
                    values = tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {}))
                    self.assertEqual(len(values), 1)
                    self.assertEqual(values[0]['parent_ref'], good['source_workset_ref'])
                finally:
                    target.write_bytes(original)
                self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                values = tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {}))
                self.assertEqual(len(values), 2)
                for repeat in range(3):
                    self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                    self.assertEqual(tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {})), values)
                code, fresh = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'fresh'), run='fresh')
                self.assertEqual(code, 0)
                self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                values = tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {}))
                self.assertEqual(len(values), 3)
                singleton_refs = {value['member_ref'] for value in values}
                self.assertFalse(any(value['parent_ref'] in singleton_refs for value in values))
                for value in values:
                    read_member(value, h.store, h.objects)
            finally:
                h.close()
    def test_recovery_capture_tampering_refuses(self):
        from copy import deepcopy
        from dataclasses import replace
        from sec_edgar_ingest.models import DirectoryOutcome, Error, parse_json
        from sec_edgar_ingest.storage.contracts import Conflict
        from sec_edgar_ingest.workflows.legacy import reconstruct_parent
        from sec_edgar_ingest.workflows.provenance import validate_parent_recovery
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                code, discovered = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'capture'))
                self.assertEqual(code, 0)
                session = AcquisitionState(h.store).discovery_session('capture').to_mapping()['value']
                ref = reconstruct_parent(session, h.store, h.objects)
                parent = read_parent(ref, h.store, h.objects)
                descriptor = h.store.get('WorkflowParentRecovery', parent.workset_id).to_mapping()['value']
                saved = parse_json(h.objects.read(descriptor['ref']))
                validate_parent_recovery(ref, descriptor, h.objects)
                variants = []
                changed = deepcopy(saved)
                changed['session']['frozen']['context']['execution_id'] = 'other'
                variants.append(changed)
                changed = deepcopy(saved)
                changed['progress'] = changed['progress'][1:]
                variants.append(changed)
                changed = deepcopy(saved)
                next(p for p in changed['progress'] if p['unit']['role'] == 'root')['value'] = None
                variants.append(changed)
                changed = deepcopy(saved)
                item = next(p for p in changed['progress'] if p['value'] and p['value']['members'])
                directory = DirectoryOutcome.from_mapping(item['value']['outcome'])
                item['value']['outcome'] = replace(directory, outcome='discovery_failed', listing_sha256=None,
                    source_ids=(), error=Error('discovery_pending', 'not complete', True, None, {})).to_mapping()
                item['value']['evidence'] = None
                variants.append(changed)
                changed = deepcopy(saved)
                changed['parent']['pinned_end_quarter'] = '2026Q3'
                variants.append(changed)
                changed = deepcopy(saved)
                changed['parent']['members'][0]['canonical_url'] += '.other'
                variants.append(changed)
                changed = deepcopy(saved)
                changed['parent']['members'][0]['source_id'] = '0' * 64
                variants.append(changed)
                changed = deepcopy(saved)
                root_progress = next(p for p in changed['progress'] if p['unit']['role'] == 'root')
                root_progress['value']['outcome'] = replace(
                    DirectoryOutcome.from_mapping(root_progress['value']['outcome']),
                    outcome='discovery_failed', listing_sha256=None, source_ids=(),
                    error=Error('discovery_pending', 'missing original ancestor', True, None, {})).to_mapping()
                root_progress['value']['members'] = []
                root_progress['value']['evidence'] = None
                variants.append(changed)
                changed = deepcopy(saved)
                root_progress = next(p for p in changed['progress'] if p['unit']['role'] == 'root')
                evidence = root_progress['value']['evidence']
                listing = parse_json(h.objects.read(evidence['body_path']))
                listing['directory']['item'] = [item for item in listing['directory']['item'] if item['name'] != '2026']
                listing_body = canonical_json(to_mapping_value(listing))
                listing_digest = hashlib.sha256(listing_body).hexdigest()
                evidence['body_path'] += '.unadvertised'
                h.objects.put_once(evidence['body_path'], listing_body)
                evidence['sha256'], evidence['byte_count'] = listing_digest, len(listing_body)
                receipt = parse_json(h.objects.read(evidence['receipt_path']))
                receipt['body_path'] = evidence['body_path']
                receipt['receipt']['sha256'], receipt['receipt']['byte_count'] = listing_digest, len(listing_body)
                receipt_body = canonical_json(to_mapping_value(receipt))
                evidence['receipt_path'] += '.unadvertised'
                h.objects.put_once(evidence['receipt_path'], receipt_body)
                evidence['receipt_sha256'], evidence['receipt_byte_count'] = hashlib.sha256(receipt_body).hexdigest(), len(receipt_body)
                root_progress['value']['outcome']['listing_sha256'] = listing_digest
                variants.append(changed)
                for number, altered in enumerate(variants):
                    with self.subTest(number=number):
                        body = canonical_json(to_mapping_value(altered))
                        digest = hashlib.sha256(body).hexdigest()
                        path = 'worksets/sec/workflow-parent-recovery/sha256=' + digest + '/recovery.json'
                        h.objects.put_once(path, body)
                        with self.assertRaises((Conflict, ValueError, OSError, KeyError)):
                            validate_parent_recovery(ref, {'ref': path, 'sha256': digest, 'bytes': len(body)}, h.objects)
                for altered in ({**descriptor, 'ref': descriptor['ref'] + '.other'},
                                {**descriptor, 'sha256': '0' * 64},
                                {**descriptor, 'bytes': descriptor['bytes'] + 1}):
                    with self.subTest(descriptor=altered):
                        with self.assertRaises((Conflict, ValueError, OSError)):
                            validate_parent_recovery(ref, altered, h.objects)
                self.assertEqual(AcquisitionState(h.store).discovery_session('capture').to_mapping()['value'], session)
            finally:
                h.close()

    def test_legacy_registry_and_capture_survive_close_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = simple_pack(root / 'pack')
            h = CommandHarness(root, pack)
            try:
                code, discovered = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'reopen'))
                self.assertEqual(code, 0)
                code, collected = h.invoke('collect', ('--workset', discovered['source_workset_ref']))
                self.assertEqual(code, 0)
                self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                before = tuple(row.to_mapping() for row in h.store.scan('WorkflowMember', {}))
                session = AcquisitionState(h.store).discovery_session('reopen').to_mapping()
                from sec_edgar_ingest.workflows.legacy import reconstruct_parent
                recovered_ref = reconstruct_parent(session['value'], h.store, h.objects)
                recovered = read_parent(recovered_ref, h.store, h.objects)
                self.assertIsNotNone(h.store.get('WorkflowParentRecovery', recovered.workset_id))
                index_hashes = {kind: hashlib.sha256(canonical_json(to_mapping_value(
                    tuple(row.to_mapping() for row in h.store.scan(kind, {}))))).hexdigest()
                    for kind in ('DiscoverySession', 'WorkflowMember', 'WorkflowParentRecovery', 'Binding')}
                object_hashes = {str(path.relative_to(h.objects.directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in h.objects.directory.rglob('*') if path.is_file()}
                h.close()
                h = CommandHarness(root, pack)
                self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                self.assertEqual(tuple(row.to_mapping() for row in h.store.scan('WorkflowMember', {})), before)
                self.assertEqual(AcquisitionState(h.store).discovery_session('reopen').to_mapping(), session)
                for row in before:
                    read_member(row['value'], h.store, h.objects)
                self.assertEqual({kind: hashlib.sha256(canonical_json(to_mapping_value(
                    tuple(row.to_mapping() for row in h.store.scan(kind, {}))))).hexdigest()
                    for kind in index_hashes}, index_hashes)
                self.assertEqual({str(path.relative_to(h.objects.directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in h.objects.directory.rglob('*') if path.is_file()}, object_hashes)
            finally:
                h.close()

    def test_corrupt_source_and_processing_do_not_hide_valid_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                code, discovered = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'corrupt-state'))
                self.assertEqual(code, 0)
                code, collected = h.invoke('collect', ('--workset', discovered['source_workset_ref']))
                self.assertEqual(code, 0)
                code, transformed = h.invoke('transform', ('--workset', collected['snapshot_workset_ref']))
                self.assertEqual(code, 0)
                parent = read_parent(discovered['source_workset_ref'], h.store, h.objects)
                identity = parent.members[0].source_id
                source_row = h.store.get('Source', identity)
                source_value = source_row.to_mapping()['value']
                source_value['source']['source_id'] = '0' * 64
                h.store.replace('Source', identity, source_value, source_row.version)
                processing_row = next(h.store.scan('Processing', {}))
                processing_value = processing_row.to_mapping()['value']
                processing_value['observation']['source']['source_id'] = '0' * 64
                h.store.replace('Processing', processing_value['processing_key'], processing_value, processing_row.version)
                gaps = bootstrap_legacy(h.store, h.objects)
                self.assertTrue({'Source', 'Processing'} <= {g.details['record_kind'] for g in gaps})
                self.assertTrue(all(g.code == 'legacy_member_unresolved' and 'record_sha256' in g.details for g in gaps))
                values = tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {}))
                self.assertEqual(len(values), 1)
                self.assertEqual(values[0]['parent_ref'], discovered['source_workset_ref'])
                read_member(values[0], h.store, h.objects)
            finally:
                h.close()


    def test_divergent_binding_winner_refuses_and_preserves_original_bytes(self):
        from support import fixture_snapshot
        from sec_edgar_ingest.models import Binding
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                code, discovered = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'winner'))
                self.assertEqual(code, 0)
                code, collected = h.invoke('collect', ('--workset', discovered['source_workset_ref']))
                self.assertEqual(code, 0)
                parent = read_parent(discovered['source_workset_ref'], h.store, h.objects)
                acquisition = AcquisitionState(h.store)
                source = parent.members[0]
                original = acquisition.binding(parent.workset_id, source.source_id)
                snapshot = acquisition.snapshot(source.source_id, original.snapshot_sha256)
                raw = h.objects.read(snapshot.raw_path)
                self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                value = next(h.store.scan('WorkflowMember', {})).to_mapping()['value']
                alternate = fixture_snapshot(source, b'divergent immutable bytes')
                h.objects.put_once(alternate.raw_path, b'divergent immutable bytes')
                acquisition.remember_snapshot(alternate)
                key = value['member_id'] + ':' + source.source_id
                row = h.store.get('Binding', key)
                h.store.replace('Binding', key, Binding(value['member_id'], source.source_id, alternate.sha256).to_mapping(), row.version)
                before = h.store.get('Binding', key).to_mapping()
                gaps = bootstrap_legacy(h.store, h.objects)
                self.assertTrue(any(g.code == 'legacy_member_unresolved' and g.details['record_kind'] == 'SourceWorkset' for g in gaps))
                self.assertEqual(h.store.get('Binding', key).to_mapping(), before)
                self.assertEqual(acquisition.binding(parent.workset_id, source.source_id), original)
                self.assertEqual(h.objects.read(snapshot.raw_path), raw)
            finally:
                h.close()

    def test_corrupt_projection_is_never_adopted_as_original_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            try:
                code, discovered = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'projection'))
                self.assertEqual(code, 0)
                self.assertEqual(bootstrap_legacy(h.store, h.objects), ())
                row = next(h.store.scan('WorkflowMember', {}))
                value = row.to_mapping()['value']
                value['source']['source_id'] = '0' * 64
                h.store.replace('WorkflowMember', value['member_id'], value, row.version)
                before = tuple(row.to_mapping() for row in h.store.scan('WorkflowMember', {}))
                session_row = AcquisitionState(h.store).discovery_session('projection')
                session = session_row.to_mapping()['value']
                session['history'].append({'workset_id': value['member_id']})
                h.store.replace('DiscoverySession', hashlib.sha256(b'projection').hexdigest(), session, session_row.version)
                gaps = bootstrap_legacy(h.store, h.objects)
                self.assertTrue({'WorkflowMember', 'DiscoverySession'} <= {g.details['record_kind'] for g in gaps})
                self.assertTrue(all('record_sha256' in g.details for g in gaps))
                self.assertEqual(tuple(row.to_mapping() for row in h.store.scan('WorkflowMember', {})), before)
                self.assertFalse(any(row.to_mapping()['value']['parent_ref'] == value['member_ref']
                                     for row in h.store.scan('WorkflowMember', {})))
            finally:
                h.close()

    def test_malformed_frozen_unit_is_isolated_from_valid_sibling(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = CommandHarness(root, simple_pack(root / 'pack'))
            original_put = LocalObjectStore.put_once
            def stop_parent(objects, path, body):
                if path.startswith('worksets/sec/source/'):
                    raise Crash('before malformed original parent write')
                return original_put(objects, path, body)
            try:
                with patch.object(LocalObjectStore, 'put_once', stop_parent):
                    with self.assertRaises(Crash):
                        h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'malformed'), run='malformed')
                code, valid = h.invoke('discover', ('--mode', 'daily', '--discovery-id', 'valid-sibling'), run='valid-sibling')
                self.assertEqual(code, 0)
                key = hashlib.sha256(b'malformed').hexdigest()
                original = h.store.get('DiscoverySession', key).to_mapping()['value']
                variants = []
                for url in (123, None, [], {}):
                    changed = deepcopy(original)
                    changed['frozen']['units'][0]['url'] = url
                    variants.append(changed)
                changed = deepcopy(original)
                changed['frozen']['units'][0] = None
                variants.append(changed)
                changed = deepcopy(original)
                changed['frozen']['units'] = {'url': 'invalid-ledger-shape'}
                variants.append(changed)
                for changed in variants:
                    with self.subTest(units=changed['frozen']['units']):
                        row = h.store.get('DiscoverySession', key)
                        h.store.replace('DiscoverySession', key, changed, row.version)
                        before = canonical_json(to_mapping_value(h.store.get('DiscoverySession', key).to_mapping()))
                        gaps = bootstrap_legacy(h.store, h.objects)
                        self.assertTrue(any(g.code == 'legacy_member_unresolved' and
                            g.details['record_kind'] == 'DiscoverySession' and
                            g.details['record_sha256'] == hashlib.sha256(canonical_json(to_mapping_value(changed))).hexdigest()
                            for g in gaps))
                        values = tuple(row.to_mapping()['value'] for row in h.store.scan('WorkflowMember', {}))
                        self.assertEqual(len(values), 1)
                        self.assertEqual(values[0]['parent_ref'], valid['source_workset_ref'])
                        read_member(values[0], h.store, h.objects)
                        self.assertEqual(canonical_json(to_mapping_value(h.store.get('DiscoverySession', key).to_mapping())), before)
            finally:
                h.close()
