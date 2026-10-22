# Bounded drain and the D5 release — Stage 1a Design Spec

**Status:** Design approved section by section by the owner, 2026-10-22. Written spec awaits owner review.
**Project:** `/Users/lowell/Projects/sec-edgar-local`.
**Parent spec:** [SEC filing-index ingestion](sec-filing-index-ingestion-spec.md) (§§3 R2, R5–R6, R12; 4.2, 4.7–4.9; 5–6; 9).
**Roadmap:** [ingestion roadmap](sec-filing-index-ingestion-roadmap.md), Stage 1a.

## 1. Purpose

On release `fc68adef…`, a run that carries the pending-source backlog cannot finish inside its
runtime limit, and a run that reaches its deadline leaves no workflow result
([plan 2](plans/2-sec-filing-index-ingestion-spec.md) F8, F11). The owner routed this to an engine
change and a new release before the Stage 2 campaign (plan 2 D5).

This stage makes every run stop starting new members before its deadline, so it always writes its
durable result. It also removes repeated child work for one source across runs (plan 2 F10). It
ships the change as a new reviewed native release, called the D5 release below.

## 2. Scope

In scope:

- A dispatch cutoff in `workflows/runner.py`, set by a new config key.
- A skip of members whose same-source sibling just completed (approach A).
- One offline measurement task, with an owner decision point.
- The D5 release, its offline verification, and the live-config release selection.
- Amendments to the parent spec (§8).

Out of scope:

- Cheaper publication (option (c) at brainstorming). It can become a later stage (§6).
- Any change to the selection format, `aliases`, `superseded`, publication, catalog, parser or schema.
- A new workflow outcome or exit code.
- Any SEC request, live run, or change under `data/`.
- Any platform item. The platform workspace member stays off `main` until the D5 build
  (platform roadmap D1; plan 3 DF6).

## 3. Requirements

| ID | Requirement |
|---|---|
| B1 | `execution.dispatch_reserve_seconds` is an optional integer. When it is absent, the normalized effective config omits it, so every existing effective-config SHA-256 is unchanged. |
| B2 | Live validation requires the key, with floor ≤ value < `execution.max_run_seconds`. The floor is a release constant (§6). The launcher refuses `--timeout-seconds` ≤ the reserve. Each refusal occurs before store or network authority. |
| B3 | `run_workflow` defers a member without dispatch when `now >= deadline − reserve`, or when the run is halted. A missing key gives `cutoff = deadline`, which is today's behavior. |
| B4 | Before it dispatches a member, the runner skips it when all of these are true: the immediately preceding member in the loop has the same `source_id` and an outcome in `workflows/contracts.py` `COMPLETE`; `reuse_exact_binding` returns no gaps; and `evaluate_member` then reports it complete with no obligations. A skipped member records a receipt with its completion capture and no child calls. In every other case the member is processed as today. |
| B5 | `validate_member_evidence` accepts the B4 receipt shape. Existing receipts stay valid byte for byte. |
| B6 | Selection bytes and format (`sec-local-workflow-selection-v1`) do not change. Exact replay of a run that holds B4 receipts returns identical bytes. |
| B7 | The D5 release is built by `build_release` from clean committed `main`. The package version stays `0.2.0`. `uv.lock` and `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` are byte-identical to their `fc68adef…` build inputs (revision `3ca50c7`; no diff to `main` on 2026-10-22). |
| B8 | The live config gains the key and selects the D5 release. Offline preflight passes, and the new effective-config SHA-256 is recorded. |

## 4. Design

### 4.1 Components

| Unit | Change |
|---|---|
| `config.py` `ExecutionSettings` | B1, B2. |
| `local_cli.py` `prepare_invocation` | B2 timeout check. |
| `workflows/runner.py` `run_workflow` | B3 cutoff in the existing `elif`; B4 skip before `process_member`. |
| `workflows/processing.py` `validate_member_evidence` | B5. |
| `conf/sec-edgar-local.json` | B8. |
| `releases/sha256=<D5 id>/` | B7. |

### 4.2 Data flow in one run

1. Selection freezes `selection.json` as today. It still holds retained and new-discovery members
   of the same source (F10).
2. The member loop keeps its order (period, source_id, member_id), so members of one source are
   adjacent. For each member, in this order of checks:
   1. A receipt exists: reuse it (replay or retry), as today.
   2. `now >= cutoff`, or the run is halted: record a `pending` member with the existing
      `workflow_deferred` gap. No child starts.
   3. The B4 conditions hold: record the no-call receipt. No child starts.
   4. Otherwise: `process_member`, as today.
3. `baseline_gaps`, `source_revert_gaps`, `summarize` and `write_workflow_result` run inside the
   reserve, before the launcher's SIGTERM.
4. Deferred members are `pending`. So the run outcome is `incomplete` (exit 3) or `pending` (exit 4),
   as today. On the D5 release a deadline deferral does not show as exit 5. Stage 2 stop rules read
   durable result fields, not exit codes (plan 2 F7).
5. A new launcher invocation continues with new IDs (`docs/runbooks/local-recovery.md`). Its
   selection again holds every incomplete member. Members still accumulate in each selection, but
   the first member of a source does the child work and B4 skips the later ones.
6. The drain ends when a run defers no member.

### 4.3 Errors and edge cases

1. **Member overrun.** A member whose child finishes at or after the hard deadline still raises
   `Conflict` (`checked.py` `_check_exit`). The run ends `state_conflict` with no result. Recovery
   stays as in `local-recovery.md`. The reserve makes this rare. Only §6 can show that it is bounded.
