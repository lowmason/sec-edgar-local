from network_guard import install
install()
from sec_edgar_ingest.models import to_mapping_value
import tempfile, unittest
from datetime import date
from pathlib import Path
from support import discovery_harness, listing_response, failed_response
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows.provenance import project_member, read_member

class ProvenanceTests(unittest.TestCase):
    def test_valid_member_of_failed_parent_retains_original_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {
                '2026Q3': [failed_response(404)],
                '2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])],
            })
            try:
                parent = h.run('daily', date(2026, 10, 7), 'provenance')
                self.assertFalse(parent.discovery_complete)
                parent_ref = h.workset_path(parent)
                parent_bytes = h.objects.read(parent_ref)
                value = project_member(parent_ref, parent.members[0].source_id, h.store, h.objects)
                child = read_member(value, h.store, h.objects)
                self.assertTrue(child.discovery_complete)
                self.assertEqual(child.members, (parent.members[0],))
                self.assertEqual(child.context, parent.context)
                self.assertEqual(h.objects.read(parent_ref), parent_bytes)
                self.assertEqual(value['parent_ref'], parent_ref)
                self.assertEqual(project_member(parent_ref, parent.members[0].source_id,
                                               h.store, h.objects), value)
                self.assertEqual(len(tuple(h.store.scan('WorkflowMember', {}))), 1)
                progress = h.state.directory_progress('provenance', child.directories[0].url)
                body_path = progress.value['evidence']['body_path']
                target = h.root / 'objects' / body_path
                retained = target.read_bytes()
                target.write_bytes(retained + b' ')
                try:
                    with self.assertRaises((Conflict, ValueError, OSError)):
                        read_member(value, h.store, h.objects)
                finally:
                    target.write_bytes(retained)
            finally:
                h.close()
    def test_corrupt_registry_is_reported_without_hiding_valid_sibling(self):
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {
                '2026Q4': [listing_response('2026Q4', ['master.20261001.idx', 'master.20261002.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'two-members')
                values = [project_member(h.workset_path(parent), source.source_id, h.store, h.objects)
                          for source in parent.members]
                self.assertEqual(len(values), 2)
                row = h.store.get('WorkflowMember', values[0]['member_id'])
                altered = row.to_mapping()['value']; altered['source']['period'] = '2026-10-03'
                h.store.replace('WorkflowMember', values[0]['member_id'], altered, row.version)
                valid, gaps = WorkflowMembers(h.store, h.objects).inventory()
                self.assertEqual(valid, (values[1],))
                self.assertEqual(len(gaps), 1)
                self.assertEqual(gaps[0].code, 'legacy_member_unresolved')
            finally:
                h.close()

    def test_retained_parent_and_member_tampering_refuses(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {
                '2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'tamper-member')
                value = project_member(h.workset_path(parent), parent.members[0].source_id, h.store, h.objects)
                variants = []
                for key in ('member_id', 'parent_ref', 'member_ref'):
                    altered = deepcopy(value)
                    altered[key] = '0' * 64 if key == 'member_id' else value[key].replace('sha256=', 'sha256=0')
                    variants.append(altered)
                altered = deepcopy(value); altered['source']['period'] = '2026-10-02'; variants.append(altered)
                altered = deepcopy(value); altered['source']['canonical_url'] += '.other'; variants.append(altered)
                for altered in variants:
                    with self.subTest(altered=altered):
                        with self.assertRaises((Conflict, ValueError, OSError, KeyError)):
                            read_member(altered, h.store, h.objects)
                progress = h.state.directory_progress(parent.discovery_id, parent.directories[0].url)
                saved = progress.to_mapping()['value']
                altered = deepcopy(saved); altered['evidence']['byte_count'] += 1
                # Select a real successful required unit; its checked receipt bytes must agree.
                h.store.replace('DirectoryProgress', __import__('hashlib').sha256(
                    canonical_json(to_mapping_value([parent.discovery_id, parent.directories[0].url]))).hexdigest(), altered, progress.version)
                with self.assertRaises((Conflict, ValueError, OSError, KeyError)):
                    read_member(value, h.store, h.objects)
            finally:
                h.close()

    def test_divergent_binding_winner_stays_unchanged(self):
        from sec_edgar_ingest.models import Binding
        from sec_edgar_ingest.state import AcquisitionState
        from support import fixture_snapshot
        from sec_edgar_ingest.workflows.provenance import transfer_binding
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {
                '2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'binding-winner')
                value = project_member(h.workset_path(parent), parent.members[0].source_id, h.store, h.objects)
                state = AcquisitionState(h.store); source = parent.members[0]
                first = fixture_snapshot(source, b'first immutable raw bytes')
                second = fixture_snapshot(source, b'second immutable raw bytes')
                for snapshot, body in ((first, b'first immutable raw bytes'), (second, b'second immutable raw bytes')):
                    h.objects.put_once(snapshot.raw_path, body); state.remember_snapshot(snapshot)
                winner = state.bind_once(Binding(value['member_id'], source.source_id, first.sha256))
                binding_key = value['member_id'] + ':' + source.source_id
                before = canonical_json(to_mapping_value(h.store.get('Binding', binding_key).to_mapping()))
                with self.assertRaises(Conflict):
                    transfer_binding(value, second, h.store, h.objects)
                self.assertEqual(state.binding(value['member_id'], source.source_id), winner)
                self.assertEqual(canonical_json(to_mapping_value(h.store.get('Binding', binding_key).to_mapping())), before)
            finally:
                h.close()

    def test_original_frozen_metadata_changes_refuse(self):
        from copy import deepcopy
        for field, changed in (('end', '2026Q3'), ('acquisition_mode', 'refresh'),
                               ('overlap_from', '2026-09-02')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
                try:
                    parent = h.run('daily', date(2026, 10, 7), 'frozen-'+field)
                    value = project_member(h.workset_path(parent), parent.members[0].source_id, h.store, h.objects)
                    row = h.state.discovery_session(parent.discovery_id)
                    original = row.to_mapping()['value']
                    altered = deepcopy(original); altered['frozen'][field] = changed
                    h.store.replace('DiscoverySession', __import__('hashlib').sha256(parent.discovery_id.encode()).hexdigest(), altered, row.version)
                    before = h.objects.read(value['parent_ref'])
                    with self.assertRaises((Conflict, ValueError)):
                        read_member(value, h.store, h.objects)
                    self.assertEqual(h.objects.read(value['parent_ref']), before)
                finally:
                    h.close()

    def test_missing_or_changed_required_ancestors_refuse(self):
        from copy import deepcopy
        for role in ('root', 'year'):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
                try:
                    parent = h.run('daily', date(2026, 10, 7), 'units-'+role)
                    value = project_member(h.workset_path(parent), parent.members[0].source_id, h.store, h.objects)
                    row = h.state.discovery_session(parent.discovery_id)
                    altered = deepcopy(row.to_mapping()['value'])
                    altered['frozen']['units'] = [u for u in altered['frozen']['units'] if u['role'] != role]
                    h.store.replace('DiscoverySession', __import__('hashlib').sha256(parent.discovery_id.encode()).hexdigest(), altered, row.version)
                    with self.assertRaises(Conflict):
                        read_member(value, h.store, h.objects)
                finally:
                    h.close()

    def test_missing_successful_receipt_and_wrong_context_refuse(self):
        from copy import deepcopy
        import hashlib
        from sec_edgar_ingest.models import parse_json
        for mutation in ('missing', 'context', 'sha', 'length'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
                try:
                    parent = h.run('daily', date(2026, 10, 7), 'receipt-'+mutation)
                    value = project_member(h.workset_path(parent), parent.members[0].source_id, h.store, h.objects)
                    unit = next(d for d in parent.directories if d.source_ids)
                    row = h.state.directory_progress(parent.discovery_id, unit.url)
                    altered = deepcopy(row.to_mapping()['value']); evidence = altered['evidence']
                    if mutation == 'missing':
                        target = h.root / 'objects' / evidence['receipt_path']
                        retained = target.read_bytes(); target.unlink()
                    elif mutation == 'context':
                        receipt = parse_json(h.objects.read(evidence['receipt_path']))
                        receipt['context']['run_id'] = 'different-origin'
                        body = canonical_json(to_mapping_value(receipt))
                        evidence['receipt_path'] += '.wrong-context'
                        h.objects.put_once(evidence['receipt_path'], body)
                        evidence['receipt_sha256'] = hashlib.sha256(body).hexdigest()
                        evidence['receipt_byte_count'] = len(body)
                    elif mutation == 'sha':
                        evidence['sha256'] = '0' * 64
                    else:
                        evidence['byte_count'] += 1
                    if mutation != 'missing':
                        key = hashlib.sha256(canonical_json(to_mapping_value([parent.discovery_id, unit.url]))).hexdigest()
                        h.store.replace('DirectoryProgress', key, altered, row.version)
                    before = h.objects.read(value['member_ref'])
                    with self.assertRaises((Conflict, ValueError, OSError)):
                        read_member(value, h.store, h.objects)
                    self.assertEqual(h.objects.read(value['member_ref']), before)
                    if mutation == 'missing':
                        target.write_bytes(retained)
                finally:
                    h.close()

    def test_parent_and_member_canonical_bytes_tampering_refuses(self):
        for name in ('parent_ref', 'member_ref'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
                try:
                    parent = h.run('daily', date(2026, 10, 7), 'bytes-'+name)
                    value = project_member(h.workset_path(parent), parent.members[0].source_id, h.store, h.objects)
                    target = h.root / 'objects' / value[name]
                    retained = target.read_bytes(); target.write_bytes(retained + b' ')
                    try:
                        with self.assertRaises((Conflict, ValueError)):
                            read_member(value, h.store, h.objects)
                    finally:
                        target.write_bytes(retained)
                    self.assertEqual(target.read_bytes(), retained)
                    self.assertEqual(read_member(value, h.store, h.objects).members, (parent.members[0],))
                finally:
                    h.close()

    def test_registry_survives_sqlite_close_reopen_and_register(self):
        from sec_edgar_ingest.storage.local import LocalStateStore
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'durable-member')
                value = project_member(h.workset_path(parent), parent.members[0].source_id, h.store, h.objects)
                original = canonical_json(to_mapping_value(h.store.get('WorkflowMember', value['member_id']).to_mapping()['value']))
                h.store.close(); h.store = LocalStateStore(h.root)
                registry = WorkflowMembers(h.store, h.objects)
                self.assertEqual(registry.all(), (value,))
                self.assertEqual(registry.register(value['parent_ref'], value['member_ref']), value)
                after = canonical_json(to_mapping_value(h.store.get('WorkflowMember', value['member_id']).to_mapping()['value']))
                self.assertEqual(after, original)
                self.assertEqual(read_member(value, h.store, h.objects).members[0], parent.members[0])
                with self.assertRaises(Conflict):
                    project_member(value['member_ref'], parent.members[0].source_id, h.store, h.objects)
            finally:
                h.close()

    def test_recovered_parent_requires_exact_ordered_authorized_units(self):
        from copy import deepcopy
        from sec_edgar_ingest.workflows.provenance import rebuild_recovered_parent
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'pure-recovery')
                session = h.state.discovery_session(parent.discovery_id).to_mapping()['value']
                progress = [{'unit': u, 'value': h.state.directory_progress(parent.discovery_id, u['url']).to_mapping()['value']}
                            for u in sorted(session['frozen']['units'], key=lambda u: (u['url'].count('/'), u['url']))]
                before = h.objects.read(h.workset_path(parent))
                self.assertEqual(rebuild_recovered_parent(session, progress, h.objects), parent)
                for captured in (progress[1:], list(reversed(progress))):
                    with self.assertRaises(Conflict):
                        rebuild_recovered_parent(session, captured, h.objects)
                altered = deepcopy(progress)
                altered[0]['value']['outcome']['outcome'] = 'discovery_failed'
                altered[0]['value']['outcome']['listing_sha256'] = None
                altered[0]['value']['outcome']['source_ids'] = []
                altered[0]['value']['outcome']['error'] = {'code': 'missing', 'message': 'failed root', 'retryable': True, 'source_id': None, 'details': {}}
                altered[0]['value']['members'] = []; altered[0]['value']['evidence'] = None
                with self.assertRaisesRegex(Conflict, 'actual successful ancestor'):
                    rebuild_recovered_parent(session, altered, h.objects)
                self.assertEqual(h.objects.read(h.workset_path(parent)), before)
            finally:
                h.close()

    def test_successful_child_must_be_advertised_by_actual_parent_listing(self):
        from copy import deepcopy
        from dataclasses import replace
        import hashlib
        from sec_edgar_ingest.models import parse_json
        from sec_edgar_ingest.worksets import make_source_workset, encode_workset
        from sec_edgar_ingest.workflows.provenance import read_parent, source_ref
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'not-advertised')
                session = h.state.discovery_session(parent.discovery_id)
                saved = session.to_mapping()['value']
                root = next(u for u in saved['frozen']['units'] if u['role'] == 'root')
                progress = h.state.directory_progress(parent.discovery_id, root['url'])
                altered = deepcopy(progress.to_mapping()['value']); evidence = altered['evidence']
                listing = parse_json(h.objects.read(evidence['body_path']))
                listing['directory']['item'] = [i for i in listing['directory']['item'] if i['name'] != '2026']
                body = canonical_json(to_mapping_value(listing)); digest = hashlib.sha256(body).hexdigest()
                evidence['body_path'] += '.unadvertised'
                h.objects.put_once(evidence['body_path'], body)
                evidence['sha256'], evidence['byte_count'] = digest, len(body)
                receipt = parse_json(h.objects.read(evidence['receipt_path']))
                receipt['body_path'] = evidence['body_path']
                receipt['receipt']['sha256'], receipt['receipt']['byte_count'] = digest, len(body)
                receipt_body = canonical_json(to_mapping_value(receipt))
                evidence['receipt_path'] += '.unadvertised'
                h.objects.put_once(evidence['receipt_path'], receipt_body)
                evidence['receipt_sha256'] = hashlib.sha256(receipt_body).hexdigest()
                evidence['receipt_byte_count'] = len(receipt_body)
                altered['outcome']['listing_sha256'] = digest
                key = hashlib.sha256(canonical_json(to_mapping_value([parent.discovery_id, root['url']]))).hexdigest()
                h.store.replace('DirectoryProgress', key, altered, progress.version)
                directories = tuple(replace(d, listing_sha256=digest) if d.url == root['url'] else d for d in parent.directories)
                counterfeit = make_source_workset(parent.context, parent.pinned_end_quarter, parent.discovery_id,
                    parent.members, directories, parent.overlap_from, acquisition_mode=parent.acquisition_mode)
                h.objects.put_once(source_ref(counterfeit), encode_workset(counterfeit))
                saved['workset_id'] = counterfeit.workset_id
                h.store.replace('DiscoverySession', hashlib.sha256(parent.discovery_id.encode()).hexdigest(), saved, session.version)
                before = h.objects.read(h.workset_path(parent))
                with self.assertRaisesRegex(Conflict, 'actual successful parent child'):
                    read_parent(source_ref(counterfeit), h.store, h.objects)
                self.assertEqual(h.objects.read(h.workset_path(parent)), before)
            finally:
                h.close()

    def test_recovery_descriptor_checks_exact_bytes_before_parent_adoption(self):
        from copy import deepcopy
        import hashlib
        from sec_edgar_ingest.workflows.provenance import RECOVERY_FORMAT, validate_parent_recovery, read_parent
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'descriptor')
                session_row = h.state.discovery_session(parent.discovery_id)
                session = session_row.to_mapping()['value']
                progress = [{'unit': u, 'value': h.state.directory_progress(parent.discovery_id, u['url']).to_mapping()['value']}
                            for u in sorted(session['frozen']['units'], key=lambda u: (u['url'].count('/'), u['url']))]
                ref = h.workset_path(parent)
                retained = {'format_version': RECOVERY_FORMAT, 'parent_ref': ref, 'parent': parent.to_mapping(),
                            'session': session, 'progress': progress}
                body = canonical_json(to_mapping_value(retained)); digest = hashlib.sha256(body).hexdigest()
                descriptor = {'ref': 'worksets/sec/workflow-parent-recovery/sha256='+digest+'/recovery.json',
                              'sha256': digest, 'bytes': len(body)}
                h.objects.put_once(descriptor['ref'], body)
                self.assertEqual(validate_parent_recovery(ref, descriptor, h.objects), {'session': session, 'progress': progress})
                absent = deepcopy(session); absent['workset_id'] = None; absent['predecessor_workset_id'] = None; absent['history'] = []
                h.store.replace('DiscoverySession', hashlib.sha256(parent.discovery_id.encode()).hexdigest(), absent, session_row.version)
                with self.assertRaises(Conflict):
                    read_parent(ref, h.store, h.objects)
                h.store.insert('WorkflowParentRecovery', parent.workset_id, descriptor)
                self.assertEqual(read_parent(ref, h.store, h.objects), parent)
                for field, changed in (('bytes', len(body)+1), ('sha256', '0'*64), ('ref', descriptor['ref']+'.other')):
                    altered = deepcopy(descriptor); altered[field] = changed
                    with self.subTest(field=field), self.assertRaises((Conflict, ValueError, OSError)):
                        validate_parent_recovery(ref, altered, h.objects)
                self.assertEqual(h.objects.read(ref), __import__('sec_edgar_ingest.worksets', fromlist=['encode_workset']).encode_workset(parent))
            finally:
                h.close()

    def test_verified_snapshot_transfer_is_idempotent(self):
        from sec_edgar_ingest.state import AcquisitionState
        from sec_edgar_ingest.workflows.provenance import transfer_binding
        from support import fixture_snapshot
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'transfer-success')
                value = project_member(h.workset_path(parent), parent.members[0].source_id, h.store, h.objects)
                body = b'accepted original bytes'; snapshot = fixture_snapshot(parent.members[0], body)
                h.objects.put_once(snapshot.raw_path, body); AcquisitionState(h.store).remember_snapshot(snapshot)
                winner = transfer_binding(value, snapshot, h.store, h.objects)
                self.assertEqual(transfer_binding(value, snapshot, h.store, h.objects), winner)
                self.assertEqual(winner.snapshot_sha256, snapshot.sha256)
                self.assertEqual(h.objects.read(snapshot.raw_path), body)
            finally:
                h.close()

    def test_support_original_rows_are_nonempty_parser_compatible(self):
        from sec_edgar_ingest.etl.parser import iter_observations
        from support import fixture_source, fixture_snapshot
        from support_workflows import idx
        for kind in ('daily', 'quarterly'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                source = fixture_source('2026-10-01', 'daily') if kind == 'daily' else fixture_source()
                filed = '20261001' if kind == 'daily' else '2026-09-30'
                fields = ('123456', 'Example', '10-K', filed, 'edgar/data/123456/0000123456-26-000001.txt')
                body = idx((fields,), kind)
                target = Path(directory) / 'original'; target.write_bytes(body)
                observations = tuple(iter_observations(target, source, fixture_snapshot(source, body),
                    parser_version='fixture-index-parser-v1', schema_version='sec-index-v1'))
                self.assertEqual(len(observations), 1)
                self.assertEqual(observations[0].original_fields, fields)
                self.assertEqual(target.read_bytes(), body)

    def test_malformed_unrelated_registry_row_does_not_block_valid_projection(self):
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'isolated-corrupt-registry')
                corrupt_id = 'f' * 64
                h.store.insert('WorkflowMember', corrupt_id, {'member_id': corrupt_id})
                corrupt_before = h.store.get('WorkflowMember', corrupt_id).to_mapping()
                value = project_member(h.workset_path(parent), parent.members[0].source_id, h.store, h.objects)
                valid, gaps = WorkflowMembers(h.store, h.objects).inventory()
                self.assertEqual(valid, (value,))
                self.assertEqual(len(gaps), 1)
                self.assertEqual(gaps[0].code, 'legacy_member_unresolved')
                self.assertEqual(gaps[0].details['member_id'], corrupt_id)
                self.assertEqual(h.store.get('WorkflowMember', corrupt_id).to_mapping(), corrupt_before)
                with self.assertRaisesRegex(Conflict, 'registered projection'):
                    project_member(value['member_ref'], parent.members[0].source_id, h.store, h.objects)
            finally:
                h.close()

    def test_refused_wrong_context_registration_changes_no_registry_or_objects(self):
        from dataclasses import replace
        from sec_edgar_ingest.workflows.members import WorkflowMembers
        from sec_edgar_ingest.workflows.provenance import projection, source_ref
        from sec_edgar_ingest.worksets import make_source_workset, encode_workset
        with tempfile.TemporaryDirectory() as directory:
            h = discovery_harness(Path(directory), {'2026Q4': [listing_response('2026Q4', ['master.20261001.idx'])]})
            try:
                parent = h.run('daily', date(2026, 10, 7), 'refusal-before-admission')
                expected = projection(parent, parent.members[0].source_id)
                wrong_context = replace(expected.context, attempt_id='other-origin')
                supplied = make_source_workset(wrong_context, expected.pinned_end_quarter,
                    expected.discovery_id, expected.members, expected.directories, expected.overlap_from,
                    acquisition_mode=expected.acquisition_mode)
                supplied_ref = source_ref(supplied)
                h.objects.put_once(supplied_ref, encode_workset(supplied))
                registry_before = tuple(row.to_mapping() for row in h.store.scan('WorkflowMember', {}))
                object_root = h.root / 'objects'
                objects_before = {str(path.relative_to(object_root)): path.read_bytes()
                                  for path in object_root.rglob('*') if path.is_file()}
                with self.assertRaisesRegex(Conflict, 'exact projection'):
                    WorkflowMembers(h.store, h.objects).register(h.workset_path(parent), supplied_ref)
                self.assertEqual(tuple(row.to_mapping() for row in h.store.scan('WorkflowMember', {})), registry_before)
                self.assertEqual({str(path.relative_to(object_root)): path.read_bytes()
                                  for path in object_root.rglob('*') if path.is_file()}, objects_before)
            finally:
                h.close()
