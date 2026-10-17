"""Validate current completion and retain immutable publication repair evidence."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import date

from ..config import Settings, pin_context
from ..discovery import reopen_listing
from ..etl.commands import _affected_quarters, read_etl_result
from ..etl.contracts import (
    GenerationCapture, ObservationRef, decode_transformed, processing_key, transformed_ref,
)
from ..etl.reader import capture_quarter, validated_manifest
from ..etl.state import EtlState
from ..etl.transform import _read_manifest
from ..models import (
    Binding, DirectoryOutcome, Error, RunContext, Snapshot, Source, SourceWorkset,
    canonical_json, error_text, parse_json, quarter_for, quarter_value, require_hash,
    require_number, safe_relative_path, to_mapping_value,
)
from ..results import result_path
from ..state import AcquisitionState, attempt_key
from ..storage.contracts import AlreadyExists, Conflict
from ..urls import canonical_listing_url, child_url
from ..worksets import decode_source_workset, encode_workset, make_source_workset
from .checked import (
    _authority, _context_matches, _transformed_input, _validate_input_output,
    read_child, read_child_capture,
)
from .contracts import CompletionEvaluation
from .provenance import (
    projection as expected_projection, read_member, read_parent, validate_parent_recovery,
)

PARENT_PROVENANCE_FORMAT = 'sec-workflow-parent-provenance-v1'


def validate_discovery_session(session) -> RunContext:
    session = parse_json(canonical_json(to_mapping_value(session)))
    if not isinstance(session, dict) or set(session) != {
            'discovery_id', 'frozen', 'workset_id', 'predecessor_workset_id', 'history', 'registered'}:
        raise Conflict('captured discovery session fields differ')
    if not isinstance(session['discovery_id'], str) or not session['discovery_id'] or type(session['registered']) is not bool:
        raise Conflict('captured discovery session identity or registration differs')
    for identity in (session['workset_id'], session['predecessor_workset_id']):
        if identity is not None:
            require_hash(identity, 'captured discovery workset identity')
    if not isinstance(session['history'], list):
        raise Conflict('captured discovery history must be an array')
    for revision in session['history']:
        if set(revision) != {'workset_id', 'predecessor_workset_id', 'resumed_by'}:
            raise Conflict('captured discovery revision fields differ')
        require_hash(revision['workset_id'], 'captured discovery revision')
        if revision['predecessor_workset_id'] is not None:
            require_hash(revision['predecessor_workset_id'], 'captured discovery predecessor')
        RunContext.from_mapping(revision['resumed_by'])
    frozen = session['frozen']
    if not isinstance(frozen, dict) or set(frozen) != {
            'context', 'today', 'end', 'mode', 'acquisition_mode', 'units', 'overlap_from'}:
        raise Conflict('captured discovery frozen fields differ')
    origin = RunContext.from_mapping(frozen['context'])
    settings = Settings.from_mapping(origin.to_mapping()['effective_config'])
    if origin.command != 'discover' or origin.pinned_on is None:
        raise Conflict('captured discovery requires its original pinned command')
    pinned, end = pin_context(settings, origin, origin.pinned_on)
    if pinned != origin or frozen['today'] != origin.pinned_on.isoformat() or frozen['end'] != end:
        raise Conflict('captured discovery original date/settings/endpoint differ')
    if frozen['mode'] not in ('daily', 'quarterly') or frozen['acquisition_mode'] not in ('refresh', 'reuse_accepted'):
        raise Conflict('captured discovery mode differs')
    overlap = date.fromisoformat(frozen['overlap_from'])
    if overlap.isoformat() != frozen['overlap_from'] or overlap > origin.pinned_on:
        raise Conflict('captured discovery overlap date differs')
    units = frozen['units']
    if not isinstance(units, list) or not units or [unit['url'] for unit in units] != sorted({unit['url'] for unit in units}):
        raise Conflict('captured discovery units must be exact ordered unique addresses')
    pattern = re.compile(r'https://www\.sec\.gov/Archives/edgar/(full-index|daily-index)/(?:([1-9][0-9]{3})/(?:QTR([1-4])/)?)?index\.json\Z')
    for unit in units:
        if not isinstance(unit, dict) or set(unit) not in ({'url', 'period', 'role'}, {'url', 'period', 'role', 'bridge_period'}):
            raise Conflict('captured discovery unit fields differ')
        if canonical_listing_url(unit['url']) != unit['url']:
            raise Conflict('captured discovery unit URL is not canonical')
        match = pattern.fullmatch(unit['url'])
        if match is None:
            raise Conflict('captured discovery unit lacks an accepted family/period address')
        family, year, ordinal = match.groups()
        expected_role = 'quarter' if ordinal is not None else 'year' if year is not None else 'root'
        expected_period = f'{year}Q{ordinal}' if ordinal is not None else year if year is not None else family
        if (unit['role'], unit['period']) != (expected_role, expected_period):
            raise Conflict('captured discovery unit role/period differs from address')
        if 'bridge_period' in unit:
            quarter_value(unit['bridge_period'])
            if expected_role != 'root' or family != 'full-index' or unit['bridge_period'] != quarter_for(origin.pinned_on):
                raise Conflict('captured root bridge period differs from original open quarter')
    return origin


def capture_parent_provenance(parent_ref, store, objects) -> Mapping:
    parent = read_parent(parent_ref, store, objects)
    evidence = {'format_version': PARENT_PROVENANCE_FORMAT, 'parent_ref': parent_ref,
                'parent': parent.to_mapping(),
                'discovery': _discovery_snapshot(parent, store, objects)}
    validate_parent_provenance(evidence, objects)
    return _plain(evidence)


def validate_parent_provenance(evidence, objects) -> SourceWorkset:
    evidence = parse_json(canonical_json(to_mapping_value(evidence)))
    if not isinstance(evidence, dict) or set(evidence) != {'format_version', 'parent_ref', 'parent', 'discovery'} or evidence['format_version'] != PARENT_PROVENANCE_FORMAT:
        raise Conflict('captured parent provenance schema differs')
    parent = _read_set(evidence['parent_ref'], objects)
    if parent.to_mapping() != evidence['parent']:
        raise Conflict('captured parent differs from exact immutable source workset')
    validate_discovery_session(evidence['discovery']['session'])
    _validate_discovery(parent, evidence['discovery'], objects)
    return parent

CAPTURE_FORMAT = 'sec-workflow-completion-v1'
OBLIGATION_FORMAT = 'sec-workflow-repair-obligation-v1'
RESOLUTION_FORMAT = 'sec-workflow-repair-resolution-v1'
PROVENANCE_FORMAT = 'sec-workflow-member-provenance-v1'


def _plain(value):
    return parse_json(canonical_json(to_mapping_value(value)))


def _immutable(kind, key, value, store):
    try:
        store.insert(kind, key, _plain(value))
    except AlreadyExists:
        row = store.get(kind, key)
        if row is None or canonical_json(to_mapping_value(row.to_mapping()['value'])) != canonical_json(to_mapping_value(value)):
            raise Conflict(f'{kind} immutable evidence differs')


def _document(value, format_version, namespace, objects):
    value = _plain(value)
    body = canonical_json(to_mapping_value(value))
    identity = hashlib.sha256(body).hexdigest()
    path = f'worksets/sec/{namespace}/sha256={identity}/evidence.json'
    objects.put_once(path, body)
    return {'ref': path, 'sha256': identity, 'bytes': len(body), 'format_version': format_version}



REPAIR_AUTHORITY_FORMAT = 'sec-workflow-repair-authority-v1'


def _repair_authority_ref(call_sha256):
    require_hash(call_sha256, 'original repair call digest')
    return f'worksets/sec/workflow-repair-authority/call-sha256={call_sha256}/obligation.json'


def _read_repair_authority(call_sha256, objects):
    try:
        body = objects.read(_repair_authority_ref(call_sha256))
    except FileNotFoundError:
        return None
    value = parse_json(body)
    if (not isinstance(value, dict)
            or set(value) != {'format_version', 'call_sha256', 'descriptor'}
            or value['format_version'] != REPAIR_AUTHORITY_FORMAT
            or value['call_sha256'] != call_sha256
            or canonical_json(to_mapping_value(value)) != body):
        raise Conflict('original repair obligation authority bytes or identity differ')
    if not isinstance(value['descriptor'], dict):
        raise Conflict('original repair obligation authority descriptor differs')
    return value['descriptor']


def _write_repair_authority(call_sha256, descriptor, objects):
    value = {'format_version': REPAIR_AUTHORITY_FORMAT,
             'call_sha256': call_sha256, 'descriptor': _plain(descriptor)}
    body = canonical_json(to_mapping_value(value))
    path = _repair_authority_ref(call_sha256)
    objects.put_once(path, body)
    if objects.read(path) != body:
        raise Conflict('original repair obligation authority differs')


def _read_document(descriptor, format_version, objects):
    if format_version not in (OBLIGATION_FORMAT, RESOLUTION_FORMAT):
        raise Conflict('unsupported repair document format')
    if not isinstance(descriptor, Mapping) or set(descriptor) != {'ref', 'sha256', 'bytes', 'format_version'}:
        raise Conflict('repair document descriptor fields differ')
    require_hash(descriptor['sha256'], 'repair document digest')
    require_number(descriptor['bytes'], 'repair document bytes', integer=True)
    safe_relative_path(descriptor['ref'], 'repair document ref')
    namespace = ('workflow-repairs' if format_version == OBLIGATION_FORMAT
                 else 'workflow-repair-resolutions')
    expected_path = f"worksets/sec/{namespace}/sha256={descriptor['sha256']}/evidence.json"
    if descriptor['ref'] != expected_path or descriptor['format_version'] != format_version:
        raise Conflict('repair document address or version differs')
    objects.verify(descriptor['ref'], descriptor['sha256'], descriptor['bytes'])
    body = objects.read(descriptor['ref'])
    value = parse_json(body)
    if not isinstance(value, dict) or canonical_json(to_mapping_value(value)) != body or value.get('format_version') != format_version:
        raise Conflict('repair document canonical payload differs')
    if format_version == RESOLUTION_FORMAT:
        if set(value) != {'format_version', 'obligation', 'call', 'result', 'quarters', 'repair_artifacts'}:
            raise Conflict('repair resolution payload fields differ')
        _read_document(value['obligation'], OBLIGATION_FORMAT, objects)
        return value
    if set(value) != {'format_version', 'call', 'context', 'transformed_ref', 'sources', 'affected_quarters'}:
        raise Conflict('repair obligation payload fields differ')
    original_call = value['call']
    actual = RunContext.from_mapping(value['context'])
    if actual.command != 'publish' or not isinstance(original_call, dict):
        raise Conflict('repair obligation must describe original publication authority')
    if original_call.get('format_version') == LEGACY_PUBLISH_FORMAT:
        if _legacy_publish_call(actual, objects) != original_call:
            raise Conflict('repair obligation differs from original legacy command')
    elif original_call.get('format_version') == 'sec-workflow-child-call-v1':
        call, template = _authority(original_call, None, objects)
        _context_matches(template, actual)
        command_path = call['result_ref'].rsplit('/', 1)[0] + '/command.json'
        frozen = {'context': actual.to_mapping(), 'intent': call['intent']}
        if objects.read(command_path) != canonical_json(to_mapping_value(frozen)):
            raise Conflict('repair obligation differs from original checked command')
    else:
        raise Conflict('repair obligation uses an unknown original call authority')
    if original_call['input_ref'] != value['transformed_ref']:
        raise Conflict('repair obligation changes original publication input')
    transformed = _transformed_input(value['transformed_ref'], None, objects)
    if (transformed.context.parser_version, transformed.context.schema_version) != (
            actual.parser_version, actual.schema_version):
        raise Conflict('repair obligation original command/input versions differ')
    if value['sources'] != [ref.to_mapping() for ref in transformed.observations]:
        raise Conflict('repair obligation sources differ from exact decoded input')
    affected = value['affected_quarters']
    if not isinstance(affected, list) or affected != sorted(set(affected)):
        raise Conflict('repair obligation affected quarters duplicate or reorder units')
    for quarter in affected:
        quarter_value(quarter)
    observed = {quarter for ref in transformed.observations for quarter in ref.quarter_counts}
    if not observed <= set(affected):
        raise Conflict('repair obligation omits an observation output quarter')
    call_sha256 = hashlib.sha256(canonical_json(to_mapping_value(original_call))).hexdigest()
    anchored = _read_repair_authority(call_sha256, objects)
    if anchored is None or anchored != _plain(descriptor):
        raise Conflict('repair obligation differs from original immutable call authority')
    return value

def _read_set(path, objects):
    body = objects.read(path)
    result = decode_source_workset(body)
    if path != f'worksets/sec/source/sha256={result.workset_id}/workset.json' or encode_workset(result) != body:
        raise Conflict('source workset path or canonical bytes differ')
    return result


def _discovery_snapshot(parent, store, objects):
    state = AcquisitionState(store)
    row = state.discovery_session(parent.discovery_id)
    session = None if row is None else row.to_mapping()['value']
    identities = set() if session is None else ({session.get('workset_id'), session.get('predecessor_workset_id')} | {item['workset_id'] for item in session.get('history', ())})
    identities.discard(None)
    if session is None or parent.workset_id not in identities:
        recovered = store.get('WorkflowParentRecovery', parent.workset_id)
        if recovered is None:
            raise Conflict('parent absent from original session and immutable recovery evidence')
        descriptor = recovered.to_mapping()['value']
        ref = f'worksets/sec/source/sha256={parent.workset_id}/workset.json'
        snapshot = validate_parent_recovery(ref, descriptor, objects)
        return {**_plain(snapshot), 'recovery': descriptor}
    progress = []
    for unit in session['frozen']['units']:
        original = next(d for d in parent.directories if d.url == unit['url'])
        if original.outcome == 'discovery_failed':
            value = {'discovery_id': parent.discovery_id, 'outcome': original.to_mapping(),
                     'members': [], 'evidence': None, 'selection': {'ignored': []},
                     'observed_gap_token': None}
        else:
            row = state.directory_progress(parent.discovery_id, unit['url'])
            if row is None:
                raise Conflict('parent has missing successful directory progress')
            value = row.to_mapping()['value']
        progress.append({'unit': unit, 'value': value})
    return {'session': session, 'progress': progress, 'recovery': None}


def _validate_discovery(parent, evidence, objects):
    if set(evidence) != {'session', 'progress', 'recovery'}:
        raise Conflict('captured discovery evidence schema differs')
    validate_discovery_session(evidence['session'])
    if evidence['recovery'] is not None:
        ref = f'worksets/sec/source/sha256={parent.workset_id}/workset.json'
        validated = validate_parent_recovery(ref, evidence['recovery'], objects)
        if _plain(validated) != {'session': evidence['session'], 'progress': evidence['progress']}:
            raise Conflict('captured recovered-parent provenance differs')
        return
    session = evidence['session']
    frozen = session['frozen']
    context = RunContext.from_mapping(frozen['context'])
    if context != parent.context or session['discovery_id'] != parent.discovery_id:
        raise Conflict('captured parent discovery provenance differs')
    allowed = {session.get('workset_id'), session.get('predecessor_workset_id')} | {item['workset_id'] for item in session.get('history', ())}
    allowed.discard(None)
    if parent.workset_id not in allowed:
        raise Conflict('captured parent was never a session workset')
    required = {unit['url']: unit for unit in frozen['units']}
    supplied = {entry['unit']['url']: entry for entry in evidence['progress']}
    if len(required) != len(frozen['units']) or len(supplied) != len(evidence['progress']) or set(supplied) != set(required):
        raise Conflict('captured discovery required-unit ledger differs')
    outcomes, members, listings = [], {}, {}
    for unit in sorted(frozen['units'], key=lambda u: (u['url'].count('/'), u['url'])):
        entry = supplied[unit['url']]
        if entry['unit'] != unit or entry['value']['discovery_id'] != parent.discovery_id:
            raise Conflict('captured directory unit identity differs')
        value = entry['value']
        outcome = DirectoryOutcome.from_mapping(value['outcome'])
        if outcome.outcome != 'discovery_failed':
            outcome, selected, entries, _ = reopen_listing(objects, value, unit, context)
            if unit['role'] != 'root':
                parent_url = unit['url'].rsplit('/', 2)[0] + '/index.json'
                wanted = unit['url'].rsplit('/', 2)[1]
                candidate = next((item for item in listings.get(parent_url, ())
                                  if item.name == wanted and item.kind == 'dir'), None)
                if candidate is None or child_url(parent_url, candidate.href, candidate.name, True) + 'index.json' != unit['url']:
                    raise Conflict('captured successful directory lacks actual parent authorization')
            listings[unit['url']] = entries
            for source in selected:
                members[source.source_id] = source
        elif outcome.url != unit['url'] or outcome.period != unit['period'] or value['members']:
            raise Conflict('captured failed directory unit differs')
        outcomes.append(outcome)
    rebuilt = make_source_workset(context, frozen['end'], parent.discovery_id,
                                  tuple(members.values()), tuple(outcomes),
                                  date.fromisoformat(frozen['overlap_from']),
                                  acquisition_mode=frozen['acquisition_mode'])
    if rebuilt != parent:
        raise Conflict('captured discovery does not reconstruct exact original parent')


def capture_member_provenance(value, store, objects) -> Mapping:
    projection = read_member(value, store, objects)
    parent = _read_set(value['parent_ref'], objects)
    evidence = {'format_version': PROVENANCE_FORMAT, 'member': _plain(value),
                'parent': parent.to_mapping(), 'projection': projection.to_mapping(),
                'discovery': _discovery_snapshot(parent, store, objects)}
    validate_member_provenance(evidence, objects)
    return evidence


def validate_member_provenance(evidence, objects) -> SourceWorkset:
    evidence = _plain(evidence)
    if set(evidence) != {'format_version', 'member', 'parent', 'projection', 'discovery'} or evidence['format_version'] != PROVENANCE_FORMAT:
        raise Conflict('unsupported member provenance capture')
    value = evidence['member']
    if set(value) != {'member_id', 'source', 'parent_ref', 'member_ref'}:
        raise Conflict('captured member registry fields differ')
    parent = _read_set(value['parent_ref'], objects)
    projection = _read_set(value['member_ref'], objects)
    if parent.to_mapping() != evidence['parent'] or projection.to_mapping() != evidence['projection']:
        raise Conflict('member provenance differs from immutable worksets')
    source = Source.from_mapping(value['source'])
    if value['member_id'] != projection.workset_id or projection.members != (source,) or source not in parent.members:
        raise Conflict('member provenance identity differs')
    expected = expected_projection(parent, source.source_id)
    if expected != projection:
        raise Conflict('member projection changes original provenance')
    _validate_discovery(parent, evidence['discovery'], objects)
    return projection


def validate_capture(capture, objects) -> None:
    capture = _plain(capture)
    fields = {'format_version', 'member', 'parent', 'projection', 'discovery',
              'binding', 'snapshot', 'observation', 'affected_quarters', 'quarters'}
    if set(capture) != fields or capture['format_version'] != CAPTURE_FORMAT:
        raise Conflict('unsupported completion capture shape')
    value = capture['member']
    if set(value) != {'member_id', 'source', 'parent_ref', 'member_ref'}:
        raise Conflict('captured member registry fields differ')
    parent = _read_set(value['parent_ref'], objects)
    projection = _read_set(value['member_ref'], objects)
    if parent.to_mapping() != capture['parent'] or projection.to_mapping() != capture['projection']:
        raise Conflict('captured source worksets differ from immutable objects')
    source = Source.from_mapping(value['source'])
    if value['member_id'] != projection.workset_id or projection.members != (source,) or source not in parent.members:
        raise Conflict('captured member identity differs')
    expected = expected_projection(parent, source.source_id)
    if expected != projection:
        raise Conflict('projection changes original provenance')
    _validate_discovery(parent, capture['discovery'], objects)
    binding = Binding.from_mapping(capture['binding'])
    snapshot = Snapshot.from_mapping(capture['snapshot'])
    ref = ObservationRef.from_mapping(capture['observation'])
    if (binding.source_workset_id, binding.source_id, binding.snapshot_sha256) != (
            projection.workset_id, source.source_id, snapshot.sha256):
        raise Conflict('capture binding differs')
    if ref.source != source or ref.snapshot != snapshot:
        raise Conflict('capture observation differs from exact source/snapshot')
    objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
    durable, _ = _read_manifest(ref.manifest_ref, objects)
    if durable != ref:
        raise Conflict('capture observation differs from immutable readback')
    affected = capture['affected_quarters']
    quarters = [GenerationCapture.from_mapping(q) for q in capture['quarters']]
    if affected != sorted(set(affected)) or [q.quarter for q in quarters] != affected or not set(ref.quarter_counts) <= set(affected):
        raise Conflict('capture affected-quarter coverage differs')
    for quarter in quarters:
        manifest = validated_manifest(quarter, objects)
        if (manifest.parser_version, manifest.schema_version) != (ref.parser_version, ref.schema_version):
            raise Conflict('captured publication versions differ')
        active = next((r for r in manifest.sources if r.source.source_id == source.source_id), None)
        if not accounts_for(active, ref):
            raise Conflict('captured publication source membership differs')


def accounts_for(active: ObservationRef | None, ref: ObservationRef) -> bool:
    """The active generation holds the member's exact observation or a strictly later one of its source."""
    if active is None:
        return False
    if active == ref:
        return True
    return (active.source == ref.source
            and (active.parser_version, active.schema_version) == (ref.parser_version, ref.schema_version)
            and active.snapshot.sha256 != ref.snapshot.sha256
            and active.snapshot.received_at > ref.snapshot.received_at)


