# Milestone 2: pure runtime and release identity contracts

Task 2 checkpoint, 2026-10-17. This covers descriptor/manifest identity validation only. Installed integrity, release setup, command-mode authorization, and live SEC acceptance remain later gates. No SEC requests, filesystem access, installation, or process execution occur in these runtime functions.

`runtime.py` supplies `validate_descriptor`, `fixture_descriptor`, `native_descriptor`, `release_id`, and `validate_manifest`. The descriptor variants use exact closed keys and lowercase SHA-256 values. Fixture provenance independently hashes canonical JSON containing only the explicit safe nonempty fixture ID. The native manifest has exactly `format_version`, `release_id`, and `identity`; every nested record also requires exact fields. The identity includes the application wheel, committed Git revision, sorted unique application payload paths, lock hash, sorted unique normalized dependency inventory, and interpreter identity. Unknown metadata, timestamps, installation paths, unsafe artifact names, cache/bytecode payload paths, missing hashes, and mismatched digests are refused. Return values are detached copies, including nested manifest containers.

Historical manifest validation checks the saved native format and application name/version/wheel agreement without comparing to the executing package's `__version__`. A saved `0.2.1` application manifest validates while this checkout is `0.2.0`. There is no invented numeric version allowlist. New release creation later must enforce current application `0.2.0`; historical compatibility follows the supported manifest/envelope contracts. Application and dependency versions use canonical version spelling, including canonical prerelease/postrelease/development/local components; leading numeric zeroes and redundant zero epochs are refused.

The interpreter interface uses `implementation=cpython`, a full stable `3.14.<patch>` version, `cache_tag=cpython-314`, and a wheel-style `platform_tag=macosx_<major>_<minor>_arm64`. The macOS numbers are not pinned to one deployment target. Linux and x86 tags are refused. Future build/preflight code must derive and compare the actual supported host identity using this convention. This pure validator checks declared identity, not the running host or installed files.

The module imports existing `models.canonical_json`, `parse_json`, `require_hash`, `require_text`, and `safe_relative_path`. It adds no reverse import in `models.py`. Later model integration must avoid a top-level reverse import cycle.

## Red/green evidence

Every cycle used this required guarded command at the repository root:

