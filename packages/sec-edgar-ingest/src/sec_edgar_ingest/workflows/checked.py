from __future__ import annotations
from .contracts import LOCAL_CONTRACT, require_contract

import argparse
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict

from .. import runtime
from ..runtime import configured_descriptor
from ..config import Settings, pin_context
from ..download import FixturePack
from ..models import CommandResult, Error, RunContext, canonical_json, parse_json, require_hash, safe_relative_path, to_mapping_value
from ..results import exit_code, read_result, result_path
from ..state import AcquisitionState, attempt_key
from ..storage.contracts import AlreadyExists, BoundaryObserver, Conflict, ObjectStore, StateStore, observe
from ..storage.contracts import deployment_binding
from ..worksets import decode_source_workset, decode_snapshot_workset, encode_workset, make_snapshot_workset
from ..etl.commands import read_etl_result, validate_workset_ref
from ..etl.contracts import Candidate, EtlResult, GenerationCapture, decode_transformed, transformed_ref, processing_key
from ..etl.manifest import validate_candidate, read_manifest
from ..etl.reader import validated_manifest
from ..etl.transform import _pinned_members, _read_manifest, read_observations
from ..etl.parser import supported_parser
from ..models import Record, validate_record_fields
from .contracts import WORKFLOW_COMMANDS


@dataclass(frozen=True, slots=True)
class CheckedChild(Record):
    call: Mapping[str, object]
    result_ref: str
    result: CommandResult | EtlResult

    def __post_init__(self):
        validate_record_fields(self)
        safe_relative_path(self.result_ref, "checked result reference")
        if self.call.get("result_ref") != self.result_ref or result_path(self.result.context) != self.result_ref:
            raise ValueError("checked child result reference differs from decoded context/call")


class ChildCall(TypedDict):
    contract_version: str
    format_version: str
    workflow_command: str
    workflow_attempt_id: str
    step_id: str
    context: dict[str, object]
    intent: dict[str, object]
    input_ref: str | None
    result_ref: str


CALL_FIELDS = frozenset(ChildCall.__annotations__)
CHILD_COMMANDS = ('discover', 'collect', 'transform', 'publish')


def _segment(value, label):
    if '/' in safe_relative_path(value, label):
        raise ValueError(label + ' must be one safe path segment')


def child_attempt_id(run_id, workflow_command, workflow_attempt_id, step_id, command):
    for name, value in (('run_id', run_id), ('workflow_command', workflow_command),
                        ('workflow_attempt_id', workflow_attempt_id), ('step_id', step_id),
                        ('command', command)):
        _segment(value, name)
    if workflow_command not in WORKFLOW_COMMANDS or command not in CHILD_COMMANDS:
        raise ValueError('unsupported workflow/child command')
    return 'wf-' + hashlib.sha256(canonical_json(
        to_mapping_value([LOCAL_CONTRACT, run_id, workflow_command, workflow_attempt_id, step_id, command]))).hexdigest()[:40]


