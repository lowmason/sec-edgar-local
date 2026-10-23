# Two-release behaviour (Stage 1a, plan 4 Task 7)

**Tests:** `packages/sec-edgar-ingest/tests/test_release_origin.py`, 3 tests, OK on 2026-10-23, branch `stage1a-bounded-drain`. The production code under test is `packages/sec-edgar-ingest/src` at `c414519`. It has not changed since `51221e4`. The tests are the version in the commit that adds this text. A commit cannot name its own SHA.
**Origin release:** `support_release.origin_release` builds revision `3ca50c7` (the `fc68adef…` source revision). Comparison with the retained `fc68adef…` manifest:

```json
{
 "origin_release_id": "edb3f40e68fa17bf0395a94cc5bc197531fbc51970effa8b126de98e28f93385",
 "git_revision": "351435a656b5c0d22a742712def161e7223d6f06",
 "package_files_equal": true,
 "application_wheel_sha256_equal": true,
 "dependencies_equal": true,
 "uv_lock_sha256_equal": true,
 "interpreter_equal": true
}
```

`git_revision` is not `3ca50c7…`, and the release ID is not `fc68adef…`. Release identity covers the Git revision (plan P6). `origin_release` extracts `3ca50c7` and commits it into a new throwaway repository. So the identity records that repository's commit. Each build makes a new commit, so these two values change on every build. The five equality results do not depend on the commit. Both application wheels have SHA-256 `6ab438e5…fd0f`.

> Deviation: the plan runs Step 4 and Step 5 with `uv run --offline --locked`. In the worktree they ran with the shadow venv `/tmp/drain-venv` (plan Task 5 deviation). The retained manifest was read with the Read tool and copied to a temporary file. The copy hashes to release ID `fc68adef…` under `runtime.release_id`, so the copy is exact.

## Results
1. The current code continues `fc68adef…`-origin pending work. These are the facts the test asserts:
   - An origin run halted on a 403 and left two pending members, one for each source.
   - The current run's discovery added one member for each source. So each source had one origin member and one current member in the frozen selection.
   - One current run completed both sources. For each source, `collect`, `transform` and `publish` each ran once.
   - The first member of each source ran the child sequence. Its `collect` ran on the release that discovered it. Its `transform` and `publish` ran on the current release.
   - The other member got the B4 receipt: a complete outcome, no child refs, and no snapshot or transformed ref.
   - The order of the two members is not fixed (plan Decisions R2). `member_id` hashes the discover child's wall-clock `started_at`, and no input reaches that value. If an origin member sorts first, its `collect` runs on the origin release. If no origin member sorts first, no child runs on the origin release. The test checks each branch.
2. `fc68adef…` reads a B4 receipt as corrupt. A later origin-release run reported one `legacy_member_unresolved` gap for each B4 member. Each gap message starts with `retained completion receipt is corrupt`. The run ended `incomplete` (exit 3).
3. `fc68adef…` refuses a config that carries `execution.dispatch_reserve_seconds`. Stderr contains `ExecutionSettings unknown keys: ['dispatch_reserve_seconds']`.
   - Inference (not tested): receipts, child results and contexts written under a D5 live config carry that config. If so, `fc68adef…` cannot validate them either.

## Consequence for §4.9
After a D5 live run has written to a store, selecting `fc68adef…` again for that store is unsupported. This follows from result 2. Result 3's inference supports it. Task 11 records this limit in the parent spec §4.9.
