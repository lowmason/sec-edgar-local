from collections.abc import Mapping
from ..config import Settings
from ..models import RunContext, to_mapping_value
from datetime import datetime, timezone
import hashlib
from ..models import Error, Source, canonical_json, error_text, parse_json
from ..collection import HALTING_OUTCOMES
from ..state import AcquisitionState
from ..storage.contracts import Conflict, observe
from ..discovery import quarter_span
from ..etl.reader import capture_from_pointer, capture_quarter, validated_manifest
from ..etl.state import EtlState
from .contracts import MemberResult, WorkflowResult, FATAL, summarize, workflow_path
from .checked import ChildUnfinished, Dispatcher
from .completion import evaluate_member, capture_member_provenance, capture_parent_provenance, validate_parent_provenance
from .legacy import bootstrap_legacy
from .members import SourceDownloads, WorkflowMembers
from .processing import process_member, validate_member_evidence
from .provenance import project_member, read_parent, read_member, transfer_binding, immutable
from .results import freeze_selection


def reuse_exact_binding(value: Mapping, store, objects) -> tuple[Error, ...]:
    acquisition = AcquisitionState(store)
    member = read_member(value, store, objects)
    identity = value['source']['source_id']
    if acquisition.binding(member.workset_id, identity) is not None or member.acquisition_mode == 'refresh':
        return ()
    gaps = []
    source = acquisition.get_source(identity)
    if source is None:
        return ()
    try:
        if source.value['needs_acquisition']:
            return ()
    except (ValueError, KeyError, TypeError) as error:
        return (Error('legacy_member_unresolved', 'source reuse evidence is corrupt: ' + error_text(error),
                      False, identity, {'member_id': value['member_id']}),)
    candidates = {}
    verified, _ = WorkflowMembers(store, objects).inventory()
    # select_work has already retained inventory gaps; reuse cannot hide them.
    for other in verified:
        if other['source'] != value['source']:
            continue
        try:
            pin = acquisition.binding(other['member_id'], identity)
            if pin is None:
                continue
            snapshot = acquisition.snapshot(identity, pin.snapshot_sha256)
            objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
            candidates[snapshot.sha256] = snapshot
        except (ValueError, OSError, Conflict, KeyError, TypeError) as error:
            gaps.append(Error('legacy_member_unresolved', 'retained reuse pin is corrupt: ' + error_text(error),
                              False, identity, {'member_id': other['member_id']}))
    if len(candidates) != 1:
        return tuple(gaps)  # Ordinary checked collection establishes its exact binding.
    # Keep winner refusal outside candidate isolation; never overwrite a divergent binding.
    transfer_binding(value, next(iter(candidates.values())), store, objects)
    return tuple(gaps)


