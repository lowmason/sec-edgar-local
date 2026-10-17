# workflows/results.py
from __future__ import annotations
from ..models import freeze, to_mapping_value

import hashlib
from datetime import datetime, timezone

from ..config import Settings, pin_context
from ..models import RunContext, canonical_json, parse_json
from ..storage.contracts import AlreadyExists, CAS_ATTEMPTS, Conflict, observe
from .checked import read_child_capture
from .completion import (validate_capture, validate_resolution_capture,
                         validate_member_provenance)
from .contracts import WorkflowResult, workflow_path

SELECTION_FORMAT = 'sec-workflow-selection-v2'
# Plan 5 wrote v1, which has no `superseded` key. A stored v1 selection stays readable, as one that
# superseded nothing, and is never written. Its exact bytes are pinned by the report, so it is not upgraded.
LEGACY_SELECTION_FORMAT = 'sec-workflow-selection-v1'


def _plain(value):
    return parse_json(canonical_json(to_mapping_value(freeze(value))))


def workflow_key(context):
    return hashlib.sha256(canonical_json(to_mapping_value([context.run_id, context.command, context.attempt_id]))).hexdigest()


def _sibling(context, name):
    return workflow_path(context).rsplit('/', 1)[0] + '/' + name


def _read(path, objects):
    body = objects.read(path)
    value = parse_json(body)
    if canonical_json(to_mapping_value(value)) != body:
        raise Conflict('workflow immutable object is not canonical JSON')
    return value, body


def _descriptor(path, body):
    return {'ref': path, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}


def _match_context(current, saved):
    expected = current.to_mapping()
    expected['started_at'] = saved.started_at.isoformat()
    if expected != saved.to_mapping():
        raise Conflict('workflow exact correlation/config/date/version/deadline differs')
    settings = Settings.from_mapping(saved.to_mapping()['effective_config'])
    if saved.pinned_on is None or pin_context(settings, saved, saved.pinned_on)[0] != saved:
        raise Conflict('workflow saved context is not exactly pinned')


def _index(context, invocation, store, objects):
    key = workflow_key(context)
    expected = {'context': context.to_mapping(), 'intent': _plain(invocation),
                'selection_ref': None, 'result_ref': None}
    for _ in range(CAS_ATTEMPTS):
        row = store.get('WorkflowAttempt', key)
        if row is None:
            try:
                store.insert('WorkflowAttempt', key, expected)
                return expected
            except AlreadyExists:
                continue
        value = row.to_mapping()['value']
        if set(value) != set(expected) or value['context'] != expected['context'] or value['intent'] != expected['intent']:
            raise Conflict('workflow Attempt conflicts with immutable saved intent')
        return value
    raise Conflict('workflow begin exhausted conditional races')


def freeze_workflow(current, intent, store, objects) -> RunContext:
    path = _sibling(current, 'intent.json')
    try:
        frozen, body = _read(path, objects)
    except FileNotFoundError:
        row = store.get('WorkflowAttempt', workflow_key(current))
        saved = current if row is None else RunContext.from_mapping(row.to_mapping()['value']['context'])
        _match_context(current, saved)
        if row is not None and row.to_mapping()['value']['intent'] != _plain(intent):
            raise Conflict('workflow begun intent changed')
        if datetime.now(timezone.utc) >= saved.deadline:
            raise TimeoutError('unfinished workflow deadline expired')
        frozen = {'context': saved.to_mapping(), 'intent': _plain(intent)}
        _index(saved, intent, store, objects)
        body = canonical_json(to_mapping_value(frozen))
        objects.put_once(path, body)
    else:
        if set(frozen) != {'context', 'intent'} or frozen['intent'] != _plain(intent):
            raise Conflict('workflow invocation differs from frozen intent')
        saved = RunContext.from_mapping(frozen['context'])
        _match_context(current, saved)
        if path != _sibling(saved, 'intent.json'):
            raise Conflict('workflow intent path differs')
        _index(saved, intent, store, objects)
    objects.verify(path, hashlib.sha256(body).hexdigest(), len(body))
    result_path = workflow_path(saved)
    try:
        objects.read(result_path)
    except FileNotFoundError:
        if datetime.now(timezone.utc) >= saved.deadline:
            raise TimeoutError('unfinished workflow deadline expired')
    else:
        read_workflow_result(result_path, store, objects)
    return saved