def make_call(context, command, attempt_id, input_ref, fixture_sha256=None, *,
              workflow_command, workflow_attempt_id, step_id, today=None,
              mode=None, discovery_id=None, refresh=False, force=False):
    expected = child_attempt_id(context.run_id, workflow_command, workflow_attempt_id, step_id, command)
    if attempt_id != expected or type(refresh) is not bool or type(force) is not bool:
        raise ValueError('child namespace or flag types differ')
    child = replace(context, command=command, attempt_id=attempt_id)
    settings = Settings.from_mapping(child.to_mapping()['effective_config'])
    if child.pinned_on is None or pin_context(settings, child, child.pinned_on)[0] != child:
        raise ValueError('child template requires exact pinned effective settings')
    if today is not None and (type(today) is not date or today != child.pinned_on):
        raise ValueError('child today differs from the pinned date')
    today_text = None if today is None else today.isoformat()
    if command == 'discover':
        if mode not in ('quarterly', 'daily') or discovery_id is None or input_ref is not None or force:
            raise ValueError('invalid discovery flags')
        _segment(discovery_id, 'discovery_id')
    elif mode is not None or discovery_id is not None or refresh:
        raise ValueError('non-discovery cannot carry discovery flags')
    if command == 'collect':
        if force or input_ref is None or not input_ref.startswith('worksets/sec/source/sha256='):
            raise ValueError('collection requires its exact source workset')
        if not re.fullmatch(r'worksets/sec/source/sha256=[0-9a-f]{64}/workset\.json', input_ref):
            raise ValueError('invalid source workset reference')
    if command in ('transform', 'publish'):
        validate_workset_ref(input_ref, 'snapshot' if command == 'transform' else 'transformed')
        if fixture_sha256 is not None or (command == 'publish' and force):
            raise ValueError('ETL cannot carry transport/force flags outside transform')
        intent = {'command': command, 'today': today_text, 'workset': input_ref,
                  'force': force if command == 'transform' else None}
    else:
        if settings.acquisition.mode == 'fixture':
            require_hash(fixture_sha256, 'fixture_sha256')
        elif fixture_sha256 is not None or today is not None:
            raise ValueError('live acquisition cannot carry fixture-only inputs')
        intent = {'command': command, 'today': today_text, 'fixture_sha256': fixture_sha256,
            'mode': mode if command == 'discover' else None,
            'discovery_id': discovery_id if command == 'discover' else None,
            'refresh': refresh if command == 'discover' else None,
            'workset': input_ref if command == 'collect' else None}
    if settings.acquisition.mode == 'live' and today is not None:
        raise ValueError('live acquisition cannot carry date override')
    return {'contract_version': LOCAL_CONTRACT, 'format_version': 'sec-local-workflow-child-call-v1', 'workflow_command': workflow_command,
        'workflow_attempt_id': workflow_attempt_id, 'step_id': step_id,
        'context': child.to_mapping(), 'intent': intent, 'input_ref': input_ref,
        'result_ref': result_path(child)}


def _validated(call):
    if not isinstance(call, Mapping) or set(call) != CALL_FIELDS:
        raise Conflict('child call must have its exact versioned fields')
    require_contract(call)
    value = parse_json(canonical_json(to_mapping_value(call)))
    context = RunContext.from_mapping(value['context'])
    intent = value['intent']
    if not isinstance(intent, dict):
        raise Conflict('child intent must be an exact mapping')
    family_flags = (('refresh', 'discover'),) if context.command in ('discover', 'collect') else (('force', 'transform'),)
    for field, applicable in family_flags:
        if field not in intent:
            raise Conflict('child intent lacks exact flag field')
        if context.command == applicable:
            if type(intent[field]) is not bool:
                raise Conflict('child flag must be an exact boolean')
        elif intent[field] is not None:
            raise Conflict('inapplicable child flag must be null')
    rebuilt = make_call(context, context.command, context.attempt_id, value['input_ref'],
        intent.get('fixture_sha256'), workflow_command=value['workflow_command'],
        workflow_attempt_id=value['workflow_attempt_id'], step_id=value['step_id'],
        today=date.fromisoformat(intent['today']) if intent.get('today') else None,
        mode=intent.get('mode'), discovery_id=intent.get('discovery_id'),
        refresh=intent['refresh'] if context.command == 'discover' else False,
        force=intent['force'] if context.command == 'transform' else False)
    if canonical_json(to_mapping_value(rebuilt)) != canonical_json(to_mapping_value(value)):
        raise Conflict('child call differs from its exact canonical identity/flags')
    return value, context


def call_ref(call):
    value, context = _validated(call)
    return (f'runs/sec/{context.run_id}/{value["workflow_command"]}/{value["workflow_attempt_id"]}'
            f'/children/{context.attempt_id}/call.json')


def call_key(call):
    value, context = _validated(call)
    return hashlib.sha256(canonical_json(to_mapping_value([LOCAL_CONTRACT, context.run_id, value['workflow_command'],
        value['workflow_attempt_id'], context.attempt_id]))).hexdigest()