def run_workflow(context: RunContext, settings: Settings, intent: Mapping, dispatcher: Dispatcher,
                 store, objects, observer=None) -> WorkflowResult:
    registry, acquisition = WorkflowMembers(store, objects), AcquisitionState(store)
    selection_path = workflow_path(context).rsplit('/', 1)[0] + '/selection.json'
    try:
        selection_body = objects.read(selection_path)
    except FileNotFoundError:
        selection = select_work(context, settings, intent, dispatcher, store, objects)
        selection = freeze_selection(context, selection, store, objects)
        observe(observer, 'workflow.after_selection')
    else:
        selection = freeze_selection(context, parse_json(selection_body), store, objects)
    results, receipt_descriptors, evidences = [], [], []
    halted = selection['halted']
    for job in selection['jobs']:
        value = job['member']
        receipt_path = workflow_path(context).rsplit('/', 1)[0] + '/members/' + value['member_id'] + '/result.json'
        try:
            body = objects.read(receipt_path)
        except FileNotFoundError:
            body = None
        if body is not None:
            result, saved_context, evidence, body = registry._read_receipt(receipt_path)
            if saved_context != context or evidence['member'] != value:
                raise Conflict('saved member receipt changes frozen context/projection')
            descriptor = registry._descriptor(result, context, body)
            key = hashlib.sha256(canonical_json(to_mapping_value([context.run_id, context.command,
                context.attempt_id, result.member_id, result.parser_version, result.schema_version]))).hexdigest()
            # Frozen provenance and the checked receipt authorize historical index repair.
            immutable(store, 'WorkflowMemberResult', key, descriptor)
        elif halted or datetime.now(timezone.utc) >= context.deadline:
            result = MemberResult(value['member_id'], Source.from_mapping(value['source']), value['parent_ref'],
                None, None, (), 'pending', False, False, False, (),
                (Error('workflow_deferred', 'halt/deadline left source undispatched', True,
                       value['source']['source_id'], {}),), context.parser_version, context.schema_version)
            descriptor = evidence = None  # Frozen selection is the undispatched-work authority.
        else:
            processed = process_member(value, context, dispatcher, store, objects, observer)
            result = processed.result
            evidence = parse_json(canonical_json(to_mapping_value(processed.evidence)))
            descriptor = registry.record(result, context, evidence)
            observe(observer, 'workflow.after_member_receipt')
        results.append(result)
        receipt_descriptors.append(descriptor)
        evidences.append(evidence)
        halted = halted or result.outcome in FATAL or any(gap.code in HALTING_OUTCOMES for gap in result.gaps)
    gaps = [Error.from_mapping(value) for value in selection['gaps']]
    gaps.extend(baseline_gaps(selection, tuple(results), evidences, store, objects))
    gaps.extend(source_revert_gaps(tuple(results), store, objects))
    selected_ids = {result.source.source_id for result in results}
    already = tuple(sorted({capture['member']['source']['source_id'] for capture in selection['already_complete']} - selected_ids))
    outcome, counts = summarize(tuple(results), tuple(gaps), selection['discovered_sources'],
        selection['unresolved_before'], context.command, already)
    after = acquisition.daily_boundary()
    selection_body = objects.read(selection_path)
    child_calls = [] if selection['discovery_call'] is None else [selection['discovery_call']]
    captures = list(selection['already_complete'])
    resolutions = []
    for evidence in evidences:
        if evidence is None:
            continue
        child_calls.extend(evidence['calls'])
        if evidence['completion'] is not None:
            captures.append(evidence['completion'])
        resolutions.extend(evidence['resolutions'])
    report_intent = {'invocation': dict(intent),
        'selection': {'ref': selection_path, 'sha256': hashlib.sha256(selection_body).hexdigest(), 'bytes': len(selection_body)},
        'discovered_sources': selection['discovered_sources'], 'unresolved_before': selection['unresolved_before'],
        'already_complete_sources': list(already), 'member_receipts': receipt_descriptors,
        'completion_captures': captures, 'child_calls': child_calls, 'repair_resolutions': resolutions}
    return WorkflowResult('sec-workflow-result-v1', context, report_intent, selection['parent_ref'],
        tuple(selection['requested_quarters']), tuple(selection['directories']), tuple(results), tuple(gaps),
        selection['boundary_before'], after.isoformat() if after else None, outcome, counts,
        max(context.started_at, datetime.now(timezone.utc)).isoformat())

