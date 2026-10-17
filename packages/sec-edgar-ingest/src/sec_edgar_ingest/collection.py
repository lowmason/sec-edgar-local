"""Promote original entities before accepting write-once workset member pins."""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from .config import Settings, pin_context
from .download import FetchError, HTTP_OK, RequestClient
from .models import (Binding, BodyReceipt, CommandResult, DAILY_ENVELOPE_VERSION, Error,
                     QUARTERLY_ENVELOPE_VERSION, RunContext, Snapshot, Source, SourceWorkset,
                     ValidatedBody, Permit, canonical_json, error_text, require_hash, require_text, safe_relative_path)
from .state import AcquisitionState
from .storage.contracts import Conflict, ObjectStore, OwnershipLost
from .validation import ValidationError, validate_envelope
from .worksets import decode_source_workset, encode_workset, make_snapshot_workset

HALTING_OUTCOMES = {
    'access_denied': 'access_blocked', 'run_halted': 'access_blocked',
    'ownership_lost': 'ownership_lost', 'policy_blocked': 'deferred',
    'retry_delay_unrepresentable': 'deferred', 'cooldown_unconfirmed': 'ownership_lost',
    'clock_uncertain': 'ownership_lost', 'sender_unverified': 'ownership_lost',
}


class Faults(Protocol):
    def hit(self, point: str) -> None: ...


def expected_envelope(source: Source) -> str:
    return QUARTERLY_ENVELOPE_VERSION if source.kind == 'quarterly' else DAILY_ENVELOPE_VERSION


def raw_path(source: Source, sha256: str) -> str:
    require_hash(sha256, 'snapshot hash')
    return f'raw/sec/indexes/kind={source.kind}/period={source.period}/sha256={sha256}/master.{source.representation}'


def _path_segment(value: str | None, label: str) -> str:
    if value is None:
        raise ValueError(label+' requires an explicit recorded identity')
    require_text(value, label)
    safe_relative_path(value, label)
    if '/' in value:
        raise ValueError(label+' must be one path segment')
    return value


def stage_receipt(objects: ObjectStore, context: RunContext, source: Source, receipt: BodyReceipt, *,
                  request_id: str | None = None) -> str:
    reservation = _path_segment(request_id, 'request_id')
    if receipt.url != source.canonical_url:
        raise Conflict('staging receipt differs from its canonical source URL')
    path = f'staging/sec/{context.run_id}/{context.attempt_id}/{source.source_id}/{reservation}/body'
    reference = objects.stage(path, receipt.temporary_path)
    objects.verify(reference, receipt.sha256, receipt.byte_count)
    objects.put_once(path.rsplit('/', 1)[0]+'/receipt.json', canonical_json({
        'receipt': receipt.to_mapping(), 'context': context.to_mapping(), 'source': source.to_mapping(),
        'request_id': reservation, 'temporary_ref': reference}))
    return reference


def snapshot_for(source: Source, body: ValidatedBody) -> Snapshot:
    receipt = body.receipt
    if receipt.url != source.canonical_url or (body.representation, body.envelope_version) != (
            source.representation, expected_envelope(source)):
        raise Conflict('validated body differs from its source representation or URL')
    return Snapshot(source.source_id, receipt.sha256, raw_path(source, receipt.sha256), receipt.byte_count,
                    receipt.received_at, receipt.headers, body.representation, body.envelope_version)


def _verify_snapshot(snapshot: Snapshot, source: Source, objects: ObjectStore) -> Snapshot:
    if (snapshot.source_id, snapshot.raw_path, snapshot.representation, snapshot.envelope_version) != (
            source.source_id, raw_path(source, snapshot.sha256), source.representation, expected_envelope(source)):
        raise Conflict('snapshot metadata differs from its exact source member')
    try:
        objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
    except (OSError, ValueError) as error:
        raise Conflict('referenced raw snapshot is missing or unreadable') from error
    return snapshot