def _capture_or_validate_discovery_failure(selection, call, template, objects, store=None):
    from ..models import Error
    from .checked import _context_matches, unfinished_child
    error = selection['discovery_error']
    if error is None or error not in selection['gaps']:
        raise Conflict('failed discovery lacks its original error gap')
    terminal = error['details']
    fields = {'call', 'outcome', 'exit', 'stdout', 'stderr', 'gaps', 'repair_pending', 'resumable'}
    if (set(terminal) != fields or terminal['call'] != call
            or terminal['outcome'] != error['code']
            or type(terminal['exit']) is not int
            or not isinstance(terminal['stdout'], str) or not isinstance(terminal['stderr'], str)
            or terminal['repair_pending'] is not False or terminal['resumable'] is not False):
        raise Conflict('failed discovery terminal details differ from original child')
    gaps = tuple(Error.from_mapping(value) for value in terminal['gaps'])
    if error['code'] != next((gap.code for gap in gaps), 'internal_error'):
        raise Conflict('failed discovery classification differs from original errors')
    if any(gap.to_mapping() not in selection['gaps'] for gap in gaps):
        raise Conflict('selection omitted an original unfinished discovery gap')
    path = call['result_ref'].rsplit('/', 1)[0] + '/terminal.json'
    if store is not None:
        actual, saved_gaps = unfinished_child(call, store)
        if saved_gaps != gaps:
            raise Conflict('discovery terminal capture differs from persisted Attempt')
        retained = {'context': actual.to_mapping(), 'terminal_error': terminal}
        objects.put_once(path, canonical_json(to_mapping_value(retained)))
    retained, _ = _read(path, objects)
    if set(retained) != {'context', 'terminal_error'} or retained['terminal_error'] != terminal:
        raise Conflict('failed discovery differs from immutable terminal capture')
    actual = RunContext.from_mapping(retained['context'])
    _context_matches(template, actual)
    command = objects.read(call['result_ref'].rsplit('/', 1)[0] + '/command.json')
    if command != canonical_json(to_mapping_value(call['intent'])):
        raise Conflict('failed discovery command differs from original checked intent')


