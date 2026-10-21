# Stage 2 baseline campaign: scope, budget and approval

**Status:** Proposed. Not approved. The release gate is closed. No live invocation may start until the
Release gate section is open and the Approval section is complete and committed.
**Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md).
**Spec:** §§4.2–4.9, 5–6, 7 G2 of the [ingestion spec](../../sec-filing-index-ingestion-spec.md).

## Identity

| Item | Value |
| --- | --- |
| Release | `fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec` |
| Live config | `conf/sec-edgar-local.json`, effective SHA-256 `088403cb…`, file SHA-256 `cad77e29d681e47a6cfb5658b7ddd13c50b6d55f17e0e315f30c2878cf8da0c4` |
| Pilot config | `conf/stage2/backfill-2026Q4-open.json`, effective SHA-256 `bef7c783784ae99b2dcfacede76da26a40fc9b326e7a0e721afd8e3a52cced23` |
| First slice config | `conf/stage2/backfill-2015Q1-2015Q2.json`, effective SHA-256 `879d0e540f09df9fda45c10fe4c0be0bb3ca30d501e6d1fefc4370d6b8463748` |
| Slice generator check | reproduces the L12 quarterly config hash `32b4da63…` |
| Data / log roots | `/Users/lowell/Projects/sec-edgar-local/data` / `…/logs` |
| Pre-campaign backup | `/Users/lowell/Projects/sec-edgar-local/backups/stage2-pre-campaign-20261021T180646Z` |
| Evidence tool | `scripts/baseline-campaign.py` at commit `4508859d97fe386c77829807bb143fd3bde1028a` |

## Release gate

Closed on release `fc68adef…`. The pilot must drain every pending daily source in one invocation. L12's
native daily publishes took 41.6 s and 187.6 s. So about 75 sources need about 3,350 s at the lower value
and about 8,800 s at the mean, against the 3,600-second live maximum. A run that reaches its deadline leaves
no result (plan 2, F8 and F11). The gate opens only on a release where the pilot's drain fits one invocation
with margin, or where undispatched members defer before the deadline, after a reviewed revision of plan 2
for that release.

## Source scope

- Workflow: launcher `backfill` only, with one slice config for each invocation. No `daily`,
  `reconcile`, low-level command, `approve` or `rollback`.
- Requested units: the quarterly sources 2015Q1–2026Q4, which is 48 units. 2026Q4 is the open quarter.
  Its source is quarter-to-date, and absence from it is not withdrawal authority (§4.4).
- Slice plan (F8, F9). (1) The pilot `2026Q4`–`open` carries every pending daily source as retained work:
  every daily body listed under `daily-index/2026/QTR3` and `QTR4`. L12 left 73 such sources, and more
  business days have been added since. These daily units are not baseline units. The finding reports them
  apart, for Stage 3. (2) Then the first slice `2015Q1`–`2015Q2` measures the per-quarter cost. No native
  closed-quarter publish time exists yet. (3) Then ascending slices run up to 2026Q3, each sized by the
  Task 5 rule. Together the slices cover every quarter exactly once.
- Source quarters and output filing quarters differ (§4.2). Daily rows can be back-dated into old filing
  quarters (findings §4.7).
- Expected exceptions: the 2024Q1 quarantine (line 88043), which is retained and selected again by the
  first slice that reaches it. Possible quarantines for 2015Q1 and 2026Q3 (retained conflict specimens).
  Possible withdrawal gates for closed quarters that hold back-dated daily rows (F5, O10).

## Budget

