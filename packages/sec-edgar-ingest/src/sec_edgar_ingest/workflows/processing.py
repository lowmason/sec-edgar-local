from collections.abc import Mapping
from dataclasses import dataclass
from ..config import Settings
from ..models import Record, RunContext, canonical_json, parse_json, validate_record_fields, to_mapping_value
from ..storage.contracts import Conflict, observe
from ..worksets import decode_snapshot_workset
from .contracts import COMPLETE, MemberResult
from .checked import ChildUnfinished, read_child_capture, _authority, _context_matches, unfinished_child
from .completion import evaluate_member, resolve_repair, validate_capture, validate_resolution_capture
from .provenance import read_member, read_source, projection, transfer_binding

@dataclass(frozen=True, slots=True)
class ProcessedMember(Record):
    result: MemberResult
    evidence: Mapping[str, object]
    def __post_init__(self):
        validate_record_fields(self)

def process_member(value, context, dispatcher, store, objects, observer=None) -> ProcessedMember:
    value = to_mapping_value(value)
    member = read_member(value, store, objects)
    from .members import WorkflowMembers
    replay = WorkflowMembers(store, objects).replay(value, context)
    if replay is not None:
        return ProcessedMember(replay[0], replay[1])
    source = member.members[0]
    origin = Settings.from_mapping(member.context.to_mapping()['effective_config'])
    initial = evaluate_member(value, context.parser_version, context.schema_version, store, objects)
    resolutions, calls, gaps, quarters = [], [], [], ()
    for obligation in initial.obligations:
        objects.verify(obligation['ref'], obligation['sha256'], obligation['bytes'])
        saved = parse_json(objects.read(obligation['ref']))
        old = saved['call']['context']
        settings = Settings.from_mapping(old['effective_config'])
        repaired = dispatcher.execute('publish', 'repair-' + obligation['sha256'], settings,
                                      ('--workset', saved['transformed_ref']))
        calls.append(dict(repaired.call))
        resolutions.append(resolve_repair(obligation, repaired.call, store, objects))
    child_refs, snapshot_ref, transformed_ref = [], None, None
    downloaded = transformed = quarantined = False
    terminal_error = None
    try:
        collected = dispatcher.execute('collect', 'collect-' + value['member_id'], origin,
                                       ('--workset', value['member_ref']))
        calls.append(dict(collected.call))
        child_refs.append(collected.result_ref)
        raw = collected.result
        gaps.extend(raw.gaps)
        outcome, snapshot_ref = raw.outcome, raw.snapshot_workset_ref
        quarantined = raw.outcome == 'quarantined' and snapshot_ref is None
        downloaded = snapshot_ref is not None
        if snapshot_ref is not None:
            snapshots = decode_snapshot_workset(objects.read(snapshot_ref))
            if snapshots.source_workset_id != member.workset_id or len(snapshots.snapshots) != 1:
                raise Conflict('collection changed exact singleton source workset')
            transfer_binding(value, snapshots.snapshots[0], store, objects)
        # Collection.quarantined counts failed body retention, not source refusal.
        if snapshot_ref is not None and outcome in COMPLETE:
            parsed = dispatcher.execute('transform', 'transform-' + value['member_id'], dispatcher.settings,
                                        ('--workset', snapshot_ref))
            calls.append(dict(parsed.call))
            child_refs.append(parsed.result_ref)
            etl = parsed.result
            gaps.extend(etl.gaps)
            outcome, transformed_ref = etl.outcome, etl.transformed_workset_ref
            transformed = bool(etl.transformed or etl.unchanged)
            quarantined = bool(etl.quarantined) and outcome not in COMPLETE and not transformed
            if quarantined:
                outcome = 'quarantined'
            if outcome in COMPLETE:
                published = dispatcher.execute('publish', 'publish-' + value['member_id'], dispatcher.settings,
                                               ('--workset', transformed_ref))
                calls.append(dict(published.call))
                child_refs.append(published.result_ref)
                outcome, quarters = published.result.outcome, published.result.quarters
                gaps.extend(published.result.gaps)
    except ChildUnfinished as error:
        if error.resumable:
            raise  # No member completion/workflow report while publication repair is unfinished.
        calls.append(dict(error.call))
        outcome = error.outcome
        gaps.extend(error.gaps)
        terminal_error = to_mapping_value(error.details)
        actual, retained_gaps = unfinished_child(error.call, store)
        if retained_gaps != error.gaps:
            raise Conflict('terminal error differs from persisted unfinished Attempt')
        retained = {'context': actual.to_mapping(), 'terminal_error': terminal_error}
        objects.put_once(error.call['result_ref'].rsplit('/', 1)[0] + '/terminal.json',
                         canonical_json(to_mapping_value(retained)))
    result = MemberResult(value['member_id'], source, value['parent_ref'], snapshot_ref,
        transformed_ref, tuple(child_refs), outcome, downloaded, transformed, quarantined,
        tuple(quarters), tuple(gaps), context.parser_version, context.schema_version)
    evaluated = evaluate_member(value, context.parser_version, context.schema_version, store, objects)
    if result.outcome in COMPLETE and not evaluated.complete:
        raise Conflict('child completion lacks all affected quarter/repair evidence')
    evidence = {'format_version': 'sec-workflow-member-evidence-v1', 'member': dict(value),
        'calls': calls, 'completion': evaluated.capture if result.outcome in COMPLETE else None,
        'resolutions': resolutions, 'terminal_error': terminal_error}
    validate_member_evidence(result, evidence, objects)
    observe(observer, 'workflow.after_member_processing')
    return ProcessedMember(result, evidence)

