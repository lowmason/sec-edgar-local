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