```sh
for test_file in test_runtime.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

1. Descriptor RED: exit 1, `Ran 7 tests`, `FAILED (failures=7)`. Each failed the intentional assertion `Task 2 requires pure runtime descriptor contracts` because `sec_edgar_ingest.runtime` did not exist. Descriptor GREEN: exit 0, `Ran 7 tests`, `OK`.
2. Manifest RED: exit 1, `Ran 21 tests`, `FAILED (failures=14)`; all 7 descriptor tests stayed green. The 14 new tests failed the intentional assertion `Task 2 requires canonical native release identity` because `release_id` was absent. After implementation, one test-helper defect surfaced: `manifest(None)` accidentally selected the default valid fixture. Reading the trace and helper isolated that cause; switching the helper default to an explicit sentinel preserved the deliberate JSON-null input. Corrected GREEN: exit 0, `Ran 21 tests`, `OK`.
3. Canonical-version boundary RED: exit 1, `Ran 23 tests`, `FAILED (failures=2)`. Both intentional subtest failures reported `ValueError not raised` for `0!0.2.0` and `0.2.0+01`, with matching wheel filenames to isolate version validation. Restricting epoch/local numeric spelling produced GREEN: exit 0, `Ran 23 tests in 0.008s`, `OK`.

The final passing suite covers exact descriptor formats/kinds/keys; non-string/list/object/bool/null refusal; cross-kind mismatch; lowercase 64-hex hashes; fixture ID safety; independent canonical hashing; nested exact manifest objects; detached copies; canonical object-key ordering; digest changes for wheel, lock, Git revision, payload file, dependency artifact, and interpreter changes; safe/sorted/unique payload and dependency inventories; malformed and mismatched application wheels; historical saved versions; supported interpreter/platform shapes; and timestamp/host-path exclusion.

## Environment and scope verification

- macOS 26.6.2 arm64, native filesystem.
- uv `0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin)`.
- Workspace interpreter CPython `3.14.0 (main, Oct 14 2025, 21:10:22) [Clang 20.1.4]`.
- No dependency, interpreter, backend, or lock changes. No build ran for this pure-library task. Task 1's declared backend remains `uv_build>=0.12.15,<0.13.0` with exact setup backend `0.12.24`; it is not installed in the application environment.
- First un-escalated test attempt exited 2 because uv could not create its cache lock temporary file under `/Users/lowell/.cache/uv`. Approved cache access allowed all guarded offline red/green runs; no network was enabled by the application guard.

Self-review read the complete new runtime module and checked the task's contract list against the tests. Applied clean-code rules: N1/N4 for explicit identity/artifact names; G30 for cohesive descriptor, record, and inventory validators; G25 for named identity fields and validation patterns; F2 for detached return values; T1/T5/T6 for strict shape/path/hash/version boundaries; C3 for retaining the historical-version design intent. No adjacent cleanup was undertaken. `git diff --check` passed before staging. Only Task 2 runtime/tests/evidence files are part of the commit. Installed wheel/preflight verification is intentionally deferred to Task 7.


# Task 3 checkpoint: strict configuration and one native local store

Task 3 completed its configuration/factory checkpoint on 2026-10-17 against base `0ebae8955f45066b345524c0a863978e785750dc`. It does not claim command or installed-release readiness. Task 4 retains the context/pin/CLI migration and complete `test_config.py` gate; those old context builders still refer to worker image fields at this checkpoint.

## Actual interfaces and policy decisions

- `Settings` now contains the exact `acquisition`, `storage`, `runtime`, `logging`, and `execution` groups. `config_version` is independently `sec-local-config-v1`. Storage has only `backend=local` and a filesystem `root`. The native/fixture runtime dataclass union uses the existing strict decoder; opposite-variant fields are absent, including when a caller tries to supply null. Azure fields and worker/jobs/orchestration groups are rejected. `load_config_env` is removed.
- `parse_config(text)` validates structure and policy without path expansion or manifest reads. `load_config(path)` validates completely, then `normalize_paths(settings, path.resolve().parent)` expands home paths and resolves storage root, logging root, and native release-manifest path. Parent paths and absolute filesystem paths are valid. Logical object-key validation is unchanged. The factory requires an absolute normalized settings root; it has no `base_path`, credential, or provider fallback.
- `Settings.to_mapping()` omits an absent fixture group, allowing a live normalized mapping to replay unchanged. A supplied null fixture group is rejected; only the two boolean override keys are accepted. Existing false defaults inside a supplied fixture group remain false. Live rejects any supplied fixture group, even an empty object or false override.
- Live uses the exact accepted HTTP values 5/2/120/15/60/90/67108864/536870912, exact 60-second lease/20-second renewal/2-second uncertainty and namespace, `execution.max_run_seconds=3600`, native runtime, and `sec-index-parser-v1`. The owner identity and one active collector are fixed; positive request rates at or below 3 remain valid. Fixture acquisition permits native or fixture runtime, safe explicit parser aliases, positive lower HTTP bounds, finite lease values at or below 60 with positive renewal below expiry, uncertainty in 0..2, and a positive integer execution allowance. Individual clock/deadline override authorization is consumed by Task 4 pinning; this task does not weaken it.
- `runtime.configured_descriptor(settings)` returns an independently hashed fixture descriptor or reads and strictly validates a native manifest. It requires an absolute manifest path, resolves symlinks, verifies the resolved `releases/sha256=<id>/release.json` address, and checks the directory digest against the validated canonical manifest identity. It performs no installation, network, store open, or subprocess work. Historical saved-version validation remains independent of the executing package version.
- `deployment_binding(settings=None, *, root=None)` emits exactly `binding_version=sec-local-binding-v1`, resolved `root`, `acquisition_mode`, fixed `namespace`, normalized `sec`, normalized `coordination`, and `storage_contract=sec-local-storage-v1`. Settings-free constructors require an explicit root and use fixture mode/default accepted policies. Explicit-root calls remain available as specified; factory calls use only normalized settings. Range, parser, release, and command IDs do not enter binding. Changed root/mode/shared policy and legacy registries conflict unchanged, before creating a database.
- `table_for` preserves `ActivePointers`, `Approvals`, `Attempts`, and `SourceState` as SQLite state categories. `blob_address` and cloud routing are removed. Native SQLite CAS/locking/retry, WAL/SHM handling, sentinel journal semantics, symlink defenses, filesystem atomicity and fsync algorithms are unchanged.
- `fixture_settings(root=...)` builds the new map and normalizes paths; factory tests supply absolute temporary roots. `fixture_snapshot` directly uses the same `2026-10-06T00:00:00+00:00` specimen time rather than constructing a context. The existing `tree_snapshot` implementation moved unchanged to `support_fs.py`, imported by `support_approval` and `test_operator_open`. Local factory tests now load without CLI or Azure imports. Public command tests are retained for later tasks.
- `Settings.config_sha256` hashes the canonical effective normalized mapping. Tests independently preserve/hash source bytes and show that differently formatted/source-relative JSON can have different input hashes but identical normalized effective hashes. No input-hash metadata was added to serialized Settings. The later invocation archival consumer must read the original bytes and archive its input SHA-256 separately, as required by Task 11.

## Task 3 red/green evidence

Commands ran from `/Users/lowell/Projects/sec-edgar-local`. Each config cycle used:

```sh
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_local_config.py -v
```

1. Initial un-escalated attempt exited 2: `Could not acquire lock`, `Operation not permitted` creating `/Users/lowell/.cache/uv/.tmpWICvGB`. This was tooling setup, not accepted as RED. Approved uv cache access enabled subsequent offline runs.
2. Supplied config RED: exit 1, `Ran 13 tests in 0.003s`, `FAILED (failures=13)`. Every test intentionally asserted the missing Task 3 contract after the current Settings refused `acquisition`, `execution`, `logging`, and `runtime` as unknown keys. After adding binding cases, RED was exit 1, `Ran 19 tests in 0.005s`, `FAILED (failures=19)` for the same intentional missing contract. Implementing strict settings, normalization, local binding and local-only factory produced GREEN: exit 0, `Ran 19 tests in 0.120s`, `OK`.
3. Configured descriptor RED: exit 1, `Ran 24 tests in 0.115s`, `FAILED (failures=5)`; the prior 19 tests stayed green. The five new tests intentionally asserted missing `configured_descriptor`. Minimal read-only descriptor implementation produced GREEN: exit 0, `Ran 24 tests in 0.127s`, `OK`.
4. Self-review found that checking only the lexical absolute manifest address could admit a symlink to a file outside the required release address. Added the real-filesystem regression first. RED: exit 1, `Ran 26 tests in 0.131s`, `FAILED (failures=1)`, exact failure `ValueError not raised`. Resolving and revalidating the release address produced GREEN: exit 0, `Ran 26 tests in 0.131s`, `OK`.
5. The actual-cwd and legacy-registry assertions strengthen already-implemented invariants: two real cwd changes with relative config filenames resolve the same original paths; a legacy registry remains byte-identical and prevents database creation.

The exact required final factory gate was:

```sh
for test_file in test_local_config.py test_storage.py test_operator_open.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