LEGACY_PUBLISH_FORMAT = 'sec-workflow-legacy-publish-v1'


def _legacy_publish_call(context, objects):
    if context.command != 'publish':
        raise Conflict('legacy repair context is not a publish command')
    settings = Settings.from_mapping(context.to_mapping()['effective_config'])
    if context.pinned_on is None or pin_context(settings, context, context.pinned_on)[0] != context:
        raise Conflict('legacy publish context is not exactly pinned')
    path = result_path(context)
    command_path = path.rsplit('/', 1)[0] + '/command.json'
    body = objects.read(command_path)
    frozen = parse_json(body)
    if (not isinstance(frozen, dict) or set(frozen) != {'context', 'intent'}
            or canonical_json(to_mapping_value(frozen)) != body or frozen['context'] != context.to_mapping()):
        raise Conflict('legacy publish frozen command differs from exact Attempt context')
    intent = frozen['intent']
    if (not isinstance(intent, dict) or set(intent) != {'command', 'today', 'workset', 'force'}
            or intent['command'] != 'publish' or intent['force'] is not None
            or intent['today'] not in (None, context.pinned_on.isoformat())):
        raise Conflict('legacy publish frozen intent differs')
    workset = decode_transformed(objects.read(intent['workset']))
    if transformed_ref(workset) != intent['workset']:
        raise Conflict('legacy publish transformed input address differs')
    if not workset.complete:
        raise Conflict('legacy unfinished publication has no complete publishable input')
    if (workset.context.parser_version, workset.context.schema_version) != (
            context.parser_version, context.schema_version):
        raise Conflict('legacy publish input versions differ')
    return {'format_version': LEGACY_PUBLISH_FORMAT, 'context': context.to_mapping(),
            'intent': intent, 'input_ref': intent['workset'], 'result_ref': path}


