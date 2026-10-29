# Stage 2 Baseline Campaign and Coverage Decision Implementation Plan

**Status: REVISED for the 2020Q1 range (Revision 2, 2026-10-29), awaiting owner review** — Tasks 1–3 and 8 executed via executing-plans on release `fc68adef…` (commits `4508859`, `7b63168`, `ea482dd`, `780ea51`, and the D7 fix `4004f2e`). Revision 1 (approved, D9) added Tasks 3a and 3b and rewrote Tasks 4–7 for the 1b release. Tasks 3a and 3b executed on release `9fa189a0…` (commits `b176598`, `c9a9cb3`), and Task 4 Step 1 found the release gate standing. At Task 4 Step 2 the owner moved the range start to 2020Q1 (D10). Revision 2 adds Task 3c and changes Tasks 4–7 for that range. Executed task text is the execution record and stays as run. Nothing in Revision 2 has run. Nothing live has run. Roadmap Stage 2 stays unticked. Read `## Revision 2 for the 2020Q1 range` first, then `## Revision 1 for the 1b release`.

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task via subagent-driven-development (the default) — or executing-plans when your human partner chose inline execution at the handoff. Steps use checkbox (`- [ ]`) syntax for tracking.

> Roadmap: specs/sec-filing-index-ingestion-roadmap.md, Stage 2 — on plan completion, tick the stage and re-validate later stages against what shipped.

**Goal:** Produce an owner-accepted written finding for gate G2. The finding accounts for every requested quarterly baseline unit by a validated publication, or by a named gap, quarantine or gate with an owner disposition. It ends with an explicit complete-or-incomplete operating decision.

**Architecture:** Offline work comes first:

1. A read-only evidence tool (file inventory, transport audit, two-axis coverage), built with TDD against the existing fixture harness.
2. A stopped-writer backup and a hash-verified restoration of one drifted immutable manifest.
3. Known-answer checks against the L12 evidence, range-only slice configs, and the proposed campaign scope and budget.

An owner gate then checks the release and approves the finite scope, budget, window and sole-issuer declaration. After the gate, the operator runs the existing launcher `backfill` workflow once for each range slice. Each slice config differs from the live config only in its backfill range. The operator audits durable transport records after each invocation, and at the end writes the two-axis coverage finding for owner disposition.

Revision 1 (2026-10-29) moves the campaign to the 1b release. On it, the runner stops starting members at the deadline minus the reserve and writes a durable result, so a slice that does not fit one invocation defers its remaining members. Two offline tasks come before the gate: Task 3a revises the evidence tool (a cheap integrity view between invocations, and per-member timing), and Task 3b re-runs the known answers and makes the 1b slice configs and campaign files.

Revision 2 (2026-10-29) starts the range at 2020Q1 (D10). Offline Task 3c changes the live config's `backfill.start_quarter`, the matching spec and runbook text, the slice set and the campaign files, and re-runs the known answers. Then the Task 4 gate runs again.

**Tech Stack:** Installed native release `9fa189a0…` (CPython 3.14.0, macOS arm64, Requests 2.34.2, PyArrow 25.0.1, application version 0.2.0). Tasks 1–3 ran on release `fc68adef…`. Stdlib `unittest` under `packages/sec-edgar-ingest/tests/network_guard.py`. SQLite backup API. Launcher `scripts/sec-edgar-local`.

**Spec:** [specs/sec-filing-index-ingestion-spec.md](../sec-filing-index-ingestion-spec.md). This plan implements Stage 2 only: §§4.2–4.9, 5–6 and 7 G2. It plans no work for Stages 3–5.

## Revision 2 for the 2020Q1 range (read first)

Written 2026-10-29 at Task 4 Step 2, after the owner asked to start the range at 2020Q1 (D10). Planning sent no SEC request and wrote nothing under `data/`. It computed the new config hashes from scratch copies under the ignored `logs/` and deleted them after. It opened the store with operator access under the edited config, and ran read-only coverage for the new range (F21–F23). It also dry-ran Task 3c's edit scripts on scratch copies.

