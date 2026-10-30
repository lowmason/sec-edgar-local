# Deferred items

## 4-sec-filing-index-bounded-drain — 2026-10-27
- [x] Per-member cost (owner decision D2, plan 4): the owner does not accept the measured
      per-member cost. Full-size quarterly members took more than 9,000 s, and no reserve fits
      them under the 3,300 s launcher default. A per-member-cost roadmap stage goes before
      Stage 2. Plan 4 did not place it. Inputs: specs/evidence/d5-release/measurement.md and
      finish-measurement.json. See specs/plans/completed/4-sec-filing-index-bounded-drain.md,
      Decisions D2 and Handoff. Size: design. Done when: derive-roadmap places the stage in
      specs/sec-filing-index-ingestion-roadmap.md and a plan for it completes.
      → done in plan 5 (specs/evidence/stage1b/measurement.md, specs/evidence/stage1b/release.md)
- [x] Unmeasured drain costs (plan 4 Task 2): the full measurement run reached its deadline, so
      measure 1 (a closed-quarter rebuild by one back-dated daily row), the 14-quarter fan-out,
      and the 40- and 80-source open-quarter publish marks were never measured.
      scripts/measure-d5-drain.py holds the scenarios. Size: plan. Done when: the per-member-cost
      stage measures them, or its spec records that they are not needed.
      → done in plan 5 (specs/evidence/stage1b/measurement.md)
- [x] Provisional live reserve (owner decisions D2 and D4): conf/sec-edgar-local.json sets
      execution.dispatch_reserve_seconds to 1800 without a measured basis. It covers a daily
      member with up to about 18 sources already in its quarter, not full-size quarterly
      members. Size: design. Done when: the owner approves a reserve set from measured member
      costs, or approves 1800 as final.
      → done in plan 5 (specs/evidence/stage1b/measurement.md, specs/evidence/stage1b/release.md)
- [ ] B4 single-candidate limit (final-review note): runner.sibling_completion in
      packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py never skips a source
      with two or more historical snapshots, so those sources keep F10's repeated child
      sequence. A refused skip also costs an extra inventory scan and evaluate_member before
      process_member repeats it. Size: plan. Revisit if: the per-member-cost stage or Stage 2
      shows repeated child sequences or refused-skip scans as a material share of run time.
      Checked against plan 5 section 6 (specs/evidence/stage1b/measurement.md, 2026-10-28): engine time inside a member's wall is 0.1% to 0.4% for the full-size members (closed baseline, authority) but 28.8% for the open daily members (about 3.7 s each) and 54.5% for the finish members. The scenarios do not separate repeated child sequences or refused-skip scans, so the revisit trigger is neither met nor cleared. Owner decision D12: keep open.
- [ ] Order-aware two-release proofs (owner decision R2): member order is not pinnable because
      member_id hashes wall-clock and per-build inputs. In about half the runs of the pending
      scenario in packages/sec-edgar-ingest/tests/test_release_upgrade.py, and one run in four
      of the first test in test_release_origin.py, no child runs on the origin release. See
      specs/evidence/d5-release/two-release.md, "Limits of the proof". Size: plan. Revisit if:
      member ordering becomes deterministic, or an origin-release regression escapes these tests.
- [ ] Test-hygiene Minors from plan 4 task reviews (all triaged to ship by the whole-branch
      review), in packages/sec-edgar-ingest/tests/:
      test_workflow_cli.py engine admission test has a vacuous assertFalse(live data exists),
      a comment that says "missing manifest" for a case that reaches the isolation refusal, and
      covers backfill only; stale comment near test_workflow_cli.py:72.
      test_workflow_drain.py: a comment near :174 overclaims; the missing-key test is weak; no
      test reuses a receipt after a cutoff; the P8 test compares () == () because fixture
      children emit no gaps; the tamper set is thin; replay checks are near-vacuous.
      test_release_upgrade.py has a tautological assertion near :203; the repair probe's
      both-B-first fallback was proven once, by a reverted local edit.
      Production: the contract-level B4 branch in workflows/contracts.py is looser than the full
      B4 shape (processing._validate_sibling_completion enforces it); a refusal message has a
      cosmetic order issue. Size: quick-fix. Done when: one test-hygiene pass over these files
      lands with the full gate green.

