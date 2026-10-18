# Milestone 3: supervised checked children

Task 9 implementation checkpoint, 2026-10-18, against base `c241b3fa2e319681557015f168072d9dc4f3c75d`. This checkpoint covers supervised release-aware checked dispatch and its process/guard test support. Independent task review, later proof/operator migration, complete default-suite readiness and genuine SEC acceptance remain separate gates. L12 is `not_run`; fixture, retained genuine bytes and loopback HTTP are not L12 evidence.

## Runtime and authority boundary

`runtime.resolve_child(settings)` resolves the child's saved configuration before call/store mutation, verifies its exact installed native release and returns its Python executable plus runtime descriptor. Only explicit fixture runtime selects the fixture parent `sys.executable`. Origin collection and saved publication repair preserve their original configuration/release, while new transform/publication use the current parent settings. Missing original installations fail before dispatch. No ingestion-time installation, resolution, synchronization or interpreter download occurs.

Native stage argv starts with existing `native_python_argv`: `python -I -B -X pycache_prefix=/dev/null -m sec_edgar_ingest ...`. Source-execution policy is established before application imports. The canonical normalized absolute configuration is retained and materialized read-only for launch. Python startup/path overrides and virtual-environment environment hints are scrubbed. `runtime.run_child` uses a dedicated POSIX process group, captures bounded output (1,048,576 bytes per stream), forwards termination, enforces the deadline and bounds shutdown/drain phases to five seconds. A timeout, signal, output overflow or unconfirmed group drain cannot assert safe completion; forced cleanup cannot fabricate an absent durable result.

Dispatcher retains the canonical checked call before launch. A closed `sec-local-child-execution-v1` state index selects immutable canonical `sec-local-child-launch-v1`, config and `sec-local-child-exit-v1` objects under that exact call/sequence. Every record carries the local contract marker. The exit reference includes SHA-256/byte count; raw stdout/stderr use canonical hex and observation time uses canonical UTC. Existing malformed indexes, altered archived config, changed launch identity or corrupt exit bytes refuse without changing the existing execution authority.

Completion requires confirmed drain, an observation before the original deadline, the actual exit code, one exact JSON descriptor and independently loaded matching durable result/Attempt/input authority. Exact finished replay revalidates this evidence without launching. Ambiguous exact replay cannot launch again. A positively observed, drained, matching unfinished publication-repair failure can explicitly retry under its saved runtime with a new immutable execution sequence.

## Offline guard and recovery evidence

The injected test-only runner copies an explicit harness into an isolated temporary directory, with a read-only validated payload containing only selected loopback origins, named fault instructions and explicit evidence paths. The bootstrap imports stdlib and the copied guard first, installs it, then imports application/harness modules from the selected environment. It never inserts an application checkout into import paths. Multiprocessing HTTP targets install the guard again and carry the exact selected origin.

A shared actual import-time sentinel attempts DNS and socket access. Tests prove denial before suite imports, in a spawned HTTP transport target, in native A/B stages and in actual installed A/B parent workflows with their distinct stage PIDs. Independently committed A/B snapshots are built and installed offline; manifest, source-origin and dependency inventories are verified. The A-origin collection/saved-repair versus B-current processing test checks actual selected executable paths and retained contexts. Production sender loopback/logical-clock refusal remains explicit in the acquisition gate.

All twelve inherited process-death points retain named fsynced event/acknowledgment evidence and bounded joins: Attempt begin, checked call, collection binding, checked result, selection, publication pointer, publication repair, ETL result object, member processing, member receipt, report object and Attempt finish. Ambiguous stage deaths first require a nonzero exact retry, then continue under a NEW workflow attempt through existing source/repair-obligation machinery. Retained old evidence and already committed publication pointers remain unchanged.

The three-collector race fixture now pins its workset to the actual temporary harness root. This corrects a test setup mismatch; collection context/root validation remains strict. Obsolete Azure/MSAL auth stubs were removed from owned guard tests because those dependencies are absent by the native release contract. All socket/DNS/selected-origin/spawn guard cases remain, with additional sentinel coverage.

