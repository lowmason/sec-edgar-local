# Per-Member Cost and the 1b Release Implementation Plan

**Status: COMPLETE (2026-10-28)** — executed via subagent-driven-development; deferred items in specs/deferred_items.md

**Approval:** Approved by the owner, 2026-10-27, with A1, A2 and P1–P8 as proposed (D1 below). This plan authorizes no SEC request.

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task via subagent-driven-development (the default) — or executing-plans when your human partner chose inline execution at the handoff. Steps use checkbox (`- [ ]`) syntax for tracking.

> Roadmap: specs/sec-filing-index-ingestion-roadmap.md, Stage 1b — on plan completion, tick the
> stage and re-validate later stages against what shipped.

**Goal:** Ship a reviewed native release (the 1b release) on which engine checks stop re-reading quarter rows, a quarter that only gains new sources is rebuilt incrementally, and the live reserve is set from measured member costs.

**Architecture:** The work has three parts.

1. A cheap integrity check (C1) replaces the full content check on every engine path (C2). The `publish` child fully checks a full-rebuild candidate once (C3).
2. An eligible quarter (C4) is rebuilt from the base generation's Arrow tables and the delta rows only (C5). A separate equivalence check (C6) recomputes the touched keys with the full path's own resolution code before the gate and pointer steps.
3. The 1b release is built from clean `main`, measured on its own interpreter (§6), and selected in the live config with a reserve set from the measured costs, at two owner checkpoints.

The code lands on a feature branch. It merges to `main` after the full gate and a whole-branch review. The release, the measurement, the live-config selection and the spec amendments run on `main`.

**Tech Stack:** Python 3.14 (CPython 3.14.0, macOS arm64). PyArrow 25.0.1 (`pyarrow.compute`, `pyarrow.parquet`). SQLite through `sqlite3`. Stdlib `unittest` under `packages/sec-edgar-ingest/tests/network_guard.py`. `uv` offline and locked. Installed releases under `releases/sha256=<id>/`.

**Spec:** [specs/completed/sec-filing-index-per-member-cost.md](../../completed/sec-filing-index-per-member-cost.md) (Stage 1b). Parent spec: [specs/sec-filing-index-ingestion-spec.md](../../sec-filing-index-ingestion-spec.md). Inputs: [engine-gap diagnosis](../../evidence/stage1b/diagnosis.md), [D5 measurement](../../evidence/d5-release/measurement.md), [completed plan 4](4-sec-filing-index-bounded-drain.md).

## Global Constraints

Copied from the spec. Every task's requirements include this section.

- No SEC request, live run, or change under `data/` (spec §2). Approval of this plan authorizes no live traffic. The plan 2 revision, written against the 1b release, and its Task 4 owner gate stay the only route to live traffic (spec §10).
- No change to the generation, manifest, receipt, selection or config formats, or to `read_quarter` (spec §2). Selection stays `sec-local-workflow-selection-v1`. Existing receipts stay valid byte for byte. Exact replay returns identical bytes (C7).
- No new workflow outcome or exit code (spec §2).
- No columnar full-rebuild path, and no fix for the history-scan cost (spec §2). §6 measures the history scan only.
- Trust model (S1): after a full content check at publication, engine checks accept a generation by its exact hashes. An incremental candidate gets the C6 equivalence check instead of the full re-derivation.
- The package version stays `0.2.0`. `uv.lock` and the requirement lines of `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` are byte-identical to the D5 build inputs (C9). The D5 build revision is `d68787fe8602e9d81a26d2012feec9bfad5c52df`.
- The 1b release is built by `build_release` from clean committed `main` (C9). The D5 release (`aa8de1ac09fa8ef1a8f638301b25c370af5222e9ef0b02fd117866c2260a6ab4`), `fc68adef…` and older releases are retained (§4.9).
- No platform item. The platform workspace member stays off `main` until the 1b release is built (S3).
- Tests use stdlib `unittest` under `network_guard.py`. Write each test before its implementation (spec §5).
- The full gate is `scripts/check-sec-edgar-ingest.sh`. The D5 gate count is 1020 tests in 64 modules. The new tests add to it (spec §5 item 7).
- Measurement runtime: the installed 1b interpreter with `-I -B -X pycache_prefix=/dev/null`, on fresh stores in new git-ignored directories under the project, not under `/tmp` or `/private/tmp`. Fixture acquisition only (spec §6).
- Floor (C8): `DISPATCH_RESERVE_FLOOR_SECONDS` = max(480, P4 floor rule). The P4 floor rule is max(60, 3 × measured finish seconds, rounded up to 30).
- Reserve rule (spec §6): reserve = 1.25 × slowest member wall + floor, rounded up to 60 s. Fit gate: slowest member wall ≤ 3,300 − reserve.

Execution environment (planning facts, not spec text):

- Tasks 1–10 run on branch `stage1b-per-member-cost` in the worktree `/Users/lowell/Projects/sec-edgar-local/.claude/worktrees/stage1b-per-member-cost` (using-git-worktrees). Leave the existing worktree `.claude/worktrees/platform-stage1-1973ff` alone. A worktree has no `releases/` or `data/`. So every test and gate command in the worktree sets `SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache`. Release paths are absolute paths into the main checkout.
- Tasks 11–14 run in the main checkout `/Users/lowell/Projects/sec-edgar-local` on `main`, after the Task 10 merge.
- In the worktree, `uv run --offline --locked` cannot build an environment (plan 4, Task 3 deviation). Tests that spawn native children also cannot use the main venv, because it holds a `.pth` path to the main checkout's source (plan 4, Task 5 deviation). So create a shadow venv once, in "Before Task 1" Step 3:

  ```bash
  WT=/Users/lowell/Projects/sec-edgar-local/.claude/worktrees/stage1b-per-member-cost
  /Users/lowell/.local/share/uv/python/cpython-3.14.0-macos-aarch64-none/bin/python3.14 -m venv /tmp/s1b-venv
  printf '%s\n%s\n' "$WT/packages/sec-edgar-ingest/src" /Users/lowell/Projects/sec-edgar-local/.venv/lib/python3.14/site-packages > /tmp/s1b-venv/lib/python3.14/site-packages/s1b.pth
  /tmp/s1b-venv/bin/python -I -c "import sec_edgar_ingest, pyarrow; print(sec_edgar_ingest.__file__, pyarrow.__version__)"
  ```

  Expected: a path under `$WT/packages/sec-edgar-ingest/src`, and `25.0.1`. If the path is in the main checkout, put the worktree line first and check again.

  The full gate (Task 10) also needs a `sec-edgar-ingest` console script in the shadow venv and the proof cache inside the worktree (plan 4, `specs/evidence/d5-release/gate.md`, "Environment deviation"):

  ```bash
  printf '%s\n' '#!/tmp/s1b-venv/bin/python' 'import sys' 'from sec_edgar_ingest.cli import main' 'sys.exit(main())' > /tmp/s1b-venv/bin/sec-edgar-ingest
  chmod +x /tmp/s1b-venv/bin/sec-edgar-ingest
  mkdir -p "$WT/releases" && ln -s /Users/lowell/Projects/sec-edgar-local/releases/artifact-cache "$WT/releases/artifact-cache"
  ```
- Test command, from the worktree root (replace `<target>` with a module, class or test name):

  ```bash
  SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache /tmp/s1b-venv/bin/python packages/sec-edgar-ingest/tests/network_guard.py <target> -v
  ```

- The Task 10 full gate and the release build use the `uv` commands from the main checkout, after the merge. The port's full gate took about 56 minutes, so run gates in the background.

## Decisions

- **D1** (owner, plan review, 2026-10-27): A1, A2 and P1–P8 accepted as proposed. That settles: C5 and C6 cover the open-quarter locality exception (A1); the new requirement C11 checks observations by hash on engine paths and in the `publish` child (A2); and the plan-level defaults P1–P8. The amendment tags in Task 1 keep the date 2026-10-27. Owner's words: "D1: I approve plan 5 with A1, A2 and P1–P8 as proposed. Commit it on main." Applied in: Global Constraints, Before Task 1, and Tasks 1–14.
- **D2** (owner, execution pre-flight, 2026-10-27): factor the identity-and-replay block that `build_candidate` and `_incremental_candidate` share into one helper in `catalog.py` (Task 7), and the scenario report header that `run`, `run_finish_only` and `run_scenario` share into one helper in `measure-d5-drain.py` (Task 9). Each implementer logs a `> Deviation:` line. Owner's words: "Extract both". Applied in: Task 7 (`catalog._identify_candidate`), Task 9 (`start_report`).
- **D3** (owner, Task 8 review, 2026-10-28): rewrite the §4.9 consequence in `two-release.md` to what was tested, and fix the evidence-label Minors and the stale `support_release.py` docstring. The stronger incremental-generation scenario is not added. Owner's words: "Narrow the wording". Applied in: Task 8 (dfb5385), Task 14 Step 4.
- **D4** (owner, Task 9 Step 5, 2026-10-28): run Task 9 Step 5 in the owner's Terminal panel, because the agent's worktree guard cannot see it. The script `step5-smoke.sh` has literal paths, uses fixture packs only, and writes only `fixture-data/s1b-smoke-*` in the main checkout and a log in the worktree `.sdd`. No git command runs in the main checkout. Owner's words: "I run it in your Terminal (Recommended)". Applied in: Task 9 Step 5.
- **D5** (owner, Task 9 review, 2026-10-28): fix the three Important findings plus two guards. I1: `summarize` refuses a proposal unless each invocation has its expected exit and one wall per dispatched member. I2: a `history_counts` test and a four-report `summarize` test. I3: the plans are built lazily inside the `try`, so a failure report is always written. Guards: `--work` must be under the project root and not under `<project>/data`, and the history partition is matched exactly. Owner's words: "Fix all three, plus two guards". Applied in: Task 9 (d8352a9).
- **D6** (owner, Task 10 Step 3, 2026-10-28): a Codex second-opinion review is approved for this repository and session. It sends the branch diff and the files that Codex reads to OpenAI. Owner's words: "Yes, run Codex". Applied in: Task 10 Step 3.
- **D7** (owner, Task 10 review batch, 2026-10-28): I2: make the A1 membership check Arrow-only now. C5 and C6 find the non-member base keys with an Arrow filter, no merge logic changes, and C5 and C6 stay independent. I1: test and document the retry block of a C6-refused candidate (a second-publish assertion, the recovery limit in spec §4.3 item 5, the parent §4.6 text and the runbook), with no code change, and correct the "until the C5 bug is fixed" claim. M4: compute C6's expected `row_count` from the full resolution, which rewrites plan-given code. Owner's words, one for each item: I2 "Arrow-only check now (Recommended)"; I1 "Test and document (Recommended)"; M4 "Yes, add it (Recommended)". Applied in: Tasks 6 and 7 code (fe6bca0, 9fef691, dc0418b), Task 10 fix wave (897af75, 6e8e86f), Task 14 Step 1.
- **D8** (owner, Task 10 gate, 2026-10-28): fix the `runtime.py` `forward` race (EPERM from `os.killpg`) on this branch, in one separate commit, test first, then a full gate re-run. Options not chosen: fix on `main` first, or merge with the failure recorded. Owner's words: "Fix it on this branch (Recommended)". Applied in: Task 10 (17d78da, 8c1c321, gate run 6).
- **D9** (owner, Task 10 Step 5, 2026-10-28): merge approved. Owner's words: "Approved: fast-forward merge stage1b-per-member-cost into main, then continue with Task 11." Applied in: Task 10 Step 6 (`main` at 50423a4).
- **D10** (owner, Task 12 Step 4, 2026-10-28): the C8 floor stays 480 s, so `config.py` does not change and Task 12 Step 5 does not apply. The reserve is 1800 s. The fit gate passed (slowest member 1,010.9 s ≤ 1,500 s), so no named limit is needed. Owner's words: "D10: Approved. Floor 480 s and reserve 1800 s. Record it as a Decision and continue with Task 13." Applied in: Tasks 12, 13 and 14 (Steps 2 and 5).
- **D11** (owner, Task 13 Step 3, 2026-10-28): the live config selects the 1b release `9fa189a0…` with `execution.dispatch_reserve_seconds` 1800 (D10). The approval authorizes no SEC traffic (spec §10). Owner's words: "D11: Approved. Select the 1b release in the live config. Record it as a Decision, commit it, and continue with Task 14." Applied in: Task 13 Step 4 (6d80da4).
- **D12** (owner, plan-completion gate, 2026-10-28): four answers. (1) Recovery text: "Reword to the review rule (Recommended)". A blocked quarter recovers when its source set or base changes. Object removal is not a supported step and needs a separately reviewed operational decision. Apply this to §4.6 and the runbook row. (2) The six Task 14 documentation Minors: "Fix them now (Recommended)", in one docs-only commit with a scoped re-review and no code change. (3) Code and test Minors from Tasks 2–9: "Defer as grouped items (Recommended)". (4) The B4 single-candidate item: "Keep it open with this check (Recommended)". Applied in: c9125fd (answers 1 and 2), `specs/deferred_items.md` (answers 3 and 4).

## Defaults for owner review

Planning checked two points against the code and found that each one changes the approved spec. Each item below is applied in the tasks as written. The owner approves or changes each one at plan review. Spec-level items have exact amendment text in Task 1.

- **A1 — Locality fails in an open quarter with a membership authority (spec-level).** Spec §4.3 item 4 says no untouched key changes. A planning probe (2026-10-27, `fixture-data/s1b-plan-probes/locality.py`) disproves this for an open quarter that has a quarterly membership authority:
  - Generation N adds key 2, which the authority does not list. Its change row is `added`, not `unresolved_absence`.
  - The next full rebuild touches only key 3. Key 2 is now in `active` and is still not a member, so `_resolve`'s open-quarter non-member rule makes it `unresolved_absence` (retained). Then `retained_from_generation` is set, so the fingerprint and `generation_id` change.
  - C5's absent set (the base `unresolved_absence` keys minus the touched keys) misses key 2, and C6 compares it as an untouched row.
  - Default: extend C5 and C6. In an open quarter with a membership authority, C5 also marks absent every untouched key of a base `added` change row that the authority does not list. C6 recomputes every base key that the authority does not list with the full path's code. The locality proof below shows that this is the only exception.
  - Alternative: add "an open quarter with a membership authority" to the C4 exclusions. That is simpler, but every daily member of an open quarter whose quarterly index already exists then takes the full path. On SEC, `full-index/<year>/QTR<n>/` exists for the open quarter, so that is the common live case for Stages 3 and 5.
  - Cost not measured: the §6 `open` scenario has no open-quarter quarterly index, so it does not run the A1 path. On that path C6 reads the authority's full key list for each member (a columnar read of two columns). The `open` scenario does not widen without the owner.
  - Applied in: Tasks 1, 6 and 7.
  > Defect: "a columnar read of two columns" did not match the plan's C5 and C6 code (Tasks 6 and 7), which read the whole authority as Python rows for each member (whole-branch review, finding I2). Fixed under D7 in fe6bca0: C5 and C6 use an Arrow filter on the authority's key column.
- **A2 — Repeated observation readbacks (spec-level).** The diagnosis counted only `_validate_row_origins`. A second planning count (F4) shows a second repeated full read of the same size.
  - `transform._read_manifest` and `read_observations` re-parse every row of an observation with `parse_fields` and fill a SQLite table.
  - The engine does this outside the full content check 1,238 times over 246,403 rows in one smoke run.
  - `checked._transformed_input` reads each observation twice. The engine reaches it from `_check_exit`, `validate_member_evidence`, `_validate_report`, `_read_publish_call` and, on every `evaluate_member`, from `_obligations` → `_publish_calls` for **every** historical publish call.
  - At full size, one readback of a 370,321-row observation is a large part of the 250 s `transform` child (D5 `measurement.md`). So after C1 and C2, each member of the `closed` baseline would still re-read every earlier member's quarterly observation about twice, and the §6 fit gate would fail.
  - Default: a new requirement C11. An integrity check of an observation does today's manifest checks and verifies the rows file hash, and reads no rows. The engine paths use it, and so does the `publish` child's check of its incoming references. The full readback stays where an observation is made or rows are used.
  - Alternative: keep the readbacks and accept the measured cost at the §6 checkpoint.
  - A2 does not change the history scan itself (S4). It makes each check in the scan cheap, and §6 still measures the scan's growth.
  - Applied in: Tasks 1–4.
- **P1 — Module placement (plan-level).** The spec's §4.1 table puts C5 in `etl/catalog.py` and C6 in `etl/manifest.py`. C6 must call `catalog._database`, `catalog._load_observations` and `catalog._resolve`, but `catalog` imports `manifest`, so C6 in `manifest.py` makes an import cycle. Default:
  - Hash-checked columnar readers go in a new `etl/columnar.py`.
  - C4 and C5 go in a new `etl/incremental.py`, called from `catalog.build_candidate`.
  - C6 goes in a new `etl/equivalence.py`.
  - `catalog` imports `equivalence` inside the one function that calls it, as `manifest.read_manifest` already does for `runtime`.
  - Separate files also make C6's independence from C5 easy to review. They share only the readers in `columnar.py`, which hold no merge logic.
  - Applied in: Tasks 5–7.
- **P2 — The §5 item 2 count is split (plan-level).** Workflow children are native processes (`support_process.CheckedRunner`), so a patch in the test process counts engine calls only. Default: one test runs a fixture workflow and asserts zero `_validate_row_origins` calls in the engine process, and then one call per `read_quarter`. Another test calls `publish_quarter` directly and asserts exactly one call for a full rebuild and none for an incremental build, an unchanged quarter or a replayed candidate. Together they prove the §5 item 2 statement. Applied in: Tasks 3 and 4.
  > Defect: "none for … a replayed candidate" contradicts C3. A replay goes through `catalog._existing`, which runs the full check. No zero-count assertion was written. After the whole-branch review (finding I3), c8949bc added `test_full_check_budget.PublishBudgetTests.test_a_replayed_incremental_candidate_is_fully_checked_once`.
- **P3 — Two callers that C2 and C3 do not name (plan-level).** `publication.repair_publication` (a `publish`-child repair after a committed pointer) uses C1. `history.quarter_history` reaches C1 through `capture_quarter`. It reads manifests only and exposes no rows. Applied in: Tasks 3 and 4.
- **P4 — The full path's pre-manifest `validate_files` stays (plan-level).** It is part of the one full rebuild and is not a repeated check. C3 counts `_validate_row_origins`. The incremental path does not run it. C6's row-level check of the delta rows replaces it. Applied in: Tasks 4 and 7.
- **P5 — Byte identity of the incremental writer (plan-level).** `catalog._write_parquet` makes one `write_table` call for each 8,192-row batch (`BATCH_ROWS`). The incremental writer writes the sorted table in the same slices, each made single-chunk with `combine_chunks()`, with the same `ParquetWriter` settings. Key order is the byte order of `cik` and `archive_path`, as SQLite `BINARY` collation gives. The oracle tests include a quarter of more than 8,192 rows and a delta that moves rows across a batch boundary. Applied in: Task 7.
- **P6 — The two-release origin is built from the D5 revision (plan-level).** `support_release.origin_release` gains a `revision` argument. The two-release tests build `d68787fe…` into its own committed repository, as plan 4 built `3ca50c7`. They do not use the installed D5 directory, so the tests stay self-contained. Applied in: Task 8.
- **P7 — Measurement design (plan-level).**
  - Each §6 scenario runs in its own process through a new `scenario` subcommand, which writes its own report in a `finally` block. A `summarize` subcommand combines the reports.
  - The `authority` scenario publishes a closed quarter (2026Q3) from 10 full-size daily files (36,520 rows), then adds a full-size quarterly authority (370,321 rows) that lists 90% of the daily keys, so withdrawals and the gate occur.
  - Member wall runs from the member's `sibling_completion` call to the return of `WorkflowMembers.record`.
  - The fixture `max_run_seconds` is 43,200 for every scenario, because the `closed` baseline's 14 first publications may take more than 6 hours under load.
  - The D5 `run` and `rebuild` subcommands stay unchanged, because they produced the D5 record.
  - Applied in: Task 9.
- **P8 — Existing tests that forge a hash-consistent generation (plan-level).** Under S1, an engine path accepts a generation by its hashes. If an existing test plants a forged but hash-consistent generation and expects an engine path to refuse it, move that assertion to `read_quarter`, which still fully checks, and record a `> Deviation:` line. Never weaken a test of `read_quarter`, `approve`, `rollback` or `catalog._existing`. Planning found one message assertion on a changed path (`test_etl_rollback.py:106`). It is on the rollback path, which keeps the full check. Applied in: Tasks 3 and 4.

## Facts established while planning (read-only, 2026-10-27)

- **F1 — `main` equals the D5 source.** `git diff d68787f HEAD -- packages/sec-edgar-ingest/src uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml scripts` is empty. Eleven commits since `d68787f` touch `specs/` only.
- **F2 — Every full-check site, and its treatment in this plan.**

  | Site | Check today | Treatment |
  |---|---|---|
  | `etl/reader.py` `capture_quarter` | `validated_manifest` | C1 (Task 3) |
  | `etl/reader.py` `read_quarter` | `validated_manifest` | unchanged, full (C3) |
  | `etl/commands.py:205` `_affected_quarters` | `validated_manifest` | C1 (Task 3) |
  | `workflows/completion.py:428` `validate_capture` | `validated_manifest` | C1 (Task 3) |
  | `workflows/completion.py:688, 705, 770, 789` repair resolutions | `validated_manifest` | C1 (Task 3) |
  | `workflows/completion.py:825` `evaluate_member` | `validated_manifest` | C1 (Task 3) |
  | `workflows/checked.py:299` `_validate_input_output` | `validated_manifest` | C1 (Task 3) |
  | `workflows/checked.py:313` gated candidate in a checked result | `validate_candidate` | C1 (Task 3) |
  | `workflows/runner.py:352` `source_revert_gaps` | `validated_manifest` | C1 (Task 3) |
  | `etl/publication.py:56` `repair_publication` | `validated_manifest` | C1 (Task 4, P3) |
  | `etl/publication.py:86` previous generation | `validated_manifest` | C1 (Task 4) |
  | `etl/publication.py:102` built candidate | `validate_candidate` | C1 (Task 4). `build_candidate` already checked it. |
  | `etl/catalog.py:61` `_existing` | `validate_candidate_content` | unchanged, full (C3) |
  | `etl/catalog.py:185` `_stage_gate` | `validate_candidate` | C1 (Task 4) |
  | `etl/catalog.py:209` active generation | `validate_candidate` | C1 (Task 4) |
  | `etl/catalog.py:223–227` fingerprint no-op | through `_stage_gate` | C1 (Task 4) |
  | `etl/catalog.py:270` pre-manifest `validate_files` | row read | full path only (P4) |
  | `etl/catalog.py:282` new full-rebuild candidate | `validate_candidate_content` | unchanged: the one full check (C3) |
  | new incremental candidate | — | C6 (Task 7) |
  | `etl/approval.py:97` `load_candidate` | `validate_candidate` | unchanged, full (C3) |
  | `etl/rollback.py:105` rollback target | `validated_manifest` | unchanged, full (C3) |
  | `etl/history.py:39` through `capture_quarter` | `validated_manifest` | C1 (P3) |
  | `workflows/checked.py:241, 244` `_transformed_input` | two observation readbacks | C11 (Task 3, A2) |
  | `workflows/completion.py:420` `validate_capture` | observation readback | C11 (Task 3, A2) |
  | `workflows/completion.py:815` `evaluate_member` | observation readback | C11 (Task 3, A2) |
  | `etl/publication.py:75` incoming references | observation readback | C11 (Task 4, A2). The build reads these rows in full anyway. |
  | `etl/transform.py` `_write_rows`, `_existing` (the `transform` child) | observation readback | unchanged |
  | `etl/catalog.py` `_load_observations`, `etl/manifest.py` `_validate_row_origins` | observation readback | unchanged (the full build and the full content check) |