## 5-sec-filing-index-per-member-cost — 2026-10-28
- [ ] Review Minor (plan 5 Task 10, task review of the runtime race fix 17d78da; see
      specs/plans/completed/5-sec-filing-index-per-member-cost.md, Decision D8): in `run_child`,
      packages/sec-edgar-ingest/src/sec_edgar_ingest/runtime.py, the two group-existence probes
      `os.killpg(process.pid, 0)` at :657-659 and :666-668 catch only `ProcessLookupError`. On
      macOS, `killpg` raises `PermissionError` (EPERM) when the only processes left in the group
      are unreaped zombies. Both probes run after `process.wait`, so the leader is reaped, but a
      detached descendant can be a short-lived zombie. Then `run_child` raises instead of
      returning a `ChildExit`. The reviewer did not reproduce it. `forward` (:613-623) already
      catches both errors since 17d78da. Deferred: the race-fix brief limited the change to
      `forward`, and `src` is frozen at the 1b release build. To do: write a test that keeps a
      zombie descendant in the child's group (model it on
      `test_native_dispatch.SupervisedProcessTests.test_overflow_survives_a_parent_that_reads_slowly`),
      then catch `PermissionError` in both probes. Open question: does EPERM count as drained?
      The review's kernel check covered a zombie group leader, alone or with a live member. It
      did not cover a reaped leader with a zombie descendant. Cost: full gate,
      release build, config selection. Size: quick-fix. Done when: both probes handle
      `PermissionError`, a zombie-descendant test pins it, and the full gate is green.
- [ ] A candidate that the C6 equivalence check refuses blocks its own retry (plan 5 whole-branch
      review, finding I1; the owner chose "test and document" with no code change in Decision D7,
      and ruled on the recovery text in Decision D12, both 2026-10-28; see
      specs/plans/completed/5-sec-filing-index-per-member-cost.md). In
      packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py, `_incremental_candidate`
      (:261-287) stages both files and stores the manifest (`_store_manifest`, :283) before C6
      runs (:284). The store is write-once, and the generation address depends only on the
      quarter, the base generation and the source fingerprint. So a retry with the same inputs
      finds the stored candidate through `_existing` (:102-111) and runs the full content check on
      it. When that check fails, `publish` reports `invalid_source`, which is not retryable
      (packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/commands.py:245-249). A C5 code fix
      does not clear the block unless it changes the retained basis. Otherwise the quarter
      recovers only when its source set or base changes. Removing the candidate's objects is not
      a supported recovery step: parent spec §4.7 forbids deleting objects to reset state, no
      command does it, and such a removal needs a separately reviewed operational decision. Each
      blocked retry costs one full check, about 415 s for a full-size quarter
      (specs/evidence/stage1b/diagnosis.md §1). Tested: in
      packages/sec-edgar-ingest/tests/test_etl_incremental.py,
      `PrePointerRefusalTests.test_a_wrong_incremental_row_is_refused_before_the_pointer` shows
      that a retry also raises and the pointer does not move. Documented in
      specs/completed/sec-filing-index-per-member-cost.md §4.3 item 5, the parent spec
      (specs/sec-filing-index-ingestion-spec.md) §4.6 and docs/runbooks/local-recovery.md (row
      "Refused incremental candidate"). The code fix is larger: run C6 on the local Parquet files
      before anything is staged or stored, so a refused candidate leaves no object. That changes
      C6's input and the incremental stage order, and it needs the full gate, a release build and
      a config selection. Size: design. Done when: the owner approves running C6 on the local
      Parquet files before anything is staged and it lands, or records a reviewed operator
      procedure for removing a refused candidate's objects.
- [ ] History-scan cost (spec decision S4, "Measure, defer fix"; plan 5 Task 12, see
      specs/plans/completed/5-sec-filing-index-per-member-cost.md): per-member engine
      time grows with the `WorkflowChildCall` rows that the engine scans (`_obligations`,
      `reuse_exact_binding`). specs/evidence/stage1b/measurement.md, "History scan (S4)", fits
      engine seconds (member wall minus its children) against those rows at member start. Slopes
      in seconds per `WorkflowChildCall` row: `open` 0.0253, `closed` 0.0290, `authority` 0.0236,
      `finish` 0.0218 (measurement.json `measures.history`). Projections: 10.0 to 13.0 s per member
      at 400 child calls, and 28.3 to 36.2 s per member at 1,200. The most rows that a member saw
      was 241 (`open`), so both projections extend the fit. The live store's child-call count is
      not measured. Figures for the check: reserve 1,800 s; reserve rule 1.25 × 1,010.9 s + 480 s
      = 1,743.6 s; fit-gate room 489 s at a fixed reserve. The fit uses only `WorkflowChildCall`
      rows, but specs/completed/sec-filing-index-per-member-cost.md §6 (the "History growth" row)
      also names `Attempt` rows. The script keys each member's child times by command
      (scripts/measure-d5-drain.py :254-255), so a repeated child command would hide seconds. A
      read-only check of the four reports in fixture-data/s1b-measure-20261028T110945Z/ found no
      repeated child command, so the slopes are not affected. Deferred by S4: this stage measures
      the cost and does not fix it. Size: plan. Revisit if: a live run's per-member engine time
      grows past the measured slope, or the projection at the live store's child-call count
      exceeds the reserve's margin.