Final output: exit 0; `Ran 26 tests in 0.129s`, `OK`; `Ran 14 tests in 0.688s`, `OK`; `Ran 5 tests in 0.045s`, `OK` (45 total). One earlier premature gate attempt followed a setup script stopping because `conf/` was absent, so the operator import extraction had not run: config 24 and storage 14 passed; operator import failed with `ModuleNotFoundError: No module named 'azure'`. This was not RED evidence. Created the required conf directory, completed the prescribed extraction, and reran the entire gate successfully before further work. The factory suite no longer imports the old cloud class.

The changed runtime module also received this regression command:

```sh
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_runtime.py -v
```

Final output: exit 0, `Ran 23 tests in 0.007s`, `OK`. No SEC requests or source-repository mutations occurred. Complete default checks/builds and genuine L12 are later release gates and were not claimed here.

## Task 3 environment and self-review

The native environment remains Darwin arm64, uv `0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin)`, CPython `3.14.0 (main, Oct 14 2025, 21:10:22) [Clang 20.1.4]`, installed application `0.2.0`, Requests `2.34.2`, and PyArrow `25.0.1`. No interpreter, dependency, backend or lock changes. No build ran. The declared backend remains `uv_build>=0.12.15,<0.13.0`; Task 1's exact setup backend was `0.12.24` and is not installed in the application environment.

Self-review read the changed production functions and tests against the brief, including final resolved-path validation, canonical policy equality, failure-before-DB creation, lease sentinel preservation, and context/CLI deferral. Clean-code applications: G30/G34 for separating supplied validation, path normalization, configured provenance and persistence binding; N1/N4 for acquisition/runtime/path naming; G25 for accepted policy constants; F2 for detached normalized return values; T1/T5/T6 for closed union/JSON/policy/path/replay/binding boundary tests; C2/C3 for updating obsolete fixture/cloud comments while preserving the SQLite WAL and fsync design intent. No adjacent cleanup was undertaken. `git diff --check` passed after removing the extra newline left by the helper move. Only Task 3 owned paths are staged. The ignored `.sdd` report remains local execution evidence.


# Task 3 review fix round 1: refuse registry-less durable state

The Important finding in `.sdd/1-sec-edgar-local-spec/task-3-review.md` was verified before implementation under the receiving-code-review procedure. The original object constructor wrote a missing registry before the state constructor opened an existing database. Three new real-filesystem regressions reproduced adoption of an unbound database with a retained row, an unbound object tree, and a previously bound store whose registry was deleted.

`LocalObjectStore` now opens the resolved root directory with the existing no-follow directory flags and holds native `fcntl.flock(LOCK_EX)` from registry inspection through fresh registry publication. Closing that descriptor releases the lock. No lockfile or other guard artifact is created. A present matching registry is read and verified; a mismatched registry still conflicts. When the registry is absent, any database, WAL/SHM/rollback-journal file (including a dangling symlink at a SQLite state path), or nonempty object directory conflicts before object-directory creation or database access. An absent/empty root or empty object directory may initialize. Existing object-directory symlinks and non-directory object roots are refused under the serialized bootstrap. There is no cleanup, rewrite, migration, or adoption path.