def _remember_call(call, store, objects):
    value, _ = _validated(call)
    body = canonical_json(to_mapping_value(value))
    objects.put_once(call_ref(value), body)
    objects.verify(call_ref(value), hashlib.sha256(body).hexdigest(), len(body))
    try:
        store.insert('WorkflowChildCall', call_key(value), value)
    except AlreadyExists:
        row = store.get('WorkflowChildCall', call_key(value))
        if row is None or canonical_json(to_mapping_value(row.to_mapping()['value'])) != body:
            raise Conflict('child call index differs from immutable authority')


def _authority(call, store, objects):
    value, context = _validated(call)
    if objects.read(call_ref(value)) != canonical_json(to_mapping_value(value)):
        raise Conflict('child call object differs from its canonical descriptor')
    row = store.get('WorkflowChildCall', call_key(value)) if store is not None else None
    if row is not None and canonical_json(to_mapping_value(row.to_mapping()['value'])) != canonical_json(to_mapping_value(value)):
        raise Conflict('child call index differs from its object')
    return value, context


def _context_matches(expected, actual):
    wanted = expected.to_mapping()
    wanted['started_at'] = actual.to_mapping()['started_at']
    if wanted != actual.to_mapping() or not expected.started_at <= actual.started_at < expected.deadline:
        raise Conflict('child result has changed identity/settings/date/deadline/start')
    settings = Settings.from_mapping(actual.to_mapping()['effective_config'])
    if pin_context(settings, actual, actual.pinned_on)[0] != actual:
        raise Conflict('saved child context cannot reproduce its pin')


def _source_input(path, objects):
    body = objects.read(path)
    workset = decode_source_workset(body)
    if path != f'worksets/sec/source/sha256={workset.workset_id}/workset.json' or encode_workset(workset) != body:
        raise Conflict('source input path/bytes disagree')
    return workset


def _snapshot_input(path, store, objects):
    body = objects.read(path)
    snapshots = decode_snapshot_workset(body)
    sources = _source_input(f'worksets/sec/source/sha256={snapshots.source_workset_id}/workset.json', objects)
    if store is not None:
        snapshots, members = _pinned_members(path, objects, AcquisitionState(store))
    else:
        if path != f'worksets/sec/snapshot/sha256={snapshots.workset_id}/workset.json':
            raise Conflict('snapshot input path differs from content identity')
        if make_snapshot_workset(sources, snapshots.snapshots) != snapshots:
            raise Conflict('snapshot input differs from original source membership/context')
        members = {source.source_id: source for source in sources.members}
    if encode_workset(snapshots) != body:
        raise Conflict('snapshot input must use canonical bytes')
    for snapshot in snapshots.snapshots:
        objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
    return snapshots, members


def _transformed_input(path, store, objects):
    workset = decode_transformed(objects.read(path))
    if transformed_ref(workset) != path:
        raise Conflict('transformed input address differs')
    snapshots, members = _snapshot_input(workset.snapshot_workset_ref, store, objects)
    if workset.origin_context != snapshots.context:
        raise Conflict('transformed origin context differs from its pinned snapshot workset')
    snapshots_by_id = {snapshot.source_id: snapshot for snapshot in snapshots.snapshots}
    covered = []
    for ref in workset.observations:
        if ref.source != members.get(ref.source.source_id) or ref.snapshot != snapshots_by_id.get(ref.source.source_id):
            raise Conflict('transformed observation differs from exact source/raw binding')
        retained, _ = _read_manifest(ref.manifest_ref, objects)
        if retained != ref:
            raise Conflict('transformed observation differs from retained manifest')
        for _ in read_observations(ref, objects):
            pass
        if store is not None:
            row = store.get('Processing', processing_key(ref.source.source_id, ref.snapshot.sha256,
                                                       ref.parser_version, ref.schema_version))
            if row is None or row.to_mapping()['value']['observation'] != ref.to_mapping():
                raise Conflict('Processing contents differ from exact observation/version identity')
        covered.append(ref.source.source_id)
    covered.extend(gap.source_id for gap in workset.failures)
    if len(covered) != len(set(covered)) or set(covered) != set(members):
        raise Conflict('transformed successes/failures must account for every pinned member')
    return workset


