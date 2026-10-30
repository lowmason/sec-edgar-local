# Stage 1c reproduction and repair proofs (plan 6 Task 4)

These proofs cover spec §5 items 1 and 4. The test module is `packages/sec-edgar-ingest/tests/test_release_1c.py`, class `MemberCompletionReleaseTests`. All tests use a fixture pack and a temporary store.

## Store shape

The fixture builds the store in these steps (plan P4). Each step runs through `CommandHarness`.
1. `simple_pack` holds the quarterly bodies `full-index` QTR3 and QTR4. Both bodies are replaced by bodies with a conflicting duplicate key: the same archive path with the names `Example` and `Changed`. The daily body stays clean.
2. A standalone `discover --mode quarterly`, then `collect`, then `transform`. The transform ends with exit 7 and outcome `invalid_source`. Its output workset has `complete=False` and 0 observations.
3. A standalone `publish` of that workset. It ends with exit 3 and outcome `incomplete`, with `quarters: []`. No pointer exists after it.

Then one `daily` workflow runs in the installed interpreter of a release. Its daily member publishes 2026Q4.

This is the shape of the L12 2024Q1 Attempt (diagnosis, Cause item 4).

## Item 1: fails on the 1b release, passes on the 1c code

Tests:
- `test_the_1b_release_halts_after_its_publish_moves_a_pointer`
- `test_the_1c_code_completes_the_member_on_the_same_store`

The 1b side runs the `daily` workflow in the 1b interpreter. The gate run (`gate.md`) used the 1b application built from `50423a404fb50a959b3ca4077301117d32804cc6` with `support_release.origin_release`. The extra run of this module used the installed release `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b`, selected with `SEC_LOCAL_1B_RELEASE` (plan P2). The 1c side runs the proof release that is built from the branch source.

| Side | Result in the test |
|---|---|
| 1b | The run ends with exit 9, outcome `state_conflict`, and `result_ref` null. The pointer for 2026Q4 has moved. The daily member has no `WorkflowMemberResult` row (no member receipt). |
| 1c | The run does not end with exit 9. The daily member has an outcome in `COMPLETE` and exactly one receipt row. The pointer list is still `['2026Q4']`. The member's completion capture lists `affected_quarters` as `['2026Q4']` and one quarter record, 2026Q4. |

Runs:
- Gate run, commit `bbd547c`: all 3 tests of this module passed (see `gate.md`).
- Installed-1b run, on the same commit: `Ran 3 tests in 56.080s`, `OK`, `exit 0`. The log is `fixture-data/stage1c-installed-1b.log` (git-ignored). The 1b side of that run used the installed `9fa189a0…` interpreter.
- Before the fix (Task 1, commit `fd86e1f`): the two 1c-side tests carried `@unittest.expectedFailure`. An unexpected success fails a unittest run, so the decorators could not be left in place after the fix. Task 2 (commit `a8eefca`) removed both decorators.

> Deviation: the plan's test code compared `capture['affected_quarters']`, a tuple, with the list `['2026Q4']`. The comparison failed only after the fix, because `expectedFailure` had hidden it. Commit `a8eefca` compares `list(capture['affected_quarters'])` with the same expected value. The check is the same fact.

## Item 4: repair (M5)

Test: `test_a_1c_rerun_completes_the_halted_member_and_moves_no_pointer`.

The test first runs the `daily` workflow on the 1b release. That run ends with exit 9, leaves one pointer (2026Q4), and writes no receipt for the daily member. The test then runs the `daily` workflow again with the 1c release (run id `repair`) on the same store. It checks these facts:
- The run does not end with exit 9.
- The pointer list is unchanged. No pointer moved a second time.
- The member's source is in `already_complete_sources`, and the member is in `selection['already_complete']`.
- No `WorkflowRepairObligation` row exists, and no `workflow-repair-authority` directory exists.
- `evaluate_member` for the member returns `complete=True` on the 1c code.

Observed path (spec §4.2): the member is selected as already complete. It is not in `selection['jobs']`, no child runs for it, and the report lists no member entry for it. The member still has no receipt after the run (0 rows). This matches the §4.2 path as the test asserts it. There is no P7 deviation.

The gate run and the installed-1b run both passed this test.

## Limits

Fixture packs only. The F17 shape (a 1b incremental publish on an `fc68adef…` base) is not tested (spec S1). The live store's evidence for it is the diagnosis's full-rebuild comparison of data rows.

No SEC request was sent. Nothing was written under `data/`.