All local constructors already enter `LocalObjectStore` before creating SQLite/object durable state. Therefore concurrent constructors serialize while the first binding is unpublished, and later constructors see that published binding before opening SQLite. This is an atomic bootstrap protocol for the supported native macOS filesystem; it relies on native advisory directory flock support, exercised on this Mac. It does not replace leases, CAS, SQLite locking, filesystem atomic writes or fsync; those algorithms remain unchanged. No shared-filesystem or Windows support is claimed.

The new deterministic concurrency test pauses the first publisher after creating registry parent directories, observes a second thread attempting the real root flock, confirms that second initialization has not completed before publication is released, then proves both opened stores share the same retained row. Events and bounded waits coordinate exact transitions; there is no scheduling sleep. Additional tests cover fresh empty-directory initialization/reopen, standalone SQLite sidecar refusal with unchanged bytes, and object-root symlink refusal without database creation. Existing WAL contention tests now establish a legitimate binding before holding a competing empty SQLite database; their original wait/timeout/SQLite-BUSY assertions remain. The operator missing-registry/missing-database matrix uses separate fresh roots because the prior matrix silently recreated the deleted registry between cases, the very behavior being removed.

## Review-fix exact evidence

Focused RED command, repository root:

```sh
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_local_config.py -v
```

After explicitly closing the SQLite test-seeding connection (the first test attempt exposed a test ResourceWarning), the clean RED was exit 1: `Ran 29 tests in 0.141s`, `FAILED (failures=3)`. All three failures were `AssertionError: Conflict not raised`, and the prior 26 tests stayed green. The minimal serialized-bootstrap implementation produced config GREEN: `Ran 29 tests in 0.127s`, `OK`, and existing storage `Ran 14 tests in 0.644s`, `OK`. The initial combined gate then exposed the operator matrix's unsupported registry-recreation setup (one error); its independent-root correction retained both refusal assertions. This setup error was not additional RED evidence.

Final exact covering command:

```sh
for test_file in test_local_config.py test_storage.py test_operator_open.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

Final output: exit 0; `Ran 29 tests in 0.123s`, `OK`; `Ran 18 tests in 0.664s`, `OK`; `Ran 5 tests in 0.043s`, `OK` (52 tests). The unbound database test verifies both unchanged complete tree/file hashes and the original SQL key/value/revision; the object and deleted-registry tests verify unchanged trees. `git diff --check` also passed. No SEC/network, source-repository mutation, dependency change, broad cleanup, or subagent work occurred. Task 4 and later deferred gates remain as recorded above.

Self-review checked creation order, root/objects no-follow defenses, the missing-registry branch before mkdir/SQLite, descriptor closure on success/failure, and the actual concurrent initialization boundary. Applied clean-code rules: G30/G34 for the cohesive locked binding bootstrap, G19 for explicit existing-database/object predicates, G25 for SQLite state-file names and named bounded test waits, T1/T5/T6 for missing/damaged/racing initialization invariants, and C3 for the lock scope and publish-before-state design intent. Only `storage/local.py`, the three targeted test modules, and this evidence are part of the review-fix commit.

## Task 4 - local acquisition provenance implementation (review pending)

Base `2d7134b2bd5c8ba1436d83b043cce7dbec3df888`, destination branch `codex/local-design`. RunContext now requires `sec-local-run-context-v1` plus immutable validated runtime mapping; CommandResult independently requires `sec-local-command-result-v1`; acquisition worksets use `sec-local-acquisition-v1`. Attempt keys, receipt/collector/staged-recovery comparisons, CLI retries, ETL runtime fields and workflow exact-context comparisons all consume detached runtime descriptors. Source/snapshot identities, canonical hash rules, origin-vs-current contexts, deadlines/IDs/intents, raw/envelope contracts and approval shapes are preserved.

Initial schema RED isolated under network_guard: `.venv/bin/python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_local_acquisition_contracts.py -k context_requires -v` -> exit1, one failure, `AssertionError: 'runtime' not found` in RunContext fields. Default uv cache was sandbox-protected, so mandatory uv commands use `UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache`; this succeeds offline with the existing environment. Required final command (root):

```sh
for test_file in test_local_acquisition_contracts.py test_worksets.py test_config.py; do
  UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

Output: exit0 for each; 9 tests/0.110s, 20/0.408s, 12/0.199s, all OK (41 total). Additional same guarded invocation by file: state11/0.197s; discovery43/8.376s; collection38/7.911s; CLI25/55.859s; checked-workflow13/32.086s; runtime23/0.006s; local-config29/0.123s; storage18/0.650s; operator-open5/0.054s; all OK. Two final CLI test-helper root adjustments received fresh affected-case checks (4 result tests and 1 result-conflict test, all OK). All 41 retained runtime modules import under the offline guard, including CLI/__main__. A CommandHarness real fixture discover/collect smoke confirms normalized temporary-root config equality with the actual store. Required source rg for `image_digest|IMAGE_PATTERN|settings\.worker|settings\.jobs|settings\.orchestration` has no matches; `git diff --check` passes.

