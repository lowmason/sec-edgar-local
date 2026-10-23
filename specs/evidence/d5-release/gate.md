# Stage 1a branch gate (plan 4 Task 8)

**Branch:** `stage1a-bounded-drain`, cut from `main` at `d46d48c`.
**Gated commit:** `93038fe4e3767c35af6fa41496b41152ea6fd81b`. Later commits on the branch change only this evidence file and the plan.
**Command:** `sh scripts/check-sec-edgar-ingest.sh` from the worktree, with `SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache`.
**Started:** 2026-10-23 22:08:14 UTC. **Ended:** 2026-10-23 23:18:19 UTC.
**Result:** `Ran 1020 tests in 4202.843s`, `OK`, `exit 0`, 64 test modules.

The gate script also built the sdist and wheel for version `0.2.0`, checked `--help` for every command and `--version`, compiled the package, and ran `git diff --check`. All passed.

## Environment deviation
`uv run --offline --locked` cannot build an environment in a worktree: the `pyarrow==25.0.1` wheel is not in the offline uv cache. So the gate ran with `UV_PROJECT_ENVIRONMENT=/tmp/drain-venv` and `UV_NO_SYNC=1`. The shadow venv puts the worktree source first, then the main venv's site-packages, and has a `sec-edgar-ingest` console script. The worktree's `releases/artifact-cache` is a symlink to the main checkout's cache. `PYTHONDONTWRITEBYTECODE` was unset for the run. The release build in Task 9 uses the normal `uv` environment in the main checkout, not this one.

## Earlier gate runs on this branch
| Run | Commit | Result | Cause of the failures |
|---|---|---|---|
| 1 | `67cf44a` | 1016 tests, 5 errors, 4461 s | See below. |
| 2 | `1650349` | 1017 tests, the same 5 errors, 4328 s | See below. |
| 3 | `93038fe` | 1020 tests, OK, 4203 s | The three tests added by the fix; no other test changed. |

The 5 errors were `test_local_modes.NativeCliTests.test_console_ignores_valid_poisoned_application_bytecode_before_first_import` and four tests in `test_runtime_preflight.PreflightTests`. They already existed on `main`. `test_acceptance_selection.py` loads `scripts/accept-sec-native.py` and `scripts/verify-sec-native-adjudication.py` in the test process. Both set `sys.pycache_prefix = os.devnull` and `sys.dont_write_bytecode = True` at module level, and the test never restored them. Discovery runs that module first, so the later tests built `/dev/null/…` cache paths. The failure reproduces on a tree exported from `d46d48c`. The earlier 952-test gate ran before that module existed. The owner chose to fix it on this branch (plan Decisions R3). Commit `93038fe` saves and restores the two values around each in-process script load and adds three regression tests. Investigation: `.sdd/…/gate-errors-report.md`.

## Test counts
`main` loads 999 tests in 62 modules (plan F-P6). The branch adds `test_workflow_drain.py` and `test_release_origin.py` (2 modules) and tests in `test_config.py`, `test_local_launcher.py`, `test_workflow_cli.py` and `test_acceptance_selection.py`. Total 1020 in 64 modules.

## Checks of `main`
- `main:pyproject.toml` has `members = ["packages/sec-edgar-ingest"]`. No platform member.
- `git diff 3ca50c7 HEAD -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml` is empty.
- `main` is still at `d46d48c`, the merge base.
