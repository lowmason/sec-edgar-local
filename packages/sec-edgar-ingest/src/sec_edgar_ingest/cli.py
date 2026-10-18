"""Validate acquisition intent before constructing the explicitly selected backend."""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from .runtime import configured_descriptor, preflight_current, retain_manifest
from . import __version__
from .collection import collect
from .config import Settings, load_config, pin_context
from .coordination import Clock, Coordinator
from .discovery import discover
from .etl.approval import activation_ref, approve
from .etl.commands import (PublicationRepairPending, read_etl_result, run_transform, run_publish,
                           write_etl_result, validate_workset_ref)
from .etl.contracts import MAX_OPERATOR_CHARS, MAX_REASON_CHARS, require_line
from .etl.history import quarter_history, withdrawal_candidates
from .etl.manifest import approval_ref
from .etl.parser import supported_parser, SCHEMA_VERSION
from .etl.publication import repair_publication
from .etl.rollback import rollback, rollback_ref
from .etl.state import EtlState
from .download import BoundedSender, FixturePack, RequestClient
from .models import (CommandResult, Error, RunContext, canonical_json, error_text, parse_json, quarter_for,
                     quarter_value, safe_relative_path, to_mapping_value)
from .results import exit_code, log_event, read_result, result_path, write_result
from .state import AcquisitionState, attempt_key
from .storage import open_stores
from .storage.contracts import CAS_ATTEMPTS, ClockUncertain, Conflict, OwnershipLost, StoreMissing
from .workflows.checked import Dispatcher as WorkflowDispatcher, ChildUnfinished
from .workflows.contracts import WORKFLOW_COMMANDS, WORKFLOW_PRIORITY, workflow_path
from .workflows.contracts import LOCAL_CONTRACT, require_contract, validate_invocation
from .workflows.results import freeze_workflow, read_workflow_result, write_workflow_result
from .workflows.runner import run_workflow
from .workflows.summary import emit_summary
from .worksets import decode_source_workset

SOURCE_REF = re.compile(r'worksets/sec/source/sha256=[0-9a-f]{64}/workset\.json\Z')


class _ExpiredAttempt(ValueError):
    pass


class _NoFaults:
    def hit(self, point: str) -> None:
        pass


class _CheckedSender:
    # RequestClient retains an unconfirmed transport; CLI must also retain an unexpected command error.
    def __init__(self, sender):
        self.sender, self.failure = sender, None

    def send(self, *args, **kwargs):
        try:
            return self.sender.send(*args, **kwargs)
        except (OwnershipLost, ClockUncertain):
            raise
        except Exception as error:
            self.failure = error
            raise

    def close(self):
        if hasattr(self.sender, 'close'):
            self.sender.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='sec-edgar-ingest')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command')
    for command in ('discover', 'collect', 'transform', 'publish', *WORKFLOW_COMMANDS):
        sub = commands.add_parser(command)
        for name in ('config', 'run-id', 'execution-id', 'attempt-id', 'deadline'):
            sub.add_argument('--' + name, required=True)
        sub.add_argument('--today')
        if command in ('discover', 'collect', *WORKFLOW_COMMANDS):
            sub.add_argument('--fixture-pack')
        if command == 'discover':
            sub.add_argument('--mode', required=True, choices=('quarterly', 'daily'))
            sub.add_argument('--discovery-id', required=True)
            sub.add_argument('--refresh', action='store_true')
        elif command in ('collect', 'transform', 'publish'):
            sub.add_argument('--workset', required=True)
        if command == 'transform':
            sub.add_argument('--force', action='store_true')
    sub = commands.add_parser('approve')
    for name in ('config', 'quarter', 'generation', 'quarterly-sha256'):
        sub.add_argument('--' + name, required=True)
    sub.add_argument('--approver', required=True, help='explicit local audit label')
    sub = commands.add_parser('candidates')
    sub.add_argument('--config', required=True)
    sub = commands.add_parser('history')
    sub.add_argument('--config', required=True)
    sub.add_argument('--quarter', required=True)
    sub = commands.add_parser('rollback')
    for name in ('config', 'quarter', 'from-generation', 'to-generation', 'reason'):
        sub.add_argument('--' + name, required=True)
    sub.add_argument('--operator', required=True, help='explicit local audit label')
    return parser


