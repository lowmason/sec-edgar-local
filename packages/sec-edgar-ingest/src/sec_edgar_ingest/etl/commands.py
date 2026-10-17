"""Storage-only ETL commands and separate, immutable ETL result commits."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from ..config import Settings, pin_context
from ..models import Error, RunContext, canonical_json, error_text, parse_json, safe_relative_path
from ..results import log_event, result_path
from ..state import AcquisitionState, attempt_key
from ..worksets import decode_snapshot_workset, encode_workset
from ..storage.contracts import BoundaryObserver, CAS_ATTEMPTS, Conflict, ObjectStore, StateStore, observe
from .contracts import (EtlResult, PublicationResult, decode_transformed,
                        processing_key, transformed_ref)
from .publication import PublicationRepairError, publish_quarter
from .reader import capture_from_pointer, validated_manifest
from .parser import supported_parser, SCHEMA_VERSION
from .state import EtlState
from .transform import transform_workset

WORKSET_REFS = {kind: re.compile(r'worksets/sec/' + kind + r'/sha256=[0-9a-f]{64}/workset\.json\Z')
                for kind in ('snapshot', 'transformed')}
FAILURE_PRIORITY = ('internal_error', 'state_conflict', 'publication_conflict', 'invalid_source',
                    'quarantined', 'incomplete', 'awaiting_approval')
ETL_OUTCOMES = frozenset(('success', 'unchanged', 'no_new_sources', *FAILURE_PRIORITY))
QUARTER_OUTCOMES = frozenset(('published', 'unchanged', 'awaiting_approval', 'publication_conflict',
                              'state_conflict', 'internal_error', 'invalid_source', 'incomplete'))


def validate_workset_ref(path: str, kind: str) -> None:
    if WORKSET_REFS[kind].fullmatch(path) is None:
        raise ValueError(f'workset must name the exact immutable {kind}-workset object path')


def _aggregate(outcomes, *, changed: bool) -> str:
    for outcome in FAILURE_PRIORITY:
        if outcome in outcomes:
            return outcome
    return 'success' if changed else 'unchanged'


def _validate_result(result: EtlResult) -> None:
    context = result.context
    if context.command not in ('transform', 'publish') or result.outcome not in ETL_OUTCOMES:
        raise ValueError('invalid ETL result command or outcome')
    for name in ('run_id', 'execution_id', 'attempt_id'):
        if '/' in safe_relative_path(getattr(context, name), name):
            raise ValueError('ETL correlation IDs must be single path segments')
    settings = Settings.from_mapping(context.to_mapping()['effective_config'])
    if context.pinned_on is None or pin_context(settings, context, context.pinned_on)[0] != context:
        raise ValueError('ETL result requires its exact pinned effective configuration')
    supported_parser(context.parser_version, fixture=settings.storage.backend == 'local-fixture')
    if result.started_at != context.started_at:
        raise ValueError('ETL result must preserve its exact context start')
    validate_workset_ref(result.input_ref, 'snapshot' if context.command == 'transform' else 'transformed')
    if result.transformed_workset_ref is not None:
        validate_workset_ref(result.transformed_workset_ref, 'transformed')
    if context.command == 'transform':
        _validate_transform_result(result)
    else:
        _validate_publication_result(result)


def _validate_transform_result(result: EtlResult) -> None:
    if result.quarters or result.published or result.awaiting_approval or result.transformed_workset_ref is None:
        raise ValueError('transform result cannot claim publication')
    if any(gap.code not in ('transform_failed', 'state_conflict') or gap.source_id is None for gap in result.gaps):
        raise ValueError('invalid transform source failure')
    if result.failed != len(result.gaps) or result.quarantined != sum(gap.code == 'transform_failed' for gap in result.gaps):
        raise ValueError('transform failure counters disagree')
    expected = ('state_conflict' if any(gap.code == 'state_conflict' for gap in result.gaps)
                else 'incomplete' if result.gaps and result.transformed + result.unchanged
                else 'invalid_source' if result.gaps else 'success' if result.transformed else 'unchanged')
    if result.outcome != expected:
        raise ValueError('transform aggregate outcome disagrees')


def _validate_quarter(quarter: PublicationResult, gaps: tuple[Error, ...]) -> None:
    if quarter.conflicts > CAS_ATTEMPTS or quarter.outcome not in QUARTER_OUTCOMES:
        raise ValueError('unsupported publication outcome or conflict count')
    base = f'curated/sec/filing_index/year={quarter.quarter[:4]}/quarter={quarter.quarter[-1]}/generation='
    if quarter.outcome in ('published', 'unchanged'):
        if (quarter.generation_id is None or quarter.manifest_ref != base + quarter.generation_id + '/manifest.json'
                or quarter.candidate_ref is not None):
            raise ValueError('committed result requires its exact manifest capture')
    elif quarter.outcome == 'awaiting_approval':
        if (quarter.generation_id is not None or quarter.manifest_ref is not None or quarter.candidate_ref is None
                or re.fullmatch(r'worksets/sec/candidates/sha256=[0-9a-f]{64}/candidate\.json', quarter.candidate_ref) is None):
            raise ValueError('gate result requires only its candidate reference')
    else:
        matching = [gap for gap in gaps if gap.code == quarter.outcome and gap.details.get('quarter') == quarter.quarter]
        if len(matching) != 1:
            raise ValueError('failed quarter requires one matching error gap')
        if quarter.generation_id is not None or quarter.candidate_ref is not None:
            raise ValueError('failed publication cannot claim a capture or gate')
        if quarter.manifest_ref is not None and (quarter.outcome != 'publication_conflict'
                or re.fullmatch(re.escape(base) + r'[0-9a-f]{64}/manifest\.json', quarter.manifest_ref) is None):
            raise ValueError('only publication conflicts may retain attempted manifest evidence')
        if quarter.outcome == 'publication_conflict' and (
                matching[0].details.get('attempted_manifest_ref') != quarter.manifest_ref
                or matching[0].details.get('conflicts') != quarter.conflicts):
            raise ValueError('conflict evidence differs from its quarter result')


def _validate_publication_result(result: EtlResult) -> None:
    if result.transformed_workset_ref != result.input_ref or result.transformed or result.quarantined:
        raise ValueError('publish result counters or transformed reference disagree')
    for quarter in result.quarters:
        _validate_quarter(quarter, result.gaps)
    counts = Counter(quarter.outcome for quarter in result.quarters)
    if (result.published, result.unchanged, result.awaiting_approval) != (
            counts['published'], counts['unchanged'], counts['awaiting_approval']):
        raise ValueError('publication counters disagree with quarter outcomes')
    failed_quarters = len(result.quarters) - result.published - result.unchanged - result.awaiting_approval
    if result.quarters:
        if len(result.gaps) != failed_quarters:
            raise ValueError('publication gaps must match failed quarters exactly')
    elif result.gaps and not (len(result.gaps) == 1 and result.gaps[0].code == 'incomplete'
                             and result.gaps[0].details.get('workset_ref') == result.input_ref):
        raise ValueError('only a partial-workset refusal may have an unassigned publication gap')
    if result.failed != len(result.gaps):
        raise ValueError('publication failed counter disagrees with gaps')
    expected = _aggregate([quarter.outcome for quarter in result.quarters] + [gap.code for gap in result.gaps],
                          changed=bool(result.published))
    if result.outcome != expected:
        raise ValueError('publication aggregate outcome disagrees')


def read_etl_result(path: str, objects: ObjectStore) -> EtlResult:
    safe_relative_path(path, 'ETL result path')
    body = objects.read(path)
    result = EtlResult.from_mapping(parse_json(body))
    _validate_result(result)
    if result_path(result.context) != path or canonical_json(result.to_mapping()) != body:
        raise Conflict('ETL result bytes or path differ from canonical command identity')
    return result


def write_etl_result(result: EtlResult, objects: ObjectStore, acquisition: AcquisitionState, *,
                     observer: BoundaryObserver | None = None) -> str:
    _validate_result(result)
    row = acquisition.store.get('Attempt', attempt_key(result.context))
    if row is None or row.to_mapping()['value']['context'] != result.context.to_mapping():
        raise Conflict('ETL result requires exact begun Attempt')
    saved = row.to_mapping()['value']['result']
    if saved is not None and saved != result.to_mapping():
        raise Conflict('ETL result differs from completed Attempt')
    path = result_path(result.context)
    objects.put_once(path, canonical_json(result.to_mapping()))
    observe(observer, 'etl_result.after_object')
    acquisition.finish_attempt(result)
    observe(observer, 'etl_result.after_attempt')
    return path


def run_transform(snapshot_ref: str, context: RunContext, settings: Settings, objects: ObjectStore,
                  store: StateStore, *, force: bool = False, observer: BoundaryObserver | None = None) -> EtlResult:
    if context.command != 'transform':
        raise ValueError('transform requires a transform command context')
    validate_workset_ref(snapshot_ref, 'snapshot')
    snapshot_body = objects.read(snapshot_ref)
    snapshots = decode_snapshot_workset(snapshot_body)
    if (snapshot_ref != f'worksets/sec/snapshot/sha256={snapshots.workset_id}/workset.json'
            or encode_workset(snapshots) != snapshot_body):
        raise Conflict('snapshot workset bytes or path differ from canonical identity')
    accepted = {row.value['processing_key'] for row in store.scan('Processing', {})}
    workset = transform_workset(snapshot_ref, context, settings, objects, EtlState(store),
                                AcquisitionState(store), force=force, observer=observer)
    unchanged = sum(not force and processing_key(ref.source.source_id, ref.snapshot.sha256,
                    ref.parser_version, ref.schema_version) in accepted for ref in workset.observations)
    transformed = len(workset.observations) - unchanged
    outcome = ('state_conflict' if any(gap.code == 'state_conflict' for gap in workset.failures)
               else 'incomplete' if workset.failures and workset.observations
               else 'invalid_source' if workset.failures else 'success' if transformed else 'unchanged')
    for ref in workset.observations:
        log_event(context, 'source_transformed', {'source_id': ref.source.source_id, 'raw_sha256': ref.snapshot.sha256,
                  'observation_ref': ref.manifest_ref, 'transformed_workset_ref': transformed_ref(workset)})
    for failure in workset.failures:
        log_event(context, 'source_transform_failed', {'source_id': failure.source_id,
                  'raw_sha256': failure.details.get('raw_sha256'), 'input_ref': snapshot_ref,
                  'transformed_workset_ref': transformed_ref(workset), 'error': failure.to_mapping()})
    return EtlResult(context, outcome, snapshot_ref, transformed_ref(workset), transformed, 0, unchanged,
                     sum(gap.code != 'state_conflict' for gap in workset.failures), 0, len(workset.failures), (),
                     workset.failures, context.started_at, max(context.started_at, datetime.now(timezone.utc)))


class PublicationRepairPending(RuntimeError):
    """Keep the exact command resumable while retaining every quarter outcome."""

    def __init__(self, quarters, gaps, repair_errors):
        super().__init__('committed publication requires ancillary repair; retry the exact invocation')
        self.details = {'quarters': [quarter.to_mapping() for quarter in quarters],
                        'gaps': [gap.to_mapping() for gap in gaps],
                        'repair_errors': repair_errors}


def _affected_quarters(observations, objects, store):
    quarters = {quarter for ref in observations for quarter in ref.quarter_counts}
    sources = {ref.source.source_id for ref in observations}
    if sources:
        # Receipts can be absent after a committed pointer, so discovery uses authority.
        for pointer in store.scan('QuarterPublication', {}):
            capture = capture_from_pointer(pointer)
            manifest = validated_manifest(capture, objects)
            if manifest.source_fingerprint != pointer.value['source_fingerprint']:
                raise Conflict('pointer source fingerprint differs from captured manifest')
            if any(ref.source.source_id in sources for ref in manifest.sources):
                quarters.add(capture.quarter)
    return sorted(quarters)


def run_publish(transformed_workset_ref: str, context: RunContext, settings: Settings,
                objects: ObjectStore, store: StateStore, *, observer: BoundaryObserver | None = None) -> EtlResult:
    if context.command != 'publish' or context.pinned_on is None or pin_context(settings, context, context.pinned_on)[0] != context:
        raise ValueError('publish requires its exact pinned effective configuration')
    supported_parser(context.parser_version, fixture=settings.storage.backend == 'local-fixture')
    if context.schema_version != SCHEMA_VERSION:
        raise ValueError('unsupported ETL schema version')
    if datetime.now(timezone.utc) >= context.deadline:
        raise TimeoutError('publication command deadline exceeded')
    validate_workset_ref(transformed_workset_ref, 'transformed')
    workset = decode_transformed(objects.read(transformed_workset_ref))
    if transformed_ref(workset) != transformed_workset_ref:
        raise Conflict('transformed workset path differs from payload identity')
    if (workset.context.parser_version, workset.context.schema_version) != (context.parser_version, context.schema_version):
        raise Conflict('publish versions differ from the immutable transformed workset')
    quarters, gaps, repair_errors = [], [], []
    if not workset.complete:
        gaps.append(Error('incomplete', 'partial transformed workset is not publishable', False, None,
                          {'workset_ref': transformed_workset_ref, 'failures': [gap.to_mapping() for gap in workset.failures]}))
    else:
        state = EtlState(store)
        for quarter in _affected_quarters(workset.observations, objects, store):
            try:
                result = publish_quarter(quarter, workset.observations, context, settings, objects, state, observer=observer)
            except PublicationRepairError as error:
                result = error.result
                repair_errors.append({'quarter': quarter, 'type': type(error.error).__name__,
                                      'message': str(error.error)})
            except Exception as error:
                outcome = ('state_conflict' if isinstance(error, (Conflict, OSError)) else
                           'invalid_source' if isinstance(error, ValueError) else 'internal_error')
                result = PublicationResult(quarter, outcome, None, None, None, 0)
                gaps.append(Error(outcome, error_text(error), False, None, {'quarter': quarter, 'type': type(error).__name__}))
            else:
                if result.outcome == 'publication_conflict':
                    gaps.append(Error('publication_conflict', 'bounded quarter publication did not commit', True, None,
                                      {'quarter': quarter, 'conflicts': result.conflicts,
                                       'attempted_manifest_ref': result.manifest_ref}))
            quarters.append(result)
            log_event(context, 'quarter_publication', result.to_mapping())
    if repair_errors:
        raise PublicationRepairPending(quarters, gaps, repair_errors)
    counts = Counter(result.outcome for result in quarters)
    outcome = _aggregate([result.outcome for result in quarters] + [gap.code for gap in gaps], changed=bool(counts['published']))
    return EtlResult(context, outcome, transformed_workset_ref, transformed_workset_ref, 0,
                     counts['published'], counts['unchanged'], 0, counts['awaiting_approval'], len(gaps), tuple(quarters),
                     tuple(gaps), context.started_at, max(context.started_at, datetime.now(timezone.utc)))