- **F3 — Locality probe (basis of A1).** `fixture-data/s1b-plan-probes/locality.py`, run on the main checkout's `.venv`: generation N has `added 1, unresolved 0` with change `[('added', …000002.txt)]`. Generation N+1 has `added 1, unresolved 1, retained True` with changes `[('unresolved_absence', …000002.txt), ('added', …000003.txt)]`.
- **F4 — Observation readbacks (basis of A2).** `fixture-data/s1b-plan-probes/count-obs-reads.py` wraps `transform._verify_parquet` and `manifest._validate_row_origins` in the engine process, and runs `scripts/measure-d5-drain.py run --scale smoke` on the installed D5 interpreter (`-I -B -X pycache_prefix=/dev/null`). Work directory: `fixture-data/s1b-plan-probes/obs-smoke-20261027T204033Z`. Exit 0. Results:
  - 2,636 observation readbacks over 545,299 rows in total, and 517 full content checks (the diagnosis counted 517 too).
  - 1,398 readbacks (298,896 rows) are inside full content checks. C1 and C2 remove them from the engine.
  - 1,238 readbacks (246,403 rows) are outside them. The largest chains are `validate_member_evidence > read_child_capture > _validate_input_output > _transformed_input` (174 calls) and `evaluate_member > _obligations > _publish_calls > _transformed_input` (120 calls).
  - The engine readback sites are `workflows/checked.py:241` and `:244` (`_transformed_input`, two readbacks for each observation), `workflows/completion.py:420` (`validate_capture`) and `:815` (`evaluate_member`). The `publish` child's site is `etl/publication.py:75`.
- **F5 — Children are native processes in tests.** `support_workflows.CommandHarness.invoke` patches `cli.WorkflowDispatcher` with `support_process.checked_dispatcher`, whose `CheckedRunner` starts each child with `runtime.native_python_argv` (basis of P2).
- **F6 — Two stores give identical generations.** `fixture_snapshot` uses a fixed `received_at` (2026-10-06 UTC), and the fixture runtime descriptor does not depend on the store root. A planning probe (`fixture-data/s1b-plan-probes/twin.py`) built the same two generations in two fresh stores and got the same manifest SHA-256 (`baf0453124b5ecdb…`) and file hashes. So an oracle test can build one lane incrementally and a twin lane by the full path, and compare bytes.
- **F7 — `_write_parquet` layout.** One `ParquetWriter(path, schema, version='2.6', compression='snappy', use_dictionary=False, use_compliant_nested_type=False)`. Rows in `ORDER BY cik,path` (data) or `ORDER BY cik,path,change_type` (changes), written in 8,192-row `pa.Table.from_pylist` batches. A file with no rows has no `write_table` call (basis of P5).
- **F8 — `objects.verify` raises `Conflict('immutable object differs from expected hash or length')`.** The full check raises `Conflict('generation file hash or length differs')` for the same fault. The class is the same, as C1 requires. A missing file raises `FileNotFoundError` on both paths.
- **F9 — The plan's C5 and C6 code was run before review.** `fixture-data/s1b-plan-probes/code/drive.py` loads this plan's `columnar.py`, `incremental.py` and `equivalence.py` blocks and its Task 2 checks into the D5-equal checkout code, with no repo change. It builds each Task 7 oracle case by the full path, then runs `build_incremental` and `write_table` on the same inputs:
  - All 11 cases give byte-identical data and change files, identical counts, the same retained basis, and C6 acceptance. That includes the A1 flip and the 9,000-row batch shift.
  - The five Task 6 refusal cases raise the expected messages.
  - This is a planning check, not acceptance evidence. Tasks 6 and 7 still write each test before its code.

## Locality proof (spec §4.3 item 4; written before C5)

Notation. `A` is the active generation, and its gate is `clear`. `S` is the selected source set: `A.sources` plus the delta sources `D`, whose `source_id` values are new (C4). `M` is the membership authority. C4 makes it the same reference in `A` and in `S`, or absent from both. For a key `k`, `O_A(k)` is its observations in the quarter over `A.sources`, and `O_S(k)` is the same over `S`. `T` is the set of keys of `D`'s observations in the quarter (the touched keys). `U_A` is the set of keys of `A`'s `unresolved_absence` change rows. `best(·)` is `_load_observations`' ranking: preference, period and receipt descending, then `source_id` ascending.

A full rebuild over `S`, with `A`'s rows as `active`, resolves each key by `_resolve`. For `k ∉ T`, `O_S(k) = O_A(k)`. Mode and membership are unchanged. Take each case of `k` in `A`'s own build:

1. **`k ∈ U_A`.** `k` was absent in `A`'s build: no proposed row, or open mode with `M` and `k` not a member. Both conditions still hold, so `k` is absent again. In closed mode with `M`, an absent key is withdrawn, and gate `clear` means `A` withdrew nothing. So this case is open mode, or closed mode without `M`. The full rebuild re-emits `unresolved_absence` with `before = after =` the `A` row, which is the row in `A`'s change file.
2. **`k` is in `A`'s data, `k ∉ U_A`, and `k` was in `A`'s own base.** `A`'s row is `best(O_A(k))`, and `k` was not absent. The rebuild proposes the same row, membership is unchanged, and so there is no change and no provenance refresh.
3. **`k` is in `A`'s data and `A`'s change row for `k` is `added`.** The rebuild proposes the same row. `k` is now in `active`. It is absent only in open mode with `M` and `k` not a member. **This is the one exception (A1):** the rebuild emits `unresolved_absence` for `k` and keeps the `A` row. In every other mode there is no change.
4. **`k` is not in `A`'s data.** `A` proposed nothing for `k`, or closed mode with `M` deleted it as a non-member. Both hold again, so `k` is not in the output.

So for untouched keys the full rebuild gives `A`'s data rows. Its change rows are the rows of `U_A \ T`, re-emitted, plus, in open mode with `M`, one `unresolved_absence` row for each key of an `A` `added` row that is untouched and not a member.

For a touched key `k ∈ T`, `O_S(k) = O_A(k) ∪ O_D(k)`:

- If `k` is in `A`'s data and `k ∉ U_A`, `A`'s row is `best(O_A(k))` (cases 2 and 3). So `best(O_S(k))` is the best of `A`'s row and `O_D(k)`. The `A` row is ranked by the source that its `source_id` names in `A.sources`.
- If `k ∈ U_A`, then `O_A(k)` is empty, or open mode with `M` and `k` not a member. In the first case `best(O_S(k)) = best(O_D(k))`. In the second, `k` stays absent whatever the ranking gives. So the `A` row is never ranked.
- If `k` is not in `A`'s data, then `O_A(k)` is empty, or closed mode with `M` deleted `k`. In the second case the same filter deletes it again. So ranking `O_D(k)` alone gives the full rebuild's result.

The closed-quarter filter, the open-quarter absence rule and the change rules then apply to `k` exactly as `_resolve` applies them. The inputs per touched key are its `A` row, whether `k ∈ U_A`, its delta rows and its membership flag. The untouched exception adds one input: the membership flags of the keys of `A`'s `added` rows. Also, `A`'s data keys are all members in closed mode with `M`, so an eligible build never withdraws, and its gate is `clear`.

---

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `specs/sec-filing-index-per-member-cost.md` | Stage 1b spec; amendments A1 (and A2 if approved) | 1 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/manifest.py` | C1 `check_candidate_integrity` | 2 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/transform.py` | C11 `checked_observation` | 2 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/reader.py` | C1 `checked_manifest`; `capture_quarter` uses it | 2, 3 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/commands.py` | `_affected_quarters` uses C1 | 3 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/completion.py`, `checked.py`, `runner.py` | Engine call sites use C1 | 3 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/publication.py` | Previous generation and built candidate use C1 | 4 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py` | Active generation and `_stage_gate` use C1; `_load_observations` reader seam; incremental branch | 4, 5, 7 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/contracts.py` | `BUSINESS_FIELDS` and `arrow_row`, moved from `catalog` | 7 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/columnar.py` (new) | Hash-checked columnar reads of generation files and observations; key masks | 5 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/equivalence.py` (new) | C6 equivalence check | 6 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/incremental.py` (new) | C4 eligibility, C5 build and writer | 7 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/config.py` | C8 floor constant (only if §6 gives more than 480) | 12 |
| `packages/sec-edgar-ingest/tests/support_catalog.py` (new) | `Lane`: one store with the catalog fixtures | 2 |
| `packages/sec-edgar-ingest/tests/test_etl_integrity.py` (new) | C1 and C11 tests | 2 |
| `packages/sec-edgar-ingest/tests/test_full_check_budget.py` (new) | §5 item 2 (P2) | 3, 4 |
| `packages/sec-edgar-ingest/tests/test_etl_columnar.py` (new) | Columnar readers and the reader seam | 5 |
| `packages/sec-edgar-ingest/tests/support_incremental.py` (new) | `Twin`: the oracle harness | 7 |
| `packages/sec-edgar-ingest/tests/test_etl_equivalence.py` (new) | C6 acceptance and refusals (§5 item 5) | 6 |
| `packages/sec-edgar-ingest/tests/test_etl_incremental.py` (new) | Oracle, fallback and budget cases (§5 items 2–4) | 7 |
| `packages/sec-edgar-ingest/tests/support_release.py` | `origin_release(…, revision=…)` | 8 |
| `packages/sec-edgar-ingest/tests/test_release_1b.py` (new) | Two-release tests (§5 item 6) | 8 |
| `scripts/measure-d5-drain.py` | §6 scenarios, one process per scenario, load and history fields | 9 |
| `specs/evidence/stage1b/` | Locality, gate, release, measurement and two-release records | 6, 8, 10–13 |
| `conf/sec-edgar-local.json` | C10 | 13 |
| `specs/sec-filing-index-ingestion-spec.md` | §§4.6, 4.8, 4.9 amendments | 14 |

---

## Before Task 1

- [x] **Step 1: Plan review (HUMAN).** The owner approves the plan, and answers A1, A2 and P1–P8. Log the answer as D1 in `## Decisions`, in the owner's words. Apply each plan-level change the owner asks for.
- [x] **Step 2: Commit the plan on `main`.** Do this only when the owner approves the commit as part of D1. The worktree is cut from `main`, so the plan must be committed first. Otherwise the branch cannot track the plan, and the Task 10 merge stops on the untracked file.

```bash
cd /Users/lowell/Projects/sec-edgar-local
git add specs/plans/5-sec-filing-index-per-member-cost.md
git commit -m "docs(specs): add plan 5 for roadmap Stage 1b"
```

- [x] **Step 3: Create the worktree and the shadow venv.** Use the using-git-worktrees skill for branch `stage1b-per-member-cost` at `.claude/worktrees/stage1b-per-member-cost`. Then run the shadow-venv commands in Global Constraints, "Execution environment".

---

### Task 1: Stage 1b spec amendments A1 and A2 (owner-approved at plan review)

Run on the branch, in the worktree. Each amendment tag carries the plan-review date. The text below uses 2026-10-27. If the owner approves on another date, use that date in every tag. If the owner rejects A1 or A2, skip its steps and follow the alternative recorded in `## Decisions`.

**Files:**
- Modify: `specs/sec-filing-index-per-member-cost.md` (§2 in-scope list, §3 rows C5 and C6 and a new row C11, §4.3 item 4, §5 items 1 and 3)

**Interfaces:**
- Consumes: the owner's plan-review answer (logged as D1).
- Produces: the amended requirement text that Tasks 2–7 implement. C11 is a new requirement ID.

- [x] **Step 1: A2, §2.** Replace:

```text
- An integrity check that reads no rows, and the move of engine-side checks to it (C1, C2).
```

with:

```text
- An integrity check that reads no rows, and the move of engine-side checks to it (C1, C2), and the
  same check for observations (C11; owner, plan 5, 2026-10-27).
```

- [x] **Step 2: A1, row C5.** In the C5 row, replace:

```text
when the quarter has a membership authority, that source's observations limited by a columnar filter to the touched keys.
```

with:

```text
when the quarter has a membership authority, that source's observations limited by a columnar filter to the touched keys and, in an open quarter, the keys of the base `added` change rows (owner, plan 5, 2026-10-27).
```

Then, in the same row, replace:

```text
The absent set is the base change file's `unresolved_absence` keys minus the touched keys that gain a proposed row.
```

with:

```text
The absent set is the base change file's `unresolved_absence` keys minus the touched keys that gain a proposed row. In an open quarter with a membership authority, it also holds every untouched key of a base `added` change row that the authority does not list, because `_resolve`'s open-quarter non-member rule makes that key absent at the next rebuild (owner, plan 5, 2026-10-27).
```

- [x] **Step 3: A1, row C6.** In the C6 row, replace:

```text
For the touched keys, the expected rows, change rows and counts come from
```

with:

```text
For the recomputed keys (the touched keys and, in an open quarter with a membership authority, every base key that the authority does not list; owner, plan 5, 2026-10-27), the expected rows, change rows and counts come from
```

- [x] **Step 4: A2, row C11.** After the C10 row of the §3 table, add:

```text
| C11 | An integrity check of an observation reads its manifest with today's address, canonical-form, producer and identity checks, and verifies the rows file SHA-256 and byte count. It reads no rows. It refuses with the same error classes as `transform._read_manifest`. Engine paths use it for an observation reached through a Processing row, a transformed workset or a capture: `evaluate_member`, `validate_capture` and `checked._transformed_input`. The `publish` child uses it for its incoming references. The full readback stays in the `transform` child, the full content check, and the full rebuild's reads of source rows. (owner, plan 5, 2026-10-27) |
```

- [x] **Step 5: A1, §4.3 item 4.** Replace:

```text
   its membership row (if any), and whether the base change file names it `unresolved_absence`. Untouched
   keys keep their rows. No touched key that was present can become absent, because sources only grow and
   membership does not change (C4). The plan proves this against `_resolve` before it builds C5. Oracle
```

with:

```text
   its membership row (if any), and whether the base change file names it `unresolved_absence`. Untouched
   keys keep their rows, with one exception. In an open quarter with a membership authority, a key that the
   base added and that the authority does not list becomes `unresolved_absence` at the next rebuild, whether
   or not the delta touches it. C5 and C6 handle that case (owner, plan 5, 2026-10-27; plan 5, Locality
   proof). The plan proves this against `_resolve` before it builds C5. Oracle
```

- [x] **Step 6: A2 and A1, §5.** Replace:

```text
Reads no rows (patched `iter_file_rows` is not called).
```

with:

```text
Reads no rows (patched `iter_file_rows` is not called). **C11** refuses a changed rows-file byte and a
   changed observation manifest, and reads no rows (patched `_verify_parquet` is not called) (owner, plan 5,
   2026-10-27).
```

Then replace:

```text
a non-member touched key; a closed daily-only quarter.
```

with:

```text
a non-member touched key; a closed daily-only quarter; an open quarter with a membership authority and an
   untouched key that the base added and the authority does not list (owner, plan 5, 2026-10-27).
```

- [x] **Step 7: Check and commit.** Leave the status line unchanged. Run:

```bash
grep -o "owner, plan 5" specs/sec-filing-index-per-member-cost.md | wc -l
git diff --stat
```

Expected: `8` (the C5 row holds two tags on one line, so count occurrences, not lines), and one changed file. Commit:

```bash
git add specs/sec-filing-index-per-member-cost.md
git commit -m "docs(specs): amend the Stage 1b spec for locality and observation checks"
```

---

### Task 2: Integrity checks C1 and C11

**Files:**
- Create: `packages/sec-edgar-ingest/tests/support_catalog.py`
- Create: `packages/sec-edgar-ingest/tests/test_etl_integrity.py`
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/manifest.py` (add `check_candidate_integrity` after `validate_candidate`)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/reader.py:13, 28–39` (`validated_manifest`, new `checked_manifest`)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/transform.py:108–125` (`_read_manifest`, new `_observation_manifest` and `checked_observation`)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `manifest.check_candidate_integrity(candidate: Candidate, objects: ObjectStore) -> None` (C1 on a candidate: manifest identity, every file's hash and length, and the gate record).
  - `reader.checked_manifest(capture: GenerationCapture, objects: ObjectStore) -> GenerationManifest` (C1 on a capture; an `awaiting_approval` generation needs its exact approval, as `validated_manifest` requires).
  - `transform.checked_observation(path: str, objects: ObjectStore) -> ObservationRef` (C11).
  - `support_catalog.Lane(day=date(2026, 10, 7), command='transform')` with `pin(day)`, `observation(period='2026Q4', kind='quarterly', rows=None, seconds=0) -> ObservationRef`, `build(refs, previous=None, quarter='2026Q4') -> Candidate`, `rows(candidate, role='data') -> list[dict]`, `path(name) -> Path`, `close()`; `support_catalog.capture(candidate) -> GenerationCapture`; `support_catalog.row(name='Example', number=1, day='2026-10-01', form='10-K', cik=123456) -> bytes`.

- [x] **Step 1: Write the shared test fixture.** Create `packages/sec-edgar-ingest/tests/support_catalog.py`:

```python
"""One fresh store with the catalog test fixtures (Stage 1b tests share it; it holds no test cases)."""
import io
import re
import tempfile
import zipfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from support import fixture_snapshot, fixture_settings, fixture_source, store_bundle
from support_etl import etl_context
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.etl.catalog import build_candidate
from sec_edgar_ingest.etl.contracts import GenerationCapture
from sec_edgar_ingest.etl.manifest import iter_file_rows
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.transform import transform_member

HEADER = b'CIK|Company Name|Form Type|Date Filed|File Name\n-----\n'


def row(name='Example', number=1, day='2026-10-01', form='10-K', cik=123456):
    return f'{cik}|{name}|{form}|{day}|edgar/data/{cik}/{cik:010d}-26-{number:06}.txt\n'.encode()


def capture(candidate):
    return GenerationCapture(candidate.manifest.quarter, candidate.manifest.generation_id,
                             candidate.manifest_ref, candidate.manifest_sha256, candidate.manifest_bytes)


class Lane:
    """A store, its ETL state and a pinned context. Call `close` when done."""

    def __init__(self, day=date(2026, 10, 7), command='transform'):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store, self.objects, leases = store_bundle(self.root)
        leases.close()
        self.state = EtlState(self.store)
        self.settings, self.context = etl_context(command=command, root=self.root)
        self.pin(day)

    def close(self):
        self.store.close()
        self.temp.cleanup()

    def pin(self, day):
        self.settings = fixture_settings(etl={'parser_version': self.context.parser_version},
                                         fixture={'allow_clock_override': True}, root=self.root)
        context = replace(self.context, config_sha256=self.settings.config_sha256, pinned_on=None, effective_config={})
        self.context = pin_context(self.settings, context, day)[0]

    def observation(self, period='2026Q4', kind='quarterly', rows=None, seconds=0):
        source = fixture_source(period, kind)
        body = HEADER + (row() if rows is None else rows)
        if kind == 'quarterly':
            target = io.BytesIO()
            with zipfile.ZipFile(target, 'w') as archive:
                info = zipfile.ZipInfo('master.idx', (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, body.replace(b'File Name', b'Filename').replace(b'\n', b'\r\n'))
            body = target.getvalue()
        else:
            body = re.sub(rb'\|(\d{4})-(\d{2})-(\d{2})\|', rb'|\1\2\3|', body)
        snapshot = fixture_snapshot(source, body)
        snapshot = replace(snapshot, received_at=snapshot.received_at + timedelta(seconds=seconds))
        self.objects.put_once(snapshot.raw_path, body)
        return transform_member(source, snapshot, self.context, self.settings, self.objects, self.state)

    def build(self, refs, previous=None, quarter='2026Q4'):
        return build_candidate(quarter, capture(previous) if previous else None, tuple(refs),
                               self.context, self.settings, self.objects, self.state)

    def rows(self, candidate, role='data'):
        return [value for ref in candidate.manifest.files if ref.role == role
                for value in iter_file_rows(ref, self.objects)]

    def path(self, name):
        return self.root / 'objects' / name
```

- [x] **Step 2: Write the failing tests.** Create `packages/sec-edgar-ingest/tests/test_etl_integrity.py`:

```python
"""Stage 1b C1 and C11: integrity checks read manifests and file hashes, never rows."""
from network_guard import install
install()

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from support_catalog import Lane, capture, row
from sec_edgar_ingest.etl import manifest as generation
from sec_edgar_ingest.etl import transform
from sec_edgar_ingest.etl.manifest import (approval_for, approval_ref, check_candidate_integrity,
                                           read_manifest)
from sec_edgar_ingest.etl.reader import checked_manifest, validated_manifest
from sec_edgar_ingest.etl.transform import _read_manifest, checked_observation
from sec_edgar_ingest.models import canonical_json
from sec_edgar_ingest.storage.contracts import Conflict


class GenerationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.lane = Lane()
        self.addCleanup(self.lane.close)
        self.candidate = self.lane.build([self.lane.observation(rows=row() + row(number=2))])
        self.capture = capture(self.candidate)

    def corrupt(self, name, body):
        path = self.lane.path(name)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(body(original))

    def test_accepts_the_exact_generation_without_reading_rows(self):
        with patch.object(generation, 'iter_file_rows', side_effect=AssertionError('read a row')), \
                patch.object(generation, '_validate_row_origins', side_effect=AssertionError('full check')):
            self.assertEqual(checked_manifest(self.capture, self.lane.objects),
                             read_manifest(self.capture, self.lane.objects))
            check_candidate_integrity(self.candidate, self.lane.objects)

    def test_refuses_a_changed_data_file_byte_with_the_full_check_class(self):
        data = next(ref for ref in self.candidate.manifest.files if ref.role == 'data')
        self.corrupt(data.path, lambda body: body[:-1] + bytes([body[-1] ^ 1]))
        for check in (checked_manifest, validated_manifest):
            with self.subTest(check=check.__name__), self.assertRaises(Conflict):
                check(self.capture, self.lane.objects)
        with self.assertRaises(Conflict):
            check_candidate_integrity(self.candidate, self.lane.objects)

    def test_refuses_a_missing_change_file_with_the_full_check_class(self):
        changes = next(ref for ref in self.candidate.manifest.files if ref.role == 'changes')
        path = self.lane.path(changes.path)
        original = path.read_bytes()
        path.unlink()
        self.addCleanup(path.write_bytes, original)
        for check in (checked_manifest, validated_manifest):
            with self.subTest(check=check.__name__), self.assertRaises(FileNotFoundError):
                check(self.capture, self.lane.objects)

    def test_refuses_a_changed_manifest(self):
        self.corrupt(self.capture.manifest_ref, lambda body: body + b' ')
        for check in (checked_manifest, validated_manifest):
            with self.subTest(check=check.__name__), self.assertRaises(Conflict):
                check(self.capture, self.lane.objects)


class GatedIntegrityTests(unittest.TestCase):
    """An awaiting-approval generation needs its exact approval and gate record, as today."""

    def setUp(self):
        self.lane = Lane()
        self.addCleanup(self.lane.close)
        old = self.lane.build([self.lane.observation(rows=row() + row(number=2))])
        revised = self.lane.observation(rows=row('Revised'), seconds=1)
        retained = self.lane.build([revised], old)
        self.lane.pin(date(2027, 1, 1))
        self.gated = self.lane.build([revised], retained)
        self.assertEqual(self.gated.manifest.gate, 'awaiting_approval')

    def approve(self, candidate):
        approval = approval_for(candidate, 'owner', datetime(2027, 1, 2, tzinfo=timezone.utc))
        self.lane.objects.put_once(approval_ref(candidate.manifest.quarter, candidate.manifest.generation_id),
                                   canonical_json(approval.to_mapping()))

    def test_refuses_an_awaiting_generation_without_its_approval(self):
        for check in (checked_manifest, validated_manifest):
            with self.subTest(check=check.__name__), \
                    self.assertRaisesRegex(ValueError, 'awaiting-approval generation cannot be current'):
                check(capture(self.gated), self.lane.objects)

    def test_accepts_an_approved_generation_without_reading_rows(self):
        self.approve(self.gated)
        with patch.object(generation, 'iter_file_rows', side_effect=AssertionError('read a row')):
            self.assertEqual(checked_manifest(capture(self.gated), self.lane.objects), self.gated.manifest)

    def test_refuses_a_changed_gate_record(self):
        path = self.lane.path(self.gated.candidate_ref)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b' ')
        with self.assertRaisesRegex(Conflict, 'candidate gate record differs'):
            check_candidate_integrity(self.gated, self.lane.objects)


class ObservationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.lane = Lane()
        self.addCleanup(self.lane.close)
        self.ref = self.lane.observation(rows=row() + row(number=2))

    def test_accepts_the_exact_observation_without_reading_rows(self):
        with patch.object(transform, '_verify_parquet', side_effect=AssertionError('read a row')):
            self.assertEqual(checked_observation(self.ref.manifest_ref, self.lane.objects), self.ref)

    def test_refuses_a_changed_rows_byte_with_the_readback_class(self):
        path = self.lane.path(self.ref.rows_ref)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        for check in (checked_observation, _read_manifest):
            with self.subTest(check=check.__name__), \
                    self.assertRaisesRegex(Conflict, 'observation bytes differ from manifest hash or length'):
                check(self.ref.manifest_ref, self.lane.objects)

    def test_refuses_a_changed_observation_manifest(self):
        path = self.lane.path(self.ref.manifest_ref)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b' ')
        for check in (checked_observation, _read_manifest):
            with self.subTest(check=check.__name__), self.assertRaises(ValueError):
                check(self.ref.manifest_ref, self.lane.objects)


if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 3: Run the tests to verify they fail.**

Run: the test command with target `test_etl_integrity`.
Expected: an `ImportError` for `check_candidate_integrity`.

- [x] **Step 4: Add C1 to `etl/manifest.py`.** After `validate_candidate` (end of file), add:

```python
def check_candidate_integrity(candidate: Candidate, objects: ObjectStore) -> None:
    """C1: the exact manifest and every listed file's hash and length; no data or change row is read."""
    capture = GenerationCapture(candidate.manifest.quarter, candidate.manifest.generation_id,
                                candidate.manifest_ref, candidate.manifest_sha256, candidate.manifest_bytes)
    manifest = read_manifest(capture, objects)
    if manifest != candidate.manifest or candidate.candidate_ref != gate_ref(manifest):
        raise ValueError('candidate differs from exact manifest/gate identity')
    for ref in manifest.files:
        objects.verify(ref.path, ref.sha256, ref.byte_count)
    if candidate.candidate_ref and objects.read(candidate.candidate_ref) != gate_payload(candidate):
        raise Conflict('candidate gate record differs from exact generation/base/hash')
```

- [x] **Step 5: Add C1 for captures to `etl/reader.py`.** Change the import line 13 to:

```python
from .manifest import (check_candidate_integrity, gate_ref, generation_base, iter_file_rows, read_approval,
                       read_manifest, validate_candidate)
```

Replace `validated_manifest` (lines 28–39) with:

```python
def _pinned_manifest(capture: GenerationCapture, objects: ObjectStore, check) -> GenerationManifest:
    manifest = read_manifest(capture, objects)
    candidate = Candidate(manifest, capture.manifest_ref, capture.manifest_sha256,
                          capture.manifest_bytes, gate_ref(manifest))
    if manifest.gate != 'clear':
        # Cheap binding check first; the check then proves the files and the gate record.
        try:
            read_approval(candidate, objects)
        except FileNotFoundError as error:
            raise ValueError('an awaiting-approval generation cannot be current without its exact approval') from error
    check(candidate, objects)
    return manifest


def validated_manifest(capture: GenerationCapture, objects: ObjectStore) -> GenerationManifest:
    """The full content check: public readers, approval and rollback keep it (C3)."""
    return _pinned_manifest(capture, objects, validate_candidate)


def checked_manifest(capture: GenerationCapture, objects: ObjectStore) -> GenerationManifest:
    """C1 for engine paths: exact manifest and file hashes, and the approval binding; no row is read."""
    return _pinned_manifest(capture, objects, check_candidate_integrity)
```

- [x] **Step 6: Add C11 to `etl/transform.py`.** Replace `_read_manifest` (lines 108–125) with:

```python
def _observation_manifest(path: str, objects: ObjectStore) -> tuple[ObservationRef, bytes]:
    """The exact canonical observation manifest at `path` and its producer; no row is read."""
    body = objects.read(path)
    value = parse_json(body)
    if not isinstance(value, dict) or set(value) != {'format_version', 'observation', 'runtime'}:
        raise ValueError('observation manifest requires exact local fields')
    if value['format_version'] != OBSERVATION_FORMAT:
        raise ValueError('unsupported observation manifest version')
    from ..runtime import validate_producer
    validate_producer(value['runtime'], objects)
    ref = ObservationRef.from_mapping(value['observation'])
    if canonical_json(value) != body:
        raise ValueError('observation manifest must be canonical')
    if ref.manifest_ref != path:
        raise ValueError('observation manifest address differs')
    return ref, body


def _read_manifest(path: str, objects: ObjectStore) -> tuple[ObservationRef, bytes]:
    ref, body = _observation_manifest(path, objects)
    with closing(read_observations(ref, objects)) as rows:
        for _ in rows:
            pass
    return ref, body


def checked_observation(path: str, objects: ObjectStore) -> ObservationRef:
    """C11 for engine paths: the exact observation manifest and its rows file hash and length; no row is read."""
    ref, _ = _observation_manifest(path, objects)
    try:
        objects.verify(ref.rows_ref, ref.rows_sha256, ref.rows_bytes)
    except Conflict as error:
        raise Conflict('observation bytes differ from manifest hash or length') from error
    return ref
```

- [x] **Step 7: Run the tests to verify they pass.**

Run: the test command with target `test_etl_integrity`, then with `test_etl_transform test_etl_catalog test_etl_publication test_etl_rollback test_etl_approval`.
Expected: all pass. Nothing else calls the new functions yet.

- [x] **Step 8: Commit.**

```bash
git add packages/sec-edgar-ingest/tests/support_catalog.py packages/sec-edgar-ingest/tests/test_etl_integrity.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/manifest.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/reader.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/transform.py
git commit -m "feat(etl): add integrity checks for generations and observations"
```

---

### Task 3: Engine paths use the integrity checks (C2, C11)

**Files:**
- Create: `packages/sec-edgar-ingest/tests/test_full_check_budget.py`
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/reader.py` (`capture_quarter`)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/commands.py:17, 205` (`_affected_quarters`)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/completion.py:16, 18, 420, 428, 688, 705, 770, 789, 815, 825`
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/checked.py:26–28, 241–245, 299, 313`
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py:12, 352`

**Interfaces:**
- Consumes: `checked_manifest`, `check_candidate_integrity` and `checked_observation` (Task 2).
- Produces: an engine that runs no full content check and no observation readback. `test_full_check_budget.py` holds the `EngineBudgetTests` class, and Task 4 adds `PublishBudgetTests` to the same module.

- [x] **Step 1: Write the failing test.** Create `packages/sec-edgar-ingest/tests/test_full_check_budget.py`:

```python
"""Stage 1b §5 item 2, split by process (plan 5, P2).

Workflow children are native processes, so a patch here sees the engine only. The engine test proves
that the engine runs no full check and no observation readback, and that `read_quarter` still runs the
full check. The publish tests call `publish_quarter` in this process.
"""
from network_guard import install
install()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_workflows import CommandHarness, simple_pack
from sec_edgar_ingest.etl import manifest as generation
from sec_edgar_ingest.etl import transform
from sec_edgar_ingest.etl.commands import _affected_quarters
from sec_edgar_ingest.etl.reader import capture_quarter, read_manifest
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.storage.contracts import Conflict