def select_work(context: RunContext, settings: Settings, intent: Mapping, dispatcher: Dispatcher,
                store, objects) -> Mapping:
    acquisition, registry = AcquisitionState(store), WorkflowMembers(store, objects)
    before = acquisition.daily_boundary()
    gaps = list(bootstrap_legacy(store, objects))
    retained, registry_gaps = registry.inventory()
    gaps.extend(registry_gaps)
    pending_before, finished, unresolved, corrupt = [], [], [], set()
    for value in retained:
        try:
            completed = registry.completed(value, context.parser_version, context.schema_version)
        except (ValueError, OSError, Conflict, KeyError, TypeError) as error:
            gaps.append(Error('legacy_member_unresolved', 'retained completion receipt is corrupt: ' + error_text(error),
                              False, value['source']['source_id'], {'member_id': value['member_id']}))
            corrupt.add(value['member_id'])
            completed = None
        if completed is not None:
            finished.append(value)
            continue
        evaluated = evaluate_member(value, context.parser_version, context.schema_version, store, objects)
        pending_before.append(value)
        if not evaluated.complete:
            unresolved.append((value, evaluated))
    mode = 'daily' if context.command == 'daily' else 'quarterly'
    flags = ('--mode', mode, '--discovery-id', 'workflow-' + context.command + '-' + context.run_id)
    if context.command == 'reconcile':
        flags += ('--refresh',)  # Reconciliation differs only by re-fetching every listed source.
    discovery_call = discovery_error = parent_ref = parent = None
    halted = False
    try:
        child = dispatcher.execute('discover', 'discover', settings, flags)
        discovery_call = dict(child.call)
        parent_ref = child.result.source_workset_ref
        if parent_ref is not None:
            parent = read_parent(parent_ref, store, objects)
        gaps.extend(child.result.gaps)
        for gap in child.result.gaps:
            normalized = HALTING_OUTCOMES.get(gap.code)
            if normalized is not None:
                gaps.append(Error(normalized, 'shared acquisition halt: ' + gap.message, gap.retryable,
                                  gap.source_id, {'cause': gap.to_mapping()}))
        halted = child.result.outcome in FATAL or any(gap.code in HALTING_OUTCOMES for gap in child.result.gaps)
    except ChildUnfinished as error:
        discovery_call = dict(error.call)
        discovery_error = Error(error.outcome, 'discovery has no durable source result', False, None, error.details)
        gaps.extend(error.gaps)
        gaps.append(discovery_error)
        halted = True
    current = []
    if parent is not None:
        for source in parent.members:
            value = project_member(parent_ref, source.source_id, store, objects)
            gaps.extend(reuse_exact_binding(value, store, objects))
            current.append(value)
    # A later completed download of the same source supersedes an older member that only awaits publication.
    # Repair obligations and corrupt evidence (state_conflict gaps) stay exact, so they still fail the run.
    # So does this attempt's own discovery: a retry of a run reuses its discovery session and member ids,
    # and every discovered member must be selected (results._validate_selection).
    discovered = {value['member_id'] for value in current}
    eligible = [value for value, evaluated in unresolved
                if value['member_id'] not in discovered and not evaluated.obligations
                and {gap.code for gap in evaluated.gaps} == {'publication_pending'}]
    superseded = []
    if eligible:
        downloads = SourceDownloads(retained, finished, {value['source']['source_id']: value['source']
                                                         for value in eligible}, store)
        # Unreadable download evidence keeps every hold of its source; other sources still proceed.
        for value, error in downloads.unreadable:
            if value['member_id'] not in corrupt:
                gaps.append(Error('legacy_member_unresolved', 'retained download evidence is corrupt: ' + error_text(error),
                                  False, value['source']['source_id'], {'member_id': value['member_id']}))
        superseded = [entry for value in eligible for entry in (downloads.supersession(value),) if entry is not None]
    dropped = {entry['member']['member_id'] for entry in superseded}
    unresolved_ids_before = {value['source']['source_id'] for value, _ in unresolved if value['member_id'] not in dropped}
    combined = {value['member_id']: value for value in (*pending_before, *current) if value['member_id'] not in dropped}
    selected, complete = [], []
    for value in sorted(combined.values(), key=lambda v: (v['source']['period'], v['source']['source_id'], v['member_id'])):
        evaluation = evaluate_member(value, context.parser_version, context.schema_version, store, objects)
        if evaluation.complete:
            complete.append(evaluation.capture)
        else:
            selected.append(value)
    # Preserve every completed exact unit; reducer counts exclude selected source IDs.
    end = intent['pinned_end_quarter']
    requested = () if context.command == 'daily' else quarter_span(settings.backfill.start_quarter, end)
    for quarter in requested:
        if parent is None or not any(source.kind == 'quarterly' and source.period == quarter for source in parent.members):
            gaps.append(Error('baseline_source_missing', 'requested quarter has no validated source', True,
                              None, {'quarter': quarter}))
    session_row = acquisition.discovery_session('workflow-' + context.command + '-' + context.run_id)
    session = None if session_row is None else session_row.to_mapping()['value']
    parent_provenance = None if parent_ref is None else capture_parent_provenance(parent_ref, store, objects)
    if parent_provenance is not None:
        session = parent_provenance['discovery']['session']
    required = [] if session is None else session['frozen']['units']
    values = sorted(selected, key=lambda v: (v['source']['period'], v['source']['source_id'], v['member_id']))
    return {'format_version': 'sec-workflow-selection-v2', 'context': context.to_mapping(),
        'invocation': dict(intent), 'members': values, 'jobs': [{'member': value, 'aliases': [value]} for value in selected],
        'member_provenance': [capture_member_provenance(value, store, objects) for value in values],
        'already_complete': complete,
        'superseded': sorted(superseded, key=lambda entry: (entry['member']['source']['period'],
                             entry['member']['source']['source_id'], entry['member']['member_id'])),
        'discovery_call': discovery_call,
        'discovery_error': None if discovery_error is None else discovery_error.to_mapping(),
        'parent_ref': parent_ref, 'parent_provenance': parent_provenance,
        'discovery_session': session, 'required_units': required,
        'requested_quarters': list(requested),
        'directories': [] if parent is None else [directory.to_mapping() for directory in parent.directories],
        'halted': halted, 'boundary_before': before.isoformat() if before else None,
        'gaps': [gap.to_mapping() for gap in gaps],
        'discovered_sources': len(current),
        'unresolved_before': len(unresolved_ids_before)}


