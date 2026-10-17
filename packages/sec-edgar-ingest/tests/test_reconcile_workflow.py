"""Offline reconcile workflow: shared runner, refreshed quarterly selection, corrections and gates."""
from network_guard import install
install()

import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from support_approval import GateFixture, row
from support_etl import etl_context
from support_reconcile import A, B, C, X, Y, ReconcileFixture
from support_reconcile import sha
from sec_edgar_ingest.etl.approval import approve
from sec_edgar_ingest.etl.contracts import processing_key
from sec_edgar_ingest.etl.history import withdrawal_candidates
from sec_edgar_ingest.etl.manifest import approval_ref, read_manifest
from sec_edgar_ingest.etl.reader import capture_from_pointer
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.transform import transform_member
from sec_edgar_ingest.models import Binding, Snapshot, canonical_json, parse_json
from sec_edgar_ingest.state import AcquisitionState
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows.checked import Dispatcher
from sec_edgar_ingest.workflows.completion import accounts_for
from sec_edgar_ingest.workflows.members import WorkflowMembers, download_times
from sec_edgar_ingest.workflows.results import _validate_selection, read_workflow_result
from sec_edgar_ingest.workflows.runner import source_revert_gaps


class ReconcileWorkflowTests(ReconcileFixture):
    def baseline(self):
        h = self.harness((A, B))
        code, _, report = self.run_phase(h, 'backfill', 'base')
        self.assertEqual((code, report.outcome), (0, 'success'), h.calls[-1])
        return h, report

    def test_unchanged_reconcile_refreshes_through_the_shared_runner(self):
        h, baseline = self.baseline()
        pointers = {quarter: EtlState(h.store).pointer(quarter) for quarter in ('2026Q3', '2026Q4')}
        code, message, report = self.run_phase(h, 'reconcile', 'same', (A, B))
        self.assertEqual((code, report.outcome), (0, 'unchanged'), h.calls[-1])
        self.assertEqual(message['result_ref'], 'runs/sec/same/reconcile/a/result.json')
        self.assertEqual((report.context.command, report.context.priority), ('reconcile', 'reconciliation'))
        self.assertEqual(report.requested_quarters, ('2026Q3', '2026Q4'))
        self.assertEqual((report.counts['published_quarters'], report.counts['unchanged_quarters']), (0, 2))
        calls = report.to_mapping()['intent']['child_calls']
        discovery = calls[0]
        self.assertEqual((discovery['intent']['mode'], discovery['intent']['refresh'],
                          discovery['intent']['discovery_id'], discovery['context']['priority']),
                         ('quarterly', True, 'workflow-reconcile-same', 'backfill'))
        self.assertEqual({call['context']['command'] for call in calls},
                         {'discover', 'collect', 'transform', 'publish'})
        self.assertIs(baseline.to_mapping()['intent']['child_calls'][0]['intent']['refresh'], False)
        self.assertEqual({quarter: EtlState(h.store).pointer(quarter) for quarter in pointers}, pointers)
        with self.assertRaises(SystemExit):
            h.invoke('reconcile', ('--refresh',), run='public-refresh')

    def test_corrections_update_and_add_while_open_quarter_absence_is_retained(self):
        h, _ = self.baseline()
        revised = ('123456', 'A Revised', *A[2:])
        code, _, report = self.run_phase(h, 'reconcile', 'fix', (revised, B, C), (X,))
        self.assertEqual((code, report.outcome), (0, 'success'), h.calls[-1])
        closed = read_manifest(h.capture('2026Q3')[0], h.objects)
        self.assertEqual((closed.updated, closed.added, closed.withdrawn, closed.gate), (1, 1, 0, 'clear'))
        self.assertEqual(self.names(h, '2026Q3'), ['A Revised', 'B', 'C'])
        opened = read_manifest(h.capture('2026Q4')[0], h.objects)
        self.assertEqual((opened.quarter_mode, opened.unresolved_absence, opened.withdrawn), ('open', 1, 0))
        self.assertEqual(self.names(h, '2026Q4'), ['X', 'Y'])

    def test_closed_withdrawal_beside_an_unchanged_quarter_awaits_approval(self):
        h, _ = self.baseline()
        before = EtlState(h.store).pointer('2026Q3')
        code, _, report = self.run_phase(h, 'reconcile', 'gate', (A,))
        self.assertEqual((code, report.outcome), (10, 'awaiting_approval'), h.calls[-1])
        self.assertEqual((report.counts['awaiting_approval_quarters'], report.counts['pending_sources'],
                          report.counts['complete_sources']), (1, 1, 1))
        self.assertEqual(EtlState(h.store).pointer('2026Q3'), before)
        self.assertEqual(self.names(h, '2026Q3'), ['A', 'B'])

    def test_invalid_correction_keeps_the_prior_generation_and_names_its_quarter(self):
        h, _ = self.baseline()
        before = EtlState(h.store).pointer('2026Q3')
        conflict = ('123456', 'Conflict', *A[2:])
        code, _, report = self.run_phase(h, 'reconcile', 'invalid', (A, conflict, B))
        self.assertEqual((code, report.outcome), (3, 'incomplete'), h.calls[-1])
        self.assertEqual(report.counts['quarantined_sources'], 1)
        self.assertEqual([member.source.period for member in report.members if member.quarantined], ['2026Q3'])
        self.assertEqual(EtlState(h.store).pointer('2026Q3'), before)

    def test_selection_requires_refresh_exactly_for_reconcile(self):
        execute = Dispatcher.execute

        def flipped(dispatcher, command, step_id, settings, flags):
            if command == 'discover':
                flags = (tuple(flag for flag in flags if flag != '--refresh') if '--refresh' in flags
                         else (*flags, '--refresh'))
            return execute(dispatcher, command, step_id, settings, flags)

        h = self.harness((A, B))
        with patch.object(Dispatcher, 'execute', flipped):
            for command in ('backfill', 'daily', 'reconcile'):
                with self.subTest(command=command):
                    code, message = h.invoke(command, run='flipped-' + command)
                    self.assertEqual((code, message['outcome']), (9, 'state_conflict'), h.calls[-1])
                    self.assertIn('refresh differs from its workflow command', h.calls[-1]['stderr'])