def _segment(value: str, name: str) -> None:
    if '/' in safe_relative_path(value, name):
        raise ValueError(name + ' must be a single path segment')


def _validate(args) -> tuple[Settings, date | None, datetime, FixturePack | None]:
    for name in ('run_id', 'execution_id', 'attempt_id'):
        _segment(getattr(args, name), name)
    if args.command == 'discover':
        _segment(args.discovery_id, 'discovery_id')
    elif args.command in ('transform', 'publish'):
        validate_workset_ref(args.workset, 'snapshot' if args.command == 'transform' else 'transformed')
    elif SOURCE_REF.fullmatch(args.workset) is None:
        raise ValueError('workset must name the exact immutable source-workset object path')
    settings = load_config(Path(args.config))
    etl = args.command in ('transform', 'publish')
    if etl:
        supported_parser(settings.etl.parser_version, fixture=settings.acquisition.mode == 'fixture')
        if settings.etl.schema_version != SCHEMA_VERSION:
            raise ValueError('unsupported ETL schema version')
    if not settings.coordination.lease_seconds.is_integer():
        raise ValueError('coordination requires whole finite lease seconds')
    deadline = datetime.fromisoformat(args.deadline.replace('Z', '+00:00'))
    if deadline.utcoffset() != timezone.utc.utcoffset(deadline):
        raise ValueError('deadline must be timezone-aware UTC')
    today = date.fromisoformat(args.today) if args.today else None
    if args.today and today.isoformat() != args.today:
        raise ValueError('today must be a canonical ISO date')
    pack = _fixture_pack(settings, getattr(args, 'fixture_pack', None), today,
                         required=not etl)
    # A completed result may outlive its deadline; only its saved context can authorize replay.
    now = Clock().now()
    if deadline > now:
        checked = _new_context(args, settings, deadline, today, now)
        if args.command == 'discover' and args.mode == 'daily':
            _, end = pin_context(settings, checked, checked.pinned_on)
            if end != quarter_for(checked.pinned_on):
                raise ValueError('daily discovery endpoint must include the current quarter')
    return settings, today, deadline, pack


def _verified_runtime(settings):
    if settings.runtime.kind == 'native':
        try:
            return preflight_current(Path(settings.runtime.release_manifest))
        except subprocess.CalledProcessError as error:
            raise ValueError('native runtime installation probe failed') from error
    return None


def _fixture_pack(settings, path, today, *, required):
    if settings.acquisition.mode == 'live':
        if path is not None or today is not None:
            raise ValueError('fixture pack and date override require fixture acquisition')
        return None
    if today is not None and (not settings.fixture or not settings.fixture.allow_clock_override):
        raise ValueError('today requires the explicit fixture clock override marker')
    if required and not path:
        raise ValueError('fixture acquisition requires an explicit fixture pack')
    return FixturePack.load(Path(path)) if path else None


def _new_context(args, settings, deadline, today, started) -> RunContext:
    priority = 'daily' if args.command == 'discover' and args.mode == 'daily' else 'backfill'
    context = RunContext(run_id=args.run_id,
        execution_id=args.execution_id,
        command=args.command,
        attempt_id=args.attempt_id,
        runtime=configured_descriptor(settings),
        parser_version=settings.etl.parser_version,
        schema_version=settings.etl.schema_version,
        config_sha256=settings.config_sha256,
        started_at=started,
        deadline=deadline,
        priority=priority,
        format_version='sec-local-run-context-v1')
    return pin_context(settings, context, today or started.date())[0]