- [ ] Unmeasured member class: an open-quarter member with a quarterly membership authority (the
      A1 locality exception; plan 5, specs/plans/completed/5-sec-filing-index-per-member-cost.md,
      "Defaults for owner review", A1). The §6 `open` scenario has no authority, and the
      `authority` scenario runs in a closed quarter (2026Q3), so
      specs/evidence/stage1b/measurement.md has no timing for this path. The whole-branch review
      found that this path read the whole authority as Python rows for each member. Commit
      fe6bca0 changed C5 and C6 to Arrow key filters (`columnar.quarter_key_column`; in
      packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/, incremental.py:123-132 and
      equivalence.py:44-49). In a fixture spy test, authority rows read as Python fell from 40 to
      0 in C5 and from 41 to 1 in C6. The reviewer named this member class the common live case
      for roadmap Stages 3 and 5. Deferred: the owner approved the measurement as run, with floor
      480 s and reserve 1800 s (plan 5 Decision D10, 2026-10-28). Size: plan. Revisit if: a live
      open-quarter member with a quarterly authority has a member wall above the slowest measured
      wall (1,010.9 s), or a later stage needs this class in its reserve.
- [ ] Full-check accounting and engine-path test gaps (plan 5 Task 3 and Task 4 reviews; see
      specs/plans/completed/5-sec-filing-index-per-member-cost.md). Code and test paths below are
      under packages/sec-edgar-ingest/:
      (1) Lost `put_once` race: in src/sec_edgar_ingest/etl/catalog.py, `_store_manifest`
      (:92-97) catches `Conflict`
      and calls `_existing`, which runs the full check. `build_candidate` then runs
      `validate_candidate_content` again (:345). So one full-rebuild candidate gets two full
      checks, against the C3 row of specs/completed/sec-filing-index-per-member-cost.md ("fully
      checked once per build, not twice"). On the incremental path the same branch gives a full
      check and then C6. No test covers the race. (2) `EngineBudgetTests` in
      tests/test_full_check_budget.py (:27-60) runs only `backfill`. `daily`, `reconcile`, the
      repair-resolution paths and `source_revert_gaps` are covered only by reading the code.
      (3) Per the Task 3 review (not re-run at HEAD),
      `test_a_changed_generation_byte_is_a_conflict_on_engine_paths` (:46-60) also passed before
      the switch to C1, so it guards the behaviour but does not prove the switch. (4) No
      engine-caller test drives a changed observation rows-file byte through `validate_capture`,
      `evaluate_member` or `checked._transformed_input` (a grep of the tests at HEAD found none).
      The C11 wiring rests on the zero readback count in the budget test.
      Deferred: tests and `src` are frozen at the 1b release build. Item (1) changes `src` if the
      second check is removed. Size: plan. Done when: the race path is tested and either skips the
      second full check or the C3 row states two checks, the budget test covers `daily` and
      `reconcile`, an engine-caller C11 test exists, and the full gate is green.
- [ ] Test gaps in the columnar, equivalence, incremental and integrity tests (plan 5 Task 2, 5, 6
      and 7 reviews; see specs/plans/completed/5-sec-filing-index-per-member-cost.md), in
      packages/sec-edgar-ingest/tests/:
      test_etl_integrity.py: no test for a missing rows file in `checked_observation` (expect
      `FileNotFoundError`), and none for the identity-mismatch `ValueError` ("candidate differs
      from exact manifest/gate identity") in `check_candidate_integrity`
      (packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/manifest.py:384-394).
      The "reads no rows" proofs patch named readers (`iter_file_rows`, `_verify_parquet`,
      `_validate_row_origins`), so a new reader would escape them.
      test_etl_columnar.py: three cheap tests. `key_mask` keeps `('1a','b')` apart from
      `('1','ab')`. `replace(ref, source_row_count=4, quarter_counts={'2026Q4':3,'2026Q3':1})`
      raises `ValueError` "observation readback counts differ". `generation_table(replace(data,
      role='changes'))` raises `ValueError` "generation Parquet schema differs". The reviewer
      argued that real data cannot collide, because a valid CIK has a fixed 10 characters (not
      re-checked).
      test_etl_equivalence.py:136-141: `test_refuses_a_duplicated_touched_row` does not assert
      that the duplicated row is the touched key (archive path ending `000003.txt`), as its name
      says.
      test_etl_incremental.py: `FallbackTests` (:130-160) has no case for a changed parser or
      schema version (C4 branch at
      packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/incremental.py:42-43; the re-transform
      in `build_candidate` also covers it). The oracle tests lack: a row count that is an exact
      multiple of 8,192 (`BATCH_ROWS`), a null `accession_number`, mixed-case or non-ASCII keys
      (Arrow byte order against SQLite BINARY, equal by inspection only), a `_best` tie on
      `source_id`, and an empty delta for the quarter.
      Deferred: tests are frozen with the 1b release build. Size: quick-fix. Done when: these
      tests land, each fails when its guard is removed by hand, and the full gate is green.
- [ ] Small cleanups in the frozen ETL code (plan 5 Task 2, 5 and 6 reviews; see
      specs/plans/completed/5-sec-filing-index-per-member-cost.md), in
      packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/:
      manifest.py:384-394: `check_candidate_integrity` repeats the identity and gate-record logic
      of `validate_candidate_content` (:367-375) and `validate_candidate` (:378-381). The plan gave
      that code verbatim. Extract one private helper.
      reader.py `_pinned_manifest`: the `check` parameter has no `Callable` annotation.
      columnar.py:56: `key_mask` sorts its value set. The sort is not needed.
      equivalence.py:101 assigns a lambda (`outside`). equivalence.py:28-32 `_change_payload`
      changes the dict that it is given.
      equivalence.py:74-78: C6 compares the candidate manifest with its base on gate, mode,
      membership authority, parser and schema. It never compares them with `context`. C4
      (`incremental.eligible`, incremental.py:36-47) does. A context check in C6 is defence in
      depth only.
      Deferred: `src` is frozen. Cost: full gate, release build, config selection, so do this
      with the next plan that builds a release. Size: quick-fix. Done when: the cleanups land in a
      release-building plan with the full gate green.
- [ ] Hardening of scripts/measure-d5-drain.py (plan 5 Task 9 review and implementer notes,
      triaged "may wait"; see specs/plans/completed/5-sec-filing-index-per-member-cost.md):
      (1) `history_fit` (:497-505) fits only `WorkflowChildCall` rows, and `history_counts`
      (:393-409) counts the whole `Attempts` table. specs/completed/sec-filing-index-per-member-cost.md
      §6 (the "History growth" row) names `Attempt` rows as a fit input. Align the spec or the
      fit. (2) `run_scenario` (:446-484) writes `WALLS` and `TIMINGS` into a failed report, but
      drops the member in progress (`OPEN_MEMBER`, :51). Per the Task 9 review, SIGTERM or SIGHUP
      can end the process without the `finally`, so no report is written. Not re-checked: while a
      child runs, `runtime.run_child` installs its own SIGTERM handler
      (packages/sec-edgar-ingest/src/sec_edgar_ingest/runtime.py:625-628), so the gap may apply
      only outside child runs. (3) `scenario` (:254-255) keys each member's children by command,
      so a repeated child command keeps only its last time and overstates engine time in
      `history_fit`. The 2026-10-28 reports have no repeats. (4) The step lists repeat in `run`
      (:334-349), `run_finish` (:352-354) and the `run_scenario` plans (:458-472). (5) `invoke`
      (:220-234) takes `splitlines()[-1]` of stdout, so an engine that refuses before it prints a
      result raises a bare `IndexError`. Deferred: the measurement record
      (specs/evidence/stage1b/measurement.md) was made with this script as it stands.
      Size: quick-fix. Done when: one pass lands with tests in
      packages/sec-edgar-ingest/tests/test_measure_cost.py and that module is green.
- [ ] Release-test assertions and documentation wording (plan 5 Task 1, 8, 11 and 14 notes; see
      specs/plans/completed/5-sec-filing-index-per-member-cost.md): (1)
      packages/sec-edgar-ingest/tests/test_release_1b.py
      `test_d5_runs_again_on_a_store_that_1b_wrote` (:28-39) asserts only exit 0 and an outcome of
      `success` or `unchanged`. The evidence also reports 0 jobs, no gaps and 2 `already_complete`
      entries (watcher only). The test could assert no gaps and no jobs. Its docstring argues a
      claim instead of saying what the test does. (2) specs/evidence/stage1b/two-release.md:5:
      "covers that half … does not test that half" reads oddly; add "(see Results item 2)". Lines
      :48 and :61 say that run 2's `d5-again` files were not captured. The Task 8 re-review says a
      partial tree exists (intent, discover call, exit, config, launch, discover result) without
      `selection.json` or the backfill `result.json` (not re-verified at HEAD). Suggested: "run 2's
      `d5-again` selection and result were not captured". (3) specs/evidence/stage1b/release.md:19
      "No platform package" rests on dependency names only. :36 "not durable" wording could be
      clearer. (4) specs/completed/sec-filing-index-per-member-cost.md: §5 items 1 and 3 each
      have one line of 127 and 133 columns against a wrap near 105, and the first §2 bullet has a
      doubled "and". (5) The §4.1 table of that spec has no row for
      packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/contracts.py (shared constants and
      `arrow_row`, changed by plan 5) or packages/sec-edgar-ingest/src/sec_edgar_ingest/runtime.py
      (the EPERM fix, 17d78da). (6) The C4 row in section 3 of the same spec says "no incoming source
      is the quarter's quarterly membership authority". `incremental.eligible`
      (packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/incremental.py:36-47) also requires the
      membership authority to equal the active generation's and every active source to stay
      selected. The behaviour is the same in practice; align the row with the code.
      Deferred: the test file is frozen with the release build. The text items were triaged "may
      wait". Size: quick-fix. Done when: one wording and assertion pass lands and the full gate is
      green for the test change.
- [ ] Two-release proof covers only first-generation 1b stores (plan 5 Task 8; on 2026-10-28 the
      owner chose to narrow the evidence wording and add no new scenario, Decision D3 in
      specs/plans/completed/5-sec-filing-index-per-member-cost.md).
      In all six runs of packages/sec-edgar-ingest/tests/test_release_1b.py, each 1b generation
      was a full rebuild with `base_generation_id` null and one source. The D5 rerun dispatched
      only its `discover` child. So no test shows D5 reading an incremental 1b generation, and no
      test shows a D5 publish built on a 1b generation. The first rests on byte identity
      (specs/completed/sec-filing-index-per-member-cost.md §5 item 3). The limits are recorded in
      parent spec §4.9 and in specs/evidence/stage1b/two-release.md, "Limits of the proof". A
      stronger scenario needs new fixture design: 1b publishes an incremental generation, then D5
      runs and publishes on top. Related: the plan 4 item "Order-aware two-release proofs".
      Stage 1c (plan 6): the live store now holds such generations: eight incremental 1b
      generations on `fc68adef…` bases, from invocation 1. The Stage 1c diagnosis compared their
      data rows with a full rebuild and found them equal. Change rows were not compared
      (specs/evidence/stage1c/diagnosis/diagnosis.md). The item stays open.
      Size: plan. Revisit if: the D5 release must run again on a store that holds an incremental
      1b generation, or a later stage plans to select D5 after a live 1b run.

## 6-sec-filing-index-member-completion — 2026-10-30
- [ ] The completion conflict names no cause when the evaluation has no gap (plan 6 Task 3, from
      the whole-branch review; the owner was told at the Task 4 checkpoint. See
      specs/plans/completed/6-sec-filing-index-member-completion.md). In
      packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py, the completion
      check after a finished child raises `child completion lacks all affected quarter/repair
      evidence` with no suffix when the evaluation has no gap, for example when it holds only
      repair obligations (spec M3 requires the stock text alone in that case). An operator then
      cannot see which obligation is open. Deferred: spec M3 fixes the text, and the 1c release is
      already built from this source. To do: decide a text that names the open obligations, add a
      test beside `test_member_completion.ProcessMemberTests`, and ship it in the next release.
      Size: quick-fix. Revisit if: an acceptance or campaign run ends with this stock conflict and
      the cause is not visible from the gaps or the obligation rows.