def read_legacy_publish(call, store, objects):
    if set(call) != {'format_version', 'context', 'intent', 'input_ref', 'result_ref'} or call['format_version'] != LEGACY_PUBLISH_FORMAT:
        raise Conflict('legacy publication call schema differs')
    context = RunContext.from_mapping(call['context'])
    if _legacy_publish_call(context, objects) != _plain(call):
        raise Conflict('legacy publication descriptor differs from canonical command')
    result = read_etl_result(call['result_ref'], objects)
    if result.context != context:
        raise Conflict('legacy publication result differs from original exact context')
    # The earlier checked validation is namespace-independent at this layer:
    # it validates exact transformed input, raw chain, versions and all quarter artifacts.
    _validate_input_output(call, result, store, objects)
    if store is not None:
        row = store.get('Attempt', attempt_key(context))
        if row is None or row.to_mapping()['value']['context'] != context.to_mapping() or row.to_mapping()['value']['result'] != result.to_mapping():
            raise Conflict('legacy publication result requires repaired original Attempt')
    return result


def _read_publish_call(call, store, objects):
    if call.get('format_version') == LEGACY_PUBLISH_FORMAT:
        return read_legacy_publish(call, store, objects)
    return read_child(call, store, objects)


def _call_context(call, store, objects):
    template = RunContext.from_mapping(call['context'])
    row = store.get('Attempt', attempt_key(template))
    if row is None:
        command_path = call['result_ref'].rsplit('/', 1)[0] + '/command.json'
        for path in (command_path, call['result_ref']):
            try:
                objects.read(path)
            except FileNotFoundError:
                continue
            raise Conflict('begun publication immutable evidence lacks its Attempt index')
        return None
    value = row.to_mapping()['value']
    actual = RunContext.from_mapping(value['context'])
    if call.get('format_version') == LEGACY_PUBLISH_FORMAT:
        if actual != template or _legacy_publish_call(actual, objects) != _plain(call):
            raise Conflict('legacy unfinished publication differs from exact canonical Attempt')
    else:
        expected = template.to_mapping()
        expected['started_at'] = actual.started_at.isoformat()
        if expected != actual.to_mapping() or actual.started_at < template.started_at or actual.started_at >= actual.deadline:
            raise Conflict('unfinished publish Attempt differs from checked call')
        command_path = call['result_ref'].rsplit('/', 1)[0] + '/command.json'
        frozen = {'context': actual.to_mapping(), 'intent': _plain(call['intent'])}
        if objects.read(command_path) != canonical_json(to_mapping_value(frozen)):
            raise Conflict('unfinished publish command intent differs')
    return value


