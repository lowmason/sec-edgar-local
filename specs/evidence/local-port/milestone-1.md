# Milestone 1: pinned local package baseline

Task 1 implementation checkpoint, 2026-10-17. This evidence covers only the deliberately small baseline; it does not claim full CLI discovery, full retained-suite readiness, native live release execution, or L12 acceptance. No SEC requests were made.

## Imported objects and fixture integrity

Source: `/Users/lowell/Projects/sec-edgar`, pinned commit `0e7701a1e2e98b669334546c90f5c9d4c45b1537`. Enumeration used `git ls-tree -r --name-only`; extraction used `subprocess.run(["git", "-C", source, "show", f"{pin}:{path}"], check=True, stdout=PIPE).stdout` and `Path.write_bytes`. The source working tree was neither copied nor modified. All 240 original-byte SHA-256 values were recorded before adaptation, sorted by `(original_path, destination_path)` in `specs/evidence/source-import.json`, and independently rechecked against the pinned Git objects after adaptation.

Imported counts: 42 retained runtime files (45 upstream minus deployment.py, storage/azure.py, storage/identity.py); 46 retained source test modules (56 minus exactly 10 cloud/image modules); 13 retained helpers; all 50 upstream package fixtures; 4 metadata/README files; 85 additional retained files. `workflows/legacy.py` and its tests are preserved. The unchanged retained manifest independently specifies 83 records totaling 14,278,591 bytes plus 2 provenance files; all 85 mapped files total 14,701,270 bytes. All hashes, byte sizes, and paths pass the independent oracle. The mapping includes headers, intents, inspections, matrix, specimen bytes, and provenance.

`test-disposition.json` records every source test module and imports, exact exclusions, retained helpers, and cloud/image-related cases for later review. Those candidates are review inventory, not skips. Whole retained-runtime/test AST cloud-import validation remains a mandatory passing Task 10 gate after mixed modules are ported. Historical text still names excluded upstream paths.

Eight imported files are intentionally adapted: both pyproject.toml files; module __init__.py; tests/network_guard.py, support.py, test_validation.py, test_discovery.py, and etl_proof.py. All other imported objects remain byte-identical. Test consumers use the complete hash-checked retained_path map and do not read the original repository. Socket/DNS denial, exact selected_origin, spawn propagation, and pre-import guard installation remain intact; only provider hooks/imports are removed.

## Environment, dependency setup, and build backend

- Host: macOS 26.6.2, arm64, native filesystem.
- Bootstrap: `/opt/homebrew/bin/python3.14`, Homebrew CPython 3.14.8.
- uv: `0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin)`.
- uv-selected workspace/build interpreter: CPython 3.14.0, `[Clang 20.1.4]`, managed installation already present at `/Users/lowell/.local/share/uv/python/cpython-3.14.0-macos-aarch64-none`; `.python-version` remains `3.14`, Python floor `>=3.14`.
- Declared build backend: `uv_build>=0.12.15,<0.13.0`. Explicit PEP 517 artifact setup selected and downloaded `uv_build==0.12.24`; a subsequent fully offline PEP 517 wheel/sdist build passed with that exact backend.
- `uv lock` and `uv sync --locked` both exited 0. Lock resolution reported 8 entries, including non-installable root sec-edgar 0.1.0; sync installed 7 distributions. The sole installable workspace member and module are sec-edgar-ingest 0.2.0. Development sync is editable; native installed release execution is deferred to its planned task.
- Installed/resolved third-party graph: certifi 2026.7.22, charset-normalizer 3.5.2, idna 3.20, pyarrow 25.0.1, requests 2.34.2, urllib3 2.8.0. Every retained third-party version exactly matches the pinned upstream lock; there are no resolver-driven transitive changes or cloud dependencies. Root constraints retain only the two direct pins.

The first un-escalated `uv lock` attempt exited 2 because the sandbox denied writing `/Users/lowell/.cache/uv/.tmp...`; requested cache access resolved it. A later un-escalated redirected build also hit that cache restriction; its escalated rerun exited 0. Explicit dependency/artifact setup may access PyPI; all required checks below ran with `--offline`. No interpreter download was requested or performed.