def _intent(args, pack) -> dict[str, object]:
    if args.command in ('transform', 'publish'):
        return {'command': args.command, 'today': args.today, 'workset': args.workset,
                'force': args.force if args.command == 'transform' else None}
    return {'command': args.command, 'today': args.today,
            'fixture_sha256': pack.manifest_sha256 if pack is not None else None,
            'mode': args.mode if args.command == 'discover' else None,
            'discovery_id': args.discovery_id if args.command == 'discover' else None,
            'refresh': args.refresh if args.command == 'discover' else None,
            'workset': args.workset if args.command == 'collect' else None}


def _matching_context(saved, current, *, explicit_today) -> RunContext:
    expected = current.to_mapping()
    actual = saved.to_mapping()
    expected['started_at'] = actual['started_at']
    if not explicit_today:
        expected['pinned_on'] = actual['pinned_on']
    if expected != actual:
        raise Conflict('attempt replay differs from its exact saved correlation/config/runtime/versions/deadline')
    # Validate the original start and pin date; never fabricate a fresh start for replay.
    pin_context(Settings.from_mapping(actual['effective_config']), saved, saved.pinned_on)
    return saved


def _existing_context(current, state, objects, intent, explicit_today):
    path = result_path(current)
    intent_path = path.rsplit('/', 1)[0] + '/command.json'
    try:
        saved = read_result(path, objects)
    except FileNotFoundError:
        saved = None
    if saved is not None:
        context = _matching_context(saved.context, current, explicit_today=explicit_today)
        if objects.read(intent_path) != canonical_json(intent):
            raise Conflict('completed attempt command inputs differ from the frozen invocation')
        state.begin_attempt(context)
        state.finish_attempt(saved)
        return context, saved
    row = state.store.get('Attempt', attempt_key(current))
    context = _matching_context(RunContext.from_mapping(row.to_mapping()['value']['context']), current,
                                explicit_today=explicit_today) if row is not None else current
    state.begin_attempt(context)
    objects.put_once(intent_path, canonical_json(intent))
    return context, None


def _existing_etl_context(current, state, objects, intent, explicit_today):
    path = result_path(current)
    intent_path = path.rsplit('/', 1)[0] + '/command.json'
    try:
        saved = read_etl_result(path, objects)
    except FileNotFoundError:
        saved = None
    try:
        frozen_body = objects.read(intent_path)
    except FileNotFoundError:
        frozen_body = None
    if frozen_body is not None:
        frozen = parse_json(frozen_body)
        if (not isinstance(frozen, dict) or set(frozen) != {'context', 'intent'}
                or canonical_json(frozen) != frozen_body or frozen['intent'] != intent):
            raise Conflict('ETL command differs from its frozen invocation')
        prior = RunContext.from_mapping(frozen['context'])
    else:
        if saved is not None:
            raise Conflict('completed ETL result has no command intent')
        # Attempt keys include runtime/execution, while immutable command paths do not.
        # Find an interrupted begin even if the caller now supplies a different key.
        matching = [RunContext.from_mapping(row.to_mapping()['value']['context'])
                    for row in state.store.scan('Attempt', {})
                    if all(row.value['context'][name] == getattr(current, name)
                           for name in ('run_id', 'command', 'attempt_id'))]
        if len(matching) > 1:
            raise Conflict('multiple attempts claim the same command path')
        prior = matching[0] if matching else current
    context = _matching_context(prior, current, explicit_today=explicit_today)
    if saved is not None and saved.context != context:
        raise Conflict('ETL result differs from its frozen command context')
    frozen = canonical_json({'context': context.to_mapping(), 'intent': intent})
    if frozen_body is not None and frozen != frozen_body:
        raise Conflict('ETL intent context differs from its exact canonical context')
    state.begin_attempt(context)
    objects.put_once(intent_path, frozen)
    if saved is not None:
        for quarter in saved.quarters:
            if quarter.outcome in ('published', 'unchanged'):
                repair_publication(quarter.quarter, objects, EtlState(state.store))
        state.finish_attempt(saved)
    return context, saved


