# Stage 1c branch gate (plan 6 Task 4)

**Branch:** `stage1c-member-completion`, cut from `main` at `4a28009`.
**Gated commit:** `bbd547cf2741bb7d73b2533452537d7532d4a325`. The worktree stayed at this commit, with a clean tree, from the start to the end of the run. No file under `packages/sec-edgar-ingest/src` changed while the gate ran.
**Command:** `sh scripts/check-sec-edgar-ingest.sh` from the worktree, in the background, with the exit code appended to the log. Environment: `env -u PYTHONDONTWRITEBYTECODE UV_PROJECT_ENVIRONMENT=/tmp/s1c-venv UV_NO_SYNC=1 SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache`.
**Started:** 2026-10-30 13:41:58 UTC. **Ended:** 2026-10-30 14:53:47 UTC.
**Result:** `Ran 1125 tests in 4305.354s`, `OK`, `exit 0`, 73 test modules. No failure, no error, no skip. This was the only gate run on this branch.

The gate script also built the sdist and wheel for version `0.2.0`, checked `--help` for every command and `--version`, compiled the package, and ran `git diff --check`. All passed.

## Environment deviations
1. **Shadow venv.** As for the Stage 1a and 1b gates, `uv run --offline --locked` cannot build an environment in a worktree, because the `pyarrow` wheel is not in the offline uv cache. The gate ran in `/tmp/s1c-venv`. Its `.pth` file puts the worktree source first, then the main venv's site-packages. `PYTHONDONTWRITEBYTECODE` was unset for the run.
2. **`.venv` symlink.** Two tests in `test_local_launcher.InstalledLauncherTests` need a `.venv` in the worktree (plan 5, `specs/evidence/stage1b/gate.md`, deviation 2). An untracked symlink `.venv` to the main checkout's `.venv` provided it. The symlink was never staged. It was removed after the gate, and `git status --porcelain --untracked-files=normal` is empty.

## Test counts
The Stage 1b gate had 1108 tests in 71 modules. After that gate, `test_baseline_campaign.py` gained 4 tests on `main`, so `main` at `4a28009` held 1112 tests (plan fact F8). This gate has 1125 tests in 73 modules, which is 1112 plus 13. The branch adds 13 tests in 2 new modules:
- `test_release_1c`: 3 tests. They reproduce the halted member on the 1b release and the repair on the 1c code (spec §5 items 1 and 4).
- `test_member_completion`: 10 tests. Six cover the legacy inventory (M1, M2, spec §5 items 2 and 3). Four cover the gap text and the stop before dispatch (M3, M4, spec §5 items 5 and 6).

The branch also adds one constant, `ONE_B_REVISION`, to the helper `tests/support_release.py`. It changes no existing test.

## Deviations from the plan's test code
> Deviation: in `test_release_1c.test_the_1c_code_completes_the_member_on_the_same_store`, the plan compared `capture['affected_quarters']` with a list. `read_workflow_result` returns a tuple, so the comparison failed with `('2026Q4',) != ['2026Q4']`. The `expectedFailure` decorator from Task 1 had hidden this. Commit `a8eefca` wraps the value in `list(...)` and keeps the expected value. The commit message says so. The test still checks the same fact.

> Deviation: the whole-branch review came after the gate. Commit `c8184c7` changes only `packages/sec-edgar-ingest/tests/test_member_completion.py` (it adds 3 tests and fixes one docstring and the import order). It changes no file under `packages/sec-edgar-ingest/src`, so the plan (Task 4 Step 5) does not require a new gate. `git diff bbd547c HEAD -- packages/sec-edgar-ingest/src` is empty. After the commit, `test_member_completion` and `test_release_1c` ran together: `Ran 16 tests in 135.661s`, `OK`. The branch tip therefore holds 1128 tests by count (1125 plus 3). The full suite was not run on the tip. Every later commit on the branch is a test or evidence file.

## Checks of the branch (plan Task 4 Step 6)
- `stage1c-member-completion:pyproject.toml` has `members = ["packages/sec-edgar-ingest"]`. No platform member.
- `git diff --stat 50423a404fb50a959b3ca4077301117d32804cc6 stage1c-member-completion -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml` is empty.
- `git diff --stat main stage1c-member-completion -- packages/sec-edgar-ingest/src` lists only `workflows/completion.py` and `workflows/processing.py`.
