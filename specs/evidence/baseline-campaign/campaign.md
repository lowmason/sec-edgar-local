# Stage 2 baseline campaign: scope, budget and approval

**Status:** Approved for live execution within the limits above.
**Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md), Revisions 1 and 2.
**Spec:** §§4.2–4.9, 5–6, 7 G2 of the [ingestion spec](../../sec-filing-index-ingestion-spec.md).
**History:** the version of this file at commit `ea482dd` proposed a campaign on release `fc68adef…`. Its
release gate stayed closed (plan 2, F11). This version replaces it. Plan 2 Revision 2 (D10) moved the
range start from 2015Q1 to 2020Q1 in this file and in the live config.

## Identity

| Item | Value |
| --- | --- |
| Release | `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b` (version 0.2.0) |
| Live config | `conf/sec-edgar-local.json`, range `2020Q1`–`open`, effective SHA-256 `2512fdcb…`, file SHA-256 `bfdf2985…` |
| Dispatch reserve / floor | 1,800 s / 480 s. At the 3,300 s timeout, no member starts after 1,500 s. |
| Slice configs | `conf/stage2/1b/`, 8 files. Effective hashes: plan 2, F13 (the pilot and the 2020–2026 rows). |
| Slice generator check | `2020Q1`–`open` reproduces the live effective hash `2512fdcb…` |
| Data / log roots | `/Users/lowell/Projects/sec-edgar-local/data` / `…/logs` |
| Pre-campaign backup | `backups/stage2-pre-campaign-20261021T180646Z` |
| Evidence tool | `scripts/baseline-campaign.py` at commit `b176598` |

## Release gate

Open on evidence for release `9fa189a0…`. Live work still needs the Approval below.

1. Undispatched members defer before the deadline. The runner starts no member after the deadline
   minus 1,800 s and writes its durable result (parent spec §4.7). Members not started end `pending`
   with `workflow_deferred`.
2. Members fit inside the reserve on fixtures. The slowest measured member took 1,010.9 s, inside
   3,300 − 1,800 = 1,500 s (`specs/evidence/stage1b/measurement.md` and `gate.md`; plan 5 D10).
3. Not measured: native cost (fixture timings can only underestimate it), and an open-quarter member
   with a quarterly authority (A1). Stop rule 7 halts when a member's wall exceeds the approved limit,
   so the campaign measures both under a halt.
4. The offline preflight passes on this release ([pre-campaign.md](pre-campaign.md), Revision 2 section).

## Source scope

- Workflow: launcher `backfill` only, with one slice config for each invocation. No `daily`,
  `reconcile`, low-level command, `approve` or `rollback`.
- Requested units: the quarterly sources 2020Q1–2026Q4, which is 28 units. 2026Q4 is the open quarter.
  Its source is quarter-to-date, and absence from it is not withdrawal authority (§4.4).
- Slice plan, in this order (plan 2 F9, O13):
  1. The pilot `2026Q4`–`open`. It carries every pending daily source as retained work: every daily
     body listed under `daily-index/2026/QTR3` and `QTR4`. L12 left 73 such sources, and each business
     day since has added one. These daily units are not baseline units. The finding reports them apart,
     for Stage 3. The pilot reruns under stop rule 9 until no daily source is pending. Its 2026Q4 daily
     members that run after the 2026Q4 quarterly source is published are the A1 class (O15).
  2. The calendar years 2020, 2021, …, 2025, one slice each, in ascending order.
  3. `2026Q1`–`2026Q3`.
  Together the slices cover every quarter exactly once. About 2 full-size quarters start in one
  invocation. A slice that does not fit defers its last members, and stop rule 9 reruns it.
- Source quarters and output filing quarters differ (§4.2). Daily rows can be back-dated into old filing
  quarters (findings §4.7). Rows back-dated before 2020Q1 publish daily-only filing quarters outside
  the range. Coverage lists them under `other_filing_quarters` (plan 2 F23).
- Expected exceptions: the 2024Q1 quarantine (line 88043), retained and selected again by the 2024
  slice. A possible quarantine for 2026Q3 (retained conflict specimen). Possible withdrawal
  gates for closed quarters that hold back-dated daily rows (plan 2 F5, O10). Possibly a refused
  incremental candidate (O16).

## Budget

| Bound | Limit | Enforced by | Basis |
| --- | --- | --- | --- |
| Invocations | 24 | audit, stop rule 4 | pilot 2–4; about 14 for the year slices at about 2 full-size members each; reruns (plan 2 O19) |
| Runtime per invocation | 3,300 s (launcher default) | launcher | live maximum 3,600 s; must stay above the 1,800 s reserve |
| Dispatch cutoff | deadline − 1,800 s | runner | parent spec §4.7 |
| Member wall | 1,056 s (`max_member_wall_seconds`) | timing after the invocation, stop rule 7 | reserve rule 1.25 × w + 480 ≤ 1,800 (plan 2 O14) |
| Request rate | 3/s, one collector | coordinator | §4.8 |
| Attempts per URL per command | 5 | downloader | §4.8 |
| Bytes per response | 67,108,864 received / 536,870,912 expanded | downloader | §4.8 |
| Request attempts per invocation | 700 | audit after the invocation | pilot about 10 listings + 1 quarterly + about 90 daily bodies; 5 attempts each is about 505 |
| Request attempts, campaign | 1,500 | audit | about 100 pilot sends; each year-slice invocation about 6 listings and up to 4 bodies; reruns add listings |
| Distinct URLs, campaign | 300 | audit | about 1 + 7 + 28 full-index listings, 28 quarterly bodies, 4 daily listings and about 90 daily bodies, about 158 |
| Received bytes, campaign | 1,073,741,824 | audit | about 27 × 4.3 MB + 90 × 0.35 MB, about 148 MB (2024Q1 4,262,821; daily 289,582 and 329,651) |
| Expanded validation bytes, campaign | declared 16 GiB | not counted durably by the launcher; reported after the campaign from retained raw ZIP member sizes | 2024Q1 `master.idx` 33,578,469 |
| Free disk before each invocation | at least 50 GiB | pre-check | 497 GiB free on 2026-10-29 |
| Store growth | at most 30 GiB | pre-check | whole-quarter generations are rewritten by full rebuilds |
| Window | from the approved UTC start, at most 7 days, and ending before 2027-01-01T00:00:00Z | pre-check | `open` must stay 2026Q4 |