def _discover_result(workset, context, clock):
    gaps = tuple(directory.error for directory in workset.directories if directory.error is not None)
    outcome = 'discovery_failed' if not workset.discovery_complete else ('success' if workset.members else 'no_new_sources')
    return CommandResult(context=context,
        outcome=outcome,
        source_workset_ref=f'worksets/sec/source/sha256={workset.workset_id}/workset.json',
        snapshot_workset_ref=None,
        discovered=len(workset.members),
        downloaded=0,
        unchanged=0,
        pending=0,
        failed=len(gaps),
        quarantined=0,
        gaps=gaps,
        started_at=context.started_at,
        ended_at=max(context.started_at, clock.now()),
        format_version='sec-local-command-result-v1')


def _collection_outcome(result):
    if result.outcome != 'incomplete' or len({gap.source_id for gap in result.gaps if gap.source_id}) != 1 or result.discovered != 1:
        return result
    gap = next((gap for gap in result.gaps if gap.source_id), None)
    if gap is None:
        return result
    transport = gap.details.get('outcome')
    outcome = {'pending': 'pending', 'exhausted': 'retry_exhausted', 'deferred': 'deferred',
               'quarantined': 'quarantined'}.get(transport)
    return replace(result, outcome=outcome) if outcome else result


def _retain_error(state, context, outcome, error):
    for _ in range(CAS_ATTEMPTS):
        row = state.store.get('Attempt', attempt_key(context))
        if row is None:
            return
        value = row.to_mapping()['value']
        if value['context'] != context.to_mapping() or value['result'] is not None:
            return
        value.update(outcome=outcome, ended_at=Clock().now().isoformat(),
                     structured_errors=[error.to_mapping()])
        try:
            state.store.replace('Attempt', attempt_key(context), value, row.version)
            return
        except Conflict:
            continue
    raise Conflict('error retention exhausted conditional races')


def _stdout(result, reference):
    if result.context.command in ('transform', 'publish'):
        sys.stdout.write(canonical_json({'outcome': result.outcome, 'result_ref': reference,
            'input_ref': result.input_ref, 'transformed_workset_ref': result.transformed_workset_ref}).decode() + '\n')
        return exit_code(result.outcome)
    sys.stdout.write(canonical_json({'outcome': result.outcome, 'result_ref': reference,
        'source_workset_ref': result.source_workset_ref, 'snapshot_workset_ref': result.snapshot_workset_ref}).decode() + '\n')
    return exit_code(result.outcome)


def _validate_workflow(args):
    for name in ('run_id', 'attempt_id', 'execution_id'):
        _segment(getattr(args, name), name)
    settings = load_config(Path(args.config))
    supported_parser(settings.etl.parser_version,
                     fixture=settings.acquisition.mode == 'fixture')
    if settings.etl.schema_version != SCHEMA_VERSION:
        raise ValueError('unsupported ETL schema version')
    if not settings.coordination.lease_seconds.is_integer():
        raise ValueError('coordination requires whole finite lease seconds')
    deadline = datetime.fromisoformat(args.deadline.replace('Z', '+00:00'))
    if deadline.utcoffset() != timezone.utc.utcoffset(deadline):
        raise ValueError('deadline must be timezone-aware UTC')
    today = date.fromisoformat(args.today) if args.today else None
    if args.today and today.isoformat() != args.today:
        raise ValueError('today must be a canonical ISO date')
    pack = _fixture_pack(settings, args.fixture_pack, today, required=True)
    if (deadline - Clock().now()).total_seconds() > settings.execution.max_run_seconds and not (
            settings.fixture and settings.fixture.allow_deadline_override):
        raise ValueError('deadline exceeds execution.max_run_seconds')
    # Do not construct a fresh context here: the immutable saved pin must be read first.
    return settings, today, deadline, pack


