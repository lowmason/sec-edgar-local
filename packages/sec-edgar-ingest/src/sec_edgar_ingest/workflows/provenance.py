from ..models import to_mapping_value
import hashlib
from dataclasses import replace
from ..models import Binding, RunContext, canonical_json
from ..state import AcquisitionState
from ..storage.contracts import AlreadyExists, Conflict
from ..worksets import decode_source_workset, encode_workset, make_source_workset
from ..discovery import reopen_listing
from ..urls import child_url

def immutable(store, kind, key, value):
    try:
        store.insert(kind, key, value)
    except AlreadyExists:
        row = store.get(kind, key)
        if row is None or canonical_json(to_mapping_value(row.to_mapping()['value'])) != canonical_json(to_mapping_value(value)):
            raise Conflict(kind + ' immutable identity differs')

def source_ref(workset):
    return f'worksets/sec/source/sha256={workset.workset_id}/workset.json'

def read_source(ref, objects):
    body = objects.read(ref)
    workset = decode_source_workset(body)
    if source_ref(workset) != ref or encode_workset(workset) != body:
        raise Conflict('source reference or canonical bytes differ')
    return workset

RECOVERY_FORMAT = 'sec-workflow-parent-recovery-v1'

def rebuild_recovered_parent(session, progress, objects):
    from datetime import date
    from ..models import DirectoryOutcome, Error
    frozen = session['frozen']
    if session['discovery_id'] == '' or set(frozen) != {
            'context', 'today', 'end', 'mode', 'acquisition_mode', 'units', 'overlap_from'}:
        raise Conflict('recovery frozen discovery fields differ')
    origin = RunContext.from_mapping(frozen['context'])
    if origin.command != 'discover' or frozen['mode'] not in ('daily', 'quarterly'):
        raise Conflict('recovery is not original discovery provenance')
    if origin.pinned_on is None or origin.pinned_on.isoformat() != frozen['today']:
        raise Conflict('recovery changes original discovery date')
    units = frozen['units']
    if not units or len({unit['url'] for unit in units}) != len(units):
        raise Conflict('recovery requires unique frozen required units')
    expected = sorted(units, key=lambda unit: (unit['url'].count('/'), unit['url']))
    if len(progress) != len(expected) or [p['unit'] for p in progress] != expected:
        raise Conflict('recovery omits or reorders required units')
    entries, members, outcomes = {}, {}, []
    for captured in progress:
        if set(captured) != {'unit', 'value'}:
            raise Conflict('recovery progress fields differ')
        unit, value = captured['unit'], captured['value']
        if set(unit) not in ({'url', 'period', 'role'}, {'url', 'period', 'role', 'bridge_period'}):
            raise Conflict('recovery unit fields differ')
        if unit['role'] not in ('root', 'year', 'quarter'):
            raise Conflict('recovery unit role differs')
        if value is None:
            outcome = DirectoryOutcome(unit['url'], unit['period'], 'discovery_failed', None, (),
                Error('discovery_pending', 'original required unit has no retained completion', True, None, {}))
            outcomes.append(outcome)
            continue
        if set(value) != {'discovery_id', 'outcome', 'members', 'evidence', 'selection', 'observed_gap_token'}:
            raise Conflict('recovery directory progress fields differ')
        if value['discovery_id'] != session['discovery_id']:
            raise Conflict('recovery directory belongs to another original session')
        outcome = DirectoryOutcome.from_mapping(value['outcome'])
        if (outcome.url, outcome.period) != (unit['url'], unit['period']):
            raise Conflict('recovery directory metadata differs from frozen unit')
        if outcome.outcome == 'discovery_failed':
            if value['members'] or value['evidence'] is not None:
                raise Conflict('failed discovery progress introduces accepted evidence')
            outcomes.append(outcome)
            continue
        if unit['role'] != 'root':
            ancestor = unit['url'].rsplit('/', 2)[0] + '/index.json'
            name = unit['url'].rsplit('/', 2)[1]
            authorized = next((entry for entry in entries.get(ancestor, ())
                               if entry.name == name and entry.kind == 'dir'), None)
            if authorized is None or child_url(ancestor, authorized.href, authorized.name, True) + 'index.json' != unit['url']:
                raise Conflict('recovered successful child lacks actual successful ancestor')
        outcome, selected, children, received = reopen_listing(objects, value, unit, origin)
        entries[unit['url']] = children
        for source in selected:
            if source.source_id in members:
                raise Conflict('recovery duplicates source across required units')
            members[source.source_id] = source
        outcomes.append(outcome)
    return make_source_workset(origin, frozen['end'], session['discovery_id'],
        tuple(members.values()), tuple(outcomes), date.fromisoformat(frozen['overlap_from']),
        acquisition_mode=frozen['acquisition_mode'])