## Verification

Final frozen gate exited 0: **41 tests passed**, no skips, warnings, errors or failures. All five modules used the same unchanged source/harness snapshot.

| Module | Tests | Seconds | Exit |
| --- | ---: | ---: | ---: |
| Native dispatch | 13 | 53.732 | 0 |
| Checked workflows | 13 | 44.685 | 0 |
| Process recovery (all twelve death points) | 2 | 124.557 | 0 |
| Network guard | 7 | 0.220 | 0 |
| Acquisition processes | 6 | 33.399 | 0 |

The exact gate, with no filtering or skips, is:

```sh
export UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never
export UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache
for test_file in test_native_dispatch.py test_workflow_checked.py test_workflow_process.py test_network_guard.py test_acquisition_processes.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

The complete gate uses authorized loopback-only sandbox escalation because the sandbox refuses `bind(('127.0.0.1',0))`; the guard stays enabled. No genuine SEC HTTP occurs. Intermediate failures were diagnosed rather than skipped: a mixed test harness copied during an earlier run produced `ModuleNotFoundError: support_process`, reproduced with the old two-file copier; and the acquisition race initially used a default-root workset against temporary-root collectors, reproduced by strict `_check_collector_context`. The final gate runs on frozen source/harness bytes.

TDD sensitivity evidence includes parent in-process invocation, duplicate finished/ambiguous launches, missing/malformed/mismatched descriptors, extra fields, tampered execution indexes, changed archived config, missing named acknowledgments and missing nested installed-parent guard propagation. Full commands, outputs, diagnoses and task report are retained in `.sdd/1-sec-edgar-local-spec/task-9-report.md`.

Environment: CPython 3.14.0, macOS 26.6.2 arm64, uv 0.13.1, pinned Requests 2.34.2/PyArrow 25.0.1, offline build backend uv_build 0.12.24 within `uv_build>=0.12.15,<0.13.0`. No lock/dependency changes, source-repository writes, raw fixture edits or cleanup/migration operations.

`git diff --check` passed with no output before staging. Self-review checked all changed production and support boundaries, exact replay/refusal behavior, scope and preserved constraints. Independent controller task review remains pending.

## Task 10: complete local recovery, operator and upgrade checkpoint

At pre-review commit `55d3951041fb5f987eba42b2dd85f4df76015c5a`, Task 10 extended the reviewed Task 9 baseline to the complete default native-local suite. That historical frozen guarded discovery passed **874 tests in 2908.251 seconds**, exit 0, with no skips, errors or failures. Its exact discovered method IDs were checked against all 58 current default modules in `test-disposition.json`. That inventory accounts for all 56 pinned source test modules: 46 retained/ported and 10 explicitly excluded cloud/image modules, plus 12 added local modules. This is the Task 10 milestone; Task 14 fresh acceptance and L12 genuine SEC acquisition remain separate gates. L12 is `not_run`.

The independent class/method retention audit maps all 217 original mixed/recovery methods: 175 local methods retained, 7 local extractions from SDK-backed tests, 15 replaced contracts and 20 genuinely cloud-only removals. Every retained/extracted/replaced method has an explicit current destination. The status breakdown is 146 unchanged, 24 adapted, 5 renamed/moved, 7 extracted and 15 replaced, with zero missing or partial mappings. The whole-source inventory includes actual current class/method names and file/body hashes. No default test is broadly skipped, and the complete runtime/test/support AST has zero Azure/MSAL imports.

The mixed-module ports preserve local journal durability/fencing, constructor contention, process-level request ordinals, finite lease uncertainty, original HTTP child drain/fatal timers, publication races and repair, validation before first-row exposure, exact approval/activation/rollback audit and operator no-mutation behavior. The >64 KiB candidate oracle still checks complete persistence, duplicate insert refusal, replacement with the actual revision and stale-CAS refusal. A separate large general pointer row and partial-stream/exclusive-target materialization cases remain. All 51 retained conflicting observations across 2010Q1, 2015Q1 and 2026Q3 still quarantine their whole sources; no parser, zero-row, duplicate-winner or force exception was added.

### Actual installed upgrade evidence

Task 7's proof factory built clean independently committed A/B wheel environments from the frozen current implementation snapshot. B differs through a benign committed package resource; parser/schema versions are unchanged. Actual proof release IDs:

- A: `f93f60e56e13374eccc7d5c68bf8de87bd66ed65ed3227e624c39e3f7eb14c2b`
- B: `05e1cdb2f69f501a20e612441b3669c817f8ce0c0444f1bb96d34e4993261bad`

The actual installed B workflow parent completes A-origin pending backlog and repairs a saved A publication by launching the installed A executable. New transform/publication execute under B. Evidence records parent PID/executable/import origin, A/B child PIDs and runtime IDs, exact checked call/result authority, read captures/counts and unchanged original results/pointers. B performs history/capture, exact-candidate approval and immutable rollback over A history. Cached and forced reuse preserve A's exact original observation/producer bytes and canonical `(cik, archive_path)` identity.

Removing the A environment still permits B historical reads through retained canonical A manifests; executing an A-origin call refuses before call/store mutation. Missing/corrupt saved A manifests refuse before exposing a row. Real native imports run from installed site-packages with `-I -B -X pycache_prefix=/dev/null`, scrubbed environment and fixed copied offline harness. No A/B installed payload was mutated to manufacture release identity. All installation, build and proof dependency access remains explicitly offline through the fork lock and prepared artifact cache; missing artifacts fail rather than skip or fetch.

`scripts/verify-native-release.py --release PATH --harness PATH --evidence PATH` is now implemented. The shared verifier copies fixed fixtures/guard/support outside checkouts, executes the selected installed Python and checks native preflight, complete lock/inventory, full package payload, workflow, audit and read behavior. The default installed cases and ETL/workflow installed adapters use this implementation or the same underlying support. Old Stage 2/3 wheelhouse/export and fixed dependency-count prerequisites are removed; wrong-transitive-version refusal remains.

### Failures and recovery

New local failure cases cover object/config-archive/event-stderr ENOSPC, foreign/corrupt SQLite structure/version, binding refusal, missing exact approval evidence and immutable rollback-record retention across index failure. Existing suites cover SQLite busy bounds, constructor races, stale CAS, corrupt/missing raw/manifest/Parquet, clock uncertainty, lost ownership and uncertain HTTP/workflow child drain. Refused old binding/selection/contracts preserve object-tree and SQLite logical contents. Two reproduced production gaps were fixed: read-only native schema validation before worker WAL/DDL or operator reads, and explicit non-Mapping workflow-contract refusal. Valid SQLite `user_version=0` remains; there is no migration or cleanup. Read-only SQLite verification may create internal transient WAL/SHM files as allowed by the storage contract.

Named fault/ack instructions now cross exec through the copied guard bootstrap; parent-only monkeypatches are not treated as child fault evidence. Explicit fixture clocks propagate only when requested. A positively observed/drained ordinary publication failure can use its saved repair path. Ambiguous child death refuses original exact replay and continues under a NEW workflow attempt, preserving original Attempt/call/execution evidence and committed pointers. No new child ID is silently substituted inside a frozen workflow.

The range/parser settings helper now preserves the actual temporary storage/log roots. A regression caught an untracked generated fixture store from the old rootless helper; the run artifact was inventoried before authorized removal. Tracked raw fixture bytes are unchanged. Task 10's logging boundary is the existing event stderr sink; launcher log mkdir/open/post-dispatch failure behavior belongs to Tasks 11/12 and later final acceptance.

### Timing and exact gate

Production 3-request/second dispatch/start measurement retains the original 1/3-second start window and no fixture timing allowance: 3 successes, 0 safe `permit_expired`, 0 progress failures, 0 invariant violations; start latency min 0.068945, median 0.070860, max 0.077270 seconds. Deliberately stale fixture cases still assert deferred/no-wire `permit_expired` separately. Production pacing, start/deadline, drain and HTTP limits were not widened.

```sh
export UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never
export UV_CACHE_DIR=/private/tmp/sec-edgar-local-uv-cache
export SEC_EDGAR_TASK10_UPGRADE_EVIDENCE=/private/tmp/task10-full-final2-upgrade
export SEC_EDGAR_TASK10_LATENCY_EVIDENCE=/private/tmp/task10-full-final2-latency.json
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p 'test_*.py' -v
```

The exact four-file focused gate passed 22 tests before the final full gate. Additional targeted storage/config/operator/acquisition/download/ETL/workflow checks and their meaningful RED/GREEN diagnoses are recorded in `.sdd/1-sec-edgar-local-spec/task-10-report.md`; the completion migration subreport preserves all 23 original completion methods. An initial full diagnostic was interrupted on obsolete history flags and is explicitly not counted as gate success. The first complete discovery ran all 874 tests with one obsolete positive selection-format assertion failure; that exact expected marker was migrated to the local format, its full 218.094-second supersession case passed with every later semantic assertion retained, and the final complete frozen gate passed. The final full gate used one frozen 257-file source/test/harness/script snapshot, verified unchanged after completion, with authorized selected-loopback sandbox access and the network guard retained. No genuine SEC HTTP occurred.

Environment: CPython 3.14.0, macOS 26.6.2 arm64, uv 0.13.1, uv_build 0.12.24 within the unchanged build requirement, Requests 2.34.2 and PyArrow 25.0.1. Fork lock SHA-256 `e3d3dac9971ed75bdc5864ebd8c422c2e34bd24236a9a77bbadb6a87cddf1bbb`. No dependency upgrades, source-repository writes, old-store migration, store relocation or automatic production cleanup. Independent controller task review remains the next checkpoint; this record makes no whole-release readiness claim.

## Task10 review fix round1: installed transitive rejection and proof target

Independent review found that the pre-review adapter retained only the synthetic wrong-urllib3 dictionary assertion, dropping the real installed negative, and still accepted ignored wheel/source arguments. This fix restores the actual installed negative and removes those obsolete Python/CLI arguments entirely. `workflow_proof.py installed --output ABSOLUTE_PATH` now verifies its actual current committed A/B proofs; --wheel/--reviewed-source are rejected before proof construction or output mutation. The ETL installed adapter already delegates through output only.

`locked_proof.verify_wrong_transitive` reconstructs a disposable environment directly at its final release/venv path from retained artifacts. It changes only that disposable urllib3 distribution metadata from2.8.0 to0.0.0. Actual isolated installed inventory still reports Requests2.34.2 and PyArrow25.0.1; both the installed inventory assertion and shared native verifier refuse the mismatch (each exit1). Native argv uses the selected venv executable with -I -B -X pycache_prefix=/dev/null and scrubbed environment, with the copied network guard installed before application imports. Accepted A/B environments are neither copied/moved nor mutated; complete before/after file content inventories are identical. Commands/stdout/stderr, metadata hashes and inventories are retained in `/private/tmp/task10-fix1-final-installed-evidence` and referenced by committed test-disposition.json.

Final focused gates:9 lock/argument tests0.126s and3 actual installed upgrade/verifier tests241.235s, both exit0 with no skips/errors/failures. A separate obsolete-argument CLI invocation exits2 and creates no output. Meaningful REDs first exposed missing installed oracle and all three obsolete argument-contract defects; full commands/outputs and the isolated resolved-temp-path assertion correction are recorded in the Task10 report. Current default inventory is878methods across58modules; all217 original mixed-method mappings remain accounted for. No production bytes changed. The historical874-test/2908.251s log and257-file snapshot above belong only to pre-review commit55d3951041fb5f987eba42b2dd85f4df76015c5a; they are not relabeled as a complete suite on these new proof/test bytes. Per controller direction these test/proof-only corrections use covering gates; later Task13/14 complete checks remain mandatory. Scoped re-review is pending. L12 remains not_run, with no genuine SEC HTTP.