def _workflow_frozen(path, objects):
    try:
        body = objects.read(path)
    except FileNotFoundError:
        return None
    value = parse_json(body)
    require_contract(value)
    if (not isinstance(value, dict) or set(value) != {'contract_version', 'context', 'intent'}
            or canonical_json(to_mapping_value(value)) != body):
        raise Conflict('workflow intent is not exact canonical context/intent')
    RunContext.from_mapping(value['context'])
    validate_invocation(value['intent'])
    return value


def _workflow_saved(args, store, objects):
    path = f'runs/sec/{args.run_id}/{args.command}/{args.attempt_id}/intent.json'
    frozen = _workflow_frozen(path, objects)
    if frozen is not None: return frozen
    # T6 begins its conditional index before writing intent bytes. Reopen that
    # actual durable start/pin if a process died between those two writes.
    key = hashlib.sha256(canonical_json(to_mapping_value([LOCAL_CONTRACT, args.run_id, args.command, args.attempt_id]))).hexdigest()
    row = store.get('WorkflowAttempt', key)
    if row is None: return None
    value = row.to_mapping()['value']
    require_contract(value)
    if set(value) != {'contract_version', 'context', 'intent', 'selection_ref', 'result_ref'}:
        raise Conflict('workflow begun index fields differ')
    saved = RunContext.from_mapping(value['context'])
    if (saved.run_id, saved.command, saved.attempt_id) != (args.run_id, args.command, args.attempt_id):
        raise Conflict('workflow begun index correlation differs')
    validate_invocation(value['intent'])
    from .workflows.results import _index
    _index(saved, value['intent'], store, objects)
    return {'contract_version': LOCAL_CONTRACT, 'context': value['context'], 'intent': value['intent']}


def _workflow_context(args, settings, today, deadline, started, pinned):
    context = RunContext(run_id=args.run_id,
        execution_id=args.execution_id,
        command=args.command,
        attempt_id=args.attempt_id,
        runtime=configured_descriptor(settings),
        parser_version=settings.etl.parser_version,
        schema_version=settings.etl.schema_version,
        config_sha256=settings.config_sha256,
        started_at=started,
        deadline=deadline,
        priority=WORKFLOW_PRIORITY[args.command],
        format_version='sec-local-run-context-v1')
    return pin_context(settings, context, today or pinned or started.date())


def _workflow_stdout(result, reference):
    sys.stdout.write(canonical_json(to_mapping_value({'outcome': result.outcome, 'result_ref': reference,
        'source_workset_ref': result.source_workset_ref,
        'counts': result.to_mapping()['counts']})).decode() + '\n')
    return exit_code(result.outcome)