def _validate_selection(selection, context, invocation, store, objects):
    from ..models import DirectoryOutcome, Error
    from ..discovery import quarter_span
    from ..state import AcquisitionState
    from .checked import _authority
    from .completion import validate_parent_provenance, validate_discovery_session
    from .members import WorkflowMembers, download_times
    from .provenance import read_member
    fields = {'format_version', 'context', 'invocation', 'members', 'jobs',
              'member_provenance', 'already_complete', 'discovery_call',
              'discovery_error', 'parent_ref', 'parent_provenance', 'discovery_session',
              'required_units', 'halted', 'requested_quarters', 'directories',
              'boundary_before', 'gaps', 'discovered_sources', 'unresolved_before'}
    formats = {LEGACY_SELECTION_FORMAT: fields, SELECTION_FORMAT: fields | {'superseded'}}
    selection = _plain(selection)
    version = selection.get('format_version')
    if (not isinstance(version, str) or version not in formats or set(selection) != formats[version]
            or selection['context'] != context.to_mapping() or selection['invocation'] != _plain(invocation)):
        raise Conflict('selection differs from frozen workflow intent')
    members = selection['members']
    keys = [(v['source']['period'], v['source']['source_id'], v['member_id']) for v in members]
    if keys != sorted(keys) or len({v['member_id'] for v in members}) != len(members):
        raise Conflict('selection member ordering/identity differs')
    jobs = selection['jobs']
    if [job['member'] for job in jobs] != members or any(set(job) != {'member', 'aliases'} or job['aliases'] != [job['member']] for job in jobs):
        raise Conflict('selection jobs must be canonical singleton member jobs')
    provenance = selection['member_provenance']
    if [e['member'] for e in provenance] != members:
        raise Conflict('selection member provenance coverage differs')
    for evidence in provenance:
        validate_member_provenance(evidence, objects)
    completed = selection['already_complete']
    for capture in completed:
        validate_capture(capture, objects)
        if (capture['observation']['parser_version'], capture['observation']['schema_version']) != (context.parser_version, context.schema_version):
            raise Conflict('skipped completion capture differs from pinned processing versions')
    completed_ids = [c['member']['member_id'] for c in completed]
    if len(set(completed_ids)) != len(completed_ids) or {v['member_id'] for v in members} & set(completed_ids):
        raise Conflict('selection completed captures overlap or duplicate members')
    superseded = selection.get('superseded', [])  # absent only from a v1 selection, which superseded nothing
    if any(set(entry) != {'member', 'by', 'served_by', 'downloaded_at', 'by_downloaded_at'} for entry in superseded):
        raise Conflict('selection superseded entry fields differ')
    order = [(e['member']['source']['period'], e['member']['source']['source_id'], e['member']['member_id'])
             for e in superseded]
    dropped = {key[2] for key in order}
    if order != sorted(order) or len(dropped) != len(order) or dropped & ({v['member_id'] for v in members} | set(completed_ids)):
        raise Conflict('selection superseded members overlap or are unordered')
    acquisition, registry, completions = AcquisitionState(store), WorkflowMembers(store, objects), {}

    def completion(value):  # entries often share `by`, and its completion scan is the heaviest read here
        if value['member_id'] not in completions:
            completions[value['member_id']] = registry.completed(
                value, context.parser_version, context.schema_version, repairs=False)
        return completions[value['member_id']]

    for entry in superseded:
        member, by, served_by = entry['member'], entry['by'], entry['served_by']
        for value in (member, by, served_by):
            read_member(value, store, objects)
        identity = member['source']['source_id']
        pinned, bound = (acquisition.binding(value['member_id'], identity) for value in (member, by))
        served, later = (datetime.fromisoformat(entry[name]) for name in ('downloaded_at', 'by_downloaded_at'))
        # Stored reports are re-validated on every read, so check only immutable or append-only rows, reached
        # by member: each frozen time must still be among its witness's receipts, whatever was received since.
        # The producer's latest-download guard reads mutable SourceState, so it is deliberately not re-checked.
        if (by['source'] != member['source'] or served_by['source'] != member['source'] or later <= served
                or pinned is None or bound is None
                or served not in download_times(served_by, pinned.snapshot_sha256, store)
                or later not in download_times(by, bound.snapshot_sha256, store)
                or completion(by) is None):
            raise Conflict('selection superseded member lacks its later completed download')
    if type(selection['halted']) is not bool:
        raise Conflict('selection halted marker is not boolean')
    for value in selection['directories']:
        DirectoryOutcome.from_mapping(value)
    for value in selection['gaps']:
        Error.from_mapping(value)
    error = selection['discovery_error']
    if error is not None:
        Error.from_mapping(error)
    call = selection['discovery_call']
    template = None
    discovery = None
    if call is not None:
        call, template = _authority(call, None, objects)
        if template.command != 'discover' or call['workflow_command'] != context.command or call['workflow_attempt_id'] != context.attempt_id or template.run_id != context.run_id:
            raise Conflict('selection discovery call belongs to another workflow')
        if call['intent']['refresh'] is not (context.command == 'reconcile'):
            raise Conflict('selection discovery refresh differs from its workflow command')
        if error is not None:
            _capture_or_validate_discovery_failure(selection, call, template, objects)
        else:
            try:
                discovery = read_child_capture(call, objects)
            except FileNotFoundError as missing:
                raise Conflict('missing discovery requires original terminal failure capture') from missing
            from ..collection import HALTING_OUTCOMES
            from .contracts import FATAL, COMPLETE
            expected_halt = (discovery.outcome in FATAL
                             or any(gap.code in HALTING_OUTCOMES for gap in discovery.gaps))
            if selection['halted'] != expected_halt:
                raise Conflict('selection discovery failure classification differs from checked result')
            if any(gap.to_mapping() not in selection['gaps'] for gap in discovery.gaps):
                raise Conflict('selection omitted an original checked discovery gap')
            if discovery.outcome not in COMPLETE and not selection['gaps']:
                raise Conflict('non-successful discovery lacks failure gaps')
    elif error is not None and error not in selection['gaps']:
        raise Conflict('undispatched discovery lacks its original error gap')
    session = selection['discovery_session']
    units = selection['required_units']
    if not isinstance(units, list) or len({unit['url'] for unit in units}) != len(units):
        raise Conflict('selection required-directory ledger duplicates or changes type')
    if session is None:
        if units:
            raise Conflict('selection required units lack an actual captured discovery session')
    else:
        origin = validate_discovery_session(session)
        if units != session['frozen']['units']:
            raise Conflict('selection exact required-directory ledger differs from frozen session')
        expected_id = (call['intent']['discovery_id'] if call is not None
                       else 'workflow-' + context.command + '-' + context.run_id)
        expected_mode = 'daily' if context.command == 'daily' else 'quarterly'
        if session['discovery_id'] != expected_id or session['frozen']['mode'] != expected_mode:
            raise Conflict('selection captured session identity or discovery mode differs')
        current = template if template is not None else context
        for field in ('run_id', 'image_digest', 'parser_version', 'schema_version', 'config_sha256', 'effective_config'):
            if getattr(origin, field) != getattr(current, field):
                raise Conflict('selection discovery session differs from current frozen run provenance')
        if origin.pinned_on != context.pinned_on or session['frozen']['end'] != invocation['pinned_end_quarter']:
            raise Conflict('selection discovery session has stale date or endpoint; use a fresh run')
        if call is not None:
            mode = 'refresh' if call['intent']['refresh'] else 'reuse_accepted'
            if session['frozen']['acquisition_mode'] != mode:
                raise Conflict('selection discovery acquisition mode differs from checked call')
    parent_ref = selection['parent_ref']
    proof = selection['parent_provenance']
    if parent_ref is None:
        if proof is not None or selection['directories'] or error is None or not selection['halted']:
            raise Conflict('absent parent requires halted/error evidence and no claimed directory coverage')
        if discovery is not None and discovery.source_workset_ref is not None:
            raise Conflict('selection omits a durable discovery parent')
    else:
        if call is None or discovery is None or discovery.source_workset_ref != parent_ref or proof is None or session is None:
            raise Conflict('selection parent lacks checked discovery and complete captured provenance')
        parent = validate_parent_provenance(proof, objects)
        if proof['parent_ref'] != parent_ref or proof['discovery']['session'] != session:
            raise Conflict('selection parent/session capture differs from exact discovery authority')
        if parent.discovery_id != call['intent']['discovery_id'] or parent.context.pinned_on != context.pinned_on or parent.pinned_end_quarter != invocation['pinned_end_quarter']:
            raise Conflict('selection parent changes discovery identity/current date/endpoint')
        if [d.to_mapping() for d in parent.directories] != selection['directories']:
            raise Conflict('selection directory outcomes differ from exact captured parent')
        if {unit['url'] for unit in units} != {d.url for d in parent.directories}:
            raise Conflict('selection omits a frozen required directory')
        from .provenance import projection, source_ref
        accounted = members + [capture['member'] for capture in completed]
        for source in parent.members:
            projected = projection(parent, source.source_id)
            expected = {'member_id': projected.workset_id, 'source': source.to_mapping(),
                        'parent_ref': parent_ref, 'member_ref': source_ref(projected)}
            if expected not in accounted:
                raise Conflict('selection omitted an exact discovered member projection')
        if selection['discovered_sources'] != len(parent.members):
            raise Conflict('selection discovered-source count differs from immutable parent')
    settings = Settings.from_mapping(context.to_mapping()['effective_config'])
    expected_requested = ([] if context.command == 'daily'
                          else list(quarter_span(settings.backfill.start_quarter, invocation['pinned_end_quarter'])))
    if selection['requested_quarters'] != expected_requested:
        raise Conflict('selection requested baseline units differ from pinned inclusive endpoints')
    for name in ('discovered_sources', 'unresolved_before'):
        if type(selection[name]) is not int or selection[name] < 0:
            raise Conflict('selection source-unit count is invalid')