Required `uv build --offline --package sec-edgar-ingest` exited 0 and emitted:

```text
Building source distribution...
warning: `build_system.requires = ["uv-build>=0.12.15,<0.13.0"]` does not contain the current uv version 0.13.1
Building wheel from source distribution...
Successfully built dist/sec_edgar_ingest-0.2.0.tar.gz
Successfully built dist/sec_edgar_ingest-0.2.0-py3-none-any.whl
```

That command uses uv 0.13.1's native fast path. To verify the declared backend rather than rely on that warning-bearing path, explicit setup ran `uv build --force-pep517 --package sec-edgar-ingest -v` (exit 0), then the extra offline PEP 517 command below (exit 0). Final artifacts were produced by uv_build 0.12.24. This is a tooling observation, not a change to the required metadata range.

## Red/green evidence

1. Before any extraction, `python3.14 -m unittest discover -s packages/sec-edgar-ingest/tests -p test_source_import.py -v` ran 2 tests and exited 1: missing `specs/evidence/source-import.json` and `tests/fixtures/retained-manifest.json` (2 FileNotFoundError errors), as required for the bootstrap. After extraction, the same command passed 2 tests.
2. Added guard/package baseline cases before their changes: the same command ran 4 tests, exited 1 with 2 failures. Guard bootstrap failed with `ModuleNotFoundError: No module named 'azure'`; metadata failed with `AssertionError: '0.1.0' != '0.2.0'`. Removing provider hooks and updating metadata produced 4 passing tests.
3. Added retained lookup happy-path/unknown-path and escape/missing/size/hash rejection cases before implementing retained_path. The same command ran 6 tests and exited 1: `ImportError: cannot import name 'retained_path' from 'support'` plus 4 missing-helper subtest AttributeErrors. Implementing the exact required lookup produced 6 passing tests, including all 85 valid paths and all rejection cases.
4. Before porting retained validation paths, the required guarded validation command ran 12 tests, exited 1 with 11 passing and one FileNotFoundError for the original provenance path under the destination root. After replacing original-root filesystem resolution with retained_path, all 12 pass without changing specimen or parser bytes.

No broad discovery or full-suite run was attempted; selected modules are the explicit milestone baseline. Discovery/ETL retained-path adaptations were self-reviewed against pinned code and their embedded original paths; those modules' broader execution remains in later gates.

## Fresh required baseline outputs
### source-import: exit 0

```sh
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_source_import.py -v
```

```text
test_guard_bootstraps_without_cloud_imports_and_denies_network (test_source_import.SourceImportTests.test_guard_bootstraps_without_cloud_imports_and_denies_network) ... ok
test_import_manifest_records_pinned_original_bytes (test_source_import.SourceImportTests.test_import_manifest_records_pinned_original_bytes) ... ok
test_local_package_graph_excludes_cloud_dependencies (test_source_import.SourceImportTests.test_local_package_graph_excludes_cloud_dependencies) ... ok
test_retained_fixtures_match_unchanged_upstream_manifest (test_source_import.SourceImportTests.test_retained_fixtures_match_unchanged_upstream_manifest) ... ok
test_retained_lookup_reads_only_verified_manifest_paths (test_source_import.SourceImportTests.test_retained_lookup_reads_only_verified_manifest_paths) ... ok
test_retained_lookup_refuses_escape_missing_or_corrupt_bytes (test_source_import.SourceImportTests.test_retained_lookup_refuses_escape_missing_or_corrupt_bytes) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.055s

OK
```

### urls: exit 0

```sh
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_urls.py -v
```

```text
test_conflicting_or_escaping_child_is_refused (test_urls.UrlTests.test_conflicting_or_escaping_child_is_refused) ... ok
test_listing_hierarchy_and_immediate_children (test_urls.UrlTests.test_listing_hierarchy_and_immediate_children) ... ok
test_source_shapes_and_stable_identity (test_urls.UrlTests.test_source_shapes_and_stable_identity) ... ok
test_unsafe_source_matrix (test_urls.UrlTests.test_unsafe_source_matrix) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.002s

OK
```