def _workflow_main(args):
    try:
        settings, today, deadline, pack = _validate_workflow(args)
        verified = _verified_runtime(settings)
    except (ValueError, OSError, TypeError) as error:
        sys.stderr.write(canonical_json(to_mapping_value({'outcome': 'configuration', 'error': str(error)})).decode() + '\n')
        return 2
    opened, context = (), None
    try:
        opened = open_stores(settings)
        store, objects, leases = opened
        if verified is not None:
            retain_manifest(objects, verified.manifest)
        frozen = _workflow_saved(args, store, objects)
        saved = None if frozen is None else RunContext.from_mapping(frozen['context'])
        started = saved.started_at if saved is not None else Clock().now()
        pinned = saved.pinned_on if saved is not None else None
        # Exact supplied correlation/config/runtime/versions/deadline is compared by T6.
        # An omitted date reuses the saved pin, even after the calendar changes.
        if saved is None and deadline <= Clock().now():
            raise _ExpiredAttempt('an expired deadline permits only exact completed-result replay')
        try:
            context, end = _workflow_context(args, settings, today, deadline, started, pinned)
        except ValueError as error:
            if saved is None: raise _ExpiredAttempt(str(error)) from error
            raise
        intent = {'contract_version': LOCAL_CONTRACT, 'command': args.command, 'today': args.today,
            'fixture_sha256': pack.manifest_sha256 if pack is not None else None,
            'pinned_end_quarter': end}
        context = freeze_workflow(context, intent, store, objects)
        try:
            completed = read_workflow_result(workflow_path(context), store, objects)
        except FileNotFoundError:
            completed = None
        if completed is not None:
            log_event(context, 'result_replayed', {'result_ref': workflow_path(context)})
            return _workflow_stdout(completed, workflow_path(context))
        if deadline <= Clock().now():
            raise _ExpiredAttempt('an unfinished expired workflow requires a new attempt')
        # Adapters belonging to children are constructed only inside their public CLI paths.
        dispatcher = WorkflowDispatcher(context, settings,
            Path(args.fixture_pack) if args.fixture_pack else None,
            None, store, objects)
        log_event(context, 'command_started', {'command': args.command})
        result = run_workflow(context, settings, intent, dispatcher, store, objects)
        reference = write_workflow_result(result, store, objects)
        log_event(context, 'command_finished', {'outcome': result.outcome,
            'result_ref': reference, 'counters': result.to_mapping()['counts']})
        emit_summary(result, reference, objects, store)
        return _workflow_stdout(result, reference)
    except Exception as exception:
        outcome = ('configuration' if isinstance(exception, (_ExpiredAttempt, TimeoutError)) else
            'ownership_lost' if isinstance(exception, (OwnershipLost, ClockUncertain)) else
            'state_conflict' if isinstance(exception, (Conflict, ValueError, OSError, KeyError)) else
            'internal_error')
        details = {'type': type(exception).__name__}
        if isinstance(exception, ChildUnfinished):
            outcome = exception.outcome
            details.update(exception.details)
        error = Error(outcome, error_text(exception),
            isinstance(exception, ChildUnfinished) and exception.resumable, None, details)
        if context is not None:
            log_event(context, 'command_error', {'outcome': outcome, 'error': error.to_mapping()})
        else:
            sys.stderr.write(canonical_json(to_mapping_value({'outcome': outcome, 'error': error.to_mapping()})).decode() + '\n')
        sys.stdout.write(canonical_json(to_mapping_value({'outcome': outcome, 'result_ref': None,
            'source_workset_ref': None, 'counts': None})).decode() + '\n')
        return exit_code(outcome)
    finally:
        for resource in reversed(opened):
            if hasattr(resource, 'close'):
                resource.close()


def _operator_settings(args) -> Settings:
    if args.command == 'history':
        quarter_value(args.quarter)
    settings = load_config(Path(args.config))
    return settings


def _configuration_error(error: Exception) -> int:
    sys.stderr.write(canonical_json({'outcome': 'configuration', 'error': str(error)}).decode() + '\n')
    return 2


def _operator_identity(settings: Settings, supplied: str | None, flag: str | None):
    """Return the explicit local audit label for commands that record an actor."""
    if flag is not None:
        require_line(supplied, '--' + flag, MAX_OPERATOR_CHARS)
    return supplied


def _operator_main(args, event: str | None, empty: dict[str, object], run, actor: str | None = None) -> int:
    """Run one operator command on verify-only stores and print its canonical result.

    `actor` names the flag (`approver` or `operator`) of a command that records who acted.
    """
    try:
        settings = _operator_settings(args)
        _verified_runtime(settings)
        principal = _operator_identity(settings, None if actor is None else getattr(args, actor), actor)
        if args.command == 'rollback':
            require_line(args.reason, '--reason', MAX_REASON_CHARS)
    except (ValueError, OSError, TypeError) as error:
        return _configuration_error(error)
    opened = ()
    try:
        opened = open_stores(settings, access='operator')
        store, objects, _ = opened
        value = {**empty, **run(objects, EtlState(store), principal)}
    except StoreMissing as error:
        return _configuration_error(error)
    except Exception as exception:
        outcome = ('state_conflict' if isinstance(exception, (Conflict, ValueError, OSError, KeyError))
                   else 'internal_error')
        value = {**empty, 'outcome': outcome, 'error': Error(
            outcome, error_text(exception), False, None, {'type': type(exception).__name__}).to_mapping()}
    finally:
        for resource in reversed(opened):
            if hasattr(resource, 'close'):
                resource.close()
    body = to_mapping_value(value)
    if event is not None:
        sys.stderr.write(canonical_json({'event': event, 'fields': body}).decode() + '\n')
    sys.stdout.write(canonical_json(body).decode() + '\n')
    return exit_code(value['outcome'])