def _repair_index_descriptor(context, field, descriptor, store):
    key = workflow_key(context)
    for _ in range(CAS_ATTEMPTS):
        row = store.get('WorkflowAttempt', key)
        if row is None:
            raise Conflict('workflow index vanished during descriptor repair')
        value = row.to_mapping()['value']
        if value['context'] != context.to_mapping():
            raise Conflict('workflow descriptor repair context differs')
        if value[field] is not None:
            if value[field] != descriptor:
                raise Conflict('workflow index descriptor conflicts with immutable authority')
            return
        value[field] = descriptor
        try:
            store.replace('WorkflowAttempt', key, value, row.version)
            return
        except Conflict:
            continue
    raise Conflict('workflow descriptor repair exhausted conditional races')


def freeze_selection(context, selection, store, objects):
    invocation, _ = _read(_sibling(context, 'intent.json'), objects)
    if invocation['context'] != context.to_mapping():
        raise Conflict('selection has no exact begun workflow intent')
    _index(context, invocation['intent'], store, objects)
    selection = _plain(selection)
    path = _sibling(context, 'selection.json')
    try:
        _read(path, objects)
    except FileNotFoundError:
        # First: the checks below can put_once a terminal capture, and a refused selection must leave nothing behind.
        if selection.get('format_version') != SELECTION_FORMAT:
            raise Conflict('new selection must use the current format')
        from .checked import _authority
        call = selection['discovery_call']
        if call is not None:
            call, template = _authority(call, None, objects)
            if selection['discovery_error'] is not None:
                _capture_or_validate_discovery_failure(selection, call, template, objects, store)
            else:
                read_child_capture(call, objects)
        from ..state import AcquisitionState
        call = selection['discovery_call']
        discovery_id = (call['intent']['discovery_id'] if call is not None
                        else 'workflow-' + context.command + '-' + context.run_id)
        actual = AcquisitionState(store).discovery_session(discovery_id)
        if actual is not None:
            captured = actual.to_mapping()['value']
            if selection['discovery_session'] != captured or selection['required_units'] != captured['frozen']['units']:
                raise Conflict('initial selection omitted or changed actual discovery session/required units')
    _validate_selection(selection, context, invocation['intent'], store, objects)
    body = canonical_json(to_mapping_value(selection))
    objects.put_once(path, body)
    objects.verify(path, hashlib.sha256(body).hexdigest(), len(body))
    if objects.read(path) != body:
        raise Conflict('frozen selection differs from exact proposed selection')
    _repair_index_descriptor(context, 'selection_ref', _descriptor(path, body), store)
    return _plain(selection)