class SupersessionRuleTests(GateFixture):
    def test_accounts_for_exact_or_strictly_later_same_source_observation(self):
        first = self.observation(rows=row() + row(number=2))
        later = self.observation(rows=row(), seconds=1)
        # Strictly later, different bytes and the same versions: only the source differs from `later`.
        daily = self.observation(period='2026-10-02', kind='daily', rows=row(), seconds=1)
        # Same source and receipt time as `first` but different bytes: only the strict `>` rejects it.
        simultaneous = self.observation(rows=row('Other'))
        self.assertTrue(accounts_for(first, first))
        self.assertTrue(accounts_for(later, first))
        self.assertFalse(accounts_for(first, later))
        self.assertFalse(accounts_for(None, first))
        self.assertFalse(accounts_for(daily, first))
        self.assertFalse(accounts_for(simultaneous, first))
        settings, context = etl_context('fixture-index-parser-v2', command='publish')
        upgraded = transform_member(later.source, later.snapshot, context, settings, self.objects, self.state)
        self.assertFalse(accounts_for(upgraded, first))


class SupersessionWorkflowTests(ReconcileFixture):
    def gate_then_revert(self, h):
        """Base (A, B), a gated (A,) reconcile, then one back on (A, B) that completes during its own run."""
        self.assertEqual(self.run_phase(h, 'backfill', 'base')[0], 0)
        code, _, gated = self.run_phase(h, 'reconcile', 'gate', (A,))
        self.assertEqual(code, 10, h.calls[-1])
        code, _, first = self.run_phase(h, 'reconcile', 'revert-1', (A, B))
        self.assertEqual(code, 10, h.calls[-1])
        held, = [member for member in gated.members if member.outcome == 'awaiting_approval']
        return held, first

    def member(self, h, report, period, *, held=False):
        """The registered value of the member this report processed for the period, held for approval or not."""
        member_id, = [member.member_id for member in report.members if member.source.period == period
                      and (member.outcome == 'awaiting_approval') == held]
        return h.store.get('WorkflowMember', member_id).to_mapping()['value']

    def receipt_time(self, h, value):
        """This member's own newest download time, from its promotion receipts."""
        receipt = AcquisitionState(h.store).promotion_receipt(value['member_id'], value['source']['source_id'])
        return receipt['snapshots'][-1]['received_at']

    def download(self, h, value, sha256, at, *, under=None):
        """A further download of known bytes of this member's source, recorded as `collect_member` records one.

        It is recorded under the member itself (a concurrent collector of it) or under another workset `under`.
        `collect_member` checkpoints the promotion before `bind_once`, so a losing collector keeps its receipt
        while the member stays pinned to the winner's bytes.
        """
        acquisition, identity = AcquisitionState(h.store), value['source']['source_id']
        workset_id = value['member_id'] if under is None else under
        snapshot = acquisition.snapshot(identity, sha256)
        staged = {'workset_id': workset_id, 'source_id': identity,
                  'receipt': {'sha256': sha256, 'byte_count': snapshot.byte_count, 'received_at': at.isoformat()}}
        checkpoint = hashlib.sha256(canonical_json(staged)).hexdigest()
        h.store.insert('StagedReceipt', checkpoint, {**staged, 'checkpoint_id': checkpoint})
        downloaded = Snapshot.from_mapping({**snapshot.to_mapping(), 'received_at': at.isoformat()})
        acquisition.record_promotion(workset_id, downloaded)
        acquisition.remember_snapshot(downloaded)
        return acquisition.bind_once(Binding(workset_id, identity, sha256))

    def test_superseded_gated_member_completes_on_the_following_reconcile(self):
        h = self.harness((A, B))
        self.assertEqual(self.run_phase(h, 'backfill', 'base')[0], 0)
        code, _, first = self.run_phase(h, 'reconcile', 'gate-1', (A,))
        self.assertEqual((code, first.counts['awaiting_approval_quarters']), (10, 1), h.calls[-1])
        # Both gated members stay pending in this run whatever their processing order.
        code, _, second = self.run_phase(h, 'reconcile', 'gate-2', (A, C))
        self.assertEqual((code, second.outcome), (10, 'awaiting_approval'), h.calls[-1])
        latest = next(candidate for candidate in self.candidates(h)
                      if candidate.manifest.membership_source.snapshot.sha256 == sha((A, C)))
        approved = approve('2026Q3', latest.manifest.generation_id, sha((A, C)), 'Lowell Mason',
                           h.objects, EtlState(h.store))
        self.assertEqual(approved.outcome, 'success')
        code, _, report = self.run_phase(h, 'reconcile', 'after-approval', (A, C))
        self.assertEqual((code, report.outcome), (0, 'unchanged'), h.calls[-1])
        self.assertEqual(self.names(h, '2026Q3'), ['A', 'C'])

    def test_revert_to_older_bytes_is_reported_not_published(self):
        h = self.harness((A, B))
        self.assertEqual(self.run_phase(h, 'backfill', 'base')[0], 0)
        code, _, added = self.run_phase(h, 'reconcile', 'add', (A, B, C))
        self.assertEqual((code, added.outcome), (0, 'success'), h.calls[-1])
        active = EtlState(h.store).pointer('2026Q3')
        code, _, report = self.run_phase(h, 'reconcile', 'revert', (A, B))
        self.assertEqual((code, report.outcome), (3, 'incomplete'), h.calls[-1])
        gap, = [gap for gap in report.gaps if gap.code == 'source_reverted']
        self.assertTrue(gap.retryable)
        self.assertEqual((gap.details['quarter'], gap.details['observed_sha256'], gap.details['active_sha256']),
                         ('2026Q3', sha((A, B)), sha((A, B, C))))
        source_id = next(m.source.source_id for m in report.members if m.source.period == '2026Q3')
        self.assertEqual((gap.source_id, gap.details['generation_id']),
                         (source_id, capture_from_pointer(active).generation_id))
        first, held, observed = (datetime.fromisoformat(gap.details[name])
                                 for name in ('first_received_at', 'active_received_at', 'observed_at'))
        self.assertLess(first, held)
        self.assertLess(held, observed)
        self.assertEqual(EtlState(h.store).pointer('2026Q3'), active)
        self.assertEqual(self.names(h, '2026Q3'), ['A', 'B', 'C'])

    def test_gated_then_reverted_member_is_superseded_by_the_later_download(self):
        h = self.harness((A, B))
        code, _, backfill = self.run_phase(h, 'backfill', 'base')
        self.assertEqual(code, 0, h.calls[-1])
        base = EtlState(h.store).pointer('2026Q3')
        code, _, gated = self.run_phase(h, 'reconcile', 'gate', (A,))
        self.assertEqual((code, gated.outcome), (10, 'awaiting_approval'), h.calls[-1])
        # A plain backfill binds its member to the gated bytes by reuse: pending too, with no download receipt.
        code, _, plain = self.run_phase(h, 'backfill', 'plain', (A,))
        self.assertEqual((code, plain.outcome), (10, 'awaiting_approval'), h.calls[-1])
        # The SEC reverts to the base bytes; that download completes during this run, so the gate still holds it.
        code, _, first = self.run_phase(h, 'reconcile', 'revert-1', (A, B))
        self.assertEqual((code, first.outcome), (10, 'awaiting_approval'), h.calls[-1])
        code, message, report = self.run_phase(h, 'reconcile', 'revert-2', (A, B))
        self.assertEqual((code, report.outcome, report.counts['awaiting_approval_quarters']), (0, 'unchanged', 0),
                         h.calls[-1])
        self.assertEqual(report.intent['unresolved_before'], 0)
        selection = parse_json(h.objects.read(report.intent['selection']['ref']))
        self.assertEqual(selection['format_version'], 'sec-workflow-selection-v2')
        held = sorted({member.member_id for member in (*gated.members, *plain.members)
                       if member.outcome == 'awaiting_approval'})
        self.assertEqual(len(held), 2)  # the gated download and the reuse-bound backfill member
        # Same period and source, so the frozen order reduces to member id.
        self.assertEqual([entry['member']['member_id'] for entry in selection['superseded']], held)
        for entry in selection['superseded']:
            self.assertIn(entry['by']['member_id'], [member.member_id for member in first.members])
            self.assertLess(datetime.fromisoformat(entry['downloaded_at']),
                            datetime.fromisoformat(entry['by_downloaded_at']))
        # Both are dated by the gated bytes' newest download, the reuse-bound member having none of its own.
        self.assertEqual(len({entry['downloaded_at'] for entry in selection['superseded']}), 1)
        self.assertFalse(set(held) & {member.member_id for member in report.members})
        self.assertEqual(EtlState(h.store).pointer('2026Q3'), base)
        self.assertEqual(self.names(h, '2026Q3'), ['A', 'B'])
        # The SEC serves the gated bytes again. Its first run still drops both held members, the completed
        # revert being the newest completed download when the run selects; the run after it dates the gated
        # bytes by that new download, so the held members come back.
        code, _, again = self.run_phase(h, 'reconcile', 'gate-again', (A,))
        self.assertEqual((code, again.outcome), (10, 'awaiting_approval'), h.calls[-1])
        lagged = parse_json(h.objects.read(again.intent['selection']['ref']))
        self.assertEqual([entry['member']['member_id'] for entry in lagged['superseded']], held)
        code, _, restored = self.run_phase(h, 'reconcile', 'gate-again-2', (A,))
        self.assertEqual((code, restored.outcome), (10, 'awaiting_approval'), h.calls[-1])
        latest = parse_json(h.objects.read(restored.intent['selection']['ref']))
        self.assertEqual(latest['superseded'], [])
        self.assertLessEqual(set(held), {value['member_id'] for value in latest['members']})
        # The stored report still validates after the store moved on.
        self.assertEqual(read_workflow_result(message['result_ref'], h.store, h.objects), report)
        # The frozen witness is the gated download, whose own receipt dates the gated bytes.
        gated_id, = [member.member_id for member in gated.members if member.outcome == 'awaiting_approval']
        self.assertEqual({entry['served_by']['member_id'] for entry in selection['superseded']}, {gated_id})
        entry = selection['superseded'][0]
        backfilled = self.member(h, backfill, '2026Q3')  # completed, downloaded before the gated bytes
        pending = self.member(h, again, '2026Q3', held=True)  # the gated bytes' new download
        elsewhere = self.member(h, first, '2026Q4')  # a completed download of another source
        # Each label names the clause its forgery breaks, with genuine evidence in every field it leaves alone.
        # Two also break a second clause: the `not later` time is absent from `by`'s receipts, and the
        # `other source` member has no Binding under the pending member's source.
        later = datetime.fromisoformat(entry['by_downloaded_at'])
        for label, forgery in (
                ('not later', {'by_downloaded_at': entry['downloaded_at']}),
                ('unrecorded', {'downloaded_at': '2000-01-01T00:00:00+00:00'}),
                ('earlier completion', {'by': backfilled, 'by_downloaded_at': self.receipt_time(h, backfilled)}),
                ('not completed', {'by': pending, 'by_downloaded_at': self.receipt_time(h, pending)}),
                ('other source', {'by': elsewhere, 'by_downloaded_at': self.receipt_time(h, elsewhere)}),
                ('witness lacks the time', {'served_by': pending}),
                ('completion time unrecorded', {'by_downloaded_at': (later + timedelta(microseconds=1)).isoformat()})):
            forged = {**selection, 'superseded': [{**entry, **forgery}, *selection['superseded'][1:]]}
            with self.subTest(label), self.assertRaisesRegex(Conflict, 'lacks its later completed download'):
                _validate_selection(forged, report.context, selection['invocation'], h.store, h.objects)
        # A witness from another source, given a forged receipt row of the pinned bytes at the frozen time under
        # its own source, fails only the shared-source clause.
        acquisition = AcquisitionState(h.store)
        pinned = acquisition.snapshot(entry['member']['source']['source_id'], sha((A,)))
        receipt = {'workset_id': elsewhere['member_id'], 'source_id': elsewhere['source']['source_id'],
                   'snapshot': {**pinned.to_mapping(), 'received_at': entry['downloaded_at']}}
        checkpoint = hashlib.sha256(canonical_json(receipt)).hexdigest()
        h.store.insert('PromotionReceipt', checkpoint, {**receipt, 'checkpoint_id': checkpoint})
        # The frozen time is now among the witness's receipts of the pinned bytes, and `by` stays genuine.
        self.assertIn(datetime.fromisoformat(entry['downloaded_at']), download_times(elsewhere, sha((A,)), h.store))
        forged = {**selection, 'superseded': [{**entry, 'served_by': elsewhere}, *selection['superseded'][1:]]}
        with self.subTest('witness from another source'), self.assertRaisesRegex(
                Conflict, 'lacks its later completed download'):
            _validate_selection(forged, report.context, selection['invocation'], h.store, h.objects)

    def test_a_losing_collectors_later_download_of_the_gated_bytes_keeps_the_hold(self):
        h = self.harness((A, B))
        held, first = self.gate_then_revert(h)
        by = self.member(h, first, '2026Q3')
        # A second collector of the completed (A, B) member downloads the gated bytes after the first one's
        # download and loses bind_once: the SEC's newest bytes are the gated ones again.
        winner = self.download(h, by, sha((A,)), datetime.now(timezone.utc))
        self.assertEqual(winner.snapshot_sha256, sha((A, B)))
        code, _, report = self.run_phase(h, 'reconcile', 'revert-2', (A, B))
        self.assertEqual((code, report.outcome), (10, 'awaiting_approval'), h.calls[-1])
        selection = parse_json(h.objects.read(report.intent['selection']['ref']))
        self.assertEqual(selection['superseded'], [])
        self.assertIn(held.member_id, [value['member_id'] for value in selection['members']])

    def test_a_later_download_outside_the_registry_keeps_the_hold(self):
        h = self.harness((A, B))
        held, first = self.gate_then_revert(h)
        by = self.member(h, first, '2026Q3')
        # A standalone `discover --refresh` then `collect --workset <parent>` records its receipt under the parent
        # workset, which no retained member carries, but it still moves the source's latest download.
        parent = hashlib.sha256(b'standalone collect of a parent workset').hexdigest()
        self.download(h, by, sha((A,)), datetime.now(timezone.utc), under=parent)
        latest = AcquisitionState(h.store).get_source(by['source']['source_id']).to_mapping()['value']
        self.assertEqual(latest['latest_downloaded_snapshot'], sha((A,)))
        code, _, report = self.run_phase(h, 'reconcile', 'revert-2', (A, B))
        self.assertEqual((code, report.outcome), (10, 'awaiting_approval'), h.calls[-1])
        selection = parse_json(h.objects.read(report.intent['selection']['ref']))
        self.assertEqual(selection['superseded'], [])
        self.assertIn(held.member_id, [value['member_id'] for value in selection['members']])

    def test_a_stored_supersession_stays_valid_without_rescanning_the_registry(self):
        h = self.harness((A, B))
        self.gate_then_revert(h)
        code, message, report = self.run_phase(h, 'reconcile', 'revert-2', (A, B))
        self.assertEqual((code, report.outcome), (0, 'unchanged'), h.calls[-1])
        entry, = parse_json(h.objects.read(report.intent['selection']['ref']))['superseded']
        with self.subTest('no inventory'), patch.object(
                WorkflowMembers, 'inventory', side_effect=AssertionError('stored report scanned the registry')):
            read_workflow_result(message['result_ref'], h.store, h.objects)
        # Concurrent collectors of the frozen members record later downloads after the report is stored.
        # Receipts are append-only, so each frozen time stays among its member's receipts.
        for label, value, sha256 in (('completed side', entry['by'], sha((A, B))),
                                     ('pending side', entry['member'], sha((A,)))):
            with self.subTest(label):
                self.download(h, value, sha256, datetime.now(timezone.utc))
                self.assertEqual(read_workflow_result(message['result_ref'], h.store, h.objects), report)
        self.assertEqual(entry['served_by'], entry['member'])  # the gated member's own download dates its bytes

    def corrupt_download(self, h, value):
        """Make this member's only promotion receipt unreadable."""
        row, = h.store.scan('PromotionReceipt', {'workset_id': value['member_id'],
                                                 'source_id': value['source']['source_id']})
        h.store.replace('PromotionReceipt', row.value['checkpoint_id'],
                        {**row.value, 'snapshot': {**row.value['snapshot'], 'received_at': 'corrupt'}}, row.version)

    def test_unreadable_download_evidence_holds_only_its_own_source(self):
        h = self.harness((A, B))
        held, first = self.gate_then_revert(h)
        by = self.member(h, first, '2026Q3')
        identity = by['source']['source_id']
        self.corrupt_download(h, by)
        code, message = h.invoke('reconcile', run='revert-2')
        self.assertIsNotNone(message.get('result_ref'), h.calls[-1])
        report = read_workflow_result(message['result_ref'], h.store, h.objects)
        self.assertEqual((code, report.outcome), (3, 'incomplete'), h.calls[-1])
        selection = parse_json(h.objects.read(report.intent['selection']['ref']))
        self.assertEqual(selection['superseded'], [])
        self.assertIn(held.member_id, [value['member_id'] for value in selection['members']])
        gap, = [gap for gap in report.gaps if gap.code == 'legacy_member_unresolved']
        self.assertEqual((gap.source_id, dict(gap.details)), (identity, {'member_id': by['member_id']}))
        other, = [member for member in report.members if member.source.period == '2026Q4']
        self.assertEqual(other.outcome, 'unchanged')

    def test_a_member_already_reported_corrupt_gets_no_second_gap(self):
        h = self.harness((A, B))
        held, first = self.gate_then_revert(h)
        by = self.member(h, first, '2026Q3')
        self.corrupt_download(h, by)
        # Its completion receipt is unreadable too, so the retained loop reports it before the download index.
        h.store.insert('WorkflowMemberResult', 'broken-receipt-row', {
            'member_id': by['member_id'], 'parser_version': h.settings.etl.parser_version,
            'schema_version': h.settings.etl.schema_version, 'ref': 'missing/corrupt-receipt.json',
            'sha256': 'a' * 64, 'bytes': 1})
        code, message = h.invoke('reconcile', run='revert-2')
        self.assertIsNotNone(message.get('result_ref'), h.calls[-1])
        report = read_workflow_result(message['result_ref'], h.store, h.objects)
        selection = parse_json(h.objects.read(report.intent['selection']['ref']))
        self.assertEqual(selection['superseded'], [])
        self.assertIn(held.member_id, [value['member_id'] for value in selection['members']])
        named = [gap.message.split(':')[0] for gap in report.gaps
                 if gap.code == 'legacy_member_unresolved' and gap.details.get('member_id') == by['member_id']]
        self.assertEqual(named, ['retained completion receipt is corrupt'])

    def test_a_retry_keeps_its_own_discovered_member_even_when_superseded(self):
        h = self.harness((A, B))
        self.assertEqual(self.run_phase(h, 'backfill', 'base')[0], 0)
        self.assertEqual(self.run_phase(h, 'reconcile', 'gate', (A,))[0], 10, h.calls[-1])
        self.assertEqual(self.run_phase(h, 'reconcile', 'revert', (A, B))[0], 10, h.calls[-1])
        # A retry of the gated run reuses its discovery session, so it discovers the same gated member again;
        # dropping it would leave a discovered projection unselected and fail every retry with exit 9.
        h.pack = self.pack((A,), (X, Y))
        code, message = h.invoke('reconcile', run='gate', attempt='b')
        self.assertEqual((code, message['outcome']), (10, 'awaiting_approval'), h.calls[-1])

    def test_a_corrupt_pending_member_is_not_superseded(self):
        h = self.harness((A, B))
        self.assertEqual(self.run_phase(h, 'backfill', 'base')[0], 0)
        code, _, gated = self.run_phase(h, 'reconcile', 'gate', (A,))
        self.assertEqual(code, 10, h.calls[-1])
        self.assertEqual(self.run_phase(h, 'reconcile', 'revert-1', (A, B))[0], 10, h.calls[-1])
        held, = [member for member in gated.members if member.outcome == 'awaiting_approval']
        # Corrupt the gated bytes' Processing identity: evaluate_member now reports state_conflict.
        key = processing_key(held.source.source_id, sha((A,)), held.parser_version, held.schema_version)
        row = h.store.get('Processing', key)
        h.store.replace('Processing', key, {**row.value, 'processing_key': 'f' * 64}, row.version)
        code, message = h.invoke('reconcile', run='revert-2')
        self.assertNotEqual(code, 0, h.calls[-1])
        selection = parse_json(h.objects.read('runs/sec/revert-2/reconcile/a/selection.json'))
        self.assertNotIn(held.member_id, [entry['member']['member_id'] for entry in selection['superseded']])

    def test_a_candidate_whose_source_moved_on_is_listed_superseded_and_refused(self):
        h = self.harness((A, B))
        self.assertEqual(self.run_phase(h, 'backfill', 'base')[0], 0)
        self.assertEqual(self.run_phase(h, 'reconcile', 'gate', (A,))[0], 10, h.calls[-1])
        listed, = withdrawal_candidates(h.objects, EtlState(h.store))
        self.assertEqual((listed['status'], listed['latest_observed_sha256']), ('pending', sha((A,))))
        self.assertEqual(self.run_phase(h, 'reconcile', 'revert', (A, B))[0], 10, h.calls[-1])
        listed, = withdrawal_candidates(h.objects, EtlState(h.store))
        self.assertEqual((listed['status'], listed['quarterly_sha256'], listed['latest_observed_sha256']),
                         ('superseded', sha((A,)), sha((A, B))))
        before = EtlState(h.store).pointer('2026Q3')
        result = approve('2026Q3', listed['generation_id'], sha((A,)), 'Lowell Mason', h.objects, EtlState(h.store))
        self.assertEqual((result.outcome, result.error.details['latest_observed_sha256']),
                         ('approval_stale', sha((A, B))))
        self.assertEqual(EtlState(h.store).pointer('2026Q3'), before)
        self.assertIsNone(EtlState(h.store).approval(listed['generation_id']))
        with self.assertRaises(FileNotFoundError):
            h.objects.read(approval_ref('2026Q3', listed['generation_id']))
        self.assertEqual(self.names(h, '2026Q3'), ['A', 'B'])

    def test_revert_detection_reads_the_active_generation_through_full_validation(self):
        h = self.harness((A, B))
        self.assertEqual(self.run_phase(h, 'backfill', 'base')[0], 0)
        code, _, added = self.run_phase(h, 'reconcile', 'add', (A, B, C))
        self.assertEqual(code, 0, h.calls[-1])
        capture = capture_from_pointer(EtlState(h.store).pointer('2026Q3'))
        data = next(ref for ref in read_manifest(capture, h.objects).files if ref.role != 'changes')
        with open(h.objects.directory / data.path, 'ab') as handle:
            handle.write(b'x')
        with self.assertRaises(Conflict):
            source_revert_gaps(added.members, h.store, h.objects)


if __name__ == '__main__':
    unittest.main()