def _member_outcome(child):
    refused = (child.context.command == 'transform' and child.quarantined
               and not (child.transformed or child.unchanged))
    return 'quarantined' if refused else child.outcome


def validate_member_evidence(result, evidence, objects) -> None:
    evidence = to_mapping_value(evidence)
    from .contracts import member_status
    from ..results import exit_code
    fields = {'format_version', 'member', 'calls', 'completion', 'resolutions', 'terminal_error'}
    if set(evidence) != fields or evidence['format_version'] != 'sec-workflow-member-evidence-v1':
        raise Conflict('member evidence schema differs')
    value = evidence['member']
    if (result.member_id, result.source.to_mapping(), result.parent_ref) != (
            value['member_id'], value['source'], value['parent_ref']):
        raise Conflict('receipt changes registered member/source/parent')
    if set(value) != {'member_id', 'source', 'parent_ref', 'member_ref'}:
        raise Conflict('member projection fields differ')
    parent = read_source(value['parent_ref'], objects)
    projected = read_source(value['member_ref'], objects)
    if projected != projection(parent, result.source.source_id) or projected.workset_id != result.member_id:
        raise Conflict('member differs from immutable original projection')
    checked, repair_calls, missing_calls = [], [], []
    namespace = None
    for call in evidence['calls']:
        call, template = _authority(call, None, objects)
        correlation = (template.run_id, call['workflow_command'], call['workflow_attempt_id'])
        if namespace is not None and namespace != correlation:
            raise Conflict('member calls change workflow namespace')
        namespace = correlation
        if call['step_id'].startswith('repair-'):
            repaired = read_child_capture(call, objects)
            if repaired.context.command != 'publish' or repaired.outcome not in COMPLETE:
                raise Conflict('repair prefix is not successful checked publication')
            if checked or missing_calls:
                raise Conflict('repair calls must precede source sequence')
            repair_calls.append(call)
            continue
        try:
            child = read_child_capture(call, objects)
        except FileNotFoundError:
            terminal = evidence['terminal_error']
            if terminal is None or terminal['call'] != call or result.outcome in COMPLETE:
                raise Conflict('missing result cannot authorize completed member')
            missing_calls.append(call)
            retained_body = objects.read(call['result_ref'].rsplit('/', 1)[0] + '/terminal.json')
            retained = parse_json(retained_body)
            actual = RunContext.from_mapping(retained['context'])
            _context_matches(template, actual)
            if retained_body != canonical_json(to_mapping_value(retained)) or retained['terminal_error'] != terminal:
                raise Conflict('terminal error differs from retained unfinished Attempt capture')
            intent = {'context': actual.to_mapping(), 'intent': call['intent']} if actual.command in ('transform', 'publish') else call['intent']
            if objects.read(call['result_ref'].rsplit('/', 1)[0] + '/command.json') != canonical_json(to_mapping_value(intent)):
                raise Conflict('terminal command differs from unfinished context')
            continue
        if missing_calls:
            raise Conflict('terminal unfinished child cannot precede successful child')
        if call['step_id'] != child.context.command + '-' + value['member_id']:
            raise Conflict('member child step differs from exact member namespace')
        checked.append((call, child))
    if tuple(call['result_ref'] for call, child in checked) != result.child_refs:
        raise Conflict('receipt child result references differ')
    commands = tuple(child.context.command for call, child in checked)
    if commands not in ((), ('collect',), ('collect', 'transform'), ('collect', 'transform', 'publish')):
        raise Conflict('member child order differs')
    expected_gaps = [g.to_mapping() for call, child in checked for g in child.gaps]
    terminal = evidence['terminal_error']
    if terminal is not None:
        if len(missing_calls) != 1 or terminal['call'] != missing_calls[0]:
            raise Conflict('terminal error lacks exact unfinished child')
        expected_command = ('collect', 'transform', 'publish')[len(checked)] if len(checked) < 3 else None
        if missing_calls[0]['context']['command'] != expected_command or missing_calls[0]['step_id'] != expected_command + '-' + value['member_id']:
            raise Conflict('terminal child breaks member chain')
        expected_input = value['member_ref'] if not checked else result.snapshot_ref if len(checked) == 1 else result.transformed_ref
        if missing_calls[0]['input_ref'] != expected_input or terminal['resumable'] or terminal['repair_pending']:
            raise Conflict('resumable or unrelated unfinished child cannot create receipt')
        if terminal['exit'] != exit_code(terminal['outcome']):
            raise Conflict('terminal exit differs from registered outcome')
        expected_gaps.extend(terminal['gaps'])
        exit_code(terminal['outcome'])
        if result.outcome != terminal['outcome']:
            raise Conflict('terminal source outcome differs from exact child failure')
    elif checked and result.outcome != _member_outcome(checked[-1][1]):
        raise Conflict('member outcome differs from final checked child')
    if [g.to_mapping() for g in result.gaps] != expected_gaps:
        raise Conflict('member omitted or invented child gaps')
    if not checked and terminal is None:
        raise Conflict('member has no checked source operation')
    raw = checked[0][1] if checked else None
    parsed = checked[1][1] if len(checked) >= 2 else None
    published = checked[2][1] if len(checked) >= 3 else None
    if raw is not None and (checked[0][0]['input_ref'] != value['member_ref'] or
            result.snapshot_ref != raw.snapshot_workset_ref or result.downloaded != (raw.snapshot_workset_ref is not None)):
        raise Conflict('member collection/snapshot identity differs')
    if raw is None and (result.snapshot_ref is not None or result.downloaded):
        raise Conflict('member invents collection progress')
    if parsed is None and (result.transformed_ref is not None or result.transformed):
        raise Conflict('member invents transform progress')
    if parsed is not None and (parsed.input_ref != result.snapshot_ref or
            parsed.transformed_workset_ref != result.transformed_ref or
            result.transformed != bool(parsed.transformed or parsed.unchanged)):
        raise Conflict('member transform identity/progress differs')
    if parsed is not None and raw.outcome not in COMPLETE or published is not None and parsed.outcome not in COMPLETE:
        raise Conflict('member continued after non-complete child')
    for child in (parsed, published):
        if child is not None and (child.context.parser_version, child.context.schema_version) != (result.parser_version, result.schema_version):
            raise Conflict('member processing versions differ from exact child context')
    expected_quarantine = bool(parsed and parsed.quarantined and not result.transformed)
    if raw is not None and raw.outcome == 'quarantined' and raw.snapshot_workset_ref is None:
        expected_quarantine = True
    if result.quarantined != expected_quarantine:
        raise Conflict('transport body retention cannot create source quarantine')
    if published is not None and (published.input_ref != result.transformed_ref or published.quarters != result.quarters):
        raise Conflict('member publication input/quarter outcomes differ')
    if published is None and result.quarters:
        raise Conflict('member invents publication outcomes')
    complete = evidence['completion']
    if member_status(result.outcome) == 'complete':
        if complete is None or complete['member'] != value:
            raise Conflict('complete member lacks exact captured evidence')
        validate_capture(complete, objects)
        if (complete['observation']['parser_version'], complete['observation']['schema_version']) != (result.parser_version, result.schema_version):
            raise Conflict('member capture processing versions differ')
        from ..models import Snapshot
        from ..worksets import make_snapshot_workset, decode_source_workset
        source_projection = decode_source_workset(objects.read(value['member_ref']))
        exact = make_snapshot_workset(source_projection, (Snapshot.from_mapping(complete['snapshot']),))
        actual = decode_snapshot_workset(objects.read(result.snapshot_ref))
        if exact != actual:
            raise Conflict('member capture differs from exact pinned snapshot workset')
        captures = {c['quarter']: c for c in complete['quarters']}
        if set(captures) != {q.quarter for q in result.quarters}:
            raise Conflict('member omitted affected publication quarter')
        for quarter in result.quarters:
            captured = captures[quarter.quarter]
            if (quarter.generation_id, quarter.manifest_ref) != (captured['generation_id'], captured['manifest_ref']):
                raise Conflict('member quarter differs from immutable capture')
    elif complete is not None:
        raise Conflict('unresolved member invents complete capture')
    if len(evidence['resolutions']) != len(repair_calls):
        raise Conflict('repair prefix lacks exact resolution')
    resolution_calls = []
    for resolution in evidence['resolutions']:
        validate_resolution_capture(resolution, objects)
        objects.verify(resolution['ref'], resolution['sha256'], resolution['bytes'])
        resolution_calls.append(parse_json(objects.read(resolution['ref']))['call'])
    if resolution_calls != repair_calls:
        raise Conflict('repair resolution belongs to another checked prefix')
