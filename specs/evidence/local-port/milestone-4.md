# Milestone 4: native launcher preparation

Task 11 test invariants (offline, network guard active; no genuine SEC HTTP):

- Structural: frozen invocation and closed versioned JSON contain exact native argv, IDs, UTC deadline, absolute archived config, original input hash and normalized effective hash. Unit tests use temporary live config and mock only current-process runtime verification.
- Relational: archived bytes reload identically and engine argv uses the archive; exclusive directory/file publication cannot overwrite prior evidence. Open remains in the config/hash; preparation pin is supplementary to the engine's authoritative pin.
- Bounds/refusal: workflow choices and finite positive timeout within configured allowance; missing release, malformed bootstrap selection, failed mkdir/write/fsync/stream preparation abort before engine/store/HTTP.
- Reproducibility/isolation: real committed offline proof wheel executes outside checkout with inherited import overrides removed and native bytecode isolation established before application imports. Shell never runs uv or package setup.

Focused gate from repository root (all cases are default offline cases, no marker/skip):

```sh
UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_local_launcher.py -v
```

Task 12 owns dispatch, stream forwarding, and supervision. Task 11 preparation metadata is not engine completion.

## Task 11 execution evidence

Environment: CPython 3.14.0, uv 0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin), application 0.2.0. Existing verified offline cache supplies uv_build 0.12.24 (artifact SHA-256 `7a0f45941530c468e9b354e6f0f8e83668b6960a331bf3c311d7232ac33888ea`); Requests 2.34.2, PyArrow 25.0.1, lock, and backend requirement are unchanged. No fetch, dependency upgrade, or genuine SEC request occurred.

The focused command above was run for each cycle:

1. Initial red: `Ran 9 tests in 0.001s`, `FAILED (failures=9)`, exit 1. Every failure asserted `Task 11 requires immutable launcher preparation` because `sec_edgar_ingest.local_cli` was absent. No unrelated cache/import failure.
2. First green: `Ran 9 tests in 0.157s`, `OK`, exit 0. One intermediate run exposed argparse's `SystemExit` instead of the promised integer main return for invalid numeric input; main now preserves that status as its return value.
3. Bootstrap red: `Ran 16 tests in 0.158s`, `FAILED (failures=7)`, exit 1. Existing nine preparation cases stayed green; seven additional cases asserted missing stdlib bootstrap or shell launcher.
4. Bootstrap green: `Ran 16 tests in 7.009s`, `OK`, exit 0. The real committed A/B snapshot proof releases were built/installed from the existing offline cache before launcher execution. Runtime launcher/bootstrap execution performs no setup and invokes no uv.
5. Final strengthened gate: `Ran 17 tests in 7.143s`, `OK`, exit 0. Added native-fixture negative coverage for a real installed process lacking the required bytecode-cache prefix policy.

Final gate output:

```text
test_bootstrap_contains_no_application_import_or_setup ... ok
test_bootstrap_execs_native_flags_and_original_argv_with_clean_environment ... ok
test_internal_project_root_cannot_be_supplied_in_original_argv ... ok
test_malformed_and_ambiguous_selection_never_executes ... ok
test_installed_preflight_refuses_tamper_before_logs_or_store ... ok
test_missing_release_refuses_without_install_or_download ... ok
test_native_fixture_still_requires_current_process_bytecode_policy ... ok
test_shell_finds_default_outside_checkout_and_archives_real_installed_release ... ok
test_archive_has_exact_normalized_bytes_original_hash_and_native_argv ... ok
test_default_config_uses_explicit_project_root_from_arbitrary_cwd ... ok
test_exclusive_file_cannot_overwrite ... ok
test_explicit_config_resolves_relative_to_calling_cwd ... ok
test_ids_unique_safe_segments_and_files_restrictive_durable_empty_streams ... ok
test_invalid_timeout_and_workflow_refuse_before_preflight_or_logs ... ok
test_invocation_collision_does_not_overwrite_or_retry ... ok
test_missing_or_unverified_runtime_refuses_before_logs ... ok
test_preparation_failures_return_two_retain_evidence_and_never_dispatch ... ok
Ran 17 tests in 7.143s
OK
```

Additional checks: `sh -n scripts/sec-edgar-local` exited 0; `git diff --check` exited 0. Unit fault injection independently exercises mkdir, exclusive write, fsync, stdout stream creation, and stderr stream creation. Each returns 2 without engine Popen/store/HTTP; partial evidence remains. Collision tests preserve earlier bytes and refuse to retry under the colliding identity. Real installed proofs reject a tampered installation receipt and a missing release before logs/store, and execute outside checkout with hostile inherited Python overrides/cwd package present.

## Integration boundary

Task 11 intentionally stops after successful preparation: main emits a structured `launcher dispatch is not yet implemented` event including the invocation path and returns 2. It never reports successful engine work. Task 12 replaces that explicit boundary with bounded dispatch and log forwarding/supervision. Empty prepared stream files and `invocation.json` are supplementary evidence, never completion.

`pin_context` retains `end_quarter=open` in the normalized effective config/hash and returns its resolved endpoint separately. Preparation therefore records a labelled supplementary pin without changing archived config semantics or introducing forbidden live `--today`. The engine owns the authoritative start/pin; preparation and dispatch can cross UTC midnight, so the supplementary date/quarter can differ from the engine's saved context. Exact manual replay uses the archived argv/config/release/IDs/deadline and the engine's durable replay rules.
