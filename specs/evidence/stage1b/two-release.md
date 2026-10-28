# Two-release behaviour (Stage 1b, plan 5 Task 8)

**Tests:** `packages/sec-edgar-ingest/tests/test_release_1b.py`, class `D5OriginTests`, 2 tests, OK in 3 of 3 runs on 2026-10-28 (UTC), branch `stage1b-per-member-cost`. The production code under test is `packages/sec-edgar-ingest/src` at `80bd84d`. The test files are those at commit `d104663`.

`D5OriginTests` inherits plan 4's `OriginReleaseTests` and replaces only `setUpClass`. Two inherited tests are switched off, because they encode `fc68adef…`-only behaviour: `test_origin_release_reports_a_b4_receipt_as_unresolved` and `test_origin_settings_refuse_the_reserve_key`. D5 reads a B4 receipt. `test_d5_runs_again_on_a_store_that_1b_wrote` covers that half: its D5 run reads the two B4 receipts that the 1b run wrote. D5 also accepts the reserve key. This module does not test that half, because its test is switched off. It comes from reading D5 `config.py:111` (`dispatch_reserve_seconds: int | None = None`). Each run collected 2 tests, so the switch-off worked.

## Inputs
- D5 source revision: `d68787fe8602e9d81a26d2012feec9bfad5c52df` (`support_release.D5_REVISION`). The retained D5 release is `aa8de1ac09fa8ef1a8f638301b25c370af5222e9ef0b02fd117866c2260a6ab4`.
- Origin release: `support_release.origin_release(..., revision=D5_REVISION)` extracts the D5 revision with `git archive`, commits it into a new throwaway repository and builds it.
- Current release: release B of `support_release.proof_releases`, built from a committed snapshot of this branch.

Release IDs that each run built:

| Run | Origin release ID (`cls.origin.release_id`) | Current release ID (`cls.current.release_id`) |
|---|---|---|
| 1 | `98886a74b23225e7405b6e96beed0b7e71700d8120b3e339c0ca70550ff46ccd` | `a3461ec9d3230eafec0f3575ae0dbdaf1cdd2c2cc4da63dd200d921ffdb06ce8` |
| 2 | `766309cd80555852b847b5d01dd98250c1581641f7768782f9306378bf68ff8d` | `67bd571424a433395284d43cf96f3c5bc2095de3ebfb2349e7ffe16e2752a4e6` |
| 3 | `f4736bdace18e24b77ec541626e5e037b1fa8422b2e3f00e45969b809cee0ae6` | `ed9edc79a107cbf42b145f55ebf114bc4b1beeb97a64369c02ce3691cc9a4897` |

The origin release ID is not `aa8de1ac…`. Release identity covers the Git revision (plan 4 P6), and each build commits into a new repository. So both IDs change on every build. In each run, the watcher's copy of the origin identity was compared with the retained `aa8de1ac…` manifest by a script outside the test. This comparison is not a test assertion. Only `git_revision` differs. `application`, `application_wheel_sha256` (`5d544087…3b4b`), `dependencies`, `interpreter`, `package_files` and `uv_lock_sha256` are equal. So the origin runs the D5 application payload.

> Deviation: the IDs were not printed from the test. A watcher script outside the repository copied each new `releases/sha256=<id>/release.json` and the throwaway repository's `git log` while the test ran. The current release is the proof release whose `git_revision` is the "snapshot B" commit. The 1b generations in each run carry this ID as `runtime.release_sha256`. So no debug print entered the test code.

## Results
Command, from the worktree root, run three times one after another:

```bash
SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache /tmp/s1b-venv/bin/python packages/sec-edgar-ingest/tests/network_guard.py test_release_1b -v
```

| Run | `test_current_code_continues_origin_pending_work` | `test_d5_runs_again_on_a_store_that_1b_wrote` | Result line | Origin-first count |
|---|---|---|---|---|
| 1 | ok | ok | `Ran 2 tests in 58.139s` / `OK` | 1 |
| 2 | ok | ok | `Ran 2 tests in 58.465s` / `OK` | 0 |
| 3 | ok | ok | `Ran 2 tests in 58.883s` / `OK` | 0 |