2. **Skip refusal.** A quarantined or failed sibling, a divergent binding (more than one candidate
   snapshot), corrupt evidence, or a repair obligation each gives normal processing. Every gap that
   today's path reports stays reported.
3. **Retry and replay.** A B4 receipt is a normal durable receipt. A retry after a crash re-evaluates
   the member against the durable sibling receipt and binding, and reaches the same decision.
4. **Two releases.** The D5 release continues `fc68adef…`-origin pending work through the existing
   two-release path (`docs/runbooks/release-upgrades.md`). If `fc68adef…` refuses a B4 receipt, then
   selecting `fc68adef…` again after a D5 run has written one is unsupported for that store. The
   plan records the tested answer in the evidence and in the spec amendment (§8).
5. **Clock.** The cutoff uses the same UTC wall clock as today's check. `ClockUncertain` handling
   does not change.

## 5. Verification (offline)

Tests use stdlib `unittest` under `packages/sec-edgar-ingest/tests/network_guard.py`. Write each
test before its implementation.

1. **Config.** With the key absent, the normalized hash equals `088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d`
   (current live config) and `32b4da638464758c2926fc9040e207696a081d452b2af3813ddd36d179441740` (L12
   quarterly config). Live validation refuses a missing key, a value below the floor, and a value ≥
   `max_run_seconds`. The launcher refuses a timeout ≤ the reserve.
2. **Cutoff.** In a fixture store with a patched clock, members after the cutoff record
   `workflow_deferred`, and the result is written and observed before the deadline. A member that is
   running when the cutoff passes completes.
3. **Drain.** A fixture store with 8 pending sources and a small budget drains through repeated
   new-ID runs. Collect, transform and publish each run once for each source. On `fc68adef…`
   behavior they run twice (F10), so the test fails there.
4. **Skip safety.** Each refusal case in §4.3 item 2 processes the member and keeps every gap.
5. **Replay.** Exact replay of a run with B4 receipts returns identical bytes.
6. **Two releases.** The D5 release continues `fc68adef…`-origin pending work. A separate test
   records whether `fc68adef…` accepts a B4 receipt.
7. **Full gate.** `scripts/check-sec-edgar-ingest.sh` passes. The retained count is 952 tests in 60
   modules. The new tests add to it.

## 6. Measurement and owner decision point

This is an early plan task. It runs offline and never opens `data/` except through the release's
validated readers.

- **Runtime:** the installed `fc68adef…` interpreter with `-I -B -X pycache_prefix=/dev/null`, on a
  fresh store in a new git-ignored directory under the project. Not under `/tmp` or `/private/tmp`.
- **Inputs:** a synthetic quarterly body with at least the row count of the retained 2024Q1 body
  (`master.zip`, 4,262,821 bytes; count its rows through the validated readers), and synthetic daily
  bodies with back-dated rows.
- **Measures:**
  1. one rebuild of a full closed quarter, caused by one back-dated daily row;
  2. an open-quarter publish with 1, 10, 40 and 80 daily sources already in the quarter;
  3. the finish step (§4.2 step 3) over 48 requested quarters.
- **Output:** a dated record in `specs/evidence/d5-release/` with each timing, and the proposed floor
  and live reserve. The floor covers the finish step with margin. The reserve covers the slowest
  measured member plus the floor.
- **Decision point:** the owner reviews the record before the floor constant and the live reserve are
  committed. If the slowest member does not fit in 3,300 seconds minus the reserve, the owner either
  accepts that limit for Stages 2–3 or adds cheaper publication as a new roadmap stage. Fixture
  timings can only underestimate native cost (plan 2 F11). The record states this limit.

## 7. Release and exit evidence

Record in `specs/evidence/d5-release/`:

1. The D5 release ID, its manifest path and its `git_revision`.
2. Empty diffs for `uv.lock` and the B7 export against the `fc68adef…` build inputs. These show
   that the release carries no platform member.
3. The offline checker result and `preflight_current` on the D5 release, with `fc68adef…` and older
   releases kept.
4. The commit that selects the D5 release in `conf/sec-edgar-local.json`, and its effective-config
   SHA-256.
5. A statement that no SEC request was sent.

The plan's `## Handoff to later stages` names every value the plan 2 revision must change:
Global Constraints, the Task 1 tool imports, the Task 3 values and slice configs, the Task 4 gate,
and the §4.8 coordination values (expected unchanged).

## 8. Parent-spec amendments

The plan's last task applies these to [the parent spec](sec-filing-index-ingestion-spec.md):

- §4.7: a run stops dispatch at `deadline − reserve`, and a deadline deferral reports exit 3 or 4.
- §4.8: a table row for `execution.dispatch_reserve_seconds`, the D5 manifest path and the new
  effective-config SHA-256.
- §4.9: the tested release-rollback limit from §4.3 item 4, if `fc68adef…` refuses a B4 receipt.

## 9. Decisions

- **S1** (owner, 2026-10-22): scope (b), bound plus less repeated work. Not cheaper publication.
- **S2** (owner, 2026-10-22): the reserve is a config key, not a code constant or a launcher flag.
- **S3** (owner, 2026-10-22): approach A, the dispatch-time skip with selection format v1 unchanged.
- **S4** (owner, 2026-10-22): design sections 1–4 approved as presented.
- Roadmap defaults (i)–(iii), approved 2026-10-22: no separate investigation stage, and Stage 1a
  ends with the reviewed live-config selection.

## 10. Rollout note

> Roadmap: specs/sec-filing-index-ingestion-roadmap.md, Stage 1a — on plan completion, tick the
> stage and re-validate later stages against what shipped.

Approval of this spec authorizes no SEC request, live run or campaign. The plan 2 revision for the
D5 release, and its Task 4 owner gate, stay the only route to live traffic.