def _validate_input_output(call, result, store, objects):
    command = result.context.command
    if command == 'discover':
        if result.snapshot_workset_ref is not None or result.source_workset_ref is None:
            raise Conflict('discovery child lacks its source-only output')
        workset = _source_input(result.source_workset_ref, objects)
        if workset.discovery_id != call['intent']['discovery_id']:
            raise Conflict('discovery output differs from requested session')
        for field in ('run_id', 'command', 'config_sha256', 'runtime', 'parser_version', 'schema_version', 'effective_config'):
            if getattr(workset.context, field) != getattr(result.context, field):
                raise Conflict('discovery output has changed frozen provenance')
    elif command == 'collect':
        source = _source_input(call['input_ref'], objects)
        if result.source_workset_ref != call['input_ref']:
            raise Conflict('collection result differs from exact requested source workset')
        for field in ('config_sha256', 'runtime', 'parser_version', 'schema_version', 'effective_config'):
            if getattr(source.context, field) != getattr(result.context, field):
                raise Conflict('collection settings differ from origin acquisition context')
        if result.snapshot_workset_ref is not None:
            snapshots, _ = _snapshot_input(result.snapshot_workset_ref, store, objects)
            if snapshots.source_workset_id != source.workset_id:
                raise Conflict('collection snapshot output belongs to another source workset')
    elif command == 'transform':
        _snapshot_input(call['input_ref'], store, objects)
        if result.input_ref != call['input_ref'] or result.transformed_workset_ref is None:
            raise Conflict('transform result lacks its exact input/output chain')
        workset = _transformed_input(result.transformed_workset_ref, store, objects)
        if workset.snapshot_workset_ref != call['input_ref'] or workset.context != result.context or workset.failures != result.gaps:
            raise Conflict('transform result differs from durable transformed workset')
    else:
        workset = _transformed_input(call['input_ref'], store, objects)
        if result.input_ref != call['input_ref'] or result.transformed_workset_ref != call['input_ref']:
            raise Conflict('publication result differs from exact transformed input')
        if (workset.context.parser_version, workset.context.schema_version) != (
                result.context.parser_version, result.context.schema_version):
            raise Conflict('publication input versions differ')
        for quarter in result.quarters:
            if quarter.outcome in ('published', 'unchanged'):
                body = objects.read(quarter.manifest_ref)
                capture = GenerationCapture(quarter.quarter, quarter.generation_id, quarter.manifest_ref,
                                            hashlib.sha256(body).hexdigest(), len(body))
                manifest = validated_manifest(capture, objects)
                if (manifest.parser_version, manifest.schema_version) != (
                        result.context.parser_version, result.context.schema_version):
                    raise Conflict('publication manifest versions differ')
            elif quarter.outcome == 'awaiting_approval':
                payload = parse_json(objects.read(quarter.candidate_ref))
                manifest_ref = payload['manifest_ref']
                body = objects.read(manifest_ref)
                capture = GenerationCapture(payload['quarter'], payload['generation_id'], manifest_ref,
                                            hashlib.sha256(body).hexdigest(), len(body))
                candidate = Candidate(read_manifest(capture, objects), manifest_ref,
                    capture.manifest_sha256, capture.manifest_bytes, quarter.candidate_ref)
                if candidate.manifest.quarter != quarter.quarter:
                    raise Conflict('candidate belongs to another quarter')
                validate_candidate(candidate, objects)
                if store is not None:
                    row = store.get('Candidate', candidate.manifest.generation_id)
                    if row is None or row.to_mapping()['value'] != candidate.to_mapping():
                        raise Conflict('gate candidate index differs from immutable evidence')


