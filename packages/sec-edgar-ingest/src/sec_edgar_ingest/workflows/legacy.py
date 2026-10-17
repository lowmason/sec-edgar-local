from ..models import to_mapping_value
import hashlib
from collections.abc import Mapping
from ..models import Error, RunContext, Source, canonical_json, error_text, parse_json, require_text
from ..state import AcquisitionState, attempt_key
from ..storage.contracts import Conflict
from ..worksets import encode_workset, decode_snapshot_workset
from ..results import read_result, result_path
from ..etl.commands import read_etl_result
from .provenance import (RECOVERY_FORMAT, immutable, source_ref, read_parent, read_member,
                        project_member, transfer_binding, rebuild_recovered_parent,
                        validate_parent_recovery)

LEGACY_ERRORS = (ValueError, OSError, Conflict, KeyError, TypeError)


def _validated_frozen_units(session):
    frozen = session['frozen']
    if not isinstance(frozen, Mapping):
        raise ValueError('legacy frozen discovery must be a mapping')
    units = frozen['units']
    if not isinstance(units, (list, tuple)) or not units:
        raise ValueError('legacy frozen units must be a nonempty array')
    for unit in units:
        if not isinstance(unit, Mapping) or set(unit) not in (
                {'url', 'period', 'role'}, {'url', 'period', 'role', 'bridge_period'}):
            raise ValueError('legacy frozen unit fields differ')
        for field in ('url', 'period', 'role'):
            require_text(unit[field], 'legacy frozen unit ' + field)
        if unit['role'] not in ('root', 'year', 'quarter'):
            raise ValueError('legacy frozen unit role differs')
        if 'bridge_period' in unit:
            require_text(unit['bridge_period'], 'legacy frozen unit bridge_period')
    return units


def reconstruct_parent(session, store, objects):
    acquisition = AcquisitionState(store)
    progress = []
    for unit in sorted(_validated_frozen_units(session), key=lambda u: (u['url'].count('/'), u['url'])):
        row = acquisition.directory_progress(session['discovery_id'], unit['url'])
        progress.append({'unit': unit, 'value': None if row is None else row.to_mapping()['value']})
    parent = rebuild_recovered_parent(session, progress, objects)
    recovery = {'format_version': RECOVERY_FORMAT, 'parent_ref': source_ref(parent),
                'parent': parent.to_mapping(), 'session': session, 'progress': progress}
    body = canonical_json(to_mapping_value(recovery))
    digest = hashlib.sha256(body).hexdigest()
    path = 'worksets/sec/workflow-parent-recovery/sha256=' + digest + '/recovery.json'
    objects.put_once(source_ref(parent), encode_workset(parent))
    retained = store.get('WorkflowParentRecovery', parent.workset_id)
    if retained is not None:
        captured = validate_parent_recovery(source_ref(parent), retained.to_mapping()['value'], objects)
        if canonical_json(to_mapping_value(captured['session']['frozen'])) != canonical_json(to_mapping_value(session['frozen'])):
            raise Conflict('retained recovery changes frozen original session')
        read_parent(source_ref(parent), store, objects)
        return source_ref(parent)
    objects.put_once(path, body)
    objects.verify(path, digest, len(body))
    descriptor = {'ref': path, 'sha256': digest, 'bytes': len(body)}
    validate_parent_recovery(source_ref(parent), descriptor, objects)
    immutable(store, 'WorkflowParentRecovery', parent.workset_id, descriptor)
    read_parent(source_ref(parent), store, objects)
    return source_ref(parent)