The checked workflow RED isolated an actual frozen-Mapping-vs-dict error at unfinished-child recovery; both sides now serialize before exact runtime comparison. Focused repair test and full13 checked cases pass. Collection fixture cases now construct worksets with their actual temporary-root context; strict production provenance comparisons were retained. CLI provider imports/options/credential branches and cloud execution lookup are removed; fixture transport/parser selection uses acquisition.mode; explicit correlation and actor labels are local audit inputs. Internal Dispatcher state_dir positional slot no longer controls a store or emits an option; all store paths come from normalized settings.

Clerical ownership deviation approved by controller: test_config.py was omitted from Task4 Files but explicitly required by its Step2/3 gate; its old provider/worker cases were ported to local/live/runtime/path semantics with strict JSON/pin/deadline/immutability coverage retained. Existing local fixture JSON already met Task3 settings and needed no change. support_workflow_evidence inherits the normalized DiscoveryHarness config, so no direct edit was required. Complete commands, RED/green details, excluded zero-test diagnostic typo, self-review and limits are in `.sdd/1-sec-edgar-local-spec/task-4-report.md`.

No live HTTP, source-repository mutation, dependency/build-backend change, release installation, compatibility alias, parser relaxation, raw-fixture change or acceptance claim. Tools remain uv0.13.1 and CPython3.14.0. Historical Minor T1-M1 backend-fast-path warning remains for Task7/13/final review. This is Task4 scoped implementation evidence, not Milestone2 or full-suite/native-current readiness: Tasks5-7 and independent review remain.

## Task 4 review fix round 1 - T4-I1 (scoped re-review pending)

Review reproduced a real fixture-oracle gap: DownloadHarness accepted a supplied default-root context or later replacement while using temporary-root settings/stores; ETL callers omitted their actual root. Six new regressions produced clean RED15 tests/failures4/errors0 (`ValueError`/`TypeError` not raised). DownloadHarness now refuses mismatched settings before opening stores and validates exact context/config/root provenance on construction and later assignment, preserving valid context objects/IDs/deadlines. etl_context requires an explicit non-None root. All retained ETL callers, re-pins, sub-stores and proof membership stores now pass their existing actual addresses; store-backed loopback/process helper settings pass their `state` address. No provenance is silently rewritten.

Final guarded required core: local-acquisition15/0.163s, worksets20/0.411s, config12/0.193s, all OK. All48 retained non-cloud download cases pass:34 selected classes/methods in1.851s;14 genuine bounded process/loopback cases in26.936s under approved localhost sandbox escalation with network_guard still active. The exact selected34 command names DownloadTests, PolicyHandoffTests, PartialExceptionTests, ExceptionTextTests, and DurableRequestAuditTests.test_two_independent_state_clients_cannot_consume_the_same_ordinal. Full unfiltered download49 diagnostics had19 localhost bind EPERM subcase errors in the sandbox plus the unchanged obsolete Azure-only method importing missing test_azure_contracts. Controller explicitly leaves that one method unchanged for Task10; it is not reported green and no skip/removal was added.

All20 ETL transform methods other than unchanged test_image_change_adopts_original_producer_manifest_even_when_forced pass in2.257s. Full unfiltered21 diagnostics have solely its preexisting worker/image KeyError; controller retains it as Task5's migration oracle. Ten affected helper/caller modules import; three actual store fixtures plus approval/proof re-pins assert archived root/config hash matches actual settings/store. AST audit confirms every retained etl_context caller passes root outside the deliberate refusal regression. No full broader future-task suites, outer-format/provider retirement, source mutations, genuine SEC requests or acceptance claims.

Controller accepted T4-M1's four no-op exemptions: worksets.py/results.py consume new strict records/constants; local.json was already migrated; support_workflow_evidence derives the corrected normalized discovery settings. Root caller ownership was explicitly extended for mechanical changes in test_download, test_etl_transform, test_etl_catalog/publication/cli, support_approval, test_reconcile_workflow and etl_proof. Their unrelated old runtime/CLI behavior remains for later owners. Complete exact commands, clean RED, excluded diagnostic failures, green outputs, self-review and limits are appended to `.sdd/1-sec-edgar-local-spec/task-4-report.md`. `git diff --check` passes. Historical T1-M1 remains unchanged.

## Task 5 - strict local ETL formats and retained producer identity (review pending)

Base `070d8d78b1b9e097e8172945436a7a11b66dbdfc`. Observation, transformed workset, generation and ETL result inventory writers/readers now use their independent `sec-local-*-v1` versions. Observation envelopes require exactly `{format_version,observation,runtime}`. `runtime.validate_producer(runtime, objects)` validates descriptor shape and, for native runtime, canonical saved release identity at `runtime/native/sha256=<release-id>/release.json` with exact digest/address agreement. Both historical observation `_read_manifest` and generation `read_manifest` call it without requiring current runtime equality or writing evidence. `runtime.retain_manifest(objects, manifest)` validates before canonical immutable publication and verifies saved readback; Task 8 owns its post-preflight storage-creation call.

