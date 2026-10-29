# Member-completion conflict fix and the 1c release — Stage 1c Design Spec

**Status: DRAFT (2026-10-29)**, awaiting owner review.
**Project:** `/Users/lowell/Projects/sec-edgar-local`.
**Parent spec:** [SEC filing-index ingestion](sec-filing-index-ingestion-spec.md) (§§3 R5, R6, R9, R12; 4.6–4.9; 5–6; 9).
**Roadmap:** [ingestion roadmap](sec-filing-index-ingestion-roadmap.md), Stage 1c.
**Inputs:** the [Stage 1c diagnosis](evidence/stage1c/diagnosis/diagnosis.md) and its scripts and outputs;
[plan 2](plans/2-sec-filing-index-ingestion-spec.md) D12, F17 and Handoff, bullet "Task 5 halt (2026-10-29)";
the invocation 1 record `specs/evidence/baseline-campaign/invocations/1-8305a3d9-54a1-46ae-863c-af8227118417.json`;
the 1b release `9fa189a0…` and its evidence (`specs/evidence/stage1b/`);
[local recovery](../docs/runbooks/local-recovery.md), row "Crash after pointer update".

## 1. Purpose

Invocation 1 of the Stage 2 campaign halted with launcher exit 9 and `state_conflict` at
`workflows/processing.py:96`. A daily member's `publish` child completed and moved nine filing-quarter
pointers. The member-completion check then judged the member incomplete.

The diagnosis found the cause. The completion check failed on its own repair inventory, not on the
published data:

1. `evaluate_member` calls `_obligations`, which calls `_publish_calls` (`workflows/completion.py:536`).
2. The legacy loop (`:551–566`) calls `_legacy_publish_call` on every `publish` Attempt that is not a
   checked child call. It does this before it looks at the Attempt's result.
3. `_legacy_publish_call` refuses an input workset that is not complete (`:472–473`).
4. The L12 acceptance run (`accept-38bf7c024e0fd5ac`, 2026-10-18) left a finished publish Attempt,
   `2024Q1-publish-attempt-000`. Its input is the 2024Q1 transformed workset, which is incomplete with
   0 observations because the 2024Q1 transform was quarantined. Its result is `incomplete` with no
   quarters, so it moved no pointer. No repair record exists for it.
5. The inventory raises. `evaluate_member` turns that into a non-retryable `state_conflict` gap. Every
   member on this store fails the same way.
6. `process_member` raises a generic `Conflict` at `:96` and drops the gap text, so the logs carry only
   the stock message.
7. `process_member` had already run `evaluate_member` before it dispatched (`:29`). It read only the
   obligations and ignored the gap, so it dispatched and moved nine pointers.

The nine generations are sound. With the 2024Q1 Attempt out of view, the member evaluates complete
with nine quarter captures. An independent full-path rebuild of each quarter equals the stored data
rows in all nine quarters. The refusal and the loop order came with the imported baseline (`9fcb4f6`),
so every release since the port carries them. The fixture stores of the 1a and 1b gates had no such
Attempt.

This stage fixes the inventory, makes the halt explain itself, and stops a member before dispatch when
the engine already knows its completion cannot pass. It ships the change as a reviewed native release,
called the 1c release below.

## 2. Scope

In scope:

- The inventory fix (M1, M2).
- The gap text in the completion conflict (M3).
- The stop before dispatch (M4).
- The offline proof that the halted member's store state completes on the 1c release (§5 item 4).
- The 1c release, its offline verification and the live-config selection (§6).
- Parent-spec and runbook amendments (§7).

Out of scope:

- Any change to the generation, manifest, receipt, selection, evidence, Attempt or config formats, or
  to an outcome or exit code (M6).
- The F17 fixture: a 1b incremental generation on a base that `fc68adef…` wrote (§4.3 item 5; S1).
- The `permit_expired` refusal of the daily-index root listing in invocation 1 (§4.3 item 6).
- Any recovery command or any edit of a pointer, Attempt or object. The repair is a normal re-run (§4.2).
- Any SEC request, live run, or change under `data/`. The live repair runs only in the plan 2 revision,
  under its own owner gate.