def bootstrap_legacy(store, objects):
    gaps, parents, covered = [], {}, set()
    acquisition = AcquisitionState(store)
    registered, projection_refs = {}, set()

    def unresolved(kind, value, error, source_id=None, **details):
        digest = hashlib.sha256(canonical_json(to_mapping_value(value))).hexdigest()
        message = error if isinstance(error, str) else error_text(error)
        gaps.append(Error('legacy_member_unresolved', message, False, source_id,
                          {'record_kind': kind, 'record_sha256': digest, **details}))

    for row in store.scan('WorkflowMember', {}):
        value = row.to_mapping()['value']
        if isinstance(value.get('member_ref'), str):
            projection_refs.add(value['member_ref'])
        try:
            read_member(value, store, objects)
            registered[value['member_ref']] = value
            covered.add(value['source']['source_id'])
        except LEGACY_ERRORS as error:
            unresolved('WorkflowMember', value, error)

    def retain(ref):
        if ref in projection_refs:
            if ref not in registered:
                raise Conflict('corrupt registered projection cannot supply original provenance')
            ref = registered[ref]['parent_ref']
        parent = read_parent(ref, store, objects)
        parents[parent.workset_id] = (ref, parent)

    for row in store.scan('DiscoverySession', {}):
        session = row.to_mapping()['value']
        try:
            _validated_frozen_units(session)
            revisions = [session.get('workset_id'), session.get('predecessor_workset_id')]
            for historical in session.get('history', ()):
                try:
                    revisions.append(historical['workset_id'])
                except LEGACY_ERRORS as error:
                    unresolved('DiscoverySession', session, error, history_entry=historical)
        except LEGACY_ERRORS as error:
            unresolved('DiscoverySession', session, error)
            continue
        recovered, retained_ids = False, set()
        identities = [identity for identity in revisions if identity is not None]
        for identity in identities:
            ref = None
            try:
                from ..models import require_hash
                require_hash(identity, 'legacy original workset')
                if identity in retained_ids:
                    continue
                retained_ids.add(identity)
                ref = 'worksets/sec/source/sha256=' + identity + '/workset.json'
                retain(ref)
            except FileNotFoundError:
                if not recovered:
                    try:
                        retain(reconstruct_parent(session, store, objects))
                        recovered = True
                    except LEGACY_ERRORS as error:
                        unresolved('DiscoverySession', session, error, ref=ref)
            except LEGACY_ERRORS as error:
                unresolved('DiscoverySession', session, error, ref=ref)
        if not identities:
            try:
                retain(reconstruct_parent(session, store, objects))
            except LEGACY_ERRORS as error:
                unresolved('DiscoverySession', session, error)

    from .checked import _authority, _transformed_input
    from .completion import _call_context, _legacy_publish_call
    for row in store.scan('WorkflowChildCall', {}):
        value = row.to_mapping()['value']
        try:
            call, template = _authority(value, None, objects)
            if template.command == 'publish':
                _transformed_input(call['input_ref'], None, objects)
                try:
                    _call_context(call, store, objects)
                except FileNotFoundError:
                    continue  # Immutable command was not committed; CAS was unreachable.
        except LEGACY_ERRORS as error:
            unresolved('WorkflowChildCall', value, error)

    for row in store.scan('Attempt', {}):
        value = row.to_mapping()['value']
        try:
            context = RunContext.from_mapping(value['context'])
            if value.get('result') is None:
                if context.command == 'publish':
                    try:
                        _legacy_publish_call(context, objects)
                    except FileNotFoundError:
                        pass  # No command commit means no publication CAS.
                continue
            if context.command not in ('discover', 'collect', 'transform', 'publish'):
                raise Conflict('legacy acquisition Attempt command differs')
            child = (read_etl_result if context.command in ('transform', 'publish') else read_result)(
                result_path(context), objects)
            if child.context != context or child.to_mapping() != value['result']:
                raise Conflict('legacy Attempt result differs from immutable command object')
            refs = []
            source_set = getattr(child, 'source_workset_ref', None)
            if source_set is not None:
                refs.append(source_set)
            snapshot_ref = getattr(child, 'snapshot_workset_ref', None)
            if context.command == 'transform':
                snapshot_ref = child.input_ref
            if snapshot_ref is not None:
                snapshots = decode_snapshot_workset(objects.read(snapshot_ref))
                refs.append('worksets/sec/source/sha256=' + snapshots.source_workset_id + '/workset.json')
        except LEGACY_ERRORS as error:
            unresolved('Attempt', value, error)
            continue
        for ref in refs:
            try:
                retain(ref)
            except LEGACY_ERRORS as error:
                unresolved('Attempt', value, error, ref=ref, attempt_key=attempt_key(context))

    for ref, parent in sorted(parents.values(), key=lambda item: item[0]):
        for source in parent.members:
            try:
                value = project_member(ref, source.source_id, store, objects)
                pin = acquisition.binding(parent.workset_id, source.source_id)
                if pin is not None:
                    transfer_binding(value, acquisition.snapshot(source.source_id, pin.snapshot_sha256), store, objects)
                covered.add(source.source_id)
            except LEGACY_ERRORS as error:
                unresolved('SourceWorkset', parent.to_mapping(), error, source.source_id, parent_ref=ref)

    for kind in ('Source', 'Processing'):
        for row in store.scan(kind, {}):
            value = row.to_mapping()['value']
            try:
                source = Source.from_mapping(value['source'] if kind == 'Source' else value['observation']['source'])
                if source.source_id not in covered:
                    unresolved(kind, value, 'source has no verified original parent', source.source_id)
            except LEGACY_ERRORS as error:
                unresolved(kind, value, error)
    return tuple(gaps)