The origin-first count is the number of sources (of 2) whose first member in the current selection was discovered by the origin release. It is for the scenario of `test_current_code_continues_origin_pending_work`. The watcher read it from that scenario's two `selection.json` files. The scenario that `test_d5_runs_again_on_a_store_that_1b_wrote` builds had counts 0, 0 and 2.

1. The 1b code continues D5-origin pending work. These are the facts the test asserts:
   - A D5 run halted on a 403 (`access_blocked`) and left two pending members, one for each source.
   - One 1b run completed both sources (`success` or `unchanged`). For each source, `collect`, `transform` and `publish` each ran once.
   - `transform` and `publish` ran on the 1b release. `collect` ran on the release that discovered the member.
   - The later member of each source got a B4 receipt with no child refs.
   - In run 1, one source's first member was a D5 member. Its `collect` ran on the D5 release. In runs 2 and 3, no child ran on the D5 release in this test. The test checks each branch.
2. D5 runs again on a store that 1b wrote. After the 1b run, a D5 backfill (`d5-again`) on the same store exited 0 with outcome `success` or `unchanged`. That is what the test asserts. The watcher also captured these facts:
   - Run 3's `d5-again` result was `unchanged`.
   - In runs 1 and 3 (watcher), the `d5-again` selection held 0 jobs, no gaps and 2 `already_complete` entries, one for each source. Each entry captures one quarter's generation (2026Q3 and 2026Q4). The captured generation IDs are the ones that the 1b release wrote.
   - The watcher missed run 2's `d5-again` files, because the scratch store was removed before its next copy. So these facts are not recorded for run 2.

   The following comes from reading the D5 code (`d68787f`), not from a test assertion:
   - D5's `select_work` (`workflows/runner.py:184–206`) passes every retained member to `WorkflowMembers.completed` (`workflows/members.py:131–161`). That method reads each member receipt, checks its hash and correlation, and validates its completion capture. A failure there becomes a `legacy_member_unresolved` gap ("retained completion receipt is corrupt"). The selection had no gaps in runs 1 and 3 (watcher). So in those runs D5 accepted the two 1b success receipts and the two B4 receipts.
   - The `already_complete` entries come from `evaluate_member` (`workflows/runner.py:262`, `workflows/completion.py:794`). It captures each affected quarter through `capture_quarter` and `validated_manifest` (`completion.py:821–825`). `validate_capture` (`completion.py:389–428`), which `completed` runs, also calls `validated_manifest` for each captured quarter. `validated_manifest` runs D5's full content check (`validate_candidate`). So D5 fully checked the 1b-written generations.
   - This record does not show that D5 read the 1b child results.

## Consequence for §4.9
The 1b release continues D5-origin pending work. Selecting the D5 release again is supported for a store that holds 1b first-generation (full-rebuild) generations and 1b and B4 receipts. This was tested once, on fixture packs. D5 reading an incremental 1b generation is not tested here. It rests on §5 item 3 (byte identity). A D5 publish on top of a 1b generation is also not tested here.

## Limits of the proof
- Order-aware checks (plan 4 R2). Member order is not pinned. So a single run proves one branch. When no origin member sorts first for a source, no child runs on the D5 release for that source. In runs 2 and 3, `test_current_code_continues_origin_pending_work` proved only that the 1b release completes both sources and that B4 completes the later members. Each branch is asserted in both directions, so neither branch hides a failure.
- Full-rebuild generations only. The watcher captured the generation manifests of all 6 scenarios (2 tests × 3 runs). In each, each quarter got one 1b generation with `base_generation_id: null` and one source. No 1b publish took the incremental path. So D5 saw only full-rebuild generations from 1b. The claim that D5 also accepts an incremental generation rests on §5 item 3: an incremental generation is byte-identical to the full rebuild. No two-release test publishes an incremental generation.
- D5 published nothing new on top of the 1b store. In runs 1 and 3 (watcher), the `d5-again` run found every member complete. It dispatched its `discover` child and no `collect`, `transform` or `publish` child. Run 2's `d5-again` files were not captured. So no test proves that a D5 publish builds on a 1b generation.
- No test runs D5 after a live 1b run, because this stage allows no live run. The tests use fixture packs only.