- Any platform item. The platform workspace member stays off `main` until the 1c release is built (S2).

## 3. Requirements

| ID | Requirement |
|---|---|
| M1 | A new builder makes the legacy publish call descriptor without the complete-input refusal. It keeps every other check that `_legacy_publish_call` has today. `_legacy_publish_call` keeps its name, signature and behavior: it calls the builder, then refuses an incomplete input with today's message. The descriptor bytes, and so the call key, stay identical to today's for every Attempt that today's code accepts. (Builder check, my call.) |
| M2 | The legacy loop of `_publish_calls` builds the descriptor for every `publish` Attempt that is not a checked child call, and keeps `_transformed_input` on every one, as today. It keeps a call when today's rule keeps it: no result, or a `WorkflowRepairObligation` row, or a repair authority under the call key. The complete-input check applies only to a kept call, with today's message. A finished Attempt with an incomplete input and no repair record is not kept and raises nothing. Only this loop uses the new builder. Every other caller keeps calling `_legacy_publish_call` unchanged: `read_legacy_publish`, `_call_context`, `_read_document` (`completion.py:228`) and `legacy.bootstrap_legacy` (`workflows/legacy.py:160`). |
| M3 | The completion conflict at `processing.py:96` carries the evaluation's gaps in its message: the stock text, then for each gap its code and message, in order. The text stays one line and passes `require_text`, as `error_text` output does. The error `details` stay `{'type': 'Conflict'}`. No format changes (M6). |
| M4 | After the replay check, `process_member` reads the gaps of its first `evaluate_member` call. If any gap has `retryable` false, it raises `Conflict` before any repair or child dispatch. The message names the member, then each such gap's code and message, in the M3 form. Retryable gaps (`acquisition_pending`, `transform_pending`, `publication_pending`) never stop a member. Obligations keep today's repair path. |
| M5 | On the 1c release, a store with the halted member's shape completes that member with no pointer moved a second time. Completion here means the engine's own definition: `evaluate_member` returns complete with no obligations, and the workflow result carries its capture under `already_complete`. No `WorkflowMemberResult` receipt is required (§4.2). The re-run takes the engine's normal path. No recovery command is added. |
| M6 | Generations, manifests, receipts, member evidence, selection (`sec-local-workflow-selection-v1`), Attempts, effective config, outcomes and exit codes do not change format. Existing receipts stay valid byte for byte. Exact replay returns identical bytes. |
| M7 | The 1c release is built by `build_release` from clean committed `main`. The package version stays `0.2.0`. `uv.lock` and the requirement lines of `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` are byte-identical to the 1b build inputs, with no platform member. The 1b release, the D5 release, `fc68adef…` and older releases are retained (§4.9). |
| M8 | The live config selects the 1c release at an owner checkpoint. `execution.dispatch_reserve_seconds` stays 1800. Offline preflight passes, and the new effective-config SHA-256 is recorded. |

## 4. Design

### 4.1 Components

| Unit | Change |
|---|---|
| `workflows/completion.py`, new descriptor builder | Extracted from `_legacy_publish_call`, without the complete-input refusal (M1). Its name is the builder's call. |
| `workflows/completion.py`, `_legacy_publish_call` | Calls the new builder, then the complete-input refusal. Behavior unchanged for all its callers (M1, M2). |
| `workflows/completion.py`, `_publish_calls` | The legacy loop calls the new builder, runs `_transformed_input`, decides whether to keep, and checks complete input only for a kept call (M2). |
| `workflows/processing.py`, `process_member` | The stop before dispatch (M4) and the gap text at `:96` (M3). One small helper formats gaps for both. |

No other module changes. `workflows/legacy.py` is unchanged. The runner's evaluations (`runner.py:87`, `:204`, `:262`) stay as they are.

### 4.2 Data flow of the repair