def _approve_main(args) -> int:
    def run(objects, state, actor):
        result = approve(args.quarter, args.generation, args.quarterly_sha256, actor, objects, state)
        ref = None if result.approval is None else approval_ref(result.approval.quarter, result.approval.generation_id)
        return {**result.to_mapping(), 'approval_ref': ref,
                'activation_ref': None if result.activation is None else activation_ref(result.activation)}
    return _operator_main(args, 'withdrawal_approval',
                          {'quarter': args.quarter, 'generation_id': args.generation, 'approval_ref': None,
                           'approval': None, 'publication': None, 'activation': None, 'activation_ref': None,
                           'error': None}, run, actor='approver')


def _candidates_main(args) -> int:
    return _operator_main(args, None, {'candidates': None, 'error': None},
                          lambda objects, state, actor: {'outcome': 'success',
                                                         'candidates': list(withdrawal_candidates(objects, state))})


def _history_main(args) -> int:
    def run(objects, state, actor):
        return {'outcome': 'success', 'lineage': list(quarter_history(args.quarter, objects, state)),
                'rollbacks': [record.to_mapping() for record in state.rollbacks(args.quarter)],
                'activations': [record.to_mapping() for record in state.activations(args.quarter)]}
    return _operator_main(args, None, {'quarter': args.quarter, 'lineage': None, 'rollbacks': None,
                                       'activations': None, 'error': None}, run)


