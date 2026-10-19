# SEC EDGAR Local Ingestion Implementation Plan

**Status: COMPLETE (2026-10-18)** — executed via subagent-driven-development; nothing deferred.

Both independent acceptance gates pass: renewed L01–L11/L13 and separately reviewed L12 adjudication of the preserved genuine bounded attempt. Original genuine run/verification remain incomplete, exit 12; the corrected offline conclusion is separately retained in `specs/evidence/local-port/sec-acceptance.md`. Final task and whole-branch reviews are approved; the current documentation finding is resolved.

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task via subagent-driven-development (the default) — or executing-plans when your human partner chose inline execution at the handoff. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the pinned ingestion implementation into a standalone native local application while retaining acquisition, coordination, publication, recovery, and audit guarantees.

**Architecture:** Keep the existing uv workspace and `sec_edgar_ingest` package. Replace cloud configuration and image provenance with strict local configuration, immutable native releases, and release-aware supervised child processes; retain the SQLite/object stores, production SEC transport, parser, and publication algorithms. Separate the complete offline verification gate from a deliberately bounded genuine SEC acceptance run.

**Tech Stack:** CPython 3.14 on macOS arm64; uv workspace/build backend; Requests `2.34.2`; PyArrow `25.0.1`; standard-library unittest, SQLite, subprocess/multiprocessing, hashing, JSON, signals, and filesystem operations.

**Spec:** `specs/completed/sec-edgar-local-spec.md`, approved in destination commit `06969c99dce6962995f6917d3507041289c20e02`.

## Global Constraints

- Source baseline: `/Users/lowell/Projects/sec-edgar`, commit `0e7701a1e2e98b669334546c90f5c9d4c45b1537`. Extract Git objects from this revision; never copy a moving working tree or modify that repository.
- “The first supported host is this Mac: CPython 3.14, macOS arm64, a native filesystem with working SQLite locking and atomic filesystem operations.” Retain `requires-python >=3.14` and `.python-version` `3.14`.
- “The release must install, build, pass its complete default checks, and run without Azure SDKs, MSAL, Azure CLI, Bicep, Docker, or a container service.” No cloud extras or optional provider fallback.
- One installable workspace member: `packages/sec-edgar-ingest`; import `sec_edgar_ingest`; console command `sec-edgar-ingest`; fork distribution/module version `0.2.0`.
- Keep Requests `2.34.2`, PyArrow `25.0.1`, and build requirement `uv_build>=0.12.15,<0.13.0`. Regenerate the local lock; record exact tool/backend/interpreter versions; no opportunistic dependency upgrades.
- `config_version=sec-local-config-v1`; `storage.backend=local`; independent `acquisition.mode=live|fixture`; `reconciliation.require_withdrawal_approval` always true.
- Defaults: `conf/sec-edgar-local.json`, `storage.root=../data`, `logging.root=../logs`, `backfill.start_quarter=2015Q1`, `backfill.end_quarter=open`, `daily.start_date=2026-10-01`.
- Preserve owner User-Agent `Lowell Mason sec-edgar-ingest mason.lowell@mac.com`, default 3 requests/second, one active collector; lower positive rates are permitted, higher rates are refused.
- Preserve five total HTTP attempts; 2-second base/120-second capped jittered retry delay respecting longer server delays; 15/60-second connect/read timeouts; 90-second exchange limit; 67,108,864 received-byte and 536,870,912 expanded-byte limits.
- Preserve namespace `sec-owner-lowell-mason`, finite 60-second leases, 20-second renewal, 2-second uncertainty bound, fencing, pacing, cooldowns, and positive HTTP-child drain confirmation.
- Live parser `sec-index-parser-v1`; row schema `sec-index-v1`; fixture parser aliases only in fixture mode. Preserve SEC canonical identities, raw hash addresses, parser/envelope meanings, and unchanged approval/activation/rollback shapes.
- `execution.max_run_seconds=3600` for live commands; launcher default timeout `3300`; validate `0 < N <= execution.max_run_seconds`. Only individually explicit fixture overrides permit fixture time/deadline exceptions.
- Native live execution uses a non-editable installed wheel in `releases/sha256=<release-id>/venv`; no application imports from either checkout or `PYTHONPATH`; no ingestion-time dependency sync, resolution, installation, or interpreter download.
- Resolve filesystem paths against the original config parent; archive normalized absolute paths and hash that effective config. Preserve the original input-byte hash separately. Logical object keys remain safe relative POSIX paths.
- Fresh store and `sec-local-binding-v1`; no old-state import, `image_digest` alias, registry rewriting, store relocation, or automatic cleanup. Bind root/mode/issuer/policies/storage contract, excluding release/parser/range/IDs.
- All 11 low-level commands remain; remove `--config-env`, `--state-dir`, provider identity arguments and cloud execution-ID discovery. Local approval/operator labels are explicit audit labels, not authentication.
- Preserve exit codes 0 and 2–11 with their spec §9 meanings. Pending, approval-gated, quarantined, deferred, and partially published work never become success for convenience.
- Preserve whole-source quarantine for the 51 conflicting retained observations across 2010Q1, 2015Q1, and 2026Q3. No duplicate winner, zero-row exception, parser relaxation, or force bypass.
- No scheduling, notifications, UI, filing-document/XBRL expansion, garbage collection, Windows/shared-filesystem support, or old-store migration.
- Default checks are offline after explicit dependency/artifact setup. L12 is a separate genuine SEC run; retained genuine fixtures and loopback HTTP cannot satisfy it.
- During execution use test-driven-development for library/pipeline changes, develop-testing-strategy below for data/process tests, verification-before-completion at every checkpoint, and requesting-code-review before final readiness claims. This document authoring session executes none of these implementation tasks.

## Decisions

- **D2** (owner, execution clarification, 2026-10-18): Wrap `download.validate_envelope` in the external acceptance harness as well as `collection.validate_envelope` and `etl.transform.validate_envelope`, using the same real validator. Production request handling validates before collection; the third alias is required to count every actual expansion. No production parser, timing, or byte limit changed. Applied in: Task 16.
- **D1** (owner, plan review, 2026-10-17): Commit the reviewed plan and execute it in a fresh session using subagent-driven-development; do not begin implementation in the planning/handoff session. Applied in: Execution handoff. This selects the execution workflow without amending the approved spec.

---

## Reading order, dependencies, and review boundaries

Read the approved spec and this entire plan before execution. Source references below use the pinned revision, not a historical cloud plan. Do not execute the original Azure Stage 7 plan or carry forward its deployment approvals.

| Milestone | Tasks, in order | Checkpoint and evidence |
|---|---|---|
| 1. Audited source and local package | 1 | Import hashes, self-contained corpus, local graph, guarded baseline discovery/build; `specs/evidence/local-port/milestone-1.md` |
| 2. Native identity and complete local records | 2–7 | Descriptor/manifest, acquisition/ETL/workflow strict codec tests and inventory; `specs/evidence/local-port/milestone-2.md` |
| 3. Local execution and recovery | 8–10 | Config/storage/mode/process/operator tests plus full retained discovery; `specs/evidence/local-port/milestone-3.md` |
| 4. Launcher and complete checks | 11–13 | Invocation/logging/signal tests, release setup/reconstruction, complete offline gate; `specs/evidence/local-port/milestone-4.md` |
| 5. Independent acceptance and review | 14–16 | Fresh isolated native proof (L01–L11/L13), implementation review, then separate L12 evidence |

Dependency refinement to spec §12: establish the pure local settings/store contract in Task 3 before context/ETL/workflow codecs, because their tests construct pinned Settings and local stores. Native release construction remains Task 7 and integrated live preflight remains Task 8. This changes implementation ordering only; the approved scope and acceptance contract are unchanged.

Tasks are sequential because the format and process interfaces cross module boundaries. Within a task, independent read-only audits may run in parallel; do not dispatch concurrent edits of `config.py`, `cli.py`, shared support, or the contract families. Each task has its own red/green check and reviewer gate. Pure codec checks in milestone 2 are intentionally narrower than the complete suite, whose first mandatory full gate is milestone 3; never present those early subsets as L02.

Each code-changing step below supplies the interface, core code/edits, invariant cases, and targeted command. Preserve inherited implementations outside the listed boundary rather than reimplementing the pipeline. Execute each listed case as a small red → implementation → green cycle; do not collect all red cases and make a single unreviewable rewrite. After each task, commit only its listed files and record exact commands, exit status, interpreter/release, and fresh output in its milestone record. Reopen a gate if later changes invalidate its evidence.

## File responsibilities

Existing paths below are imported by Task 1. New paths are created only during execution.