class EngineBudgetTests(unittest.TestCase):
    def harness(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        harness = CommandHarness(root, simple_pack(root / 'pack'))
        self.addCleanup(harness.close)  # Runs before the directory cleanup (LIFO).
        return harness

    def test_the_engine_runs_no_full_check_and_readers_still_do(self):
        h = self.harness()
        with patch.object(generation, '_validate_row_origins', wraps=generation._validate_row_origins) as full, \
                patch.object(transform, '_verify_parquet', wraps=transform._verify_parquet) as readback:
            code, message = h.invoke('backfill')
            self.assertEqual(code, 0, message)
            self.assertEqual((full.call_count, readback.call_count), (0, 0))
            h.capture('2026Q4')
            self.assertEqual(full.call_count, 1)

    def test_a_changed_generation_byte_is_a_conflict_on_engine_paths(self):
        h = self.harness()
        code, message = h.invoke('backfill')
        self.assertEqual(code, 0, message)
        state = EtlState(h.store)
        captured = capture_quarter('2026Q4', h.objects, state)
        data = next(ref for ref in read_manifest(captured, h.objects).files if ref.role == 'data')
        path = h.root / '.fixture-state/objects' / data.path
        path.write_bytes(path.read_bytes() + b'\0')
        with self.assertRaises(Conflict):
            capture_quarter('2026Q4', h.objects, state)
        sources = read_manifest(captured, h.objects).sources
        with self.assertRaises(Conflict):
            _affected_quarters(sources, h.objects, h.store)


if __name__ == '__main__':
    unittest.main()
```

The harness store keeps its objects under `<root>/.fixture-state/objects/`, as `test_workflow_checked.py` uses them.

- [x] **Step 2: Run the test to verify it fails.**

Run: the test command with target `test_full_check_budget`.
Expected: `test_the_engine_runs_no_full_check_and_readers_still_do` fails, because both counts are above 0. The second test may already pass.

- [x] **Step 3: `etl/reader.py`.** In `capture_quarter`, replace `manifest = validated_manifest(capture, objects)` with:

```python
    manifest = checked_manifest(capture, objects)
```

- [x] **Step 4: `etl/commands.py`.** Change line 17 to `from .reader import capture_from_pointer, checked_manifest`. In `_affected_quarters`, replace `manifest = validated_manifest(capture, objects)` with `manifest = checked_manifest(capture, objects)`.

- [x] **Step 5: `workflows/completion.py`.**
  - Change line 16 to `from ..etl.reader import capture_quarter, checked_manifest`.
  - Change line 18 to `from ..etl.transform import checked_observation`.
  - Replace each of the six `validated_manifest(` calls (lines 428, 688, 705, 770, 789, 825) with `checked_manifest(`.
  - At line 420 (`validate_capture`) and line 815 (`evaluate_member`), replace `durable, _ = _read_manifest(ref.manifest_ref, objects)` with:

```python
    durable = checked_observation(ref.manifest_ref, objects)
```

  Keep each line's indentation. Then confirm that no use is left:

```bash
grep -n "validated_manifest\|_read_manifest" packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/completion.py
```

  Expected: no output.

- [x] **Step 6: `workflows/checked.py`.** Change lines 26–28 to:

```python
from ..etl.manifest import check_candidate_integrity, read_manifest
from ..etl.reader import checked_manifest
from ..etl.transform import _pinned_members, checked_observation
```

In `_transformed_input`, replace:

```python
        retained, _ = _read_manifest(ref.manifest_ref, objects)
        if retained != ref:
            raise Conflict('transformed observation differs from retained manifest')
        for _ in read_observations(ref, objects):
            pass
```

with:

```python
        retained = checked_observation(ref.manifest_ref, objects)
        if retained != ref:
            raise Conflict('transformed observation differs from retained manifest')
```

In `_validate_input_output`, replace `manifest = validated_manifest(capture, objects)` with `manifest = checked_manifest(capture, objects)`, and `validate_candidate(candidate, objects)` with `check_candidate_integrity(candidate, objects)`. Then run:

```bash
grep -n "validated_manifest\|validate_candidate\b\|_read_manifest\|read_observations" packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/checked.py
```

Expected: no output. If `_pinned_members` is unused after the change, remove it from the import too.

- [x] **Step 7: `workflows/runner.py`.** Change line 12 to `from ..etl.reader import capture_from_pointer, capture_quarter, checked_manifest`. In `source_revert_gaps`, replace `validated_manifest(capture, objects)` with `checked_manifest(capture, objects)`.

- [x] **Step 8: Run the test to verify it passes, then the affected modules.**

Run: the test command with target `test_full_check_budget`. Expected: PASS.

Then run it with `test_workflow_completion test_workflow_checked test_workflow_runner test_workflow_processing test_workflow_results test_workflow_drain test_workflow_acceptance test_local_failures test_etl_cli test_etl_history test_reconcile_workflow`. Expected: all pass. A failure that expects an engine path to refuse a forged but hash-consistent generation follows P8. Move that assertion to `read_quarter` and record a `> Deviation:` line under this step. Any other failure is a bug: stop and use systematic-debugging.

- [x] **Step 9: Commit.**

```bash
git add packages/sec-edgar-ingest/tests/test_full_check_budget.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/reader.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/commands.py packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/completion.py packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/checked.py packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py
git commit -m "perf(workflows): check generations and observations by hash on engine paths"
```

---

### Task 4: The `publish` child checks the previous generation by hash and a full rebuild once (C2, C3, C11)

**Files:**
- Modify: `packages/sec-edgar-ingest/tests/test_full_check_budget.py` (add `PublishBudgetTests`)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/publication.py:11–14, 54–56, 75, 86, 102`
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py:18–19, 178–186, 207–210`

**Interfaces:**
- Consumes: Task 2's checks; `support_catalog.Lane(command='publish')`.
- Produces: `publish_quarter` with exactly one `_validate_row_origins` call for a full-rebuild candidate, and none for an unchanged quarter. Task 7 adds the incremental case to `PublishBudgetTests`.

- [x] **Step 1: Write the failing tests.** Add these imports to `test_full_check_budget.py`:

```python
from datetime import date

from support_catalog import Lane, row
from sec_edgar_ingest.etl.publication import publish_quarter
```

Add this class before the `if __name__` block:

```python
class PublishBudgetTests(unittest.TestCase):
    def setUp(self):
        self.lane = Lane(command='publish')
        self.addCleanup(self.lane.close)

    def publish(self, *refs):
        return publish_quarter('2026Q4', tuple(refs), self.lane.context, self.lane.settings,
                               self.lane.objects, self.lane.state)

    def counted(self, *refs):
        with patch.object(generation, '_validate_row_origins', wraps=generation._validate_row_origins) as full:
            result = self.publish(*refs)
        return result, full.call_count

    def test_a_first_publication_is_fully_checked_once(self):
        result, count = self.counted(self.lane.observation(rows=row() + row(number=2)))
        self.assertEqual((result.outcome, count), ('published', 1))

    def test_an_unchanged_quarter_is_not_fully_checked(self):
        ref = self.lane.observation()
        self.publish(ref)
        result, count = self.counted(ref)
        self.assertEqual((result.outcome, count), ('unchanged', 0))

    def test_a_replacement_rebuild_is_fully_checked_once(self):
        self.publish(self.lane.observation('2026-10-01', 'daily', row() + row(number=2)))
        replacement = self.lane.observation('2026-10-01', 'daily', row('Changed'), seconds=1)
        result, count = self.counted(replacement)
        self.assertEqual((result.outcome, count), ('published', 1))

    def test_a_gated_rebuild_is_fully_checked_once(self):
        self.publish(self.lane.observation(rows=row() + row(number=2)))
        revised = self.lane.observation(rows=row('Revised'), seconds=1)
        self.publish(revised)
        self.lane.pin(date(2027, 1, 1))
        result, count = self.counted(revised)
        self.assertEqual((result.outcome, count), ('awaiting_approval', 1))
```

- [x] **Step 2: Run the tests to verify they fail.**

Run: the test command with target `test_full_check_budget.PublishBudgetTests`.
Expected: the first, third and fourth tests fail with counts of 2 or 3. The unchanged test fails with a count of 1, from `validated_manifest(previous)`.

> Deviation: the RED counts were first publication 2, replacement 4, gated rebuild 5 and unchanged 1, not "2 or 3" (the plan's counts were wrong, found in the pre-flight scan). Each test still failed for the stated reason (task 4 report).

- [x] **Step 3: `etl/publication.py`.** Change lines 11–14 to:

```python
from .manifest import check_candidate_integrity
from .reader import capture_from_pointer, capture_quarter, checked_manifest
from .state import EtlState
from .transform import _validate_context, checked_observation
```

In `repair_publication`, replace `state.record_publication(validated_manifest(capture, objects))` with:

```python
        state.record_publication(checked_manifest(capture, objects))
```

In `publish_quarter`, make three replacements:

```python
    for ref in incoming:
        durable = checked_observation(ref.manifest_ref, objects)
        if durable != ref:
            raise Conflict('incoming reference differs from immutable observation manifest')
```

```python
        existing = checked_manifest(previous, objects) if previous else None
```

```python
        # build_candidate fully checked a full rebuild once (C3), or ran the C6 equivalence check.
        check_candidate_integrity(candidate, objects)
```

The last one replaces `validate_candidate(candidate, objects)`.

- [x] **Step 4: `etl/catalog.py`.** Change the `.manifest` import (lines 18–19) to:

```python
from .manifest import (check_candidate_integrity, gate_payload, gate_ref, generation_base, generation_identity,
                       iter_file_rows, read_manifest, source_fingerprint, validate_candidate_content, validate_files)
```

In `_stage_gate`, replace `validate_candidate(candidate, objects)` with `check_candidate_integrity(candidate, objects)`. In `build_candidate`, replace:

```python
    active = read_manifest(previous, objects) if previous else None
    if active:
        validate_candidate(Candidate(active, previous.manifest_ref, previous.manifest_sha256,
                                     previous.manifest_bytes, gate_ref(active)), objects)
```

with:

```python
    active = read_manifest(previous, objects) if previous else None
    if active:
        # The previous generation was fully checked when its pointer committed (S1, C2).
        check_candidate_integrity(Candidate(active, previous.manifest_ref, previous.manifest_sha256,
                                            previous.manifest_bytes, gate_ref(active)), objects)
```

The `_existing` and full-rebuild `validate_candidate_content` calls stay (C3).

- [x] **Step 5: Run the tests to verify they pass, then the affected modules.**

Run: the test command with target `test_full_check_budget`. Expected: PASS.

Then run it with `test_etl_publication test_etl_catalog test_etl_approval test_etl_rollback test_etl_history test_etl_processes test_etl_cli test_local_etl_contracts test_workflow_checked`. Expected: all pass. A failure follows the Task 3 Step 8 rule (P8).

- [x] **Step 6: Commit.**

```bash
git add packages/sec-edgar-ingest/tests/test_full_check_budget.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/publication.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py
git commit -m "perf(etl): fully check a full-rebuild candidate once in the publish child"
```

---

### Task 5: Hash-checked columnar readers and the `_load_observations` reader seam

**Files:**
- Create: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/columnar.py`
- Create: `packages/sec-edgar-ingest/tests/test_etl_columnar.py`
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py:75–79` (`_load_observations`)

**Interfaces:**
- Consumes: `transform._file_identity`, `contracts.canonical_schema`, `change_schema`, `observation_schema`, `Observation`, `IndexRow`.
- Produces (used by Tasks 6 and 7):
  - `columnar.Key = tuple[str, str]` (`cik`, `archive_path`).
  - `columnar.generation_table(ref: FileRef, objects: ObjectStore) -> pa.Table`: one generation file after its hash, length, schema and row count.
  - `columnar.quarter_observations(ref: ObservationRef, objects: ObjectStore, quarter: str, keys: Iterable[Key] | None = None) -> Iterator[Observation]`: one source's rows filed in `quarter`, optionally only `keys`, in file order, after the rows file hash. It does not re-parse rows (S1).
  - `columnar.key_mask(table: pa.Table, keys: Iterable[Key]) -> pa.ChunkedArray` and `columnar.table_keys(table: pa.Table) -> set[Key]`.
  - `catalog._load_observations(db, selected, quarter, membership, objects, context, read=read_observations)`. `read(ref, objects)` returns a closable iterator of `Observation`.

- [x] **Step 1: Write the failing tests.** Create `packages/sec-edgar-ingest/tests/test_etl_columnar.py`:

```python
"""Stage 1b readers: hash-checked columnar reads give the rows that the full readers give (S1)."""
from network_guard import install
install()

import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pyarrow as pa

from support_catalog import Lane, row
from sec_edgar_ingest.etl import transform
from sec_edgar_ingest.etl.catalog import _database, _load_observations
from sec_edgar_ingest.etl.columnar import generation_table, key_mask, quarter_observations, table_keys
from sec_edgar_ingest.etl.manifest import iter_file_rows
from sec_edgar_ingest.etl.transform import read_observations
from sec_edgar_ingest.models import quarter_for
from sec_edgar_ingest.storage.contracts import Conflict


class ColumnarReaderTests(unittest.TestCase):
    def setUp(self):
        self.lane = Lane()
        self.addCleanup(self.lane.close)
        self.ref = self.lane.observation('2026-10-02', 'daily',
                                         row() + row(number=2) + row(number=3, day='2026-09-30'))
        old = self.lane.build([self.lane.observation('2026-10-01', 'daily', row('Old') + row(number=4))])
        self.candidate = self.lane.build([self.ref], old)

    def changed(self, name):
        path = self.lane.path(name)
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b'\0')

    def test_generation_tables_equal_the_full_reader(self):
        for ref in self.candidate.manifest.files:
            with self.subTest(role=ref.role):
                self.assertEqual(generation_table(ref, self.lane.objects).to_pylist(),
                                 list(iter_file_rows(ref, self.lane.objects)))

    def test_generation_table_refuses_changed_counts_and_bytes(self):
        data = next(ref for ref in self.candidate.manifest.files if ref.role == 'data')
        with self.assertRaisesRegex(ValueError, 'generation file row count differs'):
            generation_table(replace(data, row_count=data.row_count + 1), self.lane.objects)
        self.changed(data.path)
        with self.assertRaisesRegex(Conflict, 'generation file hash or length differs'):
            generation_table(data, self.lane.objects)

    def test_quarter_observations_equal_the_full_reader_without_a_readback(self):
        with closing(read_observations(self.ref, self.lane.objects)) as rows:
            expected = [obs for obs in rows if quarter_for(obs.row.filing_date) == '2026Q4']
        self.assertEqual(len(expected), 2)
        keys = {(expected[1].row.cik, expected[1].row.archive_path)}
        with patch.object(transform, '_verify_parquet', side_effect=AssertionError('readback')):
            self.assertEqual(list(quarter_observations(self.ref, self.lane.objects, '2026Q4')), expected)
            self.assertEqual(list(quarter_observations(self.ref, self.lane.objects, '2026Q4', keys)), expected[1:])
            self.assertEqual(len(list(quarter_observations(self.ref, self.lane.objects, '2026Q3'))), 1)

    def test_quarter_observations_refuse_changed_bytes(self):
        self.changed(self.ref.rows_ref)
        with self.assertRaisesRegex(Conflict, 'observation bytes differ from manifest hash or length'):
            list(quarter_observations(self.ref, self.lane.objects, '2026Q4'))

    def test_key_masks_select_exact_pairs(self):
        table = pa.table({'cik': ['1', '1', '2'], 'archive_path': ['a', 'b', 'a']})
        self.assertEqual(key_mask(table, {('1', 'b'), ('2', 'a'), ('3', 'a')}).to_pylist(), [False, True, True])
        self.assertEqual(key_mask(table, set()).to_pylist(), [False, False, False])
        self.assertEqual(table_keys(table), {('1', 'a'), ('1', 'b'), ('2', 'a')})

    def test_the_reader_seam_resolves_the_same_proposed_rows(self):
        sources = self.candidate.manifest.sources

        def proposed(**kwargs):
            with TemporaryDirectory() as directory, closing(_database(Path(directory) / 'db.sqlite')) as db:
                _load_observations(db, sources, '2026Q4', None, self.lane.objects, self.lane.context, **kwargs)
                return db.execute('SELECT cik,path,payload FROM proposed ORDER BY cik,path').fetchall()

        everything = proposed()
        self.assertEqual(len(everything), 3)
        self.assertEqual(proposed(read=lambda ref, objects: quarter_observations(ref, objects, '2026Q4')), everything)
        first = {(everything[0][0], everything[0][1])}
        self.assertEqual(proposed(read=lambda ref, objects: quarter_observations(ref, objects, '2026Q4', first)),
                         everything[:1])


if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 2: Run the tests to verify they fail.**

Run: the test command with target `test_etl_columnar`.
Expected: `ModuleNotFoundError: No module named 'sec_edgar_ingest.etl.columnar'`.

- [x] **Step 3: Write `etl/columnar.py`.**

```python
"""Hash-checked columnar reads for the incremental build (C5) and its equivalence check (C6).

Under S1 a file is trusted by its exact SHA-256 and length once a full check accepted it, so these
readers never re-parse rows. They hold no merge logic, so C5 and C6 stay independent of each other.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..models import quarter_value
from ..storage.contracts import Conflict, ObjectStore
from .contracts import (FileRef, IndexRow, Observation, ObservationRef, canonical_schema, change_schema,
                        observation_schema)
from .transform import _file_identity

Key = tuple[str, str]
KEY_SEPARATOR = '\x1f'  # Never inside a CIK or an archive path.


def _read_table(path: str, sha256: str, byte_count: int, objects: ObjectStore, schema: pa.Schema,
                hash_message: str, schema_message: str) -> pa.Table:
    with TemporaryDirectory(prefix='sec-columnar-read-') as directory:
        target = Path(directory) / 'rows.parquet'
        objects.materialize(path, target)
        if _file_identity(target) != (sha256, byte_count):
            raise Conflict(hash_message)
        with pq.ParquetFile(target) as parquet:
            if not parquet.schema_arrow.equals(schema, check_metadata=True):
                raise ValueError(schema_message)
            return parquet.read()


def generation_table(ref: FileRef, objects: ObjectStore) -> pa.Table:
    """One generation file as an Arrow table, after its exact hash, length, schema and row count."""
    table = _read_table(ref.path, ref.sha256, ref.byte_count, objects,
                        canonical_schema() if ref.role == 'data' else change_schema(),
                        'generation file hash or length differs', 'generation Parquet schema differs')
    if table.num_rows != ref.row_count:
        raise ValueError('generation file row count differs')
    return table


def key_column(table: pa.Table) -> pa.ChunkedArray:
    return pc.binary_join_element_wise(table['cik'], table['archive_path'], KEY_SEPARATOR)


def key_mask(table: pa.Table, keys: Iterable[Key]) -> pa.ChunkedArray:
    """True for each row whose (cik, archive_path) is one of `keys`."""
    value_set = pa.array(sorted(cik + KEY_SEPARATOR + path for cik, path in keys), pa.string())
    return pc.is_in(key_column(table), value_set=value_set)


def table_keys(table: pa.Table) -> set[Key]:
    return set(zip(table['cik'].to_pylist(), table['archive_path'].to_pylist()))


def _quarter_bounds(quarter: str) -> tuple[date, date]:
    year, ordinal = quarter_value(quarter)
    start = date(year, 3 * ordinal - 2, 1)
    return start, date(year + 1, 1, 1) if ordinal == 4 else date(year, 3 * ordinal + 1, 1)


def quarter_observations(ref: ObservationRef, objects: ObjectStore, quarter: str,
                         keys: Iterable[Key] | None = None) -> Iterator[Observation]:
    """One source's rows filed in `quarter` (only `keys` when given), in file order, after the rows file hash."""
    table = _read_table(ref.rows_ref, ref.rows_sha256, ref.rows_bytes, objects, observation_schema(),
                        'observation bytes differ from manifest hash or length', 'observation Parquet schema differs')
    if table.num_rows != ref.source_row_count:
        raise ValueError('observation readback counts differ')
    start, end = _quarter_bounds(quarter)
    mask = pc.and_(pc.greater_equal(table['filing_date'], pa.scalar(start, pa.date32())),
                   pc.less(table['filing_date'], pa.scalar(end, pa.date32())))
    if keys is not None:
        mask = pc.and_(mask, key_mask(table, keys))
    for value in table.filter(mask).to_pylist():
        original = tuple(value.pop('original_fields'))
        line_number = value.pop('line_number')
        yield Observation(IndexRow(**value), original, line_number)
```

- [x] **Step 4: Add the reader seam to `etl/catalog.py`.** Replace the first lines of `_load_observations`:

```python
def _load_observations(db, selected, quarter, membership, objects, context):
    for ref in selected:
        if not ref.source_row_count:
            raise ValueError('invalid_source: empty source observations')
        with closing(read_observations(ref, objects)) as rows:
```

with:

```python
def _load_observations(db, selected, quarter, membership, objects, context, read=read_observations):
    for ref in selected:
        if not ref.source_row_count:
            raise ValueError('invalid_source: empty source observations')
        with closing(read(ref, objects)) as rows:
```

The rest of the function does not change.

- [x] **Step 5: Run the tests to verify they pass.**

Run: the test command with target `test_etl_columnar`, then with `test_etl_catalog test_etl_publication`.
Expected: all pass.

- [x] **Step 6: Commit.**

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/columnar.py packages/sec-edgar-ingest/tests/test_etl_columnar.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py
git commit -m "feat(etl): add hash-checked columnar readers and a source-reader seam"
```

---

### Task 6: The C6 equivalence check

C6 is written and tested before C5, against full-rebuild candidates. Under C5 an eligible input gives the same bytes as the full rebuild, so C6 must accept every full rebuild of an eligible input. Task 7 then wires C6 after C5.

**Files:**
- Create: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/equivalence.py`
- Create: `packages/sec-edgar-ingest/tests/test_etl_equivalence.py`
- Create: `specs/evidence/stage1b/locality.md`

**Interfaces:**
- Consumes: `columnar.generation_table`, `key_mask`, `quarter_observations`, `table_keys` (Task 5); `catalog._database`, `_load_observations`, `_resolve`; `manifest._row`, `check_candidate_integrity`; `reader.checked_manifest`; `transform.checked_observation`.
- Produces: `equivalence.validate_incremental_candidate(candidate: Candidate, previous: GenerationCapture, context: RunContext, objects: ObjectStore) -> None`. It raises `ValueError` (or `Conflict` from the integrity checks) when the candidate is not the full rebuild of its eligible base.

- [x] **Step 1: Record the locality proof.** Create `specs/evidence/stage1b/locality.md` with a title line `# Locality of an eligible addition (Stage 1b, plan 5)`, a line `Source: plan 5, section "Locality proof"; spec §4.3 item 4 as amended (A1).`, and the plan's "Locality proof" section copied without change. Add the F3 probe result as a last section, `## Probe`. This is the record that spec §4.3 item 4 asks for before C5.

- [x] **Step 2: Write the failing tests.** Create `packages/sec-edgar-ingest/tests/test_etl_equivalence.py`:

```python
"""Stage 1b C6: an incremental candidate must equal the full rebuild on every key it can change."""
from network_guard import install
install()

import hashlib
import unittest
from dataclasses import replace
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq

from support_catalog import Lane, capture, row
from sec_edgar_ingest.etl.contracts import canonical_schema, change_schema
from sec_edgar_ingest.etl.equivalence import validate_incremental_candidate
from sec_edgar_ingest.models import canonical_json

CLOSED = date(2027, 1, 7)


def forge(lane, candidate, *, data=None, changes=None, **fields):
    """Rewrite a candidate's files and manifest in place, keeping every hash consistent."""
    files = []
    for ref in candidate.manifest.files:
        rows = data if ref.role == 'data' else changes
        if rows is None:
            files.append(ref)
            continue
        path = lane.path(ref.path)
        pq.write_table(pa.Table.from_pylist(rows, schema=canonical_schema() if ref.role == 'data' else change_schema()), path)
        body = path.read_bytes()
        files.append(replace(ref, sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body), row_count=len(rows)))
    manifest = replace(candidate.manifest, files=tuple(files), **fields)
    body = canonical_json(manifest.to_mapping())
    lane.path(candidate.manifest_ref).write_bytes(body)
    return replace(candidate, manifest=manifest, manifest_sha256=hashlib.sha256(body).hexdigest(),
                   manifest_bytes=len(body))


class EquivalenceTests(unittest.TestCase):
    def lane(self, day=date(2026, 10, 7)):
        lane = Lane(day)
        self.addCleanup(lane.close)
        return lane

    def check(self, lane, candidate, base):
        validate_incremental_candidate(candidate, capture(base), lane.context, lane.objects)

    def open_addition(self):
        lane = self.lane()
        base = lane.build([lane.observation('2026-10-01', 'daily', row() + row(number=2))])
        candidate = lane.build([lane.observation('2026-10-02', 'daily', row('Changed') + row(number=3))], base)
        return lane, base, candidate

    def test_accepts_the_full_rebuild_of_an_open_daily_addition(self):
        lane, base, candidate = self.open_addition()
        self.check(lane, candidate, base)

    def test_accepts_the_open_authority_flip(self):
        lane = self.lane()
        g0 = lane.build([lane.observation(rows=row())])
        g1 = lane.build([lane.observation('2026-10-02', 'daily', row(number=2))], g0)
        g2 = lane.build([lane.observation('2026-10-03', 'daily', row(number=3))], g1)
        self.assertEqual(g2.manifest.unresolved_absence, 1)
        self.check(lane, g1, g0)
        self.check(lane, g2, g1)

    def test_accepts_a_closed_back_dated_addition(self):
        lane = self.lane(CLOSED)
        base = lane.build([lane.observation(rows=row() + row(number=2))])
        daily = lane.observation('2027-01-02', 'daily', row('Daily', day='2026-10-03') + row(number=9, day='2026-11-01'))
        self.check(lane, lane.build([daily], base), base)

    def test_accepts_a_touched_key_that_the_base_retained(self):
        lane = self.lane()
        g1 = lane.build([lane.observation('2026-10-01', 'daily', row() + row(number=2))])
        g2 = lane.build([lane.observation('2026-10-01', 'daily', row(), seconds=1)], g1)
        g3 = lane.build([lane.observation('2026-10-02', 'daily', row('Back', number=2))], g2)
        self.check(lane, g3, g2)

    def test_refuses_a_changed_untouched_row(self):
        lane, base, candidate = self.open_addition()
        rows = lane.rows(candidate)
        rows[1] = {**rows[1], 'company_name': 'Forged'}
        with self.assertRaisesRegex(ValueError, 'outside its recomputed keys'):
            self.check(lane, forge(lane, candidate, data=rows), base)

    def test_refuses_a_changed_touched_row(self):
        lane, base, candidate = self.open_addition()
        rows = lane.rows(candidate)
        rows[2] = {**rows[2], 'company_name': 'Forged'}
        with self.assertRaisesRegex(ValueError, 'rows differ from the full resolution'):
            self.check(lane, forge(lane, candidate, data=rows), base)

    def test_refuses_a_dropped_re_emitted_absence(self):
        lane = self.lane()
        g1 = lane.build([lane.observation('2026-10-01', 'daily', row() + row(number=2))])
        g2 = lane.build([lane.observation('2026-10-01', 'daily', row(), seconds=1)], g1)
        g3 = lane.build([lane.observation('2026-10-02', 'daily', row(number=3))], g2)
        kept = [value for value in lane.rows(g3, 'changes') if value['change_type'] != 'unresolved_absence']
        with self.assertRaisesRegex(ValueError, 'outside its recomputed keys'):
            self.check(lane, forge(lane, g3, changes=kept), g2)

    def test_refuses_a_forged_count(self):
        lane, base, candidate = self.open_addition()
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            self.check(lane, forge(lane, candidate, updated=candidate.manifest.updated + 1), base)

    def test_refuses_a_candidate_checked_against_another_base(self):
        lane, base, candidate = self.open_addition()
        other = lane.build([lane.observation('2026-10-05', 'daily', row(number=7))])
        with self.assertRaisesRegex(ValueError, 'eligible base'):
            self.check(lane, candidate, other)


if __name__ == '__main__':
    unittest.main()
```

In `open_addition`, the candidate's data rows sort as keys 1, 2, 3 (F9). Row index 1 is key 2 (untouched), and row index 2 is key 3 (touched).

> Deviation: review fix round 1 (0a261ae, tests only) added five tests beyond the plan's set: a duplicated touched row, touched-key change rows, a forged delta observation reference, a forged retained basis, and an accepted untouched re-emitted absence. `test_etl_equivalence` then had 14 tests, not 9.

- [x] **Step 3: Run the tests to verify they fail.**

Run: the test command with target `test_etl_equivalence`.
Expected: `ModuleNotFoundError: No module named 'sec_edgar_ingest.etl.equivalence'`.

- [x] **Step 4: Write `etl/equivalence.py`.**

```python
"""C6: an incremental candidate equals the full rebuild on every key that the delta can change.

The recomputed keys are resolved by the full path's own code (`catalog._load_observations` and
`catalog._resolve`) over every selected source, limited to those keys. Every other row must equal its
base row, column by column. Nothing here reuses the incremental build (C5); both share only the
hash-checked readers in `columnar`.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow.compute as pc

from ..models import RunContext, canonical_json
from ..storage.contracts import ObjectStore
from .columnar import generation_table, key_mask, quarter_observations, table_keys
from .contracts import Candidate, GenerationCapture, IndexRow
from .manifest import _row, check_candidate_integrity
from .reader import checked_manifest
from .transform import checked_observation

CHANGE_FIELDS = ('change_type', 'cik', 'archive_path', 'before', 'after', 'reason')


def _change_payload(value, quarter) -> bytes:
    for field in ('before', 'after'):
        if value[field] is not None:
            value[field] = _row(value[field], quarter).to_mapping()
    return canonical_json({name: value[name] for name in CHANGE_FIELDS})


def _strictly_sorted(table) -> None:
    keys = list(zip(table['cik'].to_pylist(), table['archive_path'].to_pylist()))
    if any(left >= right for left, right in zip(keys, keys[1:])):
        raise ValueError('generation keys are duplicate or unsorted')


def _recomputed_keys(manifest, delta, base_data, objects) -> set:
    keys = {(obs.row.cik, obs.row.archive_path) for ref in delta
            for obs in quarter_observations(ref, objects, manifest.quarter)}
    if manifest.quarter_mode == 'open' and manifest.membership_source is not None:
        # Locality exception (A1): any base key the authority does not list may become absent.
        members = {(obs.row.cik, obs.row.archive_path)
                   for obs in quarter_observations(manifest.membership_source, objects, manifest.quarter)}
        keys |= table_keys(base_data) - members
    return keys


def _expected(manifest, base_data, keys, context, objects):
    from .catalog import _database, _load_observations, _resolve
    quarter = manifest.quarter
    with TemporaryDirectory(prefix='sec-equivalence-') as directory, \
            closing(_database(Path(directory) / 'expected.sqlite')) as db:
        _load_observations(db, manifest.sources, quarter, manifest.membership_source, objects, context,
                           read=lambda ref, objects: quarter_observations(ref, objects, quarter, keys))
        for value in base_data.filter(key_mask(base_data, keys)).to_pylist():
            row = IndexRow(**value)
            db.execute('INSERT INTO active VALUES(?,?,?)', (row.cik, row.archive_path, canonical_json(row.to_mapping())))
        counts = _resolve(db, manifest.quarter_mode, manifest.membership_source)
        rows = {(cik, path): payload for cik, path, payload in db.execute('SELECT cik,path,payload FROM proposed')}
        changes = {(cik, path): payload for cik, path, payload in db.execute('SELECT cik,path,payload FROM changes')}
    return rows, changes, counts


def validate_incremental_candidate(candidate: Candidate, previous: GenerationCapture, context: RunContext,
                                   objects: ObjectStore) -> None:
    manifest, quarter = candidate.manifest, candidate.manifest.quarter
    check_candidate_integrity(candidate, objects)
    base = checked_manifest(previous, objects)
    if (manifest.base_generation_id != previous.generation_id or base.quarter != quarter or base.gate != 'clear'
            or (base.quarter_mode, base.membership_source, base.parser_version, base.schema_version)
            != (manifest.quarter_mode, manifest.membership_source, manifest.parser_version, manifest.schema_version)
            or not all(ref in manifest.sources for ref in base.sources)):
        raise ValueError('incremental candidate differs from its eligible base')
    base_ids = {ref.source.source_id for ref in base.sources}
    delta = [ref for ref in manifest.sources if ref.source.source_id not in base_ids]
    for ref in delta:
        if checked_observation(ref.manifest_ref, objects) != ref:
            raise ValueError('incremental source differs from its immutable observation manifest')
    files, base_files = ({ref.role: ref for ref in value.files} for value in (manifest, base))
    data, changes = generation_table(files['data'], objects), generation_table(files['changes'], objects)
    base_data, base_changes = generation_table(base_files['data'], objects), generation_table(base_files['changes'], objects)
    _strictly_sorted(data)
    _strictly_sorted(changes)
    keys = _recomputed_keys(manifest, delta, base_data, objects)
    expected_rows, expected_changes, counts = _expected(manifest, base_data, keys, context, objects)
    actual_rows = {}
    for value in data.filter(key_mask(data, keys)).to_pylist():
        row = _row(value, quarter)
        actual_rows[row.cik, row.archive_path] = canonical_json(row.to_mapping())
    if actual_rows != expected_rows:
        raise ValueError('incremental rows differ from the full resolution of their keys')
    actual_changes = {(value['cik'], value['archive_path']): _change_payload(value, quarter)
                      for value in changes.filter(key_mask(changes, keys)).to_pylist()}
    if actual_changes != expected_changes:
        raise ValueError('incremental change rows differ from the full resolution of their keys')
    outside = lambda table: table.filter(pc.invert(key_mask(table, keys)))
    if not outside(data).equals(outside(base_data)):
        raise ValueError('incremental candidate changes a data row outside its recomputed keys')
    re_emitted = outside(base_changes.filter(pc.equal(base_changes['change_type'], 'unresolved_absence')))
    if not outside(changes).equals(re_emitted):
        raise ValueError('incremental change rows outside its recomputed keys differ from re-emitted absences')
    expected = {'row_count': data.num_rows, 'added': counts['added'], 'updated': counts['updated'],
                'withdrawn': counts['withdrawn'], 'provenance_refreshed': counts['provenance_refreshed'],
                'unresolved_absence': counts['unresolved_absence'] + re_emitted.num_rows}
    if any(getattr(manifest, name) != value for name, value in expected.items()):
        raise ValueError('incremental counts differ from the full resolution')
    retained = previous.generation_id if manifest.unresolved_absence else None
    gate = 'awaiting_approval' if manifest.quarter_mode == 'closed' and manifest.withdrawn else 'clear'
    if (manifest.retained_from_generation, manifest.gate) != (retained, gate):
        raise ValueError('incremental retained basis or gate differs')
```

`catalog` is imported inside `_expected` because `catalog` will import this module (P1).

> Deviation: the plan's `equivalence.py` code was changed after the whole-branch review (D7). fe6bca0 finds the non-member base keys with an Arrow filter on the authority's key column (`columnar.quarter_key_column`), not one `IndexRow` per authority row. 9fef691 and dc0418b take the expected row count from the full resolution and require it to equal both `data.num_rows` and `manifest.row_count`.

- [x] **Step 5: Run the tests to verify they pass.**

Run: the test command with target `test_etl_equivalence`.
Expected: all 9 pass. If an accept test fails, the full rebuild and C6 disagree on an eligible input. That is a C6 bug or a locality case the proof missed. Stop and use systematic-debugging. Do not loosen a comparison to make it pass.

- [x] **Step 6: Commit.**

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/equivalence.py packages/sec-edgar-ingest/tests/test_etl_equivalence.py specs/evidence/stage1b/locality.md
git commit -m "feat(etl): add the C6 equivalence check for incremental candidates"
```

---

### Task 7: Eligibility and the incremental build (C4, C5), wired with C6

**Files:**
- Create: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/incremental.py`
- Create: `packages/sec-edgar-ingest/tests/support_incremental.py`
- Create: `packages/sec-edgar-ingest/tests/test_etl_incremental.py`
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/contracts.py` (end of file: `BUSINESS_FIELDS`, `ABSENCE_REASON`, `WITHDRAWAL_REASON`, `arrow_row`)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py` (imports; `BUSINESS_FIELDS`, `_resolve`, `_arrow_row`, `_write_parquet`, `build_candidate`; new `FILE_NAMES`, `_stage_file`, `_generation`, `_store_manifest`, `_incremental_candidate`)
- Modify: `packages/sec-edgar-ingest/tests/test_full_check_budget.py` (one test)

**Interfaces:**
- Consumes: Task 5's readers; Task 6's `validate_incremental_candidate`.
- Produces:
  - `incremental.eligible(active: GenerationManifest | None, incoming: tuple[ObservationRef, ...], selected: tuple[ObservationRef, ...], membership: ObservationRef | None, mode: str, context: RunContext) -> bool` (C4).
  - `incremental.build_incremental(quarter: str, active: GenerationManifest, selected: tuple[ObservationRef, ...], membership: ObservationRef | None, mode: str, context: RunContext, objects: ObjectStore) -> Delta`. `Delta` has `data: pa.Table`, `changes: pa.Table` and `counts: Counter` with the keys `_resolve` uses (`data`, `added`, `updated`, `withdrawn`, `unresolved_absence`, `provenance_refreshed`, `retained`).
  - `incremental.write_table(table: pa.Table, path: Path, schema: pa.Schema, context: RunContext) -> None` (P5).
  - `incremental._resolve_touched(...)`, one touched key's resolution. Task 7's C6-refusal test patches it.
  - `contracts.BUSINESS_FIELDS`, `contracts.ABSENCE_REASON`, `contracts.WITHDRAWAL_REASON`, `contracts.arrow_row(value) -> dict`.
  - `support_incremental.Twin(day)`: `fast` and `full` lanes; `observation(...) -> (fast_ref, full_ref)`; `build(pairs, previous=None, quarter='2026Q4') -> ((fast, full), incremental_build_count)`; `pin(day)`; `close()`.

- [x] **Step 1: Write the oracle harness.** Create `packages/sec-edgar-ingest/tests/support_incremental.py`:

```python
"""Twin lanes for the Stage 1b oracle (§5 item 3): the same inputs in two fresh stores.

`fast` builds as the release does, so an eligible quarter takes the incremental path (C5).
`full` forces today's full rebuild by making C4 refuse every input. Two stores give the same
generation bytes for the same inputs (plan 5, F6).
"""
from datetime import date
from unittest.mock import patch

from support_catalog import Lane
from sec_edgar_ingest.etl import incremental


class Twin:
    def __init__(self, day=date(2026, 10, 7)):
        self.fast, self.full = Lane(day), Lane(day)

    def close(self):
        self.fast.close()
        self.full.close()

    def pin(self, day):
        self.fast.pin(day)
        self.full.pin(day)

    def observation(self, *args, **kwargs):
        return self.fast.observation(*args, **kwargs), self.full.observation(*args, **kwargs)

    def build(self, pairs, previous=None, quarter='2026Q4'):
        """Both lanes' candidates, and the number of incremental builds the fast lane ran."""
        with patch.object(incremental, 'build_incremental', wraps=incremental.build_incremental) as built:
            fast = self.fast.build([pair[0] for pair in pairs], previous[0] if previous else None, quarter)
        with patch.object(incremental, 'eligible', return_value=False):
            full = self.full.build([pair[1] for pair in pairs], previous[1] if previous else None, quarter)
        return (fast, full), built.call_count
```

- [x] **Step 2: Write the failing tests.** Create `packages/sec-edgar-ingest/tests/test_etl_incremental.py`:

```python
"""Stage 1b §5 items 3–5: incremental generations are byte-identical to full rebuilds (C4–C6)."""
from network_guard import install
install()

import unittest
from datetime import date
from unittest.mock import patch

from support_catalog import Lane, row
from support_incremental import Twin
from sec_edgar_ingest.etl import incremental
from sec_edgar_ingest.etl.publication import publish_quarter
from sec_edgar_ingest.models import canonical_json, parse_json

OPEN = date(2026, 10, 7)
CLOSED = date(2027, 1, 7)


class TwinCase(unittest.TestCase):
    def twin(self, day=OPEN):
        twin = Twin(day)
        self.addCleanup(twin.close)
        return twin

    def step(self, twin, pairs, previous=None, *, incremental_expected=True, quarter='2026Q4'):
        pair, built = twin.build(pairs, previous, quarter)
        self.assertEqual(pair[0], pair[1])  # Same manifest, so the same file hashes and counts.
        self.assertEqual(built, int(incremental_expected))
        return pair

    @staticmethod
    def names(twin, pair):
        return {value['archive_path'][-10:]: value['company_name'] for value in twin.fast.rows(pair[0])}


class OracleTests(TwinCase):
    def test_open_daily_addition_updates_and_adds(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row() + row(number=2))], incremental_expected=False)
        g2 = self.step(t, [t.observation('2026-10-02', 'daily', row('Changed') + row(number=3))], g1)
        self.assertEqual((g2[0].manifest.updated, g2[0].manifest.added), (1, 1))

    def test_a_new_row_beats_the_winner_and_one_loses(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-02', 'daily', row('Mid') + row('Mid', number=2))],
                       incremental_expected=False)
        newer = t.observation('2026-10-03', 'daily', row('New'))
        older = t.observation('2026-10-01', 'daily', row('Old', number=2))
        g2 = self.step(t, [newer, older], g1)
        self.assertEqual(self.names(t, g2), {'000001.txt': 'New', '000002.txt': 'Mid'})

    def test_two_delta_rows_with_one_key(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row())], incremental_expected=False)
        first = t.observation('2026-10-03', 'daily', row('A', number=5))
        second = t.observation('2026-10-04', 'daily', row('B', number=5))
        g2 = self.step(t, [first, second], g1)
        self.assertEqual((g2[0].manifest.added, self.names(t, g2)['000005.txt']), (1, 'B'))

    def test_closed_quarter_with_authority_takes_back_dated_rows(self):
        t = self.twin(CLOSED)
        g1 = self.step(t, [t.observation(rows=row() + row(number=2))], incremental_expected=False)
        daily = t.observation('2027-01-02', 'daily', row('Daily', day='2026-10-03') + row(number=9, day='2026-11-01'))
        g2 = self.step(t, [daily], g1)
        manifest = g2[0].manifest
        self.assertEqual((manifest.row_count, manifest.added, manifest.updated, manifest.gate), (2, 0, 0, 'clear'))

    def test_touched_key_retained_without_membership(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row() + row(number=2))], incremental_expected=False)
        replacement = t.observation('2026-10-01', 'daily', row(), seconds=1)
        g2 = self.step(t, [replacement], g1, incremental_expected=False)  # §5 item 4: a replacement snapshot
        self.assertEqual(g2[0].manifest.unresolved_absence, 1)
        g3 = self.step(t, [t.observation('2026-10-02', 'daily', row('Back', number=2))], g2)
        self.assertEqual((g3[0].manifest.updated, g3[0].manifest.unresolved_absence), (1, 0))
        self.assertIsNone(g3[0].manifest.retained_from_generation)

    def test_open_quarter_authority_and_keys_it_does_not_list(self):
        t = self.twin()
        g0 = self.step(t, [t.observation(rows=row())], incremental_expected=False)
        g1 = self.step(t, [t.observation('2026-10-02', 'daily', row(number=2))], g0)
        self.assertEqual((g1[0].manifest.added, g1[0].manifest.unresolved_absence), (1, 0))
        # A1: key 2 is untouched here, but the base added it and the authority does not list it.
        g2 = self.step(t, [t.observation('2026-10-03', 'daily', row(number=3))], g1)
        self.assertEqual((g2[0].manifest.added, g2[0].manifest.unresolved_absence), (1, 1))
        self.assertEqual(g2[0].manifest.retained_from_generation, g1[0].manifest.generation_id)
        # Key 2 is touched and retained; key 3 is the next untouched flip.
        g3 = self.step(t, [t.observation('2026-10-04', 'daily', row('Again', number=2))], g2)
        self.assertEqual(g3[0].manifest.unresolved_absence, 2)

    def test_closed_daily_only_quarter(self):
        t = self.twin(CLOSED)
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row() + row(number=2))], incremental_expected=False)
        g2 = self.step(t, [t.observation('2026-10-02', 'daily', row('Changed'))], g1)
        self.assertEqual((g2[0].manifest.updated, g2[0].manifest.gate), (1, 'clear'))

    def test_more_than_one_batch_with_a_boundary_shift(self):
        t = self.twin(CLOSED)
        big = b''.join(row(number=number) for number in range(100, 9100))
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', big)], incremental_expected=False)
        self.assertEqual(g1[0].manifest.row_count, 9000)
        shift = b''.join(row(number=number) for number in range(1, 6)) + row('Changed', number=8290)
        g2 = self.step(t, [t.observation('2026-10-02', 'daily', shift)], g1)
        self.assertEqual((g2[0].manifest.row_count, g2[0].manifest.added, g2[0].manifest.updated), (9005, 5, 1))

    def test_rows_filed_in_another_quarter_are_ignored(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row())], incremental_expected=False)
        g2 = self.step(t, [t.observation('2026-10-02', 'daily', row(number=2) + row(number=3, day='2026-09-30'))], g1)
        self.assertEqual((g2[0].manifest.added, g2[0].manifest.row_count), (1, 2))


class FallbackTests(TwinCase):
    """§5 item 4: each ineligible input takes today's full path, with today's output."""

    def test_a_revert_to_an_earlier_snapshot(self):
        t = self.twin()
        first = t.observation('2026-10-01', 'daily', row('A'))
        g1 = self.step(t, [first], incremental_expected=False)
        g2 = self.step(t, [t.observation('2026-10-01', 'daily', row('B'), seconds=1)], g1, incremental_expected=False)
        self.step(t, [first], g2, incremental_expected=False)

    def test_an_incoming_quarterly_authority(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row())], incremental_expected=False)
        self.step(t, [t.observation(rows=row() + row(number=2))], g1, incremental_expected=False)

    def test_a_mode_change(self):
        t = self.twin()
        g1 = self.step(t, [t.observation('2026-10-01', 'daily', row())], incremental_expected=False)
        t.pin(CLOSED)
        self.step(t, [t.observation('2026-10-02', 'daily', row(number=2))], g1, incremental_expected=False)

    def test_a_gate_other_than_clear(self):
        t = self.twin()
        g1 = self.step(t, [t.observation(rows=row() + row(number=2))], incremental_expected=False)
        revised = t.observation(rows=row('Revised'), seconds=1)
        g2 = self.step(t, [revised], g1, incremental_expected=False)
        t.pin(CLOSED)
        g3 = self.step(t, [revised], g2, incremental_expected=False)
        self.assertEqual(g3[0].manifest.gate, 'awaiting_approval')
        daily = t.observation('2027-01-02', 'daily', row('Daily', day='2026-10-03'))
        self.step(t, [daily], g3, incremental_expected=False)


class PrePointerRefusalTests(unittest.TestCase):
    """§5 item 5: C6 refuses a wrong incremental row before the pointer commits."""

    def test_a_wrong_incremental_row_is_refused_before_the_pointer(self):
        lane = Lane(command='publish')
        self.addCleanup(lane.close)
        publish = lambda ref: publish_quarter('2026Q4', (ref,), lane.context, lane.settings, lane.objects, lane.state)
        publish(lane.observation('2026-10-01', 'daily', row()))
        pointer = lane.state.pointer('2026Q4')
        original = incremental._resolve_touched

        def wrong(*args, **kwargs):
            output, change = original(*args, **kwargs)
            if output is not None:
                output = canonical_json({**parse_json(output), 'company_name': 'Wrong'})
            return output, change

        with patch.object(incremental, '_resolve_touched', side_effect=wrong), \
                self.assertRaisesRegex(ValueError, 'incremental rows differ'):
            publish(lane.observation('2026-10-02', 'daily', row(number=2)))
        self.assertEqual(lane.state.pointer('2026Q4'), pointer)


if __name__ == '__main__':
    unittest.main()
```

In `test_a_revert_to_an_earlier_snapshot`, the last build returns the active generation (the fingerprint no-op), because `select_sources` keeps the newer snapshot. That is today's output, and C4 is never asked.

Add this test to `PublishBudgetTests` in `test_full_check_budget.py`:

```python
    def test_an_incremental_rebuild_is_not_fully_checked(self):
        self.publish(self.lane.observation('2026-10-01', 'daily', row()))
        result, count = self.counted(self.lane.observation('2026-10-02', 'daily', row(number=2)))
        self.assertEqual((result.outcome, count), ('published', 0))
```

- [x] **Step 3: Run the tests to verify they fail.**

Run: the test command with target `test_etl_incremental`.
Expected: `ImportError` for `sec_edgar_ingest.etl.incremental`.

- [x] **Step 4: Move the shared names to `etl/contracts.py`.** At the end of `contracts.py`, add:

```python
BUSINESS_FIELDS = ('cik', 'company_name', 'form_type', 'archive_path', 'filing_date', 'accession_number')
ABSENCE_REASON = 'absence is not authoritative withdrawal evidence'
WITHDRAWAL_REASON = 'absent from closed quarterly membership'


def arrow_row(value: Mapping[str, object]) -> dict[str, object]:
    """A canonical row mapping with its filing date as a `date`, as the Arrow schemas need."""
    return {**value, 'filing_date': IndexRow.from_mapping(value).filing_date}
```

In `catalog.py`:
- Delete the `BUSINESS_FIELDS = …` line and the `_arrow_row` function.
- Change the `.contracts` import to `from .contracts import (ABSENCE_REASON, BUSINESS_FIELDS, WITHDRAWAL_REASON, Candidate, FileRef, GenerationCapture, GenerationManifest, IndexRow, ObservationRef, arrow_row, canonical_schema, change_schema)`.
- In `_resolve`, replace the two reason strings with `WITHDRAWAL_REASON` and `ABSENCE_REASON`.
- In `_write_parquet`, replace both `_arrow_row(` calls with `arrow_row(`.
- Run `grep -rn "_arrow_row\|catalog.BUSINESS_FIELDS" packages/sec-edgar-ingest`. Expected: no output.

- [x] **Step 5: Write `etl/incremental.py`.**

```python
"""Stage 1b C4 and C5: rebuild an eligible quarter from its base tables and its delta rows.

Plan 5's locality proof names the keys that an eligible addition can change: the touched keys and,
in an open quarter with a membership authority, base `added` keys that the authority does not list.
Every other data row and re-emitted absence is copied from the base generation's columns.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..models import RunContext, canonical_json, parse_json
from ..storage.contracts import ObjectStore
from .columnar import Key, generation_table, key_mask, quarter_observations, table_keys
from .contracts import (ABSENCE_REASON, BUSINESS_FIELDS, WITHDRAWAL_REASON, GenerationManifest, IndexRow,
                        ObservationRef, arrow_row, canonical_schema, change_schema)
from .transform import BATCH_ROWS, PARQUET_VERSION, _check_deadline

Rank = tuple[int, str, str]


@dataclass(frozen=True)
class Delta:
    """The sorted candidate tables and `catalog._resolve`-shaped counts."""
    data: pa.Table
    changes: pa.Table
    counts: Counter


def eligible(active: GenerationManifest | None, incoming: tuple[ObservationRef, ...],
             selected: tuple[ObservationRef, ...], membership: ObservationRef | None, mode: str,
             context: RunContext) -> bool:
    """C4: new sources added to a clear generation of the same mode, versions and membership authority."""
    if active is None or active.gate != 'clear' or active.quarter_mode != mode:
        return False
    if (active.parser_version, active.schema_version) != (context.parser_version, context.schema_version):
        return False
    base_ids = {ref.source.source_id for ref in active.sources}
    if any(ref.source.source_id in base_ids for ref in incoming) or not all(ref in selected for ref in active.sources):
        return False
    return membership == active.membership_source


def _rank(ref: ObservationRef) -> Rank:
    return int(ref.source.kind == 'quarterly'), ref.source.period, ref.snapshot.received_at.isoformat()


def _best(candidates: list[tuple[Rank, str, bytes]]) -> bytes:
    """`_load_observations`' winner: preference, period and receipt descending, then source_id ascending."""
    by_source = sorted(candidates, key=lambda item: item[1])
    return sorted(by_source, key=lambda item: item[0], reverse=True)[0][2]


def _change(key: Key, kind: str, before, after, reason=None) -> dict:
    return {'change_type': kind, 'cik': key[0], 'archive_path': key[1],
            'before': None if before is None else arrow_row(before),
            'after': None if after is None else arrow_row(after), 'reason': reason}


def _resolve_touched(key: Key, base: bytes | None, unresolved: set[Key], delta: list[tuple[Rank, str, bytes]],
                     rank_of: dict[str, Rank], member: bool, mode: str, has_membership: bool,
                     counts: Counter) -> tuple[bytes | None, dict | None]:
    """`catalog._resolve`'s rules for one touched key: (output row or None, change row or None)."""
    candidates = list(delta)
    if base is not None and key not in unresolved:
        source_id = parse_json(base)['source_id']
        candidates.append((rank_of[source_id], source_id, base))
    proposed = _best(candidates) if candidates else None
    if mode == 'closed' and has_membership and not member:
        proposed = None
    if base is None:
        if proposed is None:
            return None, None
        counts['added'] += 1
        return proposed, _change(key, 'added', None, parse_json(proposed))
    before = parse_json(base)
    if proposed is None or (mode == 'open' and has_membership and not member):
        if mode == 'closed' and has_membership:
            counts['withdrawn'] += 1
            return None, _change(key, 'withdrawn', before, None, WITHDRAWAL_REASON)
        counts['unresolved_absence'] += 1
        counts['retained'] += 1
        return base, _change(key, 'unresolved_absence', before, before, ABSENCE_REASON)
    after = parse_json(proposed)
    if any(before[name] != after[name] for name in BUSINESS_FIELDS):
        counts['updated'] += 1
        return proposed, _change(key, 'updated', before, after)
    if before != after:
        counts['provenance_refreshed'] += 1
    return proposed, None


def _change_keys(table: pa.Table, kind: str) -> tuple[pa.Table, set[Key]]:
    rows = table.filter(pc.equal(table['change_type'], kind))
    return rows, table_keys(rows)


def build_incremental(quarter: str, active: GenerationManifest, selected: tuple[ObservationRef, ...],
                      membership: ObservationRef | None, mode: str, context: RunContext,
                      objects: ObjectStore) -> Delta:
    """C5: the full rebuild's tables, computed from the base tables and the delta rows only."""
    files = {ref.role: ref for ref in active.files}
    base_data, base_changes = generation_table(files['data'], objects), generation_table(files['changes'], objects)
    rank_of = {ref.source.source_id: _rank(ref) for ref in selected}
    base_ids = {ref.source.source_id for ref in active.sources}
    delta: dict[Key, list[tuple[Rank, str, bytes]]] = {}
    for ref in selected:
        if ref.source.source_id in base_ids:
            continue
        for obs in quarter_observations(ref, objects, quarter):
            delta.setdefault((obs.row.cik, obs.row.archive_path), []).append(
                (rank_of[ref.source.source_id], ref.source.source_id, canonical_json(obs.row.to_mapping())))
        _check_deadline(context)
    touched = set(delta)
    unresolved_rows, unresolved = _change_keys(base_changes, 'unresolved_absence')
    added = (_change_keys(base_changes, 'added')[1] - touched) if mode == 'open' and membership else set()
    members = set()
    if membership is not None:
        members = {(obs.row.cik, obs.row.archive_path)
                   for obs in quarter_observations(membership, objects, quarter, touched | added)}
    flips = added - members  # Locality exception (A1).
    base_rows = {}
    for value in base_data.filter(key_mask(base_data, touched | flips)).to_pylist():
        row = IndexRow(**value)
        base_rows[row.cik, row.archive_path] = canonical_json(row.to_mapping())
    counts, outputs, changes = Counter(), [], []
    for key in sorted(touched):
        output, change = _resolve_touched(key, base_rows.get(key), unresolved, delta[key], rank_of,
                                          key in members, mode, membership is not None, counts)
        if output is not None:
            outputs.append(arrow_row(parse_json(output)))
        if change is not None:
            changes.append(change)
    for key in sorted(flips):
        before = parse_json(base_rows[key])
        changes.append(_change(key, 'unresolved_absence', before, before, ABSENCE_REASON))
        counts['unresolved_absence'] += 1
        counts['retained'] += 1
    re_emitted = unresolved_rows.filter(pc.invert(key_mask(unresolved_rows, touched)))
    counts['unresolved_absence'] += re_emitted.num_rows
    counts['retained'] += re_emitted.num_rows
    kept = base_data.filter(pc.invert(key_mask(base_data, touched))).cast(canonical_schema())
    data = pa.concat_tables([kept, pa.Table.from_pylist(outputs, schema=canonical_schema())]).sort_by(
        [('cik', 'ascending'), ('archive_path', 'ascending')])
    change_table = pa.concat_tables([re_emitted.cast(change_schema()),
                                     pa.Table.from_pylist(changes, schema=change_schema())]).sort_by(
        [('cik', 'ascending'), ('archive_path', 'ascending'), ('change_type', 'ascending')])
    counts['data'] = data.num_rows
    return Delta(data, change_table, counts)


def write_table(table: pa.Table, path: Path, schema: pa.Schema, context: RunContext) -> None:
    """`catalog._write_parquet`'s layout: the same writer settings and 8,192-row single-chunk slices (P5)."""
    with pq.ParquetWriter(path, schema, version=PARQUET_VERSION, compression='snappy',
                          use_dictionary=False, use_compliant_nested_type=False) as writer:
        for start in range(0, table.num_rows, BATCH_ROWS):
            writer.write_table(table.slice(start, BATCH_ROWS).combine_chunks())
            _check_deadline(context)
```

The delta rows come from `quarter_observations`, the hash-checked reader, not from `read_observations` (S1, A2). The `publish` child checked each incoming reference with C11, and the `transform` child read every row back when it wrote them.

> Deviation: the plan's C5 code was changed after the whole-branch review (D7, finding I2). fe6bca0 reads the membership authority only as an Arrow key column (`columnar.quarter_key_column`), with no full authority row read as Python.

- [x] **Step 6: Wire C4, C5 and C6 into `etl/catalog.py`.**

Add `from . import incremental` to the imports, and `from .transform import _file_identity` if it is not already imported (it is, in the `.transform` import line). Add, after `_candidate`:

```python
FILE_NAMES = {'data': 'part-00000.parquet', 'changes': 'changes.parquet'}


def _stage_file(path, ref, objects, observer):
    objects.stage(ref.path, path)
    objects.verify(ref.path, ref.sha256, ref.byte_count)
    observe(observer, 'candidate.after_' + ref.role)


def _generation(quarter, generation_id, previous, fingerprint, context, selected, files, counts, mode,
                membership, retained):
    return GenerationManifest(quarter=quarter,
        generation_id=generation_id,
        base_generation_id=previous.generation_id if previous else None,
        source_fingerprint=fingerprint,
        parser_version=context.parser_version,
        schema_version=context.schema_version,
        runtime=context.runtime,
        sources=selected,
        files=tuple(files),
        row_count=counts['data'],
        added=counts['added'],
        updated=counts['updated'],
        withdrawn=counts['withdrawn'],
        unresolved_absence=counts['unresolved_absence'],
        provenance_refreshed=counts['provenance_refreshed'],
        quarter_mode=mode,
        membership_source=membership,
        retained_from_generation=retained,
        gate='awaiting_approval' if mode == 'closed' and counts['withdrawn'] else 'clear')


def _store_manifest(manifest, previous, objects, observer):
    base = generation_base(manifest.quarter, manifest.generation_id)
    if previous:
        objects.put_once(base + '/retained-base.json', canonical_json(previous.to_mapping()))
    body = canonical_json(manifest.to_mapping())
    candidate = _candidate(manifest, body)
    try:
        objects.put_once(candidate.manifest_ref, body)
    except Conflict:
        candidate = _existing(manifest.quarter, manifest.generation_id, objects)
        if candidate is None:
            raise Conflict('concurrent candidate vanished')
    observe(observer, 'candidate.after_manifest')
    return candidate
```

In `_write_parquet`, replace `name = 'part-00000.parquet' if role == 'data' else 'changes.parquet'` with `name = FILE_NAMES[role]`.

Add, before `build_candidate`:

```python
def _incremental_candidate(quarter, previous, active, selected, membership, mode, context, objects, state, observer):
    """C5, then C6 before the gate and pointer steps."""
    from .equivalence import validate_incremental_candidate
    delta = incremental.build_incremental(quarter, active, selected, membership, mode, context, objects)
    retained = previous.generation_id if delta.counts['retained'] else None
    fingerprint = source_fingerprint(quarter, selected, mode=mode, membership_source=membership,
                                     retained_from_generation=retained)
    generation_id = generation_identity(quarter, previous.generation_id, fingerprint)
    existing = _existing(quarter, generation_id, objects)
    if existing:
        observe(observer, 'candidate.after_validation')
        _stage_gate(existing, objects, state)
        return existing
    base, files = generation_base(quarter, generation_id), []
    with TemporaryDirectory(prefix='sec-catalog-delta-') as directory:
        for role, table, schema in (('data', delta.data, canonical_schema()), ('changes', delta.changes, change_schema())):
            path = Path(directory) / FILE_NAMES[role]
            incremental.write_table(table, path, schema, context)
            digest, byte_count = _file_identity(path)
            ref = FileRef(base + '/' + FILE_NAMES[role], digest, byte_count, table.num_rows, role)
            _stage_file(path, ref, objects, observer)
            files.append(ref)
    manifest = _generation(quarter, generation_id, previous, fingerprint, context, selected, files,
                           delta.counts, mode, membership, retained)
    candidate = _store_manifest(manifest, previous, objects, observer)
    validate_incremental_candidate(candidate, previous, context, objects)
    observe(observer, 'candidate.after_validation')
    _stage_gate(candidate, objects, state)
    return candidate
```

In `build_candidate`, after the fingerprint no-op block (`return candidate` at the end of `if active and source_fingerprint(...) == active.source_fingerprint:`), add:

```python
    if incremental.eligible(active, incoming, selected, membership, mode, context):
        return _incremental_candidate(quarter, previous, active, selected, membership, mode,
                                      context, objects, state, observer)
```

Then replace everything from `base = generation_base(quarter, generation_id)` to the end of `build_candidate` with:

```python
            base = generation_base(quarter, generation_id)
            files = []
            for role in ('data', 'changes'):
                path, ref = _write_parquet(db, root, base, role, context)
                _stage_file(path, ref, objects, observer)
                files.append(ref)
        manifest = _generation(quarter, generation_id, previous, fingerprint, context, selected, files,
                               counts, mode, membership, retained)
        validate_files(manifest, objects)
        candidate = _store_manifest(manifest, previous, objects, observer)
        validate_candidate_content(candidate, objects)
        observe(observer, 'candidate.after_validation')
        _stage_gate(candidate, objects, state)
        return candidate
```

The full path keeps its order: files, `validate_files`, `retained-base.json`, manifest, the one full check (C3), then the gate.

> Deviation: D2. The identity-and-replay block that `build_candidate` and `_incremental_candidate` share is one helper, `catalog._identify_candidate`, not two copies (task 7 report, 80bd84d).
> Deviation: after the whole-branch review, c8949bc runs `_validate_identity` before the incremental `_store_manifest` (finding M1), and 4c73269 refuses an empty source before the incremental build stages files, through the shared `catalog._require_rows` (finding N3).

- [x] **Step 7: Run the tests to verify they pass.**

Run: the test command with target `test_etl_incremental`, then `test_full_check_budget test_etl_equivalence test_etl_columnar`.
Expected: all pass. A byte-identity failure in `OracleTests` is a C5 bug (or a P5 writer difference). Stop and use systematic-debugging. Compare `pq.ParquetFile(...).metadata` of the two lanes' files row group by row group. Never relax `assertEqual(pair[0], pair[1])`.

- [x] **Step 8: Run the existing ETL and workflow modules.** Many existing tests now take the incremental path, so they are a second oracle.

Run: the test command with `test_etl_catalog test_etl_publication test_etl_approval test_etl_rollback test_etl_history test_etl_processes test_etl_cli test_local_etl_contracts test_workflow_acceptance test_workflow_drain test_workflow_checked test_workflow_completion test_reconcile_workflow test_reconcile_acceptance`.
Expected: all pass. The rule for failures is the same as Step 7, and P8 applies to forged-generation tests.

- [x] **Step 9: Commit.**

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/incremental.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/contracts.py packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py packages/sec-edgar-ingest/tests/support_incremental.py packages/sec-edgar-ingest/tests/test_etl_incremental.py packages/sec-edgar-ingest/tests/test_full_check_budget.py
git commit -m "feat(etl): rebuild an eligible quarter incrementally behind the C6 check"
```

---

### Task 8: Two-release tests (spec §5 item 6, §4.3 item 8)

**Files:**
- Modify: `packages/sec-edgar-ingest/tests/support_release.py:95–133` (`origin_release`)
- Create: `packages/sec-edgar-ingest/tests/test_release_1b.py`
- Create: `specs/evidence/stage1b/two-release.md`

**Interfaces:**
- Consumes: plan 4's `test_release_origin.OriginReleaseTests` helpers (`configured`, `origin_run`, `current_run`, `continued`, `scratch`).
- Produces: `support_release.D5_REVISION`; `origin_release(project, cache, revision=ORIGIN_REVISION)`; the two-release record that Task 14 cites in §4.9.

- [x] **Step 1: Parameterize the origin release.** In `support_release.py`, after `ORIGIN_REVISION`, add:

```python
D5_REVISION = 'd68787fe8602e9d81a26d2012feec9bfad5c52df'  # source revision of the D5 release aa8de1ac…
```

Change `origin_release` in four places:
- The signature becomes `def origin_release(project: Path, cache: Path, revision: str = ORIGIN_REVISION) -> VerifiedRelease:`.
- The first docstring line becomes `"""Build one source revision (default: that of fc68adef…) into its own committed repository and install it.`
- The cache key becomes `key = str(project), str(cache), revision`.
- `ORIGIN_REVISION` becomes `revision` in the `git archive` call and in the commit message (`'Origin source revision ' + revision`).

> Deviation: the `_ORIGINS` key annotation changed to a three-part tuple, to match the new cache key. The plan does not name this change (task 8 report).

- [x] **Step 2: Write the tests.** Create `packages/sec-edgar-ingest/tests/test_release_1b.py`:

```python
"""Stage 1b §5 item 6: the 1b code continues D5-origin pending work, and D5 runs again on a store that 1b wrote.

The module imports `test_release_origin` as a module, so discovery does not collect plan 4's class a second time.
"""
from network_guard import install
install()

import unittest
from pathlib import Path

import test_release_origin as origin_tests


class D5OriginTests(origin_tests.OriginReleaseTests):
    """Plan 4's two-release proofs with the D5 release as origin. They stay order-aware (plan 4 R2)."""

    @classmethod
    def setUpClass(cls):
        from support_release import D5_REVISION, origin_release, proof_releases
        project = Path(__file__).resolve().parents[3]
        cls.origin = origin_release(project, project / 'releases/artifact-cache', revision=D5_REVISION)
        _, cls.current = proof_releases(project, project / 'releases/artifact-cache')

    # fc68adef…-only behaviours: D5 reads a sibling-completion receipt and accepts the reserve key.
    test_origin_release_reports_a_b4_receipt_as_unresolved = None
    test_origin_settings_refuse_the_reserve_key = None

    def test_d5_runs_again_on_a_store_that_1b_wrote(self):
        """§4.3 item 8: C7 changes no format, so D5 should read and continue a 1b-written store.

        An incremental generation is byte-identical to the full rebuild (§5 item 3), so D5's full checks
        see the same bytes either way.
        """
        h, origin, _, report, _ = self.continued(self.scratch())
        self.assertIn(report.outcome, ('success', 'unchanged'))
        code, message = self.origin_run(h, origin, 'd5-again')
        self.assertEqual(code, 0, message)
        self.assertIn(message['outcome'], ('success', 'unchanged'), message)


if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 3: Run the module three times.** Member order is not pinned (plan 4 R2), so one run proves little.

Run: the test command with target `test_release_1b` three times. Record each result.
Expected: all pass in each run. The first run builds both releases (several minutes).

If an inherited test fails because it encodes `fc68adef…` behavior, override it in `D5OriginTests` with the D5 expectation and record a `> Deviation:` line. If `test_d5_runs_again_on_a_store_that_1b_wrote` fails, use systematic-debugging to find the cause:
- A format or receipt difference contradicts C7. That is a bug: fix it with a test.
- A limit that C7 does not cover (for example a D5 refusal of a 1b child result) is a finding. Stop and ask the owner. On approval, change the test to assert the observed limit, and record it for §4.9.

> Deviation: the release IDs were not printed from the test code. A watcher script outside the repository (`$TMPDIR/s1b-t8/run.sh`) captured them while each of the three runs went (task 8 report; two-release.md).

- [x] **Step 4: Record and commit.** Create `specs/evidence/stage1b/two-release.md` with these sections:
  1. `## Inputs`: the D5 revision, the origin and current release IDs that the test built (print `cls.origin.release_id` and `cls.current.release_id` in one run).
  2. `## Results`: the three runs. For each, list pass or fail per test and the origin-first count (as plan 4's record did).
  3. `## Consequence for §4.9`: "The 1b release continues D5-origin pending work. Selecting the D5 release again for a store that the 1b release wrote is supported (tested)." Write the observed limit instead, if Step 3 found one.
  4. `## Limits of the proof`: the order-aware limit from plan 4 R2. Also state that no test runs D5 after a live 1b run, because no live run is allowed in this stage.

```bash
git add packages/sec-edgar-ingest/tests/support_release.py packages/sec-edgar-ingest/tests/test_release_1b.py specs/evidence/stage1b/two-release.md
git commit -m "test(release): prove D5-origin continuation and D5 on a 1b-written store"
```

> Deviation: D3. dfb5385 narrowed the §4.9 consequence in `two-release.md` to what was tested: only first-generation full-rebuild 1b generations, and no D5 publish on top of a 1b generation. No new scenario was added. The fix round also corrected the evidence labels and the `support_release.py` docstring.

---

### Task 9: Measurement script for §6

**Files:**
- Modify: `scripts/measure-d5-drain.py`
- Create: `packages/sec-edgar-ingest/tests/test_measure_cost.py`

**Interfaces:**
- Consumes: the installed release's `runner.sibling_completion` and `members.WorkflowMembers.record(self, result, context, evidence)`. Both exist in D5 and in the 1b code.
- Produces:
  - `measure-d5-drain.py scenario --name {open,closed,authority,finish} --release-manifest M --work W --counts C --scale {smoke,full}`. It writes `W/<name>-report.json`, in a `finally` block.
  - `measure-d5-drain.py summarize --work W`. It writes `W/measurement.json` and prints the measures and the proposal.
  - `cost_proposal(finish_seconds, slowest_seconds) -> dict` with `p4_floor_seconds`, `floor_seconds`, `floor_changes`, `reserve_seconds`, `slowest_member_wall_seconds`, `fit_gate_passes`.
  - The D5 `run`, `count` and `rebuild` subcommands keep their behavior.

- [x] **Step 1: Write the failing tests.** Create `packages/sec-edgar-ingest/tests/test_measure_cost.py`:

```python
"""Stage 1b §6 rules in scripts/measure-d5-drain.py: the C8 floor, the reserve and the fit gate."""
from network_guard import install
install()

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / 'scripts' / 'measure-d5-drain.py'


def load():
    spec = importlib.util.spec_from_file_location('measure_cost_script', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CostProposalTests(unittest.TestCase):
    def setUp(self):
        self.measure = load()

    def test_the_floor_stays_480_for_the_d5_finish_cost(self):
        value = self.measure.cost_proposal(152.15, 1000.0)
        self.assertEqual((value['p4_floor_seconds'], value['floor_seconds'], value['floor_changes']), (480, 480, False))
        self.assertEqual(value['reserve_seconds'], 1740)
        self.assertTrue(value['fit_gate_passes'])

    def test_a_larger_finish_cost_raises_the_floor(self):
        value = self.measure.cost_proposal(200.0, 600.0)
        self.assertEqual((value['p4_floor_seconds'], value['floor_seconds'], value['floor_changes']), (600, 600, True))

    def test_the_fit_gate_boundary_near_1250_seconds(self):
        self.assertTrue(self.measure.cost_proposal(150.0, 1240.0)['fit_gate_passes'])
        failing = self.measure.cost_proposal(150.0, 1250.0)
        self.assertEqual(failing['reserve_seconds'], 2100)
        self.assertFalse(failing['fit_gate_passes'])

    def test_summarize_names_incomplete_scenarios_and_proposes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'open-report.json').write_text(json.dumps({
                'status': 'failed', 'release_id': 'r', 'scenarios': {}, 'partial_walls': []}))
            summary = self.measure.summarize(work)
        self.assertEqual(summary['measures']['incomplete_scenarios'], ['open', 'closed', 'authority', 'finish'])
        self.assertIsNone(summary['proposal'])


if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 2: Run the tests to verify they fail.**

Run: the test command with target `test_measure_cost`.
Expected: `AttributeError: module 'measure_cost_script' has no attribute 'cost_proposal'`.

- [x] **Step 3: Extend the script.** Make these changes to `scripts/measure-d5-drain.py`:

1. Change the module docstring's first line to `"""Offline drain and per-member cost measurement (Stage 1a bounded-drain spec §6; Stage 1b spec §6).`, and add a paragraph to the docstring: `` `scenario` runs one Stage 1b scenario in this process and always writes its report. `summarize` combines the reports and applies the C8 floor and reserve rules. ``
2. Add `import os` to the imports.
3. After `MEMBERS: list[dict] = []`, add:

```python
COST_FORMAT = 'sec-1b-cost-measurement-v1'
COST_SCENARIOS = ('open', 'closed', 'authority', 'finish')
COST_MAX_RUN_SECONDS = 43200  # The closed baseline's 14 first publications can exceed 6 hours under load (plan 5, P7).
LAUNCHER_DEFAULT_SECONDS = 3300
FLOOR_MINIMUM_SECONDS = 480
RESERVE_FACTOR = 1.25
HISTORY_MARKS = (400, 1200)
WALLS: list[dict] = []
OPEN_MEMBER: dict = {}
```

4. In `SCALES`, add `'authority_days': 2` to `smoke` and `'authority_days': 10` to `full`.
5. Give `write_config` a keyword `max_run_seconds: int = MAX_RUN_SECONDS`, and write `'execution': {'max_run_seconds': max_run_seconds}`. Give `invoke` a parameter `max_run_seconds: int = MAX_RUN_SECONDS`, and set `deadline = datetime.now(timezone.utc) + timedelta(seconds=max_run_seconds - 600)`.
6. Replace `scenario` with:

```python
def scenario(name: str, work: Path, manifest: Path, leaves, steps: list,
             max_run_seconds: int = MAX_RUN_SECONDS) -> dict:
    """`leaves` is one pack for every step, or a list with one pack for each step."""
    root = work / name
    root.mkdir(parents=True)
    packs = ([build_pack(root / 'pack', leaves)] * len(steps) if isinstance(leaves, dict)
             else [build_pack(root / f'pack-{index}', value) for index, value in enumerate(leaves)])
    invocations = []
    for index, (command, ranges) in enumerate(steps):
        config = write_config(root / f'config-{index}.json', root, manifest, max_run_seconds=max_run_seconds, **ranges)
        first_timing, first_member, first_wall = len(TIMINGS), len(MEMBERS), len(WALLS)
        call = invoke(config, command, f'measure-{name}-{index}', packs[index], max_run_seconds)
        timings = TIMINGS[first_timing:]
        members = MEMBERS[first_member:]
        walls = WALLS[first_wall:]
        for member in (*members, *walls):
            member['children'] = {t['command']: t['seconds'] for t in timings
                                  if t['label'] == 'child' and t['step_id'].endswith('-' + member['member_id'])}
        call.update(timings=timings, members=members, walls=walls)
        invocations.append(call)
    return {'invocations': invocations}
```

7. Move the three leaf builders out of `run` and `run_finish` into functions, with no change to the rows they make:

```python
def open_leaves(sizes: dict, daily_rows: int) -> dict:
    days = [date(2026, 10, 1) + timedelta(days=index) for index in range(sizes['open_days'])]
    return {('full-index', 2026, 4): [], ('daily-index', 2026, 3): [], ('daily-index', 2026, 4): [
        (f'master.{day:%Y%m%d}.idx', body('daily', [row('daily', 300000 + index, serial, day)
                                                     for serial in range(daily_rows)]))
        for index, day in enumerate(days)]}


def closed_leaves(sizes: dict, quarterly_rows: int, daily_rows: int) -> dict:
    """A quarterly baseline from closed_start to 2026Q3, the back-dated quarters full size, then two daily files:
    one back-dates one row into one closed quarter (measure 1), the other one row into each (findings §4.7)."""
    heavy = sizes['closed_quarters']
    leaves = {('full-index', 2026, 4): [], ('daily-index', 2026, 4): []}
    for index, (year, quarter) in enumerate(quarters(sizes['closed_start'], '2026Q3')):
        size = quarterly_rows if f'{year}Q{quarter}' in heavy else sizes['finish_rows']
        first = date(year, (quarter - 1) * 3 + 1, 2)
        leaves['full-index', year, quarter] = [('master.zip', body('quarterly', [
            row('quarterly', 100000 + index * 50000 + serial % 40000, serial, first) for serial in range(size)]))]
        leaves['daily-index', year, quarter] = []

    def back_date(label: str) -> date:
        return date(int(label[:4]), (int(label[-1]) - 1) * 3 + 1, 12)

    single = [row('daily', 310000, serial, date(2026, 12, 1)) for serial in range(daily_rows)]
    single.append(row('daily', 900001, 1, back_date(heavy[0])))
    fanout = [row('daily', 320000, serial, date(2026, 12, 2)) for serial in range(daily_rows)]
    fanout.extend(row('daily', 900100 + index, 1, back_date(label)) for index, label in enumerate(heavy))
    leaves['daily-index', 2026, 4] = [('master.20261201.idx', body('daily', single)),
                                      ('master.20261202.idx', body('daily', fanout))]
    return leaves


def finish_leaves(sizes: dict) -> dict:
    leaves = {}
    for index, (year, quarter) in enumerate(quarters(sizes['finish_start'], '2026Q4')):
        first = date(year, (quarter - 1) * 3 + 1, 1)
        leaves['full-index', year, quarter] = [('master.zip', body('quarterly', [
            row('quarterly', 400000 + serial, index * 1000 + serial, first) for serial in range(sizes['finish_rows'])]))]
        leaves['daily-index', year, quarter] = []
    return leaves
```

   In `run`, delete the inline `days`, `open_leaves`, `heavy`, `closed_leaves`, `back_date`, `single` and `fanout` code. Pass the function calls straight into the two `scenario` calls: `scenario('open', work, manifest, open_leaves(sizes, daily_rows), …)` and `scenario('closed', work, manifest, closed_leaves(sizes, quarterly_rows, daily_rows), …)`. In `run_finish`, pass `finish_leaves(sizes)` the same way. Do not assign a local variable named `open_leaves`, `closed_leaves` or `finish_leaves`. A local of the same name shadows the function and raises `UnboundLocalError`. The scenario calls and their steps stay as they are.

8. Add after `run_finish_only`:

```python
def authority_leaves(sizes: dict, quarterly_rows: int, daily_rows: int) -> list[dict]:
    """Findings §2: a closed quarter (2026Q3) with a daily-only generation gains its quarterly authority.

    Step 1 publishes `authority_days` full-size daily files. Step 2's quarterly file lists 90% of their keys
    and its own rows up to the full quarterly size, so the full rebuild loads the active rows, withdraws the
    rest and stops at the gate.
    """
    days = [date(2026, 7, 1) + timedelta(days=index) for index in range(sizes['authority_days'])]
    keys = [(500000 + index, serial, day) for index, day in enumerate(days) for serial in range(daily_rows)]
    daily = [(f'master.{day:%Y%m%d}.idx', body('daily', [row('daily', cik, serial, filed)
                                                          for cik, serial, filed in keys if filed == day]))
             for day in days]
    listed = [key for position, key in enumerate(keys) if position % 10]
    rows = [row('quarterly', cik, serial, filed) for cik, serial, filed in listed]
    rows.extend(row('quarterly', 600000 + serial % 40000, serial, date(2026, 7, 2))
                for serial in range(quarterly_rows - len(listed)))
    first = {('full-index', 2026, 3): [], ('full-index', 2026, 4): [],
             ('daily-index', 2026, 3): daily, ('daily-index', 2026, 4): []}
    return [first, {**first, ('full-index', 2026, 3): [('master.zip', body('quarterly', rows))]}]


def history_counts(state: Path) -> dict:
    """Rows of the history tables that `_obligations` and `reuse_exact_binding` scan (S4)."""
    import sqlite3
    if not state.exists():
        return {'WorkflowChildCall': 0, 'Attempts': 0}
    connection = sqlite3.connect('file:' + str(state) + '?mode=ro', uri=True)
    try:
        return {name: connection.execute('select count(*) from records where table_name = ?', (name,)).fetchone()[0]
                for name in ('WorkflowChildCall', 'Attempts')}
    finally:
        connection.close()


def instrument_members(state: Path) -> None:
    """Member wall (§6): from the member's `sibling_completion` call to the return of its durable receipt.

    Machine load and the history row counts are sampled at each member boundary.
    """
    from sec_edgar_ingest.workflows import members, runner
    sibling, record = runner.sibling_completion, members.WorkflowMembers.record

    def entered(value, *args, **kwargs):
        OPEN_MEMBER.clear()
        OPEN_MEMBER.update(member_id=value['member_id'], kind=value['source']['kind'],
                           period=value['source']['period'], started=time.monotonic(),
                           load_at_start=list(os.getloadavg()), history=history_counts(state))
        return sibling(value, *args, **kwargs)

    def recorded(self, result, context, evidence):
        descriptor = record(self, result, context, evidence)
        if OPEN_MEMBER.get('member_id') == result.member_id:
            WALLS.append({**OPEN_MEMBER, 'wall_seconds': time.monotonic() - OPEN_MEMBER['started'],
                          'load_at_end': list(os.getloadavg()), 'outcome': result.outcome})
            OPEN_MEMBER.clear()
        return descriptor

    runner.sibling_completion = entered
    members.WorkflowMembers.record = recorded


def run_scenario(name: str, manifest: Path, work: Path, counts: dict, scale: str) -> dict:
    """One Stage 1b scenario in this process. Its report is written even when the run fails."""
    sizes, sources = SCALES[scale], counts['sources']
    quarterly_rows = sources['2024Q1']['rows'] if scale == 'full' else 1000
    daily_rows = max(v['rows'] for v in sources.values() if v['kind'] == 'daily') if scale == 'full' else 20
    report = {'format_version': COST_FORMAT, 'kind': 'scenario', 'scenario': name, 'scale': scale,
              'python': sys.executable,
              'flags': {'isolated': sys.flags.isolated, 'dont_write_bytecode': sys.dont_write_bytecode,
                        'pycache_prefix': sys.pycache_prefix},
              'release_id': json.loads(manifest.read_text())['release_id'],
              'inputs': {'quarterly_rows': quarterly_rows, 'daily_rows': daily_rows, **sizes},
              'max_run_seconds': COST_MAX_RUN_SECONDS, 'started_at': datetime.now(timezone.utc).isoformat(),
              'status': 'running', 'scenarios': {}}
    instrument()
    instrument_members(work / name / 'store' / 'state.sqlite3')
    plans = {
        'open': (open_leaves(sizes, daily_rows),
                 [('daily', {'start': '2026Q4', 'end': 'open', 'daily_start': '2026-10-01'})]),
        'closed': (closed_leaves(sizes, quarterly_rows, daily_rows),
                   [('backfill', {'start': sizes['closed_start'], 'end': '2026Q3', 'daily_start': '2026-12-01'}),
                    ('daily', {'start': sizes['closed_start'], 'end': 'open', 'daily_start': '2026-12-01'})]),
        'authority': (authority_leaves(sizes, quarterly_rows, daily_rows),
                      [('daily', {'start': '2026Q3', 'end': 'open', 'daily_start': '2026-07-01'}),
                       ('backfill', {'start': '2026Q3', 'end': '2026Q3', 'daily_start': '2026-07-01'})]),
        'finish': (finish_leaves(sizes),
                   [('backfill', {'start': sizes['finish_start'], 'end': 'open', 'daily_start': '2026-12-31'})]),
    }
    leaves, steps = plans[name]
    try:
        report['scenarios'][name] = scenario(name, work, manifest, leaves, steps, COST_MAX_RUN_SECONDS)
        report['status'] = 'complete'
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = repr(error)
        report['partial_walls'], report['partial_timings'] = WALLS, TIMINGS
        raise
    finally:
        report['ended_at'] = datetime.now(timezone.utc).isoformat()
        (work / f'{name}-report.json').write_text(json.dumps(report, sort_keys=True, indent=1) + '\n')
    return report


def cost_proposal(finish_seconds: float, slowest_seconds: float) -> dict:
    """C8 floor and the §6 reserve rule. The owner sets the committed values at the checkpoint."""
    p4_floor = max(60, math.ceil(3 * finish_seconds / 30) * 30)
    floor = max(FLOOR_MINIMUM_SECONDS, p4_floor)
    reserve = math.ceil((RESERVE_FACTOR * slowest_seconds + floor) / 60) * 60
    return {'p4_floor_seconds': p4_floor, 'floor_seconds': floor, 'floor_changes': floor != FLOOR_MINIMUM_SECONDS,
            'reserve_seconds': reserve, 'slowest_member_wall_seconds': slowest_seconds,
            'fit_gate_passes': slowest_seconds <= LAUNCHER_DEFAULT_SECONDS - reserve}


def history_fit(walls: list[dict]) -> dict | None:
    """Per-member engine seconds (wall minus children) against `WorkflowChildCall` rows at member start (S4)."""
    points = [(w['history']['WorkflowChildCall'], w['wall_seconds'] - sum(w['children'].values())) for w in walls]
    if len({x for x, _ in points}) < 2:
        return None
    fit = linear_fit(points)
    slope, intercept = fit['slope_seconds_per_source'], fit['intercept_seconds']
    return {'slope_seconds_per_child_call': slope, 'intercept_seconds': intercept, 'points': fit['points'],
            'projected_engine_seconds': {str(mark): intercept + slope * mark for mark in HISTORY_MARKS}}


def summarize(work: Path) -> dict:
    """Combine the scenario reports into the §6 measures and the C8 and reserve proposal."""
    reports = {name: json.loads((work / f'{name}-report.json').read_text()) for name in COST_SCENARIOS
               if (work / f'{name}-report.json').exists()}
    calls = {name: report['scenarios'][name]['invocations'] for name, report in reports.items()
             if report['status'] == 'complete'}

    def walls(name: str, index: int) -> list[dict]:
        return calls[name][index]['walls'] if name in calls and index < len(calls[name]) else []

    def finish(call: dict) -> float:
        return sum(t['seconds'] for t in call['timings'] if t['label'] in FINISH_LABELS)

    every = [wall for value in calls.values() for call in value for wall in call['walls']]
    open_walls, closed_daily = walls('open', 0), walls('closed', 1)
    finish_seconds = {f'{name}-{index}': finish(call) for name in ('closed', 'finish') if name in calls
                      for index, call in enumerate(calls[name])}
    slowest = max(every, key=lambda wall: wall['wall_seconds']) if every else None
    measures = {
        'incomplete_scenarios': [name for name in COST_SCENARIOS if name not in calls],
        'open_member_wall_seconds': {str(mark): open_walls[mark]['wall_seconds'] for mark in OPEN_MARKS
                                     if mark < len(open_walls)},
        'closed_first_publication_wall_seconds': {wall['period']: wall['wall_seconds'] for wall in walls('closed', 0)
                                                  if wall['kind'] == 'quarterly'},
        'closed_measure_1_wall_seconds': closed_daily[0]['wall_seconds'] if closed_daily else None,
        'closed_fanout_wall_seconds': closed_daily[1]['wall_seconds'] if len(closed_daily) > 1 else None,
        'authority_wall_seconds': next((wall['wall_seconds'] for wall in walls('authority', 1)
                                        if wall['kind'] == 'quarterly'), None),
        'finish_seconds': finish_seconds,
        'slowest_member': None if slowest is None else {key: slowest[key] for key in
                                                        ('kind', 'period', 'wall_seconds', 'children', 'outcome')},
        'history': {name: history_fit([wall for call in value for wall in call['walls']]) for name, value in calls.items()},
        'load_at_start': {name: [min(w['load_at_start'][0] for w in ws), max(w['load_at_start'][0] for w in ws)]
                          for name, ws in ((n, [w for c in v for w in c['walls']]) for n, v in calls.items()) if ws},
        'exits': {name: [call['exit'] for call in value] for name, value in calls.items()},
    }
    complete = not measures['incomplete_scenarios'] and finish_seconds and slowest is not None
    proposal = cost_proposal(max(finish_seconds.values()), slowest['wall_seconds']) if complete else None
    return {'format_version': COST_FORMAT, 'kind': 'summary', 'work': str(work),
            'release_ids': sorted({report['release_id'] for report in reports.values()}),
            'measures': measures, 'proposal': proposal}
```

9. In `main`, add two subparsers before `args = parser.parse_args(argv)`:

```python
    scenario_parser = commands.add_parser('scenario')
    scenario_parser.add_argument('--name', choices=COST_SCENARIOS, required=True)
    scenario_parser.add_argument('--release-manifest', type=Path, required=True)
    scenario_parser.add_argument('--work', type=Path, required=True)
    scenario_parser.add_argument('--counts', type=Path, required=True)
    scenario_parser.add_argument('--scale', choices=sorted(SCALES), required=True)
    summarizing = commands.add_parser('summarize')
    summarizing.add_argument('--work', type=Path, required=True)
```

   After the `count` branch, add:

```python
    if args.command in ('scenario', 'summarize'):
        work = args.work.resolve()
        if work.is_relative_to('/tmp') or work.is_relative_to('/private/tmp'):
            raise SystemExit('measurement work must be under the project, not /tmp')
        if args.command == 'summarize':
            summary = summarize(work)
            (work / 'measurement.json').write_text(json.dumps(summary, sort_keys=True, indent=1) + '\n')
            sys.stdout.write(json.dumps({'measures': summary['measures'], 'proposal': summary['proposal']},
                                        sort_keys=True, indent=1) + '\n')
            return 0 if summary['proposal'] is not None else 1
        work.mkdir(parents=True, exist_ok=True)
        report = run_scenario(args.name, args.release_manifest.resolve(), work,
                              json.loads(args.counts.read_text()), args.scale)
        sys.stdout.write(json.dumps({'scenario': args.name, 'status': report['status']}) + '\n')
        return 0
```

> Deviation: D2. One helper, `start_report`, builds the report header for `run`, `run_finish_only` and `run_scenario` (task 9 report).
> Deviation: the plan's `history_counts` query (`table_name = 'WorkflowChildCall'`) matched no row, because record kinds share physical tables. f1cd024 matches the `partition` suffix in `SourceState` instead. d8352a9 makes the match exact.
> Deviation: D5. d8352a9 makes `summarize` refuse a proposal unless each invocation has its expected exit and one wall per dispatched member, builds the scenario plans inside the `try` so that a failure report is always written, and requires `--work` under the project root and not under `<project>/data`. 54601ff (whole-branch review and Codex) refuses mixed release, flags or scale across reports, reads a minimal failed report safely, and case-folds the `data` check.

- [x] **Step 4: Run the tests to verify they pass.**

Run: the test command with target `test_measure_cost`.
Expected: 4 pass.

> Deviation: after D5 (d8352a9), `test_measure_cost` has 21 tests, not 4.

- [x] **Step 5: Smoke-check the mechanics on the D5 interpreter.** This checks the script, not the release. It runs from the main checkout's installed D5 release, with the worktree's script:

```bash
cd /Users/lowell/Projects/sec-edgar-local
WT=$PWD/.claude/worktrees/stage1b-per-member-cost
R=$PWD/releases/sha256=aa8de1ac09fa8ef1a8f638301b25c370af5222e9ef0b02fd117866c2260a6ab4
W=$PWD/fixture-data/s1b-smoke-$(date -u +%Y%m%dT%H%M%SZ)
for name in open closed authority finish; do
  "$R/venv/bin/python" -I -B -X pycache_prefix=/dev/null "$WT/scripts/measure-d5-drain.py" scenario --name "$name" --release-manifest "$R/release.json" --work "$W" --counts "$PWD/specs/evidence/d5-release/counts.json" --scale smoke || echo "$name failed"
done
"$R/venv/bin/python" -I -B -X pycache_prefix=/dev/null "$WT/scripts/measure-d5-drain.py" summarize --work "$W"
```

Then check that the D5 `run` path keeps its behavior after the refactor:

```bash
"$R/venv/bin/python" -I -B -X pycache_prefix=/dev/null "$WT/scripts/measure-d5-drain.py" run --release-manifest "$R/release.json" --work "$W-d5run" --counts "$PWD/specs/evidence/d5-release/counts.json" --scale smoke
```

Expected: four `"status": "complete"` lines and a summary whose `proposal` is not null. The D5 `run` prints its measures and exits 0. `incomplete_scenarios` is empty, and every scenario has walls, children and history counts. In `authority`, step 1 has only daily members, and step 2 has one quarterly member. If a scenario fails or the authority members differ, fix the script and run the smoke again. Do not commit smoke output.

> Deviation: D4. The agent's worktree guard refused the D5 interpreter in the main checkout, so the owner ran the smoke in the Terminal panel (`step5-smoke.sh`). The re-run after d8352a9 (`step5-smoke-2.sh`) put `W` under the worktree's `fixture-data/`, because the new `--work` guard anchors on the script's own checkout. Both runs passed: four scenarios complete, authority exits [0, 10], proposal not null, D5 `run` exit 0.

- [x] **Step 6: Commit.**

```bash
git add scripts/measure-d5-drain.py packages/sec-edgar-ingest/tests/test_measure_cost.py
git commit -m "feat(scripts): measure Stage 1b member costs one scenario per process"
```

> Deviation: the controller made the Step 6 commit (f1cd024), because the implementer stopped at Step 5.

---

### Task 10: Full gate, whole-branch review and merge to main (HUMAN checkpoint)

**Files:**
- Create: `specs/evidence/stage1b/gate.md`

**Interfaces:**
- Consumes: the branch after Tasks 1–9.
- Produces: `main` holding the reviewed change, from which Task 11 builds.

- [x] **Step 1: Run the full gate in the background.** From the worktree root, with `run_in_background`. Plan 4's pre-merge gate used this environment (`specs/evidence/d5-release/gate.md`, "Environment deviation"): the shadow venv as the uv project environment, no sync, and `PYTHONDONTWRITEBYTECODE` unset.

```bash
env -u PYTHONDONTWRITEBYTECODE UV_PROJECT_ENVIRONMENT=/tmp/s1b-venv UV_NO_SYNC=1 SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache sh scripts/check-sec-edgar-ingest.sh > /Users/lowell/Projects/sec-edgar-local/fixture-data/stage1b-gate.log 2>&1; echo "exit $?" >> /Users/lowell/Projects/sec-edgar-local/fixture-data/stage1b-gate.log
```

Expected: the log ends with `exit 0`, and unittest prints `OK`. The count is 1020 plus the new tests, in 71 modules: 64 plus the seven new `test_*` modules (`test_etl_integrity`, `test_full_check_budget`, `test_etl_columnar`, `test_etl_equivalence`, `test_etl_incremental`, `test_release_1b`, `test_measure_cost`). Support modules are not counted. The gate runs before the merge, because the Step 5 checkpoint approves the merge on it. If this environment fails for a reason other than a test, stop and ask. Do not move the gate after the merge.

> Deviation: run 1 wrote its log under the worktree, not the main checkout, and from run 5 a wrapper kept the gate's exit code. An untracked `.venv` symlink to the main `.venv` was needed for two `InstalledLauncherTests`. Runs 1 to 3 were stopped because `src` changed. Runs 4 and 5 on 8a7e9c3 failed one test on a `runtime.py` `killpg` EPERM race. Run 6 on 8c1c321 passed after the D8 fix: `Ran 1108 tests`, `OK`, 71 modules (specs/evidence/stage1b/gate.md).

- [x] **Step 2: Record the gate.** Create `specs/evidence/stage1b/gate.md` with the commit, the start and end times, the `Ran N tests in S s` line, `OK` and the module count. Commit:

```bash
git add specs/evidence/stage1b/gate.md
git commit -m "docs(evidence): record the Stage 1b branch gate"
```

- [x] **Step 3: Whole-branch review.** Use the requesting-code-review skill. It dispatches the `code-reviewer` agent on `main..stage1b-per-member-cost`, against the spec (as amended in Task 1), this plan and its Decisions. Name C5 and C6 independence, the locality proof and P8 as review focus. Fix each accepted finding with a test, re-run the affected modules, and commit. If a fix changes code, re-run Step 1 and update `gate.md`.

> Deviation: the review had two seats: the `code-reviewer` agent and a Codex read-only second opinion (D6). Under D7 the fix wave (6e8e86f, then dd1f0fc and 8a7e9c3) made the Arrow-only A1 membership check, a replay full-check test, a retry test and recovery text for a refused C6 candidate, and the full-resolution row count. Under D8, 17d78da and 8c1c321 fixed the `runtime.py` `forward` EPERM race, outside the plan's file list.

- [x] **Step 4: Check that the branch carries no platform member.**

```bash
git -C /Users/lowell/Projects/sec-edgar-local show stage1b-per-member-cost:pyproject.toml | grep -n 'members'
git -C /Users/lowell/Projects/sec-edgar-local diff --stat d68787fe8602e9d81a26d2012feec9bfad5c52df stage1b-per-member-cost -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml
```

Expected: `members = ["packages/sec-edgar-ingest"]`, and no diff output.

- [x] **Step 5: Owner checkpoint (HUMAN).** Show the owner the gate record, the review result and `git log --oneline main..stage1b-per-member-cost`. Ask for approval to merge the branch into `main` before the release build. Stop until the owner answers. Log the answer as a Decision.

- [x] **Step 6: Merge.** In the main checkout:

```bash
cd /Users/lowell/Projects/sec-edgar-local
git status --porcelain --untracked-files=all
git merge --ff-only stage1b-per-member-cost || git merge --no-ff stage1b-per-member-cost -m "merge: Stage 1b per-member cost"
git status --porcelain --untracked-files=all
```

Expected: both `git status` calls print nothing. If `main` gained commits that touch the changed files, stop and ask before merging. Keep the worktree until Task 14 ends.

---

### Task 11: Build and verify the 1b release (C9; spec §7 items 1–3)

Run in the main checkout on `main`.

**Files:**
- Create: `specs/evidence/stage1b/release.md`

**Interfaces:**
- Consumes: clean committed `main` after Task 10.
- Produces: `releases/sha256=<1B>/`. Its ID, manifest path and `git_revision` feed Tasks 12–14.

- [x] **Step 1: Confirm a clean tree.**

```bash
cd /Users/lowell/Projects/sec-edgar-local
git status --porcelain --untracked-files=all
git rev-parse HEAD
```

Expected: no status output. Record the revision.

- [x] **Step 2: Build.**

```bash
cd /Users/lowell/Projects/sec-edgar-local
export UV_PYTHON_DOWNLOADS=never
project=$(pwd -P)
UV_OFFLINE=1 uv run --offline --locked --package sec-edgar-ingest python scripts/prepare-native-release.py --project "$project" --releases "$project/releases" --python "$project/.venv/bin/python" --artifact-cache "$project/releases/artifact-cache" --offline
```

Expected: one printed path, `…/releases/sha256=<1B>`. Record `<1B>`.

- [x] **Step 3: Check identity, lock and export (C9).** Plan 4 found that `runtime-requirements.txt` holds a comment with a random temporary path, so compare the requirement lines only.

```bash
cd /Users/lowell/Projects/sec-edgar-local
B=releases/sha256=<1B>
D5=releases/sha256=aa8de1ac09fa8ef1a8f638301b25c370af5222e9ef0b02fd117866c2260a6ab4
cmp "$B/uv.lock" "$D5/uv.lock" && echo lock-identical
[ "$(grep -v '^#' "$B/runtime-requirements.txt" | shasum -a 256)" = "$(grep -v '^#' "$D5/runtime-requirements.txt" | shasum -a 256)" ] && echo export-lines-identical
git diff --exit-code d68787fe8602e9d81a26d2012feec9bfad5c52df HEAD -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml && echo inputs-identical
python3 -c "import json,sys; i=json.load(open(sys.argv[1]))['identity']; print(i['application']['version'], i['git_revision'], sorted(d['name'] for d in i['dependencies']))" "$B/release.json"
```

Expected: `lock-identical`, `export-lines-identical`, `inputs-identical`. Version `0.2.0`. `git_revision` equals Step 1's revision. The dependency names equal the D5 list, with no platform package.

- [x] **Step 4: Offline verification on the 1b interpreter.** Plan 4 found that the harness guard refuses any path inside a checkout, and that the verifier's children inherit the working directory. So the harness and evidence go under a directory outside the checkout:

```bash
cd /Users/lowell/Projects/sec-edgar-local
project=$(pwd -P)
release="$project/releases/sha256=<1B>"
outside=$(mktemp -d)
UV_OFFLINE=1 uv run --offline --locked --package sec-edgar-ingest python - "$outside/harness" <<'PY'
import shutil, sys
from pathlib import Path
source = Path('packages/sec-edgar-ingest/tests').resolve()
sys.path.insert(0, str(source))
from network_guard import install
install()
from workflow_proof import harness_files
target = Path(sys.argv[1])
for path in harness_files():
    destination = target / path.relative_to(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
print(target)
PY
(cd "$outside" && "$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null "$project/scripts/verify-native-release.py" --release "$release" --harness "$outside/harness" --evidence "$outside/evidence")
cp -R "$outside/evidence" "$project/fixture-data/s1b-verify-evidence"
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -c "import sys; from pathlib import Path; from sec_edgar_ingest.runtime import preflight_current; print(preflight_current(Path(sys.argv[1])).release_id)" "$release/release.json"
```

Expected: the verifier prints JSON with `"exit": 0` and `"release_id": "<1B>"`. `preflight_current` prints `<1B>`.

- [x] **Step 5: Confirm retention.**

```bash
ls /Users/lowell/Projects/sec-edgar-local/releases
```

Expected: `sha256=49b7a2ed…`, `sha256=900952a8…`, `sha256=d718ae5f…`, `sha256=fc68adef…`, `sha256=aa8de1ac…` and `sha256=<1B>` are all present.

- [x] **Step 6: Write the release evidence.** Create `specs/evidence/stage1b/release.md` with:
1. The 1b release ID, its manifest path and its `git_revision` (§7 item 1).
2. The Step 3 results: identical lock, export lines and inputs, version `0.2.0`, and no platform package (§7 item 2).
3. The verifier JSON, the preflight output and the evidence directory, with D5, `fc68adef…` and older releases kept (§7 item 3).
4. The line "No SEC request was sent. Verification used fixture acquisition only."

```bash
git add specs/evidence/stage1b/release.md
git commit -m "docs(evidence): record the 1b release build and offline verification"
```

---

### Task 12: Measure on the 1b release, set the floor, and the owner checkpoint (C8; spec §6; HUMAN checkpoint)

Run in the main checkout on `main`.

**Files:**
- Create: `specs/evidence/stage1b/measurement.md`, `specs/evidence/stage1b/measurement.json`
- Modify (only if the floor rule gives more than 480): `packages/sec-edgar-ingest/src/sec_edgar_ingest/config.py:26–27`, `specs/evidence/stage1b/release.md`

**Interfaces:**
- Consumes: `<1B>` from Task 11; the Task 9 script.
- Produces: the measured floor and reserve, the fit-gate result, and the owner's decision. Tasks 13 and 14 consume them. If the floor changes, a rebuilt release `<1B'>` replaces `<1B>` in Tasks 13 and 14.

- [x] **Step 0: Check the machine load.** Spec §6 names load as the known risk: the slowest member may pass on a quiet machine and fail at the D5 run's load. Run `sysctl vm.loadavg` and record the output. Do not start while a full gate, a release build or another heavy session runs on this machine. If the 1-minute load is above 2, ask the owner whether to wait.

> Deviation: the 1-minute load was 1.81 to 1.94, under the limit of 2. Another project's Python job (PID 71263) still used about one core. It was not stopped. measurement.md "Limits" records it.

- [x] **Step 1: Run the four scenarios one after another, in the background.** Run them in sequence, not in parallel, so that they do not slow each other. With `run_in_background`:

```bash
cd /Users/lowell/Projects/sec-edgar-local
R=$PWD/releases/sha256=<1B>
W=$PWD/fixture-data/s1b-measure-$(date -u +%Y%m%dT%H%M%SZ)
mkdir "$W"
for name in open closed authority finish; do
  "$R/venv/bin/python" -I -B -X pycache_prefix=/dev/null scripts/measure-d5-drain.py scenario --name "$name" --release-manifest "$R/release.json" --work "$W" --counts "$PWD/specs/evidence/d5-release/counts.json" --scale full > "$W/$name.log" 2>&1
  echo "$name exit $? $(date -u +%FT%TZ)" >> "$W/driver.log"
done
```

Expected: `driver.log` holds four `exit 0` lines. This can take more than 12 hours. A failed scenario still leaves its `<name>-report.json`. Do not re-run a scenario before reading why it failed.

> Deviation: the loop ran from a driver script, `fixture-data/run-s1b-measure.sh`, under `caffeinate -i`. The driver also logged the load at each scenario end. Four `exit 0` lines, in 4 h 35 min.

- [x] **Step 2: Summarize.**

```bash
"$R/venv/bin/python" -I -B -X pycache_prefix=/dev/null scripts/measure-d5-drain.py summarize --work "$W"
cp "$W/measurement.json" specs/evidence/stage1b/measurement.json
```

Expected: a non-null `proposal`. If a scenario is incomplete, `proposal` is null. Report this at Step 4, and do not invent values.

- [x] **Step 3: Write `specs/evidence/stage1b/measurement.md`.** Use these sections:
  - `## Inputs`: the release ID, the work directory, the bodies (quarterly 370,321 rows, daily 3,652 rows), and the flags.
  - `## Results`: every measure, in a table for each scenario. Include the open marks at 1, 10, 40 and 80, the closed first publications, measure 1, the fan-out, the authority member, the finish steps, the slowest member, the history fits with the projections at 400 and 1,200 child calls, and the load range for each scenario.
  - `## Proposal`: the P4 floor rule's value, the C8 floor, the reserve, and the fit gate (`slowest ≤ 3,300 − reserve`).
  - `## Limits`: the line "Fixture timings can only underestimate native cost (plan 2 F11)." Also give the load range, and state that the history-scan cost is measured, not fixed (S4).

Then:

```bash
git add specs/evidence/stage1b/measurement.md specs/evidence/stage1b/measurement.json
git commit -m "docs(evidence): record the Stage 1b member-cost measurement"
```

- [x] **Step 4: Owner checkpoint (HUMAN).** Show the owner `measurement.md`: the slowest member, the proposed floor and reserve, and the fit-gate result. Ask for the floor and reserve integers.
  - **If the fit gate fails, the plan stops here** (spec §6). The owner either approves a named, measured limit, or adds a columnar full-rebuild path as a new roadmap stage. Do not widen this stage. Record the answer as a Decision. Continue only if the owner approves a named limit.
  - Stop until the owner answers. Log the answer as a Decision, with the owner's words.

- [ ] **Step 5: Floor change (only if the approved floor is more than 480).** In `config.py`, replace:

```python
# Owner decision D2 (plan 4, Task 2): three times the measured finish step (152.2 s), rounded up to 30 s.
DISPATCH_RESERVE_FLOOR_SECONDS = 480
```

with (write the measured finish seconds and the approved floor):

```python
# Stage 1b (plan 5, C8): max(480, three times the measured full-size finish step, rounded up to 30 s).
DISPATCH_RESERVE_FLOOR_SECONDS = FLOOR
```

Run the test command with `test_config test_local_launcher test_workflow_cli`, then the full gate in the background (Task 10 Step 1, from the main checkout). Commit `config.py` alone:

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/config.py
git commit -m "fix(config): set the dispatch-reserve floor from the Stage 1b measurement"
```

Then repeat Task 11 Steps 1–5 to rebuild and re-verify. Append a section `## Rebuilt for the floor` to `release.md`. It names both release IDs (`<1B>` measured, `<1B'>` rebuilt), the floor commit, and the line "The floor change touches only the constant, so the member and finish timings taken on `<1B>` stay valid for `<1B'>` (spec §6)." Commit `release.md`. From here on, `<1B>` means the rebuilt release.

> Skipped: the owner approved floor 480 s (decision D10), which is not above 480, so config.py stays. Not deferred.

---

### Task 13: Select the 1b release in the live config (C10; spec §7 item 5; HUMAN checkpoint)

**Files:**
- Modify: `conf/sec-edgar-local.json` (`execution.dispatch_reserve_seconds`, `runtime.release_manifest`)
- Modify: `specs/evidence/stage1b/release.md`

**Interfaces:**
- Consumes: the Task 12 Decision's reserve; `<1B>`.
- Produces: the new effective-config SHA-256, which Task 14 and the Handoff name.

- [x] **Step 1: Edit the config.** In `conf/sec-edgar-local.json`, set `execution.dispatch_reserve_seconds` to the approved reserve, and `runtime.release_manifest` to `/Users/lowell/Projects/sec-edgar-local/releases/sha256=<1B>/release.json`. Change nothing else.

> Deviation: only `runtime.release_manifest` changed. `execution.dispatch_reserve_seconds` was already 1800 (plan 4 D4), which D10 approved.

- [x] **Step 2: Offline preflight and hash on the 1b interpreter.**

```bash
cd /Users/lowell/Projects/sec-edgar-local
release=releases/sha256=<1B>
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -c "
from pathlib import Path
from sec_edgar_ingest.config import DISPATCH_RESERVE_FLOOR_SECONDS, admit_dispatch_reserve, load_config
from sec_edgar_ingest.runtime import preflight_current
from sec_edgar_ingest.storage.contracts import deployment_binding
settings = load_config(Path('conf/sec-edgar-local.json'))
print('floor', DISPATCH_RESERVE_FLOOR_SECONDS)
print('reserve', admit_dispatch_reserve(settings))
print('release', preflight_current(Path(settings.runtime.release_manifest)).release_id)
print('effective', settings.config_sha256)
print('binding', deployment_binding(settings))"
git diff conf/sec-edgar-local.json
```

Expected: `floor` and `reserve` are the approved integers, `release` is `<1B>`, and `effective` is a new SHA-256 (before: `32e822323d24d2bb3ee41b53e7c3eb16082b7dc9059d6ba17c578dbdd1c0579e`). The diff shows at most two changed values. `binding` holds no `execution` field. Run no launcher command: `prepare_invocation` writes logs.

- [x] **Step 3: Owner checkpoint (HUMAN).** Show the owner the diff and the Step 2 output. Ask for approval of the live-config selection. Stop until the owner answers. Log the answer as a Decision.

- [x] **Step 4: Record and commit.** Append a section `## Live-config selection` to `release.md`, with the effective-config SHA-256, the floor, the reserve, the binding output, and the line "No SEC request was sent in this stage." Then:

```bash
git add conf/sec-edgar-local.json specs/evidence/stage1b/release.md
git commit -m "chore(config): select the 1b release with the measured dispatch reserve"
```

Add the commit hash to `release.md` in the Task 14 commit, not by amending.

---

### Task 14: Parent-spec and runbook amendments (spec §8)

**Files:**
- Modify: `specs/sec-filing-index-ingestion-spec.md` (§4.6 last paragraph, §4.8 table row and selection text, §4.9 after the D5 paragraph)
- Modify: `docs/runbooks/local-ingestion.md:37`
- Modify: `specs/evidence/stage1b/release.md` (the Task 13 commit hash)

**Interfaces:**
- Consumes: `<1B>`, the Task 12 and 13 Decisions, the Task 13 SHA-256 and commit, and the Task 8 result.

- [x] **Step 1: §4.6.** Replace:

```text
Atomicity is per quarter, not across the complete historical catalog. Readers capture a generation
with `capture_quarter`, then use `read_quarter` to validate its manifest, files, and counts before
exposing rows.
```

with:

```text
Atomicity is per quarter, not across the complete historical catalog. Readers capture a generation
with `capture_quarter`, then use `read_quarter` to validate its manifest, files, and counts before
exposing rows. The engine checks a generation or an observation that a committed pointer, a retained
capture or a checked result names by its exact manifest and file hashes, without reading rows; the
full content check runs once, before a full rebuild's pointer commits, and again in `read_quarter`,
`approve` and `rollback`. A quarter that only gains new sources is rebuilt from its base generation and
the new rows, and an equivalence check against the full path's resolution of every key that can change
runs before its pointer commits. (Stage 1b, plan 5; C1–C6, C11.)
```

> Deviation: §4.6 also carries the owner-approved recovery sentences for a refused incremental candidate (D7, finding I1), and says "the equivalence check", not "C6". c9125fd (D12) later reworded the recovery text: removing objects is not a supported step. It also named the stored-candidate full check and the C4 conditions.

- [x] **Step 2: §4.8 table.** Replace the `| Dispatch reserve | …` row with:

```text
| Dispatch reserve | `execution.dispatch_reserve_seconds=RESERVE`, set from measured member costs (Stage 1b, plan 5; [measurement](evidence/stage1b/measurement.md)). Required for a new live workflow run. The value must be at least the floor of FLOOR seconds (release constant) and below `max_run_seconds`. The launcher refuses a timeout at or below the reserve. (Stage 1a, plan 4; Stage 1b, plan 5.) |
```

Write the approved integers in place of `RESERVE` and `FLOOR`. If the owner approved a named limit at Task 12, add one sentence that names it.

- [x] **Step 3: §4.8 selection.** Replace the selected-manifest code block's path line with `/Users/lowell/Projects/sec-edgar-local/releases/sha256=<1B>/release.json`. Before the paragraph that begins `Stage 1a (plan 4) selected the D5 release`, add:

```text
Stage 1b (plan 5) selected the 1b release `<1B>` and the measured reserve at commit `<Task 13 commit>`.
The effective-config SHA-256 is `<Task 13 SHA-256>`, confirmed by offline preflight.
```

Then change the next paragraph's first words, `Stage 1a (plan 4) selected`, to `Before that, Stage 1a (plan 4) selected`. Write the full release ID, commit hash and SHA-256 in place of the bracketed names.

> Deviation: c9125fd (D12) rewrote the selection sentence. 6d80da4 selected the release only. The reserve stays at 1800 s, set in Stage 1a and now backed by the measurement.

- [x] **Step 4: §4.9.** After the paragraph that ends `[two-release evidence](evidence/d5-release/two-release.md).)`, add:

```text
The 1b release changes no generation, manifest, receipt, selection or config format (C7). It continues
D5-origin pending work, and selecting the D5 release again for a store that the 1b release wrote is
supported (tested offline). (Stage 1b, plan 5; [two-release evidence](evidence/stage1b/two-release.md).)
```

If Task 8 recorded a limit instead, write that limit.

> Deviation: D3. §4.9 carries the narrowed wording of `two-release.md`, not the plan's "is supported (tested offline)". It says "sibling-completion receipts", because the parent spec does not define B4.

- [x] **Step 5: Runbook.** In `docs/runbooks/local-ingestion.md` line 37, replace `The floor is 480 s and the live reserve is 1800 s (provisional).` with `The floor is FLOOR s and the live reserve is RESERVE s, set from measured member costs (Stage 1b).` Write the approved integers.

- [x] **Step 6: Verify and commit.**

```bash
grep -n "Stage 1b, plan 5" specs/sec-filing-index-ingestion-spec.md
grep -n "provisional" specs/sec-filing-index-ingestion-spec.md docs/runbooks/local-ingestion.md
```

Expected: three matches for the first grep (§4.6, the §4.8 row, §4.9), and no match for "provisional" in the §4.8 row or the runbook line. Add the Task 13 commit hash to `release.md`. Then:

```bash
git add specs/sec-filing-index-ingestion-spec.md docs/runbooks/local-ingestion.md specs/evidence/stage1b/release.md specs/plans/5-sec-filing-index-per-member-cost.md
git commit -m "docs(specs): amend the parent spec for the 1b release"
```

> Deviation: e0c21c3 also changed `docs/runbooks/local-recovery.md` (new row "Refused incremental candidate") and did not add this plan file. A second commit, 8aa41e0, aligned the 1b spec's §4.1 table and its C5 and C6 rows with the built code. c9125fd fixed six Task 14 review Minors after D12.

---

## After the last task

Run the writing-plans Plan Completion Protocol, step 3a included.

**Deferred items** (spec §7). In `specs/deferred_items.md`, section `4-sec-filing-index-bounded-drain — 2026-10-27`:
- Tick "Per-member cost", "Unmeasured drain costs" and "Provisional live reserve", each with `→ done in plan 5` and its evidence path (`specs/evidence/stage1b/measurement.md`, `release.md`).
- Under "B4 single-candidate limit", add one line with the revisit-trigger check against the §6 measures: do repeated child sequences or refused-skip scans form a material share of run time? Leave the item open unless the owner closes it.
- Leave "Order-aware two-release proofs" and "Test-hygiene Minors" open.
- In this plan's own section, add a new item for the history-scan cost (S4). Give its measured slope (seconds per `WorkflowChildCall` row), the projections at 400 and 1,200 child calls, `Size: plan`, and `Revisit if: a live run's per-member engine time grows past the measured slope, or the projection at the live store's child-call count exceeds the reserve's margin.`

**`## Handoff to later stages`.** It must name every value the plan 2 revision must change (spec §7):
- Global Constraints: the release `<1B>`, the effective-config SHA-256, and the reserve and floor.
- Regenerate `conf/stage2/*.json` with the 1b manifest and the reserve key.
- Re-verify `scripts/baseline-campaign.py` against `<1B>` (plan 2 Task 1 Steps 4–5). `catalog`, `publication`, `reader`, `completion`, `checked` and `runner` changed. No result format changed (C7).
- The `campaign.md` Release gate reads against `<1B>`. Stop rules still read durable result fields.
- Traps: the §4.9 two-release result; the measured limit if the owner approved one; the fixture-only measurement (plan 2 F11); and the S1 trust model. An engine path no longer detects a hash-consistent content fault. `read_quarter` and `rollback` still do.
- Stages 3 and 5: the reserve now covers the measured member classes. A member running at the cutoff still completes (parent §4.7).
- Plan 3 DF6: the 1b release is built, so the platform member may merge to `main` under plan 3's Merge gate. That merge belongs to the platform roadmap.

Remove the `stage1b-per-member-cost` worktree and `/tmp/s1b-venv` after the retire commit (finishing-a-development-branch).

## Handoff to later stages

The 1b spec is `specs/completed/sec-filing-index-per-member-cost.md` after the retire commit. Deferred items that a later stage inherits are in `specs/deferred_items.md`, section `5-sec-filing-index-per-member-cost — 2026-10-28`.

- **Stage 2 (baseline campaign; the plan 2 revision).** Consumes, as built:
  - Release `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b` (manifest `releases/sha256=9fa189a0…/release.json`, `git_revision` `50423a404fb50a959b3ca4077301117d32804cc6`), selected in the live config at commit `6d80da4d9e1f30461c45a826fecbf8eefc899201`. Effective-config SHA-256 `db62e7fb8c941f125f84992c5bccfdbb65d6461231d899054af505700e9004b1`. Reserve 1800 s. Floor 480 s (release constant, unchanged). Evidence: `specs/evidence/stage1b/release.md`, `measurement.md`, `gate.md`.
  - The plan 2 revision must change: its Global Constraints (release, effective-config SHA-256, reserve, floor); `conf/stage2/*.json`, regenerated with the 1b manifest and the reserve key; `scripts/baseline-campaign.py`, re-verified against the 1b release (plan 2 Task 1 Steps 4–5); and the `campaign.md` Release gate, read against the 1b release. Stop rules still read durable result fields.
  - Changed modules: `etl/catalog.py`, `publication.py`, `reader.py`, `commands.py`, `transform.py`, `manifest.py`, `contracts.py`; new `etl/columnar.py`, `incremental.py`, `equivalence.py`; `workflows/completion.py`, `checked.py`, `runner.py`; `runtime.py` (the D8 EPERM fix). No result, generation, manifest, receipt, selection or config format changed (C7; 1b spec §2).
  - Difference from the roadmap `Produces`: no named measured limit was approved, because the fit gate passed (slowest member 1,010.9 s ≤ 3,300 − 1,800 s). The reserve value did not change from the plan 4 provisional 1800 s. The measurement now backs it (D10).
  - Traps: (a) S1 trust model (1b spec §9 S1; parent §4.6). An engine path accepts a generation by its exact hashes, so it no longer detects a hash-consistent content fault. `read_quarter`, `approve`, `rollback` and `catalog._existing` still run the full check. (b) The §4.9 two-release result covers only stores with first-generation full-rebuild 1b generations (`specs/evidence/stage1b/two-release.md`, "Limits of the proof"; D3). (c) The measurement used fixture acquisition only, so its timings can only underestimate native cost (plan 2 F11). The native `collect` child is not measured. (d) A full-size closed-quarter first publication still takes about 912–1,011 s on the full path (1b spec §2: no columnar full rebuild). (e) A candidate that C6 refuses blocks its own retry as `invalid_source`, which is not retryable. Object removal is not a supported recovery step (1b spec §4.3 item 5; `docs/runbooks/local-recovery.md`; D12). (f) Per-member engine time grows with the history scan (S4, measured, not fixed).
  - Deferred into this stage: the history-scan cost, the refused-C6-candidate retry block and the first-generation two-release limit (section `5-sec-filing-index-per-member-cost — 2026-10-28`). The B4 single-candidate limit stays open in section `4-sec-filing-index-bounded-drain — 2026-10-27`, and its revisit trigger names Stage 2.
- **Stage 3 (daily catch-up).** Consumes the same release, config, reserve and floor as Stage 2. The reserve now covers the measured member classes (`specs/evidence/stage1b/measurement.md`): open-quarter daily members at n = 1 to 80 sources, measure 1, the 14-quarter fan-out and full-size quarterly members. A member running at the cutoff still completes (parent §4.7). Traps: (a) An open-quarter member whose quarter has a quarterly membership authority (the A1 path) is not measured. That is the common live case once SEC posts the open quarter's quarterly index. (b) Traps (a), (c), (e) and (f) of the Stage 2 bullet. Deferred into this stage: the unmeasured A1 member class and the history-scan cost (section `5-sec-filing-index-per-member-cost — 2026-10-28`).
- **Stage 4 (manual reconciliation).** Consumes the selected release and config, and the retained candidate, approval and rollback contracts. As built: `approve` and `rollback` keep the full content check (C3), and no format changed (C7). A quarter with a gate other than `clear`, a revert, a replacement snapshot or an incoming quarterly authority takes the full rebuild (C4). Traps: trap (a) of the Stage 2 bullet, and the refused-C6-candidate block (trap (e)), which needs a recovery disposition when it occurs. Removing the candidate's objects needs a separately reviewed operational decision (D12). Deferred into this stage: the refused-C6-candidate retry block (section `5-sec-filing-index-per-member-cost — 2026-10-28`).
- **Stage 5 (local scheduling).** Consumes the same release, config, reserve and floor, and the cutoff semantics of parent §4.7: a member running at the cutoff still completes. Traps: the unmeasured A1 member class and the history-scan growth (Stage 3 bullet). A schedule that lets the store's `WorkflowChildCall` rows grow raises per-member engine time (1b spec §6; measurement.md, "History scan (S4)"). Deferred into this stage: the history-scan cost and the unmeasured A1 member class (section `5-sec-filing-index-per-member-cost — 2026-10-28`).
- **Platform roadmap (not a stage of this roadmap).** Plan 3 DF6: the 1b release is built, so the platform member may merge to `main` under plan 3's Merge gate. That merge belongs to the platform roadmap.