def _rollback_main(args) -> int:
    def run(objects, state, actor):
        result = rollback(args.quarter, args.from_generation, args.to_generation, actor, args.reason,
                          objects, state)
        return {**result.to_mapping(),
                'rollback_ref': None if result.rollback is None else rollback_ref(result.rollback)}
    return _operator_main(args, 'quarter_rollback',
                          {'quarter': args.quarter, 'from_generation_id': args.from_generation,
                           'to_generation_id': args.to_generation, 'rollback_ref': None, 'active': None,
                           'rollback': None, 'error': None}, run, actor='operator')


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command in WORKFLOW_COMMANDS:
        return _workflow_main(args)
    if args.command == 'approve':
        return _approve_main(args)
    if args.command == 'candidates':
        return _candidates_main(args)
    if args.command == 'history':
        return _history_main(args)
    if args.command == 'rollback':
        return _rollback_main(args)
    try:
        settings, today, deadline, pack = _validate(args)
        verified = _verified_runtime(settings)
    except (ValueError, OSError, TypeError) as error:
        sys.stderr.write(canonical_json({'outcome': 'configuration', 'error': str(error)}).decode() + '\n')
        return 2
    state = context = sender = None
    opened = ()
    try:
        clock = Clock()
        opened = open_stores(settings)
        store, objects, leases = opened
        if verified is not None:
            retain_manifest(objects, verified.manifest)
        state = AcquisitionState(store, clock=clock)
        path = f'runs/sec/{args.run_id}/{args.command}/{args.attempt_id}/result.json'
        try:
            prior = (read_etl_result if args.command in ('transform', 'publish') else read_result)(path, objects)
        except FileNotFoundError:
            prior = None
        if prior is None and deadline <= clock.now():
            raise _ExpiredAttempt('an expired deadline permits only an exact completed-result replay')
        started = prior.context.started_at if prior is not None else clock.now()
        pin_date = today or (prior.context.pinned_on if prior is not None else None)
        context = _new_context(args, settings, deadline, pin_date, started)
        workset = None
        if args.command == 'collect':
            try:
                workset = decode_source_workset(objects.read(args.workset))
            except (ValueError, OSError):
                state.begin_attempt(context)
                raise
            if args.workset != f'worksets/sec/source/sha256={workset.workset_id}/workset.json':
                raise Conflict('workset object path differs from its content identity')
            context = replace(context, priority=workset.context.priority)
        if args.command in ('transform', 'publish'):
            context, saved = _existing_etl_context(context, state, objects, _intent(args, pack), bool(args.today))
        else:
            context, saved = _existing_context(context, state, objects, _intent(args, pack), bool(args.today))
        if saved is not None:
            log_event(context, 'result_replayed', {'result_ref': result_path(context)})
            return _stdout(saved, result_path(context))
        if args.command in ('transform', 'publish'):
            log_event(context, 'command_started', {'command': args.command, 'input_ref': args.workset})
            result = (run_transform(args.workset, context, settings, objects, store, force=args.force)
                      if args.command == 'transform' else run_publish(args.workset, context, settings, objects, store))
            reference = write_etl_result(result, objects, state)
            log_event(context, 'command_finished', {'outcome': result.outcome, 'result_ref': reference,
                      'counters': {name: getattr(result, name) for name in
                          ('transformed', 'published', 'unchanged', 'quarantined', 'awaiting_approval', 'failed')}})
            return _stdout(result, reference)
        coordinator = Coordinator(settings, store, leases, clock)
        sender = _CheckedSender(BoundedSender(settings, clock) if settings.acquisition.mode == 'live'
                                else pack.sender(store))
        client = RequestClient(settings, coordinator, sender, state, clock)
        log_event(context, 'command_started', {'command': args.command})
        if args.command == 'discover':
            workset = discover(settings, context, args.mode, args.discovery_id, client, state, objects,
                               context.pinned_on, refresh=args.refresh)
            result = _discover_result(workset, context, clock)
        else:
            result = _collection_outcome(collect(workset, context, settings, client, state, objects, _NoFaults()))
        if sender.failure is not None:
            raise sender.failure
        reference = write_result(result, objects, state)
        log_event(context, 'command_finished', {'outcome': result.outcome, 'result_ref': reference,
            'counters': {name: getattr(result, name) for name in ('discovered', 'downloaded', 'unchanged', 'pending', 'failed', 'quarantined')}})
        return _stdout(result, reference)
    except Exception as exception:
        outcome = 'configuration' if isinstance(exception, _ExpiredAttempt) else 'ownership_lost' if isinstance(exception, (OwnershipLost, ClockUncertain)) else ('state_conflict' if isinstance(exception, (Conflict, ValueError, OSError, KeyError)) else 'internal_error')
        details = {'type': type(exception).__name__}
        repair_pending = isinstance(exception, PublicationRepairPending)
        if repair_pending:
            details.update(exception.details)
        error = Error(outcome, error_text(exception), repair_pending, None, details)
        if state is not None and context is not None:
            try:
                _retain_error(state, context, outcome, error)
            except Exception as retention:
                error = Error('internal_error', 'attempt error could not be retained: ' + error_text(retention), False, None, {'cause': error.to_mapping()})
                outcome = 'internal_error'
        if context is not None:
            log_event(context, 'command_error', {'outcome': outcome, 'error': error.to_mapping()})
        else:
            sys.stderr.write(canonical_json({'outcome': outcome, 'error': error.to_mapping()}).decode() + '\n')
        sys.stdout.write(canonical_json({'outcome': outcome, 'result_ref': None, 'source_workset_ref': None, 'snapshot_workset_ref': None}).decode() + '\n')
        return exit_code(outcome)
    finally:
        if sender is not None and hasattr(sender, 'close'):
            sender.close()
        for resource in reversed(opened):
            if hasattr(resource, 'close'):
                resource.close()
