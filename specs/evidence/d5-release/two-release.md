# Two-release behaviour (Stage 1a, plan 4 Task 7)

**Tests:** `packages/sec-edgar-ingest/tests/test_release_origin.py`, 3 tests, OK on 2026-10-23, branch `stage1a-bounded-drain` at `393d3c0` plus the Task 7 commit that adds these tests.
**Origin release:** built from revision `3ca50c7` (the `fc68adef…` source revision) by `support_release.origin_release`. Equivalence to the retained `fc68adef…` manifest:

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

The origin release ID and `git_revision` belong to one build. Each build makes a new throwaway commit, so these two values change from run to run. The five equality results do not depend on the commit. Both application wheels have SHA-256 `6ab438e5…fd0f`.

> Deviation: the plan runs Step 4 and Step 5 with `uv run --offline --locked`. In the worktree they ran with the shadow venv `/tmp/drain-venv` (plan Task 5 deviation). The retained manifest was read with the Read tool and copied to a temporary file. The copy hashes to release ID `fc68adef…` under `runtime.release_id`, so the copy is exact.

## Results
1. The current code continues `fc68adef…`-origin pending work. An origin run halted on a 403 and left two pending members. One current run completed both sources, with each child sequence once. Two members completed with no child (the B4 shape). Each collection step stayed bound to the release that discovered its member: an origin-discovered member collects on the origin release, and a current-discovered member collects on the current release. Transform and publish ran on the current release. The test does not fix which member of a source runs the child sequence, so it does not require that an origin-discovered member is collected.
2. `fc68adef…` reads a B4 receipt as corrupt. A later origin run reported `legacy_member_unresolved` for each B4 member and ended `incomplete` (exit 3). This is the plan's prediction, and the run confirmed it.
3. `fc68adef…` refuses a config that carries `execution.dispatch_reserve_seconds` (stderr contains `unknown keys: ['dispatch_reserve_seconds']`, raised by the record check in `models.py` at `3ca50c7`). So it cannot validate any receipt, child result or context written under a D5 live config, because those configs carry the key.

## Consequence for §4.9
After a D5 live run has written to a store, selecting `fc68adef…` again for that store is unsupported. Task 11 records this limit in the parent spec §4.9.