def _receipt_attempt(state: AcquisitionState, context: RunContext, source: Source, receipt: BodyReceipt):
    rows = state.request_history(context, source.canonical_url)
    matching = [row.to_mapping()['value'] for row in rows if row.to_mapping()['value'].get('receipt') == receipt.to_mapping()]
    if len(matching) != 1 or matching[0]['context'] != context.to_mapping() or matching[0]['source_id'] != source.source_id:
        raise Conflict('receipt requires its exact finalized recorded transport reservation')
    row = matching[0]
    if rows[-1].value['request_id'] != row['request_id'] or row['ended_at'] is None:
        raise Conflict('receipt must match the latest finalized request for this context and URL')
    if row['permit'] is None or row['permit']['request_id'] != row['request_id']:
        raise Conflict('recorded request and permit identity disagree')
    return row


def _validated_saved_receipt(workset: SourceWorkset, source: Source, entry: dict[str, object],
                             state: AcquisitionState) -> BodyReceipt:
    checkpoint = {key: value for key, value in entry.items() if key != 'checkpoint_id'}
    if entry['checkpoint_id'] != hashlib.sha256(canonical_json(checkpoint)).hexdigest():
        raise Conflict('staged receipt checkpoint digest does not match its original metadata')
    if entry['workset_id'] != workset.workset_id or Source.from_mapping(entry['source']) != source:
        raise Conflict('staged receipt differs from its exact workset member')
    context = RunContext.from_mapping(entry['context'])
    settings = Settings.from_mapping(context.to_mapping()['effective_config'])
    if context.pinned_on is None:
        raise Conflict('staged receipt requires its actual context pinning date')
    pinned, _ = pin_context(settings, context, context.pinned_on)
    fields = ('image_digest', 'parser_version', 'schema_version', 'config_sha256')
    if pinned != context or any(getattr(context, field) != getattr(workset.context, field) for field in fields):
        raise Conflict('staged receipt has conflicting frozen versions/configuration')
    if context.effective_config != workset.context.effective_config:
        raise Conflict('staged receipt effective configuration differs from workset origin')
    receipt = BodyReceipt.from_mapping(entry['receipt'])
    request_id = _path_segment(entry['request_id'], 'request_id')
    expected = f'staging/sec/{context.run_id}/{context.attempt_id}/{source.source_id}/{request_id}/body'
    if (entry['temporary_ref'] != expected or receipt.url != source.canonical_url or not receipt.complete
            or receipt.status != HTTP_OK or receipt.error is not None):
        raise Conflict('staged receipt lacks exact original accepted transport metadata')
    request = entry['transport_attempt']
    permit = Permit.from_mapping(request['permit'])
    history = [row.to_mapping()['value'] for row in state.request_history(context, source.canonical_url)]
    if (request not in history or request['request_id'] != request_id or permit.request_id != request_id
            or request['context'] != context.to_mapping() or request['source_id'] != source.source_id
            or request['url'] != receipt.url or request['receipt'] != receipt.to_mapping()
            or request['outcome'] != 'received' or request['ended_at'] is None):
        raise Conflict('staged receipt lacks its exact finalized transport attempt and permit')
    return receipt


def _recover_saved_receipt(workset: SourceWorkset, source: Source, entry: dict[str, object],
                           state: AcquisitionState, objects: ObjectStore) -> BodyReceipt:
    receipt = _validated_saved_receipt(workset, source, entry, state)
    original_context = RunContext.from_mapping(entry['context'])
    _retain_attempt_failures(objects, state, original_context, source)
    return receipt


def _validate_retained(objects: ObjectStore, reference: str, source: Source, receipt: BodyReceipt,
                       settings: Settings) -> Snapshot:
    objects.verify(reference, receipt.sha256, receipt.byte_count)
    # ObjectStore exposes bytes rather than a local path; validate a bounded retained copy.
    with tempfile.TemporaryDirectory(prefix='sec-retained-envelope-') as directory:
        path = Path(directory)/'body'
        path.write_bytes(objects.read(reference))
        return snapshot_for(source, validate_envelope(source, replace(receipt, temporary_path=path), settings))