Processing keys, observation refs, source fingerprints and generation IDs remain runtime-independent. Migrated runtime/force oracle retains exact original observation bytes; two new native release tests pin each context to its corresponding settings, use seeded raw/source binding and explicitly retained manifests, and prove ordinary/forced observation reuse plus generation no-op preserve original producer identity and bytes. Historical saved application0.1.0/interpreter3.14.1 records validate independently of the current0.2.0/3.14.0 environment. Missing, corrupt, noncanonical and mismatched native evidence fails at both reader boundaries. Existing Arrow/row/Parquet/quarantine tests remain. The Stage-2-store dependency was replaced by deterministic old-context/workset/binding refusal with unchanged before/after file-byte snapshots. Approval, activation, pointer, rollback and public capture/read shapes are unchanged.

Required guarded command, repository root, before and after implementation:

```sh
for test_file in test_local_etl_contracts.py test_etl_contracts.py test_etl_transform.py test_etl_catalog.py; do
  UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

Initial RED: local10 tests/failures9 (four old format values, old observation acceptance, missing explicit producer APIs); contracts11/errors1 (independent local-format workset hash mismatch against old constant); transform21 and catalog31 already OK after preserving/migrating runtime oracles. Expanded local native-cache tests then RED12/failures11 in0.413s, still intentional contract/API failures. The shell loop returns the last command's status; earlier per-file failures establish RED. Final required GREEN: local12/0.536s; contracts11/0.032s; transform21/2.380s; catalog31/30.740s, all OK (75 tests). Additional same guarded invocations: owned ETL CLI42/6.764s and runtime23/0.006s, all OK (140 tests total). CLI fixture migration removes its old `--state-dir` arguments and worker-image mutations, uses the local result version, and archives actual-root source-workset contexts; production CLI needed no change. `git diff --check` passes.

Self-review checked the scoped production/test diff, strict shape/canonical/hash/address validation, historical producer read-only behavior, validation-before-retention, immutable repeat/collision handling and actual native cache/generation behavior. Clean-code N1/N4, G30, F2, T1/T5/T6 and C3 applied within scope. No source repository mutation, HTTP, dependency/backend/lock change, release install or broad cleanup. Tools remain uv0.13.1 and CPython3.14.0. Full commands/output, no-op file rationale, self-review and limits are in `.sdd/1-sec-edgar-local-spec/task-5-report.md`. Independent review remains; Task6 workflow markers, Task7 installed preflight, Task8 retention hook, full-suite Milestone3, genuine SEC L12 and historical T1-M1 are not claimed complete.


## Task 7 - immutable native release setup and installed preflight (review pending)

Base `62f0701507011600499299ca90e9e127c406c8e4`, branch `codex/local-design`. Explicit `release.prepare_artifact_cache`, `build_release`, and `reconstruct_release` now separate network setup from read-only runtime verification. `runtime.preflight` validates portable artifacts and installed bytes, then runs the referenced Python with `-I` and a sanitized offline/no-download environment. `preflight_current` also requires the executing prefix, executable, actual imported module version/origin, exact distribution inventory, and full interpreter identity to match. The frozen `VerifiedRelease` carries the manifest, release ID, final directory and Python address. Historical `validate_producer` remains manifest-only and independent of current application/interpreter versions; the 12 local ETL producer/cache tests remain green.

The builder refuses tracked, staged, untracked and uncommitted source changes, checks the existing local lock offline, and builds/exports in an external temporary setup directory. It validates the original wheel basename, distribution/version/filename-vs-WHEEL tags, duplicate/escaping ZIP members, and sorted full package bytes including `py.typed` and resources. The identity includes the application wheel, committed source revision, payload, lock, every selected transitive runtime wheel, and CPython implementation/full patch/cache/platform identity. Installation paths, mtimes, setup logs and build tools are outside that identity. The release directory is created exclusively; complete matching installations are verified and reused without installing, and partial/conflicting installations are refused without overwrite or cleanup. Failed installation attempts retain evidence and receive no usable receipt.

Installation executes the three specified argv operations: `uv venv --python PYTHON FINAL/venv`; offline/no-index/find-links/require-hashes external requirements installation; and offline/no-deps application-wheel installation under its retained valid basename. All retained artifact hashes are rechecked before installation, and the app wheel is independently rehashed after dependency installation. The isolated self-check must succeed before `installation.json` is written. Reconstruction reads retained identity/artifacts independently of the old executable and creates a fresh venv directly at its new final address, preserving release identity and valid launcher paths. It never moves an existing venv.

### Contract-family reader/writer/hash/equality inventory

This closes the Tasks 2-7 implementation inventory; prior scoped gate evidence above remains the evidence for earlier families. Task 7 adds installed execution checks without making old producers depend on old executable availability.

| Family | Writer/reader | Hash and equality boundaries | Evidence |
| --- | --- | --- | --- |
| Runtime fixture/native descriptor | `fixture_descriptor` / `native_descriptor` / `validate_descriptor` | canonical fixture identity, strict variant fields and hashes | `test_runtime.py` 23 tests |
| Native manifest and retained producer | `build_release`, `retain_manifest` / `validate_manifest`, `validate_producer`, `retained_release` | canonical release digest; exact saved producer address; historical app versions independent of current | runtime23; local ETL12; release/preflight tests |
| Config and durable store binding | `Settings`, config normalization, `deployment_binding` / strict config and local-store open | effective config hash vs original input hash; exact normalized root/mode/issuer/policy/storage binding; no release/parser/range/ID coupling | Task3 config/storage/operator gates above |
| Run context, acquisition worksets and command results | strict models, workset/result writers and readers | independent local formats; exact runtime/context/attempt/result/workset hash/equality checks | Task4 acquisition/worksets/config gates above |
| Observation, transformed workset, generation and ETL result | Task5 strict codecs/writers/readers | independent local formats and canonical hashes; unchanged processing/fingerprint/generation identity; original producer preserved during cache/no-op reuse | Task5 gates above; local ETL12 rerun after Task7 |
| Workflow and child/completion/process evidence (all 34 inventoried families) | exact per-family readers/writers in `contract-inventory.json` | exact per-family hash/equality sites in that inventory; independent local contract marker | Task6 scoped review/gates; inventory unchanged by Task7 |
| Runtime artifact cache and external requirements | explicit `prepare_artifact_cache` / `_cache_inventory`, `verify_requirements` | lock/interpreter identity; sorted declared role/name/URL/hash inventory; exact complete applicable lock graph and exported hashes | release20 and preflight11 |
| Native installed execution and receipt | `_install` after isolated self-verification / `preflight`, `preflight_current` | retained wheel/lock/payload hashes; exact installed distribution set; noneditable origin inside resolved release venv; full interpreter identity; directory/receipt agreement | release20 and preflight11 |

Production-source audit `image_digest|IMAGE_PATTERN|settings\.worker|settings\.jobs|settings\.orchestration` has no matches. No image alias, cloud dependency/fallback, parser/schema change, SEC request, old-store import or automatic release cleanup was added. Existing approval/activation/rollback shapes remain unchanged.

### Explicit setup inventory and backend warning resolution

`releases/artifact-cache/artifacts.json` was prepared explicitly with public PyPI network access after a sandbox DNS refusal; no SEC access or Python download occurred. It records `sec-native-artifact-cache-v1`, the lock hash and full interpreter identity, and seven path-sorted declared artifacts (six runtime, one build). Every downloaded/cached wheel was SHA-256 checked, and the separate `uv-build` cache was populated from the verified build wheel. Later tests ran with `UV_OFFLINE=1`, `UV_PYTHON_DOWNLOADS=never` and `network_guard`; an absent cache is an explicit setup error.

Lock SHA-256: `e3d3dac9971ed75bdc5864ebd8c422c2e34bd24236a9a77bbadb6a87cddf1bbb`. Interpreter: `{"cache_tag": "cpython-314", "implementation": "cpython", "platform_tag": "macosx_26_6_arm64", "version": "3.14.0"}`. Tools: `uv 0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin)`, CPython `3.14.0`, backend `uv_build 0.12.24`. Existing Requests `2.34.2`, PyArrow `25.0.1`, the complete locked graph and required `uv_build>=0.12.15,<0.13.0` metadata are unchanged; `uv lock --check --offline` succeeds. No dependency upgrade or new lock resolution was needed.

| Role | Retained artifact | SHA-256 |
| --- | --- | --- |
| build | `uv_build-0.12.24-py3-none-macosx_11_0_arm64.whl` | `7a0f45941530c468e9b354e6f0f8e83668b6960a331bf3c311d7232ac33888ea` |
| runtime | `certifi-2026.7.22-py3-none-any.whl` | `62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775` |
| runtime | `charset_normalizer-3.5.2-cp314-cp314-macosx_10_15_universal2.whl` | `fcff63213e8e6e47770541a4607175404f47cbb3ebea7b6058cc82d524a0e424` |
| runtime | `idna-3.20-py3-none-any.whl` | `ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c` |
| runtime | `pyarrow-25.0.1-cp314-cp314-macosx_12_0_arm64.whl` | `bf0b672390cdcb640d7288f96b826d71ff4e9abb254a86c89890baf51a29cee6` |
| runtime | `requests-2.34.2-py3-none-any.whl` | `2a0d60c172f83ac6ab31e4554906c0f3b3588d37b5cb939b1c061f4907e278e0` |
| runtime | `urllib3-2.8.0-py3-none-any.whl` | `0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3` |

Historical Minor T1-M1 is resolved for this explicit native release path. `uv build --offline --package sec-edgar-ingest --wheel --sdist` is retained with `--force-pep517`, `--python`, an external `--out-dir`, `--no-create-gitignore`, `--no-index --find-links CACHE/build`, and SHA-256-constrained `uv_build==0.12.24` via `--build-constraints --require-build-hashes`. `--preview-features build-dependency-hashes` explicitly enables uv0.13.1's named hash-checking feature and removes its experimental-feature warning. Captured A/B build logs contain neither the incompatible native-fast-path warning nor any other warning; no backend range was relaxed or backend silently upgraded. `setup.json` records actual argv/tool/backend/interpreter/build output separately from runtime identity.

### Genuine offline proof environments and verification

`tests.support_release.proof_releases(project, cache)` exports tracked and untracked nonignored implementation/metadata into an independent temporary Git repository, excluding stores/caches/evidence. It commits A, builds A at its final location, adds/commits only a harmless included resource for B, and builds B there. Both have real installed wheels/dependencies and independently checked full lock inventory. The factory caches its result per session/snapshot and can instead validate an explicit real proof catalog. Temporary proof repositories/environments are test support and are cleaned when that test session exits; this is not the accepted fork release or Task14's fresh acceptance build.

Actual final proof capture (complete manifests, isolated installed evidence and build/tool logs are in `.sdd/1-sec-edgar-local-spec/task-7-proof-evidence.json`):

| Proof | Actual temporary Git revision | Release ID | Module/distribution |
| --- | --- | --- | --- |
| A | `0c9e0e411ebe7000210766f38d26a2ea20eef82f` | `8bdf0c73f887df97ecbd50440297efcfca541adfc5b8f558a629e4abf2fb8d37` | `0.2.0` / `0.2.0` |
| B | `59fbdbe3fc3ba6ebd986c1cf2dc4d1ef56554131` | `ef4988f9c6930cd00e86e08f854e6597bfb4b7c9b5d07d5cfa0a4c96d3d61529` | `0.2.0` / `0.2.0` |

The actual A/B dependency inventories are exactly certifi 2026.7.22, charset-normalizer 3.5.2, idna 3.20, pyarrow 25.0.1, requests 2.34.2 and urllib3 2.8.0 plus sec-edgar-ingest 0.2.0. The build backend is absent from runtime inventory. B contains `sec_edgar_ingest/proof_resource.txt`; parser and schema remain unchanged. Rebuilding the same committed snapshot after changing source mtime and installation path produces the same identity; reconstruction also preserves identity while creating a new final venv/prefix/launcher.

Initial focused RED before production implementation: release9/failures9 (`Task 7 release builder absent` or `Task 7 requires explicit immutable release setup`), preflight7/failures7 (`Task 7 requires read-only native installed preflight`); runtime23 already green. Additional clean REDs caught filename-vs-WHEEL tag mismatch, escaped installed-origin containment, module/distribution version mismatch, and the uv experimental warning; all were corrected and rerun. One oracle correction changed a launcher-path assertion to inspect uv's long-path shell trampoline rather than assuming a direct short Python shebang.

Final required guarded gate, after all production changes:

```sh
export UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache
export UV_PYTHON_DOWNLOADS=never
export UV_OFFLINE=1
set -e
for test_file in test_runtime.py test_release.py test_runtime_preflight.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