def _publish_calls(store, objects):
    checked, checked_paths = [], set()
    for row in store.scan('WorkflowChildCall', {}):
        value = row.to_mapping()['value']
        try:
            call, template = _authority(value, None, objects)
            if template.command != 'publish':
                continue
            attempt = _call_context(call, store, objects)
            if attempt is None:
                continue  # Before begin/command commit, this call cannot have reached CAS.
            _transformed_input(call['input_ref'], None, objects)
            checked.append(call); checked_paths.add(call['result_ref'])
        except (ValueError, OSError, Conflict, KeyError, TypeError) as error:
            raise Conflict(f'checked publication authority inventory uncertain: {error}') from error
    legacy = []
    for row in store.scan('Attempt', {}):
        value = row.to_mapping()['value']
        try:
            context = RunContext.from_mapping(value['context'])
            if context.command != 'publish' or result_path(context) in checked_paths:
                continue
            call = _legacy_publish_call(context, objects)
            _transformed_input(call['input_ref'], None, objects)
            call_key = hashlib.sha256(canonical_json(to_mapping_value(call))).hexdigest()
            if (value['result'] is None
                    or store.get('WorkflowRepairObligation', call_key) is not None
                    or _read_repair_authority(call_key, objects) is not None):
                legacy.append(call)
        except (ValueError, OSError, Conflict, KeyError, TypeError) as error:
            raise Conflict(f'ordinary publication authority inventory uncertain: {error}') from error
    calls = checked + legacy
    if len({canonical_json(to_mapping_value(call)) for call in calls}) != len(calls):
        raise Conflict('duplicate original publication call authority')
    return tuple(calls)

