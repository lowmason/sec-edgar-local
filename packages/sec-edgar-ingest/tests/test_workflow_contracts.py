"""Offline workflow coverage and strict result contracts."""
from network_guard import install

install()

import unittest
from dataclasses import replace
from datetime import timedelta

from support import fixture_context, fixture_source, fixture_workset
from sec_edgar_ingest.etl.contracts import PublicationResult
from sec_edgar_ingest.models import Error
from sec_edgar_ingest.results import EXIT_CODES
from sec_edgar_ingest.workflows.contracts import (
    MemberResult, WorkflowResult, member_status, summarize, workflow_path,
)


class CompletionRecordTests(unittest.TestCase):
    def test_incomplete_capture_cannot_claim_completion(self):
        from sec_edgar_ingest.workflows.contracts import CompletionEvaluation
        from sec_edgar_ingest.models import Error
        gap = Error('publication_missing', 'not committed', True, None, {})
        with self.assertRaises(ValueError):
            CompletionEvaluation(True, None, (), ())
        with self.assertRaises(ValueError):
            CompletionEvaluation(True, {'member_id': 'a' * 64}, (), (gap,))
        with self.assertRaises(ValueError):
            CompletionEvaluation(True, {'member_id': 'a' * 64}, ({'id': 'b' * 64},), ())
        value = CompletionEvaluation(False, None, (), (gap,))
        self.assertEqual(CompletionEvaluation.from_mapping(value.to_mapping()), value)


class SkippedSourceTests(unittest.TestCase):
    def test_complete_source_participates_in_quarantine_precedence(self):
        from sec_edgar_ingest.models import Source, Error
        from sec_edgar_ingest.workflows.contracts import MemberResult, summarize
        from sec_edgar_ingest.urls import source_id
        url = 'https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/master.20261001.idx'
        source = Source(source_id(url), url, 'daily', '2026-10-01', 'idx')
        refused = MemberResult('b' * 64, source,
            'worksets/sec/source/sha256=' + 'c' * 64 + '/workset.json',
            None, None, (), 'quarantined', False, False, True, (), (),
            'fixture-index-parser-v1', 'sec-index-v1')
        outcome, counts = summarize((refused,), (), 1, 0, 'backfill', ('d' * 64,))
        self.assertEqual(outcome, 'incomplete')
        self.assertEqual((counts['complete_sources'], counts['failed_sources'],
                          counts['quarantined_sources']), (1, 1, 1))
        with self.assertRaises(ValueError):
            summarize((refused,), (), 1, 0, 'backfill', (source.source_id,))
        with self.assertRaises(ValueError):
            summarize((), (), 0, 0, 'daily', ('d' * 64, 'd' * 64))