The audit checks the aggregate limits between invocations, not inside one. Inside one invocation, the
hard bounds are the runtime, the dispatch cutoff, the rate, the per-URL attempt limit and the
per-response byte limits. Expected launcher time: about 16–20 invocations of about 2,200 s each.

## Stop rules

After each invocation, apply the first rule that matches.

1. **Halt** on a launcher exit of 2, 6, 8, 9 or 11, or any exit outside 0, 3, 4, 5, 7 and 10.
2. **Halt** when the run left no `result_ref` or no `workflow_summary`. This is a deadline or crash
   (plan 2 F8). Follow `docs/runbooks/local-recovery.md` with the owner before any further invocation.
3. **Halt** on a workflow outcome of `access_blocked`, `ownership_lost`, `state_conflict` or `internal_error`.
4. **Halt** on any audit breach, any HTTP 403, or any `uncertain` transport attempt.
5. **Halt** when the files comparison against L12 reports `missing` or `changed_immutable`.
6. **Halt** when `workflow_summary.summary_error` is not null.
7. **Halt** when the timing report has a breach: a member's wall above `max_member_wall_seconds`
   (plan 2 O14, O15).
8. **Halt** when any member has outcome `invalid_source` and is not quarantined. The likely cause is a
   publish that refused its incremental candidate (C6). Its retry is blocked, and its objects stay
   (plan 2 O16). Read the member's gaps and report them.
9. **Rerun the same slice** when any of its units, or any daily source, has outcome `pending`,
   `deferred` or `throttled`, and this is the slice's first invocation or its previous invocation
   reduced that count. Halt when a rerun does not reduce it.
10. **Halt** on the second consecutive invocation with `discovery_complete: false`.
11. **Next slice** when quarters remain without a campaign result. Take the next slice in the Source
    scope order.
12. **Finish** when every quarter 2020Q1–2026Q4 has a campaign result and no member has outcome
    `pending`, `deferred` or `throttled`. Quarantined, failed and `awaiting_approval` members are not
    eligible work.

A halt stops the campaign. The operator reports to the owner and does nothing else. A halt is evidence,
not a failure of the plan.

## Evidence locations

- Committed: this directory. `pre-campaign.md`, `pre-campaign/1b/`, `pre-campaign/rev2/`, `invocations.md`,
  `invocations/<k>-<run-id>.json`, `final/`, `quarantine/`, `coverage-finding.md`. Slice configs in
  `conf/stage2/1b/`.
- Raw and ignored: `data/` (store, durable results), `logs/<run-id>/<attempt-id>/` (launcher evidence),
  `logs/baseline-campaign/` (coverage, audit, timing and files reports after each invocation), `backups/`
  (pre-campaign backup).

## Approval boundary

- Plan 2's approval authorized Tasks 1–3. The owner's approval of Revision 1 authorizes Tasks 3a and 3b.
  The owner's approval of Revision 2 authorizes Task 3c, including its one live config edit.
- A live invocation needs all four of these: (1) the Release gate above, open; (2) the Approval section
  below, completed with the owner's words and committed; (3) the Task 3b files check with exit 0;
  (4) the sole-issuer declaration below, with its start time.
- Never authorized here: `approve`, `rollback`, `daily`, `reconcile`, a parser, schema, release or live
  config change, a second root, object removal, or any SEC request outside the launcher.

## Approval

The owner answered each item as a separate question in the operator session. Quoted text is the option the
owner selected.

- Owner: Lowell Mason. Approved on (UTC): 2026-10-29T13:13:49Z. The owner gave no timestamp; this is when
  the operator recorded the answers.
- Range: "Confirm 2020Q1–2026Q4". Slices, budget and stop rules: as proposed ("Confirm as proposed").
- Runtime per invocation: 3300. Window: starts 2026-10-29T13:00:00Z, ends 2026-11-05T13:00:00Z.
- Member-wall limit: 1056. Pilot as the first A1 measurement: "Pilot measures A1".
- Refused incremental candidate: "Confirm as proposed" (halt, remove no objects, Stage 4 disposition).
- Withdrawal policy and order effect: "Confirm as proposed". Retained daily sources: "Confirm as proposed".
- Sole-issuer declaration: the owner selected this drafted wording: "During the campaign window, the
  launcher on this machine is the only SEC client under my identity. No other machine and not the original
  sec-edgar Azure project sends SEC requests under it."