def read_child_capture(call, objects):
    value, expected = _authority(call, None, objects)
    result = (read_etl_result if expected.command in ('transform', 'publish') else read_result)(
        value['result_ref'], objects)
    _context_matches(expected, result.context)
    intent_path = value['result_ref'].rsplit('/', 1)[0] + '/command.json'
    frozen = ({'context': result.context.to_mapping(), 'intent': value['intent']}
              if expected.command in ('transform', 'publish') else value['intent'])
    if objects.read(intent_path) != canonical_json(to_mapping_value(frozen)):
        raise Conflict('child frozen command differs from expected intent/context')
    _validate_input_output(value, result, None, objects)
    return result


def read_child(call, store, objects):
    value, expected = _authority(call, store, objects)
    result = read_child_capture(value, objects)
    row = store.get('Attempt', attempt_key(result.context))
    saved = row.to_mapping()['value'] if row is not None else None
    if saved is None or saved['context'] != result.context.to_mapping() or saved['result'] != result.to_mapping():
        raise Conflict('child result requires repaired exact Attempt readback')
    _validate_input_output(value, result, store, objects)
    return result


def unfinished_child(call, store):
    value, expected = _validated(call)
    matches = [row for row in store.scan('Attempt', {})
               if all(to_mapping_value(row.value['context'][field]) == to_mapping_value(getattr(expected, field))
                      for field in ('run_id', 'command', 'attempt_id', 'execution_id', 'runtime'))]
    if len(matches) != 1:
        raise Conflict('unfinished child lacks one exact begun Attempt')
    row = matches[0].to_mapping()['value']
    actual = RunContext.from_mapping(row['context'])
    _context_matches(expected, actual)
    if row['result'] is not None:
        raise Conflict('unfinished child index already contains a result')
    return actual, tuple(Error.from_mapping(error) for error in row.get('structured_errors', ()))


class ChildUnfinished(RuntimeError):
    def __init__(self, call, outcome, gaps, code, stdout, stderr):
        super().__init__('child has no repaired immutable result: ' + outcome)
        self.call, self.outcome, self.gaps = call, outcome, gaps
        self.exit, self.stdout, self.stderr = code, stdout, stderr
        self.repair_pending = any(gap.retryable and gap.details.get('type') == 'PublicationRepairPending'
                                  for gap in gaps)
        self.resumable = self.repair_pending or call['context']['command'] == 'publish'
        self.details = {'contract_version': LOCAL_CONTRACT, 'call': to_mapping_value(call), 'outcome': outcome, 'exit': code, 'stdout': stdout,
                        'stderr': stderr, 'gaps': [gap.to_mapping() for gap in gaps],
                        'repair_pending': self.repair_pending, 'resumable': self.resumable}


def _flags(command, flags):
    if any(not isinstance(flag, str) for flag in flags):
        raise ValueError('child flags must contain only text')
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False, allow_abbrev=False)
    if command == 'discover':
        parser.add_argument('--mode', required=True, choices=('quarterly', 'daily'))
        parser.add_argument('--discovery-id', required=True)
        parser.add_argument('--refresh', action='store_true')
    else:
        parser.add_argument('--workset', required=True)
        if command == 'transform':
            parser.add_argument('--force', action='store_true')
    try:
        parsed = parser.parse_args(flags)
    except (SystemExit, argparse.ArgumentError) as error:
        raise ValueError('invalid command-specific child flags') from error
    names = [flag for flag in flags if flag.startswith('--')]
    if len(names) != len(set(names)):
        raise ValueError('duplicate child flags')
    return vars(parsed)