Exit0, runtime23/0.011s; release20/8.596s; preflight11/3.593s; all OK, no skips or warnings (54 tests). Complete output: `.sdd/1-sec-edgar-local-spec/task-7-focused-green.log`. Additional historical local ETL12/0.630s is green. ZIP fixtures, subprocess boundaries, actual clean/stale committed source, actual installed inventory/tampering, exact install argv, failure evidence retention, offline cache integrity and cross-location reconstruction are all covered. `git diff --check` passes.

The full guarded default suite was attempted once and interrupted with SIGINT/exit130 after concrete unrelated later-owned failures and sandbox loopback refusal were established; it is not green or complete. `.sdd/1-sec-edgar-local-spec/task-7-full-suite.log` preserves that incomplete run. Isolated later-owned examples: approval activation fails on removed `open_stores(base_path=...)`; Azure coordination case imports absent `azure`. Those tests were not changed or skipped, and no unrelated loopback permission escalation occurred. Task7 scoped checks are green; independent review, Task8 integration, Task14 clean release proof and genuine SEC L12 remain separate gates.

Self-review covered the complete scoped source/test diff and each brief acceptance item. Applied clean-code N1/N4/N7 (effectful setup vs read-only verification names), G30/G34 (cohesive artifact/build/install/verify stages), G19 (explicit identity/inventory variables), G25 (named build/cache constants), F2 (returned validated records), C3 (portable-evidence and isolated-probe intent), and T1/T5/T6 (tamper, partial-install, version/origin, lock and relocation boundaries). No adjacent cleanup was applied. Runtime remains the specified descriptor/manifest/preflight boundary; no unplanned module split was introduced.