### validation: exit 0

```sh
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_validation.py -v
```

```text
test_accepted_guard_values_refuse_advertised_limit_plus_one (test_validation.ValidationTests.test_accepted_guard_values_refuse_advertised_limit_plus_one) ... ok
test_all_ten_hash_checked_retained_originals_validate (test_validation.ValidationTests.test_all_ten_hash_checked_retained_originals_validate) ... ok
test_archive_shapes_truncation_and_crc_failure_are_retained (test_validation.ValidationTests.test_archive_shapes_truncation_and_crc_failure_are_retained) ... ok
test_forged_expanded_size_and_prefix_crc_cannot_hide_deflate_suffix (test_validation.ValidationTests.test_forged_expanded_size_and_prefix_crc_cannot_hide_deflate_suffix) ... ok
test_full_deflate_end_marker_is_required_even_with_matching_size_and_crc (test_validation.ValidationTests.test_full_deflate_end_marker_is_required_even_with_matching_size_and_crc) ... ok
test_html_denial_and_error_pages_never_validate_as_index (test_validation.ValidationTests.test_html_denial_and_error_pages_never_validate_as_index) ... ok
test_nonempty_complete_entity_and_length_are_required (test_validation.ValidationTests.test_nonempty_complete_entity_and_length_are_required) ... ok
test_receipt_hash_and_file_count_are_checked (test_validation.ValidationTests.test_receipt_hash_and_file_count_are_checked) ... ok
test_received_and_expanded_caps_refuse_one_byte_past_guard (test_validation.ValidationTests.test_received_and_expanded_caps_refuse_one_byte_past_guard) ... ok
test_row_syntax_is_left_for_later_parser (test_validation.ValidationTests.test_row_syntax_is_left_for_later_parser) ... ok
test_selected_header_ascii_and_line_endings_are_exact (test_validation.ValidationTests.test_selected_header_ascii_and_line_endings_are_exact) ... ok
test_synthetic_daily_and_archive_original_bytes_validate (test_validation.ValidationTests.test_synthetic_daily_and_archive_original_bytes_validate) ... ok

----------------------------------------------------------------------
Ran 12 tests in 1.123s

OK
```

## Offline declared-backend build: exit 0

```sh
uv build --offline --force-pep517 --package sec-edgar-ingest -v
```