def _obligations(source, store, objects):
    found = []
    for call in _publish_calls(store, objects):
        workset = decode_transformed(objects.read(call['input_ref']))
        if not any(ref.source == source for ref in workset.observations):
            continue
        call_key = hashlib.sha256(canonical_json(to_mapping_value(call))).hexdigest()
        saved = store.get('WorkflowRepairObligation', call_key)
        if saved is None:
            descriptor = _read_repair_authority(call_key, objects)
            if descriptor is None:
                try:
                    _read_publish_call(call, store, objects)
                except FileNotFoundError:
                    attempt = _call_context(call, store, objects)
                    if attempt is None:
                        continue
                    if attempt['result'] is not None:
                        raise Conflict('finished Attempt lacks its immutable child result')
                else:
                    continue
                recorded = [q['quarter'] for error in attempt['structured_errors']
                            for q in error.get('details', {}).get('quarters', ())]
                quarters = sorted(set(recorded) | set(_affected_quarters(workset.observations, objects, store)))
                payload = {'format_version': OBLIGATION_FORMAT, 'call': call,
                           'context': attempt['context'], 'transformed_ref': call['input_ref'],
                           'sources': [ref.to_mapping() for ref in workset.observations],
                           'affected_quarters': quarters}
                descriptor = _document(payload, OBLIGATION_FORMAT, 'workflow-repairs', objects)
                # The original capture wins before a recoverable index is written.
                _write_repair_authority(call_key, descriptor, objects)
        else:
            indexed = saved.to_mapping()['value']
            if indexed['call_sha256'] != call_key:
                raise Conflict('repair obligation call identity differs')
            descriptor = indexed['descriptor']
        payload = _read_document(descriptor, OBLIGATION_FORMAT, objects)
        if (payload['call'] != call or payload['transformed_ref'] != call['input_ref']
                or payload['sources'] != [r.to_mapping() for r in workset.observations]):
            raise Conflict('repair obligation immutable input differs')
        if saved is None:
            _immutable('WorkflowRepairObligation', call_key,
                       {'call_sha256': call_key, 'descriptor': descriptor}, store)
        resolution_row = store.get('WorkflowRepairResolution', call_key)
        if resolution_row is None:
            try:
                repaired = _read_publish_call(call, store, objects)
            except FileNotFoundError:
                pass
            else:
                if repaired.outcome in ('success', 'unchanged'):
                    if call.get('format_version') == LEGACY_PUBLISH_FORMAT:
                        # Exact original public retry may finish its own index. Its
                        # immutable result discharges this obligation directly.
                        captures, artifacts = _publication_captures(repaired, store, objects)
                        _write_resolution(descriptor, call, repaired, captures, artifacts, store, objects)
                    else:
                        resolve_repair(descriptor, call, store, objects)
                    resolution_row = store.get('WorkflowRepairResolution', call_key)
        if resolution_row is not None:
            resolution = resolution_row.to_mapping()['value']
            resolved = _read_document(resolution, RESOLUTION_FORMAT, objects)
            if resolved['obligation'] != _plain(descriptor):
                raise Conflict('repair resolution index names another original obligation')
            validate_resolution_capture(resolution, objects)
        else:
            found.append(descriptor)
    return tuple(found)