| Bound | Limit | Enforced by | Basis |
| --- | --- | --- | --- |
| Invocations | 16 | stop rule | pilot invocations, first slice, sized slices, reruns |
| Runtime per invocation | 3,300 s (launcher default) | launcher | live maximum 3,600 s |
| Request rate | 3/s, one collector | coordinator | §4.8 |
| Attempts per URL per command | 5 | downloader | §4.8 |
| Bytes per response | 67,108,864 received / 536,870,912 expanded | downloader | §4.8 |
| Request attempts per invocation | 700 | audit after the invocation | pilot about 7 listings + 1 quarterly + up to about 110 daily bodies; 5 attempts each is about 590 |
| Request attempts, campaign | 1,500 | audit | slices add about 2 + years + quarters listings and one body per quarter |
| Distinct URLs, campaign | 300 | audit | about 1 + 12 + 48 full-index listings, 48 quarterly bodies, 4 daily listings and about 110 daily bodies, about 223 |
| Received bytes, campaign | 1,073,741,824 | audit | about 47 × 4.3 MB + 110 × 0.35 MB, about 240 MB (2024Q1 4,262,821; daily 289,582 and 329,651) |
| Expanded validation bytes, campaign | declared 16 GiB | not counted durably by the launcher; reported after the campaign from retained raw ZIP member sizes | 2024Q1 `master.idx` 33,578,469; L12 counted repeated validation (102,593,106 for 3 bodies) |
| Free disk before each invocation | at least 50 GiB | pre-check | 599 GiB free on 2026-10-21 |
| Store growth | at most 30 GiB | pre-check | whole-quarter generations are rewritten when daily members publish |
| Window | from the approved UTC start, at most 7 days, and ending before 2027-01-01T00:00:00Z | pre-check | `open` must stay 2026Q4 |

The audit checks the aggregate limits between invocations, not inside one. Inside one invocation, the
hard bounds are the runtime, the rate, the per-URL attempt limit and the per-response byte limits.

## Stop rules

After each invocation, apply the first rule that matches.

1. **Halt** on a launcher exit of 2, 6, 8, 9 or 11, or any exit outside 0, 3, 4, 5, 7 and 10.
2. **Halt** when the run left no `result_ref` or no `workflow_summary`. This is a deadline or crash
   (F8). Follow `docs/runbooks/local-recovery.md` with the owner before any further invocation.
3. **Halt** on a workflow outcome of `access_blocked`, `ownership_lost`, `state_conflict` or `internal_error`.
4. **Halt** on any audit breach, any HTTP 403, or any `uncertain` transport attempt.
5. **Halt** when the files comparison against L12 reports `missing` or `changed_immutable`.
6. **Halt** when `workflow_summary.summary_error` is not null.
7. **Rerun the same slice** when any of its units, or any daily source after the pilot, has outcome
   `pending`, `deferred` or `throttled`, and this is the slice's first invocation or its previous
   invocation reduced that count. Halt when a rerun does not reduce it.
8. **Halt** on the second consecutive invocation with `discovery_complete: false`.
9. **Next slice** when quarters remain without a campaign result. Size it by the Task 5 rule.
10. **Finish** when every quarter 2015Q1–2026Q4 has a campaign result and no member has outcome
    `pending`, `deferred` or `throttled`. Quarantined, failed and `awaiting_approval` members are not
    eligible work.

A halt stops the campaign. The operator reports to the owner and does nothing else. A halt is evidence,
not a failure of the plan.

## Evidence locations

- Committed: this directory. `pre-campaign.md`, `invocations.md`, `invocations/<k>-<run-id>.json`,
  `final/`, `quarantine/`, `coverage-finding.md`. Slice configs in `conf/stage2/`.
- Raw and ignored: `data/` (store, durable results), `logs/<run-id>/<attempt-id>/` (launcher evidence),
  `logs/baseline-campaign/` (large tool outputs), `backups/` (pre-campaign backup).

## Approval boundary

- Plan 2's approval authorizes Tasks 1–3 only.
- A live invocation needs all four of these: (1) the Release gate above, open; (2) the Approval section
  below, completed with the owner's words and committed; (3) Task 2 verification with exit 0; (4) the
  sole-issuer declaration below, with its start time.
- Never authorized here: `approve`, `rollback`, `daily`, `reconcile`, a parser, schema, release or live
  config change, a second root, or any SEC request outside the launcher.

## Approval

To be completed in Task 4 with the owner's exact words.
