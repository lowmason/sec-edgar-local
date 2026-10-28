# Stage 1b branch gate (plan 5 Task 10)

**Branch:** `stage1b-per-member-cost`, cut from `main` at `ceeb0f3`.
**Gated commit:** `8c1c32180eef0317ea337a3d99b6175b39773fe2`. Later commits on the branch change only this evidence file.
**Command:** `sh scripts/check-sec-edgar-ingest.sh` from the worktree, started through a small wrapper script that keeps the gate's exit code. Environment: `SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache`, `UV_PROJECT_ENVIRONMENT=/tmp/s1b-venv`, `UV_NO_SYNC=1`.
**Started:** 2026-10-28 09:46:48 UTC. **Ended:** 2026-10-28 11:00:25 UTC.
**Result:** `Ran 1108 tests in 4413.532s`, `OK`, `exit 0`, 71 test modules. No failure, no error, no skip.

The gate script also built the sdist and wheel for version `0.2.0`, checked `--help` for every command and `--version`, compiled the package, and ran `git diff --check`. All passed.

## Environment deviations
1. **Shadow venv.** As for the Stage 1a gate, `uv run --offline --locked` cannot build an environment in a worktree, because the `pyarrow` wheel is not in the offline uv cache. The gate ran in `/tmp/s1b-venv`. It puts the worktree source first, then the main venv's site-packages. `PYTHONDONTWRITEBYTECODE` was unset for the run.
2. **`.venv` symlink.** The worktree had no `.venv`. Two tests in `test_local_launcher.InstalledLauncherTests` then failed with "project Python is missing". An untracked symlink `.venv` to the main checkout's `.venv` fixes that. `.gitignore` lists `.venv/`, which matches a directory only, so `git status` shows the symlink as `?? .venv`. It was never staged. It is removed after the gate.

## Gate runs on this branch
| Run | Commit | Result | Cause |
|---|---|---|---|
| 1 to 3 | earlier commits | Stopped before the end. Not evidence. | The code under `packages/sec-edgar-ingest/src` changed while each run was going (the review fix wave). Run 1 also showed the two launcher errors above. |
| 4 | `8a7e9c3` | 1107 tests, 1 error, 4081 s | `test_native_dispatch…test_output_overflow_is_bounded_and_never_safe_completion`. See below. |
| 5 | `8a7e9c3` | 1107 tests, the same 1 error, 4060 s | The same test and the same traceback, with no other process running. |
| 6 | `8c1c321` | 1108 tests, OK, 4414 s | The fix below, plus one new test. |

## The error in runs 4 and 5
The test raised `PermissionError: [Errno 1] Operation not permitted` from `os.killpg` in `runtime.py` (`run_child`, inner function `forward`). `forward` caught only `ProcessLookupError`. The branch did not change `runtime.py` or that test file.

**Cause.** The test makes a child write 2 MiB at once. The output limit is 1 MiB. After the limit, `run_child` sends `SIGTERM` for every further chunk it reads. The first signal kills the child. If the parent then reads one more buffered chunk, it signals a child group that has died and is not yet reaped. On macOS, `killpg` then raises `PermissionError`, not `ProcessLookupError`. The `finally` block could raise the same error from `forward(SIGKILL)`. This is a timing race. The test passes only when the read loop reaches end-of-file before the child is gone.

**Evidence.**
- The test passed alone 31 of 31 times in the foreground. The whole `test_native_dispatch` module passed alone. The branch's new modules followed by `test_native_dispatch` in one process passed (98 tests). As a background task the single test failed 1 of 20 times.
- On the unchanged `runtime.py`, a parent that sleeps after each `os.read` raised the same `PermissionError` every time (3 of 3, with delays of 0.05 s and 0 s). Without any sleep call it passed (4 of 4).
- A direct check on this Mac: `killpg` on the group of an exited, unreaped child raises `PermissionError`. A group with an unreaped leader and a live member is signalled normally. So swallowing the error cannot hide an undelivered signal to a live process of the same user.

**Fix.** Commit `17d78da`: `forward` now catches `(ProcessLookupError, PermissionError)`. The new test `test_overflow_survives_a_parent_that_reads_slowly` slows the parent's reads after the limit, so the race happens every time. It failed 6 of 6 on the unchanged code and passed 12 of 12 with the fix. Commit `8c1c321` adds one comment to that test. The owner chose to fix it on this branch (ledger decision D8). A scoped review (Opus) approved it with no Critical or Important finding. A Codex read-only review found no actionable regression.

**Not known.** Why the Stage 1a gate passed this test and runs 4 and 5 did not. The race depends on scheduling, and the larger process in the full run may be slower per read. This was not measured.

**Deferred.** The two `os.killpg(process.pid, 0)` probes in `run_child` also catch only `ProcessLookupError`. They could raise `PermissionError` if a detached descendant stays in the group as a short-lived zombie. This was not reproduced and is outside the fix.

## Test counts
The Stage 1a gate had 1020 tests in 64 modules. This gate has 1108 tests in 71 modules. The branch adds 7 test modules: `test_etl_columnar`, `test_etl_equivalence`, `test_etl_incremental`, `test_etl_integrity`, `test_full_check_budget`, `test_measure_cost` and `test_release_1b`. It also changes tests in `test_reconcile_workflow.py` and `test_native_dispatch.py`, and the helper `support_release.py`, and adds the helpers `support_catalog.py` and `support_incremental.py`.

## Checks of `main`
- `main:pyproject.toml` has `members = ["packages/sec-edgar-ingest"]`. No platform member.
- `git diff ceeb0f3 HEAD -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml data` is empty.
- `main` is still at `ceeb0f3`, the merge base. A fast-forward merge is possible.