def validate_parent_recovery(parent_ref, descriptor, objects):
    from ..models import parse_json, require_hash
    if set(descriptor) != {'ref', 'sha256', 'bytes'}:
        raise Conflict('recovery descriptor fields differ')
    require_hash(descriptor['sha256'], 'recovery digest')
    expected_path = 'worksets/sec/workflow-parent-recovery/sha256=' + descriptor['sha256'] + '/recovery.json'
    if descriptor['ref'] != expected_path:
        raise Conflict('recovery descriptor address differs')
    objects.verify(descriptor['ref'], descriptor['sha256'], descriptor['bytes'])
    body = objects.read(descriptor['ref'])
    saved = parse_json(body)
    if canonical_json(to_mapping_value(saved)) != body or set(saved) != {'format_version', 'parent_ref', 'parent', 'session', 'progress'}:
        raise Conflict('recovery bytes/schema differ')
    if saved['format_version'] != RECOVERY_FORMAT or saved['parent_ref'] != parent_ref:
        raise Conflict('recovery version/original parent differs')
    parent = read_source(parent_ref, objects)
    rebuilt = rebuild_recovered_parent(saved['session'], saved['progress'], objects)
    if rebuilt != parent or saved['parent'] != parent.to_mapping():
        raise Conflict('recovery changes exact reconstructed original parent')
    return {'session': saved['session'], 'progress': saved['progress']}


def read_parent(ref, store, objects):
    parent = read_source(ref, objects)
    acquisition = AcquisitionState(store)
    row = acquisition.discovery_session(parent.discovery_id)
    if row is None:
        raise Conflict('original discovery session absent')
    saved = row.to_mapping()['value']
    frozen = saved['frozen']
    origin = RunContext.from_mapping(frozen['context'])
    identities = {saved.get('workset_id'), saved.get('predecessor_workset_id')}
    identities.update(item['workset_id'] for item in saved.get('history', ()))
    if parent.workset_id not in identities:
        recovery = store.get('WorkflowParentRecovery', parent.workset_id)
        if recovery is None:
            raise Conflict('parent is neither retained discovery revision nor validated recovery')
        snapshot = validate_parent_recovery(ref, recovery.to_mapping()['value'], objects)
        if (snapshot['session']['discovery_id'] != parent.discovery_id or
                canonical_json(to_mapping_value(snapshot['session']['frozen'])) != canonical_json(to_mapping_value(frozen))):
            raise Conflict('recovery changes original frozen discovery session')
        return parent
    if (origin != parent.context or frozen['end'] != parent.pinned_end_quarter or
            frozen['overlap_from'] != parent.overlap_from.isoformat() or
            frozen['acquisition_mode'] != parent.acquisition_mode):
        raise Conflict('parent changes frozen origin')
    units = {unit['url']: unit for unit in frozen['units']}
    if len(units) != len(frozen['units']) or set(units) != {d.url for d in parent.directories}:
        raise Conflict('parent omits or changes required discovery units')
    entries, reopened = {}, {}
    for unit in sorted(units.values(), key=lambda u: (u['url'].count('/'), u['url'])):
        directory = next(d for d in parent.directories if d.url == unit['url'])
        if directory.outcome == 'discovery_failed':
            if directory.error is None:
                raise Conflict('failed required unit lacks retained error')
            continue
        if unit['role'] != 'root':
            ancestor = unit['url'].rsplit('/', 2)[0] + '/index.json'
            name = unit['url'].rsplit('/', 2)[1]
            entry = next((e for e in entries.get(ancestor, ()) if e.name == name and e.kind == 'dir'), None)
            if entry is None or child_url(ancestor, entry.href, entry.name, True) + 'index.json' != unit['url']:
                raise Conflict('successful unit lacks actual successful parent child')
        progress = acquisition.directory_progress(parent.discovery_id, unit['url'])
        if progress is None:
            raise Conflict('successful listing progress absent')
        outcome, sources, children, received = reopen_listing(objects, progress.to_mapping()['value'], unit, origin)
        if outcome != directory:
            raise Conflict('parent outcome differs from original listing receipt')
        entries[unit['url']] = children
        reopened.update((source.source_id, source) for source in sources)
    if tuple(sorted(reopened)) != tuple(source.source_id for source in parent.members):
        raise Conflict('parent source set differs from successful listings')
    if any(reopened[source.source_id] != source for source in parent.members):
        raise Conflict('parent relabels original source')
    return parent