The runbook row "Crash after pointer update" says: re-run through the checked publish/workflow boundary,
and never advance a pointer twice. On the 1c release, the halted member takes this path:

1. The member has no `WorkflowMemberResult`, so it stays pending.
2. Its `evaluate_member` now returns complete, with nine quarter captures and no obligations (diagnosis,
   `diag7` spike).
3. The runner's selection (`runner.py:262`) puts a complete member in its `complete` list, not in
   `selected`. So the member is not dispatched, and no child runs for it.
4. The workflow result accounts for it from that capture, and lists its source in
   `already_complete_sources`. No pointer moves.

The member gets no `WorkflowMemberResult` receipt on this path (`run_workflow` writes receipts only for
`selection['jobs']`). So `WorkflowMembers.inventory` keeps it as pending, and every later invocation
evaluates it again and lists it as already complete. That is an existing state on this store, not a new
one. Under the M2 rule, the L12 members for 2026-10-14 and 2026-10-15 are in the same state today
(diagnosis, `diag8`). This stage counts that as member completion, so the repair obligation of the
runbook row is met. The plan Handoff tells the campaign ledger and the coverage tool that these three
sources appear as already complete in every invocation.

If the builder finds that a different path is taken (for example `runner.py:87`, or a dispatch that ends
`unchanged`), that is acceptable when M5 holds. The plan records the path that the §5 item 4 test
observes.

A live `backfill` invocation still runs its `discover` child first, and that child sends SEC requests.
So the live repair belongs to the plan 2 revision and its Task 4 gate, not to this stage.

### 4.3 Errors and edge cases

1. **A kept call with an incomplete input.** An unfinished publish, or one with a repair record, whose
   input is incomplete still raises with today's message. Repairing it would republish an input that
   cannot publish. This case is not known to exist. M2 keeps today's refusal for it.
2. **Corruption outside the complete-input rule.** Every other check of `_legacy_publish_call` and
   `_transformed_input` still runs on every Attempt. A changed command, intent or input address still
   makes the inventory uncertain, and M4 now stops the member before dispatch.
3. **The stop rule and normal work.** A pending member normally starts with `acquisition_pending` or
   `transform_pending`. Both are retryable, so they dispatch as today. `evaluate_member` produces a
   non-retryable gap only from its caught exceptions (`state_conflict`).
4. **The stop rule and other members.** M4 raises, so the command ends with `state_conflict`, exit 9,
   and no workflow result, as invocation 1 did. The difference is that no child ran for the member, so
   no pointer moved and no repair obligation was created. A per-member skip that lets the run continue
   is not in scope: the known poisoning is store-wide, so every later member would stop too.
5. **F17.** The 1b incremental publish onto `fc68adef…` bases stays without a fixture test. Its evidence
   for this store is the diagnosis's full-rebuild comparison of the eight incremental quarters (data
   rows only). The deferred item "Two-release proof covers only first-generation 1b stores" stays open.
6. **`permit_expired`.** The discovery child's request for the daily-index root listing was refused at
   13:40:42Z ("child refused a stale dispatch window"). The local design treats a safely refused
   expired permit as an explicit deferral, not a fault (`specs/completed/sec-edgar-local-spec.md`).
   The plan Handoff names it for the plan 2 revision, which must account for the listing it skipped.
7. **Selecting the 1b release again.** The 1c release writes no new format, so the 1b release can still
   read a store that 1c wrote. On this store it fails the same completion check, so selecting it again
   is unsupported in practice. §4.9 records that.

## 5. Verification (offline)

Tests use stdlib `unittest` under `packages/sec-edgar-ingest/tests/network_guard.py`. Write each test
before its implementation.

1. **Reproduction (Exit item 1).** A fixture store gets a finished legacy publish Attempt whose input
   workset is incomplete: a quarterly source whose transform is quarantined by a conflicting duplicate
   key, then a standalone `publish` of that partial workset, which ends `incomplete` with no quarters.
   This is the shape of the L12 2024Q1 Attempt. Then a checked workflow member publishes a daily source.
   The fixture runs on the retained 1b release interpreter (`9fa189a0…`), as the Stage 1b two-release
   proof ran the D5 release, and the member fails with the state_conflict. The same fixture on the 1c
   code completes the member with all affected quarter evidence. The result goes into
   `specs/evidence/stage1c/`. A pinned assertion of the old behavior does not meet the Exit. (Builder
   check, my call.)