def outstanding_repairs(value, store, objects) -> tuple[Mapping, ...]:
    read_member(value, store, objects)
    return _obligations(Source.from_mapping(value['source']), store, objects)


def read_repair_obligation(path, objects):
    body = objects.read(path)
    descriptor = {'ref': path, 'sha256': hashlib.sha256(body).hexdigest(),
                  'bytes': len(body), 'format_version': OBLIGATION_FORMAT}
    _read_document(descriptor, OBLIGATION_FORMAT, objects)
    return descriptor


def _repair_artifacts(manifest, store):
    artifacts = []
    for ref in manifest.sources:
        if not ref.quarter_counts.get(manifest.quarter):
            continue
        key = processing_key(ref.source.source_id, ref.snapshot.sha256,
                             ref.parser_version, ref.schema_version)
        receipt_key = hashlib.sha256(canonical_json(to_mapping_value([key, manifest.quarter, manifest.generation_id]))).hexdigest()
        expected = {'processing_key': key, 'quarter': manifest.quarter,
                    'generation_id': manifest.generation_id,
                    'source_fingerprint': manifest.source_fingerprint}
        receipt = store.get('PublicationReceipt', receipt_key)
        processing = store.get('Processing', key)
        if receipt is None or receipt.to_mapping()['value'] != expected or processing is None:
            raise Conflict('checked publication repair artifacts are absent or differ')
        value = processing.to_mapping()['value']
        if value['processing_key'] != key or value['observation'] != ref.to_mapping() or value['publications'].get(manifest.quarter, {}).get(manifest.generation_id) != receipt_key:
            raise Conflict('checked publication Processing membership differs')
        artifacts.append({'receipt_key': receipt_key, 'receipt': expected,
                          'observation': ref.to_mapping()})
    return artifacts