def projection(parent, source_id):
    selected = tuple(source for source in parent.members if source.source_id == source_id)
    directories = tuple(d for d in parent.directories if source_id in d.source_ids)
    if len(selected) != 1 or len(directories) != 1 or directories[0].outcome == 'discovery_failed':
        raise Conflict('projection needs exact successful immediate member')
    directory = replace(directories[0], source_ids=(source_id,))
    unit = hashlib.sha256(canonical_json(to_mapping_value([parent.workset_id, source_id]))).hexdigest()
    return make_source_workset(parent.context, parent.pinned_end_quarter, 'member-' + unit,
                               selected, (directory,), parent.overlap_from,
                               acquisition_mode=parent.acquisition_mode)

def project_member(parent_ref, source_id, store, objects):
    if any(row.value.get('member_ref') == parent_ref for row in store.scan('WorkflowMember', {})):
        raise Conflict('a registered projection cannot become an original parent')
    parent = read_parent(parent_ref, store, objects)
    member = projection(parent, source_id)
    body = encode_workset(member)
    ref = source_ref(member)
    objects.put_once(ref, body)
    objects.verify(ref, hashlib.sha256(body).hexdigest(), len(body))
    value = {'member_id': member.workset_id, 'source': member.members[0].to_mapping(),
             'parent_ref': parent_ref, 'member_ref': ref}
    immutable(store, 'WorkflowMember', member.workset_id, value)
    return value

def read_member(value, store, objects):
    if set(value) != {'member_id', 'source', 'parent_ref', 'member_ref'}:
        raise Conflict('member record fields differ')
    row = store.get('WorkflowMember', value['member_id'])
    if row is None or canonical_json(to_mapping_value(row.to_mapping()['value'])) != canonical_json(to_mapping_value(dict(value))):
        raise Conflict('member record lacks exact registry binding')
    parent = read_parent(value['parent_ref'], store, objects)
    expected = projection(parent, value['source']['source_id'])
    actual = read_source(value['member_ref'], objects)
    if (actual != expected or actual.workset_id != value['member_id'] or
            actual.members[0].to_mapping() != value['source']):
        raise Conflict('member changes exact original projection')
    return actual

def transfer_binding(value, snapshot, store, objects):
    member = read_member(value, store, objects)
    acquisition = AcquisitionState(store)
    remembered = acquisition.snapshot(snapshot.source_id, snapshot.sha256)
    if remembered != snapshot or snapshot.source_id != member.members[0].source_id:
        raise Conflict('binding snapshot metadata differs')
    objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
    requested = Binding(member.workset_id, snapshot.source_id, snapshot.sha256)
    winner = acquisition.bind_once(requested)
    if winner != requested:
        raise Conflict('existing binding winner differs; immutable pin preserved')
    return winner