```text
DEBUG Found workspace root: /Users/lowell/Projects/sec-edgar-local
DEBUG Adding root workspace member: /Users/lowell/Projects/sec-edgar-local
DEBUG Adding discovered workspace member: /Users/lowell/Projects/sec-edgar-local/packages/sec-edgar-ingest
DEBUG Found workspace configuration at `/Users/lowell/Projects/sec-edgar-local/pyproject.toml`
DEBUG Searching for user configuration in: /Users/lowell/.config/uv/uv.toml
DEBUG uv 0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin)
DEBUG Reading Python requests from version file at `/Users/lowell/Projects/sec-edgar-local/.python-version`
DEBUG Searching for Python 3.14 in virtual environments, managed installations, or search path
DEBUG Found `cpython-3.14.0-macos-aarch64-none` at `/Users/lowell/Projects/sec-edgar-local/.venv/bin/python` (virtual environment)
DEBUG Using request connect timeout of 10s and read timeout of 30s
Building source distribution...
DEBUG Assessing Python executable as base candidate: /Users/lowell/.local/share/uv/python/cpython-3.14.0-macos-aarch64-none/bin/python3.14
DEBUG Using base executable for virtual environment: /Users/lowell/.local/share/uv/python/cpython-3.14.0-macos-aarch64-none/bin/python3.14
DEBUG Resolving build requirements
DEBUG Solving with installed Python version: 3.14
DEBUG Solving with target Python version: >=3.14
DEBUG Adding direct dependency: uv-build>=0.12.15, <0.13.0
DEBUG Searching for a compatible version of uv-build (>=0.12.15, <0.13.0)
DEBUG Selecting: uv-build==0.12.24 [compatible] (uv_build-0.12.24-py3-none-macosx_11_0_arm64.whl)
DEBUG Tried 1 versions: uv-build 1
DEBUG marker environment resolution took 0.000s
DEBUG Installing `uv-build==0.12.24` in `/Users/lowell/.cache/uv/builds-v0/.tmpsojQaQ`
DEBUG Registry requirement already cached: uv-build==0.12.24
DEBUG Installing build requirement: uv-build==0.12.24
DEBUG Creating PEP 517 build environment
DEBUG Calling `uv_build.get_requires_for_build_sdist()`
DEBUG Calling `uv_build.build_sdist(__import__("os").fsdecode(b"/Users/lowell/Projects/sec-edgar-local/dist"), {})`
Building wheel from source distribution...
DEBUG Assessing Python executable as base candidate: /Users/lowell/.local/share/uv/python/cpython-3.14.0-macos-aarch64-none/bin/python3.14
DEBUG Using base executable for virtual environment: /Users/lowell/.local/share/uv/python/cpython-3.14.0-macos-aarch64-none/bin/python3.14
DEBUG Resolving build requirements
DEBUG Solving with installed Python version: 3.14
DEBUG Solving with target Python version: >=3.14
DEBUG Adding direct dependency: uv-build>=0.12.15, <0.13.0
DEBUG Searching for a compatible version of uv-build (>=0.12.15, <0.13.0)
DEBUG Selecting: uv-build==0.12.24 [compatible] (uv_build-0.12.24-py3-none-macosx_11_0_arm64.whl)
DEBUG Tried 1 versions: uv-build 1
DEBUG marker environment resolution took 0.000s
DEBUG Installing `uv-build==0.12.24` in `/Users/lowell/.cache/uv/builds-v0/.tmp1Y8tXL`
DEBUG Registry requirement already cached: uv-build==0.12.24
DEBUG Installing build requirement: uv-build==0.12.24
DEBUG Creating PEP 517 build environment
DEBUG Calling `uv_build.get_requires_for_build_wheel()`
DEBUG Calling `uv_build.build_wheel(__import__("os").fsdecode(b"/Users/lowell/Projects/sec-edgar-local/dist"), {}, None)`
Successfully built dist/sec_edgar_ingest-0.2.0.tar.gz
Successfully built dist/sec_edgar_ingest-0.2.0-py3-none-any.whl
```

Wheel inspection confirms only `Requires-Dist: pyarrow==25.0.1` and `Requires-Dist: requests==2.34.2`; the three excluded runtime files are absent. Final generated artifacts (ignored, not committed):

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| sec_edgar_ingest-0.2.0-py3-none-any.whl | 170116 | 8047e6bf7f7ba3e7739ac67f1d8eb894167742027cd72849013a17f66daedff6 |
| sec_edgar_ingest-0.2.0.tar.gz | 142342 | 01587d7face188d1360d0ba5d9b4afba9cbb952cf3ef48dbd092e0d9fa1e36ff |

## Self-review and scope limits

Self-review compared every intentionally adapted import against its pinned original and rehashed all 240 original objects. No unrelated files were edited; fixture bytes and source import hashes were not rewritten after adaptation. The local fixture helper accepts only map-listed original paths, rejects resolved escape/missing files, verifies size and SHA-256 before returning. Guard preservation was checked in the diff and with subprocess socket/DNS rejection checks. Tests remain unittest; no pytest, broad skips, or additional service dependencies were introduced.

Applied clean-code rules: N1/N4 (explicit original_path/local_path and manifest terminology); G30 (one cohesive retained-path verification helper); T1/T5 (missing, unknown, escape, length/hash mismatch boundaries); C2 (guard documentation now matches the removal of provider handling). No adjacent cleanups were undertaken.

Remaining planned work: full CLI import after the excluded identity reference is ported; mixed cloud/image test extraction and full AST import gate in Task 10; complete default checks and installed native release execution in later milestones; genuine L12 separately. These are intentional Task 1 limits. The uv native fast-path warning is resolved for the final evidence artifacts by the successful declared-backend PEP 517 build, and should remain visible when later build automation is chosen.