def _publication_captures(result, store, objects):
    captures, artifacts = [], []
    for quarter in result.quarters:
        if quarter.outcome not in ('published', 'unchanged'):
            raise Conflict('repair resolution has unfinished publication quarter')
        body = objects.read(quarter.manifest_ref)
        capture = GenerationCapture(quarter.quarter, quarter.generation_id, quarter.manifest_ref,
                                    hashlib.sha256(body).hexdigest(), len(body))
        manifest = validated_manifest(capture, objects)
        captures.append(capture.to_mapping())
        artifacts.append({'quarter': quarter.quarter, 'records': _repair_artifacts(manifest, store)})
    return captures, artifacts


def _write_resolution(obligation, call, result, captures, artifacts, store, objects):
    original = _read_document(obligation, OBLIGATION_FORMAT, objects)
    if (result.context.command != 'publish' or result.outcome not in ('success', 'unchanged')
            or result.input_ref != original['transformed_ref']
            or call['input_ref'] != original['transformed_ref']):
        raise Conflict('repair resolution requires exact successful transformed input')
    if set(original['affected_quarters']) - {q['quarter'] for q in captures}:
        raise Conflict('repair resolution omitted formerly affected quarter')
    for ref_value in original['sources']:
        ref = ObservationRef.from_mapping(ref_value)
        for captured in captures:
            manifest = validated_manifest(GenerationCapture.from_mapping(captured), objects)
            if next((r for r in manifest.sources if r.source.source_id == ref.source.source_id), None) != ref:
                raise Conflict('repair resolution silently supersedes unfinished source evidence')
    payload = {'format_version': RESOLUTION_FORMAT, 'obligation': _plain(obligation),
               'call': _plain(call), 'result': result.to_mapping(),
               'quarters': captures, 'repair_artifacts': artifacts}
    descriptor = _document(payload, RESOLUTION_FORMAT, 'workflow-repair-resolutions', objects)
    call_key = hashlib.sha256(canonical_json(to_mapping_value(original['call']))).hexdigest()
    _immutable('WorkflowRepairResolution', call_key, descriptor, store)
    return descriptor


def resolve_repair(obligation, successful_publish_call, store, objects) -> Mapping:
    _read_document(obligation, OBLIGATION_FORMAT, objects)
    call = _plain(successful_publish_call)
    result = _read_publish_call(call, store, objects)
    captures, artifacts = _publication_captures(result, store, objects)
    return _write_resolution(obligation, call, result, captures, artifacts, store, objects)


def _expected_artifacts(manifest):
    expected = []
    for ref in manifest.sources:
        if not ref.quarter_counts.get(manifest.quarter):
            continue
        key = processing_key(ref.source.source_id, ref.snapshot.sha256,
                             ref.parser_version, ref.schema_version)
        receipt_key = hashlib.sha256(canonical_json(to_mapping_value([key, manifest.quarter, manifest.generation_id]))).hexdigest()
        receipt = {'processing_key': key, 'quarter': manifest.quarter,
                   'generation_id': manifest.generation_id,
                   'source_fingerprint': manifest.source_fingerprint}
        expected.append({'receipt_key': receipt_key, 'receipt': receipt,
                         'observation': ref.to_mapping()})
    return expected


