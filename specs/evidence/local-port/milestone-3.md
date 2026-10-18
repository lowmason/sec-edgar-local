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