def _validate_report(result, store, objects):
    from ..worksets import decode_source_workset
    context = result.context
    intent = _plain(result.intent)
    intent_fields = {'invocation', 'selection', 'child_calls', 'completion_captures',
                     'repair_resolutions', 'member_receipts', 'already_complete_sources',
                     'discovered_sources', 'unresolved_before'}
    if set(intent) != intent_fields:
        raise Conflict('workflow report intent schema differs')
    frozen, _ = _read(_sibling(context, 'intent.json'), objects)
    if frozen != {'context': context.to_mapping(), 'intent': _plain(intent['invocation'])}:
        raise Conflict('report differs from immutable invocation/context')
    selection, selection_body = _read(_sibling(context, 'selection.json'), objects)
    _validate_selection(selection, context, frozen['intent'], store, objects)
    from .contracts import COMPLETE
    if result.outcome in COMPLETE:
        proof = selection['parent_provenance']
        if (selection['halted'] or proof is None
                or not decode_source_workset(objects.read(selection['parent_ref'])).discovery_complete
                or any(value['outcome'] not in ('available', 'no_new_sources') for value in selection['directories'])):
            raise Conflict('successful workflow requires complete successful discovery listings')
    expected_descriptor = _descriptor(_sibling(context, 'selection.json'), selection_body)
    if _plain(intent['selection']) != expected_descriptor:
        raise Conflict('report frozen-selection descriptor differs')
    _index(context, frozen['intent'], store, objects)
    row = store.get('WorkflowAttempt', workflow_key(context))
    value = row.to_mapping()['value']
    if value['selection_ref'] is not None and value['selection_ref'] != expected_descriptor:
        raise Conflict('report/index selection descriptor differs')
    if result.source_workset_ref != selection['parent_ref']:
        raise Conflict('report source workset differs from frozen discovery')
    if result.requested_quarters != tuple(selection['requested_quarters']) or result.to_mapping()['directories'] != selection['directories'] or result.boundary_before != selection['boundary_before']:
        raise Conflict('report coverage ledger differs from frozen selection')
    for name in ('discovered_sources', 'unresolved_before'):
        if intent[name] != selection[name]:
            raise Conflict('report source-unit count differs from frozen selection')
    completed = selection['already_complete']
    selected_source_ids = {m.source.source_id for m in result.members}
    already = sorted({c['member']['source']['source_id'] for c in completed} - selected_source_ids)
    if sorted(intent['already_complete_sources']) != already:
        raise Conflict('report skipped-source count lacks exact before-dispatch captures')
    captures = [_plain(c) for c in intent['completion_captures']]
    for capture in captures:
        validate_capture(capture, objects)
    for capture in completed:
        if capture not in captures:
            raise Conflict('report omitted skipped-source immutable capture')
    by_member = {c['member']['member_id']: c for c in captures}
    complete_ids = {m.member_id for m in result.members if m.outcome in ('success', 'unchanged', 'no_new_sources')}
    expected_capture_ids = complete_ids | {c['member']['member_id'] for c in completed}
    if len(by_member) != len(captures) or set(by_member) != expected_capture_ids:
        raise Conflict('report contains orphan/duplicate completion captures')
    selected = {v['member_id']: v for v in selection['members']}
    if [m.member_id for m in result.members] != list(selected):
        raise Conflict('report does not account for every frozen selected member')
    receipts = intent['member_receipts']
    if len(receipts) != len(result.members):
        raise Conflict('report member receipt coverage differs')
    allowed_unfinished, receipt_calls, receipt_completions, receipt_resolutions = [], [], [], []
    from .members import WorkflowMembers
    receipts_reader = WorkflowMembers(store, objects)
    from ..models import Error, Source
    from .contracts import MemberResult
    for member, descriptor in zip(result.members, receipts):
        if descriptor is None:
            value = selected[member.member_id]
            pending = MemberResult(value['member_id'], Source.from_mapping(value['source']), value['parent_ref'],
                None, None, (), 'pending', False, False, False, (),
                (Error('workflow_deferred', 'halt/deadline left source undispatched', True,
                       value['source']['source_id'], {}),), context.parser_version, context.schema_version)
            if member != pending:
                raise Conflict('receipt-less member differs from canonical undispatched pending work')
            continue
        if set(descriptor) != {'ref', 'sha256', 'bytes', 'member_id', 'parser_version', 'schema_version'}:
            raise Conflict('report member receipt descriptor fields differ')
        objects.verify(descriptor['ref'], descriptor['sha256'], descriptor['bytes'])
        saved_member, saved_context, evidence, receipt_body = receipts_reader._read_receipt(descriptor['ref'])
        if (saved_member != member or saved_context != context
                or descriptor != receipts_reader._descriptor(member, context, receipt_body)
                or evidence['member'] != selected[member.member_id]):
            raise Conflict('report member receipt identity/context differs')
        receipt_calls.extend(evidence['calls'])
        if evidence['completion'] is not None:
            receipt_completions.append(evidence['completion'])
        receipt_resolutions.extend(evidence['resolutions'])
        terminal = evidence['terminal_error']
        if terminal is not None:
            if terminal.get('repair_pending') or terminal['call']['context']['command'] == 'publish':
                raise Conflict('workflow report cannot finalize unfinished publication repair')
            allowed_unfinished.append(terminal['call'])
    expected_calls = receipt_calls + ([] if selection['discovery_call'] is None else [selection['discovery_call']])
    if {canonical_json(to_mapping_value(call)) for call in expected_calls} != {canonical_json(to_mapping_value(call)) for call in intent['child_calls']}:
        raise Conflict('report child calls differ from exact member receipts/discovery')
    if {canonical_json(to_mapping_value(c)) for c in completed + receipt_completions} != {canonical_json(to_mapping_value(c)) for c in intent['completion_captures']}:
        raise Conflict('report completion evidence differs from exact receipts/selection')
    if {canonical_json(to_mapping_value(r)) for r in receipt_resolutions} != {canonical_json(to_mapping_value(r)) for r in intent['repair_resolutions']}:
        raise Conflict('report repair resolutions differ from member receipts')
    calls = {_plain(c)['result_ref']: _plain(c) for c in intent['child_calls']}
    if len(calls) != len(intent['child_calls']):
        raise Conflict('report contains duplicate child calls')
    durable = {}
    for ref, call in calls.items():
        if call == selection['discovery_call'] and selection['discovery_error'] is not None:
            continue
        try:
            durable[ref] = read_child_capture(call, objects)
        except FileNotFoundError:
            if call not in allowed_unfinished:
                raise Conflict('report contains unaccounted unfinished child')
    if selection['discovery_call'] is not None and selection['discovery_call'] not in list(calls.values()):
        raise Conflict('report omitted frozen discovery child')
    for member in result.members:
        if member.source.to_mapping() != selected[member.member_id]['source'] or member.parent_ref != selected[member.member_id]['parent_ref']:
            raise Conflict('report member provenance differs from selection')
        if (member.parser_version, member.schema_version) != (context.parser_version, context.schema_version):
            raise Conflict('report member versions differ from current pinned workflow')
        if member.snapshot_ref is not None:
            from ..worksets import decode_snapshot_workset
            snapshot_set = decode_snapshot_workset(objects.read(member.snapshot_ref))
            if snapshot_set.source_workset_id != selected[member.member_id]['member_id']:
                raise Conflict('report snapshot belongs to another original member alias')
        children = []
        for ref in member.child_refs:
            if ref not in durable:
                raise Conflict('report member lacks exact checked child result')
            children.append(durable[ref])
        by_command = {child.context.command: child for child in children}
        if len(by_command) != len(children):
            raise Conflict('report member repeats a child command')
        if 'collect' in by_command and by_command['collect'].snapshot_workset_ref != member.snapshot_ref:
            raise Conflict('member snapshot reference differs from collection child')
        if 'transform' in by_command:
            transform = by_command['transform']
            if transform.input_ref != member.snapshot_ref or transform.transformed_workset_ref != member.transformed_ref:
                raise Conflict('member transform chain differs')
        if 'publish' in by_command:
            publication = by_command['publish']
            if publication.input_ref != member.transformed_ref or publication.quarters != member.quarters:
                raise Conflict('member publication chain differs')
        if member.outcome in ('success', 'unchanged', 'no_new_sources'):
            if member.member_id not in by_member or 'publish' not in by_command:
                raise Conflict('complete member lacks child and immutable completion evidence')
            capture = by_member[member.member_id]
            from ..worksets import make_snapshot_workset
            from ..models import Snapshot
            projection = decode_source_workset(objects.read(selected[member.member_id]['member_ref']))
            if make_snapshot_workset(projection, (Snapshot.from_mapping(capture['snapshot']),)) != snapshot_set:
                raise Conflict('complete member snapshot capture differs from exact child input')
            if capture['member'] != selected[member.member_id] or (capture['observation']['parser_version'], capture['observation']['schema_version']) != (member.parser_version, member.schema_version):
                raise Conflict('complete member evidence/version differs')
            if set(capture['affected_quarters']) != {q.quarter for q in member.quarters}:
                raise Conflict('complete member report omitted an affected quarter')
            captured_quarters = {q['quarter']: q for q in capture['quarters']}
            for quarter in member.quarters:
                proof = captured_quarters[quarter.quarter]
                if (quarter.generation_id, quarter.manifest_ref) != (proof['generation_id'], proof['manifest_ref']):
                    raise Conflict('complete member capture differs from exact publish child')
        for child in children:
            if child.context.command in ('transform', 'publish') and (child.context.parser_version, child.context.schema_version) != (member.parser_version, member.schema_version):
                raise Conflict('member processing child uses another pinned version')
        child_gaps = [gap.to_mapping() for child in children for gap in child.gaps]
        member_gaps = [gap.to_mapping() for gap in member.gaps]
        if any(gap not in member_gaps for gap in child_gaps):
            raise Conflict('member omitted retained child error evidence')
    for gap in selection['gaps']:
        if gap not in [g.to_mapping() for g in result.gaps]:
            raise Conflict('report omitted frozen discovery/selection gap')
    from .contracts import summarize
    outcome, counts = summarize(result.members, result.gaps, intent['discovered_sources'],
                                intent['unresolved_before'], context.command,
                                tuple(intent['already_complete_sources']))
    if result.outcome != outcome or result.to_mapping()['counts'] != counts:
        raise Conflict('report outcome/counts differ from checked source evidence')
    for resolution in intent['repair_resolutions']:
        validate_resolution_capture(resolution, objects)
    return selection, expected_descriptor


def read_workflow_result(path, store, objects) -> WorkflowResult:
    mapping, body = _read(path, objects)
    result = WorkflowResult.from_mapping(mapping)
    if workflow_path(result.context) != path:
        raise Conflict('workflow report path differs from canonical command identity')
    selection, selection_descriptor = _validate_report(result, store, objects)
    descriptor = _descriptor(path, body)
    _repair_index_descriptor(result.context, 'selection_ref', selection_descriptor, store)
    _repair_index_descriptor(result.context, 'result_ref', descriptor, store)
    return result


def write_workflow_result(result, store, objects, observer=None) -> str:
    path = workflow_path(result.context)
    _validate_report(result, store, objects)
    # The deadline stops child work; final validated accounting of pending work
    # may be committed by an invocation that already began before the deadline.
    body = canonical_json(to_mapping_value(result.to_mapping()))
    objects.put_once(path, body)
    objects.verify(path, hashlib.sha256(body).hexdigest(), len(body))
    observe(observer, 'workflow.after_report_object')
    read_workflow_result(path, store, objects)
    observe(observer, 'workflow.after_attempt_finish')
    return path
