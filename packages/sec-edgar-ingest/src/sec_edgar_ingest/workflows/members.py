import hashlib
from collections.abc import Iterable, Mapping
from datetime import datetime

from ..models import RunContext, Snapshot, canonical_json, parse_json, to_mapping_value
from ..storage.contracts import Conflict
from .contracts import COMPLETE, CompletionEvaluation, MemberResult, workflow_path
from .provenance import immutable, project_member, projection, read_member, read_parent, read_source, source_ref

class WorkflowMembers:
    def __init__(self, store, objects):
        self.store, self.objects = store, objects

    def inventory(self):
        from ..models import Error, error_text
        valid, gaps = [], []
        for row in self.store.scan('WorkflowMember', {}):
            value = row.to_mapping()['value']
            try:
                read_member(value, self.store, self.objects)
                valid.append(value)
            except (ValueError, OSError, Conflict, KeyError, TypeError) as error:
                identity = value.get('member_id') if isinstance(value, dict) else None
                gaps.append(Error('legacy_member_unresolved', error_text(error), False, None,
                    {'record_kind': 'WorkflowMember', 'member_id': identity,
                     'record_sha256': __import__('hashlib').sha256(canonical_json(to_mapping_value(value))).hexdigest()}))
        return tuple(sorted(valid, key=lambda v: (v['source']['period'], v['source']['source_id'], v['member_id']))), tuple(gaps)

    def all(self):
        values, gaps = self.inventory()
        if gaps:
            raise Conflict('registry contains unresolved corrupt members')
        return values

    def register(self, parent_ref, member_ref):
        selected = read_source(member_ref, self.objects)
        if len(selected.members) != 1:
            raise Conflict('registry requires singleton member')
        parent = read_parent(parent_ref, self.store, self.objects)
        expected = projection(parent, selected.members[0].source_id)
        if selected != expected or source_ref(expected) != member_ref:
            raise Conflict('registered member differs from exact projection')
        return project_member(parent_ref, selected.members[0].source_id, self.store, self.objects)

    def _path(self, member_id, context):
        return workflow_path(context).rsplit('/', 1)[0] + '/members/' + member_id + '/result.json'

    def _descriptor(self, result, context, body):
        return {'ref': self._path(result.member_id, context),
                'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body),
                'member_id': result.member_id, 'parser_version': result.parser_version,
                'schema_version': result.schema_version}

    def _read_receipt(self, path):
        from .processing import validate_member_evidence
        body = self.objects.read(path)
        receipt = parse_json(body)
        if (not isinstance(receipt, dict) or set(receipt) != {'format_version', 'context', 'result', 'evidence'}
                or canonical_json(to_mapping_value(receipt)) != body
                or receipt['format_version'] != 'sec-workflow-member-receipt-v1'):
            raise Conflict('member receipt canonical bytes/schema differ')
        result = MemberResult.from_mapping(receipt['result'])
        context = RunContext.from_mapping(receipt['context'])
        if path != self._path(result.member_id, context):
            raise Conflict('member receipt path differs from context/member')
        self._validate_context(result, context, receipt['evidence'])
        validate_member_evidence(result, receipt['evidence'], self.objects)
        return result, context, receipt['evidence'], body

    def _validate_context(self, result, context, evidence):
        from ..config import Settings, pin_context
        try:
            settings = Settings.from_mapping(context.to_mapping()['effective_config'])
            pinned = pin_context(settings, context, context.pinned_on)[0]
        except (ValueError, TypeError) as error:
            raise Conflict('member receipt workflow context cannot reproduce its original pin') from error
        if pinned != context:
            raise Conflict('member receipt workflow context changes its original pin')
        if (result.parser_version, result.schema_version) != (context.parser_version, context.schema_version):
            raise Conflict('member result versions differ from workflow context')
        for call in evidence['calls']:
            child = RunContext.from_mapping(call['context'])
            if (child.run_id, call['workflow_command'], call['workflow_attempt_id'], child.execution_id,
                    child.started_at, child.deadline, child.pinned_on) != (
                    context.run_id, context.command, context.attempt_id, context.execution_id,
                    context.started_at, context.deadline, context.pinned_on):
                raise Conflict('member child differs from original workflow namespace/context')
            if not call['step_id'].startswith('repair-') and child.command != 'collect':
                if child.effective_config != context.effective_config or child.image_digest != context.image_digest:
                    raise Conflict('member child differs from current workflow settings')

    def record(self, result, context, evidence) -> Mapping:
        from .processing import validate_member_evidence
        from .checked import unfinished_child
        evidence = to_mapping_value(evidence)
        read_member(evidence['member'], self.store, self.objects)
        self._validate_context(result, context, evidence)
        validate_member_evidence(result, evidence, self.objects)
        terminal = evidence['terminal_error']
        if terminal is not None:
            actual, gaps = unfinished_child(terminal['call'], self.store)
            retained = parse_json(self.objects.read(terminal['call']['result_ref'].rsplit('/', 1)[0] + '/terminal.json'))
            if actual.to_mapping() != retained['context'] or [g.to_mapping() for g in gaps] != terminal['gaps']:
                raise Conflict('member terminal capture differs from persisted Attempt')
        path = self._path(result.member_id, context)
        receipt = {'format_version': 'sec-workflow-member-receipt-v1', 'context': context.to_mapping(),
                   'result': result.to_mapping(), 'evidence': evidence}
        body = canonical_json(to_mapping_value(receipt))
        self.objects.put_once(path, body)
        index = self._descriptor(result, context, body)
        self.objects.verify(path, index['sha256'], index['bytes'])
        key = hashlib.sha256(canonical_json(to_mapping_value([context.run_id, context.command, context.attempt_id,
            result.member_id, result.parser_version, result.schema_version]))).hexdigest()
        immutable(self.store, 'WorkflowMemberResult', key, index)
        return index

    def replay(self, value, context):
        path = self._path(value['member_id'], context)
        try:
            self.objects.read(path)
        except FileNotFoundError:
            return None
        result, saved_context, evidence, body = self._read_receipt(path)
        if saved_context != context or evidence['member'] != to_mapping_value(value):
            raise Conflict('exact member replay changes frozen context/projection')
        self.record(result, saved_context, evidence)
        return result, evidence

    def completed(self, value, parser_version, schema_version, *, repairs=True) -> Mapping | None:
        from .completion import outstanding_repairs, validate_capture
        from ..state import AcquisitionState
        value = to_mapping_value(value)
        read_member(value, self.store, self.objects)
        if repairs and outstanding_repairs(value, self.store, self.objects):
            return None
        candidates = []
        for row in self.store.scan('WorkflowMemberResult', {'member_id': value['member_id'],
                'parser_version': parser_version, 'schema_version': schema_version}):
            descriptor = row.to_mapping()['value']
            if set(descriptor) != {'ref', 'sha256', 'bytes', 'member_id', 'parser_version', 'schema_version'}:
                raise Conflict('member receipt descriptor fields differ')
            self.objects.verify(descriptor['ref'], descriptor['sha256'], descriptor['bytes'])
            result, context, evidence, body = self._read_receipt(descriptor['ref'])
            if descriptor != self._descriptor(result, context, body) or evidence['member'] != value:
                raise Conflict('member receipt descriptor/projection correlation differs')
            if (result.parser_version, result.schema_version) != (parser_version, schema_version):
                raise Conflict('receipt version lookup differs from decoded versions')
            if result.outcome not in COMPLETE:
                continue
            capture = evidence['completion']
            binding = AcquisitionState(self.store).binding(value['member_id'], value['source']['source_id'])
            if binding is None or binding.to_mapping() != capture['binding']:
                raise Conflict('historical completed receipt changes immutable raw pin')
            validate_capture(capture, self.objects)
            candidates.append(capture)
        if not candidates:
            return None
        capture = sorted(candidates, key=lambda item: canonical_json(to_mapping_value(item)))[0]
        return CompletionEvaluation(True, capture, (), ()).capture


