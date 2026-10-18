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

## Task 12: native stream and signal supervision

Task 12 replaces Task 11's historical dispatch boundary above with `run_invocation`. Preparation and stream reopening remain pre-dispatch exit 2. The launcher appends to the already exclusively created archives, dispatches one native engine in a separate process group, and concurrently drains its stdout and stderr without decoding or mixing bytes. It never reads or changes the engine's durable result.

Terminal descriptors are nonblocking with a 1,048,576-byte queue per stream and a one-second final drain allowance. A closed, overloaded, or stalled terminal sink becomes a remembered required logging failure; other sinks and engine reads continue. Archive writes and final fsync are independently checked. After engine/descendant supervision, logging failure returns 9 and writes a `logging_failed` stderr event containing the actual engine return code wherever a stderr sink remains usable. Otherwise the actual engine return code is preserved.

SIGINT/SIGTERM are caught before Popen to close the dispatch handoff race, then forwarded to the engine group. The saved deadline sends SIGTERM; a ten-second engine grace precedes forced engine termination. A bounded independent ancestry observer tracks PID, group, and process birth identity, including separately grouped checked-stage descendants; its failures cannot block normal stream reads or signal forwarding. Surviving recorded descendants require conservative cleanup and `shutdown_uncertain` evidence. PID reuse never authorizes following unrelated children or signaling their groups. An unavailable ancestry snapshot preserves uncertainty rather than proving successful descendant drain. Forced cleanup does not fabricate a result or rerun an engine.

Approved process-test strategy invariants and fixtures:

| Invariant | Falsifying fixture / check |
|---|---|
| Structural / relational | One whitespace-preserving JSON stdout result, separate structured stderr, exact archive bytes, engine statuses 0/5/7/10/11; launch/start/drain event counts |
| Bounds | Closed terminal pipes; open but unread pipe with 4 MiB output; slower reader within the queue allowance; saved deadline; uncooperative engine forced termination |
| Failure precedence / persistence | stdout/stderr/both archive writes, archive fsync, final stderr fsync, terminal failure plus archive and engine failure; already-fsynced durable result remains byte-identical |
| Process isolation / reproducibility | Guard installed before imports in runner/engine/child; separate child group; native `-I -B -X pycache_prefix=/dev/null`; installed launcher origin and SHA-256 equal current source; one engine and no uv/pip dispatch |
| Recovery / refusal | Failed pre-dispatch archive reopen retains every prepared byte and returns 2; expired invocation never opens streams or dispatches; absent ancestry and forced cleanup emit uncertainty with actual status; dead engine cannot establish child drain through its status or closed pipes |

The uninstalled test fixture `launcher_engine.py` runs only explicit synthetic process scenarios. It records engine/child start and drain acknowledgments, creates one fsynced synthetic durable result, and injects faults only through the test runner. No production test flag or endpoint bypass exists. No network traffic, genuine SEC HTTP, or L12 claim is involved. These tests remain in default unittest discovery without exclusions.

Both focused files use the same commands before and after implementation:

```sh
UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_local_launcher.py -v
UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_launcher_process.py -v
```

Small-cycle red/green evidence:

1. Initial process red: `Ran 8 tests in 0.001s`, `FAILED (failures=8)`, exit 1. All assert the missing Task 12 bounded `run_invocation` contract before a process can launch. Integration red: `Ran 17 tests in 7.034s`, `FAILED (failures=3)`, exit 1; two main status assertions still received Task 11's 2 and the installed bootstrap still emitted its explicit unimplemented-dispatch event. A preliminary one-nanosecond timeout rounded to zero in `timedelta`; the bootstrap test uses one microsecond so its intended expiration is valid.
2. Implementation validation separately exposed a wrong positional argument to the existing zero-argument `isolated_environment()` helper, then a sandbox refusal to execute `/bin/ps`. The API call was corrected. The latter is environmental evidence, not a contract red: native process tests run under scoped sandbox escalation while keeping network_guard and offline settings active. No guard was disabled. An initial slow-reader scenario produced faster than its consumer and correctly hit the finite queue; its producer cadence was made explicitly slower to test successful bounded drainage separately from the blocked/overflow case.
3. Ancestry-failure regression red: full process command `Ran 11 tests in 32.471s`, `FAILED (failures=1)`, exit 1; injected unavailable ancestry killed the real engine and returned 9 rather than continuing its streams/status. The independent observer now records uncertainty without controlling stream/signal progress. The strengthened process gate then passed `Ran 11 tests in 33.278s`, `OK`, exit 0.
4. Final-fsync red: process command above plus `-k archive_failures`: `Ran 1 test in 2.859s`, `FAILED (failures=1)`, exit 1; final stderr fsync failure returned engine 10 instead of 9. The later complete process gate includes this now-green subcase.
5. Dispatch signal red: process command above plus `-k popen_boundary`: `Ran 1 test in 5.542s`, `FAILED (failures=1)`, exit 1; SIGTERM inside the Popen return boundary killed the wrapper with -15. After installing the handoff handler before dispatch, the same command gave `Ran 1 test in 5.638s`, `OK`, exit 0; the wrapper reaped its engine and preserved its actual -15, represented by POSIX process status 241.
6. PID-birth red: preparation command above plus `-k reused_engine`: `Ran 1 test in 0.068s`, `FAILED (failures=1)`, exit 1; an engine PID reused with a different birth identity incorrectly adopted an unrelated child. The observer now retains the engine's birth identity as well as descendants' identities. The final complete preparation gate includes the now-green regression.
7. Final precommit focused green: preparation `Ran 21 tests in 7.173s`, `OK`, exit 0; process `Ran 13 tests in 30.271s`, `OK`, exit 0. Forced-engine assertions verify actual -9 and wrapper process status 247, no manufactured durable result, one launch, separate child drain acknowledgment, and no surviving engine/child PID. Terminal/archive/engine simultaneous failure preserves actual engine 11 while returning wrapper 9. `git diff --check` exited 0.

Installed process proofs export current workspace source and tests into an independent repository, commit that immutable snapshot, then build/install its wheel from the existing offline artifact cache. They do not build an uncommitted production release. Runtime assertions establish the imported `local_cli.py` is beneath that proof release's `venv`, and its SHA-256 exactly matches the launcher implementation being tested. The proof cache key includes the current source bytes; no old Task 11 wheel can satisfy this assertion.

Tool versions remain CPython 3.14.0 and uv 0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin), using the previously recorded locked backend/artifacts. No dependency or lock changes, cache downloads, source-repository changes, or store cleanup occurred. Postcommit focused verification is recorded in the Task 12 report.