def baseline_gaps(selection, results, evidences, store, objects) -> tuple[Error, ...]:
    gaps = []
    parent = (None if selection['parent_ref'] is None else
              validate_parent_provenance(selection['parent_provenance'], objects))
    independent = (bool(selection['gaps']) or selection['halted'] or parent is None
                   or not parent.discovery_complete
                   or {unit['url'] for unit in selection['required_units']} != {d.url for d in parent.directories})
    for result, evidence in zip(results, evidences, strict=True):
        if evidence is not None:
            validate_member_evidence(result, evidence, objects)
        elif result.quarantined:
            raise Conflict('baseline quarantine attribution lacks checked stored receipt')
    refused = {result.source.source_id for result in results if result.quarantined and result.outcome not in ('pending', 'deferred')}
    by_source = {value['source']['source_id']: value for value in selection['members']}
    for quarter in selection['requested_quarters']:
        if capture_quarter(quarter, objects, EtlState(store)) is not None:
            continue
        causes = sorted(source_id for source_id, value in by_source.items()
                        if value['source']['kind'] == 'quarterly' and value['source']['period'] == quarter)
        details = {'quarter': quarter}
        if not independent and causes and set(causes) <= refused:
            # Earlier validators establish exact listings/selection/refusal, not this marker alone.
            details.update(coverage_cause='selected_source_quarantine', source_ids=causes)
        gaps.append(Error('baseline_publication_missing', 'requested baseline quarter lacks readable generation',
                          True, None, details))
    return tuple(gaps)


def source_revert_gaps(results, store, objects) -> tuple[Error, ...]:
    """Report sources whose newest download repeats older bytes that the active generation supersedes.

    Identical bytes keep their first receipt, so receipt-ordered selection keeps the newer
    snapshot and the member publishes unchanged; without this gap the run would read as reconciled.
    """
    acquisition, state, found, manifests = AcquisitionState(store), EtlState(store), {}, {}
    for result in results:
        quarters = sorted({q.quarter for q in result.quarters if q.outcome in ('published', 'unchanged')})
        identity = result.source.source_id
        row = acquisition.get_source(identity) if quarters else None
        if row is None:
            continue
        value = row.to_mapping()['value']
        latest, observed = value['latest_downloaded_snapshot'], value['latest_received_at']
        if latest is None or observed is None:
            continue
        observed_at = datetime.fromisoformat(observed)
        first = acquisition.snapshot(identity, latest).received_at
        for quarter in quarters:
            pointer = state.pointer(quarter)
            if pointer is None:
                continue
            capture = capture_from_pointer(pointer)
            if capture.generation_id not in manifests:
                manifests[capture.generation_id] = validated_manifest(capture, objects)
            manifest = manifests[capture.generation_id]
            active = next((ref for ref in manifest.sources if ref.source.source_id == identity), None)
            if active is None or active.snapshot.sha256 == latest:
                continue
            if first < active.snapshot.received_at < observed_at:
                found[identity, quarter] = Error(
                    'source_reverted', 'newest download repeats older bytes that the active generation supersedes',
                    True, identity, {'quarter': quarter, 'observed_sha256': latest, 'observed_at': observed,
                                     'first_received_at': first.isoformat(),
                                     'active_sha256': active.snapshot.sha256,
                                     'active_received_at': active.snapshot.received_at.isoformat(),
                                     'generation_id': capture.generation_id})
    return tuple(found[key] for key in sorted(found))
