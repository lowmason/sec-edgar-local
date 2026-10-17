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