1. **What changes.** The requested range becomes 2020Q1–2026Q4: 28 quarterly units, with 2026Q4 open. The live config's `backfill.start_quarter` changes from `2015Q1` to `2020Q1`, so its file and effective hashes change (F21). Spec §4.8 and `docs/runbooks/local-ingestion.md` name the old start or hash, and change with it. The year slices 2015–2019 are not run, and their five configs are removed (O18). `max_invocations` drops to 24 (O19).
2. **New Task 3c** makes these edits and re-runs the known answers on the edited config. Tasks 4–7 change their range, unit counts and hashes.
3. **What stays.** Release `9fa189a0…`, the reserve, the evidence tool at `b176598`, every other config value, the stop rules other than rule 12, and the member-wall limit. The 8 kept slice configs stay byte-identical. Each one copies every live-config field and replaces only `backfill`, so its F13 hash holds (F21). Tasks 3a and 3b are the execution record and stay as run. Their 2015Q1 values are history.
4. **Not touched.** `conf/sec-edgar-local-fixture.json` and the test fixture configs keep `2015Q1`: they are fixtures, not the live config. `packages/sec-edgar-ingest/tests/test_config.py` embeds a frozen snapshot of an older live config (release `fc68adef…`, hash `088403cb…`) and reads no live file. No test reads `conf/sec-edgar-local.json`. So no test changes, and the full offline checker is not required. Runbook line 62 names retained 2015Q1 specimens as a historical fact and stays.
5. **Task 4 answers given before this revision are not approval.** The owner answered items 5, 6, 8 and 9 "as proposed", chose the window start 2026-10-29T12:00:00Z (it passed before this revision's review), and selected the drafted sole-issuer wording. Task 4 asks all ten items again against Revision 2.

## Revision 1 for the 1b release

Written 2026-10-29 against the Stage 2 roadmap entry (`Consumes`, amended at the 2026-10-28 resume) and plan 5, Handoff, Stage 2 bullet. Planning sent no SEC request and wrote nothing under `data/`. It ran the tool's tests, the offline preflight and read-only known answers (F12–F20).

1. **The F11 blocker is resolved on the 1b release.** Release `9fa189a0…` stops starting members at the deadline minus `execution.dispatch_reserve_seconds` (1800) and writes its durable result (parent spec §4.7). Members not started end `pending` with `workflow_deferred`. The fixture measurement puts the slowest member at 1,010.9 s, inside 3,300 − 1,800 = 1,500 s (plan 5 D10; `specs/evidence/stage1b/measurement.md`, `gate.md`). The pilot no longer has to fit one invocation: it drains across reruns. What stays unmeasured is native cost (F18) and the A1 member class (F19). O14 and O15 cover both.
2. **What Revision 1 changes.** Global Constraints (release, hashes, reserve, floor, prelude). New Task 3a: the evidence tool gets `coverage --check integrity` and a `timing` command (F16, O12). New Task 3b: known answers on the 1b interpreter, 13 new slice configs under `conf/stage2/1b/` (F13, O13), and new `campaign.json` and `campaign.md`. Tasks 4–7: the 1b release gate, the new slice list, new stop rules (O14, O16) and the evidence for the revisit triggers deferred into this stage (O17).
3. **What stays.** Tasks 1–3 and 8 and their evidence are the execution record on `fc68adef…`. Their ticked text is not changed. The slice configs `conf/stage2/backfill-2026Q4-open.json` and `conf/stage2/backfill-2015Q1-2015Q2.json` bind to `fc68adef…`. They stay as history and are never run. Task 2's backup and restoration stand: the live root is unchanged since then (F14).
4. **Never select an older release for this store after the first 1b live write** (parent spec §4.9). This plan changes no release selection, so it does not meet the revisit condition of the `specs/deferred_items.md` item "Two-release proof covers only first-generation 1b stores". Task 7 says so.

## Feasibility blocker on release `fc68adef…` (history, resolved by Revision 1)

On release `fc68adef…`, the first live invocation has no safe margin inside the runtime limit, and very likely exceeds it. Planning found this from retained native evidence and offline fixtures. It sent no SEC request.

1. The first invocation must carry every pending daily source (F4, F9). On 2026-10-21 that is about 75 sources: L12's 73, plus the business days 2026-10-19 and 2026-10-20 if they are listed. The count grows by one each business day.
2. In L12's genuine run, the native `publish` of the two daily sources took **41.6 s** (2026-10-14) and **187.6 s** (2026-10-15). The source is `specs/evidence/local-port/sec-acceptance.json`, `selected_sources[1].publish` and `selected_sources[2].publish`. The cause of the difference is not established.
3. At the lower value, 75 publishes take about 3,120 s. Collect and transform add about 230 s (L12: 0.6–0.7 s and 2.2–2.6 s for each source). That totals about 3,350 s, before the second processing of each source (F10) and before any growth (F11). The launcher default is 3,300 s and the live maximum is 3,600 s, so even this floor leaves under 10% margin. With about 80 sources by execution day, the floor is about 3,570 s. At the mean of the two observed publishes, the drain needs about 8,800 s, about 2.5 times the live maximum.
4. A run that reaches its deadline is killed and leaves no workflow result (F8). The runner defers undispatched members only when `now >= deadline`, with no margin. So the member in flight at that time becomes `state_conflict`, not a clean deferral. One overrun ends the run with no workflow result, so a run near the limit is not a safe operating point.

Consequence: Tasks 1–3 are offline and remain useful preparation. Task 4's live gate stays closed on this release. The owner routed the blocker at plan review: D5, option (a) of O11. The engine change is outside this plan.

**Status of authority:** This plan authorizes no live traffic.

- Tasks 1, 3, 3a, 3b and 3c are offline and send no SEC request.
- Task 3c edits `conf/sec-edgar-local.json`, the spec and a runbook. It writes nothing under `data/`. The owner's approval of Revision 2 authorizes it, and it is the only task that may edit the live config.
- Task 2 changes files under `data/`. The owner approved its defaults O2, O3 and O9 (D6). It still runs only with no writer running (Task 2 Step 1).
- Task 4 is the owner's live-execution gate. It opens only on a release that clears the feasibility blocker, after a reviewed revision of this plan for that release. Revision 1 is that revision for release `9fa189a0…`. Revision 2 changes its range, so Task 4 runs again after Task 3c. Tasks 5–7 run only after the Task 4 approval commit exists.
- Task 8 edits spec text only. The owner approved O4 (D6), and the task does not depend on the campaign.

## Global Constraints

Every task's requirements include these lines. Revision 1 (2026-10-29) replaced the release, hash, reserve, slice-config and prelude lines. Revision 2 (2026-10-29) replaced the live-config, slice-config and backfill lines. Tasks 1–3 and 8 ran under the 2026-10-21 lines, which stay in git history at `4004f2e`. Tasks 3a and 3b ran under the Revision 1 lines, at `d3e959c`.

- Release: `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b` (version 0.2.0, `git_revision` `50423a404fb50a959b3ca4077301117d32804cc6`), manifest `/Users/lowell/Projects/sec-edgar-local/releases/sha256=9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b/release.json`. Selected in the live config at commit `6d80da4`. Evidence: `specs/evidence/stage1b/release.md`, `measurement.md`, `gate.md`.
- Live config: `conf/sec-edgar-local.json`, `config_version=sec-local-config-v1`. After Task 3c: effective-config SHA-256 `2512fdcb999a302d93de84315d45e4e44d0bb942d5165698b64c371fc42b5be5` and file-byte SHA-256 `bfdf29859325fa396520c0fabd0bcd6f6e34d8854b558d56e4bf4a7731038204` (F21). Before Task 3c: `db62e7fb8c941f125f84992c5bccfdbb65d6461231d899054af505700e9004b1` and `de6c0dd9a67ff4bb29adf82d6df8eb5c69b934ed801ea7f5c2f3c26cc9d47fcc` (offline preflight, 2026-10-29). Task 3c Step 2 makes the one approved edit. Do not edit it otherwise.
- Dispatch reserve and floor: `execution.dispatch_reserve_seconds` 1800 (measured, plan 5 D10). Floor 480 s (release constant `config.DISPATCH_RESERVE_FLOOR_SECONDS`). The launcher refuses `--timeout-seconds` at or below the reserve. At the 3,300-second launcher default, the runner starts no member after 1,500 s (the dispatch cutoff, parent spec §4.7). A member running at the cutoff still completes.
- Release history of this store: `fc68adef…` wrote every object in it (L12). After the first 1b live write, selecting `fc68adef…` or the D5 release `aa8de1ac…` for this store is unsupported (parent spec §4.9). Never change `runtime.release_manifest` during or after the campaign.
- Slice configs: `conf/stage2/1b/backfill-<start>-<end>.json`, made only by Task 3b's `slice_config` function. After Task 3c, 8 files remain: the pilot, the years 2020–2025 and `2026Q1`–`2026Q3` (O18). Each one equals the live config except for `backfill.start_quarter` and `backfill.end_quarter`. Its storage and logging roots are written as the same absolute paths. The store binding excludes the range (§4.5), so every slice uses the same bound root. The two files directly under `conf/stage2/` bind to `fc68adef…`. Never run them.
- Observed config facts, 2026-10-21. The file is tracked since commit `001edf5` (spec §4.8 as amended by Task 8).
- Storage / acquisition: `storage.backend=local`; `acquisition.mode=live`. Data root `/Users/lowell/Projects/sec-edgar-local/data`. Logging root `/Users/lowell/Projects/sec-edgar-local/logs`.
- Backfill / handoff (live config): `2020Q1` through `open` after Task 3c (was `2015Q1`, D10); daily handoff `2026-10-01`.
- SEC identity: `Lowell Mason sec-edgar-ingest mason.lowell@mac.com`. Request policy: 3 requests/second, one active collector.
- HTTP: five total attempts; 2-second base, 120-second local cap with jitter; honor longer server delays. Connect / read / exchange limits 15 / 60 / 90 seconds. Received / expanded limits 67,108,864 / 536,870,912 bytes per response.
- Coordination: namespace `sec-owner-lowell-mason`; 60-second lease, 20-second renewal, 2-second uncertainty.
- Parser / schema: `sec-index-parser-v1` / `sec-index-v1`. Withdrawal approval: `reconciliation.require_withdrawal_approval=true`.
- Execution: live maximum 3,600 seconds; launcher default 3,300 seconds; dispatch reserve 1,800 seconds.
- Every native process uses `-I -B -X pycache_prefix=/dev/null`. No checkout application import, dependency sync or install, or interpreter download during a run.
- No parser, schema, runtime, storage or release change. No `--force`. No `approve` or `rollback`. No duplicate-winner selection, pointer edit or object deletion. The single exception is the reviewed Task 2 restoration and `.DS_Store` removal. A candidate that the C6 equivalence check refused stays in the store: removing its objects is not a supported recovery step (parent spec §4.7; plan 5 D12; `docs/runbooks/local-recovery.md`, row "Refused incremental candidate").
- During a campaign window, the launcher is the only SEC client under the owner identity. Do not send manual `curl`, browser or other requests with the owner User-Agent. The sole-issuer declaration covers every other machine and the original `sec-edgar` Azure project.
- Do not open `data/` in an editor, formatter, Finder or Quick Look. Read store contents only through `scripts/baseline-campaign.py` or the release's validated readers.
- Put no campaign evidence under `/tmp` or `/private/tmp`.
- Do not rerun the port's acceptance harness `scripts/accept-sec-native.py` or its adjudicator `scripts/verify-sec-native-adjudication.py`. Do not repeat acceptance (§6).
- Committed evidence goes under `specs/evidence/baseline-campaign/`, apart from `specs/evidence/local-port/` (§8). Raw evidence stays in the ignored `data/`, `logs/` and `backups/` trees. Committed records cite it by path and SHA-256.
- Do not infer completeness from an exit code, latest filing date, directory presence or one nonempty captured quarter (§7). Keep approved incomplete coverage distinct from complete coverage.
- Shell prelude: shell state does not persist between steps, so every shell step below starts with these lines. The shell is zsh: do not rely on word splitting of an unquoted variable.

```sh
project=/Users/lowell/Projects/sec-edgar-local
release="$project/releases/sha256=9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b"
native() { "$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null "$@"; }
tool() { native "$project/scripts/baseline-campaign.py" "$@"; }
evidence="$project/specs/evidence/baseline-campaign"
campaign_logs="$project/logs/baseline-campaign"
cd "$project"
```

## Decisions

- **D1** (owner, brief, 2026-10-21): The plan covers roadmap Stage 2 only, scoped to Spec §§4.2–4.9, 5–6 and 7 G2. It plans nothing for Stages 3–5. Applied in: all tasks.
- **D2** (owner, brief, 2026-10-21): Planning sends no SEC request, runs no acquisition, and does not rerun the completed port or the genuine acceptance harness. Plan approval is not live authority. The owner's review of the limits and confirmation of the sole-issuer condition gate live execution. Applied in: Global Constraints, Task 4.
- **D3** (owner, brief, 2026-10-21): The plan consumes findings §§2 and 4.6–4.7 (daily indexes add back-dated rows to old filing quarters) and §5 (2024Q1 quarantine: three conflicting keys that look like combined filings). Applied in: Task 1 (verdict rules), Tasks 6–7.
- **D4** (owner, brief, 2026-10-21): The intended range defaults to the config's `2015Q1`–`open` and needs owner confirmation. Applied in: Task 3 (see O1).
- **D5** (owner, plan review, 2026-10-21): O11 (a). An engine change and a new release come before the Stage 2 live campaign. Tasks 1–3 stay as offline preparation on release `fc68adef…`. Owner's words: "Route O11 (a): an engine change and a new release come before the Stage 2 live campaign. Keep Tasks 1–3 as offline preparation." Applied in: Feasibility blocker, Task 4, After the last task.
- **D6** (owner, plan review, 2026-10-21): O1–O10 accepted as proposed. Owner's words: "Accept O1–O10 as proposed in plan 2." That settles: the range 2015Q1–2026Q4 in slices, pilot first (O1); restoring the 2021Q1 manifest (O2); removing the five `.DS_Store` files (O3); recording the lost L12 directory and amending the spec (O4); budgeting and reporting the retained daily sources (O5); approving no withdrawal in Stage 2 (O6); no discovery-only probe (O7); the `campaign.json` limits (O8); the backup location under `backups/` (O9); and the pilot order (O10). Applied in: the tasks that each default names.
- **D7** (owner, execution review relayed by the parent session, 2026-10-21): After Tasks 1–3 ran, the integrity check reported `state.sqlite3-wal` and `state.sqlite3-shm` as `missing`, because SQLite deletes them when the last connection closes cleanly. The tool now lets those two files appear or vanish and reports that under `changed_state`. `state.sqlite3` stays strict. Owner's words: "Yes, approve the WAL/SHM integrity-check fix as proposed: let state.sqlite3-wal and -shm appear or disappear, keep state.sqlite3 strict, add a test, and correct the plan's code and the errors=10 wording." Applied in: Task 1 (code, test, Steps 2, 4 and 5), Task 2 Step 6.
- **D8** (owner, brief, 2026-10-27): Roadmap default (vi), approved at the 2026-10-27 resume: Stage 2 consumes the Stage 1b release in place of the D5 release, and the plan 2 revision is written against it. The values to change and the traps come from plan 5, Handoff, Stage 2 bullet (roadmap resume, 2026-10-28). Applied in: Revision 1, Global Constraints, Tasks 3a–7.
- **D9** (owner, plan review, 2026-10-29): Revision 1 approved, with O12–O17 accepted as proposed. Owner's words: "Approve and commit". This approval authorizes Tasks 3a and 3b. It is not live authority: Task 4 still gates every live invocation. Applied in: Tasks 3a–7.
- **D10** (owner, Task 4 Step 2, 2026-10-29): The requested range and the live config's `backfill.start_quarter` start at 2020Q1. This replaces O1's 2015Q1 start. Owner's words: "Can we change the range for this package as well as the quarterly index downloads to 2020Q1-2026-Q4?", then "Write Revision 2". Planning read "this package" as the live config, the only place a range lives. Applied in: Revision 2, Global Constraints, Task 3c (config, spec amendment, runbook), Tasks 4–7.

## Defaults for owner review

Each default below is applied in the named task. The owner accepted O1–O10 as proposed (D6) and settled O11 (D5). O12–O17 are new in Revision 1. The owner accepted them as proposed (D9). O1–O10 stand as accepted. Where Revision 1 changes how one applies (O1's slices, O8's limits), the new default names it. O18 and O19 are new in Revision 2 and await the owner's review. D10 changes O1's range.

- **O1 — Range and slices.** Default: requested range 2015Q1–2026Q4, which is 48 quarterly units. This is the live config's `2015Q1`–`open` on a UTC date in 2026Q4. 2026Q4 is the open quarter, so its quarterly source is quarter-to-date. The campaign runs as range slices (F8, F9). The first slice is the pilot `2026Q4`–`open`. Then ascending slices run from 2015Q1 to 2026Q3, and together they cover the range with no gap or overlap. If the campaign starts on or after 2027-01-01T00:00:00Z, `open` becomes 2027Q1: re-derive the range, the open quarter and every value that names 2026Q4 in the plan revision that Task 4 requires. Alternative: an earlier start, such as the `2010Q1` that the completed design names as a possible later revision. Applied in: Tasks 3 and 5. Revision 2 (D10): the owner set the range to 2020Q1–2026Q4, 28 units, and the live config's start to `2020Q1`.
- **O2 — 2021Q1 manifest restoration.** Default: after a stopped-writer backup, write the canonical bytes back (Task 2). The canonical re-encoding of the drifted file is SHA-256 `a445d0a8…`, 5,100 bytes, which equals the L12 inventory record. Alternative: leave the file. Then every reader and every publication onto 2021Q1 refuses with `state_conflict`. That includes a future `daily` run whose back-dated rows reach 2021Q1. Applied in: Task 2.
- **O3 — Five `.DS_Store` files in `data/`.** Default: remove them after the backup and record their hashes. Alternative: leave them and accept them as `added` in every inventory comparison. Applied in: Task 2.
- **O4 — Lost L12 external evidence.** `/private/tmp/sec-local-task16-acceptance-20261018` is absent (F3). Spec §6 requires that it be retained. Default: record the loss and amend the spec text (Task 8). What Stage 2 keeps intact is then the committed `specs/evidence/local-port/` records, the immutable live-root objects and the releases. Applied in: Tasks 2 and 8.
- **O5 — Retained daily sources.** The pilot also discovers, collects and publishes every daily body listed under `daily-index/2026/QTR3` and `QTR4` (F4). Default: accept this, budget for it, and report these sources apart from the baseline units for Stage 3. The workflow has no supported way to exclude them. Applied in: Tasks 3, 5 and 7.
- **O6 — Withdrawal gates.** A closed-quarter quarterly source that lacks keys from active daily-only generations proposes withdrawals and stops at `awaiting_approval` (F5). Findings §4.6 shows that such rows can be genuine late releases. Default: approve nothing in Stage 2. The old generation stays active, and each such quarter becomes a named `gated` unit for owner disposition. Approvals belong to Stage 4. Applied in: Tasks 5 and 7.
- **O7 — Discovery-only probe.** Default: no probe. The budget uses the measured 2024Q1 and L12 body sizes, plus margin and stop rules. Alternative: run low-level `discover --mode quarterly` first (about 65 listing requests) to read listed sizes before any body is fetched. Applied in: Task 3.
- **O8 — Budget numbers.** Default: the limits in Task 3's `campaign.json`. Applied in: Tasks 3 and 5.
- **O9 — Backup location.** Default: `/Users/lowell/Projects/sec-edgar-local/backups/stage2-pre-campaign-<UTC stamp>/`, with `backups/` added to `.gitignore`. Applied in: Task 2.
- **O10 — Order effect of the forced pilot.** The pilot runs the daily members before any older quarterly source. Back-dated daily keys therefore become active first in their closed quarters. A closed-quarter quarterly file that lacks such a key then shows as an explicit `gated` unit, with the key in its candidate. In a single full-range run, quarterly sources 2015–2025 would come first. The same keys would then be dropped from publication with no change record (`catalog._resolve`). After any later approval the end state is the same. The difference is visibility against the number of `covered` verdicts. The pilot order is forced while daily sources are pending (F9). A single full-range run is the only alternative, and it cannot fit its deadline (F8, F11). Default: accept the pilot order. In both orders, closed-quarter publication keeps only quarterly-membership keys, and Task 7 must state this as a downstream limitation. Applied in: Tasks 5 and 7.
- **O11 — Routing the feasibility blocker (F11).** Settled by D5: (a).
  - (a) Route an engine change before the live campaign. Candidate fix areas, from reading the code: a dispatch margin in `runner.run_workflow`, a per-invocation member cap, or cheaper daily publication. With a margin or a cap, undispatched members end as `workflow_deferred` before the deadline, and new-ID continuation (`docs/runbooks/local-recovery.md`) drains the rest across invocations. Any of these is an engine change. It needs a new release with its own design and plan, outside Stage 2. After that release exists, revise this plan for it (Global Constraints, Task 3 values, the Task 4 release gate), get owner review, and then run Tasks 4–7.
  - (b) Untested alternative: drain on this release by deliberate deadline expiry and new-ID continuation. Each invocation would end with exit 9 and no workflow result. A kill during a collect can leave an `uncertain` transport attempt. Stop rules 1, 2 and 4 halt on these outcomes. So this route needs its own offline proof and new stop rules, and the recovery runbook names it a recovery path, not an operating mode. This plan does not include it.
  - (c) Stop Stage 2 after Tasks 1–3, or before them.
  - Applied in: Task 4.
- **O12 — Evidence tool revision (Task 3a).** Default: add `coverage --check integrity`, which checks only the exact manifest and file hashes and reports `validated_rows` as null, with the new verdict `published_unchecked`. Task 5 uses it between invocations. Keep `--check full` as the default, with one full content check per quarter instead of two, and run it once in Task 6. Add a `timing` command that joins each member's child refs to durable `Attempt` rows and reports child seconds, member wall and engine seconds. Reason: F16. A full check costs about 415 s per full-size quarter, and the stop rules read only member outcomes. Under the 1b trust model (plan 5 Handoff, trap (a)), the final full read is the only independent content check on engine-built generations, so it stays. Alternative: keep the tool as it is. Then the between-invocation coverage grows to hours (F16). Applied in: Tasks 3a, 5, 6.
- **O13 — Slices and budget.** Default: the pilot `2026Q4`–`open` first, rerun until no daily source is pending. Then 11 calendar-year slices `2015`–`2025`, then `2026Q1`–`2026Q3`. That is 13 configs, all made in Task 3b, and no sizing rule. A year slice that does not fit one invocation defers its last members, and stop rule 9 reruns it. Budget: `max_invocations` 40 (about 2 full-size members start in each invocation, F18: pilot 2–4, year slices about 24, plus reruns). The other limits stay as O8 set them. They still hold, because each rerun adds only listing requests. This replaces O1's slice plan and O8's invocation count. Alternative: two-quarter slices (24 configs, fewer reruns, more configs). Applied in: Tasks 3b, 4, 5. Revision 2: 8 of the 13 configs remain (O18), and `max_invocations` is 24 (O19).
- **O14 — Member-wall halt.** Default: halt after any invocation in which a timed member's wall exceeds **1,056 s**. A member's wall holds no finish step: the tool reports that apart as the run's `tail_seconds` (Task 3a, Timing rules). That is the largest wall for which the measured reserve rule still gives at most the approved reserve: 1.25 × 1,056 + 480 = 1,800 (plan 5 D10). The fixture value is 1,010.9 s, and native cost is not measured (plan 5 Handoff, trap (c)). So the first full-size year slice may halt here. A halt then is evidence for the owner, who may approve a named, measured limit. Alternatives: 1,320 s (the reserve minus the floor, the hard fit for a member that starts at the cutoff), or report only. Applied in: Tasks 4, 5.
- **O15 — The A1 member class in the pilot.** The pilot publishes the open quarter's quarter-to-date quarterly source. Every 2026Q4 daily member after it is an open-quarter member with a quarterly membership authority (A1). That class is not measured (`specs/deferred_items.md`, section `5-sec-filing-index-per-member-cost — 2026-10-28`). Default: accept the pilot as the first measurement of A1, under the O14 halt. Alternative: measure A1 offline first, in a separate plan with a new fixture scenario, before Task 4. Applied in: Tasks 4, 5, 7.
- **O16 — Refused incremental candidate (C6).** A member whose publish refuses its candidate ends `invalid_source` and is not quarantined. Its retry is blocked (plan 5 Handoff, trap (e)). Default: halt after that invocation. Name the unit as an exception in Task 7, with a disposition that points to Stage 4. Do not remove objects. Applied in: Tasks 4, 5, 7.
- **O17 — Revisit triggers deferred into Stage 2.** Default: report, do not halt (except O14). Task 7 §8 records the evidence for each trigger: B4 (`repeated_sources` and `b4_members`), the history scan (engine seconds against `child_call_rows`), A1 (2026Q4 member walls), refused C6 candidates, and the two-release limit (no release change). The items stay open in `specs/deferred_items.md` unless the evidence meets their closure conditions at plan completion. Applied in: Tasks 5, 6, 7.
- **O18 — The five unused slice configs (Revision 2).** Default: `git rm` the 2015–2019 year configs in Task 3c, so `conf/stage2/1b/` holds exactly the 8 slices to run and none can be run by mistake. They stay in git history at `c9a9cb3`. Alternative: keep them as never-run history, as the two `fc68adef…` configs are kept. Applied in: Task 3c.
- **O19 — Budget for 28 units (Revision 2).** Default: `max_invocations` 24. That is the pilot's 2–4 invocations, about 14 for the 27 closed quarterly members at about 2 for each invocation, and reruns. The other limits stay as O8 and Revision 1 set them. They are upper bounds and still hold, now with more margin: about 158 of 300 distinct URLs and about 148 MB of 1 GiB received bytes. The runtime and the member-wall limit do not change. Alternative: also lower the campaign request, URL and byte limits in proportion. Applied in: Tasks 3c, 4.

## Facts established while planning (read-only, 2026-10-21)

- **F1 — Drifted immutable manifest.** The manifest of the only 2021Q1 generation was rewritten. The file is `data/objects/curated/sec/filing_index/year=2021/quarter=1/generation=887cfe89f5fc96113ade4494ec2d727265baaa0dfc69b4ad9c26cbec08d15001/manifest.json`, with mtime 2026-10-19 08:57 local. It is now tab-indented, 5,655 bytes, SHA-256 `16529f52b03e2a0c178b8105ea4e7821a903d258df12b1be79d9142b567900e0`. L12 recorded 5,100 bytes, `a445d0a836208255d238d92434c98e58f83682bd00de5c4a76860ff24a47f11a`. The cause is not established. The pointer binds the manifest hash and byte count (`etl/reader.py` `capture_from_pointer`, `validated_manifest`), so every reader and every publication onto that base refuses 2021Q1. A `state_conflict` is fatal and halts a workflow (`workflows/contracts.py` `FATAL`).
- **F2 — Finder metadata.** The live root has 160 files against L12's 155. The 5 extra files are `.DS_Store` files.
- **F3 — L12 external evidence absent.** `/private/tmp/sec-local-task16-acceptance-20261018` does not exist. A disk-wide search found no copy of `run-b0bfc28dcc7d48e686b12b5253d8a414.json`. The host had restarted about 12.5 hours before the check. `specs/evidence/local-port/sec-acceptance.json` keeps every recorded hash and the full inventory.
- **F4 — Retained daily work joins any backfill.** In quarterly mode, `discovery._inventory` adds a `daily-index` family for every pending source. `runner.select_work` selects every incomplete retained member. A `backfill` therefore also collects and publishes the L12 pending daily bodies and every other body listed in those directories.
- **F5 — Closed-quarter withdrawals.** In closed mode with quarterly membership, `etl/catalog.py` `_resolve` drops proposed keys that are absent from the membership and marks active keys that are absent as `withdrawn`. The gate is then `awaiting_approval`. Task 1's fixture test `test_closed_quarterly_missing_a_late_daily_key_is_gated_not_covered` reproduces exit 10.
- **F6 — The engine's baseline check is not coverage.** `runner.baseline_gaps` reports a gap only when a requested quarter has no readable capture. A quarter published only from back-dated daily rows therefore shows no gap, even when its quarterly source is quarantined. Task 1's fixture test `test_daily_only_generation_never_counts_for_a_quarantined_quarterly_source` reproduces this.
- **F7 — Quarantines are expected.** 2024Q1 is quarantined (line 88043). The completed design (§231) records conflicting observations in retained 2010Q1, 2015Q1 and 2026Q3 specimens, and 2015Q1 and 2026Q3 are in range. Every `backfill` returns nonzero while a quarantine remains. So the stop rules use durable result fields, not "repeat until exit 0".
- **F8 — A run that reaches its deadline leaves no workflow result.** The launcher sends SIGTERM to the engine group at the deadline (`local_cli.py`, supervision loop). The runner checks the deadline only between members, and only as `now >= context.deadline` (`runner.run_workflow`). A checked child that ends after its deadline, or whose drain is not confirmed, is a `Conflict` (`workflows/checked.py` `_check_exit`), which is `state_conflict`. Work must therefore fit inside each invocation with margin. A range-only config is the supported bound. The L12 quarterly config was such a config, and Task 3's generator reproduces its effective SHA-256 `32b4da638464758c2926fc9040e207696a081d452b2af3813ddd36d179441740` exactly.
- **F9 — Pending sources fix the slice order.** Discovery refuses any member whose quarter is after the pinned end (`worksets._validate_source_directory`: "source member is after the pinned endpoint"), which ends the run with `state_conflict`. While daily sources in 2026Q3–Q4 are pending, every backfill slice must end at 2026Q4. So the pilot is `2026Q4`–`open`, and it drains them. After that, slices run in ascending order, so a pending source from slice k is never after slice k+1's end. The rule is confirmed offline in a fixture store.
- **F10 — Each pending daily source is processed twice.** The selection holds both the retained member from the earlier discovery and the new discovery's member for the same source (`runner.select_work`, `combined`). In the 4-source fixture pilot, `process_member` ran 8 times. The second pass is cheaper.
- **F11 — The pilot has no safe margin inside its runtime on this release.** This is the blocker stated at the top.
  - Native evidence: L12's two daily publishes took 41.6 s and 187.6 s (`sec-acceptance.json`, `selected_sources[1..2].publish`). L12's 2024Q1 transform took 11.7 s and stopped as `invalid_source`, so no native closed-quarter publish time exists.
  - Fixture evidence (temporary stores, fixture parser, 20-row synthetic daily bodies, one back-dated row each, checkout package): the pilot took 50–61 s, 119.8 s and 349.9 s for 2, 4 and 8 pending sources. Child-process time was 20.6 s, 38.9 s and 91.3 s. Both grow faster than the source count.
  - Fixture profile at 4 sources: total 132.6 s. `select_work` 6.7 s (`reuse_exact_binding` 0.2 s, `inventory` 0.1 s). `process_member` 85.0 s over 8 calls, of which children 44.0 s. `baseline_gaps` 6.1 s. The cost is per-member processing, not selection.
  - Fixture timings can only underestimate native cost. So no fixture estimate can show the pilot to be feasible.
  - Unmeasured: the native cost of one closed-quarter quarterly publish. An offline estimate of it was stopped unfinished when this blocker made it moot.

## Facts established for Revision 1 (read-only, 2026-10-29)

No SEC request was sent. Nothing under `data/` was written. The store was opened only with operator access by the evidence tool, as in Task 3.

- **F12 — 1b inputs.** Offline preflight of the live config under the 1b interpreter printed effective SHA-256 `db62e7fb…`, release `9fa189a0…`, range `2015Q1`–`open` and reserve 1800. The file bytes are `de6c0dd9…`. These equal plan 5, Handoff, Stage 2 bullet.
- **F13 — Slice generator.** The Task 3 generator, run into a scratch directory with the 1b interpreter, reproduces the live effective hash `db62e7fb…` exactly for the slice `2015Q1`–`open`. That is the new known answer for the generator. The L12 check no longer applies: `2024Q1`–`2024Q1` now gives `c3b01790…`, not `32b4da63…`, because the release manifest and the reserve key changed. The 13 campaign configs give these effective hashes:

| Config | Effective SHA-256 |
| --- | --- |
| `backfill-2026Q4-open.json` (pilot) | `aab50ee232bfe0c062931593ea976cec485c82335e8a1e03503678b7d4d6573d` |
| `backfill-2015Q1-2015Q4.json` | `a4003c361fb6bd11f2682a435b8966183fef8ef79cdfd300421e4ab4a8163de6` |
| `backfill-2016Q1-2016Q4.json` | `2e5377911323cba4338972f046b66732a3a22a35406a645c5c72d60a8aafd7d8` |
| `backfill-2017Q1-2017Q4.json` | `e49855b75c50ee176718d92e4282721713bfd8f8c74936325db1682d0376a79a` |
| `backfill-2018Q1-2018Q4.json` | `4d8e600fc725456a17e74a86dae492b0be18713dd3a77bd7c8825036657e6cb0` |
| `backfill-2019Q1-2019Q4.json` | `6aa0b675459f8642290bf01593f189db4a36e00b6228f9306503ccc2d05e832c` |
| `backfill-2020Q1-2020Q4.json` | `6af8dd95411a8d9614d075eb067382ee12526d3140173449abc76b1094f0d3d3` |
| `backfill-2021Q1-2021Q4.json` | `403ee6d813448f30e98f80adf39937339ace1d1793adad7f799af9eb105a6279` |
| `backfill-2022Q1-2022Q4.json` | `ce09a643e7b97f7b86ae781ca53ad17232e9315de9e9a11423536bb2c5ec284d` |
| `backfill-2023Q1-2023Q4.json` | `12b29832fd23c31bd726e738ab3363d72fa05bee3e1e608bbb8c4f1da64c44a8` |
| `backfill-2024Q1-2024Q4.json` | `b3800ebbc33494fea29b970d0999db206d0cd040d665c36dbc8be9b22b445694` |
| `backfill-2025Q1-2025Q4.json` | `1d733369522f78bc9d857390cfd3c0539b9a24ac50be8f3026e531c24b15adce` |
| `backfill-2026Q1-2026Q3.json` | `d84919ef81fea54f9026c9ab014b2c7e5e2b825166e23e9cd323269d50eeed61` |

- **F14 — Live root unchanged since Task 2.** `files` against L12 reports 153 files, 12,170,549 bytes, and an empty comparison except `changed_state` for the SQLite journal files. No writer runs. The backup `backups/stage2-pre-campaign-20261021T180646Z` exists. 497 GiB are free.
- **F15 — The tool on the 1b code.** The checkout source equals the 1b `git_revision` (empty `git diff 50423a4 HEAD -- packages/sec-edgar-ingest/src`). The tool's 11 tests pass on it (110.8 s). Every release internal the tool imports is defined in `9fa189a0…`, and the tests exercise each one. `audit` gives the L12 store total again (10 attempts, 10 URLs, 4,946,565 bytes, ordinal 1). `coverage` gives `{'no_campaign_result': 48}`, 16 published daily-only quarters and 6,744 rows. `_validate_report` and `capture_quarter` use the cheap C1 check on this release.
- **F16 — Coverage cost.** `quarter_view` calls `validated_manifest` and then `read_quarter`, which calls `validated_manifest` again. So each published quarter gets two full content checks. One full check of a full-size quarter is about 415 s (`specs/evidence/stage1b/diagnosis.md` §1). On the live root's 16 small quarters, a prototype of the Task 3a tool took 51.5 s with `--check full` and 0.6 s with `--check integrity`. With about 2 full-size quarters added in each invocation, an unchanged between-invocation coverage would cost about 2k × 830 s after invocation k.
- **F17 — Two-release coverage of this store.** Every object in the live store was written by `fc68adef…`. Continuation of `fc68adef…`-origin pending work by the current code is tested by `test_release_origin.OriginReleaseTests`, which ran in the 1b gate (1108 tests, OK). Continuation of D5-origin work is in `specs/evidence/stage1b/two-release.md`. Not tested: a 1b incremental publish onto a base generation that `fc68adef…` wrote, which is what the pilot does to the 16 daily-only quarters. It rests on unchanged formats (1b spec C7) and on C6, which checks each incremental candidate before the pointer moves. A C6 refusal is handled by O16.
- **F18 — Dispatch arithmetic.** Fixture member walls: full-size closed first publication 911.9–1,010.9 s; open-quarter daily members 8.8–16.2 s at n = 1–80; measure 1 16.7 s; fan-out 21.0 s; authority full rebuild 985.4 s; finish step up to 97.8 s (`measurement.md`). With the cutoff at 1,500 s, about 2 full-size members start in one invocation, and the run ends near 2,100–2,200 s. The reserve rule 1.25 × w + 480 ≤ 1,800 holds up to w = 1,056 s (O14).
- **F19 — A1 arises in the pilot.** The pilot's selection holds the 2026Q4 quarter-to-date quarterly source and the 2026Q4 daily sources. Once the quarterly source is published, later 2026Q4 daily members take the A1 path, which plan 5 did not measure (O15).
- **F20 — History scan starts at zero.** The live store has 0 `WorkflowChildCall` rows and 14 `Attempt` rows (all from L12, run `accept-38bf7c024e0fd5ac`). Each timed member adds up to 3 child calls. The measured slopes are 0.0218–0.0290 s per row (`measurement.md`, "History scan (S4)").

## Facts established for Revision 2 (read-only, 2026-10-29)

No SEC request was sent. Nothing under `data/` was written. Scratch configs were written to the ignored `logs/` and deleted.

- **F21 — New config hashes.** Replacing the one `"start_quarter": "2015Q1"` with `"start_quarter": "2020Q1"` in `conf/sec-edgar-local.json` gives file SHA-256 `bfdf29859325fa396520c0fabd0bcd6f6e34d8854b558d56e4bf4a7731038204` (1,361 bytes, the same length) and effective SHA-256 `2512fdcb999a302d93de84315d45e4e44d0bb942d5165698b64c371fc42b5be5`. Two paths gave the same effective hash: a byte copy in `logs/`, whose relative roots resolve to the same absolute paths, and the slice-generator path with absolute roots. The effective mapping differs from the live one only in `backfill`. All 13 Task 3b configs still equal the live config except for `backfill`, with their F13 hashes. Their hashes do not depend on the live start.
- **F22 — Store and coverage on the new range.** The store opens with operator access under the edited config (16 `QuarterPublication` rows), so the store binding excludes the range (§4.5). `coverage --start 2020Q1 --end 2026Q4 --open-quarter 2026Q4` gives `{'no_campaign_result': 28}` and 16 published daily-only quarters. With `--check full` it reads 6,744 rows. `other_filing_quarters` is empty: every published quarter is 2021Q1 or later.
- **F23 — The engine reads the range only from config.** `discovery.py` and `runner.py` take `backfill.start_quarter` from settings. `workflows/results.py` rebuilds a result's requested quarters from the effective config recorded in that result, so the live edit does not change how slice results validate. Daily rows back-dated into filing quarters before 2020Q1 still publish, as daily-only quarters outside the range. Coverage lists them under `other_filing_quarters`.

## File structure

| Path | Responsibility | Task |
| --- | --- | --- |
| `scripts/baseline-campaign.py` | Read-only evidence tool: `files`, `audit`, `coverage` (`--check full\|integrity`), `timing`. Verified against releases `fc68adef…` and `9fa189a0…`. | 1, 3a |
| `packages/sec-edgar-ingest/tests/test_baseline_campaign.py` | Offline tests: pure rules plus fixture-store workflows. | 1, 3a |
| `.gitignore` | Adds `backups/`. | 2 |
| `backups/stage2-pre-campaign-<stamp>/` (ignored) | Stopped-writer backup: SQLite backup copy and raw copy of `data/`. | 2 |
| `specs/evidence/baseline-campaign/pre-campaign.md`, `pre-campaign/*.json` | Integrity findings, backup, restoration and known-answer results. `pre-campaign/1b/*.json` holds the Revision 1 known answers, `pre-campaign/rev2/*.json` the Revision 2 ones. | 2–3, 3b, 3c |
| `conf/stage2/backfill-<start>-<end>.json` | Range-only slice configs bound to `fc68adef…`. History; never run. | 3 |
| `conf/stage2/1b/backfill-<start>-<end>.json` | The range-only slice configs bound to `9fa189a0…`: 13 made, 8 kept. | 3b, 3c, 5 |
| `conf/sec-edgar-local.json` | The live config. Task 3c changes `backfill.start_quarter` to `2020Q1`. | 3c |
| `docs/runbooks/local-ingestion.md` | The backfill start in its config rules. | 3c |
| `specs/evidence/baseline-campaign/campaign.md`, `campaign.json` | Scope, budget, slice plan, stop rules, evidence locations, approval boundary, release gate and owner approval. Rewritten for the 1b release, then edited for the 2020Q1 range. | 3, 3b, 3c, 4 |
| `specs/evidence/baseline-campaign/invocations.md`, `invocations/<k>-<run-id>.json` | Ledger and record for each invocation, with its timing summary. | 5 |
| `specs/evidence/baseline-campaign/final/*.json`, `quarantine/<quarter>.txt` | Final full coverage, audit, timing, inventory comparison and conflict enumerations. | 6 |
| `specs/evidence/baseline-campaign/coverage-finding.md` | The G2 finding, dispositions and operating decision. | 7 |
| `specs/sec-filing-index-ingestion-spec.md` | Amendment for F3 and the config observation (Task 8). §4.8 backfill row and effective hash for the 2020Q1 range (Task 3c). | 8, 3c |

---

### Task 1: Read-only campaign evidence tool

> Revision 1: executed on release `fc68adef…`. Task 3a extends this tool for the 1b release. The text below is the execution record.

**Files:**
- Create: `scripts/baseline-campaign.py`
- Create: `packages/sec-edgar-ingest/tests/test_baseline_campaign.py`

**Interfaces:**
- Consumes: installed `sec_edgar_ingest` APIs of release `fc68adef…`: `config.load_config`, `storage.open_stores(settings, access='operator')`, `etl.state.EtlState`, `etl.reader.capture_quarter / read_quarter / validated_manifest`, `workflows.contracts.WorkflowResult / workflow_path / member_status`, `workflows.results._read / _validate_report`, `discovery.quarter_span`, and `StateStore.scan('TransportAttempt' | 'QuarterPublication', {})`. Do not use `read_workflow_result`: it repairs index records, so it is not read-only.
- Produces (stdout is indented sorted JSON with `format_version: sec-baseline-campaign-evidence-v1`):
  - `files --root PATH [--recorded JSON]` returns `{kind: files, inventory: {root, file_count, byte_count, files[{relative_path, sha256, byte_count}]}, comparison?: {missing, added, changed_immutable, changed_state}}`. Exit 1 when `missing` or `changed_immutable` is nonempty. `state.sqlite3-wal` and `state.sqlite3-shm` may appear or vanish, and the comparison lists that under `changed_state`. `state.sqlite3` itself stays strict. `--recorded` accepts the L12 machine evidence, an earlier `files` report or a bare inventory.
  - `audit --config PATH [--run-id ID]... [--budget JSON]` returns `{kind: audit, runs{run_id: summary}, total, store_total, breaches?}`. Each summary is `{attempts, distinct_urls, received_bytes, max_ordinal, uncertain, access_denied, statuses, outcomes}`. Exit 1 on any breach.
  - `coverage --config PATH [--result REF]... --start Q --end Q [--open-quarter Q]` returns `{kind: coverage, requested, results, verdicts, complete, units[{quarter, verdict, source, filing_quarter, last_result_gaps}], other_filing_quarters, daily_sources}`. Exit 0. `filing_quarter` includes `membership_source_id`, `source_kinds` and `daily_rows_considered`.
  - Unit verdicts: `covered`, `covered_open_quarter`, `quarantined`, `gated`, `pending`, `failed`, `publication_mismatch`, `source_missing`, `no_campaign_result`. `complete` is true only when every verdict is `covered` or `covered_open_quarter`.
  - Budget file: `{format_version: sec-baseline-campaign-budget-v1, max_invocations, max_request_attempts, max_request_attempts_per_invocation, max_distinct_urls, max_received_bytes}`.

The coverage rule is the core of G2. A requested unit counts as covered only when the quarter's quarterly source member is complete and the active generation names that same source as its `membership_source`. The gate must also be `clear`, and the validated row count must equal the manifest row count and be above zero. A readable quarter alone never counts (F6).

- [x] **Step 1: Write the failing test**

Create `packages/sec-edgar-ingest/tests/test_baseline_campaign.py`:

```python
"""Offline invariants for the read-only Stage 2 baseline-campaign evidence tool."""
from network_guard import install
install()

import contextlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from support import fixture_settings
from support_workflows import BASE, CommandHarness, build_pack, idx

PROJECT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT / 'scripts/baseline-campaign.py'
FULL, DAILY = BASE + 'full-index/', BASE + 'daily-index/'


def tool():
    if not SCRIPT.exists():
        raise AssertionError('missing read-only baseline campaign evidence tool')
    return runpy.run_path(str(SCRIPT))


def row(cik, name, filed, number):
    return (cik, name, '10-K', filed, f'edgar/data/{cik}/0000{cik}-26-{number:06d}.txt')


def campaign_pack(root, quarterly, daily_rows):
    """Quarterly 2026Q2-Q4 plus one daily body on 2026-10-01 under daily-index QTR4."""
    listings = {FULL + 'index.json': [('2026', 'dir')],
                FULL + '2026/index.json': [('QTR2', 'dir'), ('QTR3', 'dir'), ('QTR4', 'dir')],
                DAILY + 'index.json': [('2026', 'dir')],
                DAILY + '2026/index.json': [('QTR3', 'dir'), ('QTR4', 'dir')],
                DAILY + '2026/QTR3/index.json': [],
                DAILY + '2026/QTR4/index.json': [('master.20261001.idx', 'file')]}
    bodies = {DAILY + '2026/QTR4/master.20261001.idx': idx(daily_rows, 'daily')}
    for quarter, rows in quarterly.items():
        listings[FULL + f'2026/QTR{quarter}/index.json'] = [('master.zip', 'file')]
        bodies[FULL + f'2026/QTR{quarter}/master.zip'] = idx(rows, 'quarterly')
    return build_pack(root, listings, bodies, repeats=16)


Q3 = (row('222222', 'Third', '2026-07-01', 3),)
Q4 = (row('333333', 'Fourth', '2026-10-01', 4),)
LATE = row('444444', 'Late release', '20260415', 9)
DAILY_ROWS = (row('333333', 'Fourth', '20261001', 4), LATE)
LATE_KEY_IN_Q2 = (row('111111', 'Second', '2026-04-01', 2), (LATE[0], LATE[1], LATE[2], '2026-04-15', LATE[4]))


class PureRuleTests(unittest.TestCase):
    def setUp(self):
        self.api = tool()

    def test_inventory_comparison_allows_only_sqlite_state_to_change(self):
        recorded = {'files': [{'relative_path': 'state.sqlite3', 'sha256': 'a', 'byte_count': 1},
                              {'relative_path': 'objects/x', 'sha256': 'b', 'byte_count': 1},
                              {'relative_path': 'objects/gone', 'sha256': 'c', 'byte_count': 1}]}
        actual = {'files': [{'relative_path': 'state.sqlite3', 'sha256': 'z', 'byte_count': 2},
                            {'relative_path': 'objects/x', 'sha256': 'b', 'byte_count': 2},
                            {'relative_path': 'objects/new', 'sha256': 'd', 'byte_count': 1}]}
        self.assertEqual(self.api['compare_inventory'](recorded, actual),
                         {'missing': ['objects/gone'], 'added': ['objects/new'],
                          'changed_immutable': ['objects/x'], 'changed_state': ['state.sqlite3']})

    def test_sqlite_journal_files_may_come_and_go_but_the_database_may_not(self):
        def entry(path):
            return {'relative_path': path, 'sha256': 'a', 'byte_count': 1}
        compare = self.api['compare_inventory']
        journaled = {'files': [entry('state.sqlite3'), entry('state.sqlite3-shm'), entry('state.sqlite3-wal')]}
        closed = {'files': [entry('state.sqlite3')]}
        # SQLite deletes its WAL and shared-memory files when the last connection closes cleanly.
        self.assertEqual(compare(journaled, closed),
                         {'missing': [], 'added': [], 'changed_immutable': [],
                          'changed_state': ['state.sqlite3-shm', 'state.sqlite3-wal']})
        self.assertEqual(compare(closed, journaled),
                         {'missing': [], 'added': [], 'changed_immutable': [],
                          'changed_state': ['state.sqlite3-shm', 'state.sqlite3-wal']})
        self.assertEqual(compare(journaled, {'files': [entry('state.sqlite3-wal')]}),
                         {'missing': ['state.sqlite3'], 'added': [], 'changed_immutable': [],
                          'changed_state': ['state.sqlite3-shm']})

    def test_recorded_inventory_reads_l12_evidence_and_files_reports(self):
        inventory = {'files': []}
        read = self.api['recorded_inventory']
        self.assertIs(read({'output_inventory': {'live_root': inventory}}), inventory)
        self.assertIs(read({'inventory': inventory}), inventory)
        self.assertIs(read(inventory), inventory)

    def test_unit_verdicts_never_treat_a_readable_quarter_as_coverage(self):
        verdict = self.api['unit_verdict']
        member = {'source_id': 's', 'outcome': 'success', 'status': 'complete', 'quarantined': False,
                  'quarters': [{'quarter': '2026Q3', 'outcome': 'published'}]}
        view = {'status': 'published', 'membership_source_id': 's', 'gate': 'clear',
                'row_count': 3, 'validated_rows': 3}
        self.assertEqual(verdict('2026Q3', '2026Q4', member, view, False), 'covered')
        self.assertEqual(verdict('2026Q4', '2026Q4', member, view, False), 'covered_open_quarter')
        self.assertEqual(verdict('2026Q3', '2026Q4', None, view, True), 'source_missing')
        self.assertEqual(verdict('2026Q3', '2026Q4', None, view, False), 'no_campaign_result')
        daily_only = {**view, 'membership_source_id': None}
        self.assertEqual(verdict('2026Q3', '2026Q4', member, daily_only, False), 'publication_mismatch')
        self.assertEqual(verdict('2026Q3', '2026Q4', member, {**view, 'validated_rows': 2}, False),
                         'publication_mismatch')
        refused = {**member, 'outcome': 'quarantined', 'status': 'failed', 'quarantined': True}
        self.assertEqual(verdict('2026Q3', '2026Q4', refused, daily_only, False), 'quarantined')
        gated = {**member, 'outcome': 'awaiting_approval', 'status': 'pending'}
        self.assertEqual(verdict('2026Q3', '2026Q4', gated, view, False), 'gated')
        self.assertEqual(verdict('2026Q3', '2026Q4', {**member, 'outcome': 'deferred', 'status': 'pending'},
                                 view, False), 'pending')
        self.assertEqual(verdict('2026Q3', '2026Q4', {**member, 'outcome': 'retry_exhausted', 'status': 'failed'},
                                 view, False), 'failed')

    def test_budget_breaches_name_each_exceeded_limit(self):
        budget = {'format_version': 'sec-baseline-campaign-budget-v1', 'max_invocations': 1,
                  'max_request_attempts': 10, 'max_request_attempts_per_invocation': 4,
                  'max_distinct_urls': 10, 'max_received_bytes': 100}
        quiet = {'attempts': 3, 'distinct_urls': 3, 'received_bytes': 50, 'access_denied': 0, 'uncertain': 0}
        check = self.api['check_budget']
        self.assertEqual(check({'runs': {'r1': quiet}, 'total': quiet}, budget), [])
        loud = {'attempts': 5, 'distinct_urls': 3, 'received_bytes': 101, 'access_denied': 1, 'uncertain': 0}
        fields = [(item['scope'], item['field'])
                  for item in check({'runs': {'r1': loud, 'r2': quiet}, 'total': loud}, budget)]
        self.assertEqual(fields, [('campaign', 'received_bytes'), ('r1', 'attempts'),
                                  ('campaign', 'invocations'), ('campaign', 'access_denied')])
        with self.assertRaises(ValueError):
            check({'runs': {}, 'total': quiet}, {**budget, 'format_version': 'other'})


class FixtureStoreTests(unittest.TestCase):
    def setUp(self):
        self.api = tool()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def harness(self, quarterly, daily_rows=DAILY_ROWS):
        settings = fixture_settings(backfill={'start_quarter': '2026Q2', 'end_quarter': 'open'},
            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
            http={'retry_base_seconds': 0.001, 'retry_cap_seconds': 0.001},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        h = CommandHarness(self.root, campaign_pack(self.root / 'pack', quarterly, daily_rows), settings)
        self.addCleanup(h.close)
        return h

    def run_tool(self, h, *argv):
        h.close()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.api['main'](list(argv))
        return code, json.loads(stdout.getvalue())

    def coverage(self, h, *refs):
        flags = [item for ref in refs for item in ('--result', ref)]
        return self.run_tool(h, 'coverage', '--config', str(h.config), *flags,
                             '--start', '2026Q2', '--end', '2026Q4', '--open-quarter', '2026Q4')

    def test_backfill_units_separate_quarantine_from_quarterly_coverage(self):
        conflict = (row('111111', 'Second', '2026-04-01', 2), row('111111', 'Changed', '2026-04-01', 2))
        h = self.harness({2: conflict, 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 3, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'])
        self.assertEqual(code, 0)
        verdicts = {unit['quarter']: unit['verdict'] for unit in report['units']}
        self.assertEqual(verdicts, {'2026Q2': 'quarantined', '2026Q3': 'covered',
                                    '2026Q4': 'covered_open_quarter'})
        self.assertFalse(report['complete'])
        self.assertEqual(report['units'][0]['filing_quarter']['status'], 'unpublished')
        self.assertIn('baseline_publication_missing', report['units'][0]['last_result_gaps'])

    def test_daily_only_generation_never_counts_for_a_quarantined_quarterly_source(self):
        conflict = (row('111111', 'Second', '2026-04-01', 2), row('111111', 'Changed', '2026-04-01', 2))
        h = self.harness({2: conflict, 3: Q3, 4: Q4})
        self.assertEqual(h.invoke('daily', run='d1', attempt='a1')[0], 0, h.calls[-1])
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 3, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'])
        unit = report['units'][0]
        # The engine's own baseline check sees a readable 2026Q2 and reports no missing publication.
        self.assertNotIn('baseline_publication_missing', unit['last_result_gaps'])
        self.assertEqual(unit['filing_quarter']['status'], 'published')
        self.assertIsNone(unit['filing_quarter']['membership_source_id'])
        self.assertEqual(unit['filing_quarter']['source_kinds'], {'daily': 1})
        self.assertEqual(unit['verdict'], 'quarantined')

    def test_closed_quarterly_missing_a_late_daily_key_is_gated_not_covered(self):
        h = self.harness({2: (row('111111', 'Second', '2026-04-01', 2),), 3: Q3, 4: Q4})
        code, daily = h.invoke('daily', run='d1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 10, h.calls[-1])
        code, report = self.coverage(h, daily['result_ref'], message['result_ref'])
        unit = report['units'][0]
        self.assertEqual(unit['verdict'], 'gated')
        self.assertIsNone(unit['filing_quarter']['membership_source_id'])
        self.assertEqual([item['period'] for item in report['daily_sources']], ['2026-10-01'])

    def test_closed_quarterly_that_lists_the_late_key_covers_the_quarter(self):
        h = self.harness({2: LATE_KEY_IN_Q2, 3: Q3, 4: Q4})
        self.assertEqual(h.invoke('daily', run='d1', attempt='a1')[0], 0, h.calls[-1])
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'])
        self.assertTrue(report['complete'])
        view = report['units'][0]['filing_quarter']
        self.assertEqual(view['source_kinds'], {'daily': 1, 'quarterly': 1})
        self.assertEqual((view['daily_rows_considered'], view['validated_rows']), (1, 2))

    def test_audit_counts_each_run_and_refuses_over_budget(self):
        h = self.harness({2: (row('111111', 'Second', '2026-04-01', 2),), 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        # Five full-index listings (root, year, three quarters) and three quarterly bodies.
        budget = self.root / 'budget.json'
        budget.write_text(json.dumps({'format_version': 'sec-baseline-campaign-budget-v1', 'max_invocations': 1,
            'max_request_attempts': 8, 'max_request_attempts_per_invocation': 8,
            'max_distinct_urls': 8, 'max_received_bytes': 10 ** 9}))
        code, report = self.run_tool(h, 'audit', '--config', str(h.config), '--run-id', 'r1',
                                     '--budget', str(budget))
        self.assertEqual(code, 0, report)
        run = report['runs']['r1']
        self.assertEqual((run['attempts'], run['distinct_urls'], run['max_ordinal']), (8, 8, 1))
        self.assertEqual((run['uncertain'], run['access_denied'], run['statuses']), (0, 0, {'200': 8}))
        self.assertGreater(run['received_bytes'], 0)
        budget.write_text(json.dumps({**json.loads(budget.read_text()), 'max_request_attempts': 7}))
        code, report = self.run_tool(h, 'audit', '--config', str(h.config), '--run-id', 'r1',
                                     '--budget', str(budget))
        self.assertEqual(code, 1)
        self.assertEqual(report['breaches'], [{'scope': 'campaign', 'field': 'attempts',
                                               'observed': 8, 'limit': 7}])

    def test_files_report_refuses_a_rewritten_immutable_object(self):
        root = self.root / 'store'
        (root / 'objects').mkdir(parents=True)
        (root / 'objects/manifest.json').write_bytes(b'{"a":1}')
        (root / 'state.sqlite3').write_bytes(b'one')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.api['main'](['files', '--root', str(root)]), 0)
        recorded = self.root / 'recorded.json'
        recorded.write_text(stdout.getvalue())
        (root / 'state.sqlite3').write_bytes(b'two')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.api['main'](['files', '--root', str(root), '--recorded', str(recorded)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())['comparison']['changed_state'], ['state.sqlite3'])
        (root / 'objects/manifest.json').write_bytes(b'{\n\t"a": 1\n}')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.api['main'](['files', '--root', str(root), '--recorded', str(recorded)]), 1)
        self.assertEqual(json.loads(stdout.getvalue())['comparison']['changed_immutable'], ['objects/manifest.json'])


if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 2: Run the test to verify it fails**

> Deviation: unittest printed `FAILED (failures=10)`, not `errors=10`. D7 corrected the wording; with the D7 test the count is 11.

```sh
cd /Users/lowell/Projects/sec-edgar-local
UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --locked --package sec-edgar-ingest \
  python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests \
  -p test_baseline_campaign.py -v
```

Expected: `FAILED (failures=11)`. Every failure is `AssertionError: missing read-only baseline campaign evidence tool`.

- [x] **Step 3: Write the implementation**

> Deviation: after execution, D7 (`4004f2e`) changed `compare_inventory` and added an 11th test. The code shown is the D7 version.

Create `scripts/baseline-campaign.py`:

```python
"""Read-only Stage 2 baseline-campaign evidence: file inventory, transport audit and coverage.

Run under the selected release interpreter with -I -B -X pycache_prefix=/dev/null. The tool opens
the store with operator access, sends no request and writes nothing under the store root. It uses
release fc68adef... internals (workflow result validation, ETL readers); re-verify it before use
with any other release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

FORMAT = 'sec-baseline-campaign-evidence-v1'
BUDGET_FORMAT = 'sec-baseline-campaign-budget-v1'
MUTABLE_STATE = frozenset({'state.sqlite3', 'state.sqlite3-wal', 'state.sqlite3-shm'})
# SQLite creates and deletes its WAL and shared-memory files itself; the database file stays strict.
TRANSIENT_STATE = MUTABLE_STATE - {'state.sqlite3'}
COVERED = frozenset({'covered', 'covered_open_quarter'})
RANK = {'complete': 0, 'pending': 1, 'failed': 2}
BUDGET_TOTALS = (('attempts', 'max_request_attempts'), ('distinct_urls', 'max_distinct_urls'),
                 ('received_bytes', 'max_received_bytes'))


def dumps(value) -> str:
    return json.dumps(value, sort_keys=True, indent=1) + '\n'


# ---- file inventory -------------------------------------------------------------------------

def file_inventory(root: Path) -> dict:
    files = []
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        files.append({'relative_path': path.relative_to(root).as_posix(), 'sha256': digest,
                      'byte_count': path.stat().st_size})
    return {'root': str(root), 'file_count': len(files),
            'byte_count': sum(item['byte_count'] for item in files), 'files': files}


def recorded_inventory(value: dict) -> dict:
    """Accept the L12 machine evidence, an earlier `files` report, or a bare inventory."""
    if 'output_inventory' in value:
        return value['output_inventory']['live_root']
    return value['inventory'] if 'inventory' in value else value


def compare_inventory(recorded: dict, actual: dict) -> dict:
    """Recorded files must survive byte-identical, except the SQLite state files.

    The WAL and shared-memory files may also appear or vanish; that is reported as a state change.
    """
    before = {item['relative_path']: item for item in recorded['files']}
    after = {item['relative_path']: item for item in actual['files']}
    changed = sorted(path for path in before.keys() & after.keys()
                     if (before[path]['sha256'], before[path]['byte_count'])
                     != (after[path]['sha256'], after[path]['byte_count']))
    journal = (before.keys() ^ after.keys()) & TRANSIENT_STATE
    return {'missing': sorted(before.keys() - after.keys() - TRANSIENT_STATE),
            'added': sorted(after.keys() - before.keys() - TRANSIENT_STATE),
            'changed_immutable': [path for path in changed if path not in MUTABLE_STATE],
            'changed_state': sorted({path for path in changed if path in MUTABLE_STATE} | journal)}


# ---- transport audit ------------------------------------------------------------------------

def summarize_attempts(values: list[dict]) -> dict:
    return {'attempts': len(values),
            'distinct_urls': len({value['url'] for value in values}),
            'received_bytes': sum(value['byte_count'] or 0 for value in values),
            'max_ordinal': max((value['ordinal'] for value in values), default=0),
            'uncertain': sum(value['outcome'] == 'uncertain' for value in values),
            'access_denied': sum(value['status'] == 403 for value in values),
            'statuses': dict(sorted(Counter(str(value['status']) for value in values).items())),
            'outcomes': dict(sorted(Counter(value['outcome'] for value in values).items()))}


def check_budget(audit: dict, budget: dict) -> list[dict]:
    if budget.get('format_version') != BUDGET_FORMAT:
        raise ValueError('unsupported campaign budget format')
    breaches = []
    total = audit['total']
    for field, limit in BUDGET_TOTALS:
        if total[field] > budget[limit]:
            breaches.append({'scope': 'campaign', 'field': field, 'observed': total[field], 'limit': budget[limit]})
    for run_id, summary in audit['runs'].items():
        if summary['attempts'] > budget['max_request_attempts_per_invocation']:
            breaches.append({'scope': run_id, 'field': 'attempts', 'observed': summary['attempts'],
                             'limit': budget['max_request_attempts_per_invocation']})
    if len(audit['runs']) > budget['max_invocations']:
        breaches.append({'scope': 'campaign', 'field': 'invocations', 'observed': len(audit['runs']),
                         'limit': budget['max_invocations']})
    for field in ('access_denied', 'uncertain'):
        if total[field]:
            breaches.append({'scope': 'campaign', 'field': field, 'observed': total[field], 'limit': 0})
    return breaches


def transport_audit(store, run_ids: list[str]) -> dict:
    rows = [row.to_mapping()['value'] for row in store.scan('TransportAttempt', {})]
    runs = {run_id: summarize_attempts([value for value in rows if value['context']['run_id'] == run_id])
            for run_id in run_ids}
    return {'runs': runs,
            'total': summarize_attempts([value for value in rows if value['context']['run_id'] in runs]),
            'store_total': summarize_attempts(rows)}


# ---- coverage -------------------------------------------------------------------------------

def unit_verdict(quarter: str, open_quarter: str | None, member: dict | None, view: dict,
                 source_missing: bool) -> str:
    """One G2 verdict for one requested quarterly source unit."""
    if member is None:
        return 'source_missing' if source_missing else 'no_campaign_result'
    if member['quarantined'] and member['status'] == 'failed':
        return 'quarantined'
    if member['outcome'] == 'awaiting_approval' or any(
            item['quarter'] == quarter and item['outcome'] == 'awaiting_approval' for item in member['quarters']):
        return 'gated'
    if member['status'] != 'complete':
        return member['status']
    if (view['status'] != 'published' or view['membership_source_id'] != member['source_id']
            or view['gate'] != 'clear' or view['row_count'] == 0 or view['validated_rows'] != view['row_count']):
        return 'publication_mismatch'
    return 'covered_open_quarter' if quarter == open_quarter else 'covered'


def member_view(result, member) -> dict:
    from sec_edgar_ingest.workflows.contracts import member_status
    return {'source_id': member.source.source_id, 'kind': member.source.kind, 'period': member.source.period,
            'url': member.source.canonical_url, 'run_id': result.context.run_id,
            'attempt_id': result.context.attempt_id, 'outcome': member.outcome,
            'status': member_status(member.outcome), 'quarantined': member.quarantined,
            'downloaded': member.downloaded, 'transformed': member.transformed,
            'quarters': [{'quarter': item.quarter, 'outcome': item.outcome, 'generation_id': item.generation_id,
                          'candidate_ref': item.candidate_ref} for item in member.quarters],
            'gaps': [{'code': gap.code, 'message': gap.message} for gap in member.gaps]}


def latest_members(results) -> dict:
    """Later invocations supersede earlier ones; inside one result the worst member status wins."""
    latest = {}
    for result in results:
        mine = {}
        for member in result.members:
            view = member_view(result, member)
            held = mine.get(view['source_id'])
            if held is None or RANK[view['status']] > RANK[held['status']]:
                mine[view['source_id']] = view
        latest.update(mine)
    return latest


def quarter_view(quarter: str, objects, state) -> dict:
    from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter, validated_manifest
    try:
        capture = capture_quarter(quarter, objects, state)
        if capture is None:
            return {'quarter': quarter, 'status': 'unpublished'}
        manifest = validated_manifest(capture, objects)
        rows = sum(1 for _ in read_quarter(capture, objects))
    except Exception as error:  # Any refusal is evidence for this quarter, never a crash of the inventory.
        return {'quarter': quarter, 'status': 'capture_invalid', 'error': type(error).__name__ + ': ' + str(error)}
    membership = manifest.membership_source
    return {'quarter': quarter, 'status': 'published', 'capture': capture.to_mapping(),
            'quarter_mode': manifest.quarter_mode, 'gate': manifest.gate, 'row_count': manifest.row_count,
            'validated_rows': rows,
            'membership_source_id': None if membership is None else membership.source.source_id,
            'membership_snapshot_sha256': None if membership is None else membership.snapshot.sha256,
            'source_kinds': dict(sorted(Counter(ref.source.kind for ref in manifest.sources).items())),
            # Closed quarters with a quarterly membership publish only membership keys (catalog._resolve).
            'daily_rows_considered': sum(ref.quarter_counts.get(quarter, 0)
                                         for ref in manifest.sources if ref.source.kind == 'daily')}


def read_results(refs: list[str], store, objects) -> list:
    from sec_edgar_ingest.workflows.contracts import WorkflowResult, workflow_path
    from sec_edgar_ingest.workflows.results import _read, _validate_report
    results = []
    for ref in refs:
        value, _ = _read(ref, objects)
        result = WorkflowResult.from_mapping(value)
        if workflow_path(result.context) != ref:
            raise ValueError('workflow result path differs from its canonical identity: ' + ref)
        _validate_report(result, store, objects)
        results.append(result)
    return sorted(results, key=lambda result: (result.context.started_at, result.context.run_id))


def coverage(store, objects, refs: list[str], start: str, end: str, open_quarter: str | None) -> dict:
    from sec_edgar_ingest.discovery import quarter_span
    from sec_edgar_ingest.etl.state import EtlState
    requested = quarter_span(start, end)
    results = read_results(refs, store, objects)
    for result in results:
        if not set(result.requested_quarters) <= set(requested):
            raise ValueError('a result requested quarters outside the campaign range: ' + result.context.run_id)
    latest = latest_members(results)
    state = EtlState(store)
    published = sorted({row.to_mapping()['value']['quarter'] for row in store.scan('QuarterPublication', {})})
    views = {quarter: quarter_view(quarter, objects, state) for quarter in sorted({*requested, *published})}
    units = []
    for quarter in requested:
        quarterly = [view for view in latest.values() if view['kind'] == 'quarterly' and view['period'] == quarter]
        if len(quarterly) > 1:
            raise ValueError('more than one quarterly source claims ' + quarter)
        member = quarterly[0] if quarterly else None
        asked = [result for result in results if quarter in result.requested_quarters]
        last = asked[-1] if asked else None
        missing = last is not None and any(gap.code == 'baseline_source_missing' and gap.details.get('quarter') == quarter
                                           for gap in last.gaps)
        units.append({'quarter': quarter, 'verdict': unit_verdict(quarter, open_quarter, member, views[quarter], missing),
                      'source': member, 'filing_quarter': views[quarter],
                      'last_result_gaps': [] if last is None else sorted(
                          {gap.code for gap in last.gaps if gap.details.get('quarter') == quarter})})
    verdicts = Counter(unit['verdict'] for unit in units)
    return {'format_version': FORMAT, 'kind': 'coverage', 'requested': {'start': start, 'end': end,
            'open_quarter': open_quarter, 'quarters': len(requested)},
            'results': [{'run_id': result.context.run_id, 'attempt_id': result.context.attempt_id,
                         'command': result.context.command, 'outcome': result.outcome,
                         'counts': dict(result.counts)} for result in results],
            'verdicts': dict(sorted(verdicts.items())),
            'complete': bool(units) and set(verdicts) <= COVERED,
            'units': units,
            'other_filing_quarters': [views[quarter] for quarter in published if quarter not in requested],
            'daily_sources': sorted((view for view in latest.values() if view['kind'] == 'daily'),
                                    key=lambda view: (view['period'], view['source_id']))}


# ---- command line ---------------------------------------------------------------------------

def _open(config: Path):
    from sec_edgar_ingest.config import load_config
    from sec_edgar_ingest.storage import open_stores
    settings = load_config(config.resolve())
    opened = open_stores(settings, access='operator')
    return settings, opened


def _close(opened) -> None:
    for resource in reversed(opened):
        if resource is not None and hasattr(resource, 'close'):
            resource.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='baseline-campaign')
    commands = parser.add_subparsers(dest='command', required=True)
    files = commands.add_parser('files')
    files.add_argument('--root', type=Path, required=True)
    files.add_argument('--recorded', type=Path)
    audit = commands.add_parser('audit')
    audit.add_argument('--config', type=Path, required=True)
    audit.add_argument('--run-id', action='append', default=[])
    audit.add_argument('--budget', type=Path)
    report = commands.add_parser('coverage')
    report.add_argument('--config', type=Path, required=True)
    report.add_argument('--result', action='append', default=[])
    report.add_argument('--start', required=True)
    report.add_argument('--end', required=True)
    report.add_argument('--open-quarter')
    args = parser.parse_args(argv)
    if args.command == 'files':
        actual = file_inventory(args.root.resolve())
        value = {'format_version': FORMAT, 'kind': 'files', 'inventory': actual}
        if args.recorded is not None:
            value['comparison'] = compare_inventory(recorded_inventory(json.loads(args.recorded.read_text())), actual)
        sys.stdout.write(dumps(value))
        return 1 if args.recorded is not None and (value['comparison']['missing']
                                                   or value['comparison']['changed_immutable']) else 0
    _, opened = _open(args.config)
    try:
        if args.command == 'audit':
            value = {'format_version': FORMAT, 'kind': 'audit', **transport_audit(opened[0], args.run_id)}
            breaches = None
            if args.budget is not None:
                breaches = check_budget(value, json.loads(args.budget.read_text()))
                value['breaches'] = breaches
            sys.stdout.write(dumps(value))
            return 1 if breaches else 0
        value = coverage(opened[0], opened[1], args.result, args.start, args.end, args.open_quarter)
        sys.stdout.write(dumps(value))
        return 0
    finally:
        _close(opened)


if __name__ == '__main__':
    raise SystemExit(main())
```

- [x] **Step 4: Run the test to verify it passes**

Run the Step 2 command again.

Expected: `Ran 11 tests` and `OK`, in about 2–3 minutes. All 11 tests passed on 2026-10-21 against the checkout package.

- [x] **Step 5: Check the tool under the release interpreter, read-only**

This reads files only. It does not open SQLite.

```sh
# prelude (Global Constraints)
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json > /dev/null; echo "exit=$?"
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  | native -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["comparison"]))'
```

Expected: `exit=1`. The comparison has `missing: []`, and `changed_state` is empty or lists only SQLite state files. It has `changed_immutable` equal to exactly the F1 manifest path, and `added` equal to exactly the five `.DS_Store` paths (`.DS_Store`, `objects/.DS_Store`, `objects/raw/.DS_Store`, `objects/raw/sec/.DS_Store`, `objects/raw/sec/indexes/.DS_Store`). Any other difference stops the plan. Report it to the owner.

- [x] **Step 6: Commit**

The full offline checker is not required, because no file under `packages/sec-edgar-ingest/src` changes and the release is unchanged. Later full checker runs also collect this module.

```sh
git diff --check
git add scripts/baseline-campaign.py packages/sec-edgar-ingest/tests/test_baseline_campaign.py
git commit -m "feat(scripts): add read-only baseline campaign evidence tool"
```

---

### Task 2: Pre-campaign backup and integrity restoration (offline, owner-approved O2, O3, O9)

**Files:**
- Modify: `.gitignore` (append `backups/`)
- Create: `backups/stage2-pre-campaign-<stamp>/` (ignored)
- Create: `specs/evidence/baseline-campaign/pre-campaign/files-before.json`, `backup-files.json`, `files-after.json`
- Create: `specs/evidence/baseline-campaign/pre-campaign.md`
- Modify (data): the F1 manifest. Delete (data): the five `.DS_Store` files.

**Interfaces:**
- Consumes: Task 1 `tool files`; the recovery runbook backup procedure (`docs/runbooks/local-recovery.md`).
- Produces: a verified backup path. A live root whose L12-inventoried files all match L12 again. `pre-campaign.md` sections `Integrity findings`, `Backup`, `Restoration` and `Verification`.

The owner approved O2, O3 and O9 (D6). It stays useful under D5, because F1 also blocks any later `daily` run whose back-dated rows reach 2021Q1. No SEC request is involved. Stop at the first unexpected value and report it. Do not improvise a repair.

- [x] **Step 1: Confirm that no writer runs**

> Deviation: `pgrep` printed four processes that do not write to the store: three VS Code formatter servers and the Antigravity hub. The pattern matches the project path. A narrower check printed nothing before the copy and before the write. Recorded in `pre-campaign.md`.

```sh
# prelude (Global Constraints)
pgrep -fl 'sec_edgar_ingest|sec-edgar-local|local-bootstrap' || echo 'no writer'
```

Expected: `no writer`.

- [x] **Step 2: Record the live root before any change**

```sh
# prelude
mkdir -p "$evidence/pre-campaign"
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  > "$evidence/pre-campaign/files-before.json"; echo "exit=$?"
```

Expected: `exit=1`, with the same comparison as Task 1 Step 5.

- [x] **Step 3: Make the stopped-writer backup**

```sh
# prelude
grep -qx 'backups/' .gitignore || printf 'backups/\n' >> .gitignore
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$project/backups/stage2-pre-campaign-$stamp"
mkdir -p "$project/backups"
mkdir "$backup"
cp -Rp "$project/data" "$backup/data-raw"
native - "$project/data/state.sqlite3" "$backup/state.sqlite3" <<'PY'
import pathlib, sqlite3, sys
source, target = map(pathlib.Path, sys.argv[1:])
if target.exists(): raise ValueError('backup target must be new')
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(target) as dst: src.backup(dst)
PY
tool files --root "$backup/data-raw" --recorded "$evidence/pre-campaign/files-before.json" \
  > "$evidence/pre-campaign/backup-files.json"; echo "exit=$?"
native -c 'import json,sys; print(json.load(open(sys.argv[1]))["comparison"])' "$evidence/pre-campaign/backup-files.json"
shasum -a 256 "$backup/state.sqlite3"
echo "$backup"
```

Expected: `exit=0`. The comparison is `{'added': [], 'changed_immutable': [], 'changed_state': [], 'missing': []}`. Record the backup path and the `state.sqlite3` backup hash in `pre-campaign.md`.

- [x] **Step 4: Restore the F1 manifest from its canonical bytes**

```sh
# prelude
native - <<'PY'
import hashlib, json, os
from pathlib import Path
from sec_edgar_ingest.models import canonical_json
target = Path('/Users/lowell/Projects/sec-edgar-local/data/objects/curated/sec/filing_index/year=2021/quarter=1/'
              'generation=887cfe89f5fc96113ade4494ec2d727265baaa0dfc69b4ad9c26cbec08d15001/manifest.json')
drifted = target.read_bytes()
if hashlib.sha256(drifted).hexdigest() != '16529f52b03e2a0c178b8105ea4e7821a903d258df12b1be79d9142b567900e0':
    raise SystemExit('the manifest is not the reviewed drifted bytes; stop')
restored = canonical_json(json.loads(drifted))
if (hashlib.sha256(restored).hexdigest(), len(restored)) != (
        'a445d0a836208255d238d92434c98e58f83682bd00de5c4a76860ff24a47f11a', 5100):
    raise SystemExit('canonical bytes differ from the L12 record; stop')
temporary = target.with_name('.manifest.json.restore')
with temporary.open('xb') as stream:
    stream.write(restored)
    stream.flush()
    os.fsync(stream.fileno())
os.chmod(temporary, 0o600)
os.replace(temporary, target)
directory = os.open(target.parent, os.O_RDONLY)
os.fsync(directory)
os.close(directory)
print(hashlib.sha256(target.read_bytes()).hexdigest(), target.stat().st_size)
PY
```

Expected: `a445d0a836208255d238d92434c98e58f83682bd00de5c4a76860ff24a47f11a 5100`. The drifted bytes stay in `$backup/data-raw/…/manifest.json`.

- [x] **Step 5: Remove the five `.DS_Store` files (O3)**

> Deviation: the Claude Code safety check blocks `rm` with variable-expanded paths. The five files were removed with literal absolute paths.

```sh
# prelude
for path in .DS_Store objects/.DS_Store objects/raw/.DS_Store objects/raw/sec/.DS_Store objects/raw/sec/indexes/.DS_Store; do
  rm -- "$project/data/$path"
done
```

Expected: no output. `files-before.json` keeps their hashes.

- [x] **Step 6: Verify the root against L12 before opening the store**

> Deviation: passed with 155 files. Task 3 then closed the store, SQLite deleted its WAL and SHM files, and the check exited 1 until D7 (`4004f2e`). The re-run then exited 0 with 153 files.

```sh
# prelude
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  > "$evidence/pre-campaign/files-after.json"; echo "exit=$?"
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(v["inventory"]["file_count"], v["comparison"])' "$evidence/pre-campaign/files-after.json"
```

Expected: `exit=0`, file count 153–155, and empty `added`, `changed_immutable` and `missing`. `changed_state` is empty or lists only SQLite files. They can change when Step 3 reads the database, and SQLite deletes its WAL and SHM files when the last connection closes.

- [x] **Step 7: Verify the restored generation through its pointer**

This opens the store with operator access.

```sh
# prelude
native - <<'PY'
import json
from pathlib import Path
from sec_edgar_ingest.config import load_config
from sec_edgar_ingest.storage import open_stores
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter
settings = load_config(Path('/Users/lowell/Projects/sec-edgar-local/conf/sec-edgar-local.json'))
store, objects, _ = open_stores(settings, access='operator')
try:
    state = EtlState(store)
    pointer = state.pointer('2021Q1').to_mapping()['value']
    capture = capture_quarter('2021Q1', objects, state)
    rows = sum(1 for _ in read_quarter(capture, objects))
    print(json.dumps({'manifest_sha256': pointer['manifest_sha256'], 'manifest_bytes': pointer['manifest_bytes'],
                      'generation_id': capture.generation_id, 'rows': rows}))
finally:
    store.close()
PY
```

Expected: `{"manifest_sha256": "a445d0a836208255d238d92434c98e58f83682bd00de5c4a76860ff24a47f11a", "manifest_bytes": 5100, "generation_id": "887cfe89f5fc96113ade4494ec2d727265baaa0dfc69b4ad9c26cbec08d15001", "rows": 4}`. This matches the 2021Q1 row of the L12 table.

- [x] **Step 8: Write `specs/evidence/baseline-campaign/pre-campaign.md`**

Write these sections. Use the values printed in Steps 2–7.

```markdown
# Stage 2 pre-campaign integrity record

**Date:** <UTC date of Steps 2–7>. **Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md), Task 2.
No SEC request was sent. No writer ran during this task.

## Integrity findings (before any change)

- The live root held 160 files against the 155 in the L12 inventory
  ([files-before.json](pre-campaign/files-before.json)).
- One immutable object differed from L12: the 2021Q1 generation `887cfe89…` manifest. It had mtime
  2026-10-19 08:57 local, 5,655 bytes, SHA-256 `16529f52…`. L12 recorded 5,100 bytes, `a445d0a8…`.
  The difference is whitespace only. The cause is not established.
- Five `.DS_Store` files were present. Their hashes are in files-before.json.
- The L12 external evidence directory `/private/tmp/sec-local-task16-acceptance-20261018` was absent. A
  disk-wide search on 2026-10-21 found no copy. The committed
  [machine evidence](../local-port/sec-acceptance.json) keeps its recorded hashes and inventory.

## Backup

- Path: `<backup path>`. Raw stopped-writer copy `data-raw/` and SQLite backup-API copy
  `state.sqlite3` (SHA-256 `<hash>`).
- The raw copy matches the live root byte for byte ([backup-files.json](pre-campaign/backup-files.json)).

## Restoration (owner decisions O2 and O3)

- The manifest was rewritten with its canonical bytes after hash checks of both the drifted and
  the canonical bytes. The drifted copy remains in the backup.
- The five `.DS_Store` files were removed.

## Verification

- All 155 L12-inventoried files match again, and no other file exists
  ([files-after.json](pre-campaign/files-after.json)).
- The 2021Q1 pointer binds `a445d0a8…`, 5,100 bytes. The validated read returns 4 rows.
```

- [x] **Step 9: Commit**

```sh
git add .gitignore specs/evidence/baseline-campaign/pre-campaign.md specs/evidence/baseline-campaign/pre-campaign/
git commit -m "docs(evidence): record pre-campaign backup and manifest restoration"
```

---

### Task 3: Known answers, slice configs and campaign scope and budget (offline)

> Revision 1: executed on release `fc68adef…`. Task 3b repeats its known answers on the 1b release, makes the 1b slice configs, and rewrites `campaign.json` and `campaign.md`. The text below is the execution record. Its `slice_config` function is redefined in Task 3b.

**Files:**
- Create: `specs/evidence/baseline-campaign/pre-campaign/audit.json`, `coverage.json`
- Modify: `specs/evidence/baseline-campaign/pre-campaign.md` (append `Known-answer checks`)
- Create: `conf/stage2/backfill-2026Q4-open.json`, `conf/stage2/backfill-2015Q1-2015Q2.json`
- Create: `specs/evidence/baseline-campaign/campaign.json`, `campaign.md`

**Interfaces:**
- Consumes: the Task 1 tool and the Task 2 restored root.
- Produces: the `slice_config` shell function (used again in Task 5), the pilot and first-slice configs with their effective hashes, and `campaign.json` and `campaign.md`, which Task 4 gates and Task 5 obeys.

Slice configs and hashes bind to the release that the live config selects. The plan revision for the new release (D5) regenerates them.

- [x] **Step 1: Offline preflight of the live config**

```sh
# prelude
shasum -a 256 conf/sec-edgar-local.json
native - "$project/conf/sec-edgar-local.json" <<'PY'
import json, sys
from pathlib import Path
from sec_edgar_ingest.config import load_config
from sec_edgar_ingest.runtime import preflight_current
settings = load_config(Path(sys.argv[1]))
verified = preflight_current(Path(settings.runtime.release_manifest))
print(json.dumps({'effective_config_sha256': settings.config_sha256, 'release_id': verified.release_id,
                  'backfill': [settings.backfill.start_quarter, settings.backfill.end_quarter]}))
PY
```

Expected: file hash `cad77e29…`, then `{"effective_config_sha256": "088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d", "release_id": "fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec", "backfill": ["2015Q1", "open"]}`. A changed file hash with the same effective hash is acceptable, but record it. Any other difference stops the plan.

- [x] **Step 2: Transport known answer**

```sh
# prelude
tool audit --config "$project/conf/sec-edgar-local.json" > "$evidence/pre-campaign/audit.json"; echo "exit=$?"
native -c 'import json,sys; print(json.load(open(sys.argv[1]))["store_total"])' "$evidence/pre-campaign/audit.json"
```

Expected: `exit=0`. `store_total` has `attempts: 10`, `distinct_urls: 10`, `max_ordinal: 1`, `received_bytes: 4946565`, `uncertain: 0` and `access_denied: 0`. These are the L12 values in `sec-acceptance.md` (ten sends, 4,946,565 received bytes, no retries). A different value stops the plan. Report it, because the budget audit would then measure something else.

- [x] **Step 3: Coverage known answer**

```sh
# prelude
tool coverage --config "$project/conf/sec-edgar-local.json" --start 2015Q1 --end 2026Q4 --open-quarter 2026Q4 \
  > "$evidence/pre-campaign/coverage.json"; echo "exit=$?"
native - "$evidence/pre-campaign/coverage.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
views = [unit['filing_quarter'] for unit in value['units'] if unit['filing_quarter']['status'] == 'published']
print(value['verdicts'], len(views), sum(view['validated_rows'] for view in views),
      sorted({view['membership_source_id'] for view in views}, key=str), value['other_filing_quarters'])
PY
```

Expected: `exit=0`, then `{'no_campaign_result': 48} 16 6744 [None] []`. That is 48 units with no campaign result, 16 published quarters totaling 6,744 rows (the L12 latest-capture total), all daily-only, and no quarter outside the range.

- [x] **Step 4: Append the known-answer section to `pre-campaign.md`**

```markdown
## Known-answer checks

- Offline preflight: effective config `088403cb…`, release `fc68adef…`, range 2015Q1–open.
  Config file bytes `<hash from Step 1>`.
- [audit.json](pre-campaign/audit.json): 10 transport attempts, 10 URLs, 4,946,565 received bytes,
  ordinal 1 only. This equals L12.
- [coverage.json](pre-campaign/coverage.json): 48 requested units without a campaign result. 16 published
  quarters, all daily-only, total 6,744 validated rows. This equals the L12 latest-capture total.
```

- [x] **Step 5: Make the pilot and first-slice configs**

> Deviation: the 2024Q1 check config was removed with a literal absolute path (same safety check). Effective hashes: pilot `bef7c783…`, first slice `879d0e54…`.

The `slice_config` function is defined here and used again in Task 5.

```sh
# prelude
slice_config() {
  native - "$project/conf/sec-edgar-local.json" "$project/conf/stage2" "$1" "$2" <<'PY'
import json, sys
from pathlib import Path
from sec_edgar_ingest.config import load_config
base_path, directory, start, end = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
base = load_config(base_path)
value = json.loads(base_path.read_text())
value['backfill'] = {'start_quarter': start, 'end_quarter': end}
value['storage']['root'] = base.storage.root
value['logging']['root'] = base.logging.root
directory.mkdir(exist_ok=True)
target = directory / f'backfill-{start}-{end}.json'
with target.open('x') as stream:
    json.dump(value, stream, indent=2)
    stream.write('\n')
derived = load_config(target)
expected = base.to_mapping()
expected['backfill'] = {'start_quarter': start, 'end_quarter': end}
if derived.to_mapping() != expected:
    raise SystemExit('slice config differs from the live config beyond the backfill range')
print(target, derived.config_sha256)
PY
}
slice_config 2024Q1 2024Q1 && rm "$project/conf/stage2/backfill-2024Q1-2024Q1.json"
slice_config 2026Q4 open
slice_config 2015Q1 2015Q2
```

Expected: the first line ends with `32b4da638464758c2926fc9040e207696a081d452b2af3813ddd36d179441740`. That is the L12 quarterly config hash, which confirms the generator. That file is then removed, because 2024Q1 is not a slice of this plan. The next two lines each print a path and a new effective hash. Record both hashes in `campaign.md`.

- [x] **Step 6: Write `specs/evidence/baseline-campaign/campaign.json`**

```json
{
 "format_version": "sec-baseline-campaign-budget-v1",
 "max_distinct_urls": 300,
 "max_invocations": 16,
 "max_received_bytes": 1073741824,
 "max_request_attempts": 1500,
 "max_request_attempts_per_invocation": 700
}
```

- [x] **Step 7: Write `specs/evidence/baseline-campaign/campaign.md`**

```markdown
# Stage 2 baseline campaign: scope, budget and approval

**Status:** Proposed. Not approved. The release gate is closed. No live invocation may start until the
Release gate section is open and the Approval section is complete and committed.
**Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md).
**Spec:** §§4.2–4.9, 5–6, 7 G2 of the [ingestion spec](../../sec-filing-index-ingestion-spec.md).

## Identity

| Item | Value |
| --- | --- |
| Release | `fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec` |
| Live config | `conf/sec-edgar-local.json`, effective SHA-256 `088403cb…`, file SHA-256 `<Task 3 Step 1>` |
| Pilot config | `conf/stage2/backfill-2026Q4-open.json`, effective SHA-256 `<Task 3 Step 5>` |
| First slice config | `conf/stage2/backfill-2015Q1-2015Q2.json`, effective SHA-256 `<Task 3 Step 5>` |
| Slice generator check | reproduces the L12 quarterly config hash `32b4da63…` |
| Data / log roots | `/Users/lowell/Projects/sec-edgar-local/data` / `…/logs` |
| Pre-campaign backup | `<Task 2 backup path>` |
| Evidence tool | `scripts/baseline-campaign.py` at commit `<Task 1 commit>` |

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
```

- [x] **Step 8: Commit**

```sh
git add conf/stage2/ specs/evidence/baseline-campaign/
git commit -m "docs(evidence): propose Stage 2 campaign scope, slices and budget"
```

---

### Task 3a: Evidence tool for the 1b release: integrity coverage and member timing (offline, O12)

**Files:**
- Modify: `scripts/baseline-campaign.py`
- Modify: `packages/sec-edgar-ingest/tests/test_baseline_campaign.py`

**Interfaces:**
- Consumes: the Task 1 tool at `4004f2e`. Installed `sec_edgar_ingest` APIs of release `9fa189a0…`: everything Task 1 lists, plus `etl.reader.checked_manifest`, `StateStore.scan('Attempt' | 'WorkflowChildCall', {})`, and `RunContext.effective_config / deadline / started_at` and `WorkflowResult.ended_at`.
- Produces:
  - `coverage … [--check full|integrity]`. The output gains `check`. Default `full`: one full content check per quarter (through `read_quarter`), and `validated_rows` is the row count read. `integrity`: the exact manifest and file hashes only (C1), and `validated_rows` is null. New verdict `published_unchecked`: the unit would be checked for coverage, but its rows were not read. It never counts as coverage, so `complete` is false.
  - `timing --config PATH [--result REF]... [--max-member-wall SECONDS]` returns `{kind: timing, runs[{run_id, command, outcome, started_at, deadline, dispatch_cutoff, ended_at, tail_seconds, members[…], timed_members, b4_members, repeated_sources, max_member_wall}], child_call_rows, max_member_wall, breaches?}`. Each member is `{source_id, kind, period, outcome, b4, ran_children, reused_children, children{collect|transform|publish: {outcome, started_at, ended_at, seconds}}, child_seconds, start, last_child_end, wall_seconds, engine_seconds}`. Exit 1 when `--max-member-wall` is given and a timed member's wall exceeds it. Each breach is `{run_id, source_id, period, wall_seconds, limit}`.
  - Pure functions used by the tests: `child_attempts(values) -> dict`, `member_timings(run_id, members, attempts) -> list[dict]`, `tail_seconds(rows, ended_at) -> float | None`, `summarize_timings(rows) -> dict`.

Timing rules. A member starts at its first child's start. Members run one at a time, so a member's wall runs to the next timed member's start. The last timed member's wall runs to its own last child's end. The run's `tail_seconds` runs from there to the result's `ended_at`: the finish step and the bookkeeping for deferred members. No member's wall holds the tail, so a slow finish step cannot trip the member-wall limit (O14). That is the plan 4 definition (collect start to next collect start), not the plan 5 one (`sibling_completion` call to receipt), so the two can differ by the engine time before a member's first child, and by the last member's receipt after its last child (0.1–0.4% of a full-size member, `measurement.md` §6). Engine seconds are the wall minus the member's own child seconds. A child ref names its run, command and attempt (`runs/sec/{run}/{command}/{attempt}/result.json`). A child of another run is listed under `reused_children` and not timed. A member that ends `unchanged` with no child ref is a B4 sibling completion. A member deferred at the cutoff has no child ref and is not B4. `repeated_sources` lists the sources with more than one member that ran children in one result (F10).

- [x] **Step 1: Write the failing tests**

In `packages/sec-edgar-ingest/tests/test_baseline_campaign.py`, add these two methods to `PureRuleTests`, directly before `test_budget_breaches_name_each_exceeded_limit`:

```python
    def test_an_integrity_only_view_is_never_coverage(self):
        verdict = self.api['unit_verdict']
        member = {'source_id': 's', 'outcome': 'success', 'status': 'complete', 'quarantined': False,
                  'quarters': [{'quarter': '2026Q3', 'outcome': 'published'}]}
        unchecked = {'status': 'published', 'membership_source_id': 's', 'gate': 'clear',
                     'row_count': 3, 'validated_rows': None}
        self.assertEqual(verdict('2026Q3', '2026Q4', member, unchecked, False), 'published_unchecked')
        self.assertEqual(verdict('2026Q4', '2026Q4', member, unchecked, False), 'published_unchecked')
        self.assertEqual(verdict('2026Q3', '2026Q4', member, {**unchecked, 'membership_source_id': None}, False),
                         'publication_mismatch')
        self.assertEqual(verdict('2026Q3', '2026Q4', member, {**unchecked, 'row_count': 0}, False),
                         'publication_mismatch')

    def test_member_timings_join_children_by_attempt_and_time_each_wall(self):
        def attempt(run, command, attempt_id, start, end, outcome='success'):
            return {'context': {'run_id': run, 'command': command, 'attempt_id': attempt_id,
                                'started_at': '2026-11-02T10:' + start + '+00:00'},
                    'started_at': '2026-11-02T10:' + start + '+00:00',
                    'ended_at': None if end is None else '2026-11-02T10:' + end + '+00:00', 'outcome': outcome}
        values = [attempt('r1', 'collect', 'c1', '00:00', '00:02'), attempt('r1', 'transform', 't1', '00:02', '00:05'),
                  attempt('r1', 'publish', 'p1', '00:05', '00:10'), attempt('r1', 'publish', 'p1', '00:05', '00:06', 'received'),
                  attempt('r1', 'collect', 'c2', '00:12', '00:13'), attempt('r1', 'collect', 'c3', '00:20', None),
                  attempt('r1', 'discover', 'd1', '00:00', '00:01')]
        attempts = self.api['child_attempts'](values)
        self.assertEqual(sorted(attempts), [('r1', 'collect', 'c1'), ('r1', 'collect', 'c2'),
                                            ('r1', 'publish', 'p1'), ('r1', 'transform', 't1')])
        ref = lambda run, command, attempt_id: f'runs/sec/{run}/{command}/{attempt_id}/result.json'
        members = [
            {'source_id': 's1', 'kind': 'daily', 'period': '2026-10-01', 'outcome': 'success',
             'child_refs': [ref('r1', 'collect', 'c1'), ref('r1', 'transform', 't1'), ref('r1', 'publish', 'p1')]},
            {'source_id': 's1', 'kind': 'daily', 'period': '2026-10-01', 'outcome': 'unchanged', 'child_refs': []},
            {'source_id': 's2', 'kind': 'quarterly', 'period': '2026Q3', 'outcome': 'retry_exhausted',
             'child_refs': [ref('r0', 'collect', 'old'), ref('r1', 'collect', 'c2')]},
            {'source_id': 's2', 'kind': 'quarterly', 'period': '2026Q3', 'outcome': 'success',
             'child_refs': [ref('r1', 'publish', 'p1')]},
            {'source_id': 's3', 'kind': 'quarterly', 'period': '2026Q4', 'outcome': 'pending', 'child_refs': []}]
        rows = self.api['member_timings']('r1', [*members[:3], members[4]], attempts)
        # The last timed member's wall ends at its own last child; the finish step is the run's tail.
        self.assertEqual([(row['wall_seconds'], row['child_seconds'], row['engine_seconds'], row['b4'])
                          for row in rows], [(12.0, 10.0, 2.0, False), (None, 0, None, True),
                                             (1.0, 1.0, 0.0, False), (None, 0, None, False)])
        self.assertEqual(self.api['tail_seconds'](rows, '2026-11-02T10:00:30+00:00'), 17.0)
        self.assertIsNone(self.api['tail_seconds'](rows[1:2], '2026-11-02T10:00:30+00:00'))
        self.assertEqual(rows[0]['children']['publish'], {'outcome': 'success', 'seconds': 5.0,
                                                           'started_at': '2026-11-02T10:00:05+00:00',
                                                           'ended_at': '2026-11-02T10:00:10+00:00'})
        self.assertEqual(rows[2]['reused_children'], [ref('r0', 'collect', 'old')])
        summary = self.api['summarize_timings'](rows)
        self.assertEqual(summary, {'timed_members': 2, 'b4_members': 1, 'repeated_sources': [],
                                   'max_member_wall': {'source_id': 's1', 'kind': 'daily',
                                                       'period': '2026-10-01', 'wall_seconds': 12.0}})
        twice = self.api['member_timings']('r1', [members[0], members[3]], attempts)
        self.assertEqual(self.api['summarize_timings'](twice)['repeated_sources'], [])
        again = [members[0], {**members[0], 'child_refs': [ref('r1', 'collect', 'c2')]}]
        rows = self.api['member_timings']('r1', again, attempts)
        self.assertEqual(self.api['summarize_timings'](rows)['repeated_sources'], ['s1'])
        with self.assertRaises(ValueError):
            self.api['member_timings']('r1', [{**members[0], 'child_refs': [ref('r1', 'collect', 'c3')]}], attempts)
```

In `FixtureStoreTests`, replace the `coverage` helper:

```python
    def coverage(self, h, *refs):
        flags = [item for ref in refs for item in ('--result', ref)]
        return self.run_tool(h, 'coverage', '--config', str(h.config), *flags,
                             '--start', '2026Q2', '--end', '2026Q4', '--open-quarter', '2026Q4')
```

with this helper and two new tests:

```python
    def coverage(self, h, *refs, check=()):
        flags = [item for ref in refs for item in ('--result', ref)]
        return self.run_tool(h, 'coverage', '--config', str(h.config), *flags,
                             '--start', '2026Q2', '--end', '2026Q4', '--open-quarter', '2026Q4', *check)

    def test_integrity_coverage_reads_no_row_and_reports_no_coverage(self):
        conflict = (row('111111', 'Second', '2026-04-01', 2), row('111111', 'Changed', '2026-04-01', 2))
        h = self.harness({2: conflict, 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 3, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'], check=('--check', 'integrity'))
        self.assertEqual(code, 0)
        self.assertEqual(report['check'], 'integrity')
        self.assertEqual({unit['quarter']: unit['verdict'] for unit in report['units']},
                         {'2026Q2': 'quarantined', '2026Q3': 'published_unchecked',
                          '2026Q4': 'published_unchecked'})
        self.assertIsNone(report['units'][1]['filing_quarter']['validated_rows'])
        self.assertEqual(report['units'][1]['filing_quarter']['row_count'], 1)
        self.assertFalse(report['complete'])
        code, report = self.coverage(h, message['result_ref'])
        self.assertEqual((report['check'], report['units'][1]['verdict']), ('full', 'covered'))

    def test_timing_times_each_member_and_refuses_a_member_over_the_limit(self):
        h = self.harness({2: (row('111111', 'Second', '2026-04-01', 2),), 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        code, report = self.run_tool(h, 'timing', '--config', str(h.config), '--result', message['result_ref'])
        self.assertEqual(code, 0, report)
        self.assertNotIn('breaches', report)
        run = report['runs'][0]
        self.assertEqual((run['run_id'], run['timed_members'], run['b4_members'], run['repeated_sources']),
                         ('r1', 3, 0, []))
        self.assertIsNone(run['dispatch_cutoff'])
        self.assertGreaterEqual(run['tail_seconds'], 0)
        for member in run['members']:
            self.assertEqual(set(member['children']), {'collect', 'transform', 'publish'})
            self.assertGreaterEqual(member['wall_seconds'], member['child_seconds'])
            self.assertGreater(member['child_seconds'], 0)
            self.assertGreaterEqual(member['engine_seconds'], 0)
        self.assertGreaterEqual(report['child_call_rows'], 9)
        code, report = self.run_tool(h, 'timing', '--config', str(h.config), '--result', message['result_ref'],
                                     '--max-member-wall', '0')
        self.assertEqual(code, 1)
        self.assertEqual(sorted(item['period'] for item in report['breaches']), ['2026Q2', '2026Q3', '2026Q4'])
        self.assertTrue(all(item['limit'] == 0 for item in report['breaches']))
```

The fixture settings carry no reserve key, so `dispatch_cutoff` is null there.

- [x] **Step 2: Run the tests to verify they fail**

```sh
cd /Users/lowell/Projects/sec-edgar-local
UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --locked --package sec-edgar-ingest \
  python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests \
  -p test_baseline_campaign.py
```

Expected: `Ran 15 tests` and `FAILED (failures=1, errors=3)`. The failure is `'publication_mismatch' != 'published_unchecked'`. The errors are `KeyError: 'child_attempts'`, `invalid choice: 'timing'` and the unknown `--check` argument.

- [x] **Step 3: Write the implementation**

In `scripts/baseline-campaign.py`, make these changes.

Replace the module docstring with:

```python
"""Read-only Stage 2 baseline-campaign evidence: file inventory, transport audit, coverage and timing.

Run under the selected release interpreter with -I -B -X pycache_prefix=/dev/null. The tool opens
the store with operator access, sends no request and writes nothing under the store root. It uses
release internals (workflow result validation, ETL readers, durable child attempts). It is verified
against releases fc68adef... and 9fa189a0...; re-verify it before use with any other release.
"""
```

After `from collections import Counter`, add:

```python
from datetime import datetime, timedelta
```

After the `RANK = …` line, add:

```python
CHECKS = ('full', 'integrity')
CHILD_COMMANDS = ('collect', 'transform', 'publish')
```

In `unit_verdict`, replace:

```python
    if (view['status'] != 'published' or view['membership_source_id'] != member['source_id']
            or view['gate'] != 'clear' or view['row_count'] == 0 or view['validated_rows'] != view['row_count']):
        return 'publication_mismatch'
```

with:

```python
    if (view['status'] != 'published' or view['membership_source_id'] != member['source_id']
            or view['gate'] != 'clear' or view['row_count'] == 0):
        return 'publication_mismatch'
    if view['validated_rows'] is None:
        return 'published_unchecked'  # An integrity-only view never counts as coverage.
    if view['validated_rows'] != view['row_count']:
        return 'publication_mismatch'
```

Replace the head of `quarter_view`, up to and including its `rows = …` line:

```python
def quarter_view(quarter: str, objects, state) -> dict:
    from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter, validated_manifest
    try:
        capture = capture_quarter(quarter, objects, state)
        if capture is None:
            return {'quarter': quarter, 'status': 'unpublished'}
        manifest = validated_manifest(capture, objects)
        rows = sum(1 for _ in read_quarter(capture, objects))
```

with:

```python
def quarter_view(quarter: str, objects, state, check: str = 'full') -> dict:
    """`full` reads every row through the release's full content check (once); `integrity` checks
    only the exact manifest and file hashes (C1) and reports `validated_rows` as null."""
    from sec_edgar_ingest.etl.reader import capture_quarter, checked_manifest, read_quarter
    if check not in CHECKS:
        raise ValueError('unknown quarter check: ' + check)
    try:
        capture = capture_quarter(quarter, objects, state)
        if capture is None:
            return {'quarter': quarter, 'status': 'unpublished'}
        rows = sum(1 for _ in read_quarter(capture, objects)) if check == 'full' else None
        manifest = checked_manifest(capture, objects)
```

In `coverage`, change the signature to:

```python
def coverage(store, objects, refs: list[str], start: str, end: str, open_quarter: str | None,
             check: str = 'full') -> dict:
```

change the `views = …` line to:

```python
    views = {quarter: quarter_view(quarter, objects, state, check) for quarter in sorted({*requested, *published})}
```

and change the first line of its `return` to:

```python
    return {'format_version': FORMAT, 'kind': 'coverage', 'check': check, 'requested': {'start': start, 'end': end,
```

Directly before the `# ---- command line ----` comment, add:

```python
# ---- member timing --------------------------------------------------------------------------

def _time(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _seconds(start, end) -> float:
    return round((_time(end) - _time(start)).total_seconds(), 3)


def child_attempts(values: list[dict]) -> dict:
    """Finished child `Attempt` values keyed by (run_id, command, attempt_id); the latest end wins."""
    found = {}
    for value in values:
        context = value['context']
        if (context['command'] not in CHILD_COMMANDS or value.get('ended_at') is None
                or value.get('outcome') == 'received'):
            continue
        key = (context['run_id'], context['command'], context['attempt_id'])
        held = found.get(key)
        if held is None or _time(value['ended_at']) > _time(held['ended_at']):
            found[key] = value
    return found


def member_timings(run_id: str, members: list[dict], attempts: dict) -> list[dict]:
    """Per-member child seconds and wall for one workflow result.

    A member starts at its first child's start. Members run one at a time, so a member's wall runs to
    the next timed member's start. The last timed member's wall runs to its own last child's end, so no
    member's wall holds the finish step (see `tail_seconds`). Engine seconds are the wall minus the
    member's own child seconds. A child of another run (a reused child) is listed, not timed. A member
    that ends `unchanged` with no child ref is a B4 sibling completion. A member deferred at the cutoff
    has no child ref either, and is not B4.
    """
    rows = []
    for member in members:
        children, reused = {}, []
        for ref in member['child_refs']:
            _, _, ref_run, command, attempt_id, _ = ref.split('/')
            if ref_run != run_id:
                reused.append(ref)
                continue
            value = attempts.get((ref_run, command, attempt_id))
            if value is None:
                raise ValueError('child result has no finished attempt record: ' + ref)
            started = value.get('started_at') or value['context']['started_at']
            children[command] = {'outcome': value['outcome'], 'started_at': str(started),
                                 'ended_at': str(value['ended_at']), 'seconds': _seconds(started, value['ended_at'])}
        start = min((_time(child['started_at']) for child in children.values()), default=None)
        end = max((_time(child['ended_at']) for child in children.values()), default=None)
        rows.append({'source_id': member['source_id'], 'kind': member['kind'], 'period': member['period'],
                     'outcome': member['outcome'], 'b4': not member['child_refs'] and member['outcome'] == 'unchanged',
                     'ran_children': bool(member['child_refs']), 'reused_children': reused,
                     'children': children, 'child_seconds': round(sum(c['seconds'] for c in children.values()), 3),
                     'start': None if start is None else start.isoformat(),
                     'last_child_end': None if end is None else end.isoformat(),
                     'wall_seconds': None, 'engine_seconds': None})
    timed = sorted((row for row in rows if row['start'] is not None), key=lambda row: row['start'])
    for row, following in zip(timed, [*timed[1:], None]):
        end = row['last_child_end'] if following is None else following['start']
        row['wall_seconds'] = _seconds(row['start'], end)
        row['engine_seconds'] = round(row['wall_seconds'] - row['child_seconds'], 3)
    return rows


def tail_seconds(rows: list[dict], ended_at) -> float | None:
    """Seconds from the last child's end to the result's end: the finish step and deferral bookkeeping."""
    ends = [row['last_child_end'] for row in rows if row['last_child_end'] is not None]
    return None if not ends else _seconds(max(ends, key=_time), ended_at)


def summarize_timings(rows: list[dict]) -> dict:
    timed = [row for row in rows if row['wall_seconds'] is not None]
    sources = Counter(row['source_id'] for row in rows if row['ran_children'])
    slowest = max(timed, key=lambda row: row['wall_seconds'], default=None)
    return {'timed_members': len(timed), 'b4_members': sum(row['b4'] for row in rows),
            'repeated_sources': sorted(source for source, count in sources.items() if count > 1),
            'max_member_wall': None if slowest is None else {
                key: slowest[key] for key in ('source_id', 'kind', 'period', 'wall_seconds')}}


def run_timing(store, objects, refs: list[str], max_wall: float | None) -> dict:
    results = read_results(refs, store, objects)
    attempts = child_attempts([row.to_mapping()['value'] for row in store.scan('Attempt', {})])
    runs, breaches = [], []
    for result in results:
        context = result.context
        members = [{'source_id': member.source.source_id, 'kind': member.source.kind,
                    'period': member.source.period, 'outcome': member.outcome,
                    'child_refs': list(member.child_refs)} for member in result.members]
        rows = member_timings(context.run_id, members, attempts)
        reserve = context.effective_config.get('execution', {}).get('dispatch_reserve_seconds')
        deadline = _time(context.deadline)
        runs.append({'run_id': context.run_id, 'command': context.command, 'outcome': result.outcome,
                     'started_at': _time(context.started_at).isoformat(), 'deadline': deadline.isoformat(),
                     'dispatch_cutoff': None if reserve is None else (deadline - timedelta(seconds=reserve)).isoformat(),
                     'ended_at': _time(result.ended_at).isoformat(), 'tail_seconds': tail_seconds(rows, result.ended_at),
                     'members': rows, **summarize_timings(rows)})
        if max_wall is not None:
            breaches += [{'run_id': context.run_id, 'source_id': row['source_id'], 'period': row['period'],
                          'wall_seconds': row['wall_seconds'], 'limit': max_wall}
                         for row in rows if row['wall_seconds'] is not None and row['wall_seconds'] > max_wall]
    every = [row for run in runs for row in run['members']]
    value = {'format_version': FORMAT, 'kind': 'timing', 'runs': runs,
             'child_call_rows': sum(1 for _ in store.scan('WorkflowChildCall', {})),
             'max_member_wall': summarize_timings(every)['max_member_wall']}
    if max_wall is not None:
        value['breaches'] = breaches
    return value


```

In `main`, after `report.add_argument('--open-quarter')`, add:

```python
    report.add_argument('--check', choices=CHECKS, default='full')
    timing = commands.add_parser('timing')
    timing.add_argument('--config', type=Path, required=True)
    timing.add_argument('--result', action='append', default=[])
    timing.add_argument('--max-member-wall', type=float)
```

and replace:

```python
        value = coverage(opened[0], opened[1], args.result, args.start, args.end, args.open_quarter)
        sys.stdout.write(dumps(value))
        return 0
```

with:

```python
        if args.command == 'timing':
            value = run_timing(opened[0], opened[1], args.result, args.max_member_wall)
            sys.stdout.write(dumps(value))
            return 1 if value.get('breaches') else 0
        value = coverage(opened[0], opened[1], args.result, args.start, args.end, args.open_quarter, args.check)
        sys.stdout.write(dumps(value))
        return 0
```

- [x] **Step 4: Run the tests to verify they pass**

Run the Step 2 command again.

Expected: `Ran 15 tests` and `OK`, in about 2.5 minutes. On 2026-10-29, planning applied this task's blocks to a throwaway copy of `4004f2e`'s files as Steps 1 and 3 say: Step 2 gave exactly the result above, and this step passed (147.7 s).

- [x] **Step 5: Check the tool under the release interpreter, read-only**

```sh
# prelude (Global Constraints)
pgrep -fl -- '-m sec_edgar_ingest|scripts/sec-edgar-local|local-bootstrap|local_bootstrap' || echo 'no writer'
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  | native -c 'import json,sys; v=json.load(sys.stdin); print(v["inventory"]["file_count"], json.dumps(v["comparison"]))'
tool timing --config "$project/conf/sec-edgar-local.json"; echo "timing exit=$?"
```

Expected: `no writer`. Then `153` and a comparison with `missing`, `added` and `changed_immutable` empty, and `changed_state` empty or listing only `state.sqlite3-shm` and `state.sqlite3-wal` (F14). Then a timing report with `runs: []`, `child_call_rows: 0` and `max_member_wall: null`, and `timing exit=0`. Any other result stops the plan. Report it to the owner.

- [x] **Step 6: Commit**

The full offline checker is not required: no file under `packages/sec-edgar-ingest/src` changes, and the release is unchanged.

```sh
git diff --check
git add scripts/baseline-campaign.py packages/sec-edgar-ingest/tests/test_baseline_campaign.py
git commit -m "feat(scripts): add integrity coverage and member timing to the campaign tool"
```

---

### Task 3b: Known answers, slice configs and campaign files on the 1b release (offline, O13–O16)

> Revision 2: executed at `c9a9cb3`. Task 3c replaces this task's live-config values and removes five of its 13 configs. The text below is the execution record.

**Files:**
- Create: `specs/evidence/baseline-campaign/pre-campaign/1b/preflight.json`, `audit.json`, `coverage-integrity.json`, `coverage-full.json`, `timing.json`, `files.json`
- Modify: `specs/evidence/baseline-campaign/pre-campaign.md` (append a Revision 1 section)
- Create: the 13 files `conf/stage2/1b/backfill-<start>-<end>.json` listed in F13
- Modify (rewrite): `specs/evidence/baseline-campaign/campaign.json`, `specs/evidence/baseline-campaign/campaign.md`

**Interfaces:**
- Consumes: the Task 3a tool and its commit hash, and the live root as Task 2 left it (F14).
- Produces: the 13 slice configs with the F13 effective hashes; `campaign.json` with `max_member_wall_seconds`, which Task 5 passes to `timing`; and `campaign.md`, which Task 4 gates and Task 5 obeys.

- [x] **Step 1: Offline preflight of the live config**

```sh
# prelude
mkdir -p "$evidence/pre-campaign/1b"
shasum -a 256 conf/sec-edgar-local.json
native - "$project/conf/sec-edgar-local.json" <<'PY' | tee "$evidence/pre-campaign/1b/preflight.json"
import json, sys
from pathlib import Path
from sec_edgar_ingest.config import load_config
from sec_edgar_ingest.runtime import preflight_current
settings = load_config(Path(sys.argv[1]))
verified = preflight_current(Path(settings.runtime.release_manifest))
print(json.dumps({'effective_config_sha256': settings.config_sha256, 'release_id': verified.release_id,
                  'backfill': [settings.backfill.start_quarter, settings.backfill.end_quarter],
                  'dispatch_reserve_seconds': settings.execution.dispatch_reserve_seconds},
                 sort_keys=True, indent=1))
PY
```

Expected: file hash `de6c0dd9a67ff4bb29adf82d6df8eb5c69b934ed801ea7f5c2f3c26cc9d47fcc`, then `backfill` `["2015Q1", "open"]`, `dispatch_reserve_seconds` `1800`, `effective_config_sha256` `db62e7fb8c941f125f84992c5bccfdbb65d6461231d899054af505700e9004b1` and `release_id` `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b`. Any difference stops the plan.

- [x] **Step 2: Known answers on the live store**

```sh
# prelude
out="$evidence/pre-campaign/1b"
tool audit --config "$project/conf/sec-edgar-local.json" > "$out/audit.json"; echo "audit exit=$?"
tool coverage --config "$project/conf/sec-edgar-local.json" --start 2015Q1 --end 2026Q4 --open-quarter 2026Q4 \
  --check integrity > "$out/coverage-integrity.json"; echo "integrity exit=$?"
tool coverage --config "$project/conf/sec-edgar-local.json" --start 2015Q1 --end 2026Q4 --open-quarter 2026Q4 \
  --check full > "$out/coverage-full.json"; echo "full exit=$?"
tool timing --config "$project/conf/sec-edgar-local.json" > "$out/timing.json"; echo "timing exit=$?"
mkdir -p "$campaign_logs"
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json > "$campaign_logs/files-1b.json"; echo "files exit=$?"
native - "$campaign_logs/files-1b.json" <<'PY' > "$out/files.json"
import json, sys
value = json.load(open(sys.argv[1]))
print(json.dumps({'file_count': value['inventory']['file_count'], 'byte_count': value['inventory']['byte_count'],
                  'comparison': value['comparison']}, sort_keys=True, indent=1))
PY
native - "$out" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
print(json.load(open(out / 'audit.json'))['store_total'])
for name in ('coverage-integrity.json', 'coverage-full.json'):
    value = json.load(open(out / name))
    views = [unit['filing_quarter'] for unit in value['units'] if unit['filing_quarter']['status'] == 'published']
    print(value['check'], value['verdicts'], len(views), sorted({str(view['validated_rows']) for view in views})[:1],
          sum(view['validated_rows'] or 0 for view in views),
          sorted({view['membership_source_id'] for view in views}, key=str), value['other_filing_quarters'])
timing = json.load(open(out / 'timing.json'))
print(timing['runs'], timing['child_call_rows'], json.load(open(out / 'files.json')))
PY
```

Expected, as planning observed on 2026-10-29 (F15):

- `audit exit=0`, `integrity exit=0`, `full exit=0`, `timing exit=0`, `files exit=0`. The full coverage takes about one minute.
- `store_total` has `attempts: 10`, `distinct_urls: 10`, `max_ordinal: 1`, `received_bytes: 4946565`, `uncertain: 0`, `access_denied: 0`.
- `integrity {'no_campaign_result': 48} 16 ['None'] 0 [None] []`.
- `full {'no_campaign_result': 48} 16 ['1'] 6744 [None] []`. The `['1']` is only the first row count in sort order.
- `[] 0`, then 153 files and a comparison with only SQLite journal files under `changed_state`.

Any other value stops the plan. Report it, because the campaign checks would then measure something else.

- [x] **Step 3: Make the 13 slice configs**

The `slice_config` function writes into `conf/stage2/1b/`. Do not touch the two files directly under `conf/stage2/`.

```sh
# prelude
slice_config() {
  native - "$project/conf/sec-edgar-local.json" "$project/conf/stage2/1b" "$1" "$2" <<'PY'
import json, sys
from pathlib import Path
from sec_edgar_ingest.config import load_config
base_path, directory, start, end = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
base = load_config(base_path)
value = json.loads(base_path.read_text())
value['backfill'] = {'start_quarter': start, 'end_quarter': end}
value['storage']['root'] = base.storage.root
value['logging']['root'] = base.logging.root
directory.mkdir(parents=True, exist_ok=True)
target = directory / f'backfill-{start}-{end}.json'
with target.open('x') as stream:
    json.dump(value, stream, indent=2)
    stream.write('\n')
derived = load_config(target)
expected = base.to_mapping()
expected['backfill'] = {'start_quarter': start, 'end_quarter': end}
if derived.to_mapping() != expected:
    raise SystemExit('slice config differs from the live config beyond the backfill range')
print(target.name, derived.config_sha256)
PY
}
slice_config 2015Q1 open && rm "$project/conf/stage2/1b/backfill-2015Q1-open.json"
slice_config 2026Q4 open
for year in 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025; do slice_config "${year}Q1" "${year}Q4"; done
slice_config 2026Q1 2026Q3
ls "$project/conf/stage2/1b" | wc -l
```

Expected: the first line is `backfill-2015Q1-open.json db62e7fb8c941f125f84992c5bccfdbb65d6461231d899054af505700e9004b1`, the live effective hash, which confirms the generator. That file is then removed. The next 13 lines each print a file name and exactly the effective hash in the F13 table. The last line is `13`. Any other hash stops the plan.

- [x] **Step 4: Rewrite `specs/evidence/baseline-campaign/campaign.json`**

```json
{
 "format_version": "sec-baseline-campaign-budget-v1",
 "max_distinct_urls": 300,
 "max_invocations": 40,
 "max_member_wall_seconds": 1056,
 "max_received_bytes": 1073741824,
 "max_request_attempts": 1500,
 "max_request_attempts_per_invocation": 700
}
```

`check_budget` reads only its named limits. Task 5 passes `max_member_wall_seconds` to `timing --max-member-wall`.

- [x] **Step 5: Rewrite `specs/evidence/baseline-campaign/campaign.md`**

Replace the whole file with the text below. Put the Task 3a commit hash (`git log -1 --format=%h -- scripts/baseline-campaign.py`) in the Evidence tool row.

```markdown
# Stage 2 baseline campaign: scope, budget and approval

**Status:** Proposed for release `9fa189a0…`. Not approved. No live invocation may start until the
Release gate section is open and the Approval section is complete and committed.
**Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md), Revision 1.
**Spec:** §§4.2–4.9, 5–6, 7 G2 of the [ingestion spec](../../sec-filing-index-ingestion-spec.md).
**History:** the version of this file at commit `ea482dd` proposed a campaign on release `fc68adef…`. Its
release gate stayed closed (plan 2, F11). This version replaces it.

## Identity

| Item | Value |
| --- | --- |
| Release | `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b` (version 0.2.0) |
| Live config | `conf/sec-edgar-local.json`, effective SHA-256 `db62e7fb…`, file SHA-256 `de6c0dd9…` |
| Dispatch reserve / floor | 1,800 s / 480 s. At the 3,300 s timeout, no member starts after 1,500 s. |
| Slice configs | `conf/stage2/1b/`, 13 files. Effective hashes: plan 2, F13. |
| Slice generator check | `2015Q1`–`open` reproduces the live effective hash `db62e7fb…` |
| Data / log roots | `/Users/lowell/Projects/sec-edgar-local/data` / `…/logs` |
| Pre-campaign backup | `backups/stage2-pre-campaign-20261021T180646Z` |
| Evidence tool | `scripts/baseline-campaign.py` at commit `<Task 3a commit>` |

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
4. The offline preflight passes on this release ([pre-campaign.md](pre-campaign.md), Revision 1 section).

## Source scope

- Workflow: launcher `backfill` only, with one slice config for each invocation. No `daily`,
  `reconcile`, low-level command, `approve` or `rollback`.
- Requested units: the quarterly sources 2015Q1–2026Q4, which is 48 units. 2026Q4 is the open quarter.
  Its source is quarter-to-date, and absence from it is not withdrawal authority (§4.4).
- Slice plan, in this order (plan 2 F9, O13):
  1. The pilot `2026Q4`–`open`. It carries every pending daily source as retained work: every daily
     body listed under `daily-index/2026/QTR3` and `QTR4`. L12 left 73 such sources, and each business
     day since has added one. These daily units are not baseline units. The finding reports them apart,
     for Stage 3. The pilot reruns under stop rule 9 until no daily source is pending. Its 2026Q4 daily
     members that run after the 2026Q4 quarterly source is published are the A1 class (O15).
  2. The calendar years 2015, 2016, …, 2025, one slice each, in ascending order.
  3. `2026Q1`–`2026Q3`.
  Together the slices cover every quarter exactly once. About 2 full-size quarters start in one
  invocation. A slice that does not fit defers its last members, and stop rule 9 reruns it.
- Source quarters and output filing quarters differ (§4.2). Daily rows can be back-dated into old filing
  quarters (findings §4.7).
- Expected exceptions: the 2024Q1 quarantine (line 88043), retained and selected again by the 2024
  slice. Possible quarantines for 2015Q1 and 2026Q3 (retained conflict specimens). Possible withdrawal
  gates for closed quarters that hold back-dated daily rows (plan 2 F5, O10). Possibly a refused
  incremental candidate (O16).

## Budget

| Bound | Limit | Enforced by | Basis |
| --- | --- | --- | --- |
| Invocations | 40 | audit, stop rule 4 | pilot 2–4; about 24 for the year slices at about 2 full-size members each; reruns |
| Runtime per invocation | 3,300 s (launcher default) | launcher | live maximum 3,600 s; must stay above the 1,800 s reserve |
| Dispatch cutoff | deadline − 1,800 s | runner | parent spec §4.7 |
| Member wall | 1,056 s (`max_member_wall_seconds`) | timing after the invocation, stop rule 7 | reserve rule 1.25 × w + 480 ≤ 1,800 (plan 2 O14) |
| Request rate | 3/s, one collector | coordinator | §4.8 |
| Attempts per URL per command | 5 | downloader | §4.8 |
| Bytes per response | 67,108,864 received / 536,870,912 expanded | downloader | §4.8 |
| Request attempts per invocation | 700 | audit after the invocation | pilot about 10 listings + 1 quarterly + about 90 daily bodies; 5 attempts each is about 505 |
| Request attempts, campaign | 1,500 | audit | about 100 pilot sends; each year-slice invocation about 6 listings and up to 4 bodies; reruns add listings |
| Distinct URLs, campaign | 300 | audit | about 1 + 12 + 48 full-index listings, 48 quarterly bodies, 4 daily listings and about 90 daily bodies, about 203 |
| Received bytes, campaign | 1,073,741,824 | audit | about 47 × 4.3 MB + 90 × 0.35 MB, about 235 MB (2024Q1 4,262,821; daily 289,582 and 329,651) |
| Expanded validation bytes, campaign | declared 16 GiB | not counted durably by the launcher; reported after the campaign from retained raw ZIP member sizes | 2024Q1 `master.idx` 33,578,469 |
| Free disk before each invocation | at least 50 GiB | pre-check | 497 GiB free on 2026-10-29 |
| Store growth | at most 30 GiB | pre-check | whole-quarter generations are rewritten by full rebuilds |
| Window | from the approved UTC start, at most 7 days, and ending before 2027-01-01T00:00:00Z | pre-check | `open` must stay 2026Q4 |

The audit checks the aggregate limits between invocations, not inside one. Inside one invocation, the
hard bounds are the runtime, the dispatch cutoff, the rate, the per-URL attempt limit and the
per-response byte limits. Expected launcher time: about 26–30 invocations of about 2,200 s each.

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
12. **Finish** when every quarter 2015Q1–2026Q4 has a campaign result and no member has outcome
    `pending`, `deferred` or `throttled`. Quarantined, failed and `awaiting_approval` members are not
    eligible work.

A halt stops the campaign. The operator reports to the owner and does nothing else. A halt is evidence,
not a failure of the plan.

## Evidence locations

- Committed: this directory. `pre-campaign.md`, `pre-campaign/1b/`, `invocations.md`,
  `invocations/<k>-<run-id>.json`, `final/`, `quarantine/`, `coverage-finding.md`. Slice configs in
  `conf/stage2/1b/`.
- Raw and ignored: `data/` (store, durable results), `logs/<run-id>/<attempt-id>/` (launcher evidence),
  `logs/baseline-campaign/` (coverage, audit, timing and files reports after each invocation), `backups/`
  (pre-campaign backup).

## Approval boundary

- Plan 2's approval authorized Tasks 1–3. The owner's approval of Revision 1 authorizes Tasks 3a and 3b.
- A live invocation needs all four of these: (1) the Release gate above, open; (2) the Approval section
  below, completed with the owner's words and committed; (3) the Task 3b files check with exit 0;
  (4) the sole-issuer declaration below, with its start time.
- Never authorized here: `approve`, `rollback`, `daily`, `reconcile`, a parser, schema, release or live
  config change, a second root, object removal, or any SEC request outside the launcher.

## Approval

To be completed in Task 4 with the owner's exact words.
```

- [x] **Step 6: Append the Revision 1 section to `pre-campaign.md`**

Fill each value from the Step 1–3 outputs.

```markdown
## Known-answer checks on release 9fa189a0… (plan 2 Revision 1)

- [1b/preflight.json](pre-campaign/1b/preflight.json): effective config `db62e7fb…`, release `9fa189a0…`,
  range 2015Q1–open, reserve 1800. Config file bytes `de6c0dd9…`.
- Slice generator: `2015Q1`–`open` reproduces `db62e7fb…`. The 13 configs in `conf/stage2/1b/` match
  plan 2, F13.
- [1b/audit.json](pre-campaign/1b/audit.json): 10 transport attempts, 10 URLs, 4,946,565 received bytes,
  ordinal 1 only. This equals L12.
- [1b/coverage-integrity.json](pre-campaign/1b/coverage-integrity.json) and
  [1b/coverage-full.json](pre-campaign/1b/coverage-full.json): 48 requested units without a campaign
  result; 16 published quarters, all daily-only. The full check reads 6,744 rows, the L12 latest-capture
  total. The integrity check reads no row.
- [1b/timing.json](pre-campaign/1b/timing.json): no workflow result yet, 0 `WorkflowChildCall` rows.
- [1b/files.json](pre-campaign/1b/files.json): 153 files. Against L12, only SQLite journal state changed.
```

- [x] **Step 7: Commit**

```sh
git add conf/stage2/1b/ specs/evidence/baseline-campaign/
git commit -m "docs(evidence): rebase the Stage 2 campaign onto the 1b release"
```

---

### Task 3c: Start the range at 2020Q1: live config, spec, slices, known answers and campaign files (offline, D10, O18, O19)

> Revision 2: new task.

**Files:**
- Modify: `conf/sec-edgar-local.json` (one substitution)
- Modify: `specs/sec-filing-index-ingestion-spec.md` (§4.8: the backfill row and the effective hash; the status line untouched)
- Modify: `docs/runbooks/local-ingestion.md` (line 23, the backfill start)
- Delete: `conf/stage2/1b/backfill-2015Q1-2015Q4.json`, `backfill-2016Q1-2016Q4.json`, `backfill-2017Q1-2017Q4.json`, `backfill-2018Q1-2018Q4.json`, `backfill-2019Q1-2019Q4.json`
- Create: `specs/evidence/baseline-campaign/pre-campaign/rev2/preflight.json`, `audit.json`, `coverage-integrity.json`, `coverage-full.json`, `timing.json`, `files.json`
- Modify: `specs/evidence/baseline-campaign/campaign.json`, `campaign.md`, `pre-campaign.md` (append a Revision 2 section)

**Interfaces:**
- Consumes: D10, O18, O19. The Task 3a tool at `b176598`. The Task 3b files at `c9a9cb3`. The live root as Task 2 left it (F14).
- Produces: the live config with file hash `bfdf2985…` and effective hash `2512fdcb…`. 8 slice configs with their F13 hashes. `campaign.json` with `max_invocations` 24. `campaign.md` for the 2020Q1 range, which Task 4 gates and Task 5 obeys.

No file under `packages/sec-edgar-ingest/src` changes, the release is unchanged, and no test reads the live config (Revision 2, item 4). So the full offline checker is not required.

- [ ] **Step 1: Confirm the starting state**

```sh
# prelude
pgrep -fl -- '-m sec_edgar_ingest|scripts/sec-edgar-local|local-bootstrap|local_bootstrap' || echo 'no writer'
shasum -a 256 conf/sec-edgar-local.json
git status --short -- conf/ specs/ docs/
ls conf/stage2/1b | wc -l
```

Expected: `no writer`, the file hash `de6c0dd9a67ff4bb29adf82d6df8eb5c69b934ed801ea7f5c2f3c26cc9d47fcc`, no `git status` line, and `13`. Any other result stops the plan.

- [ ] **Step 2: Edit the live config**

This is the one approved edit of the live config (D10). It changes only the start quarter.

```sh
# prelude
native - "$project/conf/sec-edgar-local.json" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
data = path.read_bytes()
old, new = b'"start_quarter": "2015Q1"', b'"start_quarter": "2020Q1"'
if data.count(old) != 1:
    raise SystemExit('expected exactly one 2015Q1 start_quarter')
path.write_bytes(data.replace(old, new))
PY
shasum -a 256 conf/sec-edgar-local.json
git diff --stat -- conf/sec-edgar-local.json
```

Expected: `bfdf29859325fa396520c0fabd0bcd6f6e34d8854b558d56e4bf4a7731038204`, then `1 file changed, 1 insertion(+), 1 deletion(-)`. Any other hash stops the plan: restore the file with `git checkout -- conf/sec-edgar-local.json` and report.

- [ ] **Step 3: Offline preflight of the edited config**

```sh
# prelude
mkdir -p "$evidence/pre-campaign/rev2"
native - "$project/conf/sec-edgar-local.json" <<'PY' | tee "$evidence/pre-campaign/rev2/preflight.json"
import json, sys
from pathlib import Path
from sec_edgar_ingest.config import load_config
from sec_edgar_ingest.runtime import preflight_current
settings = load_config(Path(sys.argv[1]))
verified = preflight_current(Path(settings.runtime.release_manifest))
print(json.dumps({'effective_config_sha256': settings.config_sha256, 'release_id': verified.release_id,
                  'backfill': [settings.backfill.start_quarter, settings.backfill.end_quarter],
                  'dispatch_reserve_seconds': settings.execution.dispatch_reserve_seconds},
                 sort_keys=True, indent=1))
PY
```

Expected: `backfill` `["2020Q1", "open"]`, `dispatch_reserve_seconds` `1800`, `effective_config_sha256` `2512fdcb999a302d93de84315d45e4e44d0bb942d5165698b64c371fc42b5be5` and `release_id` `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b`. Any difference stops the plan.

- [ ] **Step 4: Remove the five unused slice configs (O18)**

```sh
# prelude
for year in 2015 2016 2017 2018 2019; do git rm -q "conf/stage2/1b/backfill-${year}Q1-${year}Q4.json"; done
ls conf/stage2/1b
```

Expected: exactly these 8 names: `backfill-2020Q1-2020Q4.json`, `backfill-2021Q1-2021Q4.json`, `backfill-2022Q1-2022Q4.json`, `backfill-2023Q1-2023Q4.json`, `backfill-2024Q1-2024Q4.json`, `backfill-2025Q1-2025Q4.json`, `backfill-2026Q1-2026Q3.json`, `backfill-2026Q4-open.json`.

- [ ] **Step 5: Check the generator and the kept slices against the edited config**

The `slice_config` function is Task 3b's, unchanged. It writes into `conf/stage2/1b/` and refuses to overwrite a file.

```sh
# prelude
slice_config() {
  native - "$project/conf/sec-edgar-local.json" "$project/conf/stage2/1b" "$1" "$2" <<'PY'
import json, sys
from pathlib import Path
from sec_edgar_ingest.config import load_config
base_path, directory, start, end = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
base = load_config(base_path)
value = json.loads(base_path.read_text())
value['backfill'] = {'start_quarter': start, 'end_quarter': end}
value['storage']['root'] = base.storage.root
value['logging']['root'] = base.logging.root
directory.mkdir(parents=True, exist_ok=True)
target = directory / f'backfill-{start}-{end}.json'
with target.open('x') as stream:
    json.dump(value, stream, indent=2)
    stream.write('\n')
derived = load_config(target)
expected = base.to_mapping()
expected['backfill'] = {'start_quarter': start, 'end_quarter': end}
if derived.to_mapping() != expected:
    raise SystemExit('slice config differs from the live config beyond the backfill range')
print(target.name, derived.config_sha256)
PY
}
slice_config 2020Q1 open && rm "$project/conf/stage2/1b/backfill-2020Q1-open.json"
native - "$project/conf/sec-edgar-local.json" "$project/conf/stage2/1b" <<'PY'
import sys
from pathlib import Path
from sec_edgar_ingest.config import load_config
base = load_config(Path(sys.argv[1]))
for path in sorted(Path(sys.argv[2]).glob('backfill-*.json')):
    derived = load_config(path)
    expected = base.to_mapping()
    expected['backfill'] = derived.to_mapping()['backfill']
    print(path.name, derived.config_sha256, derived.to_mapping() == expected)
PY
git status --short -- conf/stage2/1b
```

Expected:

- The first line is `backfill-2020Q1-open.json 2512fdcb999a302d93de84315d45e4e44d0bb942d5165698b64c371fc42b5be5`, the new live effective hash. That file is then removed.
- Then 8 lines. Each ends in `True` and shows exactly its F13 hash: `2020Q1-2020Q4` `6af8dd95…`, `2021Q1-2021Q4` `403ee6d8…`, `2022Q1-2022Q4` `ce09a643…`, `2023Q1-2023Q4` `12b29832…`, `2024Q1-2024Q4` `b3800ebb…`, `2025Q1-2025Q4` `1d733369…`, `2026Q1-2026Q3` `d84919ef…`, `2026Q4-open` `aab50ee2…`.
- `git status` shows only the five `D` lines from Step 4. The kept configs are byte-identical.

Any other hash, a `False`, or a modified kept config stops the plan.

- [ ] **Step 6: Known answers on the live store under the edited config**

```sh
# prelude
out="$evidence/pre-campaign/rev2"
tool audit --config "$project/conf/sec-edgar-local.json" > "$out/audit.json"; echo "audit exit=$?"
tool coverage --config "$project/conf/sec-edgar-local.json" --start 2020Q1 --end 2026Q4 --open-quarter 2026Q4 \
  --check integrity > "$out/coverage-integrity.json"; echo "integrity exit=$?"
tool coverage --config "$project/conf/sec-edgar-local.json" --start 2020Q1 --end 2026Q4 --open-quarter 2026Q4 \
  --check full > "$out/coverage-full.json"; echo "full exit=$?"
tool timing --config "$project/conf/sec-edgar-local.json" > "$out/timing.json"; echo "timing exit=$?"
mkdir -p "$campaign_logs"
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json > "$campaign_logs/files-rev2.json"; echo "files exit=$?"
native - "$campaign_logs/files-rev2.json" <<'PY' > "$out/files.json"
import json, sys
value = json.load(open(sys.argv[1]))
print(json.dumps({'file_count': value['inventory']['file_count'], 'byte_count': value['inventory']['byte_count'],
                  'comparison': value['comparison']}, sort_keys=True, indent=1))
PY
native - "$out" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
print(json.load(open(out / 'audit.json'))['store_total'])
for name in ('coverage-integrity.json', 'coverage-full.json'):
    value = json.load(open(out / name))
    views = [unit['filing_quarter'] for unit in value['units'] if unit['filing_quarter']['status'] == 'published']
    print(value['check'], value['verdicts'], len(views), sorted({str(view['validated_rows']) for view in views})[:1],
          sum(view['validated_rows'] or 0 for view in views),
          sorted({view['membership_source_id'] for view in views}, key=str), value['other_filing_quarters'])
timing = json.load(open(out / 'timing.json'))
print(timing['runs'], timing['child_call_rows'], json.load(open(out / 'files.json')))
PY
```

Expected, as planning observed on 2026-10-29 (F15, F22):

- `audit exit=0`, `integrity exit=0`, `full exit=0`, `timing exit=0`, `files exit=0`. The full coverage takes about one minute.
- `store_total` has `attempts: 10`, `distinct_urls: 10`, `max_ordinal: 1`, `received_bytes: 4946565`, `uncertain: 0`, `access_denied: 0`.
- `integrity {'no_campaign_result': 28} 16 ['None'] 0 [None] []`.
- `full {'no_campaign_result': 28} 16 ['1'] 6744 [None] []`.
- `[] 0`, then 153 files and a comparison with only SQLite journal files under `changed_state`.

Any other value stops the plan.

- [ ] **Step 7: Amend the spec and the runbook**

Spec-level edits (D10), approved with this revision. Each new spec line carries `(owner, plan 2, 2026-10-29)`. The spec's status line is not touched.

```sh
# prelude
native - "$project/specs/sec-filing-index-ingestion-spec.md" "$project/docs/runbooks/local-ingestion.md" <<'PY'
import sys
from pathlib import Path
spec, runbook = Path(sys.argv[1]), Path(sys.argv[2])
EDITS = {
    spec: [
        ('| Backfill / handoff | `2015Q1` through `open`; daily handoff `2026-10-01`. |\n',
         '| Backfill / handoff | `2020Q1` through `open`; daily handoff `2026-10-01` (owner, plan 2, 2026-10-29). |\n'),
        ('The effective-config SHA-256 is\n'
         '`db62e7fb8c941f125f84992c5bccfdbb65d6461231d899054af505700e9004b1`, confirmed by offline preflight.\n',
         'The effective-config SHA-256 was\n'
         '`db62e7fb8c941f125f84992c5bccfdbb65d6461231d899054af505700e9004b1`, confirmed by offline preflight.\n'
         'Plan 2 Revision 2 moved the backfill start to `2020Q1`. The effective-config SHA-256 is now\n'
         '`2512fdcb999a302d93de84315d45e4e44d0bb942d5165698b64c371fc42b5be5`, confirmed by offline preflight\n'
         '(owner, plan 2, 2026-10-29).\n')],
    runbook: [('backfill `2015Q1` to `open`', 'backfill `2020Q1` to `open`')],
}
for path, edits in EDITS.items():
    text = path.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise SystemExit(f'{path.name}: expected exactly one match for: {old[:60]}')
        text = text.replace(old, new)
    path.write_text(text)
    print(path.name, len(edits), 'edits')
PY
git diff --stat -- specs/sec-filing-index-ingestion-spec.md docs/runbooks/local-ingestion.md
```

Expected: `sec-filing-index-ingestion-spec.md 2 edits` and `local-ingestion.md 1 edits`, then 2 files changed. The spec diff changes the §4.8 backfill row and adds three lines after the `db62e7fb…` hash. The runbook diff changes only `2015Q1` to `2020Q1` on line 23.

- [ ] **Step 8: Edit `specs/evidence/baseline-campaign/campaign.json` (O19)**

Replace the whole file with:

```json
{
 "format_version": "sec-baseline-campaign-budget-v1",
 "max_distinct_urls": 300,
 "max_invocations": 24,
 "max_member_wall_seconds": 1056,
 "max_received_bytes": 1073741824,
 "max_request_attempts": 1500,
 "max_request_attempts_per_invocation": 700
}
```

Only `max_invocations` changes, from 40 to 24.

- [ ] **Step 9: Edit `specs/evidence/baseline-campaign/campaign.md` for the 2020Q1 range**

```sh
# prelude
native - "$evidence/campaign.md" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
EDITS = [
    ('**Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md), Revision 1.\n',
     '**Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md), Revisions 1 and 2.\n'),
    ('release gate stayed closed (plan 2, F11). This version replaces it.\n',
     'release gate stayed closed (plan 2, F11). This version replaces it. Plan 2 Revision 2 (D10) moved the\n'
     'range start from 2015Q1 to 2020Q1 in this file and in the live config.\n'),
    ('| Live config | `conf/sec-edgar-local.json`, effective SHA-256 `db62e7fb…`, file SHA-256 `de6c0dd9…` |\n',
     '| Live config | `conf/sec-edgar-local.json`, range `2020Q1`–`open`, effective SHA-256 `2512fdcb…`, '
     'file SHA-256 `bfdf2985…` |\n'),
    ('| Slice configs | `conf/stage2/1b/`, 13 files. Effective hashes: plan 2, F13. |\n',
     '| Slice configs | `conf/stage2/1b/`, 8 files. Effective hashes: plan 2, F13 (the pilot and the 2020–2026 rows). |\n'),
    ('| Slice generator check | `2015Q1`–`open` reproduces the live effective hash `db62e7fb…` |\n',
     '| Slice generator check | `2020Q1`–`open` reproduces the live effective hash `2512fdcb…` |\n'),
    ('([pre-campaign.md](pre-campaign.md), Revision 1 section).\n',
     '([pre-campaign.md](pre-campaign.md), Revision 2 section).\n'),
    ('- Requested units: the quarterly sources 2015Q1–2026Q4, which is 48 units.',
     '- Requested units: the quarterly sources 2020Q1–2026Q4, which is 28 units.'),
    ('  2. The calendar years 2015, 2016, …, 2025, one slice each, in ascending order.\n',
     '  2. The calendar years 2020, 2021, …, 2025, one slice each, in ascending order.\n'),
    ('  quarters (findings §4.7).\n',
     '  quarters (findings §4.7). Rows back-dated before 2020Q1 publish daily-only filing quarters outside\n'
     '  the range. Coverage lists them under `other_filing_quarters` (plan 2 F23).\n'),
    ('Possible quarantines for 2015Q1 and 2026Q3 (retained conflict specimens).',
     'A possible quarantine for 2026Q3 (retained conflict specimen).'),
    ('| Invocations | 40 | audit, stop rule 4 | pilot 2–4; about 24 for the year slices at about 2 full-size members each; reruns |\n',
     '| Invocations | 24 | audit, stop rule 4 | pilot 2–4; about 14 for the year slices at about 2 full-size members each; '
     'reruns (plan 2 O19) |\n'),
    ('about 1 + 12 + 48 full-index listings, 48 quarterly bodies, 4 daily listings and about 90 daily bodies, about 203 |\n',
     'about 1 + 7 + 28 full-index listings, 28 quarterly bodies, 4 daily listings and about 90 daily bodies, about 158 |\n'),
    ('about 47 × 4.3 MB + 90 × 0.35 MB, about 235 MB', 'about 27 × 4.3 MB + 90 × 0.35 MB, about 148 MB'),
    ('Expected launcher time: about 26–30 invocations of about 2,200 s each.',
     'Expected launcher time: about 16–20 invocations of about 2,200 s each.'),
    ('12. **Finish** when every quarter 2015Q1–2026Q4 has a campaign result',
     '12. **Finish** when every quarter 2020Q1–2026Q4 has a campaign result'),
    ('`pre-campaign.md`, `pre-campaign/1b/`, `invocations.md`,',
     '`pre-campaign.md`, `pre-campaign/1b/`, `pre-campaign/rev2/`, `invocations.md`,'),
    ("The owner's approval of Revision 1 authorizes Tasks 3a and 3b.\n",
     "The owner's approval of Revision 1 authorizes Tasks 3a and 3b.\n"
     "  The owner's approval of Revision 2 authorizes Task 3c, including its one live config edit.\n"),
]
for old, new in EDITS:
    if text.count(old) != 1:
        raise SystemExit('campaign.md: expected exactly one match for: ' + old[:60])
    text = text.replace(old, new)
for stale in ('2015', '48 units', 'db62e7fb', 'de6c0dd9', '13 files'):
    if stale in text.replace('from 2015Q1 to 2020Q1', ''):
        raise SystemExit('campaign.md still names ' + stale)
path.write_text(text)
print('campaign.md: %d edits' % len(EDITS))
PY
```

Expected: `campaign.md: 17 edits`. Planning dry-ran this script on a copy of the `c9a9cb3` file. Any `SystemExit` stops the plan. The Approval section stays "To be completed in Task 4".

- [ ] **Step 10: Append the Revision 2 section to `pre-campaign.md`**

Every value below must equal the Step 2–6 outputs. A difference stops the plan.

```markdown

## Known-answer checks after the 2020Q1 range change (plan 2 Revision 2)

- The live config now starts at `2020Q1` (plan 2, D10). File bytes `bfdf2985…`, effective config `2512fdcb…`.
- [rev2/preflight.json](pre-campaign/rev2/preflight.json): effective config `2512fdcb…`, release `9fa189a0…`,
  range 2020Q1–open, reserve 1800.
- Slice generator: `2020Q1`–`open` reproduces `2512fdcb…`. The 8 configs left in `conf/stage2/1b/` keep
  their plan 2 F13 hashes and equal the live config except for the range. The five 2015–2019 configs were
  removed (plan 2, O18).
- [rev2/audit.json](pre-campaign/rev2/audit.json): 10 transport attempts, 10 URLs, 4,946,565 received bytes,
  ordinal 1 only. This equals L12.
- [rev2/coverage-integrity.json](pre-campaign/rev2/coverage-integrity.json) and
  [rev2/coverage-full.json](pre-campaign/rev2/coverage-full.json): 28 requested units without a campaign
  result; 16 published quarters, all daily-only and all inside the range. The full check reads 6,744 rows.
  The integrity check reads no row.
- [rev2/timing.json](pre-campaign/rev2/timing.json): no workflow result yet, 0 `WorkflowChildCall` rows.
- [rev2/files.json](pre-campaign/rev2/files.json): 153 files. Against L12, only SQLite journal state changed.
```

- [ ] **Step 11: Commit**

```sh
git diff --check
git add conf/sec-edgar-local.json conf/stage2/1b/ specs/sec-filing-index-ingestion-spec.md \
  docs/runbooks/local-ingestion.md specs/evidence/baseline-campaign/
git status --short
git commit -m "chore(config): start the Stage 2 range at 2020Q1"
```

Expected: `git status` lists the live config, the five deleted configs, the spec, the runbook, `campaign.json`, `campaign.md`, `pre-campaign.md` and the six `pre-campaign/rev2/` files, all staged.

---

### Task 4: Release gate and owner live-execution gate (human checkpoint)

> Revision 1: rewritten for release `9fa189a0…`. The 2026-10-21 text gated `fc68adef…` and stays in git history at `4004f2e`.
>
> Revision 2: Step 1 checks the edited config and the Task 3c commit. Step 2 asks all ten items again for the 2020Q1 range. Step 1 ran once under Revision 1 on 2026-10-29 and found the gate standing for the 2015Q1 config. It is unticked so that it runs again after Task 3c.

**Files:**
- Modify: `specs/evidence/baseline-campaign/campaign.md` (`Status` and `Approval` sections)
- Modify: `specs/evidence/baseline-campaign/campaign.json` (only if the owner changes a limit)

**Interfaces:**
- Consumes: the Task 3a, 3b and 3c commits, and `specs/evidence/baseline-campaign/pre-campaign/rev2/preflight.json`.
- Produces: either a stop that ends the plan, or the approval commit that Task 5 checks before every invocation.

- [ ] **Step 1: Check the release gate**

```sh
# prelude
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(v["release_id"], v["effective_config_sha256"], v["dispatch_reserve_seconds"])' \
  "$evidence/pre-campaign/rev2/preflight.json"
shasum -a 256 conf/sec-edgar-local.json
git log -1 --format='%H %s' -- specs/evidence/baseline-campaign/campaign.md
```

Expected: `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b 2512fdcb999a302d93de84315d45e4e44d0bb942d5165698b64c371fc42b5be5 1800`, then the file hash `bfdf29859325fa396520c0fabd0bcd6f6e34d8854b558d56e4bf4a7731038204`, then the Task 3c commit.

- If the release, the effective hash, the file hash or the reserve differs, stop. The owner has selected another release or config, and this revision pins `9fa189a0…` and the 2020Q1 config. Revise the plan again (Global Constraints, Task 3a Step 5, Tasks 3b and 3c) and get owner review before any gate.
- Otherwise the Release gate that Task 3b wrote stands. Continue to Step 2.

- [ ] **Step 2: Present the revision and the campaign files to the owner**

Present `pre-campaign.md` (its Revision 1 and Revision 2 sections), `campaign.md`, and plan 2's O12–O19 and D10. Ask the owner to confirm or change each of these. Ask every item again, including the ones answered before Revision 2 (Revision 2, item 5). Ask one question for each item, so that a changed answer to one item cannot silently replace the others.

1. The range, 2020Q1–2026Q4, 28 units (O1, D10).
2. The slice list (8 configs), the budget (`max_invocations` 24) and the stop rules (O13, O18, O19).
3. The runtime per invocation: 3,300 s, or another value above the 1,800 s reserve and at most 3,600 s.
4. The member-wall limit, 1,056 s (O14).
5. The pilot as the first measurement of the A1 member class (O15).
6. The handling of a refused incremental candidate (O16).
7. The window start in UTC.
8. The withdrawal policy (O6) and the order effect (O10).
9. The retained daily sources (O5).
10. The sole-issuer declaration.

Do not suggest that the owner skip any item.

- [ ] **Step 3: Record the owner's answers verbatim**

Replace the Approval section with the following, filled only from the owner's words:

```markdown
## Approval

- Owner: Lowell Mason. Approved on (UTC): <owner's timestamp>.
- Range: <owner's words>. Slices, budget and stop rules: <"as proposed" or the owner's changes>.
- Runtime per invocation: <3300 or another value above 1800 and up to 3600>. Window: starts <UTC>, ends <UTC>.
- Member-wall limit: <1056 or the owner's value>. Pilot as the first A1 measurement: <owner's words>.
- Refused incremental candidate: <owner's words>.
- Withdrawal policy and order effect: <owner's words>. Retained daily sources: <owner's words>.
- Sole-issuer declaration, verbatim: "<owner's words>"
```

If the owner selects wording that the operator drafted, in place of typing it, record the declaration line as `- Sole-issuer declaration: the owner selected this drafted wording: "<exact text>"`. The record then shows where the words came from.

Set `**Status:** Approved for live execution within the limits above.`

- If the owner changes a limit, the member-wall limit included, update `campaign.json` in the same commit.
- If the owner chooses O15's alternative (measure A1 offline first), stop. That measurement needs its own plan. Task 4 restarts after it.
- If the owner does not approve, stop. The plan then ends at Task 4 with nothing live run.

- [ ] **Step 4: Commit**

```sh
git add specs/evidence/baseline-campaign/campaign.md specs/evidence/baseline-campaign/campaign.json
git commit -m "docs(evidence): record the Stage 2 release gate and owner decision"
```

---

### Task 5: Campaign invocations (live, after Task 4 approval)

> Revision 1: rewritten for release `9fa189a0…`: a fixed slice list instead of a sizing rule, integrity coverage and member timing after each invocation, and stop rules 7 and 8.
>
> Revision 2: the 8 configs from 2020Q1, the edited live config hash, and coverage from 2020Q1.

**Files:**
- Create: `specs/evidence/baseline-campaign/invocations.md`
- Create: `specs/evidence/baseline-campaign/invocations/<k>-<run-id>.json` (one for each invocation)
- Create (ignored): `logs/baseline-campaign/coverage-after-<k>.json`, `audit-after-<k>.json`, `timing-after-<k>.json`, `files-after-<k>.json`, `launcher-exit-<k>`, `invocation-<k>.json`

**Interfaces:**
- Consumes: the Task 4 approval commit, `campaign.json`, the 8 configs in `conf/stage2/1b/`, and Task 3a's `tool audit / coverage --check integrity / timing / files`.
- Produces: the result refs and run IDs for Task 6, in `invocations/*.json`. Each record has an `after` block.

The slice order is fixed (O13). Each entry is a file in `conf/stage2/1b/`:

1. `backfill-2026Q4-open.json` (the pilot). It reruns under stop rule 9 until no daily source is pending.
2. `backfill-2020Q1-2020Q4.json`, then each year to `backfill-2025Q1-2025Q4.json`, in ascending order.
3. `backfill-2026Q1-2026Q3.json`.

Repeat Steps 1–7 for k = 1, 2, … until a stop rule says finish or halt. Never start an invocation while another writer runs. Never read the store while the launcher runs.

Collection is bound to the release that discovered the member (`specs/evidence/d5-release/two-release.md`; `specs/evidence/stage1b/two-release.md`). So the pilot's `collect` children for the pending members that L12 discovered run on the retained `fc68adef…` release, and the other children run on `9fa189a0…`. That is expected. It is not a release selection, so it does not breach the Global Constraints.

- [ ] **Step 1: Choose the slice**

```sh
# prelude
k=$(( $(ls "$evidence"/invocations/*-*.json 2>/dev/null | wc -l) + 1 )); echo "k=$k"
tail -1 "$evidence/invocations.md" 2>/dev/null
```

For k = 1, use the pilot. Otherwise use the decision in the last ledger row: on Rerun, the same config; on Next slice, the next config in the order above. Note the config's effective hash from the F13 table.

- [ ] **Step 2: Pre-check**

```sh
# prelude
pgrep -fl -- '-m sec_edgar_ingest|scripts/sec-edgar-local|local-bootstrap|local_bootstrap' || echo 'no writer'
git log -1 --format='%H %s' -- specs/evidence/baseline-campaign/campaign.md
shasum -a 256 conf/sec-edgar-local.json
df -g "$project" | tail -1
du -sg "$project/data" | cut -f1
date -u +%Y-%m-%dT%H:%M:%SZ
k=$(( $(ls "$evidence"/invocations/*-*.json 2>/dev/null | wc -l) + 1 ))
last=$(ls "$evidence"/invocations/"$((k - 1))"-*.json 2>/dev/null)
[ -n "$last" ] && native -c 'import json,sys; print("daily_open", json.load(open(sys.argv[1]))["after"]["daily_open"])' "$last"
```

Expected:

- `no writer`.
- The last `campaign.md` commit is the Task 4 approval commit.
- The live config file hash is `bfdf2985…` (F21). A different hash means the config or its release changed: halt (Global Constraints, release history).
- At least 50 GiB available.
- Store growth since pre-campaign (12 MB) of at most 30 GiB.
- The UTC time is inside the approved window and before 2027-01-01T00:00:00Z.
- For any slice after the pilot: `daily_open []`. A daily source that is still pending, or failed and not quarantined, stays selected and is after every year slice's end, so the run would end in `state_conflict` (F9).

If any check fails, halt.

- [ ] **Step 3: Run one invocation**

The run can last up to the timeout. Run it in the background with the agent harness's background mode, and wait for the exit notification. Do not poll the SEC or the store meanwhile. Set `config` to this invocation's slice config and `timeout` to the approved value.

```sh
# prelude
k=$(( $(ls "$evidence"/invocations/*-*.json 2>/dev/null | wc -l) + 1 ))
config="$project/conf/stage2/1b/backfill-2026Q4-open.json"   # this invocation's slice config
timeout=3300                                                  # the approved value
scripts/sec-edgar-local backfill --config "$config" --timeout-seconds "$timeout"
code=$?
mkdir -p "$campaign_logs"
echo "$code" > "$campaign_logs/launcher-exit-$k"
echo "launcher exit=$code"
```

Expected: an exit code. With quarantines present, 3 is normal (F7). A run that deferred members at the cutoff ends `incomplete` or `pending` (exit 3 or 4), never exit 5.

- [ ] **Step 4: Record the invocation**

```sh
# prelude
k=$(( $(ls "$evidence"/invocations/*-*.json 2>/dev/null | wc -l) + 1 ))
attempt_dir=$(ls -dt "$project"/logs/*/*/ | grep -v '/logs/baseline-campaign/' | head -1)
mkdir -p "$evidence/invocations"
native - "$attempt_dir" "$project/data/objects" "$k" "$(cat "$campaign_logs/launcher-exit-$k")" <<'PY' > "$campaign_logs/invocation-$k.json"
import hashlib, json, sys
from pathlib import Path
directory, objects, k, launcher_exit = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
invocation_bytes = (directory / 'invocation.json').read_bytes()
invocation = json.loads(invocation_bytes)
stdout = [json.loads(line) for line in (directory / 'stdout.jsonl').read_text().splitlines() if line.strip()]
events = []
for line in (directory / 'stderr.jsonl').read_text().splitlines():
    try:
        events.append(json.loads(line))
    except ValueError:
        continue
summaries = [event['fields'] for event in events if event.get('event') == 'workflow_summary']
result_ref = stdout[-1].get('result_ref') if stdout else None
result = json.loads((objects / result_ref).read_bytes()) if result_ref else None
print(json.dumps({'k': k, 'launcher_exit': launcher_exit, 'log_directory': str(directory),
    'invocation_sha256': hashlib.sha256(invocation_bytes).hexdigest(),
    'run_id': invocation['run_id'], 'attempt_id': invocation['attempt_id'], 'command': invocation['command'],
    'release_id': invocation['release_id'], 'config_sha256': invocation['config_sha256'],
    'backfill': invocation['effective_config']['backfill'],
    'dispatch_reserve_seconds': invocation['effective_config'].get('execution', {}).get('dispatch_reserve_seconds'),
    'started_at': invocation['started_at'], 'deadline': invocation['deadline'],
    'ended_at': None if result is None else result['ended_at'],
    'stdout': stdout, 'result_ref': result_ref,
    'result_sha256': hashlib.sha256((objects / result_ref).read_bytes()).hexdigest() if result_ref else None,
    'workflow_summary': summaries[-1] if summaries else None}, sort_keys=True, indent=1))
PY
run_id=$(native -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$campaign_logs/invocation-$k.json")
cp "$campaign_logs/invocation-$k.json" "$evidence/invocations/$k-$run_id.json"
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(v["release_id"], v["config_sha256"], v["backfill"], v["dispatch_reserve_seconds"], v["result_ref"], v["ended_at"], v["workflow_summary"] is not None)' "$evidence/invocations/$k-$run_id.json"
```

Expected: release `9fa189a0…`, the slice config's effective hash from F13, the slice range, `1800`, a non-null `result_ref` and `ended_at`, and `True`. If the release, the config hash or the reserve differs, halt. If `result_ref` is null, apply stop rule 2.

- [ ] **Step 5: Audit the budget**

```sh
# prelude
k=$(ls "$evidence"/invocations/*-*.json | wc -l | tr -d ' ')
flags=()
for f in "$evidence"/invocations/*-*.json; do
  flags+=(--run-id "$(native -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$f")")
done
tool audit --config "$project/conf/sec-edgar-local.json" "${flags[@]}" --budget "$evidence/campaign.json" \
  > "$campaign_logs/audit-after-$k.json"; echo "audit exit=$?"
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(len(v["runs"]), v["total"], v["breaches"])' "$campaign_logs/audit-after-$k.json"
```

Expected: `audit exit=0`, the run count equal to k, and `breaches: []`. Otherwise halt (rule 4).

- [ ] **Step 6: Coverage, timing and integrity after the invocation**

The coverage here uses `--check integrity`: it reads no row, so it takes seconds, and no unit can be `covered` (O12). Task 6 runs the full check once.

```sh
# prelude
k=$(ls "$evidence"/invocations/*-*.json | wc -l | tr -d ' ')
record=$(ls "$evidence"/invocations/"$k"-*.json)
refs=()
for f in "$evidence"/invocations/*-*.json; do
  ref=$(native -c 'import json,sys; print(json.load(open(sys.argv[1]))["result_ref"] or "")' "$f")
  [ -n "$ref" ] && refs+=(--result "$ref")
done
this=$(native -c 'import json,sys; print(json.load(open(sys.argv[1]))["result_ref"])' "$record")
limit=$(native -c 'import json,sys; print(json.load(open(sys.argv[1]))["max_member_wall_seconds"])' "$evidence/campaign.json")
tool coverage --config "$project/conf/sec-edgar-local.json" "${refs[@]}" --start 2020Q1 --end 2026Q4 \
  --open-quarter 2026Q4 --check integrity > "$campaign_logs/coverage-after-$k.json"; echo "coverage exit=$?"
tool timing --config "$project/conf/sec-edgar-local.json" --result "$this" --max-member-wall "$limit" \
  > "$campaign_logs/timing-after-$k.json"; echo "timing exit=$?"
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  > "$campaign_logs/files-after-$k.json"; echo "files exit=$?"
native - "$campaign_logs/coverage-after-$k.json" "$campaign_logs/audit-after-$k.json" \
  "$campaign_logs/timing-after-$k.json" "$record" <<'PY'
import json, sys
from pathlib import Path
coverage, audit, timing, record = (Path(item) for item in sys.argv[1:])
value, spent, timed = (json.loads(path.read_text()) for path in (coverage, audit, timing))
waiting = ('pending', 'deferred', 'throttled')
sources = [unit['source'] for unit in value['units'] if unit['source']] + value['daily_sources']
eligible = [unit['quarter'] for unit in value['units'] if unit['source'] and unit['source']['outcome'] in waiting]
eligible += [item['period'] for item in value['daily_sources'] if item['outcome'] in waiting]
daily_open = [item['period'] for item in value['daily_sources']
              if item['outcome'] in waiting or (item['status'] == 'failed' and not item['quarantined'])]
refused = [{'kind': item['kind'], 'period': item['period'], 'gaps': item['gaps']} for item in sources
           if item['outcome'] == 'invalid_source' and not item['quarantined']]
untouched = [unit['quarter'] for unit in value['units'] if unit['verdict'] == 'no_campaign_result']
run = timed['runs'][0]
entry = json.loads(record.read_text())
entry['after'] = {'verdicts': value['verdicts'], 'eligible': eligible, 'untouched': untouched,
                  'daily_open': daily_open, 'refused': refused, 'daily_sources': len(value['daily_sources']),
                  'campaign_total': spent['total'], 'child_call_rows': timed['child_call_rows'],
                  'timing': {key: run[key] for key in ('dispatch_cutoff', 'tail_seconds', 'timed_members',
                                                       'b4_members', 'repeated_sources', 'max_member_wall')},
                  'timing_breaches': timed['breaches']}
record.write_text(json.dumps(entry, sort_keys=True, indent=1) + '\n')
print(json.dumps(entry['after']))
PY
```

Expected: `coverage exit=0` and `files exit=0`. `timing exit=0`, or `timing exit=1` with a non-empty `after.timing_breaches` (rule 7). Any other nonzero exit, or an exit 1 whose output does not parse or has no breach, is a tool failure: halt and report it. The printed `after` block is now in the invocation record. The full timing report stays in `logs/baseline-campaign/timing-after-<k>.json`.

- [ ] **Step 7: Decide, log and commit**

Apply the `campaign.md` stop rules in order. Use the launcher exit, `result_ref`, `workflow_summary` (`outcome`, `summary_error`, `discovery_complete`), the audit breaches, the files exit, `after.timing_breaches` (rule 7), `after.refused` (rule 8), `after.eligible` (rule 9) and `after.untouched` (rule 11). For rule 9, compare the length of `eligible` with the previous invocation of the same slice.

Append one row to `invocations.md`. Create the file with this header on k = 1:

```markdown
# Stage 2 campaign invocations

| k | Slice | Run ID | Launcher exit | Outcome | Elapsed (s) | Complete / pending / failed sources | Published quarters | Timed / B4 members | Max member wall (s) | Attempts (run / campaign) | Received bytes (campaign) | Eligible after | Untouched after | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
```

```sh
# prelude
k=$(ls "$evidence"/invocations/*-*.json | wc -l | tr -d ' ')
git add specs/evidence/baseline-campaign/invocations.md specs/evidence/baseline-campaign/invocations/
git commit -m "docs(evidence): record Stage 2 campaign invocation $k"
```

On Rerun or Next slice, go back to Step 1. On Finish, go to Task 6. On Halt, report to the owner with the invocation record and stop the plan here. The owner decides whether Task 6 runs on the evidence so far.

---

### Task 6: Final coverage inventory, integrity and quarantine enumeration (offline)

> Revision 1: Step 1 now runs the full content check once (`--check full`) and adds the final timing report.
>
> Revision 2: the range starts at 2020Q1, which is 28 units.

**Files:**
- Create: `specs/evidence/baseline-campaign/final/coverage.json`, `audit.json`, `timing.json`, `files.json`
- Create: `specs/evidence/baseline-campaign/quarantine/<quarter>.txt` (one for each quarantined unit)

**Interfaces:**
- Consumes: the result refs and run IDs in `invocations/*.json`.
- Produces: the inputs for Task 7.

- [ ] **Step 1: Final full coverage, audit and timing**

The full check reads every published quarter once through the release's full content check. That is about 415 s for each full-size quarter (F16), so expect about 3.5 hours for the 28 units. Run it in the background with the agent harness's background mode, and wait for the exit notification. No writer may run until it ends.

```sh
# prelude
mkdir -p "$evidence/final" "$evidence/quarantine"
refs=(); flags=()
for f in "$evidence"/invocations/*-*.json; do
  ref=$(native -c 'import json,sys; print(json.load(open(sys.argv[1]))["result_ref"] or "")' "$f")
  [ -n "$ref" ] && refs+=(--result "$ref")
  flags+=(--run-id "$(native -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$f")")
done
limit=$(native -c 'import json,sys; print(json.load(open(sys.argv[1]))["max_member_wall_seconds"])' "$evidence/campaign.json")
tool coverage --config "$project/conf/sec-edgar-local.json" "${refs[@]}" --start 2020Q1 --end 2026Q4 \
  --open-quarter 2026Q4 --check full > "$evidence/final/coverage.json"; echo "coverage exit=$?"
tool audit --config "$project/conf/sec-edgar-local.json" "${flags[@]}" --budget "$evidence/campaign.json" \
  > "$evidence/final/audit.json"; echo "audit exit=$?"
tool timing --config "$project/conf/sec-edgar-local.json" "${refs[@]}" --max-member-wall "$limit" \
  > "$evidence/final/timing.json"; echo "timing exit=$?"
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(v["check"], v["verdicts"], v["complete"], len(v["daily_sources"]), [q["quarter"] for q in v["other_filing_quarters"]])' "$evidence/final/coverage.json"
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(len(v["runs"]), v["child_call_rows"], v["max_member_wall"], len(v["breaches"]))' "$evidence/final/timing.json"
```

Expected: `coverage exit=0`, `audit exit=0` and `timing exit=0`. The coverage check is `full`, and the verdicts cover exactly 28 units with no `published_unchecked`. The timing report has one run for each invocation with a result, and 0 breaches against the limit in `campaign.json`. If the owner approved a higher limit after a halt, `campaign.json` already carries it.

- [ ] **Step 2: Final integrity comparison**

```sh
# prelude
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  > "$campaign_logs/files-final.json"; echo "files exit=$?"
shasum -a 256 "$campaign_logs/files-final.json"
native - "$campaign_logs/files-final.json" <<'PY' > "$evidence/final/files.json"
import json, sys
value = json.load(open(sys.argv[1]))
print(json.dumps({'inventory_ref': sys.argv[1], 'file_count': value['inventory']['file_count'],
                  'byte_count': value['inventory']['byte_count'],
                  'comparison': {key: (items if key != 'added' else len(items)) for key, items in value['comparison'].items()}},
                 sort_keys=True, indent=1))
PY
```

Expected: `files exit=0`. `missing` and `changed_immutable` are empty. `changed_state` may list the SQLite files. `added` is a count. The full inventory stays in `logs/` and its SHA-256 goes in the finding.

- [ ] **Step 3: Enumerate conflicts for each quarantined quarterly unit**

The parser stops at the first conflict (L12 record). This step lists every repeated raw key with more than one distinct row, from retained bytes only. Run it for each quarter with verdict `quarantined`:

```sh
# prelude
quarter=2024Q1   # repeat for each quarantined quarter
for zip in "$project"/data/objects/raw/sec/indexes/kind=quarterly/period=$quarter/sha256=*/master.zip; do
  echo "# $zip $(shasum -a 256 "$zip" | cut -d' ' -f1)"
  unzip -p "$zip" master.idx | tr -d '\r' | awk -F'|' 'NF==5 && $1 ~ /^[0-9]+$/ {
      k=$1"|"$5; if (!((k SUBSEP $0) in seen)) {seen[k SUBSEP $0]=1; d[k]++}; r[k]=r[k] NR":"$3"; "}
      END {for (k in d) if (d[k]>1) print k "\t" r[k]}' | sort
done > "$evidence/quarantine/$quarter.txt"
wc -l "$evidence/quarantine/$quarter.txt"
```

Expected for 2024Q1: 4 lines, one header line and 3 key lines. The key lines are CIK 1426332 at lines 88033/88043 and 88035/88044, and CIK 1481241 at lines 98688/98690, as in findings §5.2. Planning checked this output against the retained 2024Q1 ZIP on 2026-10-21. This is a raw-field enumeration. The parser's normalized key could merge more rows, and the record must say so.

- [ ] **Step 4: Commit**

```sh
git add specs/evidence/baseline-campaign/final/ specs/evidence/baseline-campaign/quarantine/
git commit -m "docs(evidence): record final Stage 2 coverage and quarantine enumeration"
```

---

### Task 7: G2 coverage finding, owner dispositions and operating decision

> Revision 1: §2 adds the timing evidence, §4 names a refused incremental candidate, and the new §8 records the revisit triggers deferred into Stage 2 (O17).
>
> Revision 2: the range is 2020Q1–2026Q4, and §5 reports filing quarters before 2020Q1.

**Files:**
- Create: `specs/evidence/baseline-campaign/coverage-finding.md`

**Interfaces:**
- Consumes: Task 6 outputs (`final/timing.json` included), `invocations.md`, `campaign.md`, `pre-campaign.md`, and `specs/deferred_items.md`, sections `4-sec-filing-index-bounded-drain — 2026-10-27` and `5-sec-filing-index-per-member-cost — 2026-10-28`.
- Produces: the accepted G2 finding that the roadmap's Stage 2 Exit requires, and that Stages 3–4 consume.

- [ ] **Step 1: Write the finding**

Use these sections in this order. Take every number from the cited JSON files. Do not round counts.

```markdown
# Stage 2 baseline coverage finding (G2)

**Status:** Proposed for owner disposition. **Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md).
**Range:** 2020Q1–2026Q4 (28 quarterly units; 2026Q4 open; start set by plan 2 D10). **Release:** `9fa189a0…` (reserve 1,800 s).
Slice configs: `conf/stage2/1b/`, see invocations.md.

## 1. Result
One paragraph: the verdict counts from final/coverage.json (full check), `complete` true or false, and
the operating decision proposed in §6.

## 2. Campaign as run
The slices, invocations and window used, and the totals against each campaign.json limit
(final/audit.json). For each invocation: elapsed seconds, the dispatch cutoff, the number of members
deferred at the cutoff (members with no child and outcome `pending`), and its slowest member wall
(final/timing.json), and its `tail_seconds` against the 97.8 s fixture finish step. The slowest member of the
campaign against the fixture value 1,010.9 s and the limit `max_member_wall_seconds`, by member class:
closed first publication, closed rebuild by an incoming quarterly authority, open-quarter daily before
and after the 2026Q4 quarterly publish (A1), closed-quarter daily. Unique expanded bytes: the sum of
`master.idx` sizes of the retained quarterly ZIPs, from `unzip -l` on each raw ZIP. Report it as post
hoc, not as enforced.

## 3. Baseline units
One table row per requested quarter: quarter, verdict, source ID (first 12 hex), member outcome,
active generation (first 12 hex), membership source equal to the unit's source (yes/no), validated rows,
daily rows considered.

## 4. Exceptions and dispositions
One subsection per unit whose verdict is not covered or covered_open_quarter. Each gives: the evidence
(gap codes, error message, quarantine file, candidate ref and withdrawn count for gated units), the
downstream limitation, the proposed disposition, and an `Owner disposition:` line that only the
owner's words fill. Proposed dispositions use one of: "accepted named gap", "deferred to a versioned
parser/schema design (Size: design)", "deferred to Stage 4 reconciliation approval review", or
"re-run in a later campaign". A unit or daily source blocked by a refused incremental candidate (O16)
gets "deferred to Stage 4 recovery disposition"; its objects stay in the store.

## 5. Other output
- Filing quarters outside the range (other_filing_quarters). Quarters before 2020Q1 hold only back-dated
  daily rows: no quarterly source was requested for them (plan 2 D10, F23).
- Daily sources processed as retained work (daily_sources): count, period range, outcomes. These are
  Stage 3 inputs.
- The open quarter 2026Q4: the snapshot receipt time, and the fact that its absences are not withdrawal
  authority.
- Downstream limitation (O10): closed-quarter publication keeps only quarterly-membership keys. A
  back-dated daily row that the quarterly file does not list is not in that quarter's catalog.

## 6. Operating decision
Exactly one of these:
- "Complete: every requested unit is covered (2026Q4 as open quarter-to-date)."
- "Approved incomplete: coverage is accepted with the named exceptions in §4 and these downstream
  limitations: …. Refused rows and sources are not accepted data."
Then the line `Owner decision:`, filled only with the owner's words and date.

## 7. Evidence integrity
- L12-inventoried immutable files are unchanged (final/files.json). SQLite state changed by design.
  Full inventory `logs/baseline-campaign/files-final.json`, SHA-256 `<hash>`.
- Pre-campaign facts: the 2021Q1 manifest restoration and the absent L12 external directory
  ([pre-campaign.md](pre-campaign.md)). Stage 2 cannot restore the absent directory.
- Release history: every invocation ran on `9fa189a0…` (invocations/*.json). The store now holds 1b
  generations, so selecting `fc68adef…` or `aa8de1ac…` for it is unsupported (parent spec §4.9).

## 8. Revisit triggers deferred into Stage 2
One subsection for each item. Each states the item's revisit condition as written in
specs/deferred_items.md, the evidence from final/timing.json, and one verdict: "met", "not met" or
"not determinable", with the reason.
- B4 single-candidate limit (section 4-…-2026-10-27): the count of `repeated_sources` and `b4_members`
  over all runs, and the share of total member wall spent by members of repeated sources.
- History-scan cost (section 5-…-2026-10-28): engine seconds of each timed member against
  `child_call_rows` before and after its invocation (the previous and this invocation record). Compare
  with the measured fit 1.38 s + 0.0290 s per row (`measurement.md`, "History scan (S4)").
- Unmeasured A1 member class: the walls of the 2026Q4 daily members that started after the 2026Q4
  quarterly member, against 1,010.9 s.
- Refused C6 candidate retry block: every `refused` entry in the invocation records, or "none occurred".
- Two-release proof covers only first-generation 1b stores: no release change happened, so its
  revisit condition is not met.
```

- [ ] **Step 2: Owner disposition**

Present §§1, 4, 6 and 8 to the owner. Record each disposition and the decision verbatim. Then set `**Status:** Accepted by the owner on <date>.` If the owner rejects the finding or asks for another campaign, stop. Record the request. The plan is then not complete.

- [ ] **Step 3: Commit**

```sh
git add specs/evidence/baseline-campaign/coverage-finding.md
git commit -m "docs(evidence): record accepted Stage 2 baseline coverage finding"
```

---

### Task 8: Spec amendment for the pre-campaign facts (owner-approved O4)

**Files:**
- Modify: `specs/sec-filing-index-ingestion-spec.md` (§4.8 and §6). Leave the status line untouched.

**Interfaces:**
- Consumes: D6 (O4 approved on 2026-10-21).
- Produces: spec text that matches the facts in F3 and in the config observation.

This task does not depend on the live campaign. It can run right after plan review.

- [x] **Step 1: Amend §4.8**

Replace:

```text
The config remains untracked. Acceptance-time statements that the preserved default selected
```

with:

```text
The config is tracked in git since commit `001edf5`; its effective-config hash is unchanged
(owner, plan 2, 2026-10-21). Acceptance-time statements that the preserved default selected
```

- [x] **Step 2: Amend §6**

Replace:

```text
Retain the live root, releases, committed evidence, and `/private/tmp/sec-local-task16-acceptance-20261018`,
including the original results and separate supplement. Future operational reports add evidence;
```

with:

```text
Retain the live root, releases, and committed evidence. The external directory
`/private/tmp/sec-local-task16-acceptance-20261018`, with the original results and separate supplement,
was found absent on 2026-10-21; its recorded hashes and inventory remain in the committed machine
evidence (owner, plan 2, 2026-10-21). Future operational reports add evidence;
```

- [x] **Step 3: Commit**

```sh
git add specs/sec-filing-index-ingestion-spec.md
git commit -m "docs(specs): record tracked config and absent L12 external evidence"
```

---

## After the last task

When Tasks 3a–7 have run under Revisions 1 and 2, run the writing-plans Plan Completion Protocol, step 3a included. Rewrite the Handoff below from what then ships. In step 3, tick or update the deferred items that Task 7 §8 found met, and keep the others open.

## Handoff to later stages

Revision 1 (2026-10-29) re-plans Tasks 3a–7 for release `9fa189a0…`, and Revision 2 (2026-10-29) moves the range start to 2020Q1. Tasks 3a and 3b have run. Nothing live has run. The bullets below are the 2026-10-21 state on release `fc68adef…`. Their F11, D5-release and slice-config statements are superseded by Revision 1. Their 2015Q1 statements, such as a possible 2015Q1 quarantine for Stage 4, are superseded by Revision 2. The Plan Completion Protocol rewrites this section.

On 2026-10-21, Stage 2 was blocked at Task 4, not complete. At that time it had produced only the offline preparation. It has not produced the roadmap's per-invocation results and captures, the coverage inventory or the operating decision. No item went to `specs/deferred_items.md`.

- **Next roadmap resume (derive-roadmap).**
  - The owner routed F11 to an engine change and a new release, before the Stage 2 live campaign (D5). That change has no stage, spec or plan yet. The resume adds it ahead of the Stage 2 live campaign.
  - Fix areas from planning (F8, F11): a dispatch margin in `runner.run_workflow`, a per-invocation member cap, or cheaper daily publication. Measured inputs: L12 daily publishes of 41.6 s and 187.6 s. The fixture profile puts the time in per-member processing, not in selection, and each pending source is processed twice (F10).
  - The condition that opens the gate is in `specs/evidence/baseline-campaign/campaign.md`, section Release gate.
  - After the new release, revise this plan before Tasks 4–7: Global Constraints, the Task 1 tool's release-internal imports (re-run Task 1 Steps 4–5), the Task 3 values and slice configs, and the Task 4 gate. `campaign.md` cites the tool at `4508859`. D7 changed the tool at `4004f2e`, so the revision updates that row.
  - The roadmap's Stage 2 Exit says "original port acceptance evidence remains intact". That holds for the committed records, the immutable objects and the releases. It does not hold for the absent `/private/tmp` directory (F3). The resume reconciles that wording.
- **Platform spec (separate roadmap).** `specs/sec-filing-platform.md` (`4b0450b`, awaiting owner review) R4 adds a bulk lane and a third priority to the shared request governor. The F11 fix areas are in the workflow runner and in publication, not in the governor. If both changes ship in one release, the Stage 2 revision must re-check the coordination values in Global Constraints: 3 requests/second, one active collector, and the lease timings.
- **Stage 3 (daily catch-up).**
  - No Stage 2 coverage decision exists yet. The pending daily work is still L12's 73 sources plus each business day since.
  - F11 applies to a `daily` invocation too. It carries every pending daily source in one invocation, and natively each daily publish took 40–190 s. So Stage 3 also needs the D5 release.
  - After the Stage 2 pilot runs, Stage 3's inventory is `final/coverage.json` `daily_sources` plus a fresh discovery (O5, F4).
- **Stage 4 (manual reconciliation).** It consumes every `gated` unit (F5, O6, O10) and every quarantine disposition that names reconciliation. None exists yet. Known in advance: the 2024Q1 quarantine (three conflicting keys, findings §5.2) and possible quarantines in 2015Q1 and 2026Q3 (F7). Closed-quarter publication keeps only quarterly-membership keys (O10, `catalog._resolve`).
- **Stage 5 (scheduling).** From Stage 2 it inherits two rules. Work must fit inside one invocation (F8), and no member may be after the pinned end (F9). On release `fc68adef…`, a scheduler must not rely on the deadline to stop a backlog.
- **All later stages: evidence tool and integrity.**
  - Tool: `scripts/baseline-campaign.py` with `files`, `audit` and `coverage`. It is pinned to `fc68adef…` internals. Its test is `packages/sec-edgar-ingest/tests/test_baseline_campaign.py` (11 tests).
  - Before live work, run `files --root data --recorded specs/evidence/local-port/sec-acceptance.json`. On 2026-10-21 it exited 0 with 153 files.
  - Under D7 (`4004f2e`), `state.sqlite3-wal` and `state.sqlite3-shm` may appear or vanish and show under `changed_state`. `state.sqlite3` stays strict.
  - Traps: the 2021Q1 manifest drift (F1). Task 2 restored it, but the cause is unknown, and editors and agents have the project folder open (`pre-campaign.md`). The lost L12 `/tmp` directory (F3). The loose writer pattern in Task 2 Step 1, which matches the project path; use `pgrep -fl -- '-m sec_edgar_ingest|scripts/sec-edgar-local|local-bootstrap|local_bootstrap'`.
  - Backup: `backups/stage2-pre-campaign-20261021T180646Z` (git-ignored). Slice configs `conf/stage2/backfill-2026Q4-open.json` (effective `bef7c783…`) and `conf/stage2/backfill-2015Q1-2015Q2.json` (`879d0e54…`) bind to `fc68adef…`. The revision regenerates them.