| Path | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version`, `packages/sec-edgar-ingest/pyproject.toml` | Single local workspace, runtime/build pins, console entry point |
| `specs/evidence/source-import.json` | Sorted original/destination/SHA-256 import provenance at the pinned source revision |
| `packages/sec-edgar-ingest/tests/fixtures/retained/` | Exactly the retained upstream bytes consumed by local tests |
| `packages/sec-edgar-ingest/tests/fixtures/retained-path-map.json` | Original-to-local fixture paths, sizes and hashes; original manifest stays intact |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/runtime.py` | Strict runtime descriptors, native identity/manifest validation, installed preflight, historical producer validation, release-aware child execution |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/release.py` | Explicit build/export/artifact selection/install/verify/reconstruction; never called by ingestion |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/config.py` | Closed local settings, validation, path normalization, effective hash, context pinning |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/storage/{__init__,contracts,local}.py` | Local factory/binding, safe immutable objects, SQLite conditional records and journal |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/{models,state,worksets,results,discovery,collection,download,coordination,cli}.py` | Retained acquisition with local records and independent source mode |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/` | Retained parser, observations, candidate/generation validation, publication/recovery/audit/captured reads |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/` | Versioned checked calls, selections, provenance, completion, repair, durable summaries |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/local_cli.py` | Immutable invocation preparation, stream retention and engine supervision |
| `scripts/sec-edgar-local`, `scripts/local-bootstrap.py` | Thin project-location bootstrap into a selected installed release; stdlib-only bootstrap |
| `scripts/check-sec-edgar-ingest.sh`, `scripts/verify-native-release.py` | Complete offline verification and isolated installed-wheel proof |
| `scripts/accept-sec-native.py` | Explicitly selected genuine SEC evidence driver, excluded from default checks |
| `conf/sec-edgar-local-fixture.json` | Explicit fixture config; no default synthetic identity in live config |
| `conf/sec-edgar-local.json` | Prepared by release setup after its explicit immutable manifest exists |
| `docs/runbooks/{native-setup,local-ingestion,local-recovery,release-upgrades}.md`, `README.md`, `packages/sec-edgar-ingest/README.md` | Current setup, manual operation, audit, recovery, upgrades and acceptance limits |

## Durable writer/reader/hash/equality inventory

This is the port checklist, not permission to globally replace one format string. For every row, change its writer and strict reader together, recompute only the stated identities, and add missing/wrong-version, unknown-field, canonical-byte and no-mutation refusal cases. Relative source module paths in this section are under `packages/sec-edgar-ingest/src/sec_edgar_ingest/`; all named files are within the tasks’ ownership lists. Line references are baseline navigation aids and will move.

### Acquisition and ETL

| Family / required local version | Writers and identities | Strict readers and equalities | Task |
|---|---|---|---|
| Run context / `sec-local-run-context-v1` | `models.py:315 RunContext`; `cli.py:_new_context,_workflow_context`; `state.py:attempt_key,_run_provenance` | Generic `record_from_mapping`/`_decode_value`, `config.py:pin_context`, `cli.py:_matching_context`; include canonical runtime in Attempt key and every explicit provenance tuple | 4 |
| Source/snapshot worksets / `sec-local-acquisition-v1` | `worksets.py:_payload,_identity,encode_workset,make_source_workset,make_snapshot_workset` | `_decode,_validate_common,_validate_source,_validate_snapshot`; digest excludes own workset ID; snapshot workset keeps source origin context | 4 |
| Acquisition result / `sec-local-command-result-v1` | `models.py:CommandResult`, `results.py:write_result`, `cli.py:_discover_result`, collection result constructors | `CommandResult.from_json`, `results.py:read_result`; canonical bytes/path/outcome and begun Attempt equality | 4 |
| Frozen discovery / original listing receipt | `discovery.py:discover,_persist_receipt`; `state.py:begin_discovery`; retained receipt metadata includes context and its own content hash | `state.py:begin_discovery`, `discovery.py:_verify_receipt_context,reopen_listing`; compare origin runtime/config/parser/schema, frozen pin/units and exact raw receipt | 4 |
| Staging, checkpoints, quarantine | `collection.py:stage_receipt,_retain_attempt_failures`; `state.py:record_receipt`; checkpoint hash excludes `checkpoint_id` | `collection.py:_validated_saved_receipt,_check_collector_context` and recovery paths; request/permit/history/context equality; keep raw addresses | 4 |
| Attempts/transport/halt/failure audit | `state.py:begin_attempt,finish_attempt,begin_request,request_attempt,halt_run,record_directory,record_failure`; `_request_key` depends on `attempt_key` | `request_history,run_halt`, existing immutable inserts; exact contexts and response ordinals; `_run_provenance` returns `dict[str, object]` | 4 |
| ETL frozen command | `cli.py:_existing_etl_context` writes `{context,intent}`; acquisition command intent remains its separate closed shape | Same function strict wrapper/canonical bytes; preserve scan for conflicting Attempts because result path omits runtime/execution | 4 |
| Observation / `sec-local-observation-v1` | `etl/transform.py:transform_member` manifest and immutable Processing adoption | `_read_manifest,_existing`; exact `{format_version,observation,runtime}`, retained producer manifest, canonical bytes, ObservationRef and Parquet validation | 5 |
| Transformed / `sec-local-transformed-workset-v1` | `etl/transform.py:transform_workset`; canonical digest excludes own ID | `etl/contracts.py:encode_transformed,decode_transformed`; `etl/commands.py:validate_workset_ref`; distinguish acquisition origin from transform context | 5 |
| Generation / `sec-local-generation-v1` | `etl/catalog.py:build_candidate`; `etl/contracts.py:GenerationManifest`; canonical manifest bytes | `etl/manifest.py:read_manifest,validate_candidate`; hash/size/path, generation identity, observation validation; permit old producer ≠ current runtime | 5 |
| ETL result / `sec-local-etl-result-v1` | `etl/commands.py:write_etl_result`; `etl/contracts.py:EtlResult` | `read_etl_result,_validate_result`; strict/canonical/path/begun Attempt/context/input/counters and post-object repair | 5 |
| Candidate/Processing/pointer/capture | `etl/state.py:accept_transform,record_candidate`, publication CAS and receipt writers | Canonical immutable candidate equality; exact `POINTER_FIELDS`, `etl/reader.py:capture_from_pointer,validated_manifest` | 5; retain shapes unless embedding changed record |
| Runtime-independent semantic identity | `etl/contracts.py:processing_key`; `etl/manifest.py:source_fingerprint,generation_identity`; `etl/catalog.py:_existing`; `etl/publication.py:unchanged_inputs` | Original cached producer preserved under reuse/force; changing release alone creates no observation/publication | 5, 10 |
| Unchanged audit families | `etl/approval.py`, `etl/rollback.py`, activation/rollback IDs and gate writers in `etl/manifest.py` | Existing approval/activation/rollback/gate readers and strict shapes; referenced generation hashes change naturally | 10 |

### Workflow named formats

All workflow context/provenance envelopes, including named formats below, additionally carry `contract_version=sec-local-contract-v1`. Update hashes over the complete marked payload, excluding only existing self-identity fields; update both sides of constructed equality dictionaries.

| Local format | Writers / hash sites | Strict readers / equality sites | Task |
|---|---|---|---|
| `sec-local-workflow-result-v1` | `workflows/contracts.py:WorkflowResult`; `runner.py:run_workflow`; `results.py:write_workflow_result` | `results.py:read_workflow_result,_validate_report`; exact derived outcome/counts/children/captures/intent | 6 |
| `sec-local-workflow-selection-v1` | `runner.py:select_work` retains current selection-v2 jobs/supersessions; `results.py:freeze_selection` SHA/canonical bytes | `_validate_selection`, all selection/report descriptor equality; remove `LEGACY_SELECTION_FORMAT` branch and optional legacy fields | 6 |
| `sec-local-workflow-child-call-v1` | `checked.py:make_call,_remember_call,call_key,child_attempt_id` | `_validated,_authority,_context_matches,_validate_input_output,unfinished_child,Dispatcher.execute`; explicit image field tuples become runtime | 6, 9 |
| `sec-local-workflow-member-receipt-v1` | `members.py:WorkflowMembers.record,_descriptor`; receipt body hash, member-result index key | `_read_receipt,_validate_context,completed`; descriptor field sets; result report member binding | 6 |
| `sec-local-workflow-member-evidence-v1` | `processing.py:process_member` evidence SHA/address and terminal capture | `validate_member_evidence`; calls/order/inputs/results/captures/resolution, exact member and terminal contexts | 6 |
| `sec-local-workflow-parent-recovery-v1` | `legacy.py:reconstruct_parent` hash/body/descriptor | `provenance.py:validate_parent_recovery,rebuild_recovered_parent,read_parent`; frozen units/progress/recovery/origin equality | 6 |
| `sec-local-workflow-parent-provenance-v1` | `completion.py:capture_parent_provenance,_discovery_snapshot` | `validate_parent_provenance,_validate_discovery,validate_discovery_session` | 6 |
| `sec-local-workflow-member-provenance-v1` | `completion.py:capture_member_provenance` and immutable hash-bound documents | `validate_member_provenance`, member/call/provenance equality | 6 |
| `sec-local-workflow-completion-v1` | `completion.py:evaluate_member` completion capture | `validate_capture`; current generation/captured rows/member/evidence equality | 6 |
| `sec-local-workflow-repair-obligation-v1` | `completion.py:_obligations,_document`; original publish-call SHA and obligation anchor/index | `_read_document,read_repair_obligation`; descriptor/body/source/context/input/quarter/authority equality | 6 |
| `sec-local-workflow-repair-resolution-v1` | `completion.py:_write_resolution`; call SHA, resolution index | `_read_document,validate_resolution_capture,validate_resolution`; successful result/capture/repair-artifact membership | 6 |
| `sec-local-workflow-repair-authority-v1` | `completion.py:_write_repair_authority`; immutable authority and descriptor | `_read_repair_authority`, authority/index/path equality | 6 |
| `sec-local-workflow-legacy-publish-v1` | `completion.py:_legacy_publish_call,_publish_calls` retain low-level publication repair | `read_legacy_publish,_read_publish_call,_call_context`; retain ordinary Attempt branch and repair-artifact receipt key matching | 6, 10 |

### Residual workflow envelopes that also require the marker

Do not interpret a nested JSON object with context/provenance as exempt merely because its enclosing record is versioned.

| Wrapper | Writer(s) | Reader/hash/equality sites |
|---|---|---|
| WorkflowAttempt and `intent.json` `{context,intent}` | `results.py:_index,freeze_workflow` | `cli.py:_workflow_frozen,_workflow_saved`; immutable index/body equality |
| Workflow invocation and report intent | `cli.py:_workflow_main`; `runner.py:run_workflow` | `cli.py` frozen/saved validation; `results.py:_validate_report` exact intent keys and derived counts |
| WorkflowMember `{member_id,source,parent_ref,member_ref}` | `provenance.py:project_member` | `read_member`; constructed copies in `processing.py`, `completion.py`, `results.py`; projection identity and immutable registry equality |
| WorkflowMemberResult descriptor | `members.py:_descriptor,record` | `members.py:completed`; `results.py:_validate_report`; hashed index key must match `runner.py:run_workflow` |
| Result/selection document descriptors | `results.py:_descriptor` | `freeze_selection`, `_validate_report`; byte/hash/path equality |
| `terminal.json`, discovery failure capture, ChildUnfinished terminal details | `processing.py:process_member`; `results.py:_capture_or_validate_discovery_failure`; `checked.py:ChildUnfinished` | `processing.py:validate_member_evidence`; `results.py` terminal/report readers; canonical context/error equality |
| Selection jobs `{member,aliases}` and supersession proofs | `runner.py:select_work`; `members.py:SourceDownloads.supersession` | `results.py:_validate_selection`; retain selection-v2 superseded/served-by/download-time semantics |
| Repair document descriptors and obligation/resolution/authority indices | `completion.py:_document,_obligations,_write_resolution,_write_repair_authority` | `_read_document`, repair readers/validators; rehash complete marked calls/documents; exact descriptors |
| Parent-recovery descriptor; discovery `{session,progress,recovery}` and progress `{unit,value}` captures | `legacy.py:reconstruct_parent`; `completion.py:_discovery_snapshot` | `provenance.py:validate_parent_recovery,rebuild_recovered_parent`; completion discovery validators; preserve source acquisition evidence without rewriting original raw receipts |
| `repair_artifacts` `{quarter,records}` and `{receipt_key,receipt,observation}` records | `completion.py:_repair_artifacts,_expected_artifacts` | `validate_resolution_capture`; source/publication/receipt-key/canonical observation equality |
| WorkflowMilestone | `summary.py:record_reconcile_success` | `last_successful_reconcile`; add exact fields/marker/result-reference validation instead of accepting an unvalidated saved dict |

Task 6 writes a machine-readable list of these owners/readers/identities to `specs/evidence/local-port/contract-inventory.json` and tests the positive/negative cases for every entry. Acquisition state containing a context automatically receives the new nested RunContext version; workflow snapshots of that state additionally receive the wrapper marker. Parser rows, unchanged pointer/audit shapes and raw bodies are not blanket-marked.

## Test strategy (develop-testing-strategy applied)

The inherited suite is unittest, not pytest. Preserve that runner and avoid a new test dependency. For this project, use an explicit, separate genuine-acceptance driver instead of a `network` pytest marker; the default runner discovers every `test_*.py`, including process and isolated-wheel proofs. Do not exclude slow recovery tests from the complete gate. Faults, synthetic clocks and loopback origin selection live only in uninstalled test support.

| Invariant group | Cheapest falsifying layer / fixture | Tests / gate |
|---|---|---|
| Structural: strict config, descriptors, record versions, fields, Arrow schema | Tiny JSON maps; typed records; existing 3–10-row synthetic fixtures | Config/runtime/codec tests, Tasks 2–7; exact schema columns/types from `etl.contracts`, no mock parser |
| Relational: round-trip canonical bytes/IDs; unique SEC row key; duplicate conflicts refuse entire source | Existing pure workset/parser functions; retained raw bytes and hand-written expected rows | Workset/ETL tests, Tasks 3–4/10; preserve 51-conflict quarantine, no mirrored transform oracle |
| Bounds: retries/bytes/expansion, finite timing/leases, no rows exposed before complete capture validation | Scripted recorded responses; real bounded loopback; native process clocks/events | Download/coordination/acquisition/ETL process tests, Tasks 8–10; events bound hangs, no arbitrary sleep-based synchronization |
| Reproducibility: same raw/parser/schema retains semantic identity; release change preserves original producer; retry inputs exactly equal | Immutable corpus; local fixture IDs for cheap tests; two actual non-editable releases for L13 | Runtime/cache/retry/cross-release tests, Tasks 2–6/10/14 |
| Local persistence: reopen/CAS/immutable collisions/crash boundaries/contention/fencing/journal | Temporary native directories, real SQLite, spawned processes | Retained storage/process tests, Tasks 7–10; injected disk-full/corrupt/missing object cases |
| Source-mode isolation: fixture requires pack, exhausts closed; live rejects fixture markers before store/network | Explicit fixture packs and invalid live configs; real production transport against test-only selected loopback | CLI/process tests, Tasks 7–9; production SEC-origin refusal remains independently tested |
| Runtime/process isolation: correct old interpreter executes old child; imports originate from installed payload; guard installed before imports in every child | Test-only bootstrap in a copied harness; actual release envs; tampered app/dependency/interpreter/manifest | Tasks 6/9/14; no production endpoint rewrite or test bypass flag |
| Data/read contract: exact Parquet schema, nonzero accepted counts, uniqueness, per-quarter/source counts, full hash validation | Real transform/publication/read against synthetic and retained fixtures | Task 10/14; zero-row and conflicting specimens remain quarantined; L12 counts are observed, never invented |
| Launcher: archive/replay identity, one engine, status precedence, signals and draining after log faults | Injected file/pipe failures and real subprocess tree, bounded event acknowledgments | Tasks 11–12; no live network |
| Genuine availability/progress | Canonical SEC HTTPS, same native release/coordinator/store, exact bounded predeclared selection | Task 16 only; never part of default discovery |

Default final command: `scripts/check-sec-edgar-ingest.sh`. Core discovery inside it:

```sh
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p 'test_*.py' -v
```

Run explicit setup before offline checks: `uv lock`, `uv sync --locked`, and Task 7 release/artifact preparation. These setup commands may fetch dependencies; no genuine SEC request is authorized by setup. The complete check must fail explicitly if its declared artifact cache is unavailable; never skip installed proofs or fetch missing dependencies during verification.

## Task 1: Audit the source import, materialize fixtures, and establish the local package baseline

**Files:** Create `specs/evidence/source-import.json`, `specs/evidence/local-port/test-disposition.json`, `specs/evidence/local-port/milestone-1.md`, `packages/sec-edgar-ingest/tests/test_source_import.py`, `packages/sec-edgar-ingest/tests/fixtures/retained-path-map.json`, `.gitignore`. Import `pyproject.toml`, `packages/sec-edgar-ingest/pyproject.toml`, `.python-version`, `packages/sec-edgar-ingest/README.md`, retained runtime/tests/fixtures below. Create local `uv.lock`. Modify imported `packages/sec-edgar-ingest/tests/network_guard.py`, `packages/sec-edgar-ingest/tests/support.py`, `packages/sec-edgar-ingest/tests/test_validation.py`, `packages/sec-edgar-ingest/tests/test_discovery.py`, `packages/sec-edgar-ingest/tests/etl_proof.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/__init__.py`.

**Interfaces:** Consumes the pinned Git objects and upstream `tests/fixtures/retained-manifest.json`. Produces sorted `source-import.json` `{format_version:"sec-local-source-import-v1",source_commit,files:[{original_path,destination_path,sha256}]}` and `retained-path-map.json` `{format_version:"sec-local-retained-paths-v1",files:[{original_path,local_path,bytes,sha256}]}`. Test helper `retained_path(original_path: str) -> Path` looks up only manifest-listed paths beneath `tests/fixtures`; it never reads the original repository.

- [x] **Step 1: Add the import/provenance test before extraction.** In `test_source_import.py`, use standard-library `json`, `hashlib`, `unittest`, and `Path` to assert the manifest and all fixture bytes exist. The essential independent fixture oracle is:

```python
expected = json.loads((fixtures / "retained-manifest.json").read_text())
mapped = json.loads((fixtures / "retained-path-map.json").read_text())["files"]
by_original = {item["original_path"]: item for item in mapped}
records = [*expected["records"], *expected["provenance"].values()]
self.assertEqual(len(expected["records"]), 83)
self.assertEqual(len(by_original), len(records))
for record in records:
    entry = by_original[record["path"]]
    body = (fixtures / entry["local_path"]).read_bytes()
    self.assertEqual(hashlib.sha256(body).hexdigest(), record["sha256"])
    self.assertEqual(len(body), entry["bytes"])