class CoverageTests(unittest.TestCase):
    def member(self, outcome='success', quarters=()):
        return MemberResult(
            'a' * 64, fixture_source(),
            'worksets/sec/source/sha256=' + 'b' * 64 + '/workset.json',
            'worksets/sec/snapshot/sha256=' + 'c' * 64 + '/workset.json',
            'worksets/sec/transformed/sha256=' + 'd' * 64 + '/workset.json',
            ('runs/sec/r/collect/a/result.json',), outcome, True, True, False,
            quarters, (), 'fixture-index-parser-v1', 'sec-index-v1',
        )

    def publication(self, outcome='published', quarter='2015Q1'):
        return PublicationResult(
            quarter, outcome, 'e' * 64, 'curated/sec/g/manifest.json', None, 0,
        )

    def workflow(self, members=None, gaps=(), **overrides):
        context = fixture_context(command='daily')
        members = (self.member(),) if members is None else members
        outcome, counts = summarize(members, gaps, 1, 0, context.command)
        directory = fixture_workset((fixture_source(),)).directories[0]
        values = dict(
            format_version='sec-workflow-result-v1', context=context,
            intent={'invocation': {'start_quarter': '2015Q1', 'end_quarter': '2015Q2'},
                    'discovered_sources': 1, 'unresolved_before': 0,
                    'already_complete_sources': []},
            source_workset_ref='worksets/sec/source/sha256=' + 'b' * 64 + '/workset.json',
            requested_quarters=('2015Q1', '2015Q2'), directories=(directory.to_mapping(),),
            members=members, gaps=gaps, boundary_before='2026-10-01',
            boundary_after='2026-10-06', outcome=outcome, counts=counts,
            ended_at=(context.started_at + timedelta(seconds=1)).isoformat(),
        )
        values.update(overrides)
        return WorkflowResult(**values)

    def test_reconcile_is_a_workflow_command_with_reconciliation_priority(self):
        from sec_edgar_ingest.workflows.contracts import WORKFLOW_COMMANDS, WORKFLOW_PRIORITY
        context = fixture_context(command='reconcile', priority='reconciliation')
        self.assertEqual(workflow_path(context), 'runs/sec/fixture-run/reconcile/fixture-attempt/result.json')
        self.assertEqual(WORKFLOW_COMMANDS, ('backfill', 'daily', 'reconcile'))
        self.assertEqual(WORKFLOW_PRIORITY, {'backfill': 'backfill', 'daily': 'daily', 'reconcile': 'reconciliation'})
        with self.assertRaises(ValueError):
            workflow_path(fixture_context(command='publish'))

    def test_gate_only_unresolved_work_is_awaiting_approval_beside_completed_sources(self):
        done = replace(self.member(), member_id='b' * 64, source=fixture_source('2015Q2'))
        gated = self.member('awaiting_approval', (self.publication('awaiting_approval'),))
        for command in ('backfill', 'daily', 'reconcile'):
            with self.subTest(command=command):
                outcome, counts = summarize((done, gated), (), 1, 0, command)
                self.assertEqual((outcome, counts['complete_sources'], counts['pending_sources'],
                                  counts['awaiting_approval_quarters']), ('awaiting_approval', 1, 1, 1))
        deferred = replace(self.member('deferred'), member_id='c' * 64, source=fixture_source('2015Q3'))
        self.assertEqual(summarize((done, gated, deferred), (), 1)[0], 'incomplete')
        reverted = Error('source_reverted', 'older bytes', True, done.source.source_id, {'quarter': '2015Q2'})
        self.assertEqual(summarize((done, gated), (reverted,), 1)[0], 'incomplete')
        failed = replace(self.member('invalid_source'), member_id='c' * 64, source=fixture_source('2015Q3'),
                         transformed=False, quarantined=True)
        self.assertEqual(summarize((done, gated, failed), (), 1)[0], 'incomplete')

    def test_gate_reduction_looks_at_unresolved_members_not_whole_sources(self):
        from sec_edgar_ingest.results import exit_code
        complete = self.member()
        gated = replace(self.member('awaiting_approval', (self.publication('awaiting_approval'),)),
                        member_id='b' * 64)
        self.assertEqual(complete.source.source_id, gated.source.source_id)
        outcome, counts = summarize((complete, gated), (), 1)
        self.assertEqual((outcome, exit_code(outcome)), ('awaiting_approval', 10))
        self.assertEqual((counts['complete_sources'], counts['pending_sources']), (0, 1))
        deferred = replace(self.member('deferred'), member_id='c' * 64, source=fixture_source('2015Q2'))
        self.assertEqual(summarize((gated, deferred), (), 1)[0], 'pending')

    def test_empty_daily_is_not_failure_or_old_backlog(self):
        self.assertEqual(summarize((), (), 0)[0], 'no_new_sources')
        gap = Error('discovery_failed', 'failed', True, None, {})
        self.assertEqual(summarize((), (gap,), 0)[0], 'incomplete')
        pending = replace(self.member(), outcome='pending', transformed=False)
        self.assertEqual(summarize((pending,), (), 0)[0], 'pending')

    def test_valid_progress_does_not_erase_invalid_member(self):
        bad = replace(self.member(), member_id='b' * 64,
                      source=fixture_source('2015Q2'), outcome='invalid_source',
                      transformed=False, quarantined=True)
        outcome, counts = summarize((self.member(), bad), (), 2)
        self.assertEqual(outcome, 'incomplete')
        self.assertEqual((counts['complete_sources'], counts['failed_sources'],
                          counts['quarantined_sources']), (1, 1, 1))
        self.assertEqual(summarize((bad,), (), 1)[0], 'quarantined')

    def test_all_exit_outcomes_have_explicit_member_and_coverage_status(self):
        expected = {
            'success': ('complete', 'unchanged'),
            'no_new_sources': ('complete', 'unchanged'),
            'unchanged': ('complete', 'unchanged'),
            'configuration': ('failed', 'incomplete'),
            'discovery_failed': ('failed', 'incomplete'),
            'incomplete': ('failed', 'incomplete'),
            'pending': ('pending', 'pending'),
            'retry_exhausted': ('failed', 'incomplete'),
            'deferred': ('pending', 'pending'),
            'throttled': ('pending', 'pending'),
            'access_blocked': ('failed', 'access_blocked'),
            'quarantined': ('failed', 'incomplete'),
            'invalid_source': ('failed', 'incomplete'),
            'ownership_lost': ('failed', 'ownership_lost'),
            'state_conflict': ('failed', 'state_conflict'),
            'internal_error': ('failed', 'internal_error'),
            'publication_conflict': ('failed', 'incomplete'),
            'awaiting_approval': ('pending', 'awaiting_approval'),
            'approval_refused': ('failed', 'incomplete'),
            'approval_stale': ('failed', 'incomplete'),
            'rollback_refused': ('failed', 'incomplete'),
            'rollback_stale': ('failed', 'incomplete'),
        }
        self.assertEqual(set(expected), set(EXIT_CODES))
        for outcome, (status, coverage) in expected.items():
            with self.subTest(outcome=outcome):
                member = self.member(outcome)
                self.assertEqual(member_status(outcome), status)
                actual, counts = summarize((member,), (), 1)
                self.assertEqual(actual, coverage)
                self.assertEqual(counts[status + '_sources'], 1)

    def test_unknown_outcome_is_refused(self):
        with self.assertRaises(KeyError):
            member_status('invented_success')
        with self.assertRaises(KeyError):
            self.member('invented_success')

    def test_source_identity_uses_worst_status_and_distinct_progress_counts(self):
        pending = replace(self.member(), member_id='b' * 64, outcome='pending', transformed=False)
        failed = replace(pending, member_id='c' * 64, outcome='invalid_source', quarantined=True)
        outcome, counts = summarize((self.member(), pending, failed), (), 1)
        self.assertEqual(outcome, 'incomplete')
        self.assertEqual(counts, {
            'complete_sources': 0, 'pending_sources': 0, 'failed_sources': 1,
            'discovered_sources': 1, 'downloaded_sources': 1, 'transformed_sources': 1,
            'quarantined_sources': 1, 'published_quarters': 0,
            'unchanged_quarters': 0, 'awaiting_approval_quarters': 0,
        })

    def test_pending_member_prevents_complete_coverage(self):
        pending = replace(self.member('deferred'), member_id='b' * 64, source=fixture_source('2015Q2'))
        self.assertEqual(summarize((self.member(), pending), (), 1)[0], 'incomplete')
        self.assertEqual(summarize((self.member('awaiting_approval'), pending), (), 0)[0], 'pending')

    def test_fatal_precedence_includes_discovery_gaps(self):
        for outcome in ('access_blocked', 'ownership_lost', 'state_conflict', 'internal_error'):
            with self.subTest(outcome=outcome):
                gap = Error(outcome, 'failed', False, None, {})
                self.assertEqual(summarize((self.member(),), (gap,), 1)[0], outcome)
        gaps = tuple(Error(code, 'failed', False, None, {}) for code in
                     ('internal_error', 'state_conflict', 'ownership_lost', 'access_blocked'))
        self.assertEqual(summarize((), gaps, 0)[0], 'access_blocked')

    def test_quarter_counts_and_approval(self):
        quarters = (self.publication(), self.publication('unchanged', '2015Q2'))
        outcome, counts = summarize((self.member(quarters=quarters),), (), 1)
        self.assertEqual((outcome, counts['published_quarters'], counts['unchanged_quarters']),
                         ('success', 1, 1))
        awaiting = self.member('awaiting_approval', (self.publication('awaiting_approval'),))
        outcome, counts = summarize((awaiting,), (), 0)
        self.assertEqual((outcome, counts['awaiting_approval_quarters']), ('awaiting_approval', 1))

    def test_zero_output_and_old_backlog(self):
        self.assertEqual(summarize((self.member(),), (), 0)[0], 'no_new_sources')
        self.assertEqual(summarize((self.member(),), (), 0, 1)[0], 'unchanged')
        self.assertEqual(summarize((self.member(),), (), 0, command='backfill')[0], 'unchanged')
        self.assertEqual(summarize((), (), 0, command='backfill')[0], 'unchanged')
        published = self.member(quarters=(self.publication(),))
        self.assertEqual(summarize((published,), (), 0)[0], 'success')

    def test_member_rejects_invalid_references_and_versions(self):
        member = self.member()
        cases = (
            {'member_id': 'not-a-hash'}, {'parent_ref': member.snapshot_ref},
            {'snapshot_ref': member.transformed_ref}, {'transformed_ref': member.snapshot_ref},
            {'child_refs': ('runs/sec/r/daily/a/result.json',)},
            {'child_refs': ('runs/sec/../collect/a/result.json',)},
            {'child_refs': ('runs/sec/r/collect/a%20/result.json',)},
            {'parser_version': 'unsupported'}, {'schema_version': 'unsupported'},
        )
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(member, **fields)

    def test_member_rejects_invented_etl_and_duplicate_quarters(self):
        member = self.member()
        cases = (
            {'snapshot_ref': None}, {'transformed_ref': None},
            {'quarters': (self.publication('awaiting_approval'),)},
            {'quarters': (self.publication(), self.publication())},
            {'quarantined': True},
            {'outcome': 'invalid_source', 'quarantined': True},
        )
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(member, **fields)
        accepted = replace(member, outcome='invalid_source', quarantined=True, transformed=False)
        self.assertTrue(accepted.quarantined)

    def test_workflow_mapping_roundtrip_and_counter_refusal(self):
        result = self.workflow(members=(self.member(quarters=(self.publication(),)),))
        self.assertEqual(WorkflowResult.from_mapping(result.to_mapping()), result)
        self.assertEqual(result.directories[0]['source_ids'], (fixture_source().source_id,))
        self.assertEqual(result.intent['invocation']['start_quarter'], '2015Q1')
        wrong = result.to_mapping()
        wrong['counts']['complete_sources'] = 2
        with self.assertRaises(ValueError):
            WorkflowResult.from_mapping(wrong)

    def test_workflow_nested_fields_are_immutable_and_detached(self):
        result = self.workflow()
        with self.assertRaises(TypeError):
            result.intent['invocation']['start_quarter'] = '2026Q4'
        detached = result.to_mapping()
        detached['directories'][0]['source_ids'].append('f' * 64)
        self.assertEqual(len(result.directories[0]['source_ids']), 1)
        self.assertEqual(WorkflowResult.from_mapping(result.to_mapping()), result)

    def test_nested_record_decoder_refuses_unknown_keys_and_wrong_types(self):
        result = self.workflow()
        for field, value in (('downloaded', 1), ('source', {}), ('unexpected', True)):
            with self.subTest(field=field):
                wrong = result.to_mapping()
                wrong['members'][0][field] = value
                with self.assertRaises(ValueError):
                    WorkflowResult.from_mapping(wrong)
        wrong = result.to_mapping()
        wrong['counts']['complete_sources'] = True
        with self.assertRaises(ValueError):
            WorkflowResult.from_mapping(wrong)

    def test_workflow_rejects_invalid_identity_time_ordering_and_outcome(self):
        result = self.workflow()
        cases = (
            {'format_version': 'unsupported'}, {'members': result.members * 2},
            {'source_workset_ref': result.members[0].snapshot_ref}, {'outcome': 'success'},
            {'ended_at': '2026-10-06T00:00:01'},
            {'ended_at': '2026-10-06T00:00:01+01:00'},
            {'ended_at': (result.context.started_at - timedelta(seconds=1)).isoformat()},
            {'requested_quarters': ('2015Q2', '2015Q1')},
            {'requested_quarters': ('2015Q1', '2015Q1')},
            {'requested_quarters': ('2015Q5',)},
            {'boundary_before': '20261001'}, {'boundary_after': '2026-02-30'},
        )
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(result, **fields)

    def test_workflow_intent_counters_are_nonnegative_integers(self):
        result = self.workflow()
        for key in ('discovered_sources', 'unresolved_before'):
            for value in (True, -1, 1.0):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    replace(result, intent={**result.to_mapping()['intent'], key: value})

    def test_already_complete_sources_add_coverage_without_duplicate_selection(self):
        result = self.workflow()
        intent = {**result.to_mapping()['intent'], 'already_complete_sources': ['f' * 64]}
        counts = {**result.to_mapping()['counts'], 'complete_sources': 2}
        accepted = replace(result, intent=intent, counts=counts)
        self.assertEqual(accepted.counts['complete_sources'], 2)
        self.assertEqual(WorkflowResult.from_mapping(accepted.to_mapping()), accepted)
        for identities in (['f' * 64, 'f' * 64], [fixture_source().source_id], ['bad']):
            with self.subTest(identities=identities), self.assertRaises(ValueError):
                replace(result, intent={**intent, 'already_complete_sources': identities})

    def test_workflow_skipped_completion_prevents_pure_quarantine(self):
        refused = replace(self.member('invalid_source'), transformed=False, quarantined=True)
        result = self.workflow(members=(refused,))
        intent = {**result.to_mapping()['intent'], 'already_complete_sources': ['f' * 64]}
        counts = {**result.to_mapping()['counts'], 'complete_sources': 1}
        accepted = replace(result, intent=intent, counts=counts, outcome='incomplete')
        self.assertEqual(WorkflowResult.from_mapping(accepted.to_mapping()), accepted)
        with self.assertRaises(ValueError):
            replace(accepted, outcome='quarantined')

    def test_empty_daily_with_discovery_or_backlog_is_unchanged(self):
        self.assertEqual(summarize((), (), 1)[0], 'unchanged')
        self.assertEqual(summarize((), (), 0, 1)[0], 'unchanged')

    def quarantine_gap(self, *sources):
        return Error(
            'baseline_publication_missing', 'selected sources have no accepted publication',
            False, None,
            {'coverage_cause': 'selected_source_quarantine',
             'source_ids': sorted(source.source_id for source in sources)},
        )

    def test_all_quarantined_retains_attributed_baseline_publication_gaps(self):
        first = replace(self.member('invalid_source'), transformed=False, quarantined=True)
        second = replace(first, member_id='b' * 64, source=fixture_source('2015Q2'))
        gaps = (self.quarantine_gap(first.source), self.quarantine_gap(second.source))
        outcome, counts = summarize((first, second), gaps, 2, command='backfill')
        self.assertEqual(outcome, 'quarantined')
        self.assertEqual(EXIT_CODES[outcome], 7)
        self.assertEqual((counts['complete_sources'], counts['failed_sources'],
                          counts['quarantined_sources']), (0, 2, 2))
        result = self.workflow(
            members=(first, second), gaps=gaps,
            context=fixture_context(command='backfill'),
            intent={'invocation': {}, 'discovered_sources': 2, 'unresolved_before': 0,
                    'already_complete_sources': []}, outcome=outcome, counts=counts,
        )
        self.assertEqual(result.gaps, gaps)
        self.assertEqual(WorkflowResult.from_mapping(result.to_mapping()), result)

    def test_independent_missing_source_or_directory_gap_prevents_pure_quarantine(self):
        refused = replace(self.member('invalid_source'), transformed=False, quarantined=True)
        derived = self.quarantine_gap(refused.source)
        independent = (
            Error('baseline_publication_missing', 'missing source', False, None,
                  {'source_ids': [fixture_source('2015Q2').source_id]}),
            Error('discovery_failed', 'directory failed', True, None, {}),
        )
        for gap in independent:
            with self.subTest(code=gap.code):
                self.assertEqual(summarize((refused,), (derived, gap), 1,
                                           command='backfill')[0], 'incomplete')

    def test_baseline_gap_attribution_requires_exact_selected_refused_source_ids(self):
        refused = replace(self.member('invalid_source'), transformed=False, quarantined=True)
        gap = self.quarantine_gap(refused.source)
        malformed = (
            {}, {'coverage_cause': 'selected_source_quarantine'},
            {**gap.to_mapping()['details'], 'source_ids': []},
            {**gap.to_mapping()['details'], 'source_ids': [refused.source.source_id] * 2},
            {**gap.to_mapping()['details'], 'source_ids': [fixture_source('2015Q2').source_id]},
            {**gap.to_mapping()['details'], 'source_ids': [123]},
            {**gap.to_mapping()['details'], 'source_ids': refused.source.source_id},
        )
        for details in malformed:
            with self.subTest(details=details):
                independent = replace(gap, details=details)
                self.assertEqual(summarize((refused,), (independent,), 1,
                                           command='backfill')[0], 'incomplete')
        unrelated = replace(gap, code='discovery_failed')
        self.assertEqual(summarize((refused,), (unrelated,), 1)[0], 'incomplete')
        misattributed = replace(gap, source_id=fixture_source('2015Q2').source_id)
        self.assertEqual(summarize((refused,), (misattributed,), 1)[0], 'incomplete')

    def test_attributed_quarantine_gaps_do_not_erase_valid_progress(self):
        refused = replace(self.member('invalid_source'), member_id='b' * 64,
                          source=fixture_source('2015Q2'), transformed=False, quarantined=True)
        gap = self.quarantine_gap(refused.source)
        self.assertEqual(summarize((self.member(), refused), (gap,), 2,
                                   command='backfill')[0], 'incomplete')

    def test_fatal_gap_precedes_attributed_all_quarantined_outcome(self):
        refused = replace(self.member('invalid_source'), transformed=False, quarantined=True)
        derived = self.quarantine_gap(refused.source)
        for code in ('access_blocked', 'ownership_lost', 'state_conflict', 'internal_error'):
            with self.subTest(code=code):
                fatal = Error(code, 'fatal failure', False, None, {})
                self.assertEqual(summarize((refused,), (derived, fatal), 1,
                                           command='backfill')[0], code)

    def test_constructor_refuses_quarantine_for_every_pending_outcome(self):
        for outcome in ('pending', 'deferred', 'throttled', 'awaiting_approval'):
            with self.subTest(outcome=outcome):
                pending = replace(self.member(outcome), transformed=False)
                fields = {name: getattr(pending, name) for name in pending.to_mapping()}
                fields['quarantined'] = True
                with self.assertRaises(ValueError):
                    MemberResult(**fields)

    def test_workflow_decoder_refuses_pending_quarantine_with_matching_counts(self):
        for outcome in ('pending', 'deferred', 'throttled', 'awaiting_approval'):
            with self.subTest(outcome=outcome):
                pending = replace(self.member(outcome), transformed=False)
                wrong = self.workflow(members=(pending,)).to_mapping()
                wrong['members'][0]['quarantined'] = True
                wrong['counts']['quarantined_sources'] = 1
                with self.assertRaises(ValueError):
                    WorkflowResult.from_mapping(wrong)

    def test_workflow_path_requires_supported_command_and_single_segment_ids(self):
        for command in ('daily', 'backfill'):
            context = fixture_context(command=command)
            self.assertEqual(workflow_path(context),
                             f'runs/sec/fixture-run/{command}/fixture-attempt/result.json')
        with self.assertRaises(ValueError):
            workflow_path(fixture_context())
        for name in ('run_id', 'execution_id', 'attempt_id'):
            for value in ('nested/id', '..', 'escaped%20id'):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    workflow_path(replace(fixture_context(command='daily'), **{name: value}))


if __name__ == '__main__':
    unittest.main()