def validate_resolution_capture(resolution, objects) -> None:
    value = _read_document(resolution, RESOLUTION_FORMAT, objects)
    original = _read_document(value['obligation'], OBLIGATION_FORMAT, objects)
    call = value['call']
    result = (read_legacy_publish(call, None, objects)
              if call.get('format_version') == LEGACY_PUBLISH_FORMAT
              else read_child_capture(call, objects))
    if (result.to_mapping() != value['result'] or result.context.command != 'publish'
            or result.input_ref != original['transformed_ref']
            or call['input_ref'] != original['transformed_ref']
            or result.outcome not in ('success', 'unchanged')):
        raise Conflict('repair resolution child evidence differs')
    quarters = {q.quarter: q for q in result.quarters}
    captured = {q['quarter']: q for q in value['quarters']}
    if len(captured) != len(value['quarters']) or set(original['affected_quarters']) - set(captured) or set(quarters) != set(captured):
        raise Conflict('repair resolution quarter set differs')
    artifacts = {v['quarter']: v['records'] for v in value['repair_artifacts']}
    if len(artifacts) != len(value['repair_artifacts']) or set(artifacts) != set(captured):
        raise Conflict('repair resolution artifact coverage differs')
    for quarter, mapping in captured.items():
        capture = GenerationCapture.from_mapping(mapping)
        manifest = validated_manifest(capture, objects)
        q = quarters[quarter]
        if q.outcome not in ('published', 'unchanged') or (q.generation_id, q.manifest_ref) != (capture.generation_id, capture.manifest_ref):
            raise Conflict('repair resolution capture differs from successful command')
        if artifacts[quarter] != _expected_artifacts(manifest):
            raise Conflict('captured repair artifacts differ from manifest identities')
        for ref_value in original['sources']:
            ref = ObservationRef.from_mapping(ref_value)
            if next((r for r in manifest.sources if r.source.source_id == ref.source.source_id), None) != ref:
                raise Conflict('repair resolution source membership differs')
def validate_resolution(resolution, store, objects):
    validate_resolution_capture(resolution, objects)
    value = _read_document(resolution, RESOLUTION_FORMAT, objects)
    result = (read_legacy_publish(value['call'], None, objects)
              if value['call'].get('format_version') == LEGACY_PUBLISH_FORMAT
              else read_child_capture(value['call'], objects))
    artifact_by_quarter = {v['quarter']: v['records'] for v in value['repair_artifacts']}
    for mapping in value['quarters']:
        capture = GenerationCapture.from_mapping(mapping)
        manifest = validated_manifest(capture, objects)
        if artifact_by_quarter[capture.quarter] != _repair_artifacts(manifest, store):
            raise Conflict('repair resolution current recoverable indexes differ')


def evaluate_member(value, parser_version, schema_version, store, objects) -> CompletionEvaluation:
    source = Source.from_mapping(value['source'])
    obligations = ()
    try:
        projection = read_member(value, store, objects)
        obligations = _obligations(source, store, objects)
        acquisition = AcquisitionState(store)
        binding = acquisition.binding(projection.workset_id, source.source_id)
        if binding is None:
            return CompletionEvaluation(False, None, obligations,
                (Error('acquisition_pending', 'member has no exact raw pin', True, source.source_id, {}),))
        snapshot = acquisition.snapshot(source.source_id, binding.snapshot_sha256)
        key = processing_key(source.source_id, snapshot.sha256, parser_version, schema_version)
        row = store.get('Processing', key)
        if row is None:
            return CompletionEvaluation(False, None, obligations,
                (Error('transform_pending', 'member has no current Processing identity', True, source.source_id, {}),))
        processing = row.to_mapping()['value']
        ref = ObservationRef.from_mapping(processing['observation'])
        if processing['processing_key'] != key or (ref.source, ref.snapshot, ref.parser_version, ref.schema_version) != (source, snapshot, parser_version, schema_version):
            raise Conflict('decoded Processing identity differs from member pin/current versions')
        durable, _ = _read_manifest(ref.manifest_ref, objects)
        if durable != ref:
            raise Conflict('Processing differs from immutable observation')
        affected = _affected_quarters((ref,), objects, store)
        captures, gaps = [], []
        for quarter in affected:
            capture = capture_quarter(quarter, objects, EtlState(store))
            if capture is None:
                gaps.append(Error('publication_pending', 'affected quarter has no publication', True, source.source_id, {'quarter': quarter}))
                continue
            manifest = validated_manifest(capture, objects)
            active = next((r for r in manifest.sources if r.source.source_id == source.source_id), None)
            if not accounts_for(active, ref):
                gaps.append(Error('publication_pending', 'affected quarter does not contain exact current observation', True, source.source_id, {'quarter': quarter}))
                continue
            captures.append(capture.to_mapping())
        if gaps or obligations:
            return CompletionEvaluation(False, None, obligations, tuple(gaps))
        parent = _read_set(value['parent_ref'], objects)
        capture = {'format_version': CAPTURE_FORMAT, 'member': _plain(value),
                   'parent': parent.to_mapping(), 'projection': projection.to_mapping(),
                   'discovery': _discovery_snapshot(parent, store, objects), 'binding': binding.to_mapping(),
                   'snapshot': snapshot.to_mapping(), 'observation': ref.to_mapping(),
                   'affected_quarters': affected, 'quarters': captures}
        validate_capture(capture, objects)
        return CompletionEvaluation(True, capture, (), ())
    except (Conflict, ValueError, OSError, KeyError, StopIteration) as error:
        return CompletionEvaluation(False, None, obligations,
            (Error('state_conflict', error_text(error), False, source.source_id,
                   {'type': type(error).__name__}),))