2. **M1 byte identity.** For every legacy publish Attempt in the existing fixtures that today's code
   accepts, the builder's descriptor and call key equal today's.
3. **M2 keep rule.** A finished Attempt with an incomplete input is not kept. An unfinished one, and one
   with a `WorkflowRepairObligation` row or a repair authority, is kept and still refused with today's
   message. A changed command or input address still makes the inventory uncertain.
4. **Repair (Exit item 2, M5).** A fixture store in the halted member's state: its `publish` child moved
   pointers, then the member-completion check failed, so no `WorkflowMemberResult` exists. One way to
   build it is item 1's store run on the 1b code. A re-run on the 1c code completes the member in the
   M5 sense: its capture is under `already_complete` and its source in `already_complete_sources`.
   Every `QuarterPublication` pointer before and after the re-run is compared: none moves a second
   time. No `WorkflowRepairObligation` row and no repair authority is left. The test records which
   path ran (§4.2).
5. **M3.** The `:96` conflict message contains each gap's code and message, in order.
6. **M4.** A non-retryable gap from the first evaluation raises before any dispatch: the fake
   dispatcher records no call, and no pointer moves. Retryable gaps dispatch as today. Obligations take
   the repair path as today.
7. **Diagnosis replay.** `diag2.py` and `diag5.py` run against a fresh scratch copy of `data/` on the 1c
   interpreter, with the same root-binding method. `evaluate_member` for member `3554e8ef…` returns
   complete with no gaps, and the pointer list equals the diagnosis's. A hash list shows `data/`
   unchanged. The other scripts depend on today's `_legacy_publish_call` or rebuild nine quarters, so
   they are not run again. The committed scripts stay as they ran. (Builder check, my call.) This runs once, at
   release verification, and its output goes into the release evidence. It is not part of the gate.
8. **Full gate.** `scripts/check-sec-edgar-ingest.sh` passes. The 1b gate count is 1108 tests in 71
   modules (`specs/evidence/stage1b/gate.md`). The new tests add to it. The gate takes about 75 minutes.

No measurement is needed. The change adds no child and no full content check, and M4 reuses an
evaluation that runs today. The reserve stays 1800 s (M8).

## 6. Release and exit evidence

Record in `specs/evidence/stage1c/`:

1. The diagnosis (`diagnosis/`), committed with this spec.
2. The 1c release ID, its manifest path and its `git_revision`.
3. The M7 lock and export comparisons against the 1b build inputs, showing no platform member.
4. The offline checker result and `preflight_current` on the 1c release, with 1b, D5, `fc68adef…` and
   older releases kept.
5. The §5 item 7 replay output.
6. The commit that selects the 1c release in `conf/sec-edgar-local.json`, and its effective-config SHA-256.
7. A statement that no SEC request was sent and nothing was written under `data/`.

Exit (roadmap Stage 1c, as amended by S1): the §5 item 1 reproduction fails on the 1b release and
passes on the 1c release; the §5 item 4 re-run completes the member and moves no pointer twice (§4.7);
the offline checker and preflight pass on the 1c release, with the 1b release and older releases
retained (§4.9); M6 holds, so the provenance and reader contracts hold (§9); no SEC request was sent
and nothing was written under `data/`.

The plan's `## Handoff to later stages` names every value the plan 2 revision must change: the release,
the effective-config SHA-256, regenerated `conf/stage2/*.json`, the re-verify list for
`scripts/baseline-campaign.py` against the 1c release, how Task 5 treats the repair of member
`3554e8ef…` (§4.2) and ledger row k = 1, the three sources that appear as already complete in every
invocation (§4.2), the skipped daily-index listing (§4.3 item 6), the window end
2026-11-05T13:00:00Z, and the open quarter 2026Q4.