class Dispatcher:
    def __init__(self, context, settings, fixture_pack, state_dir, store, objects, observer=None, *, child_runner=runtime.run_child):
        if context.command not in WORKFLOW_COMMANDS or context.pinned_on is None:
            raise ValueError('dispatcher requires a pinned workflow context')
        if pin_context(settings, context, context.pinned_on)[0] != context:
            raise ValueError('workflow context differs from current settings')
        if settings.acquisition.mode == 'fixture':
            if fixture_pack is None:
                raise ValueError('fixture workflow requires its explicit pack')
            self.pack = FixturePack.load(fixture_pack)
        else:
            if fixture_pack is not None:
                raise ValueError('fixture inputs are forbidden for live acquisition')
            self.pack = None
        self.context, self.settings, self.fixture_pack = context, settings, fixture_pack
        self.state_dir, self.store, self.objects, self.observer = state_dir, store, objects, observer
        self.child_runner = child_runner

    def execute(self, command, step_id, settings, flags):
        if command not in CHILD_COMMANDS or not isinstance(flags, tuple):
            raise ValueError('child command/flags require their closed interface')
        if deployment_binding(settings) != deployment_binding(self.settings):
            raise Conflict('origin child settings differ from the shared storage/issuer binding')
        parsed = _flags(command, flags)
        parent = self.context
        attempt = child_attempt_id(parent.run_id, parent.command, parent.attempt_id, step_id, command)
        child = replace(parent, command=command, attempt_id=attempt,
            runtime=configured_descriptor(settings), parser_version=settings.etl.parser_version,
            schema_version=settings.etl.schema_version, config_sha256=settings.config_sha256,
            effective_config={}, pinned_on=None,
            priority='daily' if command == 'discover' and parsed['mode'] == 'daily' else 'backfill')
        if command == 'collect':
            child = replace(child, priority=_source_input(parsed['workset'], self.objects).context.priority)
        child = pin_context(settings, child, parent.pinned_on)[0]
        fixture = settings.acquisition.mode == 'fixture'
        today = parent.pinned_on if fixture and settings.fixture and settings.fixture.allow_clock_override else None
        digest = self.pack.manifest_sha256 if command in ('discover', 'collect') and self.pack else None
        call = make_call(child, command, attempt, parsed.get('workset'), digest,
            workflow_command=parent.command, workflow_attempt_id=parent.attempt_id, step_id=step_id,
            today=today, mode=parsed.get('mode'), discovery_id=parsed.get('discovery_id'),
            refresh=parsed.get('refresh', False), force=parsed.get('force', False))
        if command == 'collect':
            source = _source_input(call['input_ref'], self.objects)
            for field in ('config_sha256', 'runtime', 'parser_version', 'schema_version', 'effective_config'):
                if getattr(source.context, field) != getattr(child, field):
                    raise Conflict('collection dispatch differs from origin settings/versions')
        elif command in ('transform', 'publish'):
            supported_parser(child.parser_version, fixture=fixture)
            if command == 'transform':
                _snapshot_input(call['input_ref'], self.store, self.objects)
            else:
                transformed = _transformed_input(call['input_ref'], self.store, self.objects)
                if (transformed.context.parser_version, transformed.context.schema_version) != (
                        child.parser_version, child.schema_version):
                    raise Conflict('publication dispatch differs from transformed input versions')
        if self.fixture_pack is not None and FixturePack.load(self.fixture_pack).manifest_sha256 != self.pack.manifest_sha256:
            raise Conflict('fixture manifest changed after dispatcher construction')
        child_python, child_runtime = runtime.resolve_child(settings)
        if child_runtime != to_mapping_value(child.runtime):
            raise ValueError('child executable differs from pinned runtime')
        _remember_call(call, self.store, self.objects)
        observe(self.observer, 'workflow_child.after_call')
        key = call_key(call)
        previous = self.store.get('WorkflowChildExecution', key)
        sequence = 0
        if previous is not None:
            saved = previous.to_mapping()['value']
            fields = {'contract_version', 'format_version', 'call_ref', 'sequence', 'exit_ref', 'exit_sha256', 'exit_bytes'}
            if (set(saved) != fields or saved['contract_version'] != LOCAL_CONTRACT
                    or saved['format_version'] != 'sec-local-child-execution-v1'
                    or saved['call_ref'] != call_ref(call)
                    or type(saved['sequence']) is not int or saved['sequence'] < 0):
                raise Conflict('child execution receipt index fields differ')
            sequence = saved['sequence']
            prefix = call_ref(call).rsplit('/', 1)[0] + '/executions/' + str(sequence)
            launch = self._launch(call, sequence, child_python)
            if self.objects.read(prefix + '/launch.json') != canonical_json(to_mapping_value(launch)):
                raise Conflict('child execution receipt launch differs')
            if self.objects.read(prefix + '/config.json') != canonical_json(to_mapping_value(settings.to_mapping())):
                raise Conflict('child execution receipt config snapshot differs')
            if saved['exit_ref'] is None:
                if saved['exit_sha256'] is not None or saved['exit_bytes'] is not None:
                    raise Conflict('child execution receipt has an incomplete exit address')
                raise Conflict('ambiguous child execution cannot be automatically relaunched')
            if saved['exit_ref'] != prefix + '/exit.json':
                raise Conflict('child execution receipt exit reference differs')
            try:
                require_hash(saved['exit_sha256'], 'child exit sha256')
                if type(saved['exit_bytes']) is not int or saved['exit_bytes'] < 0:
                    raise ValueError('child exit bytes must be nonnegative')
                self.objects.verify(saved['exit_ref'], saved['exit_sha256'], saved['exit_bytes'])
            except (ValueError, OSError) as error:
                raise Conflict('child execution receipt exit bytes differ') from error
            execution, observed_at = self._read_exit(saved['exit_ref'], call, sequence)
            try:
                return self._check_exit(call, execution, observed_at)
            except ChildUnfinished as error:
                if not error.repair_pending:
                    raise
            sequence += 1
        else:
            try:
                self.objects.read(call_ref(call).rsplit('/', 1)[0] + '/executions/0/launch.json')
            except FileNotFoundError:
                pass
            else:
                raise Conflict('ambiguous child launch lacks its execution index')
        index = {'contract_version': LOCAL_CONTRACT, 'format_version': 'sec-local-child-execution-v1',
                 'call_ref': call_ref(call), 'sequence': sequence, 'exit_ref': None,
                 'exit_sha256': None, 'exit_bytes': None}
        if previous is not None:
            execution_row = self.store.replace('WorkflowChildExecution', key, index, previous.version)
        else:
            try:
                execution_row = self.store.insert('WorkflowChildExecution', key, index)
            except AlreadyExists as error:
                raise Conflict('ambiguous concurrent child execution cannot be relaunched') from error
        prefix = call_ref(call).rsplit('/', 1)[0] + '/executions/' + str(sequence)
        self.objects.put_once(prefix + '/launch.json', canonical_json(to_mapping_value(
            self._launch(call, sequence, child_python))))
        frozen_config = canonical_json(to_mapping_value(settings.to_mapping()))
        self.objects.put_once(prefix + '/config.json', frozen_config)
        with TemporaryDirectory(prefix='sec-workflow-child-') as directory:
            config = Path(directory) / 'config.json'
            config.write_bytes(frozen_config)
            config.chmod(0o444)
            argv = [*runtime.native_python_argv(child_python), '-m', 'sec_edgar_ingest', command, '--config', str(config), '--run-id', parent.run_id,
                '--execution-id', parent.execution_id, '--attempt-id', attempt,
                '--deadline', parent.deadline.isoformat(), *flags]
            if today is not None:
                argv.extend(('--today', today.isoformat()))
            if command in ('discover', 'collect') and self.fixture_pack is not None:
                argv.extend(('--fixture-pack', str(self.fixture_pack)))
            execution = self.child_runner(child_python, argv, deadline=child.deadline,
                environ=runtime.isolated_environment())
        observed_at = datetime.now(timezone.utc)
        exit_ref = prefix + '/exit.json'
        observed = {'contract_version': LOCAL_CONTRACT, 'format_version': 'sec-local-child-exit-v1',
            'call_ref': call_ref(call), 'sequence': sequence, 'returncode': execution.returncode,
            'stdout_hex': execution.stdout.hex(), 'stderr_hex': execution.stderr.hex(),
            'drained': execution.drained, 'observed_at': observed_at.isoformat()}
        exit_body = canonical_json(to_mapping_value(observed))
        self.objects.put_once(exit_ref, exit_body)
        self.store.replace('WorkflowChildExecution', key,
            {**index, 'exit_ref': exit_ref, 'exit_sha256': hashlib.sha256(exit_body).hexdigest(),
             'exit_bytes': len(exit_body)}, execution_row.version)
        result = self._check_exit(call, execution, observed_at)
        observe(self.observer, 'workflow_child.after_result')
        return result

    def _launch(self, call, sequence, python):
        return {'contract_version': LOCAL_CONTRACT, 'format_version': 'sec-local-child-launch-v1',
            'call_ref': call_ref(call), 'sequence': sequence, 'python': str(python),
            'runtime': to_mapping_value(call['context']['runtime']),
            'config_sha256': call['context']['config_sha256']}

    def _read_exit(self, path, call, sequence):
        body = self.objects.read(path)
        fields = {'contract_version', 'format_version', 'call_ref', 'sequence', 'returncode',
                  'stdout_hex', 'stderr_hex', 'drained', 'observed_at'}
        try:
            value = parse_json(body)
            if (not isinstance(value, dict) or set(value) != fields or value['contract_version'] != LOCAL_CONTRACT
                    or value['format_version'] != 'sec-local-child-exit-v1'
                    or value['call_ref'] != call_ref(call) or type(value['sequence']) is not int
                    or value['sequence'] != sequence or type(value['returncode']) is not int
                    or type(value['drained']) is not bool or canonical_json(value) != body):
                raise ValueError('closed exit fields differ')
            stdout, stderr = bytes.fromhex(value['stdout_hex']), bytes.fromhex(value['stderr_hex'])
            if (stdout.hex(), stderr.hex()) != (value['stdout_hex'], value['stderr_hex']):
                raise ValueError('noncanonical output encoding')
            observed_at = datetime.fromisoformat(value['observed_at'])
            if observed_at.tzinfo != timezone.utc or observed_at.isoformat() != value['observed_at']:
                raise ValueError('observation time must use canonical UTC')
        except (ValueError, TypeError, KeyError) as error:
            raise Conflict('child execution receipt fields differ') from error
        return runtime.ChildExit(value['returncode'], stdout, stderr, value['drained']), observed_at

    def _check_exit(self, call, execution, observed_at):
        child = RunContext.from_mapping(to_mapping_value(call['context']))
        command = child.command
        code = execution.returncode
        stdout = execution.stdout.decode('utf-8', errors='replace')
        stderr = execution.stderr.decode('utf-8', errors='replace')
        if not execution.drained:
            raise Conflict('child shutdown/drain was not confirmed')
        if not child.started_at <= observed_at < child.deadline:
            raise Conflict('child completed after its deadline')
        try:
            result = read_child(call, self.store, self.objects)
        except FileNotFoundError:
            _, gaps = unfinished_child(call, self.store)
            outcome = next((gap.code for gap in gaps), 'internal_error')
            if exit_code(outcome) != code:
                raise Conflict('unfinished retained error differs from child exit')
            try:
                printed = parse_json(execution.stdout)
            except ValueError as error:
                raise Conflict('unfinished child stdout lacks its result descriptor') from error
            if printed != {'outcome': outcome, 'result_ref': None,
                           'source_workset_ref': None, 'snapshot_workset_ref': None}:
                raise Conflict('unfinished child stdout differs from retained error')
            raise ChildUnfinished(call, outcome, gaps, code, stdout, stderr)
        if exit_code(result.outcome) != code:
            raise Conflict('durable child result differs from child exit')
        try:
            printed = parse_json(execution.stdout)
        except ValueError as error:
            raise Conflict('child stdout lacks its exact result descriptor') from error
        expected_stdout = {'outcome': result.outcome, 'result_ref': call['result_ref']}
        if command in ('transform', 'publish'):
            expected_stdout.update(input_ref=result.input_ref,
                transformed_workset_ref=result.transformed_workset_ref)
        else:
            expected_stdout.update(source_workset_ref=result.source_workset_ref,
                snapshot_workset_ref=result.snapshot_workset_ref)
        if printed != expected_stdout:
            raise Conflict('child stdout differs from independently read durable result')
        return CheckedChild(call, call['result_ref'], result)