def download_times(value: Mapping, sha256: str, store) -> frozenset[datetime]:
    """When this member itself downloaded these bytes, from its append-only promotion receipts.

    Identical bytes keep their first Snapshot receipt, so only a member's own receipts date its downloads.
    A member bound without downloading (reuse) has none.
    """
    from ..state import AcquisitionState
    receipt = AcquisitionState(store).promotion_receipt(value['member_id'], value['source']['source_id'])
    return frozenset(() if receipt is None else (Snapshot.from_mapping(snapshot).received_at
                     for snapshot in receipt['snapshots'] if snapshot['sha256'] == sha256))


class SourceDownloads:
    """Every own download by the retained members of some sources, indexed once per selection.

    Every promotion receipt counts, whatever bytes its member is pinned to: a losing concurrent collector of a
    member keeps its receipt but not the pin, and its download still shows what the SEC served. A member whose
    Binding or receipts cannot be read is kept in `unreadable`, and nothing of its source is superseded.
    Each source's latest downloaded snapshot is read too (`latest`), because a download outside the retained
    members moves it without leaving a receipt here; a source whose row cannot be read is tainted the same way.
    """

    def __init__(self, retained: Iterable[Mapping], finished: Iterable[Mapping], sources: Mapping[str, Mapping], store):
        from ..state import AcquisitionState
        acquisition, done = AcquisitionState(store), {value['member_id'] for value in finished}
        self.served, self.completed, self.pinned, self.latest = {}, {}, {}, {}
        self.unreadable, self.tainted = [], set()
        for identity in sources:
            try:
                row = acquisition.get_source(identity)
                self.latest[identity] = None if row is None else row.to_mapping()['value']['latest_downloaded_snapshot']
            except (ValueError, OSError, Conflict, KeyError, TypeError):
                self.tainted.add(identity)  # an unreadable latest download keeps every hold of its source
        for other in retained:
            identity = other['source']['source_id']
            if sources.get(identity) != other['source']:
                continue
            try:
                binding = acquisition.binding(other['member_id'], identity)
                receipt = acquisition.promotion_receipt(other['member_id'], identity)
                snapshots = () if receipt is None else tuple(Snapshot.from_mapping(value) for value in receipt['snapshots'])
            except (ValueError, OSError, Conflict, KeyError, TypeError) as error:
                self.unreadable.append((other, error))
                self.tainted.add(identity)
                continue
            pinned = None if binding is None else binding.snapshot_sha256
            self.pinned[other['member_id']] = pinned
            for snapshot in snapshots:
                download = (snapshot.received_at, other)
                self.served.setdefault((identity, snapshot.sha256), []).append(download)
                # A completion is dated only by its own download of the bytes it completed with.
                if other['member_id'] in done and snapshot.sha256 == pinned:
                    newest = self.completed.get(identity)
                    if newest is None or _order(download) > _order(newest):
                        self.completed[identity] = download

    def supersession(self, value: Mapping) -> dict | None:
        """The newest completed download of this member's source, when strictly later than the SEC last served
        this member's pinned bytes to any retained member of the source.

        Dating the pending side by its bytes covers members bound by reuse and losing collectors' downloads,
        and keeps a gate that the SEC re-serves (A, then A+B, then A again) standing. A download recorded
        under a workset that is no retained member (`collect --workset <parent>`, or a member that fails
        inventory) has no receipt here but still moves the source's latest download, the signal
        `etl.approval.superseding` reads: while that is this member's pinned bytes, nothing supersedes it.
        """
        identity, pinned = value['source']['source_id'], self.pinned.get(value['member_id'])
        served = self.served.get((identity, pinned))
        completed = self.completed.get(identity)
        if identity in self.tainted or not served or completed is None or self.latest.get(identity) == pinned:
            return None
        (served_at, served_by), (later, by) = max(served, key=_order), completed
        if later <= served_at:
            return None
        return {'member': value, 'by': by, 'served_by': served_by, 'downloaded_at': served_at.isoformat(),
                'by_downloaded_at': later.isoformat()}


def _order(download: tuple[datetime, Mapping]) -> tuple[datetime, str]:
    return download[0], download[1]['member_id']