```

Run `python3.14 -m unittest discover -s packages/sec-edgar-ingest/tests -p test_source_import.py -v`. Expected red: missing manifest/fixture files. This bootstrap check has no third-party imports.

- [x] **Step 2: Extract selected bytes from the pinned commit and record original hashes before edits.** Use `subprocess.run(["git","-C",source,"show",f"{pin}:{path}"],check=True,stdout=PIPE).stdout`, `Path.write_bytes`, and SHA-256; never `git clone` or `cp -R`. Enumerate tracked paths with `git ls-tree -r --name-only <pin>`. Keep all 45 tracked runtime paths except `deployment.py`, `storage/azure.py`, `storage/identity.py` (42 retained). Keep all 50 package fixture files, package metadata/README, root metadata and `.python-version`. Exclude exactly these cloud/image test modules:

```text
test_adf_interpreter.py
test_azure_alerts.py
test_azure_config_template.py
test_azure_contracts.py
test_azure_identity.py
test_azure_roles.py
test_azure_state_payloads.py
test_azure_template.py
test_image_definition.py
test_run_worker_pipeline.py
```

Exclude support files `adf_interpreter.py`, `image_smoke.py`, `support_adf.py`, `support_azure.py`, `support_template.py`. Retain/adapt the other 46 source test modules and helpers `__init__.py`, `etl_proof.py`, `locked_proof.py`, `network_guard.py`, `support.py`, `support_approval.py`, `support_checked.py`, `support_etl.py`, `support_reconcile.py`, `support_scenario.py`, `support_workflow_evidence.py`, `support_workflows.py`, `workflow_proof.py`. Keep `workflows/legacy.py` and its tests. Write each imported path/hash record sorted by `(original_path,destination_path)`; later port edits do not change these original-byte hashes.

Materialize each original retained-manifest record/provenance path under `tests/fixtures/retained/stage-1/` by removing `specs/evidence/sec-filing-index-ingestion/stage-1/`; store that mapping with exact sizes/hashes. There are 83 records (14,278,591 bytes) and two provenance files. This includes headers/intents/inspection/matrix, not only the ten original specimens. Preserve the original retained manifest bytes. Port the four consumers named in Files to `retained_path`; embedded provenance paths remain original paths interpreted through the map.

In `tests/support.py`, use this complete manifest lookup; import `hashlib` with the other standard-library imports. Consumers pass original paths from the unchanged upstream manifest:

```python
def retained_path(original_path: str) -> Path:
    fixtures = Path(__file__).resolve().parent / "fixtures"
    mapping = json.loads((fixtures / "retained-path-map.json").read_text())
    by_original = {item["original_path"]: item for item in mapping["files"]}
    entry = by_original[original_path]
    target = (fixtures / entry["local_path"]).resolve()
    if not target.is_relative_to(fixtures) or not target.is_file():
        raise ValueError("retained fixture escaped or is missing")
    body = target.read_bytes()
    if len(body) != entry["bytes"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
        raise ValueError("retained fixture bytes differ from the import map")
    return target
```


- [x] **Step 3: Make the bootstrap guard cloud independent and the package graph local.** Remove `_guard_loaded_auth`, provider class patching/import hooks, and unconditional Azure/MSAL imports from `network_guard.py`; preserve all socket/DNS denial, `selected_origin`, spawn propagation and pre-import installation. At this baseline, assert excluded cloud runtime files and cloud dependencies are absent; mixed imported test modules are not imported by the selected baseline. The full retained-runtime/test AST import inventory becomes a mandatory passing gate in Task 10 after those mixed modules are ported; historical text may describe excluded upstream paths. Change package metadata and `__version__` to `0.2.0`; use:

```toml
[project]
name = "sec-edgar-ingest"
version = "0.2.0"
description = "Native local SEC filing-index ingestion"
readme = "README.md"
requires-python = ">=3.14"
dependencies = ["pyarrow==25.0.1", "requests==2.34.2"]

[project.scripts]
sec-edgar-ingest = "sec_edgar_ingest.cli:main"

[build-system]
requires = ["uv_build>=0.12.15,<0.13.0"]
build-backend = "uv_build"
```

Root metadata keeps `package=false`, dependency `sec-edgar-ingest`, workspace source/member and Python floor; remove cloud/transitive constraints and retain only direct pin constraints if needed. Write `.gitignore` for `.venv/`, `data/`, `fixture-data/`, `logs/`, `releases/`, `dist/`, `build/`, `__pycache__/`, bytecode and egg-info; remove old evidence exceptions. Run `uv lock`, then `uv sync --locked`. Record resolved tools and graph, not an old fixed dependency count.

- [x] **Step 4: Verify the intentionally small import baseline and commit.** Run the import test and guarded `test_urls`/`test_validation`; build wheel/sdist. Full CLI import is deferred until the excluded identity import is ported in Task 4; do not claim whole-suite discovery yet.

```sh
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_source_import.py -v
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_urls.py -v
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p test_validation.py -v
uv build --offline --package sec-edgar-ingest
```

Expected: each selected module passes, fixture hashes match, wheel/sdist build, no cloud imports. Record mixed-test dispositions in the inventory (Task 10 lists required extraction). Commit `chore: import pinned local ingestion baseline and fixtures` with only Task 1 paths. Milestone 1 gate: review import map, excluded paths, pins, fixture completeness, baseline outputs.

## Task 2: Define strict native/fixture descriptors and canonical release identity

**Files:** Create `packages/sec-edgar-ingest/src/sec_edgar_ingest/runtime.py`, `packages/sec-edgar-ingest/tests/test_runtime.py` under `packages/sec-edgar-ingest/`; create `specs/evidence/local-port/milestone-2.md`.

**Interfaces:** `validate_descriptor(value: Mapping[str, object]) -> dict[str, object]`; `fixture_descriptor(fixture_id: str) -> dict[str, object]`; `native_descriptor(release_id: str) -> dict[str, object]`; `release_id(identity: Mapping[str, object]) -> str`; `validate_manifest(value: Mapping[str, object]) -> dict[str, object]`. The release JSON has exactly `{format_version:"sec-native-release-v1",release_id,identity}`. `identity` has exactly `application`, `git_revision`, `application_wheel_sha256`, `package_files`, `uv_lock_sha256`, `dependencies`, `interpreter`; application is `{name,version,wheel_filename}`, package file records `{path,sha256}`, dependency records `{name,version,filename,sha256}`, interpreter `{implementation,version,cache_tag,platform_tag}`. Paths here are installed-relative artifact names, never executable paths.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_runtime.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Write pure descriptor/identity tests.** Cover exact keys/formats/kinds; lowercase 64-hex; fixture ID safety; list/object/bool/null kind refusal; native/fixture cross-kind mismatch; unknown keys; missing digest; canonical order; timestamp/path exclusion; different wheel, lock, payload file, interpreter, or dependency hash changes identity. Use independent fixture hashing:

```python
fixture_id = "local-contract-tests-v1"
expected = hashlib.sha256(canonical_json({"fixture_id": fixture_id})).hexdigest()
self.assertEqual(fixture_descriptor(fixture_id), {
    "format_version": "sec-fixture-runtime-v1",
    "kind": "fixture", "fixture_sha256": expected,
})
with self.assertRaises(ValueError):
    validate_descriptor({"kind": "native", "release_sha256": "a" * 64})
```

Run guarded discovery for `test_runtime.py`; expected red: runtime functions absent.

- [x] **Step 2: Implement the descriptor and canonical manifest functions.** Use existing `models.canonical_json`, `parse_json`, `require_hash`, `require_text`, safe relative paths and immutable copies; avoid a top-level import from `models.py` back into runtime. Descriptor validation must be closed:

```python
def validate_descriptor(value):
    if not isinstance(value, Mapping):
        raise ValueError("runtime descriptor must be an object")
    variants = {
        "native": ("sec-native-runtime-v1", "release_sha256"),
        "fixture": ("sec-fixture-runtime-v1", "fixture_sha256"),
    }
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise ValueError("runtime kind must be a string")
    variant = variants.get(kind)
    if variant is None:
        raise ValueError("unsupported runtime kind")
    version, digest_key = variant
    if set(value) != {"format_version", "kind", digest_key}:
        raise ValueError("runtime descriptor requires exact fields")
    if value["format_version"] != version:
        raise ValueError("unsupported runtime descriptor version")
    require_hash(value[digest_key], digest_key)
    return dict(value)
```

Manifest validation requires sorted unique normalized distribution names and package paths, safe artifact basenames, no bytecode/cache paths, application name `sec-edgar-ingest`, current version `0.2.0` for a newly built release, nonempty artifact hashes, CPython 3.14 supported host at build/preflight, and `release_id == sha256(canonical_json(identity))`. Historical manifest validation accepts supported saved native application versions; it does not require equality with executing release/version. Keep host/install paths and timestamps in separate setup metadata, not identity.

- [x] **Step 3: Run the descriptor suite and commit.** Repeat guarded `test_runtime.py`; expected all cases pass with deterministic canonical identity and no filesystem writes/network. Commit `feat: define native release and fixture runtime contracts`. This is the identity building block; installed integrity is Task 7.

## Task 3: Normalize strict local configuration and bind one local persistence backend

**Files:** Modify `packages/sec-edgar-ingest/src/sec_edgar_ingest/config.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/runtime.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/storage/__init__.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/storage/contracts.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/storage/local.py`, `packages/sec-edgar-ingest/tests/support.py`, `packages/sec-edgar-ingest/tests/test_config.py`, `packages/sec-edgar-ingest/tests/test_storage.py`, `packages/sec-edgar-ingest/tests/test_operator_open.py`, `packages/sec-edgar-ingest/tests/support_approval.py`, `packages/sec-edgar-ingest/tests/fixtures/config/local.json`; create `packages/sec-edgar-ingest/tests/support_fs.py`, `packages/sec-edgar-ingest/tests/test_local_config.py`, `conf/sec-edgar-local-fixture.json`, `specs/evidence/local-port/milestone-2.md`.

**Interfaces:** Define `AcquisitionSettings(mode)`, `StorageSettings(backend,root)`, `NativeRuntimeSettings(kind: Literal["native"], release_manifest: str)`, `FixtureRuntimeSettings(kind: Literal["fixture"], fixture_id: str)`, `RuntimeSettings = NativeRuntimeSettings | FixtureRuntimeSettings`, `LoggingSettings(root)`, `ExecutionSettings(max_run_seconds)` and replace worker/jobs/orchestration in Settings. Use the existing strict dataclass-union decoder; opposite-variant fields are absent, never null. `runtime.configured_descriptor(settings: Settings) -> dict[str, object]` returns a fixture hash or strictly validated native manifest digest with no install/network/store work. `parse_config(text: str) -> Settings` validates supplied fields; `load_config(path: Path) -> Settings` validates then normalizes paths against `path.resolve().parent`; `normalize_paths(settings: Settings, config_parent: Path) -> Settings` is idempotent on absolute paths. `Settings.config_sha256` is SHA-256 of canonical normalized mapping. `open_stores(settings: Settings, *, observer: BoundaryObserver | None=None, access: str="worker") -> tuple[StateStore,ObjectStore,LeaseStore | None]` has no `base_path` or credential. Retain the existing helper names `deployment_binding(settings: Settings | None=None, *, root: Path | None=None) -> dict[str, object]` and `table_for(kind: str) -> str` to avoid unrelated caller churn. Their implementations are strictly local: use the explicit root or the normalized settings root; a settings-free test-store constructor requires a supplied root and binds fixture mode/default accepted policies. Preserve SQLite grouping values as explicit local state categories, with no cloud address/table selection.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_local_config.py test_storage.py test_operator_open.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Add config/root/binding tests before implementation.** Build standalone local maps in `test_local_config.py` without calling `fixture_context` or importing CLI; context/pin tests are ported in Task 4. Table-drive duplicate/unknown/nonfinite JSON, exact independent version, local-only storage keys, native/fixture runtime union, live fixture override/parser rejection, explicit max-run/HTTP/issuer policies, path expansion and two arbitrary cwd cases. Compare normalized hashes for semantically equivalent absolute snapshots and original byte hashes for different source text. Essential path test:

```python
first = load_config(config_path)
archived = invocation_directory / "config.json"
archived.write_bytes(canonical_json(first.to_mapping()))
second = load_config(archived)
self.assertEqual(first.storage.root, str((config_path.parent / "../data").resolve()))
self.assertEqual(second.to_mapping(), first.to_mapping())
self.assertEqual(second.config_sha256, first.config_sha256)
```

Binding cases: fixture/live mismatch; moved root; changed issuer/pacing/coordination refused unchanged; changed range/parser/release allowed; operator missing DB/registry/root creates nothing. Run guarded `test_local_config.py`; expected red: current cwd/root/backend behavior. Extract local `test_operator_open.py` imports/classes now so its factory-only cases can run without cloud dependencies.

- [x] **Step 2: Implement the complete supplied JSON contract.** Native runtime config has exactly `{kind:"native",release_manifest:PATH}`; fixture config exactly `{kind:"fixture",fixture_id:ID}`. Storage exactly `{backend:"local",root:PATH}`; acquisition exactly `{mode:"live"|"fixture"}`; logging exactly `{root:PATH}`; execution exactly `{max_run_seconds:3600}` for live. Preserve other spec §5 group fields/values, disallow cloud/worker/jobs/orchestration fields. Fixture group may contain only the two individually explicit boolean overrides; live rejects its presence even when false. Fixture acquisition may use native runtime. Native release paths must resolve to explicit `releases/sha256=<id>/release.json`, with directory digest/manifest identity agreement; no mutable latest.

Filesystem normalization is separate from object-key validation:

```python
def absolute_field(value, config_parent):
    require_text(value, "filesystem path")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = config_parent / candidate
    return str(candidate.resolve())
```

Apply to storage root, logging root, and native manifest path only after complete structural/policy validation. Low-level commands and archived snapshots use the same loader. Tests construct explicit absolute temp-root configs; remove the second root override rule. Task 4 ports `pin_context` once RunContext has its runtime field; in this task test policy validation and normalization without constructing an old context. `load_config_env` is removed.

`deployment_binding` emits exactly `{binding_version:"sec-local-binding-v1",root,acquisition_mode,namespace,sec,coordination,storage_contract:"sec-local-storage-v1"}` using resolved root and normalized policies. It excludes release/parser/selection/IDs. Preserve safe logical-key/symlink defenses and canonical registry equality. `table_for` retains current SQLite grouping (`ActivePointers`, `Approvals`, `Attempts`, `SourceState`) as an internal local contract. Remove cloud routing fields/helpers and `blob_address`; no cloud backend is selected by these groups. Do not delete grouping while SQLite still depends on it. Preserve journal records, lease sentinel distinctions, fsync/atomic writes, WAL/SHM handling, CAS retry bounds and verify-only opens.

- [x] **Step 3: Verify local factory and config policy, then commit.** Run guarded `test_local_config.py`, `test_storage.py`, `test_operator_open.py`; update `fixture_settings` to the new local map/root arguments here. Port/remove only cloud classes/imports in these three modules now per Task 10 disposition. Before this gate, remove two indirect context/CLI dependencies: in `support.fixture_snapshot`, use `datetime(2026, 10, 6, tzinfo=timezone.utc)` directly for `received_at` instead of `fixture_context().started_at`; this is the same fixed specimen instant. Move the existing pure `tree_snapshot` implementation unchanged from `support_approval.py` to `support_fs.py` (hash files, include directories, exclude transient `-wal`/`-shm`); import it from `support_fs` in both `support_approval` and `test_operator_open`. This prevents the factory-only suite from importing CLI before Task 4. The complete pin/context tests in `test_config.py` run after Task 4. Expected: arbitrary cwd/replay stability, binding rejects before DB creation/mutation, local reopen/CAS/objects pass, no Azure fallback/import. Commit `feat: normalize local configuration and bind native stores`. Keep every public command test for the acquisition/CLI tasks; this checkpoint proves the configuration/factory contract only.

## Task 4: Port acquisition contexts, worksets, results, and every provenance comparison

**Files:** Modify `packages/sec-edgar-ingest/src/sec_edgar_ingest/models.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/config.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/state.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/worksets.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/results.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/discovery.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/collection.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/cli.py`, `packages/sec-edgar-ingest/tests/support.py`, `packages/sec-edgar-ingest/tests/fixtures/config/local.json`, `packages/sec-edgar-ingest/tests/test_worksets.py`, `packages/sec-edgar-ingest/tests/test_state.py`, `packages/sec-edgar-ingest/tests/test_discovery.py`, `packages/sec-edgar-ingest/tests/test_collection.py`, `packages/sec-edgar-ingest/tests/test_cli.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/contracts.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/transform.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/commands.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/download.py`, `packages/sec-edgar-ingest/tests/support_workflows.py`, `packages/sec-edgar-ingest/tests/support_checked.py`, `packages/sec-edgar-ingest/tests/support_workflow_evidence.py`, `packages/sec-edgar-ingest/tests/support_etl.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/checked.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/members.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/results.py`; create `packages/sec-edgar-ingest/tests/test_local_acquisition_contracts.py`, all under the package.

**Interfaces:** `RunContext.runtime: Mapping[str, object]` replaces `image_digest`; add required `RunContext.format_version="sec-local-run-context-v1"` and required `CommandResult.format_version="sec-local-command-result-v1"` to serialized fields. Keep construction keyword-only at changed call sites to prevent positional field shifts. The local settings/store contracts are already supplied by Task 3. `attempt_key(context: RunContext) -> str` hashes canonical selected fields including the runtime dict. Existing workset/result API signatures otherwise remain. Consume Task 3’s normalized local settings/store contracts; do not redeclare their types here.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_local_acquisition_contracts.py test_worksets.py test_config.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Add a pure codec matrix before editing each family.** Extend test helpers to construct a fixture descriptor and local config map without opening a store. For context/source/snapshot/result cases assert canonical round-trip, required format, unknown/missing fields, nested runtime refusal, digest tampering and detached mapping immutability. Essential runtime/key regression:

```python
first = replace(context, runtime=fixture_descriptor("release-a"))
second = replace(context, runtime=fixture_descriptor("release-b"))
self.assertNotEqual(attempt_key(first), attempt_key(second))
self.assertEqual(RunContext.from_mapping(first.to_mapping()), first)
old = first.to_mapping()
old.pop("format_version")
old["image_digest"] = "sha256:" + "1" * 64
with self.assertRaises(ValueError):
    RunContext.from_mapping(old)
```

Run guarded `test_local_acquisition_contracts.py`; expected red: old context fields/formats. Persist tests for origin snapshot context vs current collector context, checkpoint hash/canonical bytes, and wrong-runtime retry even if other IDs equal.

- [x] **Step 2: Change the strict records and all inventory sites together.** Use the existing Record machinery; `RunContext.__post_init__` locally imports `validate_descriptor`, validates its mapping then freezes it. Remove `IMAGE_PATTERN`/`image_digest`; add independent config constant, not an alias to acquisition format. Consume the local settings union/normalization/factory already implemented by Task 3. Replace `pin_context` and all remaining field consumers here; no access to removed worker/jobs/orchestration fields may remain. Local fixture settings use explicit absolute roots and fixture ID. Define `fixture_settings(*, root: Path | None=None, **overrides) -> Settings`, `fixture_context(command: str="collect", priority: str="backfill", *, settings: Settings | None=None) -> RunContext`, and `fixture_workset(members, discovery_complete=True, *, context: RunContext | None=None) -> SourceWorkset`. Pure record tests may use the configured default fixture root; every store/CLI helper passes its actual temporary root/settings/context explicitly so root provenance matches the store. Use Task 3’s `runtime.configured_descriptor` in `pin_context` and context constructors; installed-current preflight is Task 7/8, never a synthetic native digest.

> Deviation: `etl_context` now requires explicit `root`; all store-backed helper callers were migrated, including mechanical callers beyond the initial file list.

Change acquisition workset `FORMAT_VERSION` to `sec-local-acquisition-v1`, acquisition result/context versions independently. Explicit provenance comparisons become:

```python
PROVENANCE_FIELDS = (
    "runtime", "parser_version", "schema_version", "config_sha256",
)

def _run_provenance(context):
    return {name: to_mapping_value(getattr(context, name))
            for name in ("run_id", *PROVENANCE_FIELDS)}
```

Apply the inventory’s exact context tuples in receipt reopening, staged recovery, collector origin validation, Attempt key/history/halt and CLI retries. Keep IDs/deadline/intent equality, saved start/pin handling, request ordinals, raw hashes and source/snapshot identities. Add format fields to all constructors; no old field fallback. Source workset context remains acquisition origin when constructing snapshot worksets. Frozen ETL command wrapper remains strict `{context,intent}` with the new nested context.

Port the fixture CLI/support plumbing needed by subsequent ETL/workflow contract tests in this task: remove the excluded `storage.identity` import, provider credential branches, cloud execution-ID lookup, `--state-dir`/`--config-env`; require explicit native correlation/actor labels. Update `support_workflows.CommandHarness`, `support_checked`, `support_workflow_evidence`, and `support_etl` to write explicit normalized temporary-root fixture configs and call `open_stores(settings)` without root/credential overrides. Change fixture sender/parser authorization and checked fixture-pack gates to `settings.acquisition.mode`; no backend string or worker-provenance substring chooses a source. Keep native-current installed verification and full live/refusal/retry matrix in Task 8. This is mechanical removal of obsolete consumers, with the existing fixture-path tests as its oracle; it does not install or exercise a native live release.

- [x] **Step 3: Verify pure local acquisition codecs, audit residual references, and commit.** Run guarded `test_local_acquisition_contracts.py`, `test_worksets.py`, `test_config.py` and newly ported fixture CLI smoke cases; inspect explicit tuple tests in state/discovery/collection as their pure cases are enabled. Port all retained runtime references to the removed fields in this task, including ETL record annotations/validation and workflow explicit field comparisons; Tasks 5 and 6 still own their outer-format and deeper producer/marker behavior. Retain no compatibility alias. Run `rg -n 'image_digest|IMAGE_PATTERN|settings\.worker|settings\.jobs|settings\.orchestration' packages/sec-edgar-ingest/src/sec_edgar_ingest`; expected no matches. Add import smoke checks for every retained runtime module, including CLI, after mechanical provider removal in this task. This prevents stale imports of deleted model names from blocking the next task. Expected: no acquisition writer/reader accepts an old context/result, canonical hashes round-trip, unknown fields refused. Commit `feat: version local acquisition provenance and results`.

## Task 5: Port ETL formats and preserve producer identity under cache reuse

**Files:** Modify `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/contracts.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/transform.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/manifest.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/commands.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/reader.py`, `packages/sec-edgar-ingest/tests/support_etl.py`, `packages/sec-edgar-ingest/tests/test_etl_contracts.py`, `packages/sec-edgar-ingest/tests/test_etl_transform.py`, `packages/sec-edgar-ingest/tests/test_etl_catalog.py`, `packages/sec-edgar-ingest/tests/test_etl_cli.py`; create `packages/sec-edgar-ingest/tests/test_local_etl_contracts.py`, under the package.

**Interfaces:** Observation manifest exact keys `{format_version,observation,runtime}`; `GenerationManifest.runtime: Mapping[str, object]` replaces image digest. Formats are the four ETL versions in the inventory. New runtime helper `validate_producer(runtime: Mapping[str, object], objects: ObjectStore) -> None` validates shape and a saved native manifest at logical key `runtime/native/sha256=<id>/release.json`; fixture descriptors need no native manifest. `retain_manifest(objects, manifest) -> str` writes canonical verified manifest once at that key after preflight, never during verify-only reads. A retained manifest is identity evidence, not permission to execute an old environment. Storage creation hooks call retention in Task 8.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_local_etl_contracts.py test_etl_contracts.py test_etl_transform.py test_etl_catalog.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Add strict ETL codec and cache tests.** For each of observation/transformed/generation/result test correct local format, wrong/missing version, missing/unknown runtime fields, canonical bytes, own-address/hash and retained-producer manifest mismatch. Preserve independent data schema/row assertions. Release-only cache test:

```python
original = transform_member(source, snapshot, first_context, first_settings, objects, state)
first_bytes = objects.read(original.manifest_ref)
reused = transform_member(source, snapshot, next_context, next_settings, objects, state, force=True)
self.assertEqual(reused, original)
self.assertEqual(objects.read(reused.manifest_ref), first_bytes)
self.assertEqual(parse_json(first_bytes)["runtime"], to_mapping_value(first_context.runtime))
```

Here `state` is `EtlState`, each context is pinned against its corresponding settings, and the retained raw/source binding is seeded by `support_etl.seed_snapshot`. Keep the existing case `test_image_change_adopts_original_producer_manifest_even_when_forced` as the behavioral oracle and rename it to runtime. Run guarded `test_local_etl_contracts.py`/`test_etl_transform.py`; expected red: old format/producer field handling.

- [x] **Step 2: Change every ETL inventory writer/reader and producer verification.** Local-format constants change independently; generation and observation validate descriptors and saved identity manifests. Avoid current-runtime equality in historical reads. New reads follow:

> Deviation: Historical producer validation and retention required the shared `runtime.py` interface in addition to the listed ETL files.

```python
value = parse_json(body)
if set(value) != {"format_version", "observation", "runtime"}:
    raise ValueError("observation manifest requires exact local fields")
if value["format_version"] != "sec-local-observation-v1":
    raise ValueError("unsupported observation manifest version")
validate_producer(value["runtime"], objects)
observation = ObservationRef.from_mapping(value["observation"])
if canonical_json(value) != body:
    raise ValueError("observation manifest must be canonical")
```

Replace `test_etl_contracts.py:test_retained_stage2_worksets_and_registry_remain_byte_identical` with old-context/workset/binding refusal tests built from deterministic records and before/after snapshots; do not require unimported Stage-2 stores. Keep upstream raw fixture hash checks in Task 1. Keep subsequent existing content/hash/Parquet checks. Keep processing keys, source fingerprints and generation semantic IDs independent of runtime; reused manifests are returned unchanged, including force verification. Preserve current approval/pointer/rollback formats and readers. `read_manifest` and observation `_read_manifest` are the historical producer validation boundaries, so `capture_quarter`/`read_quarter` retain their API. `retain_manifest` is write-once canonical JSON and checks descriptor digest identity before storing.

- [x] **Step 3: Verify codec/cache behavior and commit.** Run guarded `test_local_etl_contracts.py`, `test_etl_contracts.py`, `test_etl_transform.py`, `test_etl_catalog.py`. Expected: strict local envelopes, exact original producer on cache/force, release-only generation no-op, corrupt saved producer manifest refusal. Commit `feat: adopt local ETL formats and retain producer identity`.

## Task 6: Version the complete workflow contract and remove only obsolete selection compatibility

**Files:** Modify `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/__init__.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/checked.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/completion.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/contracts.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/legacy.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/members.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/provenance.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/results.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/summary.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/cli.py` frozen workflow readers, `packages/sec-edgar-ingest/tests/support_workflows.py`, `packages/sec-edgar-ingest/tests/support_workflow_evidence.py`, `packages/sec-edgar-ingest/tests/support_checked.py`, `packages/sec-edgar-ingest/tests/test_workflow_contracts.py`, `packages/sec-edgar-ingest/tests/test_workflow_results.py`, `packages/sec-edgar-ingest/tests/test_workflow_selection_v1.py`, `packages/sec-edgar-ingest/tests/test_workflow_completion.py`, `packages/sec-edgar-ingest/tests/test_workflow_provenance.py`, `packages/sec-edgar-ingest/tests/test_workflow_processing.py`, `packages/sec-edgar-ingest/tests/test_workflow_legacy.py`, `packages/sec-edgar-ingest/tests/test_workflow_summary.py`; create `packages/sec-edgar-ingest/tests/test_local_workflow_contracts.py` and `specs/evidence/local-port/contract-inventory.json`.

**Interfaces:** Keep existing workflow APIs except the explicitly expanded milestone signatures below, and current selection-v2 semantics, using all local names in the inventory. Add `LOCAL_CONTRACT="sec-local-contract-v1"`, helper `require_contract(value: Mapping[str, object]) -> None` in `workflows/contracts.py`, and required marker to every named and residual workflow envelope listed above. `WorkflowResult` and any other strict record with a marker gets a required serialized field, not a permissive default reader.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_local_workflow_contracts.py test_workflow_contracts.py test_workflow_results.py test_workflow_selection_v1.py test_workflow_legacy.py test_workflow_completion.py test_workflow_provenance.py test_workflow_summary.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Write the per-family contract matrix and nonmutation refusal tests.** Use deterministic newly built local records, never initialized historical evidence stores. Inventory rows record `family`, `writers`, `readers`, `hash_sites`, `equality_sites`, `positive_test`, `negative_test`. For every marker-bearing envelope remove/change marker, add unknown field, alter named version and assert its actual reader refuses. For store-mediated cases compare a tree snapshot plus SQLite logical contents before/after refusal. Include old selection-v1/v2 and old image contexts; all are refused by the local reader. Run guarded `test_local_workflow_contracts.py`; expected red: marker absent/not enforced.

> Deviation: The full 34-family matrix was expanded after the initial child-writer RED rather than before every production edit. Later negative coverage, reviewer regressions, and complete gates establish current behavior, not retroactive sequencing.

- [x] **Step 2: Implement named versions and markers across the complete inventory.** Use:

```python
LOCAL_CONTRACT = "sec-local-contract-v1"

def require_contract(value):
    if value.get("contract_version") != LOCAL_CONTRACT:
        raise ValueError("unsupported local workflow contract")
```

Each writer explicitly inserts the marker before hashing/canonical serialization; each strict reader adds it to its exact-key set and calls `require_contract`. Change `results.py:SELECTION_FORMAT` to `sec-local-workflow-selection-v1`; delete `LEGACY_SELECTION_FORMAT` and its optional-field/legacy-supersession reader branches. Require the current superseded field semantics. Replace `test_workflow_selection_v1.py` historical-store loading with explicit nonmutation refusal tests. Keep `legacy.py:reconstruct_parent,bootstrap_legacy` and `completion.py` legacy-publish descriptor/repair paths, now reading only the new local contracts. Update call/member/index/descriptor hashes and both sides of every constructed equality listed above; no global string replacement in arbitrary payloads.

For WorkflowMilestone, require exactly `{contract_version,workflow,ended_at,result_ref}` and verify the referenced local workflow result before using its successful-reconcile time. Change the signatures explicitly to `last_successful_reconcile(store: StateStore, objects: ObjectStore) -> str | None` and `record_reconcile_success(result: WorkflowResult, reference: str, store: StateStore, objects: ObjectStore) -> None`; update both calls in `emit_summary` and all `test_workflow_summary.py` cases in this task. Validate existing CAS rows and newly referenced results for local contract, exact reference, reconcile command, exit-0 outcome and matching `ended_at`. Missing result, malformed reference, foreign command/non-success or mismatched time refuses that milestone and is reported as the existing supplementary summary error, without rewriting the engine result. Mark discovery/progress snapshots without changing the original retained acquisition receipts they capture. Regenerate expected serialized fixture application artifacts, retaining raw fixture bodies unchanged.

- [x] **Step 3: Run family/selection/legacy/provenance/completion checks and commit.** Run guarded discovery for `test_local_workflow_contracts.py`, `test_workflow_contracts.py`, `test_workflow_results.py`, `test_workflow_selection_v1.py`, `test_workflow_legacy.py`, `test_workflow_completion.py`, `test_workflow_provenance.py`. Expected: every inventory row has tested strict positive/negative coverage; current selection semantics and publication repair both survive; old contracts fail without store mutation. Commit `feat: close local workflow envelopes and preserve repair contracts`.

## Task 7: Build, retain, reconstruct, and preflight immutable native releases

**Files:** Create `packages/sec-edgar-ingest/src/sec_edgar_ingest/release.py`, `packages/sec-edgar-ingest/tests/test_release.py`, `packages/sec-edgar-ingest/tests/test_runtime_preflight.py`, `packages/sec-edgar-ingest/tests/support_release.py`; extend `packages/sec-edgar-ingest/src/sec_edgar_ingest/runtime.py` and `packages/sec-edgar-ingest/tests/locked_proof.py`; create `scripts/prepare-native-release.py`, under root/package as applicable.

**Interfaces:** `release.build_release(project: Path, releases: Path, *, python: Path, artifact_cache: Path, offline: bool=False) -> Path`; `release.reconstruct_release(manifest: Path, destination_releases: Path, *, python: Path) -> Path`; `runtime.preflight(manifest_path: Path, *, executable: Path | None=None) -> VerifiedRelease`; `VerifiedRelease` is a frozen record with `release_id: str`, `manifest: Mapping[str, object]`, `directory: Path`, `python: Path`. `runtime.preflight_current(manifest_path: Path) -> VerifiedRelease` additionally checks that the executing interpreter/import origin is the referenced installation. `prepare-native-release.py --project PATH --releases PATH --python PATH --artifact-cache PATH [--offline]` is explicit setup only. Its separate `--prepare-cache-only` operation needs project/python/cache, reads the lock and prepares hash-verified runtime/build artifacts without requiring a release build or a clean source tree; ordinary build still requires a clean committed tree. `release.prepare_artifact_cache(lock: Path, python: Path, cache: Path, *, offline: bool=False) -> Path` writes the cache inventory. `tests.support_release.proof_releases(project: Path, cache: Path) -> tuple[VerifiedRelease,VerifiedRelease]` makes real A/B proof environments in an independent temporary committed Git repository, or validates an explicitly supplied proof catalog. These are test-support interfaces, never production settings.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_runtime.py test_release.py test_runtime_preflight.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Write red builder/preflight tests with tiny wheel ZIP fixtures and subprocess stubs, then actual install proof cases.** Assert dirty/uncommitted source refusal (including untracked implementation files), stale lock refusal, path-sorted payload inventory including `py.typed`/resources, duplicate/escaping wheel members refusal, artifact hash verification before installation, full transitive inventory equality, non-editable import location, interpreter identity, manifest tamper, wheel/app payload tamper, missing artifact identity, different installed dependency version and no mutation of existing release. Tests must also prove digest ignores timestamps/install paths/setup logs and reconstructing at another location creates a fresh venv there. Run guarded `test_release.py`/`test_runtime_preflight.py`; expected red: builder/preflight absent.

- [x] **Step 2: Implement explicit build/export/artifact/install flow.** Require clean committed implementation, check current lock with `uv lock --check --offline`, then run:

> Deviation: Builds use explicit `--force-pep517`, hash-pinned `uv_build==0.12.24` constraints and build-dependency hashes to retain the mandated backend range without the uv fast-path warning.

```sh
uv build --offline --package sec-edgar-ingest --wheel --sdist
uv export --offline --locked --package sec-edgar-ingest --no-dev --no-emit-workspace --format requirements.txt --output-file runtime-requirements.txt
```

Use a temporary setup directory outside the committed tree for export/build records; final release content includes `wheels/` containing the application wheel under its original valid wheel basename, `uv.lock`, `runtime-requirements.txt`, `artifacts/`, `release.json`, `setup.json`, `venv/`. Record that basename as `identity.application.wheel_filename`; validate it against the built distribution/version/tags, and use the same retained name for install, preflight and reconstruction. Do not rename a wheel to `application.whl`. Select exact compatible wheels during explicit setup using the locked hashes; record every actual selected dependency artifact, including transitives. Preserve the pinned baseline versions of retained runtime libraries when regenerating the graph; any necessary resolver-driven change is a recorded reviewed dependency change, not an opportunistic upgrade. Keep a separate build-tool cache for the pinned resolved uv_build wheel; it is setup evidence, not a runtime dependency. Derive identity from wheel/package bytes, lock, selected wheels and target interpreter before creating the final directory.

Create the content-addressed release directory exclusively; if it exists, verify/reuse a complete matching release or refuse an incomplete/conflicting directory rather than overwriting it. Given the validated `identity`, its `digest`, the selected target `python: Path`, and the requested `releases: Path`, the builder executes these exact argv operations:

```python
release_directory = releases / ("sha256=" + digest)
venv = release_directory / "venv"
wheel = release_directory / "wheels" / identity["application"]["wheel_filename"]
subprocess.run(["uv", "venv", "--python", str(python), str(venv)], check=True)
subprocess.run([
    "uv", "pip", "install", "--python", str(venv / "bin/python"),
    "--offline", "--no-index", "--find-links", str(release_directory / "artifacts"),
    "--require-hashes", "-r", str(release_directory / "runtime-requirements.txt"),
], check=True)
subprocess.run([
    "uv", "pip", "install", "--python", str(venv / "bin/python"),
    "--offline", "--no-deps", str(wheel),
], check=True)
```

The builder independently verifies the application wheel hash before the last command. The requirements file contains only external runtime distributions; no local/editable workspace entry. Never move a venv after creating it. Retain lock/export/wheels and write setup/tool metadata separately; write a usable installation receipt only after an isolated self-verification subprocess succeeds. Failed partial releases remain unusable evidence and are not auto-deleted.

- [x] **Step 3: Implement installed and historical verification without conflating them.** Installed preflight hashes every application payload member, checks exact installed distribution/dependency versions, interpreter implementation/full version/cache/platform tag, non-editable import origin, matching release directory/digest, canonical manifest and required retained artifacts. The self-check executes the referenced Python in isolated mode and returns structured evidence, so a launcher’s bootstrap interpreter is not mistaken for the release interpreter. No ingestion preflight downloads or installs. Historical producer validation checks the retained canonical identity manifest only; it never requires the old interpreter or equality to current release. Missing old executable is an execution failure when dispatch/retry needs it.

> Deviation: Native execution additionally bypasses ordinary bytecode caches using `-I -B -X pycache_prefix=/dev/null` before application imports; preflight verifies the policy without deleting caches.

- [x] **Step 4: Prepare the explicit proof cache, verify, audit provenance inventory, and commit.** First run the setup-only cache preparation with network permitted for locked package artifacts, never SEC. Save `releases/artifact-cache/artifacts.json` containing lock/interpreter identity and sorted `{filename,url,sha256,role}` entries (`runtime` or `build`), hash-check downloads, and populate the declared uv build cache. Unit/process tests then use only this cache with `UV_OFFLINE=1` and `UV_PYTHON_DOWNLOADS=never`.

`support_release.proof_releases` exports the current implementation snapshot (tracked and untracked nonignored implementation files, excluding stores/caches/evidence outputs) plus its lock/metadata to a separate temporary repository, commits it for A, builds A at its final environment path, then adds/commits a harmless included package resource for B and builds B there. It does not pretend an uncommitted checkout is an accepted release: each proof records its actual temporary Git revision and differs from Task 14’s accepted clean fork build. Keep parser/schema unchanged. Cache the factory result for the test session; per-test stores/configs remain separate. Provide this factory to Tasks 9/10/11–13 so every task’s integration checks can run immediately, with no forward dependency on Task 14. An absent cache is an explicit setup error, not a skip. Task 14 repeats the proofs in an independently fresh environment.

Run guarded runtime/release/preflight suites. Expected: positive build/verification/reconstruction and all tamper refusals before store/HTTP; exact artifact inventory includes the application and transitive runtime graph, excludes build-only tools. Update milestone 2 with every contract family and evidence. Commit `feat: prepare and verify immutable native releases`. Milestone 2 gate: reader/writer/hash/equality inventory complete, no old image aliases, cached producer semantics retained. Actual clean release build is repeated after all implementation commits in Task 14.

## Task 8: Separate live/fixture acquisition and restore the complete local CLI contract

**Files:** Modify `packages/sec-edgar-ingest/src/sec_edgar_ingest/cli.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/download.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/commands.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/transform.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/checked.py` mode validation, `packages/sec-edgar-ingest/tests/test_cli.py`, `packages/sec-edgar-ingest/tests/test_etl_cli.py`, `packages/sec-edgar-ingest/tests/test_workflow_cli.py`, `packages/sec-edgar-ingest/tests/test_workflow_config_env.py`, `packages/sec-edgar-ingest/tests/test_operator_identity.py`; create `packages/sec-edgar-ingest/tests/test_local_modes.py`.

**Interfaces:** Preserve the public commands/flags in spec §9 and source inventory; every low-level worker/workflow command requires `--config`, `--run-id`, `--execution-id`, `--attempt-id`, aware UTC `--deadline`. `approve` requires `--approver`, rollback `--operator` and `--reason`. `cli` validation calls current native preflight before any store construction/HTTP, then worker store opens retain the verified native manifest. Fixture provenance is refused in live mode. No public alternate endpoint or root override.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_local_modes.py test_cli.py test_etl_cli.py test_workflow_cli.py test_workflow_config_env.py test_operator_identity.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Write CLI and source-mode refusal tests.** Patch `open_stores` and sender construction with failure-on-call spies and assert invalid config/runtime/fixture combinations exit 2 before either call. Test fixture no pack, corrupt pack, exhausted response sequence, missing URL mapping, live pack/clock/deadline/parser markers, live fixture runtime, removed options, missing execution/actor labels. Exact retry tests change one field at a time: release descriptor, effective config, IDs, intent, parser/schema, deadline; completed replay after deadline succeeds, unfinished expired attempt requires a new attempt. Use existing result readers as the oracle, not logs.

Run guarded `test_local_modes.py`; expected red: local backend still implies fixture and identity imports remain.

- [x] **Step 2: Route transport by acquisition mode and install preflight.** Remove provider identity imports and code branches, cloud environment execution-ID derivation, `--config-env`, `--state-dir`, and credential arguments. Require explicit local labels with existing safety/length bounds. Production transport selection is:

> Deviation: The builder installs and preflight verifies an exact shell console bootstrap establishing the mandatory native source-only import policy before application import.

```python
if settings.acquisition.mode == "live":
    if fixture_pack is not None:
        raise ValueError("live acquisition forbids a fixture pack")
    sender = BoundedSender(settings, clock)
else:
    if fixture_pack is None:
        raise ValueError("fixture acquisition requires its explicit pack")
    sender = fixture_pack.sender(state)
```

Adapt the fixture sender call to the existing `FixturePack.sender` signature after opening the validated fixture store; pack validation itself precedes store construction. Change ScriptedSender, `_FixtureSender`, supported parser checks and all backend/provenance-substring gates to explicit mode policy. Production `BoundedSender` retains canonical SEC HTTPS checks and real Clock; any loopback origin selection is reachable only through the test-support subclass/runner from Task 9. `_Transport.fixture_only` remains internal test support, never a config field or a provenance substring heuristic. Transform/publish validate retained worksets and never construct RequestClient/collector. Preserve shared coordinator and exact frozen attempts, including native preflight for completed replay; a completed result does not authorize using another release identity.

- [x] **Step 3: Verify help, fixture workflow entry points and identity/replay checks.** Run guarded local-mode/CLI/ETL/workflow config tests. Exercise all command help/module version; expected: no removed flags or provider imports, one JSON stdout result and structured stderr, correct exit distinctions. Commit `feat: decouple local persistence from SEC source mode`.

## Task 9: Execute checked children as supervised release-aware subprocesses

**Files:** Modify `packages/sec-edgar-ingest/src/sec_edgar_ingest/runtime.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/checked.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py`, `packages/sec-edgar-ingest/tests/support_checked.py`, `packages/sec-edgar-ingest/tests/workflow_proof.py`, `packages/sec-edgar-ingest/tests/network_guard.py`, `packages/sec-edgar-ingest/tests/test_workflow_checked.py`, `packages/sec-edgar-ingest/tests/test_workflow_process.py`, `packages/sec-edgar-ingest/tests/test_network_guard.py`, `packages/sec-edgar-ingest/tests/test_acquisition_processes.py`; create `packages/sec-edgar-ingest/tests/checked_child_bootstrap.py`, `packages/sec-edgar-ingest/tests/support_process.py`, `packages/sec-edgar-ingest/tests/test_native_dispatch.py`.

**Interfaces:** `runtime.resolve_child(settings: Settings) -> tuple[Path, Mapping[str, object]]` returns the verified selected executable and exact descriptor, choosing fixture parent `sys.executable` only for fixture runtime; `runtime.run_child(python: Path, argv: Sequence[str], *, deadline: datetime, environ: Mapping[str,str]) -> ChildExit`. `ChildExit` is a frozen record `{returncode:int,stdout:bytes,stderr:bytes,drained:bool}`. Preserve `Dispatcher.execute(command, step_id, settings, flags) -> CheckedChild`, `ChildUnfinished` and durable result validation. Add an internal constructor dependency `child_runner=runtime.run_child` for harnesses; no public config/CLI fixture bypass.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_native_dispatch.py test_workflow_checked.py test_workflow_process.py test_network_guard.py test_acquisition_processes.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Add subprocess/authority failures before changing dispatch.** Cover same-release child is a different PID, fixture child is supervised, A-origin collection under B parent uses A executable/config, saved A publication repair uses A, new transform/publish use B; missing A fails before child/store mutation. Persist call then inject child crash, missing result, malformed stdout, mismatched exit/result, late deadline and uncertain shutdown; prove one launch only and no success from stdout alone. Ensure exact call replay does not rerun an ambiguous/finished child. Run guarded `test_native_dispatch.py`; expected red: in-process child execution/current executable.

- [x] **Step 2: Replace in-process StringIO dispatch with verified child execution.** Preserve `_remember_call`, original acquisition/repair settings, exact normalized config snapshot and result identity checks. Select by the child’s saved configuration; never use parent runtime as a substitute. The native argv is built as arguments, not shell text:

```python
child_python, child_runtime = resolve_child(settings)
if child_runtime != to_mapping_value(child.runtime):
    raise ValueError("child executable differs from pinned runtime")
argv = [str(child_python), "-I", "-m", "sec_edgar_ingest", command,
        "--config", str(snapshot), "--run-id", child.run_id,
        "--execution-id", child.execution_id, "--attempt-id", child.attempt_id,
        "--deadline", child.deadline.isoformat(), *flags]
```

Fixture children use `sys.executable` in the same subprocess/result boundary with their explicit pack/descriptor. Strip `PYTHONPATH`, `PYTHONHOME`, Python startup/user-path overrides and `VIRTUAL_ENV` from inherited environment; isolated mode prevents checkout/user-site imports. Freeze canonical absolute config before launch. Use a dedicated POSIX process group and bounded spool/drain for stdout/stderr. On signal/deadline forward termination, drain/wait for the stage and its HTTP children; an unconfirmed drain leaves retained call/lease/recovery evidence and an explicit failed/ownership outcome, never a safe-release assertion. Forceful cleanup may reap processes but cannot fabricate a missing durable result. Compare actual child return code, single JSON result descriptor and independently loaded matching durable result exactly as the inherited dispatcher does.

- [x] **Step 3: Move faults and network guards across both process boundaries in test support.** `checked_child_bootstrap.py` imports only stdlib and the copied guard first, installs it, then imports app modules from the chosen environment and explicit harness hooks. The injected test child runner selects this script using the verified child Python and `-I`; production runner still invokes the module directly. Pass exact selected loopback origins and named fault-point instructions through an immutable test-support payload; the bootstrap validates its schema. Propagate guard/selected origin again in multiprocessing HTTP targets via `guarded_transport_child`; do not rely on the parent’s monkeypatches surviving exec/spawn. Harness imports never add an application checkout to import paths.

Port the twelve inherited process-death points: Attempt begin, child call, collection binding, child result, selection, publication pointer, publication repair, ETL result object, member processing, member receipt, report object and Attempt finish. Each fault has a named synchronization event/acknowledgment and bounded join; production dispatch/start windows remain unchanged. Add a sentinel module that attempts DNS/socket access on import; prove guard denies it in suite, stage, spawned HTTP child and both A/B release harnesses. Production sender itself must still reject loopback and logical clocks.

- [x] **Step 4: Run dispatch/process/guard suites and commit.** Guarded `test_native_dispatch.py`, `test_workflow_checked.py`, `test_workflow_process.py`, `test_network_guard.py`, `test_acquisition_processes.py`. Expected: process isolation, retained call/result authority, correct original runtime, guard-before-import at every boundary, no double launch and conservative ambiguity. Commit `feat: supervise checked children in their pinned native releases`.

## Task 10: Retain local recovery, operator, data-quality and upgrade behavior

**Files:** Modify remaining local tests/support named below, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/completion.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/members.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/summary.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/approval.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/history.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/rollback.py`, `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/publication.py` only where local provenance/actor changes require it; create `packages/sec-edgar-ingest/tests/test_release_upgrade.py`, `packages/sec-edgar-ingest/tests/test_local_failures.py`, `scripts/verify-native-release.py`. Modify `packages/sec-edgar-ingest/tests/test_workspace.py`, `packages/sec-edgar-ingest/tests/test_workflow_installed_lock.py`, `packages/sec-edgar-ingest/tests/locked_proof.py`, `packages/sec-edgar-ingest/tests/etl_proof.py`, `packages/sec-edgar-ingest/tests/workflow_proof.py` before the full-suite gate. Update `specs/evidence/local-port/test-disposition.json` and `specs/evidence/local-port/milestone-3.md`.

**Interfaces:** Keep `capture_quarter(quarter: str, objects: ObjectStore, state: EtlState) -> GenerationCapture | None`, `read_quarter(capture: GenerationCapture, objects: ObjectStore) -> Iterator[IndexRow]`, exact-candidate approvals and immutable rollback records. Retained manifest validation is independent of executable availability; execution of an old-origin attempt still requires its old environment. Source/generation cache identity remains runtime independent.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_release_upgrade.py test_local_failures.py test_workspace.py test_workflow_installed_lock.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Write missing failure/upgrade tests and extract mixed modules without deleting local coverage.** Use this explicit disposition:

> Deviation: Existing SQLite schema is validated read-only before WAL/DDL; malformed-contract refusal also validates Mapping type. No migration or cleanup was added.

| Imported test module | Retain / replace |
|---|---|
| `test_config.py` | Strict JSON/config/pin/deadline/immutability; replace cloud endpoint/image cases with local-mode/path/runtime/no-side-effect cases |
| `test_coordination.py` | Local journal, detached permit, uncertainty, contention, fencing, all local process tests; remove only `azure_leases`/Azure classes |
| `test_download.py` | Real HTTP child timer/drain, durable policy/ordinal/retry bounds and production loopback refusal; replace scripted Azure routing with live-mode refusal |
| `test_approval_activation.py` | First approval, stale/race/reactivation and CLI activation; remove Azure approvals-table routing |
| `test_etl_publication.py` | Keep >64 KiB candidate insert/replace/stale-CAS, every crash/result-repair/capture/corruption case; extract SDK ETag portions into local assertions |
| `test_etl_storage.py` | Logical key safety, exclusive materialize, local revisions/CAS/audit persistence/idempotence, close-failure/conflicting-transform/bounded-retry cases; remove only Azure transport methods |
| `test_operator_identity.py`, `test_operator_open.py` | Explicit actor validation, missing/mismatched root/registry/DB no mutation, no operator lease; remove Azure credentials/classes |
| `test_workflow_config_env.py` | Explicit execution-ID requirement, removed-option refusal, config/snapshot/path behavior; remove config-env success/provider assertions |
| `test_workflow_summary.py` | JSON/events, durable reconcile milestone, gated outcomes; remove SDK routing |
| `test_network_guard.py` | Socket/DNS/selected-origin/closing/pre-import/spawn checks; replace provider stubs with cloud-import denial inventory |
| `test_workflow_selection_v1.py` | Replace old-store compatibility with refusal/nonmutation; retain `test_workflow_legacy.py` recovery |
| `test_workflow_installed_lock.py`, `test_workspace.py` | Fork lock/export/artifact/payload inventory, single member/version and local command contracts; no Stage-2/3 cache or fixed counts |

Add failure matrix for disk-full at object/config/log boundaries, SQLite busy timeout, constructor races, stale CAS, corrupt/missing body/manifest/Parquet, clock uncertainty, lost ownership and uncertain child drain. Preserve evidence and produce explicit result/recovery errors, with no cleanup or force bypass. Assert tree and SQLite contents for rejected old binding/contracts. Run targeted new tests red before each local production correction; isolate unexpected failures before proposing fixes.

- [x] **Step 2: Add two-release and cache/history cases using real installed releases.** The lightweight unit matrix may use fixture descriptors; the integration oracle calls Task 7’s `support_release.proof_releases` immediately for A/B actual clean committed wheel environments from the current implementation snapshot. It does not wait for Task 14. Cover A pending origin collected by B parent under A; A publication repair under saved A; new transform/publish under B; B history/capture/approve/rollback over A; A producer retained under cached/force reuse; missing A environment permits history using retained manifest and refuses execution. A missing/corrupt saved manifest refuses historical read. Do not mutate installed A/B payloads to manufacture releases; commit a benign runtime resource change for B in an isolated proof repository, keeping parser/schema versions unchanged.

Cache/read invariants are asserted directly:

```python
before = objects.read(observation.manifest_ref)
current = capture_quarter(quarter, objects, etl_state)
rows = list(read_quarter(current, objects))
self.assertGreater(len(rows), 0)
self.assertEqual(len({(row.cik, row.archive_path) for row in rows}), len(rows))
self.assertEqual(objects.read(observation.manifest_ref), before)
```

The canonical key is exactly `(cik, archive_path)`, as in the retained transform/catalog SQLite primary keys; do not add form/date to it or create a new deduplication policy. Keep exact Arrow schema, source counts, cross-quarter accounting and complete validation-before-row-exposure assertions. Retained 2010Q1/2015Q1/2026Q3 conflicts still quarantine the entire source; new fixture application outputs use local formats without claiming fresh genuine acquisition.

- [x] **Step 3: Finish installed-proof adapters, then run the full guarded local suite and milestone gate.** Before discovery, remove every old Stage-2/3 wheelhouse/export and fixed dependency-count prerequisite from `test_workflow_installed_lock.py`, `test_workspace.py`, `locked_proof.py`, `etl_proof.py` and `workflow_proof.py`. Use the fork lock/export, Task 7’s declared cache and actual A/B environments. Create `scripts/verify-native-release.py --release PATH --harness PATH --evidence PATH` now; its harness copies fixtures/guard/support independently, executes the selected installed Python outside the checkouts and checks payload/inventory/workflow/audit/read behavior with no app PYTHONPATH. All full-suite installed tests call this verifier or the same support implementation. Task 13 composes it into the documented complete check rather than supplying its first implementation. Keep the negative wrong-transitive-version test and fail on missing cache/artifacts instead of skipping/fetching. First run all targeted storage/acquisition/download/coordination/ETL/operator/workflow suites, then:

> Deviation: The complete fresh installed/default acceptance gate was finalized in Task 14 and renewed after Task 15 fixes; earlier scoped checks were not claimed as complete acceptance.

```sh
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p 'test_*.py' -v
```

All installed-release cases at this milestone run using Task 7’s actual A/B proof factory and prepared cache; none may skip or wait for a later task. Record the exact discovered tests and environment/release IDs. Task 14’s independently fresh verification remains a separate acceptance gate. There must be no cloud-import failure or broad skip masking a retained local module. Audit every source `test_*.py` against `test-disposition.json`, including class/method extraction for mixed modules. Record production 3/sec dispatch/start latency and `permit_expired` outcomes separately from fixture timing allowances. Safe expiry is deferred; an invariant violation or bounded-progress failure blocks readiness and needs a reproducing test/reviewed correction. Commit `test: preserve local recovery audit and upgrade guarantees`. Milestone 3 review checks coverage retention, old-format nonmutation, guard propagation and no widened production timing.

## Task 11: Prepare immutable launcher invocations and exact replay metadata

**Files:** Create `packages/sec-edgar-ingest/src/sec_edgar_ingest/local_cli.py`, `scripts/sec-edgar-local`, `scripts/local-bootstrap.py`, `packages/sec-edgar-ingest/tests/test_local_launcher.py`, `specs/evidence/local-port/milestone-4.md`.

**Interfaces:** `local_cli.prepare_invocation(config_path: Path, command: str, timeout_seconds: float, *, project_root: Path) -> Invocation`; frozen `Invocation` fields `directory:Path`, `config_path:Path`, `argv:tuple[str,...]`, `run_id:str`, `execution_id:str`, `attempt_id:str`, `started_at:datetime`, `deadline:datetime`, `release_id:str`. Invocation JSON has closed `format_version=sec-local-invocation-v1` and records these values plus original config path/byte hash, normalized config/hash, data/log/release paths and exact native descriptor. `local_cli.main(argv: Sequence[str] | None=None) -> int` accepts workflow command, optional `--config`, optional `--timeout-seconds`; default 3300.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_local_launcher.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Add pre-dispatch metadata and refusal tests.** Arbitrary cwd still finds project default config; explicit path resolves correctly; invalid/nonfinite/zero/over-limit timeout refuses; live config needs existing release; IDs are safe unique segments; archived config is normalized absolute bytes used by engine argv; invocation collision never overwrites. Inject mkdir/write/fsync/stream-open failures and assert exit 2, no engine PID, no store/HTTP. Retain partial preparation evidence without dispatch. Test replay metadata preserves original config byte hash separately from effective config hash. Run guarded `test_local_launcher.py`; expected red: launcher absent.

- [x] **Step 2: Implement stdlib-only bootstrap and immutable preparation.** The project shell launcher resolves its own directory, removes inherited Python import overrides and invokes `scripts/local-bootstrap.py` through an already available project Python; it never runs uv. The bootstrap uses only stdlib, validates strict JSON enough to locate an explicit immutable release, then execs that release’s Python with `-I -m sec_edgar_ingest.local_cli`, an explicit project-root argument internal to the bootstrap, and the original user argv. The installed local_cli repeats full config/current-runtime preflight before preparing invocation. No app module is imported from the checkout. A malicious/malformed bootstrap selection never permits store/HTTP before installed verification.

> Deviation: The stdlib selector establishes native source-only bytecode policy as well as isolation before the first installed application import; bare `-I` is insufficient.

Prepare `logs/<run-id>/<attempt-id>/config.json`, `invocation.json`, `stdout.jsonl` and `stderr.jsonl` exclusively. Files use restrictive permissions and fsync before dispatch; write-once publication and unique ID directory creation avoid overwrite/races. Use this complete exclusive-file write primitive (its parent directory is exclusively created and validated before the call):

```python
def write_exclusive(path, body):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
```

Record canonical normalized snapshot, original bytes hash, exact argv/IDs/UTC start/deadline/release, paths, and invocation format. Engine argv references the archived snapshot and release Python directly, never the source config or uv. Resolve `open` at engine invocation pin and retain effective pin/deadline evidence; normal invocation IDs are new, exact replay is manual use of archived original argv/runtime/deadline, never an implicit relaunch. The invocation record is supplementary and cannot stand in for engine completion.

- [x] **Step 3: Verify preparation and commit.** Run guarded launcher preparation cases; expected pre-dispatch errors exit 2, exact absolute snapshot/hash/release metadata, no overwritten invocation and no import from checkout. Commit `feat: archive native launcher invocation identity`.

## Task 12: Preserve stream/status semantics and supervise the engine after logging faults

**Files:** Modify `packages/sec-edgar-ingest/src/sec_edgar_ingest/local_cli.py`, `packages/sec-edgar-ingest/tests/test_local_launcher.py`; create `packages/sec-edgar-ingest/tests/launcher_engine.py`, `packages/sec-edgar-ingest/tests/test_launcher_process.py`.

**Interfaces:** `local_cli.run_invocation(invocation: Invocation) -> int` launches exactly one bounded engine, tees stdout/stderr while retaining original bytes and returns engine status if required logging succeeds, otherwise 9 after dispatch. Pre-dispatch preparation remains Task 11 exit 2. Launcher structured stderr event includes actual engine status when post-dispatch log failure occurs and an output channel remains usable. Engine durable result is never rewritten by wrapper logging failures.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_local_launcher.py test_launcher_process.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Write fault/signal tests before implementing supervision.** Use a test-only engine that emits one result JSON, structured stderr, a child-process start/drain acknowledgment and chosen exit code. Matrix: engine statuses 0/5/7/10/11; stdout/stderr log write failure after dispatch; terminal sink failure; simultaneous engine failure/log failure; SIGINT/SIGTERM; blocked/slow stream; result already durable when log sink fails. Track launch count and descendant exit events. Assert actual JSON stdout bytes are unchanged, streams retained separately, exactly one engine and no dependency tooling. Run guarded `test_launcher_process.py`; expected red: supervision/status behavior absent.

- [x] **Step 2: Implement bounded tee/drain with explicit status precedence.** Start a separate engine process group, drain both pipes concurrently into their archive and corresponding terminal stream, and remember logging errors while continuing to read/discard/drain failed sinks. Forward interrupts/deadline to the engine group; wait for supervised descendants and preserve uncertain completion evidence. Never retry the worker after a stream or status ambiguity. The final precedence is:

```python
if not dispatched:
    return 2
if required_logging_failed:
    emit_launcher_event("logging_failed", engine_returncode=engine_returncode)
    return 9
return engine_returncode
```

Use this after engine drain, not as a substitute for cleanup. Preserve actual engine exit status in the event wherever stderr/archive remains possible. Do not append launcher diagnostics to JSON stdout. Engine result authority remains its durable matching result, even when wrapper returns 9. Add no synchronization dependency on normal logging success.

- [x] **Step 3: Verify streams, signals, failure precedence and commit.** Run guarded `test_local_launcher.py`, `test_launcher_process.py`; expected every pre/post-dispatch distinction, stream preservation and no-relaunch assertion passes with no orphan HTTP/engine child. Commit `feat: supervise native launcher streams signals and failures`.

## Task 13: Add complete offline checks and current setup/recovery/upgrade runbooks

**Files:** Create/replace `scripts/check-sec-edgar-ingest.sh`, update existing `scripts/verify-native-release.py`, `docs/runbooks/native-setup.md`, `docs/runbooks/local-ingestion.md`, `docs/runbooks/local-recovery.md`, `docs/runbooks/release-upgrades.md`, `README.md`, `packages/sec-edgar-ingest/README.md`; modify `packages/sec-edgar-ingest/tests/test_workspace.py`, `packages/sec-edgar-ingest/tests/test_workflow_installed_lock.py`, `packages/sec-edgar-ingest/tests/locked_proof.py`, `packages/sec-edgar-ingest/tests/etl_proof.py`, `packages/sec-edgar-ingest/tests/workflow_proof.py`. Exclude old Azure runbooks rather than importing them.

**Interfaces:** `scripts/verify-native-release.py --release PATH --harness PATH --evidence PATH` runs installed proofs outside both checkouts, using a copied test-only harness and declared release artifacts; never an application PYTHONPATH. Complete check accepts a test-only `SEC_LOCAL_PROOF_CACHE` absolute cache path (default project `releases/artifact-cache`) and optional `SEC_LOCAL_PROOF_CATALOG` JSON with exact `{format_version:"sec-local-proof-catalog-v1",a_manifest,b_manifest,harness}` absolute paths. With no catalog it builds A/B offline via Task 7’s factory; with a catalog it verifies/reuses those immutable releases. It fails on missing artifacts and performs no dependency/network fetching. These variables are test-harness inputs, never production configuration. The same verifier is called by installed unittest integration cases and standalone acceptance recording, sharing one implementation.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_workspace.py test_workflow_installed_lock.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Write packaging/check contract tests.** Assert one workspace member, fork version, direct pins/backend range, local dependency graph and dynamic exact runtime inventory; include wheel `py.typed` and resources, exclude cloud modules. Confirm Task 10’s replacement of every Stage-2/3 wheelhouse/export/fixed-count dependency in `locked_proof`, `etl_proof`, `workflow_proof` and installed-lock tests; any newly exposed reference is fixed here. Retain negative transitive-version tamper with correct direct pins. Test missing cache/artifact fails rather than skips/fetches, guard is installed before discovery imports, and default check never invokes genuine driver/provider/image tooling. Run guarded workspace/installed-lock cases red before edits.

- [x] **Step 2: Implement the complete offline script and connect the isolated proof entry point already supplied by Task 10.** Preserve the first five local source-check operations, change `--frozen` to freshness-checking `--locked`, and remove every ADF/Bicep/image line. The final script contains:

> Deviation: Explicit copied harness paths are authoritative, and upgrade probes reconstruct disposable proof environments before missing-runtime tests so shared A/B inputs remain available.

```sh
#!/bin/sh
set -eu
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p 'test_*.py' -v
uv build --offline --package sec-edgar-ingest --wheel --sdist
uv run --offline --locked --package sec-edgar-ingest sec-edgar-ingest --help
for command in discover collect transform publish backfill daily reconcile candidates approve history rollback; do
  uv run --offline --locked --package sec-edgar-ingest sec-edgar-ingest "$command" --help >/dev/null
done
uv run --offline --locked --package sec-edgar-ingest python -m sec_edgar_ingest --version
uv run --offline --locked --package sec-edgar-ingest python -m sec_edgar_ingest --help
uv run --offline --locked --package sec-edgar-ingest python -m compileall -q packages/sec-edgar-ingest/src
git -c core.whitespace=cr-at-eol diff --check
```

Installed-proof tests invoke `verify-native-release.py` with Task 7’s A/B proof factory output or the explicit catalog and copied harness; they must fail if the declared cache/artifacts are absent, so this is a complete gate rather than a hidden reduced suite. The harness runs through each release’s actual isolated Python/console entry point in an unrelated temporary cwd with source directories unavailable. It checks exact wheel/lock/export/installed inventories, all command help, fixture workflow/reconcile/approval/rollback/captured reads, result retry authority, log/signal behavior and two-release scenarios. It installs the guard before app imports and carries it into checked/HTTP children. Artifact setup happens separately before the check.

- [x] **Step 3: Write concrete current runbooks.** Document explicit dependency setup (`uv sync --locked` development; non-editable release wheel install by builder), exact immutable release layout/setup/reconstruction commands, initial live config preparation after release ID exists, manual launcher workflows and operator low-level commands, no sync during a run and no auto scheduling. Explain sole live issuer is an external operating declaration: the launcher cannot inspect/stop other collectors or Azure. Document same-root multi-command coordination and different-root noncoordination.

Recovery runbook distinguishes completed exact replay, unfinished expired attempt/new attempt, new-ID continuation, pending work/approval gates, quarantines and publication post-pointer repair. Preserve old release environments/manifests; new code can read history, original runtime is required to execute old attempts. Missing runtime is explicit failure. Backups require stopped writers, consistent SQLite backup and matching immutable objects; include WAL/SHM caveat, disk-full/no-cleanup handling, corruption/clock/uncertain-shutdown evidence and no manual pointer edits/Parquet globbing. State supported host and unsupported relocation/shared filesystems. Provide a reader example that captures once then calls `read_quarter` and records validated counts. Describe L01–L11/L13 offline vs L12 genuine acceptance with no historical coverage claim.

- [x] **Step 4: Verify check composition/docs and commit.** Run workspace/installed-lock tests with Task 7’s prepared artifact cache and actual A/B proof environments; `sh -n scripts/check-sec-edgar-ingest.sh`; build and all command help. Mark actual installed L01–L11/L13 run pending Task 14 until fresh evidence exists. Commit `docs: add native setup recovery and offline verification`. Milestone 4 gate: launcher tests, complete offline command composition and no stale provider/image/old-cache requirements; no L12 result inferred.

## Task 14: Run fresh isolated native/offline acceptance, including two actual releases

**Files:** Create `specs/evidence/local-port/offline-acceptance.md`, `specs/evidence/local-port/offline-acceptance.json`, `specs/evidence/local-port/milestone-5.md`; use release/proof scripts and tests from Tasks 6/10/13. Any fixes belong to their owning runtime/test files and require renewed focused tests/review before repeating this gate.

**Interfaces:** Offline acceptance JSON records `format_version=sec-local-offline-acceptance-v1`, implementation Git revision, platform/full interpreter/uv/backend, release IDs, lock/wheel/payload/artifact hashes, commands/exit codes/output paths, discovered test inventory, L01–L11/L13 per-case status and evidence. L12 is explicitly `not_run` here. Evidence files contain observed output, not assumed counts.

- [x] **Step 1: Prepare clean artifacts and proof environments explicitly.** Commit all implementation and tests before building the accepted release. Resolve the exact already available interpreter with `uv python find 3.14`; record it, `uv --version`, macOS/architecture and the resolved build backend. Use `scripts/prepare-native-release.py` against the clean committed fork; dependency/artifact fetching is permitted only in this setup step. Prepare A/B proof releases in a temporary independent Git repository using the same implementation and a committed benign package-resource change for B; same parser/schema, distinct wheel/release IDs. Record every artifact identity and final environment location. Cache build/runtime wheels required by the complete offline check. Do not manufacture A/B by changing a manifest or installed file.

> Deviation: Checkout-denial guard gaps were fixed and independently reviewed before accepted builds; child cwd and every executable PATH fallback candidate are attributed conservatively.

The setup script’s concrete CLI is:

```python
from pathlib import Path
import subprocess

project = Path("/Users/lowell/Projects/sec-edgar-local")
python = subprocess.check_output(["uv", "python", "find", "3.14"], text=True).strip()
subprocess.run([
    python, str(project / "scripts/prepare-native-release.py"),
    "--project", str(project), "--releases", str(project / "releases"),
    "--python", python, "--artifact-cache", str(project / "releases/artifact-cache"),
], check=True)
```

The exact interpreter returned by the read-only lookup is recorded before this setup invocation. Prepare live config only after release ID/manifest exist; populate every default from Global Constraints. This is setup, not live acquisition.

- [x] **Step 2: Run complete offline checks with cloud tools/dependencies absent.** Use a fresh CPython 3.14 macOS arm64 environment and constrained PATH containing only required shell/Git/uv/native Python tools; installed inventory must prove no Azure/MSAL distributions. Set `UV_OFFLINE=1` and `UV_PYTHON_DOWNLOADS=never`, explicit artifact cache, A/B proof release catalog and copied harness paths in test-support configuration. Run `scripts/check-sec-edgar-ingest.sh`, preserving both streams and exit code. Inspect all discovered modules/methods against the disposition inventory; no broad cloud skips or missing local cases. Confirm wheel and sdist builds, console/module help, compileall and diff checks all ran.

Run `scripts/verify-native-release.py` from an unrelated cwd with the accepted release and copied self-contained harness. Test-support audit hooks deny opening/importing/executing from both original checkout paths and install before application imports, in both checked stages and spawned HTTP children. The copied fixture/harness tree is independent; no app source directory is added to sys.path. Proofs assert actual module files lie in the selected release. Test original `source-import` provenance remains data rather than a runtime path dependency. Verify fresh wheel install/reconstruction from retained hash-bearing artifacts without network.

- [x] **Step 3: Exercise real installed A/B upgrade/recovery and negative preflights.** Run `test_release_upgrade` with both actual release environments, copied fixtures and test harness. Check A-origin pending collect and exact publication repair under A; B new transform/publish and B history/approve/rollback/capture over A; cache producer preserved; absent A environment refuses execution but not history; corrupt retained manifest refuses read. Separately clone disposable release environments for app/dependency/interpreter/manifest tamper tests; never tamper accepted releases. Run launcher faults/signals with installed runtime. Record process PID/executable, result/call identities, captured counts and no unexpected network. Bounded loopback uses the unchanged production timer/parser/store code via test-only origin selection.

Measure native dispatch/start latency at unchanged production 3/sec. Preserve safe `permit_expired` records; do not count them as completed acquisition. If progress cannot complete within the bounded offline/live acceptance windows, readiness remains blocked until a reproduced/reviewed correction passes. Fixture allowances do not authorize production timing changes.

- [x] **Step 4: Evaluate and record the acceptance matrix.** L01–L11/L13 require fresh passing output for their exact spec cases, not only a suite exit 0. Record L12 `not_run`; retained fixtures, synthetic workflows and loopback are offline evidence. Include schema, source/generation counts, raw/manifest hashes, validation results, guard propagation and environment inventory. Commit `test: record isolated native offline acceptance`. Gate: do not claim native offline readiness until every required offline row passes; fixes invalidate and rerun affected proof/complete check.

> Deviation: Task 15 runtime admission fixes invalidated the earlier accepted payload; the full 952-test gate and actual native A/B proofs were renewed for the selected `fc68adef` release. Historical Task 14 evidence remains unchanged.

## Task 15: Review the complete implementation and resolve findings before genuine SEC acceptance

**Files:** Create `specs/evidence/local-port/implementation-review.md`; read full implementation diff against destination approved-spec commit `06969c99dce6962995f6917d3507041289c20e02`, approved spec, import manifest and offline evidence. Fixes touch only implicated runtime/tests/docs.

**Interfaces:** requesting-code-review supplies the exact commit range/spec/plan, a read-only whole-branch reviewer and acceptance evidence. Review classifications record concrete file/line, finding, disposition and verification; no cloud deployment/integration approval is inherited.

- [x] **Step 1: Dispatch whole-branch review and perform owner-boundary audit.** Check local-only packaging, complete record inventory, historical vs current runtime verification, original-runtime subprocess recovery, log-failure precedence, safe modes/root binding, guard/process coverage, retained local tests/fixtures and unchanged data policy. Reviewer must inspect code/evidence, not trust this checklist’s claims. Independently confirm no live request has been made by default tests and L12 remains separate.
- [x] **Step 2: Resolve findings critically.** Reproduce/isolate concrete failures, write a failing regression, apply the minimal correction, rerun targeted tests and affected offline gates. Do not convert correctness/provenance/ownership or missing acceptance into a deferral. Record nonblocking observations honestly; scope changes require owner review of exact proposed spec amendment, not silent policy expansion.

> Deviation: Stable typed canonical command admission was added before Attempt creation and ETL side effects; the contract inventory now contains 35 families. Fresh regressions and renewed complete native acceptance followed.
- [x] **Step 3: Record review and selected release.** After all required findings resolve, run fresh complete offline check if implementation changed; rebuild a new clean native release if runtime/dependency payload changed and renew corresponding installed proofs. Record the exact release approved by the technical review for Task 16. Commit `docs: record local implementation review`. This is a technical readiness checkpoint; it does not claim L12, historical completeness or external sole-issuer enforcement.

## Task 16: Record and run a separately bounded genuine SEC acceptance case

**Files:** Create `scripts/accept-sec-native.py`, `scripts/sec-acceptance-child.py`, `packages/sec-edgar-ingest/tests/test_acceptance_selection.py`, `specs/evidence/local-port/sec-acceptance-selection.json`, `specs/evidence/local-port/sec-acceptance.md`, `specs/evidence/local-port/sec-acceptance.json`. Genuine retained bodies/results live in the explicitly selected ignored live root; evidence stores immutable references/hashes/counts and command streams. Do not add this driver to default unittest/check invocation or automatic scheduling.

**Interfaces:** Driver subcommands: `prepare --release PATH --root PATH --evidence PATH`, `run --selection PATH`, `verify --selection PATH`. `prepare` performs no HTTP; writes a complete strict selection record. `run` accepts only a previously prepared, unchanged selection with confirmed sole-issuer declaration, verifies current native release and effective configs, and runs bounded canonical production acquisition. `verify` is offline and reads retained results/generations/captures. Internal subprocess interface: `[selected_python,"-I",absolute_child_script,"--selection",selection_path,"--call",call_path]`. The closed immutable call file has `{format_version:"sec-local-sec-call-v1",selection_sha256,argv,config_sha256}`; `argv` is the exact public low-level command argv, not shell text. The child script has no application source path injection: it verifies the selected installed native interpreter/config, installs the acceptance-only budget wrappers in that process, then calls the actual installed `cli.main(argv)`. It uses the same production transport/parser/coordinator/store; no alternate origin, fixture identity, fixture clock or recorded response. Every resumed low-level process uses the same bootstrap and ledger. The driver uses existing `project_member(parent_ref, source_id, store, objects)` for exact daily body selection, with no new production source-selection/endpoint override.

**Focused red/green command (repository root):** Run this before and after the corresponding implementation step. Initial red must identify the intended missing/incorrect contract, not a missing unrelated cache/import. The task’s gate requires all listed cases green.

```sh
for test_file in test_acceptance_selection.py; do
  uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p "$test_file" -v
done
```

- [x] **Step 1: Write offline selection/limit tests and implement the acceptance-only driver.** Use local maps/fake boundary receipts to test selection validation, counting and evidence; these are offline tests, never SEC requests. Driver `prepare` writes `format_version=sec-local-sec-selection-v1` with exact quarterly source `2024Q1`, daily dates `2026-10-14` and `2026-10-15`, canonical source URLs/IDs, selected reviewed release ID and config hashes, same resolved root/issuer binding, native interpreter, UTC acceptance window, sole-issuer declaration, limits, and evidence paths. Validate those daily dates are within production discovery’s required quarter set at execution time; if not, refuse preparation and require an explicit revised selection record before HTTP. Do not use live `--today` to force a historical test.

> Deviation: Owner decision D2 adds the third real validator alias. Independent review also required a full-driver process watchdog and evidence-derived verification, including failed launches.

Initial run bounds: 900 seconds wall-clock overall; each engine invocation no longer than the remaining window and `execution.max_run_seconds`; at most 20 distinct canonical URLs and 100 total request attempts (five per URL); received bytes at most 134,217,728 cumulatively, expanded bytes at most 1,073,741,824 cumulatively, while retaining all stricter per-response limits from Global Constraints. At most one archived quarterly body and two daily bodies. Distinct URL/attempt counts include listing traffic, retries and restarts; the admission budget conservatively counts a reserved send attempt even when its permit later expires before HTTP starts, while the evidence reports actual sent requests separately. This distinction cannot grant extra admissions beyond 100. Over-bound discovery refuses before another request. Missing/oversize/blocked/quarantined outcomes are retained, not bypassed.

The driver creates `budget.sqlite3` in the evidence directory after selection/runtime verification. Its schema has `metadata(selection_sha256 TEXT PRIMARY KEY, limits_json TEXT NOT NULL)`, `totals(kind TEXT PRIMARY KEY, limit_value INTEGER NOT NULL, charged INTEGER NOT NULL)`, `urls(url TEXT PRIMARY KEY)`, `requests(request_id TEXT PRIMARY KEY, url TEXT NOT NULL, command_key TEXT NOT NULL, ordinal INTEGER NOT NULL)`, and `reservations(reservation_id TEXT PRIMARY KEY, request_id TEXT, kind TEXT NOT NULL, ceiling INTEGER NOT NULL, actual INTEGER, status TEXT NOT NULL)`. Initialize totals for attempts, received bytes and expanded bytes from the immutable selection. Every mutation is a `BEGIN IMMEDIATE` transaction with bounded busy handling; a changed selection hash/limits refuses the existing ledger.

`sec-acceptance-child.py` retains the real class/function objects, then replaces only the CLI sender factory with an acceptance wrapper around the real `BoundedSender` and both `collection.validate_envelope` and `etl.transform.validate_envelope` references with wrappers around the same real `validation.validate_envelope`. The expanded-byte cap counts every actual validation, including transform revalidation and replay, rather than only unique source sizes. These are external evidence-harness wrappers, not installed production flags or fixture substitutes. Before every real sender `.send`, atomically verify the URL is canonical and permitted by the declared discovery/body scope, enforce at most 20 distinct URLs and 100 requests, and reserve the full unchanged per-response received ceiling of 67,108,864 bytes against the cumulative remaining allowance. Refuse before send if that ceiling cannot fit; never send and discover an overrun afterward. Record request ID, exact attempt key and ordinal. After a positively drained receipt, settle to actual received bytes and refund only the verified difference. An exception/uncertain drain leaves its full reservation charged; recovery never refunds an unconfirmed request. Retries and new attempts consume the same global ledger.

Before real envelope validation, reserve the unchanged per-source expanded ceiling of 536,870,912 bytes, then settle to the real validator’s `expanded_byte_count` on success. Validation failure/uncertainty conservatively retains the full charge. Refused budget is a distinct acceptance-limit failure and incomplete run, not a parser quarantine or permission to weaken limits. No wrapper rewrites URLs, extends permits, changes retry policy or supplies fixture bytes. A watchdog uses the original 900-second absolute UTC boundary with a per-process monotonic timer bounded by its remaining duration, forwards cancellation and drains; restarts cannot reset that window. Offline tests cover last-response boundary, crash before/after reservation/settlement, retry, incomplete receipt, child exec propagation, concurrent reservations and unchanged selection enforcement. The driver runs from the selected verified environment; no checkout application imports. Add exact core selection checks:

```python
if selection["quarterly_periods"] != ["2024Q1"]:
    raise ValueError("quarterly selection differs from the recorded bounded case")
if len(selection["daily_dates"]) != 2 or len(set(selection["daily_dates"])) != 2:
    raise ValueError("acceptance requires two distinct explicit daily dates")
if selection["sole_issuer_confirmed"] is not True:
    raise ValueError("sole live issuer must be confirmed before acquisition")
if selection["limits"]["attempts"] > 100:
    raise ValueError("acceptance request budget exceeds the recorded bound")
```

Actual production shared pacing remains 3/sec with one active collector. The declaration records that other project-budget collectors were stopped externally; the driver does not inspect or stop Azure/other machines. If that fact is not known when execution reaches this task, ask for that specific operating fact and keep `run` pending; offline preparation/verification is still complete. The present planning request authorizes writing this task only, not making the declaration or fetching now.

Run guarded `test_acceptance_selection.py` red, implement selection/ledger/driver, rerun green, and code-review the bounded harness before any genuine requests. The accepted runtime must include all runtime fixes; adding only the external harness does not relabel its release. Save exact argv/config snapshots/results and requested bounds before dispatch.

- [x] **Step 2: Prepare the actual run record, inspect it, then execute only its declared source set.** Archive two normalized live configs referencing the same native manifest/root: archived `backfill.start_quarter=end_quarter=2024Q1`; daily `backfill.end_quarter=open`, approved `daily.start_date=2026-10-01`. Both use live mode and production parser. `prepare` inventories existing pending/failed directory work without HTTP and records the resulting required listing URLs; refuse this initial smoke if the 20-URL plan would be exceeded, retaining the existing store unchanged. Do not silently create a second live root to evade its backlog. Daily discovery includes previous/current-quarter leaves plus older handoff/pending/failed quarters and may yield many sources; record this full listing scope and pending remainder separately from the two chosen body dates. Never describe daily.start_date as a strict small body-range selector.

Run quarterly discovery and collect its exact archived source before daily discovery, so the archived pending source does not expand daily inventory. Then run daily discovery, validate the complete retained parent/listing evidence, locate exact requested date/source IDs and use `project_member` for singleton immutable worksets. Collect only those worksets through canonical real transport. Bound listing requests and retries with the same ledger. Do not invoke `daily`/`backfill` runner afterward: it would intentionally collect the unselected backlog. Native installed fixture workflows have already proven workflow orchestration offline.

- [x] **Step 3: Prove restart/reuse, publication, capture and validated read.** Restart a fresh process under the same selected native release and use retained immutable refs; demonstrate reopen/reuse and matching exact result replay without changed config/IDs/intent/deadline. New unfinished expired continuation uses a new attempt; preserve the old attempt evidence. Transform/publish accepted genuine observations using the normal production parser/ETL/CAS and same live root/coordinator. Capture each published generation once, read through `read_quarter`, assert nonempty validated rows, exact schema, unique canonical keys, matching source/generation counts and retained hashes. Preserve expected quarantines as quarantines; list acquisition success separately from ETL acceptance/publication. Record all outcomes, including safely expired permits, pending unselected discoveries, engine statuses and actual budget consumption.

- [x] **Step 4: Evaluate L12 independently and record actual status.** L12 passes only if real native acquisition/persistence/restart/reuse and at least one accepted genuine source complete transform, publication, capture and validated nonempty read under the reviewed release. If every selected source quarantines, no source publishes/read validates, request/time bounds are exhausted, or sole-issuer fact is unavailable, record L12 incomplete and its exact reason. A later selection revision is a new predeclared bounded attempt, retaining earlier evidence; never loosen parser/quarantine/timing rules or loop indefinitely. Commit evidence/driver tests as `test: record bounded genuine SEC native acceptance` only with actual status clearly stated. A successful download alone does not pass L12. Readiness requires both the independent offline gate and a passing L12, without claiming complete historical coverage.

> Deviation: The original genuine attempt and original verification remain incomplete/exit 12 because FrozenMapping-to-dict equality falsely excluded native admissions. A reviewed one-expression canonical comparison fix and separate offline-only analyzer establish L12 pass from the same immutable bounded evidence, with no repeated HTTP, revised selection, relaxed policy, or overwritten original result.

## Acceptance coverage map

| Spec case | Owning tasks | Fresh evidence required |
|---|---|---|
| L01 | 1, 7, 13, 14 | Fork lock/export/wheel/install inventory; cloud distributions/tools absent |
| L02 | 1, 6, 9, 10, 13, 14 | All intended retained/local tests discovered, fixture hashes self-contained, no broad cloud skips |
| L03 | 4, 8, 11, 13, 14 | All console/module commands, installed workflow outside source dirs, no app PYTHONPATH |
| L04 | 3, 4, 8, 11 | Original-parent normalization, archived idempotence, refuse before store/network |
| L05 | 3, 8, 9, 14 | Production bounded transport/local store via exact test-only loopback; closed fixture mode and root binding |
| L06 | 3, 9, 10, 14 | Real SQLite/process contention/CAS/crash/lease/fencing/pacing/cooldown/drain |
| L07 | 5, 6, 8–10, 14 | Local fixture pipeline/workflows/reconcile/approval/rollback/captured-reader durable results |
| L08 | 4, 6, 8, 9, 11, 14 | Exact identity refusal, completed expired replay, unfinished-expired continuation |
| L09 | 2, 5, 7, 8, 14 | Manifest/app/dependency/interpreter tamper refused before writes/HTTP; producer preserved |
| L10 | 3–6, 10 | Every inventory family/wrapper strict round-trip and old-contract/binding nonmutation refusal |
| L11 | 11–14 | Immutable invocation, JSON/events/streams, pre/post-dispatch failures, status/signals/no installs |
| L12 | 16 only | Separate genuine selection/bounds/declaration/results and accepted nonempty published read |
| L13 | 7, 9, 10, 14 | Two actual native releases, original-runtime collection/repair, B audit/read, no provenance substitution |

## Spec-to-task traceability and review checklist

| Spec section | Coverage |
|---|---|
| §1 Outcome/boundaries | Global Constraints; Tasks 1, 7–10, 13–16 |
| §2 Decisions | Local extraction/workspace/runtime/storage architecture and exclusions in Tasks 1–13 |
| §3 Repository/import | Task 1 exact tracked-byte map, 85 retained evidence files, pins/build/layout; Tasks 13–14 self-containment |
| §4 Components/data flow | File responsibilities; Tasks 2–12 checked-result boundaries and retained algorithms |
| §5 Config/filesystem | Tasks 3/4/8/11 strict config, path/hash/root/binding/verify-only rules; Task 13 backups |
| §6 Native provenance | Tasks 2/5/7/8/9/10/11/14 descriptor/manifest/install/preflight/history/execution split |
| §7 Durable formats | Full named/residual inventory; Tasks 4–6/10 negative and canonical tests |
| §8 Acquisition/coordination | Tasks 3/8–10/14/16 modes, canonical HTTP, leases/pacing/drain and startup measurement |
| §9 Commands/operation | Tasks 8/9/11/12/13 exact CLI, launcher status/logs/replay, operators and manual continuation |
| §10 Quality/recovery | Tasks 5/6/9/10/13/16 whole-source quarantine, immutable evidence, crash/repair/audit/read |
| §11 Verification | Test strategy and Tasks 1–16, acceptance map, independent L12 |
| §12 Ordering/handoff | Five milestone gates and execution instructions; source cloud plans explicitly excluded |
| §13 Source/evidence status | Pinned inventories and source import; all new evidence is fresh, baseline observations never relabeled |

Before requesting plan approval, the plan author checks spec coverage, placeholder patterns, all introduced types/functions and intertask signatures, exact command options, task file ownership, and genuine/offline boundaries. The planning review may correct this document only. No task checkbox is checked by authoring/reviewing the plan.

## Planning review record

Reviewed on 2026-10-17 against the approved spec, pinned source and writing-plans requirements. The author checked section-by-section coverage, format/writer/reader/hash/equality ownership, intertask signatures, concrete command flags and prerequisite order. Independent read-only reviews checked spec boundaries and execution interfaces; their concrete findings were corrected in this document:

- Preserve the application’s valid wheel basename through identity, installation and reconstruction.
- Supply ObjectStore explicitly to strict workflow milestone readers/writers and their callers.
- Establish local settings/store prerequisites before context and workflow consumers; remove indirect context/CLI dependencies from the early factory tests.
- Define offline A/B proof-artifact preparation before any task that needs installed subprocess tests; port historical proof adapters before full discovery.
- Correct actual `transform_member` arguments, canonical `(cik, archive_path)` keys, strict descriptor kind validation and child executable bindings.
- Define the genuine-acceptance installed child bootstrap and durable pre-send byte reservations; account expanded validation in both collection and transform.

All implementation checkboxes remain unchecked. The planning checks validate this document; the commands prescribed for implementation and L01–L13 have not been executed by authoring/reviewing it. No changes to the approved spec or original source are part of this plan.

## Historical execution handoff (2026-10-17)

Planning status: reviewed; the owner authorized committing this plan and selected a fresh subagent-driven-development execution session on 2026-10-17. Implementation has not started. No source files were imported, dependencies installed, tests/builds run, stores created, native releases built or genuine SEC requests made by writing this plan. Document verification is not application acceptance.

Selected execution workflow: a fresh session using subagent-driven-development, one task at a time with review between tasks, because each contract family and process boundary needs a focused reviewer. The new session reads this plan plus the approved spec and pinned source; it does not need this planning conversation. Use executing-plans only if the owner chooses inline execution. Establish an isolated execution worktree via using-git-worktrees if the execution checkout contains unrelated work; do not disturb this spec/plan or another developer’s files.

This planning/handoff session stops after committing the reviewed plan and delivering the fresh-session prompt. The selected fresh session may begin Task 1 under D1; this paragraph is a boundary for the planning/handoff session, not an instruction for the executor to stop before Task 1. No implementation, release setup or live acceptance is started in the planning/handoff session. On eventual completion, resolve mandatory acceptance/review work before marking the plan complete; then follow writing-plans’ Plan Completion Protocol and deliberate branch integration/cleanup. If L12 remains incomplete, report it separately and keep readiness/plan completion incomplete rather than retiring the spec as fully implemented.