def recover_promoted(workset: SourceWorkset, source: Source, state: AcquisitionState,
                     objects: ObjectStore) -> Snapshot | None:
    promoted = state.promotion_receipt(workset.workset_id, source.source_id)
    staged = state.staged_receipt(workset.workset_id, source.source_id)
    entries = [] if staged is None else staged['receipts']
    settings = Settings.from_mapping(workset.context.to_mapping()['effective_config'])
    if promoted is not None:
        for value in promoted['snapshots']:
            snapshot = _verify_snapshot(Snapshot.from_mapping(value), source, objects)
            matching = [entry for entry in entries if entry['receipt']['sha256'] == snapshot.sha256
                        and entry['receipt']['byte_count'] == snapshot.byte_count
                        and entry['receipt']['received_at'] == snapshot.received_at.isoformat()
                        and entry['receipt']['headers'] == snapshot.to_mapping()['validators']]
            if not matching:
                raise Conflict('promotion checkpoint lacks its exact staged original receipt')
            receipt = _recover_saved_receipt(workset, source, matching[0], state, objects)
            validated = _validate_retained(objects, snapshot.raw_path, source, receipt, settings)
            if validated != snapshot:
                raise Conflict('promotion metadata differs from the exact validated original receipt')
        return state.remember_snapshot(Snapshot.from_mapping(promoted['snapshots'][0]))
    for entry in entries:
        receipt = _recover_saved_receipt(workset, source, entry, state, objects)
        reference = raw_path(source, receipt.sha256)
        try:
            snapshot = _validate_retained(objects, reference, source, receipt, settings)
        except FileNotFoundError:
            try:
                snapshot = _validate_retained(objects, entry['temporary_ref'], source, receipt, settings)
            except FileNotFoundError:
                continue
            objects.promote(entry['temporary_ref'], snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
        state.record_promotion(workset.workset_id, snapshot)
        return state.remember_snapshot(snapshot)
    return None


def collect_member(workset: SourceWorkset, source: Source, context: RunContext, settings: Settings,
                   client: RequestClient, state: AcquisitionState, objects: ObjectStore,
                   faults: Faults) -> Snapshot:
    _check_collector_context(workset, context, settings, client)
    if source not in workset.members:
        raise Conflict('collection member is not in the immutable source workset')
    pinned = state.binding(workset.workset_id, source.source_id)
    if pinned is not None:
        accepted = _verify_snapshot(state.snapshot(source.source_id, pinned.snapshot_sha256), source, objects)
        staged = state.staged_receipt(workset.workset_id, source.source_id)
        if staged is not None:
            for entry in staged['receipts']:
                if entry['receipt']['sha256'] == accepted.sha256:
                    _recover_saved_receipt(workset, source, entry, state, objects)
        return accepted
    snapshot = recover_promoted(workset, source, state, objects)
    if snapshot is None and workset.acquisition_mode == 'reuse_accepted':
        snapshot = state.reusable_snapshot(source, expected_envelope(source))
        if snapshot is not None:
            _verify_snapshot(snapshot, source, objects)
    if snapshot is None:
        receipt = client.fetch(source.canonical_url, context, source)
        _retain_attempt_failures(objects, state, context, source)
        validated = validate_envelope(source, receipt, settings)
        request = _receipt_attempt(state, context, source, receipt)
        temporary_ref = stage_receipt(objects, context, source, receipt, request_id=request['request_id'])
        snapshot = snapshot_for(source, validated)
        state.record_receipt(workset.workset_id, source, receipt, temporary_ref)
        faults.hit('after_receipt_checkpoint')
        objects.promote(temporary_ref, snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
        faults.hit('after_raw_promotion')
        state.record_promotion(workset.workset_id, snapshot)
        faults.hit('after_promotion_receipt')
    state.remember_snapshot(snapshot)
    faults.hit('after_snapshot_record')
    winner = state.bind_once(Binding(workset.workset_id, source.source_id, snapshot.sha256))
    faults.hit('after_binding')
    return _verify_snapshot(state.snapshot(source.source_id, winner.snapshot_sha256), source, objects)


def _retain_attempt_failures(objects, state, context, source, *, override=None):
    retained = 0
    for row in state.request_history(context, source.canonical_url):
        request = row.to_mapping()['value']
        if request['receipt'] is None:
            continue
        receipt = BodyReceipt.from_mapping(request['receipt'])
        error = Error.from_mapping(request['error']) if request['error'] is not None else receipt.error
        if override is not None and override[0].to_mapping() == receipt.to_mapping():
            error = override[1]
        if error is None or not receipt.byte_count:
            continue
        permit = Permit.from_mapping(request['permit'])
        if (request['source_id'] != source.source_id or request['context'] != context.to_mapping()
                or receipt.url != source.canonical_url or request['ended_at'] is None
                or permit.request_id != request['request_id']):
            raise Conflict('quarantine requires its exact finalized original request and permit')
        path = f'quarantine/sec/{context.run_id}/{source.source_id}/{context.attempt_id}/{request["request_id"]}/body'
        try:
            objects.verify(path, receipt.sha256, receipt.byte_count)
        except FileNotFoundError:
            objects.stage(path, receipt.temporary_path)
            objects.verify(path, receipt.sha256, receipt.byte_count)
        objects.put_once(path.rsplit('/', 1)[0]+'/receipt.json', canonical_json({
            'receipt': receipt.to_mapping(), 'error': error.to_mapping(), 'context': context.to_mapping(),
            'source': source.to_mapping(), 'request_id': request['request_id'], 'body_path': path}))
        retained += 1
    return retained


def _check_collector_context(workset, context, settings, client):
    _path_segment(context.run_id, 'run_id')
    _path_segment(context.attempt_id, 'attempt_id')
    if context.pinned_on is None:
        raise ValueError('collector context requires its actual pinning date')
    pinned, _ = pin_context(settings, context, context.pinned_on)
    fields = ('config_sha256', 'image_digest', 'parser_version', 'schema_version')
    if (pinned != context or client.settings != settings
            or any(getattr(context, field) != getattr(workset.context, field) for field in fields)
            or context.effective_config != workset.context.effective_config):
        raise ValueError('collector config/image/parser/schema must match the frozen source workset')


def _check_collection_input(workset, context, settings, client, objects):
    if not isinstance(workset, SourceWorkset):
        raise Conflict('collection requires a typed source workset')
    expected_bytes = encode_workset(workset)
    try:
        decoded = decode_source_workset(expected_bytes)
        path = f'worksets/sec/source/sha256={workset.workset_id}/workset.json'
        objects.verify(path, hashlib.sha256(expected_bytes).hexdigest(), len(expected_bytes))
        if decode_source_workset(objects.read(path)) != decoded:
            raise Conflict('retained source workset differs from requested immutable input')
    except (OSError, ValueError) as error:
        raise Conflict('source workset digest or approved retained path is invalid') from error
    _check_collector_context(workset, context, settings, client)
    return path


def collect(workset: SourceWorkset, context: RunContext, settings: Settings, client: RequestClient,
            state: AcquisitionState, objects: ObjectStore, faults: Faults) -> CommandResult:
    source_ref = snapshot_ref = None
    failed = quarantined = 0
    accepted = {}
    fetched = set()
    gaps = []
    outcome = 'incomplete'
    try:
        source_ref = _check_collection_input(workset, context, settings, client, objects)
        state.begin_attempt(context)
    except (Conflict, ValueError, OSError) as error:
        outcome = 'configuration' if isinstance(error, ValueError) else 'state_conflict'
        gaps.append(Error(outcome, error_text(error), False, None, {}))
    else:
        for directory in workset.directories:
            if directory.outcome == 'discovery_failed':
                gaps.append(Error('discovery_failed', 'source workset contains incomplete directory discovery', True, None,
                                  {'directory': directory.to_mapping()}))
        for source in workset.members:
            error = receipt = None
            try:
                before = len(state.request_history(context, source.canonical_url))
                if state.get_source(source.source_id) is None:
                    state.observe(source, workset.context.started_at, 'available')
                snapshot = collect_member(workset, source, context, settings, client, state, objects, faults)
                accepted[source.source_id] = snapshot
                if len(state.request_history(context, source.canonical_url)) > before:
                    fetched.add(source.source_id)
            except (FetchError, ValidationError, Conflict, OSError, ValueError, OwnershipLost, KeyError) as exception:
                if isinstance(exception, FetchError):
                    error, receipt = exception.error, exception.receipt
                elif isinstance(exception, ValidationError):
                    error, receipt = Error(exception.code, error_text(exception), False, source.source_id, {}), exception.receipt
                else:
                    code = 'ownership_lost' if isinstance(exception, OwnershipLost) else 'state_conflict'
                    error = Error(code, error_text(exception), False, source.source_id, {})
                if not isinstance(exception, FetchError):
                    try:
                        state.record_failure(source, error)
                    except (Conflict, OSError, ValueError) as failure:
                        gaps.append(Error('state_conflict', 'source failure checkpoint could not be recorded: '+error_text(failure),
                                          False, source.source_id, {'cause': error.to_mapping()}))
                        outcome = 'state_conflict'
                gaps.append(error)
                failed += 1
                if error.code == 'state_conflict':
                    outcome = 'state_conflict'
            try:
                override = (receipt, error) if receipt is not None else None
                quarantined += _retain_attempt_failures(objects, state, context, source, override=override)
            except (Conflict, OSError, ValueError, KeyError) as retention:
                gaps.append(Error('state_conflict', 'quarantine evidence could not be confirmed: '+error_text(retention),
                                  False, source.source_id, {}))
                outcome = 'state_conflict'
            halt = HALTING_OUTCOMES.get(error.code) if error is not None else None
            if halt is None and error is not None:
                try:
                    run_halt = state.run_halt(context)
                except (Conflict, ValueError, OSError) as control:
                    gaps.append(Error('state_conflict', 'run control could not be confirmed: '+error_text(control), False, None, {}))
                    outcome = 'state_conflict'
                    break
                if run_halt is not None:
                    gaps.append(run_halt)
                    halt = 'access_blocked'
            if halt is not None:
                outcome = halt
                break
        if outcome in HALTING_OUTCOMES.values():
            # An issuer halt forbids fetching; later existing pins can still be verified offline.
            for source in workset.members:
                if source.source_id in accepted:
                    continue
                try:
                    binding = state.binding(workset.workset_id, source.source_id)
                    if binding is not None:
                        accepted[source.source_id] = _verify_snapshot(
                            state.snapshot(source.source_id, binding.snapshot_sha256), source, objects)
                except (Conflict, OSError, ValueError) as error:
                    gaps.append(Error('state_conflict', error_text(error), False, source.source_id, {}))
                    failed += 1
        if len(accepted) == len(workset.members) and workset.discovery_complete and not gaps:
            try:
                # Re-read Binding authority for assembly; candidates and SourceState latest cannot select inputs.
                pinned = tuple(_verify_snapshot(state.snapshot(source.source_id,
                    state.binding(workset.workset_id, source.source_id).snapshot_sha256), source, objects)
                    for source in workset.members)
                snapshot_workset = make_snapshot_workset(workset, pinned)
                path = f'worksets/sec/snapshot/sha256={snapshot_workset.workset_id}/workset.json'
                body = encode_workset(snapshot_workset)
                objects.put_once(path, body)
                objects.verify(path, hashlib.sha256(body).hexdigest(), len(body))
                faults.hit('after_snapshot_workset_write')
                snapshot_ref = path
                outcome = 'success' if workset.members else 'no_new_sources'
            except (Conflict, OSError, ValueError) as error:
                outcome = 'state_conflict'
                gaps.append(Error(outcome, error_text(error), False, None, {}))
    downloaded = len(fetched)
    result = CommandResult(context, outcome, source_ref, snapshot_ref, len(workset.members),
                           downloaded, len(accepted)-downloaded, len(workset.members)-len(accepted), failed, quarantined,
                           tuple(gaps), context.started_at, max(context.started_at, client.clock.now()))
    faults.hit('before_result_write')
    return result