**Roadmap.** At plan completion the resume amends Stage 1c's Exit to the real cause (S1). Its first
Exit clause today names the F17 shape, which the diagnosis ruled out.

**Deferred items.** "Two-release proof covers only first-generation 1b stores" stays open, with a note
that the live store now holds such generations and that the diagnosis compared their data rows to a
full rebuild. No new item unless the plan finds one.

## 7. Parent-spec and runbook amendments

The plan's last task applies these:

- Parent spec §4.7: a finished publish Attempt with an incomplete input and no repair record is not a
  repair obligation. A member stops before dispatch when its completion check reports a non-retryable
  gap.
- Parent spec §4.8: the 1c manifest path and the new effective-config SHA-256.
- Parent spec §4.9: the 1c release, and that selecting 1b again for this store is unsupported (§4.3
  item 7).
- `docs/runbooks/local-recovery.md`: under "Crash after pointer update", that the conflict message now
  names the gaps, and that a stop before dispatch leaves no pointer to repair.

## 8. Decisions

Owner answers at brainstorming, 2026-10-29:

- **Diagnosis:** "Yes, diagnose". The diagnosis ran read-only on a scratch copy of `data/`.
- **S1** Exit reproduction: "Real cause only". The Exit tests the real cause. The diagnosis's
  full-rebuild comparison is the F17 evidence for this store, and the F17 fixture stays deferred.
- **S2** Platform: "Hold platform". The platform member stays off `main` until the 1c release is built.
- **S3** Approach: "Fix + explain + stop". The inventory fix (M1, M2), the gap text (M3) and the stop
  before dispatch (M4).
- Roadmap defaults (vii)–(ix), approved 2026-10-29: one stage, not an investigation stage plus a build
  stage; the recovery path is designed and proved offline, and runs live only in the plan 2 revision;
  Stages 3–5 consume this release.

Calls made in writing this spec, for the owner's review:

- The stop is in `process_member` only, not also in the runner before `discover` (§4.1). On a poisoned
  store, the `discover` child still sends its requests before the first member stops.
- The repair is the normal re-run, with no recovery command (M5, §4.2), because the diagnosis shows the
  halted member already evaluates complete under the fix.
- `permit_expired` goes to the plan 2 revision through the Handoff, not into this stage (§4.3 item 6).
- The diagnosis replay on a scratch copy is release evidence, not a gate test (§5 item 7), because the
  gate must not read `data/`. It replays only `diag2.py` and `diag5.py`.
- `_legacy_publish_call` keeps its behavior for every caller, and only the inventory loop uses the new
  builder (M1, M2). The builder check found two callers the draft did not name.
- Completion of the halted member is the `already_complete` capture, with no receipt (M5, §4.2). The
  L12 members for 2026-10-14 and 2026-10-15 are already in that state.
- The reproduction runs on the retained 1b interpreter, not as a pinned assertion (§5 item 1), because
  the Exit says it "fails on the 1b release".

Approaches considered:

| Approach | What changes | Trade-off |
|---|---|---|
| 1. Fix only | M1, M2 | Smallest review. The next unknown halt still shows the stock message and moves pointers first. |
| 2. Fix and explain | M1–M3 | The next halt names its cause. It can still move pointers before it fails. |
| 3. Fix, explain and stop (chosen) | M1–M4 | The next halt names its cause and moves no pointer. A wrong stop rule could block a member, so M4 fires only on non-retryable gaps. |

"Skip every finished Attempt" was rejected: the loop needs the built descriptor's call key to find a
repair record, so a finished Attempt must still be built.

## 9. Rollout note

> Roadmap: specs/sec-filing-index-ingestion-roadmap.md, Stage 1c — on plan completion, tick the
> stage and re-validate later stages against what shipped.

Approval of this spec authorizes no SEC request, live run or campaign. The plan 2 revision, written
against the 1c release, and its Task 4 owner gate stay the only route to live traffic.
