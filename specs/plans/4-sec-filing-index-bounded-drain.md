# Bounded Drain and the D5 Release Implementation Plan

**Status:** Approved by the owner, 2026-10-22, with defaults P1–P8 and amendments A1 and A2 as proposed (D1 below). Nothing is executed. This plan authorizes no SEC request.

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task via subagent-driven-development (the default) — or executing-plans when your human partner chose inline execution at the handoff. Steps use checkbox (`- [ ]`) syntax for tracking.

> Roadmap: specs/sec-filing-index-ingestion-roadmap.md, Stage 1a — on plan completion, tick the
> stage and re-validate later stages against what shipped.

**Goal:** Ship a reviewed native release (the D5 release) on which a workflow run stops starting members before its deadline, always writes its durable result, and processes each pending source's child sequence once.

**Architecture:** An offline measurement on release `fc68adef…` comes first and fixes the floor and the live reserve at an owner checkpoint. Then the engine change lands on a feature branch:

1. An optional config key, `execution.dispatch_reserve_seconds`, checked only when a new live run is admitted.
2. A dispatch cutoff at `deadline − reserve` in `runner.run_workflow`.
3. A no-child "sibling completion" receipt for a member whose source this run already completed.

The branch merges to `main` after the full gate and a whole-branch review. The D5 release is then built from clean `main`, verified offline and selected in the live config. Spec amendments close the plan.

**Tech Stack:** Python 3.14 (CPython 3.14.0, macOS arm64). Stdlib `unittest` under `packages/sec-edgar-ingest/tests/network_guard.py`. `uv` offline and locked. Installed releases under `releases/sha256=<id>/`. Measurement on the installed `fc68adef…` interpreter.

**Spec:** [specs/sec-filing-index-bounded-drain.md](../sec-filing-index-bounded-drain.md) (Stage 1a). Parent spec: [specs/sec-filing-index-ingestion-spec.md](../sec-filing-index-ingestion-spec.md).

## Global Constraints

Copied from the spec. Every task's requirements include this section.

- No SEC request, live run, or change under `data/` (spec §2). Approval of this plan authorizes no live traffic. The plan 2 revision for the D5 release, and its Task 4 owner gate, stay the only route to live traffic (spec §10).
- No change to the selection format, `aliases`, `superseded`, publication, catalog, parser or schema. Selection bytes and format (`sec-local-workflow-selection-v1`) do not change (B6).
- No new workflow outcome or exit code (spec §2).
- Existing receipts stay valid byte for byte (B5). With the key absent, every existing effective-config SHA-256 is unchanged (B1).
- The key check runs only at admission. It never runs in `Settings` validation (B2).
- The package version stays `0.2.0`. `uv.lock` and `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` are byte-identical to their `fc68adef…` build inputs (revision `3ca50c7`) (B7).
- The D5 release is built by `build_release` from clean committed `main` (B7). `fc68adef…` and older releases are retained (§4.9).
- No platform item. The platform workspace member stays off `main` until the D5 build (platform roadmap D1; plan 3 DF6).
- Tests use stdlib `unittest` under `network_guard.py`. Write each test before its implementation (spec §5).
- Measurement runtime: the installed `fc68adef…` interpreter with `-I -B -X pycache_prefix=/dev/null`, on a fresh store in a new git-ignored directory under the project, not under `/tmp` or `/private/tmp` (spec §6).

Execution environment (planning facts, not spec text):

- Tasks 1–8 run on branch `stage1a-bounded-drain` in a worktree (using-git-worktrees). A worktree has no `releases/` or `data/`. So every test and gate command in the worktree sets `SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache`. Release and data paths are absolute paths into the main checkout.
- Tasks 9–11 run in the main checkout `/Users/lowell/Projects/sec-edgar-local` on `main`, after the Task 8 merge.
- Test command, from the checkout or worktree root (replace `<target>` with a module, class or test name):

  ```bash
  SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py <target> -v
  ```

  > Deviation (Task 3): in the worktree, `uv run --offline --locked` cannot build an environment (`Failed to download pyarrow==25.0.1`, not in the uv cache). Tests ran with the main checkout's venv interpreter instead, with the worktree sources first on the path: `SEC_LOCAL_PROOF_CACHE=… PYTHONPATH=<worktree>/packages/sec-edgar-ingest/src /Users/lowell/Projects/sec-edgar-local/.venv/bin/python packages/sec-edgar-ingest/tests/network_guard.py <target> -v`. The Task 8 full gate and the release build must still use the `uv` command, from the main checkout after the merge.

  > Deviation (Task 5): tests that spawn native children (Task 5 on) cannot use the main venv even with `PYTHONPATH`. The main venv has an editable install of the main checkout's source, and `run_child` strips `PYTHON*` and uses `-I`. So the children run main-checkout code, which rejects `dispatch_reserve_seconds`. Use a shadow venv instead: `/tmp/drain-venv` (stdlib `venv` over the same base interpreter) holds one `.pth` file that lists, in this order, the worktree's `packages/sec-edgar-ingest/src` and the main venv's `lib/python3.14/site-packages`. Check with `/tmp/drain-venv/bin/python -I -c "import sec_edgar_ingest; print(sec_edgar_ingest.__file__)"` that the path is in the worktree. Run tests as `SEC_LOCAL_PROOF_CACHE=… /tmp/drain-venv/bin/python packages/sec-edgar-ingest/tests/network_guard.py <target> -v`.

## Decisions

- **D1** (owner, plan review, 2026-10-22): P1–P8 accepted as proposed, with amendments A1 and A2. That settles: B4 also skips when the selection's `already_complete` holds the source (P1, A1); the B4 receipt names no worksets, and `MemberResult` and `_validate_report` accept that exact shape (P2, A1); engine admission in `cli._validate_workflow`, before any store opens (P3, A2); the floor and reserve proposal rule (P4); the measurement design with the 14-quarter fan-out (P5); the origin release built from `3ca50c7` (P6); the merge to `main` before the build (P7); and skip-check gaps that are not reported (P8). The amendment tags in Task 1 keep the date 2026-10-22. Owner's words: "Approved". Applied in: Tasks 1, 2, 4, 6, 7 and 8–11.
- **D2** (owner, Task 2 checkpoint, 2026-10-23). The full measurement failed: its `open` and `closed` runs reached their hard deadline, so P4 gave no floor or reserve (`specs/evidence/d5-release/measurement.md`). Owner's words, in order: "D2: the slowest member does not fit, so add cheaper publication as a new roadmap stage. Floor and reserve: <integers, or say to defer them>." Then, after the controller recommended floor 300 s with the reserve deferred to D4: "D2 approved: measure finish only before setting the floor, add a per-member-cost stage before Stage 2 instead of accepting the limit, and continue Stage 1a with a provisional reserve." That settles four things.
  - The floor was not set until the finish step was measured alone (Task 2 Step 8b). That run (2026-10-23, `specs/evidence/d5-release/finish-measurement.json`) took 152.2 s for the finish step over 48 quarters. The floor is the P4 rule's value (approved in D1): `max(60, ceil(3 × 152.15 / 30) × 30)` = **480 s**. It replaces the provisional value Task 3 first used (60), in the one line `DISPATCH_RESERVE_FLOOR_SECONDS` in `config.py` (commit `51221e4`). The owner confirmed the 480 s integer in this session on 2026-10-23, by choosing "Approved, record it" in answer to: "The parent session says you replied "Approved" to the 480 s floor committed in 51221e4 … Do you confirm it here so I record it as D2?"
- **R1** (owner, review of Tasks 5 and 6, 2026-10-23). Three tests that this plan supplied verbatim are weak (Task 5: `assertLess(ended_at, deadline)` cannot fail under the mocked clock; Task 6: the no-state check reads the wrong table, and no end-to-end case shows a refused skip running its child sequence and keeping its gaps, spec §5 item 4 and P8). The owner chose "Strengthen all (Recommended)": replace or drop the vacuous assertions, check the binding row, and add the end-to-end refusal case. Production code stays as written. Applied in: Tasks 5 and 6.
- **R2** (owner, review of Task 7, 2026-10-23). `test_release_upgrade.ReleaseUpgradeTests.test_installed_b_workflow_continues_a_origin_pending_and_repairs` fails in about 60% of runs on this branch, and Task 7's first test can pass without the origin release running a child. Cause (investigation, `flaky-release-upgrade-report.md`): `select_work` orders members by `(period, source_id, member_id)`, and `member_id` hashes a workset that holds the wall-clock `started_at` and `deadline`. So which of two same-source members runs first flips between runs. The B4 skip completes the second one without a child, so no child runs under release A whenever the current-release member sorts first. The skip follows B4. The tests assumed an order B4 no longer guarantees. The owner chose "Pin order, fall back (Recommended)": fix the clock and deadline inputs so the A-origin member always sorts first and still runs a child under A (keeps the full proof). If that is not feasible, use order-aware checks (A-first requires an A child, B-first requires the no-child receipt). Tests only, no production change. Applied in: Task 7, and the existing `workflow_proof.py` and `test_release_upgrade.py`.
  - The owner does not accept the limit. A new per-member-cost roadmap stage goes before Stage 2. This plan does not plan or place that stage. The session that owns the roadmap does (derive-roadmap).
  - Stage 1a continues.
  - The live reserve is provisional. Its integer is set at the Task 10 owner approval (D4), where it must satisfy floor ≤ reserve < 3,300.

## Defaults for owner review

Planning found three places where the code and the approved spec disagree, and settled the rest of the open choices. Each item below is applied in the tasks as written. The owner approves or changes each one at plan review. Spec-level items have exact amendment text in Task 1.

- **P1 — Widen B4 to the selection's `already_complete` (spec-level, amendment A1).** The trace in F-P2 below shows that a cutoff between the two members of a pair leaves the second member with no binding. In the next run, the new discovery member of that source lands in `already_complete`, not in the loop. So "the immediately preceding member" never fires for the deferred member, and it reruns `collect`, `transform` and `publish`. Spec §5 item 3 then fails for every source whose pair straddles a cutoff. Default: B4's first condition also holds when the frozen selection's `already_complete` holds a capture of the same `source_id`. Alternative: keep B4 as written, and weaken §5 item 3 to "at most once, except a source whose pair straddles a cutoff". Applied in: Tasks 1 and 6.
- **P2 — The B4 receipt names no worksets (spec-level, part of A1).** `transfer_binding` writes only a `Binding`, not a snapshot workset object (`provenance.py:216–227`). A transformed workset embeds its transform child's context. So a B4 receipt cannot name a `snapshot_ref` or `transformed_ref` of its own. Default: `snapshot_ref`, `transformed_ref` and `child_refs` are empty. `workflows/contracts.py` `MemberResult` and `workflows/results.py` `_validate_report` accept that exact shape. They currently require a snapshot, a transformed workset and a `publish` child for every complete member. The acceptance keys on `child_refs == ()` with both refs null. No valid old receipt has that shape, so the change only adds a shape. Applied in: Tasks 1 and 6.
- **P3 — Engine admission before stores open (spec-level, amendment A2).** B2 says each refusal occurs before store or network authority, and names "engine new-context creation" as the engine check. But the engine learns whether a context is new only after `open_stores` and `retain_manifest` (`cli._workflow_main`). Default: the engine check runs in `cli._validate_workflow`, on the invocation's own config only, before any store opens. It never touches a saved or historical config. It refuses the same invocations in practice. Every D5 attempt is admitted with the key, and exact replays of older attempts run on their own releases, because `preflight_current` binds the engine to the config's release. Alternative: the literal "new-context" placement in the `saved is None` branch, after `open_stores`. Applied in: Tasks 1 and 4.
- **P4 — Proposal rule for the floor and the reserve (plan-level).** The measurement script proposes floor = max(60, 3 × finish-step seconds, rounded up to 30 s) and reserve = 2 × slowest member + floor, rounded up to 60 s. It also checks that the slowest member fits in 3,300 − reserve. The owner sets the committed values at the Task 2 checkpoint. Applied in: Task 2.
- **P5 — Measurement design (plan-level).** Fixture acquisition with `sec-index-parser-v1` (`supported_parser` allows it), native runtime on the `fc68adef…` release, and the release's own workflow engine run in-process with native child processes. Synthetic quarterly bodies have the counted row count of the retained 2024Q1 body. Synthetic daily bodies have the larger counted row count of the two retained L12 daily bodies. Three scenarios:
  - `open`: 81 daily sources in 2026Q4.
  - `closed`: a quarterly baseline for 2021Q1–2026Q3, in which the 14 quarters that the retained 2026-10-15 daily file back-dates into (findings §4.7) are full size. Then two daily sources. One back-dates one row into one closed quarter (the spec's measure 1). The other back-dates one row into each of the 14 quarters, which is the real fan-out.
  - `finish`: a backfill over 2015Q1–2026Q4, 48 quarters.

  Applied in: Task 2.
- **P6 — Origin release for the two-release tests (plan-level).** `proof_releases` builds both A and B from the current snapshot, so after this change both carry D5 code. Default: a new `origin_release` helper builds revision `3ca50c7` (the `fc68adef…` source revision) into its own committed repository and installs it. It is hermetic. Its release ID differs from `fc68adef…`, because identity covers the Git revision. Task 7 records whether its package files, dependencies and lock equal the retained `fc68adef…` manifest's. Alternative: use the retained `releases/sha256=fc68adef…` through `SEC_LOCAL_PROOF_CATALOG`, which makes the default gate depend on a git-ignored local directory. Applied in: Task 7.
- **P7 — Merge before the build (plan-level).** B7 requires a build from clean committed `main`. Default: after the full gate and the whole-branch review (Task 8), the owner approves a merge of `stage1a-bounded-drain` to `main`. The release build, evidence, config selection and amendments then land on `main` (Tasks 9–11). Applied in: Tasks 8–11.
- **P8 — Gaps found while deciding a skip (plan-level).** When the skip check's `reuse_exact_binding` call reports a gap, the skip is refused and the member runs its ordinary child sequence. The check's own gap is not added to the run result. Today's path never makes that call for the member, so the result loses no gap that today's run reports (spec §4.3 item 2). Applied in: Task 6.

## Facts established while planning (read-only, 2026-10-22)

- **F-P1 — Package source equals `fc68adef…`.** `git diff 3ca50c7 HEAD -- packages/sec-edgar-ingest/src` is empty. So on `main` before this plan, the checkout's package behaves as `fc68adef…`. `uv.lock` and both `pyproject.toml` files have no diff since `3ca50c7`.
- **F-P2 — The straddling pair (basis of P1).** In run k, the cutoff falls after member S₁ of source S completes and before its sibling S₂. Run k+1 selects S₂ again from the retained pending members (`runner.select_work`, `pending_before`), still with no binding. The new discovery member S₃ gets S₁'s pin through `reuse_exact_binding` at selection, evaluates complete, and goes to `already_complete`. So no same-source member precedes S₂ in run k+1's loop.
- **F-P3 — Three validators reject a no-child complete member (basis of P2).**
  - `MemberResult.__post_init__` requires `snapshot_ref` and `transformed_ref` for `COMPLETE` (`workflows/contracts.py:108–112`).
  - `validate_member_evidence` refuses a receipt with no calls ("member has no checked source operation", `processing.py:197–198`).
  - `_validate_report` requires a `publish` child for a complete member (`results.py`, member loop).
  - No existing test asserts those three messages.
- **F-P4 — Admission placement (basis of P3).** `cli._workflow_main` calls `open_stores` and `retain_manifest` before `_workflow_saved`, so "new context" is known only after the store opens. `members._validate_context` and `cli._matching_context` call `pin_context` on saved contexts, so admission must never move into `pin_context` or `Settings`.
- **F-P5 — Config hashes.** Current code reproduces `088403cb…` from `conf/sec-edgar-local.json` and `32b4da63…` from the L12 effective config (backfill `2024Q1`–`2024Q1`). `load_config` resolves `../data` against the checkout path, so a worktree gives a different hash. Task 3's test embeds the normalized live mapping instead.
- **F-P6 — Test count.** `main` loads 999 tests in 62 modules (loader count, not run). The spec's "952 tests in 60 modules" is the retained `fc68adef…` acceptance count. `test_acceptance_selection` and `test_baseline_campaign` were added since. The port's full gate took 3,338.8 s, so run the gate in the background.
- **F-P7 — Keyless live configs in tests.** `test_local_launcher.py` builds two live configs without the key (`setUp` near lines 48 and 388) and prepares invocations from them. B2 refuses those, so Task 4 adds the key there.
- **F-P9 — Fixture checks behind Tasks 6 and 7.**
  - Quarterly-mode discovery maps a pending quarterly source to the `full-index` family (`discovery._inventory`, `:148–151`). So the Task 6 drain over `quarter_pack` stays quarterly-only. `test_workflow_acceptance` already runs `quarter_pack` through 2026Q4 with today 2026-10-07.
  - A 403 records a `RunHalt` keyed by run ID only (`state.py:520`; "stops every subsequent request in this run"). So Task 7's origin halt does not block the next run.
  - The retained 2026-10-15 daily file back-dates rows into 14 closed quarters (findings §4.7). That is the basis of the Task 2 fan-out scenario.
- **F-P8 — Worktree visibility.** `.claude/worktrees/` is excluded through `.git/info/exclude`, so `build_release`'s clean-tree check (`git status --porcelain --untracked-files=all`) does not see it.

---

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `specs/sec-filing-index-bounded-drain.md` | Stage 1a spec; amendments A1, A2 | 1 |
| `scripts/measure-d5-drain.py` (new) | Offline measurement under an installed release | 2 |
| `specs/evidence/d5-release/` (new) | Measurement, two-release and release evidence | 2, 7, 9, 10 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/config.py` | B1 field, floor constant, `admit_dispatch_reserve` | 3 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/local_cli.py` | B2 launcher admission | 4 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/cli.py` | B2 engine admission | 4 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py` | B3 cutoff; B4 `sibling_completion` | 5, 6 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py` | B5 receipt validation | 6 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/contracts.py` | `MemberResult` accepts the B4 shape | 6 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/results.py` | `_validate_report` accepts a B4 member | 6 |
| `packages/sec-edgar-ingest/tests/test_config.py` | B1/B2 config tests | 3 |
| `packages/sec-edgar-ingest/tests/test_local_launcher.py` | Launcher admission tests | 4 |
| `packages/sec-edgar-ingest/tests/test_workflow_cli.py` | Engine admission test | 4 |
| `packages/sec-edgar-ingest/tests/test_workflow_drain.py` (new) | Cutoff, drain, skip safety, receipt shape, replay | 5, 6 |
| `packages/sec-edgar-ingest/tests/support_release.py` | `origin_release` helper | 7 |
| `packages/sec-edgar-ingest/tests/test_release_origin.py` (new) | Two-release tests (§5 item 6) | 7 |
| `conf/sec-edgar-local.json` | Reserve key and D5 selection (B8) | 10 |
| `specs/sec-filing-index-ingestion-spec.md` | §§4.7–4.9 amendments | 11 |

---

### Task 1: Stage 1a spec amendments A1 and A2 (owner-approved at plan review)

Apply only the amendments the owner approved at plan review (D1). If the owner rejected A1 or A2, skip its blocks and record `> Skipped:` under this task.

**Files:**
- Modify: `specs/sec-filing-index-bounded-drain.md` (§3 rows B2 and B4; §4.1 table)

**Interfaces:**
- Consumes: the owner's plan-review decision D1.
- Produces: spec text that Tasks 4 and 6 implement.

- [ ] **Step 1: Apply A1 to row B4.** Replace:

```text
the runner skips it when all of these are true: the immediately preceding member in the loop has the same `source_id` and an outcome in `workflows/contracts.py` `COMPLETE`; `reuse_exact_binding` returns no gaps;
```

with:

```text
the runner skips it when all of these are true: the immediately preceding member in the loop has the same `source_id` and an outcome in `workflows/contracts.py` `COMPLETE`, or the frozen selection's `already_complete` holds a capture of the same `source_id` (owner, plan 4, 2026-10-22); `reuse_exact_binding` returns no gaps;
```

Then replace:

```text
A skipped member records a receipt with its completion capture and no child calls.
```

with:

```text
A skipped member records a receipt with its completion capture and no child calls. Its `snapshot_ref`, `transformed_ref` and `child_refs` are empty, because no child of its own ran (owner, plan 4, 2026-10-22).
```

- [ ] **Step 2: Apply A2 to row B2.** Replace:

```text
The check runs only at admission: launcher `prepare_invocation`, and engine new-context creation for `backfill`, `daily` and `reconcile`.
```

with:

```text
The check runs only at admission: launcher `prepare_invocation`, and the engine's workflow configuration check `cli._validate_workflow` for `backfill`, `daily` and `reconcile`, on the invocation's own config, before any store opens (owner, plan 4, 2026-10-22).
```

- [ ] **Step 3: Apply A1 and A2 to the §4.1 table.** Replace the row:

```text
| `cli.py` new-context creation for workflow commands | B2 admission. |
```

with:

```text
| `cli.py` `_validate_workflow` for workflow commands | B2 admission (owner, plan 4, 2026-10-22). |
```

Then replace the row:

```text
| `workflows/processing.py` `validate_member_evidence` | B5. |
```

with:

```text
| `workflows/processing.py` `validate_member_evidence` | B5. |
| `workflows/contracts.py` `MemberResult` | Accept the B4 receipt shape (owner, plan 4, 2026-10-22). |
| `workflows/results.py` `_validate_report` | Accept a B4 member, whose receipt capture stands in for a `publish` child (owner, plan 4, 2026-10-22). |
```

If the owner approved on a later date than 2026-10-22, use D1's date in every tag.

- [ ] **Step 4: Verify.** Run:

```bash
grep -c "owner, plan 4" specs/sec-filing-index-bounded-drain.md
```

Expected: `6` with both amendments applied. The spec's status line is unchanged.

> Deviation: `grep -c` counts lines, and two tags share the B4 row, so it prints `5`. `grep -o "owner, plan 4" specs/sec-filing-index-bounded-drain.md | wc -l` prints `6`. All six tags are present (Task 1 review, 2026-10-22).

- [ ] **Step 5: Commit.**

```bash
git add specs/sec-filing-index-bounded-drain.md
git commit -m "docs(specs): amend Stage 1a's skip and admission rules at plan review"
```

---

### Task 2: Offline measurement and the owner decision point (spec §6)

This task runs the installed `fc68adef…` release offline. It never opens `data/` except through `count`, which uses operator access and the release's validated readers. It ends at a hard owner checkpoint. Tasks 3–11 wait for D2.

**Files:**
- Create: `scripts/measure-d5-drain.py`
- Create: `specs/evidence/d5-release/counts.json`, `specs/evidence/d5-release/measurement.json`, `specs/evidence/d5-release/measurement.md`

**Interfaces:**
- Consumes: `releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/` (installed), `conf/sec-edgar-local.json` (main checkout), `specs/evidence/local-port/sec-acceptance.json`.
- Produces: D2, the owner-approved floor (an integer number of seconds) and live reserve (an integer number of seconds). Task 3 commits the floor as `DISPATCH_RESERVE_FLOOR_SECONDS`. Task 10 commits the reserve as `execution.dispatch_reserve_seconds`.

- [ ] **Step 1: Confirm that no writer is running.**

```bash
pgrep -fl -- '-m sec_edgar_ingest|scripts/sec-edgar-local|local-bootstrap|local_bootstrap' || echo none
```

Expected: `none`. If a process is listed, stop and ask the owner.

- [ ] **Step 2: Write the measurement script.** Create `scripts/measure-d5-drain.py`:

```python
"""Offline drain measurement for Stage 1a (bounded-drain spec §6).

Run with the installed release interpreter and -I -B -X pycache_prefix=/dev/null.
`count` opens the live store with operator access only, and counts the rows of retained bodies.
`run` builds fixture packs and fresh stores under --work, and drives the release's own workflow engine
in this process with native child processes. Fixture acquisition sends no request.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

FORMAT = 'sec-d5-drain-measurement-v1'
BASE = 'https://www.sec.gov/Archives/edgar/'
TODAY = date(2026, 12, 31)
MAX_RUN_SECONDS = 21600
OPEN_MARKS = (1, 10, 40, 80)
FINISH_LABELS = ('baseline_gaps', 'source_revert_gaps', 'summarize', 'write_workflow_result', 'emit_summary')
# closed_quarters: the 14 closed quarters that the retained 2026-10-15 daily file back-dates into (findings §4.7).
SCALES = {
    'smoke': {'open_days': 3, 'finish_start': '2026Q1', 'finish_rows': 20, 'closed_start': '2025Q1',
              'closed_quarters': ('2025Q1', '2025Q2')},
    'full': {'open_days': 81, 'finish_start': '2015Q1', 'finish_rows': 50, 'closed_start': '2021Q1',
             'closed_quarters': ('2021Q1', '2021Q2', '2021Q3', '2021Q4', '2022Q1', '2022Q2', '2023Q3',
                                 '2024Q4', '2025Q1', '2025Q2', '2025Q3', '2025Q4', '2026Q1', '2026Q3')},
}
TIMINGS: list[dict] = []
MEMBERS: list[dict] = []


def count_rows(body: bytes, kind: str) -> int:
    if kind == 'quarterly':
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            body = archive.read('master.idx')
    lines = body.decode('ascii').splitlines()
    start = next(index for index, line in enumerate(lines) if line and set(line) == {'-'}) + 1
    return sum(1 for line in lines[start:] if line.strip())


def count(config: Path, evidence: Path) -> dict:
    from sec_edgar_ingest.config import load_config
    from sec_edgar_ingest.state import AcquisitionState
    from sec_edgar_ingest.storage import open_stores
    selected = json.loads(evidence.read_text())['selected_sources']
    opened = open_stores(load_config(config.resolve()), access='operator')
    try:
        acquisition, objects, found = AcquisitionState(opened[0]), opened[1], {}
        for source in selected:
            snapshot = acquisition.snapshot(source['source_id'], source['snapshot']['sha256'])
            objects.verify(snapshot.raw_path, snapshot.sha256, snapshot.byte_count)
            found[source['period']] = {'kind': source['kind'], 'sha256': snapshot.sha256,
                                       'bytes': snapshot.byte_count,
                                       'rows': count_rows(objects.read(snapshot.raw_path), source['kind'])}
        return {'format_version': FORMAT, 'kind': 'count', 'sources': found}
    finally:
        for resource in reversed(opened):
            if resource is not None and hasattr(resource, 'close'):
                resource.close()


def row(kind: str, cik: int, serial: int, filed: date) -> str:
    text = filed.isoformat() if kind == 'quarterly' else filed.strftime('%Y%m%d')
    accession = f'{cik:010d}-{filed.year % 100:02d}-{serial:06d}'
    return f'{cik}|Company {cik}|10-K|{text}|edgar/data/{cik}/{accession}.txt'


def body(kind: str, rows: list[str]) -> bytes:
    ending, title = ('\r\n', 'Filename') if kind == 'quarterly' else ('\n', 'File Name')
    text = ('Description:           Master Index of EDGAR Dissemination Feed' + ending
            + 'Last Data Received:    synthetic' + ending + ending
            + 'CIK|Company Name|Form Type|Date Filed|' + title + ending + '-' * 80 + ending
            + ending.join(rows) + ending)
    raw = text.encode('ascii')
    if kind == 'daily':
        return raw
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        info = zipfile.ZipInfo('master.idx', (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, raw)
    return output.getvalue()


def listing(url: str, children: list[tuple[str, str]]) -> bytes:
    from sec_edgar_ingest.models import canonical_json, to_mapping_value
    return canonical_json(to_mapping_value({'directory': {
        'name': url[len(BASE):-len('index.json')], 'parent-dir': '../',
        'item': [{'name': name, 'href': name + ('/' if kind == 'dir' else ''), 'type': kind,
                  'size': '1', 'last-modified': 'synthetic'} for name, kind in children]}}))


def build_pack(root: Path, leaves: dict, repeats: int = 4) -> Path:
    """leaves: {(family, year, quarter): [(filename, body), ...]}, every listed leaf directory."""
    from sec_edgar_ingest.models import canonical_json, to_mapping_value
    (root / 'bodies').mkdir(parents=True)
    documents = {}
    for family in ('full-index', 'daily-index'):
        base = BASE + family + '/'
        keys = sorted(key for key in leaves if key[0] == family)
        years = sorted({year for _, year, _ in keys})
        documents[base + 'index.json'] = listing(base + 'index.json', [(str(year), 'dir') for year in years])
        for year in years:
            url = base + f'{year}/index.json'
            documents[url] = listing(url, [(f'QTR{quarter}', 'dir') for _, y, quarter in keys if y == year])
        for _, year, quarter in keys:
            url = base + f'{year}/QTR{quarter}/index.json'
            files = leaves[family, year, quarter]
            documents[url] = listing(url, [(name, 'file') for name, _ in files])
            for name, payload in files:
                documents[base + f'{year}/QTR{quarter}/{name}'] = payload
    responses = {}
    for url, payload in sorted(documents.items()):
        digest = hashlib.sha256(payload).hexdigest()
        target = root / 'bodies' / (digest + '.body')
        if not target.exists():
            target.write_bytes(payload)
        spec = {'status': 200, 'headers': {'Content-Length': str(len(payload)), 'X-Fixture': 'synthetic'},
                'body_path': 'bodies/' + digest + '.body', 'body_sha256': digest}
        responses[url] = [dict(spec) for _ in range(repeats)]
    path = root / 'manifest.json'
    path.write_bytes(canonical_json(to_mapping_value({'fixture_version': 'sec-acquisition-fixture-v1',
                                                      'provenance': 'synthetic', 'responses': responses})))
    return path


def write_config(path: Path, root: Path, manifest: Path, *, start: str, end: str, daily_start: str) -> Path:
    from sec_edgar_ingest.config import HTTP_POLICY, Settings
    from sec_edgar_ingest.models import canonical_json, to_mapping_value
    value = {
        'config_version': 'sec-local-config-v1',
        'backfill': {'start_quarter': start, 'end_quarter': end},
        'daily': {'start_date': daily_start},
        'sec': {'user_agent': 'Lowell Mason sec-edgar-ingest mason.lowell@mac.com',
                'requests_per_second': 3, 'max_active_collectors': 1},
        'http': dict(HTTP_POLICY),
        'coordination': {'lease_seconds': 60, 'renew_every_seconds': 20,
                         'namespace': 'sec-owner-lowell-mason', 'clock_uncertainty_seconds': 2},
        'storage': {'backend': 'local', 'root': str(root / 'store')},
        'acquisition': {'mode': 'fixture'},
        'runtime': {'kind': 'native', 'release_manifest': str(manifest)},
        'logging': {'root': str(root / 'logs')},
        'execution': {'max_run_seconds': MAX_RUN_SECONDS},
        'etl': {'parser_version': 'sec-index-parser-v1', 'schema_version': 'sec-index-v1'},
        'reconciliation': {'require_withdrawal_approval': True},
        'fixture': {'allow_clock_override': True, 'allow_deadline_override': False},
    }
    Settings.from_mapping(value)  # Refuse an invalid config before any store exists.
    path.write_bytes(canonical_json(to_mapping_value(value)))
    return path


def instrument() -> None:
    """Time the release's own engine steps in this process; children stay native processes."""
    from sec_edgar_ingest import cli
    from sec_edgar_ingest.workflows import checked, runner

    def timed(owner, name):
        original = getattr(owner, name)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                return original(*args, **kwargs)
            finally:
                TIMINGS.append({'label': name, 'seconds': time.monotonic() - start})
        setattr(owner, name, wrapper)

    for name in ('select_work', 'baseline_gaps', 'source_revert_gaps', 'summarize'):
        timed(runner, name)
    for name in ('write_workflow_result', 'emit_summary'):
        timed(cli, name)
    execute = checked.Dispatcher.execute
    def timed_execute(self, command, step_id, settings, flags):
        start = time.monotonic()
        try:
            return execute(self, command, step_id, settings, flags)
        finally:
            TIMINGS.append({'label': 'child', 'command': command, 'step_id': step_id,
                            'seconds': time.monotonic() - start})
    checked.Dispatcher.execute = timed_execute
    process = runner.process_member
    def timed_member(value, *args, **kwargs):
        start = time.monotonic()
        processed = process(value, *args, **kwargs)
        MEMBERS.append({'member_id': value['member_id'], 'kind': value['source']['kind'],
                        'period': value['source']['period'], 'seconds': time.monotonic() - start,
                        'outcome': processed.result.outcome,
                        'quarters': [{'quarter': q.quarter, 'outcome': q.outcome} for q in processed.result.quarters]})
        return processed
    runner.process_member = timed_member


def invoke(config: Path, command: str, run_id: str, pack: Path) -> dict:
    from sec_edgar_ingest.cli import main
    deadline = datetime.now(timezone.utc) + timedelta(seconds=MAX_RUN_SECONDS - 600)
    argv = [command, '--config', str(config), '--run-id', run_id, '--execution-id', 'measure',
            '--attempt-id', 'a', '--deadline', deadline.isoformat(), '--today', TODAY.isoformat(),
            '--fixture-pack', str(pack)]
    out, err = io.StringIO(), io.StringIO()
    start = time.monotonic()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    seconds = time.monotonic() - start
    (config.parent / (run_id + '.stderr.jsonl')).write_text(err.getvalue())
    message = json.loads(out.getvalue().splitlines()[-1])
    return {'command': command, 'run_id': run_id, 'exit': code, 'outcome': message['outcome'],
            'result_ref': message['result_ref'], 'seconds': seconds}


def scenario(name: str, work: Path, manifest: Path, leaves: dict, steps: list) -> dict:
    root = work / name
    root.mkdir(parents=True)
    pack = build_pack(root / 'pack', leaves)
    invocations = []
    for index, (command, ranges) in enumerate(steps):
        config = write_config(root / f'config-{index}.json', root, manifest, **ranges)
        first_timing, first_member = len(TIMINGS), len(MEMBERS)
        call = invoke(config, command, f'measure-{name}-{index}', pack)
        timings = TIMINGS[first_timing:]
        members = MEMBERS[first_member:]
        for member in members:
            member['children'] = {t['command']: t['seconds'] for t in timings
                                  if t['label'] == 'child' and t['step_id'].endswith('-' + member['member_id'])}
        call.update(timings=timings, members=members)
        invocations.append(call)
    return {'invocations': invocations}


def quarters(start: str, end: str) -> list[tuple[int, int]]:
    year, quarter = int(start[:4]), int(start[-1])
    stop = (int(end[:4]), int(end[-1]))
    found = []
    while (year, quarter) <= stop:
        found.append((year, quarter))
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return found


def run(manifest: Path, work: Path, counts: dict, scale: str) -> dict:
    sizes = SCALES[scale]
    sources = counts['sources']
    quarterly_rows = sources['2024Q1']['rows'] if scale == 'full' else 1000
    daily_rows = max(v['rows'] for v in sources.values() if v['kind'] == 'daily') if scale == 'full' else 20
    instrument()
    report = {'format_version': FORMAT, 'kind': 'run', 'scale': scale, 'python': sys.executable,
              'flags': {'isolated': sys.flags.isolated, 'dont_write_bytecode': sys.dont_write_bytecode,
                        'pycache_prefix': sys.pycache_prefix},
              'release_id': json.loads(manifest.read_text())['release_id'],
              'inputs': {'quarterly_rows': quarterly_rows, 'daily_rows': daily_rows, **sizes},
              'started_at': datetime.now(timezone.utc).isoformat(), 'scenarios': {}}
    days = [date(2026, 10, 1) + timedelta(days=index) for index in range(sizes['open_days'])]
    open_leaves = {('full-index', 2026, 4): [], ('daily-index', 2026, 4): [
        (f'master.{day:%Y%m%d}.idx', body('daily', [row('daily', 300000 + index, serial, day)
                                                     for serial in range(daily_rows)]))
        for index, day in enumerate(days)]}
    report['scenarios']['open'] = scenario('open', work, manifest, open_leaves,
        [('daily', {'start': '2026Q4', 'end': 'open', 'daily_start': '2026-10-01'})])
    # Closed baseline: every quarter from closed_start to 2026Q3 has a quarterly source; the back-dated
    # quarters are full size. Then two daily files: one back-dates one row into one closed quarter (the
    # spec's measure 1), the other one row into each back-dated quarter (the fan-out of findings §4.7).
    heavy = sizes['closed_quarters']
    closed_leaves = {('full-index', 2026, 4): [], ('daily-index', 2026, 4): []}
    for index, (year, quarter) in enumerate(quarters(sizes['closed_start'], '2026Q3')):
        size = quarterly_rows if f'{year}Q{quarter}' in heavy else sizes['finish_rows']
        first = date(year, (quarter - 1) * 3 + 1, 2)
        closed_leaves['full-index', year, quarter] = [('master.zip', body('quarterly', [
            row('quarterly', 100000 + index * 50000 + serial % 40000, serial, first) for serial in range(size)]))]
        closed_leaves['daily-index', year, quarter] = []
    def back_date(label: str) -> date:
        return date(int(label[:4]), (int(label[-1]) - 1) * 3 + 1, 12)
    single = [row('daily', 310000, serial, date(2026, 12, 1)) for serial in range(daily_rows)]
    single.append(row('daily', 900001, 1, back_date(heavy[0])))
    fanout = [row('daily', 320000, serial, date(2026, 12, 2)) for serial in range(daily_rows)]
    fanout.extend(row('daily', 900100 + index, 1, back_date(label)) for index, label in enumerate(heavy))
    closed_leaves['daily-index', 2026, 4] = [('master.20261201.idx', body('daily', single)),
                                             ('master.20261202.idx', body('daily', fanout))]
    report['scenarios']['closed'] = scenario('closed', work, manifest, closed_leaves, [
        ('backfill', {'start': sizes['closed_start'], 'end': '2026Q3', 'daily_start': '2026-12-01'}),
        ('daily', {'start': sizes['closed_start'], 'end': 'open', 'daily_start': '2026-12-01'})])
    finish_leaves = {}
    for index, (year, quarter) in enumerate(quarters(sizes['finish_start'], '2026Q4')):
        first = date(year, (quarter - 1) * 3 + 1, 1)
        finish_leaves['full-index', year, quarter] = [('master.zip', body('quarterly', [
            row('quarterly', 400000 + serial, index * 1000 + serial, first) for serial in range(sizes['finish_rows'])]))]
        finish_leaves['daily-index', year, quarter] = []
    report['scenarios']['finish'] = scenario('finish', work, manifest, finish_leaves,
        [('backfill', {'start': sizes['finish_start'], 'end': 'open', 'daily_start': '2026-12-31'})])
    report['ended_at'] = datetime.now(timezone.utc).isoformat()
    report['measures'] = measures(report)
    report['proposal'] = proposal(report['measures'])
    return report


def measures(report: dict) -> dict:
    scenarios = report['scenarios']
    open_members = scenarios['open']['invocations'][0]['members']
    single, fanout = scenarios['closed']['invocations'][1]['members']
    finish = scenarios['finish']['invocations'][0]
    every = [member for value in scenarios.values() for call in value['invocations'] for member in call['members']]
    slowest = max(every, key=lambda member: member['seconds'])
    return {'open_publish_seconds': {str(k): open_members[k]['children'].get('publish')
                                     for k in OPEN_MARKS if k < len(open_members)},
            'closed_rebuild_publish_seconds': single['children'].get('publish'),
            'closed_rebuild_quarters': single['quarters'],
            'closed_fanout_publish_seconds': fanout['children'].get('publish'),
            'closed_fanout_quarters': fanout['quarters'],
            'finish_seconds': sum(t['seconds'] for t in finish['timings'] if t['label'] in FINISH_LABELS),
            'finish_members': len(finish['members']),
            'slowest_member': {key: slowest[key] for key in ('kind', 'period', 'seconds', 'children', 'outcome')},
            'exits': {name: [call['exit'] for call in value['invocations']] for name, value in scenarios.items()}}


def proposal(values: dict) -> dict:
    """Plan 4 default P4. The owner sets the committed values (D2)."""
    floor = max(60, math.ceil(3 * values['finish_seconds'] / 30) * 30)
    slowest = values['slowest_member']['seconds']
    reserve = math.ceil((2 * slowest + floor) / 60) * 60
    return {'floor_seconds': floor, 'reserve_seconds': reserve,
            'slowest_fits_default_timeout': slowest <= 3300 - reserve}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='measure-d5-drain')
    commands = parser.add_subparsers(dest='command', required=True)
    counting = commands.add_parser('count')
    counting.add_argument('--config', type=Path, required=True)
    counting.add_argument('--evidence', type=Path, required=True)
    running = commands.add_parser('run')
    running.add_argument('--release-manifest', type=Path, required=True)
    running.add_argument('--work', type=Path, required=True)
    running.add_argument('--counts', type=Path, required=True)
    running.add_argument('--scale', choices=sorted(SCALES), required=True)
    args = parser.parse_args(argv)
    if args.command == 'count':
        sys.stdout.write(json.dumps(count(args.config, args.evidence), sort_keys=True, indent=1) + '\n')
        return 0
    work = args.work.resolve()
    if work.is_relative_to('/tmp') or work.is_relative_to('/private/tmp'):
        raise SystemExit('measurement work must be under the project, not /tmp')
    work.mkdir(parents=True, exist_ok=False)
    report = run(args.release_manifest.resolve(), work, json.loads(args.counts.read_text()), args.scale)
    (work / 'measurement.json').write_text(json.dumps(report, sort_keys=True, indent=1) + '\n')
    sys.stdout.write(json.dumps({'measures': report['measures'], 'proposal': report['proposal']},
                                sort_keys=True, indent=1) + '\n')
    return 0 if all(code == 0 for codes in report['measures']['exits'].values() for code in codes) else 1


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 3: Count the retained bodies.** From the worktree root:

```bash
mkdir -p specs/evidence/d5-release
REL=/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec
"$REL/venv/bin/python" -I -B -X pycache_prefix=/dev/null scripts/measure-d5-drain.py count --config /Users/lowell/Projects/sec-edgar-local/conf/sec-edgar-local.json --evidence specs/evidence/local-port/sec-acceptance.json > specs/evidence/d5-release/counts.json
cat specs/evidence/d5-release/counts.json
```

Expected: `2024Q1` has `"bytes": 4262821` and `"rows": 370321`, which matches findings §5.1. `2026-10-14` and `2026-10-15` are `daily`, each with a row count. Use the absolute config path. The worktree's `conf/` resolves `../data` inside the worktree, where operator access refuses to create a store.

- [ ] **Step 4: Smoke run.**

```bash
REL=/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec
"$REL/venv/bin/python" -I -B -X pycache_prefix=/dev/null scripts/measure-d5-drain.py run --release-manifest "$REL/release.json" --work /Users/lowell/Projects/sec-edgar-local/fixture-data/d5-measure-smoke-$(date -u +%Y%m%dT%H%M%SZ) --counts specs/evidence/d5-release/counts.json --scale smoke
```

Expected: exit 0. Every value in `measures.exits` is `0`. If an invocation fails because of the fixture tree (discovery listing, parser format), read that run's `.stderr.jsonl` in the work directory, fix the script, and repeat. Record each fix as `> Deviation:` under this step. Do not weaken a validation in the release.

> Deviation: `run()` in `scripts/measure-d5-drain.py` lists an empty `daily-index/2026/QTR3` leaf in the `open` pack. Daily discovery also requires the quarter before the open quarter (`required_daily_quarters`). Without the leaf the first smoke run ended `incomplete` (exit 3, `missing_directory`). No release validation was changed. Smoke run: exit 0, wall 6 min 48 s.

> Deviation: the worktree command guard refuses any command that names the `sha256=…` release path. The owner launched the Step 5 command in their own terminal instead (2026-10-22 20:09 UTC).

- [ ] **Step 5: Full run, in the background.** Start it with `run_in_background`. It can take several hours: 81 open-quarter members, 14 full-size closed quarterly baselines, two back-dating daily members and 48 backfill members, all with native children.

```bash
REL=/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec
WORK=/Users/lowell/Projects/sec-edgar-local/fixture-data/d5-measure-full-$(date -u +%Y%m%dT%H%M%SZ)
echo "$WORK"
"$REL/venv/bin/python" -I -B -X pycache_prefix=/dev/null scripts/measure-d5-drain.py run --release-manifest "$REL/release.json" --work "$WORK" --counts specs/evidence/d5-release/counts.json --scale full
```

Expected: exit 0, then a JSON summary with `measures` and `proposal`.

> Deviation: the full run failed and wrote no `measurement.json`. The `open` run (81 daily sources) reached its hard deadline after 24 completed members, and the `closed` baseline reached it after 2 of 23 members. Both ended `state_conflict` ("child shutdown/drain was not confirmed"). The `finish` scenario and the back-dated daily steps never ran. The in-process timers were lost. At the owner's instruction (2026-10-23), the timings were rebuilt from the durable `Attempts` records in the two stores with a new `rebuild` subcommand of `scripts/measure-d5-drain.py` (stdlib only, read-only). `measurement.json` is that rebuilt output (`kind: rebuilt-from-store`). `measurement.md` states what is missing. The P4 proposal cannot be computed.

- [ ] **Step 6: Write the evidence.** Copy `$WORK/measurement.json` to `specs/evidence/d5-release/measurement.json`. Write `specs/evidence/d5-release/measurement.md` with these sections, filled from the JSON:

```markdown
# D5 drain measurement (Stage 1a, plan 4 Task 2)

**Date:** <UTC date of the full run>. **Release:** `fc68adef…` installed interpreter, `-I -B -X pycache_prefix=/dev/null`.
**Work directory:** `<WORK>` (git-ignored, under the project). No SEC request was sent.

## Inputs
Counted bodies (counts.json): 2024Q1 quarterly, <rows> rows, 4,262,821 bytes; daily <period> and <period>, <rows> rows each.
Synthetic bodies: quarterly <quarterly_rows> rows; daily <daily_rows> rows; fixture acquisition, parser `sec-index-parser-v1`.

## Results
| Measure | Seconds |
|---|---|
| Closed-quarter rebuild by one back-dated daily row (publish child) | … |
| Fan-out: one daily file back-dating into 14 closed quarters (publish child) | … |
| Open-quarter publish, 1 / 10 / 40 / 80 sources already in the quarter | … / … / … / … |
| Finish step, 48 requested quarters (baseline_gaps, source_revert_gaps, summarize, write, summary) | … |
| Slowest member (kind, period, total) | … |

## Proposal (plan 4 default P4)
Floor <floor_seconds> s. Reserve <reserve_seconds> s. Slowest member fits in 3,300 − reserve: <true|false>.

## Limits
Fixture timings can only underestimate native cost (plan 2 F11). Synthetic bodies are not SEC bodies, and the L12 publish spread (41.6–187.6 s) is unexplained. The fan-out uses the 14 quarters of one retained daily file (findings §4.7). A daily file that back-dates into more quarters, or into larger ones, costs more than any measured member.

## Owner decision
To be completed at the Task 2 checkpoint with the owner's exact words.
```

- [ ] **Step 7: Commit the script and the evidence.**

```bash
git add scripts/measure-d5-drain.py specs/evidence/d5-release/counts.json specs/evidence/d5-release/measurement.json specs/evidence/d5-release/measurement.md
git commit -m "test(evidence): measure the drain costs on release fc68adef offline"
```

- [ ] **Step 8: Owner checkpoint (HUMAN).** Show the owner `measurement.md`. Ask for:

1. the floor, as an integer number of seconds;
2. the live reserve, as an integer number of seconds, with floor ≤ reserve < 3,600 and reserve < 3,300 (the launcher default timeout);
3. if the slowest member does not fit in 3,300 − reserve, either acceptance of that limit for Stages 2–3, or a new roadmap stage for cheaper publication.

Stop until the owner answers. Record the answer verbatim under `## Owner decision`. Log it in this plan's `## Decisions` as D2, with both integers.

> Deviation (D2): Step 8b is added. The owner asked to measure the finish step alone before the floor is set. `scripts/measure-d5-drain.py run --scale full --only finish` runs only the `finish` scenario (48 quarters of 50 rows) and reports `finish_seconds` with a per-label split. The owner launches it in their own terminal, because the worktree command guard refuses commands that name the release path. Record the result in `measurement.md`, then the floor integer under D2, and use it in Task 3 Step 4. Limit to state: the finish scenario has small quarters (50 rows each), so the finish step on a store with full-size quarters can cost more (the baseline run's engine gaps grew with the store).

- [ ] **Step 9: Commit the decision.**

```bash
git add specs/evidence/d5-release/measurement.md specs/plans/4-sec-filing-index-bounded-drain.md
git commit -m "docs(evidence): record the owner's floor and reserve decision"
```

---

### Task 3: The optional reserve key and the admission check (B1, B2 config part)

**Files:**
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/config.py` (`ExecutionSettings` at :106–108; `Settings.__post_init__`, `from_mapping`, `to_mapping` at :145–184; new function after `_validate_live_policy`)
- Test: `packages/sec-edgar-ingest/tests/test_config.py`

**Interfaces:**
- Consumes: D2's floor.
- Produces:
  - `ExecutionSettings.dispatch_reserve_seconds: int | None` (default `None`).
  - `DISPATCH_RESERVE_FLOOR_SECONDS: int` in `sec_edgar_ingest.config`.
  - `admit_dispatch_reserve(settings: Settings) -> int | None`. For live settings it returns the reserve, or raises `ValueError` with `dispatch_reserve_seconds` in the message. For fixture settings it returns the reserve or `None`.

- [ ] **Step 1: Write the failing tests.** Append to `packages/sec-edgar-ingest/tests/test_config.py`:

```python
import json

PROJECT = Path(__file__).resolve().parents[3]
# conf/sec-edgar-local.json normalized in the main checkout (plan 4 F-P5); embedded so worktrees hash the same.
LIVE_EFFECTIVE = {
    "config_version": "sec-local-config-v1",
    "backfill": {"start_quarter": "2015Q1", "end_quarter": "open"},
    "daily": {"start_date": "2026-10-01"},
    "sec": {"user_agent": "Lowell Mason sec-edgar-ingest mason.lowell@mac.com",
            "requests_per_second": 3.0, "max_active_collectors": 1},
    "http": {"max_attempts": 5, "retry_base_seconds": 2.0, "retry_cap_seconds": 120.0,
             "connect_timeout_seconds": 15.0, "read_timeout_seconds": 60.0,
             "exchange_deadline_seconds": 90.0, "max_received_bytes": 67108864,
             "max_expanded_bytes": 536870912},
    "coordination": {"lease_seconds": 60.0, "renew_every_seconds": 20.0,
                     "namespace": "sec-owner-lowell-mason", "clock_uncertainty_seconds": 2.0},
    "storage": {"backend": "local", "root": "/Users/lowell/Projects/sec-edgar-local/data"},
    "acquisition": {"mode": "live"},
    "runtime": {"kind": "native", "release_manifest": "/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/release.json"},
    "logging": {"root": "/Users/lowell/Projects/sec-edgar-local/logs"},
    "execution": {"max_run_seconds": 3600},
    "etl": {"parser_version": "sec-index-parser-v1", "schema_version": "sec-index-v1"},
    "reconciliation": {"require_withdrawal_approval": True},
}
LIVE_SHA256 = "088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d"
L12_QUARTERLY_SHA256 = "32b4da638464758c2926fc9040e207696a081d452b2af3813ddd36d179441740"


class DispatchReserveConfigTests(unittest.TestCase):
    def live(self, **execution):
        value = copy.deepcopy(LIVE_EFFECTIVE)
        value["execution"].update(execution)
        return value

    def test_absent_key_leaves_every_effective_hash_unchanged(self):
        from sec_edgar_ingest.config import Settings
        settings = Settings.from_mapping(self.live())
        self.assertIsNone(settings.execution.dispatch_reserve_seconds)
        self.assertNotIn("dispatch_reserve_seconds", settings.to_mapping()["execution"])
        self.assertEqual(settings.config_sha256, LIVE_SHA256)
        quarterly = self.live()
        quarterly["backfill"] = {"start_quarter": "2024Q1", "end_quarter": "2024Q1"}
        self.assertEqual(Settings.from_mapping(quarterly).config_sha256, L12_QUARTERLY_SHA256)

    def test_present_key_round_trips_and_changes_the_hash(self):
        from sec_edgar_ingest.config import DISPATCH_RESERVE_FLOOR_SECONDS, Settings
        settings = Settings.from_mapping(self.live(dispatch_reserve_seconds=DISPATCH_RESERVE_FLOOR_SECONDS))
        self.assertEqual(settings.to_mapping()["execution"]["dispatch_reserve_seconds"],
                         DISPATCH_RESERVE_FLOOR_SECONDS)
        self.assertEqual(Settings.from_mapping(settings.to_mapping()), settings)
        self.assertNotEqual(settings.config_sha256, LIVE_SHA256)

    def test_key_is_a_positive_integer_and_never_null(self):
        from sec_edgar_ingest.config import Settings
        for bad in (None, 0, -1, 1.5, True, "600"):
            with self.subTest(value=bad), self.assertRaisesRegex(ValueError, "dispatch_reserve_seconds|invalid type"):
                Settings.from_mapping(self.live(dispatch_reserve_seconds=bad))

    def test_admission_requires_the_key_in_range_for_live_work_only(self):
        from sec_edgar_ingest.config import DISPATCH_RESERVE_FLOOR_SECONDS as floor, Settings, admit_dispatch_reserve
        with self.assertRaisesRegex(ValueError, "dispatch_reserve_seconds"):
            admit_dispatch_reserve(Settings.from_mapping(self.live()))
        for bad in (floor - 1, 3600, 3601):
            with self.subTest(value=bad), self.assertRaisesRegex(ValueError, "dispatch_reserve_seconds"):
                admit_dispatch_reserve(Settings.from_mapping(self.live(dispatch_reserve_seconds=bad)))
        for good in (floor, 3599):
            with self.subTest(value=good):
                self.assertEqual(admit_dispatch_reserve(Settings.from_mapping(self.live(dispatch_reserve_seconds=good))), good)
        self.assertIsNone(admit_dispatch_reserve(fixture_settings()))

    def test_fc68adef_origin_live_child_contexts_validate_without_the_key(self):
        from sec_edgar_ingest.config import Settings
        from sec_edgar_ingest.models import RunContext
        evidence = json.loads((PROJECT / "specs/evidence/local-port/sec-acceptance.json").read_text())
        contexts = [source[step]["context"] for source in evidence["selected_sources"]
                    for step in ("transform", "publish")]
        self.assertEqual(len(contexts), 6)
        for value in contexts:
            with self.subTest(run=value["run_id"], command=value["command"]):
                context = RunContext.from_mapping(value)
                self.assertNotIn("dispatch_reserve_seconds", value["effective_config"]["execution"])
                self.assertEqual(Settings.from_mapping(value["effective_config"]).config_sha256, context.config_sha256)
```

`test_key_is_a_positive_integer_and_never_null` accepts either message. A bool or a string fails type decoding ("has an invalid type"). The range and null checks name the key.

- [ ] **Step 2: Run the tests to verify that they fail.**

Run the test command with target `test_config.DispatchReserveConfigTests`.
Expected: errors. `ImportError: cannot import name 'DISPATCH_RESERVE_FLOOR_SECONDS'`, `AttributeError: … 'dispatch_reserve_seconds'`, and `ExecutionSettings unknown keys: ['dispatch_reserve_seconds']`. Only `test_fc68adef_origin_live_child_contexts_validate_without_the_key` passes already. It guards B1 for historical configs.

- [ ] **Step 3: Implement the field and the hash-preserving mapping.** In `config.py`, change `ExecutionSettings`:

```python
@dataclass(frozen=True, slots=True)
class ExecutionSettings(Record):
    max_run_seconds: int
    dispatch_reserve_seconds: int | None = None
```

In `Settings.__post_init__`, after the `require_number(self.execution.max_run_seconds, …)` line, add:

```python
        if self.execution.dispatch_reserve_seconds is not None:
            require_number(self.execution.dispatch_reserve_seconds, "execution.dispatch_reserve_seconds",
                           positive=True, integer=True)
```

Replace `Settings.from_mapping` and `Settings.to_mapping` with:

```python
    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> Settings:
        if isinstance(value, dict) and "fixture" in value and value["fixture"] is None:
            raise ValueError("fixture must be an explicit object when supplied")
        execution = value.get("execution") if isinstance(value, dict) else None
        if isinstance(execution, dict) and execution.get("dispatch_reserve_seconds", 0) is None:
            raise ValueError("execution.dispatch_reserve_seconds must be an integer when supplied")
        return record_from_mapping(cls, value, require_all=False)

    def to_mapping(self) -> dict[str, object]:
        mapping = super(Settings, self).to_mapping()
        if self.fixture is None:
            mapping.pop("fixture")
        # An absent reserve stays absent, so every pre-reserve effective-config hash is unchanged.
        if self.execution.dispatch_reserve_seconds is None:
            mapping["execution"].pop("dispatch_reserve_seconds")
        return mapping
```

- [ ] **Step 4: Add the floor constant (the one literal).** After `WORKER_ALLOWANCE_SECONDS = 3600`, add the constant with the floor that D2 approved. For example, if D2 approved 120 seconds:

```python
# Owner decision D2 (plan 4, Task 2): the finish step's measured cost with margin.
DISPATCH_RESERVE_FLOOR_SECONDS = 120
```

Use D2's integer, not 120, unless D2 approved 120. No other file holds this number. Tests and code use the name.

- [ ] **Step 5: Add the admission function.** After `_validate_live_policy`, add:

```python
def admit_dispatch_reserve(settings: Settings) -> int | None:
    """Admit a new workflow invocation's dispatch reserve.

    Call this only on the invocation's own config: frozen historical configs never carry the key.
    Live work requires floor <= reserve < execution.max_run_seconds; fixture work may omit it.
    """
    reserve = settings.execution.dispatch_reserve_seconds
    if settings.acquisition.mode != "live":
        return reserve
    if reserve is None:
        raise ValueError("live workflow admission requires execution.dispatch_reserve_seconds")
    if not DISPATCH_RESERVE_FLOOR_SECONDS <= reserve < settings.execution.max_run_seconds:
        raise ValueError(f"execution.dispatch_reserve_seconds must be at least {DISPATCH_RESERVE_FLOOR_SECONDS}"
                         " and below execution.max_run_seconds")
    return reserve
```

- [ ] **Step 6: Run the tests to verify that they pass.**

Run the test command with targets `test_config` and `test_local_config`.
Expected: `OK`.

- [ ] **Step 7: Commit.**

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/config.py packages/sec-edgar-ingest/tests/test_config.py
git commit -m "feat(config): add the optional dispatch reserve and its admission check"
```

---

### Task 4: Admission in the launcher and the engine (B2)

**Files:**
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/local_cli.py:21` (import), `:96–97` (after the timeout check)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/cli.py:17` (import), `_validate_workflow` (:403–406)
- Test: `packages/sec-edgar-ingest/tests/test_local_launcher.py`, `packages/sec-edgar-ingest/tests/test_workflow_cli.py`

**Interfaces:**
- Consumes: `admit_dispatch_reserve`, `DISPATCH_RESERVE_FLOOR_SECONDS` (Task 3).
- Produces: launcher refusal (`ValueError`, exit 2) and engine refusal (exit 2, `configuration` on stderr). Both happen before preflight, logs or stores.

- [ ] **Step 1: Give the existing live launcher configs the key (F-P7).** In `test_local_launcher.py`, in both `setUp` methods that set `value['acquisition'] = {'mode': 'live'}` (near lines 48 and 388), add after that line:

```python
        from sec_edgar_ingest.config import DISPATCH_RESERVE_FLOOR_SECONDS
        value['execution']['dispatch_reserve_seconds'] = DISPATCH_RESERVE_FLOOR_SECONDS
```

`InstalledLauncherTests.test_shell_finds_default_outside_checkout_and_archives_real_installed_release` prepares with `--timeout-seconds 0.000001` to reach the expired-deadline path. B2 refuses that timeout for a live config. The test is about dispatch selection, not admission, so make its config fixture acquisition. Add at the start of that test:

```python
        # B2 refuses a live timeout at or below the reserve; this test is about dispatch selection, not admission.
        value = json.loads(self.config.read_bytes())
        value['acquisition'] = {'mode': 'fixture'}
        value['execution'].pop('dispatch_reserve_seconds')
        self.config.write_text(json.dumps(value))
```

The other tests in both classes keep the live config. They prepare with the default 3,300-second timeout, then replace the deadline, or they patch `execve`.

- [ ] **Step 2: Write the failing launcher test.** Add to `LauncherPreparationTests`:

```python
    def write_execution(self, **execution):
        value = json.loads(self.config.read_text())
        value['execution'] = {'max_run_seconds': 3600, **execution}
        self.config.write_text(json.dumps(value, indent=3) + '\n')

    def test_live_reserve_admission_refuses_before_preflight_or_logs(self):
        from sec_edgar_ingest.config import DISPATCH_RESERVE_FLOOR_SECONDS as floor
        for execution in ({}, {'dispatch_reserve_seconds': floor - 1}, {'dispatch_reserve_seconds': 3600}):
            with self.subTest(execution=execution):
                self.write_execution(**execution)
                with self.assertRaisesRegex(ValueError, 'dispatch_reserve_seconds'):
                    self.prepare()
        self.write_execution(dispatch_reserve_seconds=floor)
        with self.assertRaisesRegex(ValueError, 'dispatch_reserve_seconds'):
            self.prepare(timeout=floor)
        self.preflight.assert_not_called()
        self.assertFalse((self.project / 'logs').exists())
        invocation = self.prepare(timeout=floor + 1)
        self.assertEqual((invocation.deadline - invocation.started_at).total_seconds(), floor + 1)
```

- [ ] **Step 3: Write the failing engine test.** Add to `WorkflowCliTests` in `test_workflow_cli.py`:

```python
    def test_live_workflow_without_an_admitted_reserve_refuses_before_any_store(self):
        from support import local_config_mapping
        from sec_edgar_ingest.config import DISPATCH_RESERVE_FLOOR_SECONDS as floor
        value = local_config_mapping()
        value.pop('fixture', None)
        value['acquisition'] = {'mode': 'live'}
        value['etl']['parser_version'] = 'sec-index-parser-v1'
        value['runtime'] = {'kind': 'native', 'release_manifest': '/missing/releases/sha256=' + 'a' * 64 + '/release.json'}
        value['storage']['root'] = str(self.root / 'live-data')
        value['logging']['root'] = str(self.root / 'live-logs')
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat()
        config = self.root / 'live.json'
        argv = ['backfill', '--config', str(config), '--run-id', 'live', '--execution-id', 'manual',
                '--attempt-id', 'a', '--deadline', deadline]
        for execution, refused in (({}, True), ({'dispatch_reserve_seconds': floor - 1}, True),
                                   ({'dispatch_reserve_seconds': 3600}, True),
                                   ({'dispatch_reserve_seconds': floor}, False)):
            with self.subTest(execution=execution):
                value['execution'] = {'max_run_seconds': 3600, **execution}
                config.write_text(json.dumps(value))
                code, message, err = cli_call(argv)
                self.assertEqual(code, 2)
                self.assertIsNone(message)
                self.assertEqual(json.loads(err)['outcome'], 'configuration')
                # An admitted reserve passes on to the release preflight, which refuses the missing manifest.
                self.assertEqual('dispatch_reserve_seconds' in err, refused, err)
                self.assertFalse((self.root / 'live-data').exists())
```

- [ ] **Step 4: Run the tests to verify that they fail.**

Run the test command with targets `test_local_launcher.LauncherPreparationTests.test_live_reserve_admission_refuses_before_preflight_or_logs` and `test_workflow_cli.WorkflowCliTests.test_live_workflow_without_an_admitted_reserve_refuses_before_any_store`.
Expected: FAIL. The launcher prepares a keyless invocation ("ValueError not raised"). The engine's stderr names the manifest, not `dispatch_reserve_seconds`.

- [ ] **Step 5: Implement the launcher check.** In `local_cli.py`, change the import to `from .config import admit_dispatch_reserve, normalize_paths, parse_config, pin_context`. After `raise ValueError('timeout_seconds exceeds execution.max_run_seconds')`, add:

```python
    reserve = admit_dispatch_reserve(settings)
    if reserve is not None and timeout_seconds <= reserve:
        raise ValueError('timeout_seconds must exceed execution.dispatch_reserve_seconds')
```

- [ ] **Step 6: Implement the engine check.** In `cli.py`, change the import to `from .config import Settings, admit_dispatch_reserve, load_config, pin_context`. In `_validate_workflow`, after the `raise ValueError('deadline exceeds execution.max_run_seconds')` block, add:

```python
    # B2 admission reads only this invocation's own config, before any store opens (plan 4 P3).
    admit_dispatch_reserve(settings)
```

- [ ] **Step 7: Run the affected modules.**

Run the test command with targets `test_local_launcher`, `test_workflow_cli`, `test_launcher_process` and `test_acceptance_selection`.
Expected: `OK`. If another module prepares or runs a live workflow invocation from a keyless config, add the key as in Step 1, and record a `> Deviation:` line that names the file.

- [ ] **Step 8: Commit.**

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/local_cli.py packages/sec-edgar-ingest/src/sec_edgar_ingest/cli.py packages/sec-edgar-ingest/tests/test_local_launcher.py packages/sec-edgar-ingest/tests/test_workflow_cli.py
git commit -m "feat(workflows): admit live workflow runs only with an in-range reserve"
```

---

### Task 5: The dispatch cutoff (B3)

**Files:**
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py:5` (import), `run_workflow` (:76–94)
- Create: `packages/sec-edgar-ingest/tests/test_workflow_drain.py`

**Interfaces:**
- Consumes: `Settings.execution.dispatch_reserve_seconds` (Task 3).
- Produces: in `test_workflow_drain.py`, the helpers `MemberBudget`, `harness(root, pack, reserve=RESERVE, start='2026Q3')`, `widen(pack, times)` and `run(h, run_id, allowed) -> (WorkflowResult, list[str])`. `run` returns the report and the step IDs that the run dispatched. Task 6 uses these helpers.

- [ ] **Step 1: Write the test module with the cutoff tests.** Create `packages/sec-edgar-ingest/tests/test_workflow_drain.py`:

```python
"""Stage 1a: the dispatch cutoff (B3) and the sibling-completion skip (B4-B6)."""
from network_guard import install
install()

import hashlib, json, tempfile, unittest
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from support import fixture_settings
from support_process import checked_dispatcher as Dispatcher
from support_workflows import CommandHarness, quarter_pack, simple_pack
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.etl.reader import capture_quarter
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.models import Error, RunContext, canonical_json, to_mapping_value
from sec_edgar_ingest.runtime import configured_descriptor
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows.contracts import COMPLETE, LOCAL_CONTRACT, workflow_path
from sec_edgar_ingest.workflows.members import WorkflowMembers
from sec_edgar_ingest.workflows.results import freeze_workflow, read_workflow_result, write_workflow_result
from sec_edgar_ingest.workflows.runner import run_workflow

RESERVE = 600
TODAY = date(2026, 10, 7)


class MemberBudget:
    """Stands in for runner.datetime.now: the first `allowed` checks see the start, later ones the cutoff."""
    def __init__(self, context, allowed, reserve=RESERVE):
        self.start, self.cutoff = context.started_at, context.deadline - timedelta(seconds=reserve)
        self.allowed, self.calls = allowed, 0

    def now(self, tz=None):
        self.calls += 1
        return self.start if self.calls <= self.allowed else self.cutoff


def harness(root, pack, reserve=RESERVE, start='2026Q3'):
    execution = {'max_run_seconds': 3600}
    if reserve is not None:
        execution['dispatch_reserve_seconds'] = reserve
    settings = fixture_settings(root=root / '.fixture-state',
        backfill={'start_quarter': start, 'end_quarter': 'open'},
        etl={'parser_version': 'fixture-index-parser-v1'},
        fixture={'allow_clock_override': True, 'allow_deadline_override': False},
        execution=execution)
    return CommandHarness(root, pack, settings)


def widen(pack, times):
    """Repeat every fixture response, so many discoveries can read the same listings."""
    manifest = json.loads(pack.read_text())
    manifest['responses'] = {url: responses * times for url, responses in manifest['responses'].items()}
    pack.write_bytes(canonical_json(to_mapping_value(manifest)))
    return pack


def run(h, run_id, allowed):
    now = datetime.now(timezone.utc)
    context = RunContext(run_id, 'manual', 'backfill', 'a', h.settings.etl.parser_version,
        h.settings.etl.schema_version, h.settings.config_sha256, now, now + timedelta(seconds=1800), 'backfill',
        runtime=configured_descriptor(h.settings), format_version='sec-local-run-context-v1')
    context = pin_context(h.settings, context, TODAY)[0]
    intent = {'contract_version': LOCAL_CONTRACT, 'command': 'backfill', 'today': TODAY.isoformat(),
              'fixture_sha256': hashlib.sha256(h.pack.read_bytes()).hexdigest(), 'pinned_end_quarter': '2026Q4'}
    context = freeze_workflow(context, intent, h.store, h.objects)
    dispatcher = Dispatcher(context, h.settings, h.pack, h.root, h.store, h.objects)
    budget, steps = MemberBudget(context, allowed), []
    execute = dispatcher.execute
    def counted(command, step_id, settings, flags):
        steps.append(step_id)
        return execute(command, step_id, settings, flags)
    with patch('sec_edgar_ingest.workflows.runner.datetime', wraps=datetime) as clock, \
            patch.object(dispatcher, 'execute', side_effect=counted):
        clock.now.side_effect = budget.now
        report = run_workflow(context, h.settings, intent, dispatcher, h.store, h.objects)
    path = write_workflow_result(report, h.store, h.objects)
    if read_workflow_result(path, h.store, h.objects) != report:
        raise AssertionError('written workflow result does not read back')
    return report, steps


class CutoffTests(unittest.TestCase):
    def test_members_after_the_cutoff_defer_and_the_result_is_written_before_the_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, simple_pack(root / 'pack'))
            try:
                report, steps = run(h, 'cutoff', allowed=1)
                first, second = report.members
                # The first member's children run while the cutoff passes; the member still completes.
                self.assertIn(first.outcome, COMPLETE)
                self.assertEqual(second.outcome, 'pending')
                self.assertEqual([gap.code for gap in second.gaps], ['workflow_deferred'])
                self.assertEqual(second.child_refs, ())
                self.assertFalse(any(step.endswith(second.member_id) for step in steps))
                self.assertLess(datetime.fromisoformat(report.ended_at), report.context.deadline)
                self.assertEqual(report.outcome, 'incomplete')
            finally:
                h.close()

    def test_a_missing_reserve_keeps_the_deadline_as_the_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, simple_pack(root / 'pack'), reserve=None)
            try:
                # The budget reports deadline - RESERVE after its first check: still before a deadline cutoff.
                report, _ = run(h, 'no-reserve', allowed=1)
                self.assertTrue(all(member.outcome in COMPLETE for member in report.members))
            finally:
                h.close()


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify that they fail.**

Run the test command with target `test_workflow_drain.CutoffTests`.
Expected: `test_members_after_the_cutoff_defer…` FAILS. Without B3 the cutoff is the deadline, so both members complete ("'success' != 'pending'" or similar). `test_a_missing_reserve…` passes.

- [ ] **Step 3: Implement the cutoff.** In `runner.py`, change line 5 to `from datetime import datetime, timedelta, timezone`. In `run_workflow`, replace:

```python
    results, receipt_descriptors, evidences = [], [], []
    halted = selection['halted']
```

with:

```python
    results, receipt_descriptors, evidences = [], [], []
    halted = selection['halted']
    reserve = settings.execution.dispatch_reserve_seconds
    # B3: stop dispatch early enough that the finish step writes the durable result before the deadline.
    cutoff = context.deadline if reserve is None else context.deadline - timedelta(seconds=reserve)
```

Then replace `elif halted or datetime.now(timezone.utc) >= context.deadline:` with:

```python
        elif halted or datetime.now(timezone.utc) >= cutoff:
```

Keep the `workflow_deferred` gap and its message unchanged. `_validate_report` compares a receipt-less member with that exact canonical pending member.

- [ ] **Step 4: Run the tests to verify that they pass.**

Run the test command with targets `test_workflow_drain` and `test_workflow_runner`.
Expected: `OK`.

- [ ] **Step 5: Commit.**

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py packages/sec-edgar-ingest/tests/test_workflow_drain.py
git commit -m "feat(workflows): stop dispatch at the deadline minus the reserve"
```

---

### Task 6: The sibling-completion skip and its receipt (B4, B5, B6)

**Files:**
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/contracts.py:108–112` (`MemberResult.__post_init__`)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py` (`validate_member_evidence` after :128; new `_validate_sibling_completion`; import of `validate_capture` at :10 is present)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/results.py` (`_validate_report` member loop, complete branch)
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py` (imports; new `sibling_completion`; member loop)
- Test: `packages/sec-edgar-ingest/tests/test_workflow_drain.py`

**Interfaces:**
- Consumes: `harness`, `widen`, `run`, `MemberBudget` (Task 5).
- Produces: `runner.sibling_completion(value: Mapping, previous: MemberResult | None, completed_sources: frozenset[str], context: RunContext, store, objects) -> ProcessedMember | None`. The B4 receipt shape: outcome `unchanged`; `snapshot_ref`, `transformed_ref` `None`; `child_refs == ()`; `downloaded`, `transformed`, `quarantined` false; no gaps; one `PublicationResult(quarter, 'unchanged', generation_id, manifest_ref, None, 0)` per capture quarter. The evidence holds `calls == []`, `resolutions == []`, `terminal_error is None` and the completion capture.

- [ ] **Step 1: Write the failing drain, shape, refusal and replay tests.** Append to `test_workflow_drain.py`, before the `if __name__` block:

```python
def child_counts(h, steps):
    """Child sequences per (command, source), from dispatched step IDs."""
    source_of = {v['member_id']: v['source']['source_id'] for v in WorkflowMembers(h.store, h.objects).inventory()[0]}
    counts = Counter()
    for step in steps:
        command, _, member_id = step.partition('-')
        if command in ('collect', 'transform', 'publish'):
            counts[command, source_of[member_id]] += 1
    return counts, set(source_of.values())


class SiblingCompletionTests(unittest.TestCase):
    def pair(self, h, name):
        """Defer every member once, then run with room: each source has a retained and a new member."""
        run(h, name + '-0', allowed=0)
        return run(h, name + '-1', allowed=10)

    def test_pending_sources_drain_with_one_child_sequence_each(self):
        periods = ('2025Q1', '2025Q2', '2025Q3', '2025Q4', '2026Q1', '2026Q2', '2026Q3', '2026Q4')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, widen(quarter_pack(root / 'pack', periods), 4), start='2025Q1')
            try:
                first, steps = run(h, 'drain-0', allowed=0)
                self.assertEqual(steps, ['discover'])
                self.assertEqual(first.counts['pending_sources'], 8)
                runs = 1
                while True:
                    # An odd budget makes cutoffs fall inside same-source pairs (plan 4 F-P2).
                    report, more = run(h, f'drain-{runs}', allowed=5)
                    steps.extend(more)
                    runs += 1
                    if not any(gap.code == 'workflow_deferred' for member in report.members for gap in member.gaps):
                        break
                    self.assertLess(runs, 20, 'the drain made no progress')
                self.assertGreater(runs, 2)
                counts, sources = child_counts(h, steps)
                self.assertEqual(len(sources), 8)
                for source_id in sources:
                    for command in ('collect', 'transform', 'publish'):
                        with self.subTest(source=source_id, command=command):
                            self.assertEqual(counts[command, source_id], 1)
                for period in periods:
                    self.assertIsNotNone(capture_quarter(period, h.objects, EtlState(h.store)))
                self.assertIn(report.outcome, ('success', 'unchanged'))
            finally:
                h.close()

    def test_sibling_receipt_shape_capture_and_exact_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, widen(simple_pack(root / 'pack'), 4))
            try:
                report, steps = self.pair(h, 'pair')
                self.assertEqual(len(report.members), 4)
                skipped = [member for member in report.members if not member.child_refs]
                self.assertEqual(len(skipped), 2)
                registry = WorkflowMembers(h.store, h.objects)
                values = {v['member_id']: v for v in registry.inventory()[0]}
                receipts = {}
                for member in skipped:
                    self.assertEqual((member.outcome, member.snapshot_ref, member.transformed_ref),
                                     ('unchanged', None, None))
                    self.assertFalse(member.downloaded or member.transformed or member.quarantined or member.gaps)
                    self.assertTrue(member.quarters)
                    self.assertTrue(all(q.outcome == 'unchanged' and q.candidate_ref is None and q.conflicts == 0
                                        for q in member.quarters))
                    self.assertFalse(any(step.endswith(member.member_id) for step in steps))
                    capture = registry.completed(values[member.member_id], member.parser_version, member.schema_version)
                    self.assertEqual([(q['quarter'], q['generation_id']) for q in capture['quarters']],
                                     [(q.quarter, q.generation_id) for q in member.quarters])
                    path = registry._path(member.member_id, report.context)
                    receipts[path] = h.objects.read(path)
                    self.assertEqual(registry._read_receipt(path)[2]['calls'], [])
                dispatcher = Dispatcher(report.context, h.settings, h.pack, h.root, h.store, h.objects)
                with patch.object(dispatcher, 'execute', side_effect=AssertionError('replay dispatched a child')), \
                        patch('sec_edgar_ingest.workflows.runner.reuse_exact_binding',
                              side_effect=AssertionError('replay decided a skip again')):
                    replay = run_workflow(report.context, h.settings, to_mapping_value(report.intent['invocation']),
                                          dispatcher, h.store, h.objects)
                self.assertEqual((replay.intent, replay.members, replay.outcome, replay.counts),
                                 (report.intent, report.members, report.outcome, report.counts))
                for path, body in receipts.items():
                    self.assertEqual(h.objects.read(path), body)
                self.assertEqual(read_workflow_result(workflow_path(report.context), h.store, h.objects), report)
            finally:
                h.close()

    def test_sibling_receipt_shape_is_exact(self):
        from sec_edgar_ingest.workflows.processing import validate_member_evidence
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, widen(simple_pack(root / 'pack'), 4))
            try:
                report, _ = self.pair(h, 'shape')
                member = next(m for m in report.members if not m.child_refs)
                registry = WorkflowMembers(h.store, h.objects)
                result, _, evidence, _ = registry._read_receipt(registry._path(member.member_id, report.context))
                first = result.quarters[0]
                for change in ({'outcome': 'success'}, {'downloaded': True}, {'transformed': True},
                               {'quarters': (replace(first, outcome='published'),) + result.quarters[1:]}):
                    with self.subTest(result=change), self.assertRaises(ValueError):
                        replace(result, **change)
                evidence = to_mapping_value(evidence)
                tampered = (
                    ({'gaps': (Error('state_conflict', 'invented', False, result.source.source_id, {}),)}, {}),
                    ({'quarters': (replace(first, generation_id='0' * 64),) + result.quarters[1:]}, {}),
                    ({'quarters': (replace(first, conflicts=1),) + result.quarters[1:]}, {}),
                    ({}, {'completion': None}),
                    ({}, {'resolutions': [{'ref': 'invented'}]}),
                )
                for result_change, evidence_change in tampered:
                    with self.subTest(result=result_change, evidence=evidence_change), self.assertRaises(Conflict):
                        validate_member_evidence(replace(result, **result_change), {**evidence, **evidence_change}, h.objects)
            finally:
                h.close()

    def test_refusals_leave_the_member_to_its_child_sequence(self):
        from contextlib import nullcontext
        from sec_edgar_ingest.workflows import runner
        from sec_edgar_ingest.workflows.contracts import CompletionEvaluation
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = harness(root, widen(simple_pack(root / 'pack'), 4))
            try:
                report, _ = self.pair(h, 'refuse')
                done = next(m for m in report.members if m.child_refs)
                other = next(m for m in report.members if m.source.source_id != done.source.source_id)
                values = WorkflowMembers(h.store, h.objects).inventory()[0]
                sibling = next(v for v in values
                               if v['source']['source_id'] == done.source.source_id and v['member_id'] != done.member_id)
                identity = done.source.source_id
                conflict = Error('state_conflict', 'corrupt sibling evidence', False, identity, {})
                unpinned = Error('acquisition_pending', 'member has no exact raw pin', True, identity, {})
                cases = {
                    'no preceding member, source not already complete': {'previous': None},
                    'preceding member of another source': {'previous': other},
                    'failed sibling': {'previous': replace(done, outcome='state_conflict')},
                    'pending sibling': {'previous': replace(done, outcome='pending')},
                    'binding gap': {'reuse': (conflict,)},
                    'divergent or missing binding': {'evaluation': CompletionEvaluation(False, None, (), (unpinned,))},
                    'repair obligation': {'evaluation': CompletionEvaluation(False, None, ({'ref': 'obligation'},), ())},
                    'corrupt evidence': {'evaluation': CompletionEvaluation(False, None, (), (conflict,))},
                }
                for name, case in cases.items():
                    evaluation = (patch.object(runner, 'evaluate_member', return_value=case['evaluation'])
                                  if 'evaluation' in case else nullcontext())
                    with self.subTest(case=name), evaluation, \
                            patch.object(runner, 'reuse_exact_binding', return_value=case.get('reuse', ())):
                        before = tuple(h.store.scan('WorkflowMemberResult', {}))
                        self.assertIsNone(runner.sibling_completion(sibling, case.get('previous', done), frozenset(),
                                                                    report.context, h.store, h.objects))
                        self.assertEqual(tuple(h.store.scan('WorkflowMemberResult', {})), before)
                # Positive controls: a complete preceding sibling, and a source already complete at selection.
                for previous, completed in ((done, frozenset()), (None, frozenset({identity}))):
                    with self.subTest(previous=previous is not None):
                        processed = runner.sibling_completion(sibling, previous, completed, report.context, h.store, h.objects)
                        self.assertEqual((processed.result.outcome, processed.result.child_refs), ('unchanged', ()))
            finally:
                h.close()
```

- [ ] **Step 2: Run the tests to verify that they fail.**

Run the test command with target `test_workflow_drain.SiblingCompletionTests`.
Expected:
- `test_pending_sources_drain_with_one_child_sequence_each` FAILS with counts of 2 or more (F10).
- The shape and replay tests FAIL, because no member has `child_refs == ()` ("0 != 2").
- `test_refusals…` ERRORS with `AttributeError: … has no attribute 'sibling_completion'`.

- [ ] **Step 3: Accept the B4 shape in `MemberResult`.** In `workflows/contracts.py`, replace:

```python
        if self.outcome in COMPLETE and (
            not self.snapshot_ref or not self.transformed_ref
            or any(quarter.outcome not in ('published', 'unchanged') for quarter in self.quarters)
        ):
            raise ValueError('complete member lacks successful ETL/publication captures')
```

with:

```python
        if self.outcome in COMPLETE:
            if self.snapshot_ref is None and self.transformed_ref is None and not self.child_refs:
                # B4 sibling completion: this run already completed the source, so no child of its own ran.
                if (self.outcome != 'unchanged' or self.downloaded or self.transformed
                        or any(quarter.outcome != 'unchanged' for quarter in self.quarters)):
                    raise ValueError('sibling completion must be unchanged with no child progress')
            elif (not self.snapshot_ref or not self.transformed_ref
                    or any(quarter.outcome not in ('published', 'unchanged') for quarter in self.quarters)):
                raise ValueError('complete member lacks successful ETL/publication captures')
```

- [ ] **Step 4: Validate the B4 receipt (B5).** In `workflows/processing.py`, in `validate_member_evidence`, after the line `raise Conflict('member differs from immutable original projection')`, add:

```python
    if not evidence['calls'] and evidence['terminal_error'] is None:
        _validate_sibling_completion(result, evidence, value, objects)
        return
```

Add this function after `validate_member_evidence`:

```python
def _validate_sibling_completion(result, evidence, value, objects) -> None:
    """B4 receipt: the run already completed this source, so its capture stands in for every child."""
    if (result.outcome != 'unchanged' or result.child_refs or result.snapshot_ref is not None
            or result.transformed_ref is not None or result.downloaded or result.transformed
            or result.quarantined or result.gaps or evidence['resolutions']):
        raise Conflict('member has no checked source operation')
    complete = evidence['completion']
    if complete is None or complete['member'] != value:
        raise Conflict('sibling completion lacks exact captured evidence')
    validate_capture(complete, objects)
    if (complete['observation']['parser_version'], complete['observation']['schema_version']) != (
            result.parser_version, result.schema_version):
        raise Conflict('member capture processing versions differ')
    expected = [(q['quarter'], 'unchanged', q['generation_id'], q['manifest_ref'], None, 0) for q in complete['quarters']]
    actual = [(q.quarter, q.outcome, q.generation_id, q.manifest_ref, q.candidate_ref, q.conflicts) for q in result.quarters]
    if actual != expected:
        raise Conflict('sibling completion quarters differ from immutable capture')
```

A receipt with no calls that is not this exact shape keeps today's refusal message.

- [ ] **Step 5: Accept a B4 member in the workflow report.** In `workflows/results.py` `_validate_report`, replace:

```python
        if member.outcome in ('success', 'unchanged', 'no_new_sources'):
            if member.member_id not in by_member or 'publish' not in by_command:
                raise Conflict('complete member lacks child and immutable completion evidence')
            capture = by_member[member.member_id]
            from ..worksets import make_snapshot_workset
            from ..models import Snapshot
            projection = decode_source_workset(objects.read(selected[member.member_id]['member_ref']))
            if make_snapshot_workset(projection, (Snapshot.from_mapping(capture['snapshot']),)) != snapshot_set:
                raise Conflict('complete member snapshot capture differs from exact child input')
```

with:

```python
        if member.outcome in ('success', 'unchanged', 'no_new_sources'):
            # MemberResult admits a complete member with no child only in the B4 sibling-completion shape.
            sibling = not member.child_refs and member.snapshot_ref is None and member.transformed_ref is None
            if member.member_id not in by_member or not (sibling or 'publish' in by_command):
                raise Conflict('complete member lacks child and immutable completion evidence')
            capture = by_member[member.member_id]
            if not sibling:
                from ..worksets import make_snapshot_workset
                from ..models import Snapshot
                projection = decode_source_workset(objects.read(selected[member.member_id]['member_ref']))
                if make_snapshot_workset(projection, (Snapshot.from_mapping(capture['snapshot']),)) != snapshot_set:
                    raise Conflict('complete member snapshot capture differs from exact child input')
```

The checks after this block (capture member, versions, affected quarters, quarter generations) stay as they are and apply to both shapes.

- [ ] **Step 6: Add the skip to the runner (B4).** In `workflows/runner.py`:

1. Change `from .contracts import MemberResult, WorkflowResult, FATAL, summarize, workflow_path` to `from .contracts import COMPLETE, MemberResult, WorkflowResult, FATAL, summarize, workflow_path`.
2. Change `from .processing import process_member, validate_member_evidence` to `from .processing import ProcessedMember, process_member, validate_member_evidence`.
3. Add `from ..etl.contracts import PublicationResult` after `from ..etl.state import EtlState`.

Add this function after `reuse_exact_binding`:

```python
def sibling_completion(value: Mapping, previous: MemberResult | None, completed_sources: frozenset[str],
                       context: RunContext, store, objects) -> ProcessedMember | None:
    """B4: complete a member without child work when this run already completed its source.

    The source counts as completed when the preceding loop member is a complete sibling, or when the
    frozen selection already holds a capture of it. Any refusal returns None: the member then runs its
    ordinary checked child sequence, which reports every gap as before (plan 4 P8).
    """
    identity = value['source']['source_id']
    preceded = previous is not None and previous.source.source_id == identity and previous.outcome in COMPLETE
    if not (preceded or identity in completed_sources):
        return None
    if reuse_exact_binding(value, store, objects):
        return None
    evaluated = evaluate_member(value, context.parser_version, context.schema_version, store, objects)
    if not evaluated.complete:  # A complete evaluation carries no obligation and no gap.
        return None
    capture = evaluated.capture
    quarters = tuple(PublicationResult(quarter['quarter'], 'unchanged', quarter['generation_id'],
                                       quarter['manifest_ref'], None, 0) for quarter in capture['quarters'])
    result = MemberResult(value['member_id'], Source.from_mapping(value['source']), value['parent_ref'],
        None, None, (), 'unchanged', False, False, False, quarters, (), context.parser_version, context.schema_version)
    evidence = {'contract_version': LOCAL_CONTRACT, 'format_version': 'sec-local-workflow-member-evidence-v1',
                'member': dict(value), 'calls': [], 'completion': capture, 'resolutions': [], 'terminal_error': None}
    validate_member_evidence(result, evidence, objects)
    return ProcessedMember(result, evidence)
```

In `run_workflow`, after the `cutoff = …` line from Task 5, add:

```python
    completed_sources = frozenset(capture['member']['source']['source_id'] for capture in selection['already_complete'])
```

Then replace:

```python
        else:
            processed = process_member(value, context, dispatcher, store, objects, observer)
```

with:

```python
        else:
            processed = sibling_completion(value, results[-1] if results else None, completed_sources,
                                           context, store, objects)
            if processed is None:
                processed = process_member(value, context, dispatcher, store, objects, observer)
```

The cutoff check stays before the skip (spec §4.2): a skip still reads captures.

- [ ] **Step 7: Run the tests to verify that they pass.**

Run the test command with target `test_workflow_drain`.
Expected: `OK`. The drain test reports more than two runs.

- [ ] **Step 8: Run the workflow modules.**

Run the test command with targets `test_workflow_runner`, `test_workflow_processing`, `test_workflow_results`, `test_workflow_contracts`, `test_workflow_cli`, `test_workflow_acceptance`, `test_workflow_completion`, `test_workflow_selection_v1`, `test_reconcile_workflow` and `test_reconcile_acceptance`.
Expected: `OK`. If an existing test now sees a skip where it expected a second child sequence, check whether the test asserted F10's double processing. If so, update the assertion to the B4 count and record a `> Deviation:` line. Otherwise stop and report.

- [ ] **Step 9: Commit.**

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/contracts.py packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/results.py packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py packages/sec-edgar-ingest/tests/test_workflow_drain.py
git commit -m "feat(workflows): complete a member whose source this run already completed"
```

---

### Task 7: Two-release tests (spec §5 item 6)

**Files:**
- Modify: `packages/sec-edgar-ingest/tests/support_release.py` (new `origin_release`)
- Create: `packages/sec-edgar-ingest/tests/test_release_origin.py`
- Create: `specs/evidence/d5-release/two-release.md`

**Interfaces:**
- Consumes: `proof_releases` (current code), `CheckedRunner`, `simple_pack`, `CommandHarness`.
- Produces: `origin_release(project: Path, cache: Path) -> VerifiedRelease` (revision `3ca50c7`, installed). Also the recorded answer to "does `fc68adef…` accept a B4 receipt", which Task 11 writes into §4.9.

- [ ] **Step 1: Write the failing tests.** Create `packages/sec-edgar-ingest/tests/test_release_origin.py`:

```python
"""Stage 1a §5 item 6: the current code continues fc68adef…-origin pending work, and fc68adef… meets a B4 receipt."""
from network_guard import install
install()

import hashlib, json, subprocess, tempfile, unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from support import fixture_settings
from support_process import CheckedRunner
from support_workflows import BASE, CommandHarness, simple_pack
from sec_edgar_ingest.config import Settings, pin_context
from sec_edgar_ingest.models import RunContext, canonical_json, to_mapping_value
from sec_edgar_ingest.runtime import configured_descriptor, isolated_environment, native_python_argv
from sec_edgar_ingest.workflows.checked import Dispatcher
from sec_edgar_ingest.workflows.contracts import COMPLETE, LOCAL_CONTRACT
from sec_edgar_ingest.workflows.members import WorkflowMembers
from sec_edgar_ingest.workflows.results import freeze_workflow, read_workflow_result, write_workflow_result
from sec_edgar_ingest.workflows.runner import run_workflow

TODAY = date(2026, 10, 7)
BLOCKED = BASE + 'full-index/2026/QTR3/master.zip'


class OriginReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support_release import origin_release, proof_releases
        project = Path(__file__).resolve().parents[3]
        cls.origin = origin_release(project, project / 'releases/artifact-cache')
        _, cls.current = proof_releases(project, project / 'releases/artifact-cache')

    def configured(self, h, release):
        value = h.settings.to_mapping()
        value['runtime'] = {'kind': 'native', 'release_manifest': str(release.directory / 'release.json')}
        return Settings.from_mapping(value)

    def origin_run(self, h, settings, run_id):
        """The whole backfill parent runs in the origin release's own installed interpreter."""
        config = h.root / (run_id + '.json')
        config.write_bytes(canonical_json(to_mapping_value(settings.to_mapping())))
        deadline = datetime.now(timezone.utc) + timedelta(seconds=1800)
        argv = [*native_python_argv(self.origin.python), '-m', 'sec_edgar_ingest', 'backfill',
                '--config', str(config), '--run-id', run_id, '--execution-id', 'manual', '--attempt-id', 'a',
                '--deadline', deadline.isoformat(), '--today', TODAY.isoformat(), '--fixture-pack', str(h.pack)]
        result = CheckedRunner()(self.origin.python, argv, deadline=deadline, environ=isolated_environment())
        return result.returncode, json.loads(result.stdout.decode().splitlines()[-1])

    def current_run(self, h, settings, run_id):
        now = datetime.now(timezone.utc)
        context = RunContext(run_id, 'manual', 'backfill', 'a', settings.etl.parser_version, settings.etl.schema_version,
            settings.config_sha256, now, now + timedelta(seconds=1800), 'backfill',
            runtime=configured_descriptor(settings), format_version='sec-local-run-context-v1')
        context = pin_context(settings, context, TODAY)[0]
        intent = {'contract_version': LOCAL_CONTRACT, 'command': 'backfill', 'today': TODAY.isoformat(),
                  'fixture_sha256': hashlib.sha256(h.pack.read_bytes()).hexdigest(), 'pinned_end_quarter': '2026Q4'}
        context = freeze_workflow(context, intent, h.store, h.objects)
        dispatcher = Dispatcher(context, settings, h.pack, h.root, h.store, h.objects, child_runner=CheckedRunner())
        steps, execute = [], dispatcher.execute
        def counted(command, step_id, child_settings, flags):
            steps.append((step_id, child_settings.runtime.release_manifest))
            return execute(command, step_id, child_settings, flags)
        dispatcher.execute = counted
        report = run_workflow(context, settings, intent, dispatcher, h.store, h.objects)
        path = write_workflow_result(report, h.store, h.objects)
        self.assertEqual(read_workflow_result(path, h.store, h.objects), report)
        return report, steps

    def continued(self, root):
        """The origin run halts on a 403 and leaves pending work; the current code then drains it.

        The current config carries no reserve key, so its receipts differ from the origin's only by
        the B4 shape (the key is tested separately below).
        """
        pack = simple_pack(root / 'pack')
        manifest = json.loads(pack.read_text())
        served = manifest['responses'][BLOCKED]
        manifest['responses'][BLOCKED] = [dict(response, status=403) for response in served]
        pack.write_bytes(canonical_json(to_mapping_value(manifest)))
        h = CommandHarness(root, pack)
        self.addCleanup(h.close)
        origin, current = self.configured(h, self.origin), self.configured(h, self.current)
        _, message = self.origin_run(h, origin, 'origin')
        self.assertEqual(message['outcome'], 'access_blocked', message)
        origin_members = {v['member_id'] for v in WorkflowMembers(h.store, h.objects).inventory()[0]}
        self.assertEqual(len(origin_members), 2)
        manifest['responses'][BLOCKED] = served
        pack.write_bytes(canonical_json(to_mapping_value(manifest)))
        report, steps = self.current_run(h, current, 'current')
        return h, origin, origin_members, report, steps

    def test_current_code_continues_origin_pending_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, _, origin_members, report, steps = self.continued(Path(tmp))
            self.assertIn(report.outcome, ('success', 'unchanged'))
            self.assertTrue(all(member.outcome in COMPLETE for member in report.members))
            self.assertTrue(origin_members <= {member.member_id for member in report.members})
            self.assertEqual(sum(1 for member in report.members if not member.child_refs), 2)
            source_of = {v['member_id']: v['source']['source_id'] for v in WorkflowMembers(h.store, h.objects).inventory()[0]}
            counts = Counter((step.partition('-')[0], source_of[step.partition('-')[2]]) for step, _ in steps
                             if step.partition('-')[0] in ('collect', 'transform', 'publish'))
            for source_id in set(source_of.values()):
                for command in ('collect', 'transform', 'publish'):
                    self.assertEqual(counts[command, source_id], 1, (command, source_id))
            origin_manifest = str(self.origin.directory / 'release.json')
            current_manifest = str(self.current.directory / 'release.json')
            for step, manifest in steps:
                command, _, member_id = step.partition('-')
                if command == 'collect':
                    # Collection stays bound to the release that discovered the member.
                    self.assertEqual(manifest, origin_manifest if member_id in origin_members else current_manifest)
                elif command in ('transform', 'publish'):
                    self.assertEqual(manifest, current_manifest)

    def test_origin_release_reports_a_b4_receipt_as_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, origin, _, report, _ = self.continued(Path(tmp))
            skipped = sorted(member.member_id for member in report.members if not member.child_refs)
            self.assertEqual(len(skipped), 2)
            code, message = self.origin_run(h, origin, 'origin-again')
            self.assertEqual((code, message['outcome']), (3, 'incomplete'), message)
            result = json.loads(h.objects.read(message['result_ref']))
            unresolved = sorted(gap['details']['member_id'] for gap in result['gaps']
                                if gap['code'] == 'legacy_member_unresolved')
            self.assertEqual(unresolved, skipped)

    def test_origin_settings_refuse_the_reserve_key(self):
        value = fixture_settings().to_mapping()
        value['execution']['dispatch_reserve_seconds'] = 600
        script = ('import json, sys\nfrom sec_edgar_ingest.config import Settings\n'
                  'Settings.from_mapping(json.loads(sys.argv[1]))\n')
        result = subprocess.run([*native_python_argv(self.origin.python), '-c', script, json.dumps(value)],
                                capture_output=True, text=True, env=isolated_environment())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown keys: ['dispatch_reserve_seconds']", result.stderr)


if __name__ == '__main__':
    unittest.main()
```

The expected answers are the plan's predictions from reading revision `3ca50c7`:
- `fc68adef…`'s `MemberResult` refuses the B4 shape. `select_work` turns that refusal into a `legacy_member_unresolved` gap, and its own evaluation still counts the member complete. So the run ends `incomplete` (exit 3).
- Its `ExecutionSettings` refuses the reserve key as unknown.

If execution observes a different answer, set the assertion to the observed value. Record a `> Deviation:` line, and carry the observed answer into Step 6 and Task 11.

- [ ] **Step 2: Run the tests to verify that they fail.**

Run the test command with target `test_release_origin`.
Expected: ERROR in `setUpClass`: `ImportError: cannot import name 'origin_release' from 'support_release'`.

- [ ] **Step 3: Add the origin-release helper.** In `support_release.py`, after `proof_releases`, add:

```python
ORIGIN_REVISION = '3ca50c78558bbf072a4eb75412af7d58a9e0f61b'  # source revision of release fc68adef…
_ORIGINS: dict[tuple[str, str], VerifiedRelease] = {}


def origin_release(project: Path, cache: Path) -> VerifiedRelease:
    """Build the fc68adef… source revision into its own committed repository and install it.

    Release identity covers the Git revision, so this release ID differs from fc68adef…; its
    application payload is that revision's. The checkout's later code never enters it.
    """
    project = project.absolute()
    override = os.environ.get('SEC_LOCAL_PROOF_CACHE')
    cache = Path(override) if override else cache
    if not cache.is_absolute():
        raise ValueError('proof cache path must be absolute')
    key = str(project), str(cache)
    if key in _ORIGINS:
        return _ORIGINS[key]
    prepare_artifact_cache(project / 'uv.lock', Path(sys.executable), cache, offline=True)
    temporary = tempfile.TemporaryDirectory(prefix='sec-native-origin-')
    _TEMPORARIES.append(temporary)
    root = Path(temporary.name)
    source = root / 'source'
    source.mkdir()
    archive = subprocess.run(['git', '-C', str(project), 'archive', '--format=tar', ORIGIN_REVISION],
                             check=True, capture_output=True).stdout
    subprocess.run(['tar', '-x', '-C', str(source)], input=archive, check=True)
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Native release proof',
                    '-c', 'user.email=proof@example.invalid', 'commit', '-qm',
                    'Origin source revision ' + ORIGIN_REVISION], check=True)
    release = preflight(build_release(source, root / 'releases', python=Path(sys.executable),
                                      artifact_cache=cache, offline=True) / 'release.json')
    assert_release_inventory(release)
    _ORIGINS[key] = release
    return release
```

- [ ] **Step 4: Run the tests to verify that they pass.**

Run the test command with target `test_release_origin`.
Expected: `OK` (3 tests). The first run builds two releases, so it takes minutes.

- [ ] **Step 5: Record whether the origin release matches `fc68adef…`.** From the worktree root:

```bash
SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --locked --package sec-edgar-ingest python - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, 'packages/sec-edgar-ingest/tests')
from network_guard import install
install()
from support_release import origin_release
project = Path.cwd().resolve()
origin = origin_release(project, project / 'releases/artifact-cache')
retained = json.loads(Path('/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/release.json').read_text())['identity']
built = origin.manifest['identity']
print(json.dumps({'origin_release_id': origin.release_id, 'git_revision': built['git_revision'],
    'package_files_equal': built['package_files'] == retained['package_files'],
    'application_wheel_sha256_equal': built['application_wheel_sha256'] == retained['application_wheel_sha256'],
    'dependencies_equal': built['dependencies'] == retained['dependencies'],
    'uv_lock_sha256_equal': built['uv_lock_sha256'] == retained['uv_lock_sha256'],
    'interpreter_equal': built['interpreter'] == retained['interpreter']}, indent=1))
PY
```

Expected: `package_files_equal`, `dependencies_equal`, `uv_lock_sha256_equal` and `interpreter_equal` are `true`. `git_revision` is the throwaway repository's commit, not `3ca50c7…`. `application_wheel_sha256_equal` is recorded as found. If `package_files_equal` is `false`, stop and report: the origin release would not stand for `fc68adef…`.

- [ ] **Step 6: Write the two-release evidence.** Create `specs/evidence/d5-release/two-release.md`:

```markdown
# Two-release behaviour (Stage 1a, plan 4 Task 7)

**Tests:** `packages/sec-edgar-ingest/tests/test_release_origin.py`, 3 tests, OK on <UTC date>, branch `stage1a-bounded-drain` at <commit>.
**Origin release:** built from revision `3ca50c7` (the `fc68adef…` source revision) by `support_release.origin_release`. Equivalence to the retained `fc68adef…` manifest: <paste the Step 5 JSON>.

## Results
1. The current code continues `fc68adef…`-origin pending work. An origin run halted on a 403 and left two pending members. One current run completed both sources, with each child sequence once. Collection of an origin-discovered member ran on the origin release.
2. `fc68adef…` reads a B4 receipt as corrupt. A later origin run reported `legacy_member_unresolved` for each B4 member and ended `incomplete` (exit 3).
3. `fc68adef…` refuses a config that carries `execution.dispatch_reserve_seconds` (`ExecutionSettings unknown keys`). So it cannot validate any receipt, child result or context written under a D5 live config, because those configs carry the key.

## Consequence for §4.9
After a D5 live run has written to a store, selecting `fc68adef…` again for that store is unsupported. Task 11 records this limit in the parent spec §4.9.
```

Replace each `<…>` with the observed value. If Step 1's predictions were changed by a deviation, write the observed results instead.

- [ ] **Step 7: Commit.**

```bash
git add packages/sec-edgar-ingest/tests/support_release.py packages/sec-edgar-ingest/tests/test_release_origin.py specs/evidence/d5-release/two-release.md
git commit -m "test(release): continue fc68adef-origin work and record its refusal of D5 receipts"
```

---

### Task 8: Full gate, whole-branch review and merge to main (HUMAN checkpoint)

**Files:**
- Create: `specs/evidence/d5-release/gate.md`

**Interfaces:**
- Consumes: the branch after Tasks 1–7.
- Produces: `main` holding the reviewed engine change, from which Task 9 builds.

- [ ] **Step 1: Run the full gate in the background.** From the worktree root, with `run_in_background`:

```bash
SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache sh scripts/check-sec-edgar-ingest.sh > /Users/lowell/Projects/sec-edgar-local/fixture-data/stage1a-gate.log 2>&1; echo "exit $?" >> /Users/lowell/Projects/sec-edgar-local/fixture-data/stage1a-gate.log
```

Expected: the log ends with `exit 0`, and unittest prints `OK`. The test count is 999 + the new tests, in 64 modules. The port's gate took about 56 minutes.

- [ ] **Step 2: Record the gate.** Create `specs/evidence/d5-release/gate.md` with the commit, the start and end times, the `Ran N tests in S s` line, `OK`, and the module count. Commit it:

```bash
git add specs/evidence/d5-release/gate.md
git commit -m "docs(evidence): record the Stage 1a branch gate"
```

- [ ] **Step 3: Whole-branch review.** Use the requesting-code-review skill. It dispatches the `code-reviewer` agent on `main..stage1a-bounded-drain`, against the spec, this plan and its Decisions. Fix each accepted finding with a test, re-run the affected modules, and commit. If a fix changes code, re-run Step 1 and update `gate.md`.

- [ ] **Step 4: Check that `main` carries no platform member.**

```bash
git -C /Users/lowell/Projects/sec-edgar-local show main:pyproject.toml | grep -n 'members'
git diff --stat 3ca50c7 stage1a-bounded-drain -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml
```

Expected: `members = ["packages/sec-edgar-ingest"]`, and no diff output.

- [ ] **Step 5: Owner checkpoint (HUMAN).** Show the owner the gate record, the review result, and `git log --oneline main..stage1a-bounded-drain`. Ask for approval to merge the branch into `main` before the release build (P7). Stop until the owner answers, and log the answer as D3.

- [ ] **Step 6: Merge.** In the main checkout:

```bash
cd /Users/lowell/Projects/sec-edgar-local
git status --porcelain --untracked-files=all
git merge --ff-only stage1a-bounded-drain || git merge --no-ff stage1a-bounded-drain -m "merge: Stage 1a bounded drain"
git status --porcelain --untracked-files=all
```

Expected: both `git status` calls print nothing. If `main` gained commits that touch the changed files, stop and ask before merging. Keep the worktree until Task 11 ends.

---

### Task 9: Build and verify the D5 release (B7; spec §7 items 1–3, 5)

Run in the main checkout on `main`.

**Files:**
- Create: `specs/evidence/d5-release/release.md`

**Interfaces:**
- Consumes: clean committed `main` after Task 8.
- Produces: `releases/sha256=<D5>/`. Its ID, manifest path and `git_revision` feed Tasks 10 and 11.

- [ ] **Step 1: Confirm a clean tree.**

```bash
cd /Users/lowell/Projects/sec-edgar-local
git status --porcelain --untracked-files=all
git rev-parse HEAD
```

Expected: no status output. Record the revision.

- [ ] **Step 2: Build.**

```bash
cd /Users/lowell/Projects/sec-edgar-local
export UV_PYTHON_DOWNLOADS=never
project=$(pwd -P)
UV_OFFLINE=1 uv run --offline --locked --package sec-edgar-ingest python scripts/prepare-native-release.py --project "$project" --releases "$project/releases" --python "$project/.venv/bin/python" --artifact-cache "$project/releases/artifact-cache" --offline
```

Expected: one printed path, `…/releases/sha256=<D5>`. Record `<D5>`.

- [ ] **Step 3: Check identity, lock and export (B7).**

```bash
cd /Users/lowell/Projects/sec-edgar-local
D5=releases/sha256=<D5>
FC=releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec
cmp "$D5/uv.lock" "$FC/uv.lock" && echo lock-identical
cmp "$D5/runtime-requirements.txt" "$FC/runtime-requirements.txt" && echo export-identical
git diff --exit-code 3ca50c7 HEAD -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml && echo inputs-identical
python3 -c "import json,sys; i=json.load(open(sys.argv[1]))['identity']; print(i['application']['version'], i['git_revision'], sorted(d['name'] for d in i['dependencies']))" "$D5/release.json"
```

Expected: `lock-identical`, `export-identical`, `inputs-identical`. Version `0.2.0`. `git_revision` equals Step 1's revision. The dependency names are the six that `fc68adef…` lists, with no platform package.

- [ ] **Step 4: Offline verification on the D5 interpreter.**

```bash
cd /Users/lowell/Projects/sec-edgar-local
project=$(pwd -P)
release="$project/releases/sha256=<D5>"
harness="$project/fixture-data/d5-harness-$(date -u +%Y%m%dT%H%M%SZ)"
UV_OFFLINE=1 uv run --offline --locked --package sec-edgar-ingest python - "$harness" <<'PY'
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
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null scripts/verify-native-release.py --release "$release" --harness "$harness" --evidence "$project/fixture-data/d5-verify-$(date -u +%Y%m%dT%H%M%SZ)"
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -c "import sys; from pathlib import Path; from sec_edgar_ingest.runtime import preflight_current; print(preflight_current(Path(sys.argv[1])).release_id)" "$release/release.json"
```

Expected: the verifier prints JSON with `"exit": 0` and `"release_id": "<D5>"`. `preflight_current` prints `<D5>`.

- [ ] **Step 5: Confirm retention.**

```bash
ls /Users/lowell/Projects/sec-edgar-local/releases
```

Expected: `sha256=49b7a2ed…`, `sha256=900952a8…`, `sha256=d718ae5f…`, `sha256=fc68adef…` and `sha256=<D5>` are all present.

- [ ] **Step 6: Write the release evidence.** Create `specs/evidence/d5-release/release.md` with:
1. The D5 release ID, its manifest path and its `git_revision` (§7 item 1).
2. The Step 3 results: identical lock, export and inputs, version `0.2.0`, and no platform package (§7 item 2).
3. The verifier JSON, the preflight output and the evidence directory path, with `fc68adef…` and older releases kept (§7 item 3).
4. The statement: "No SEC request was sent in Tasks 2–9. Measurement and verification used fixture acquisition only." (§7 item 5).

Commit:

```bash
git add specs/evidence/d5-release/release.md
git commit -m "docs(evidence): record the D5 release build and offline verification"
```

---

### Task 10: Select the D5 release in the live config (B8; spec §7 item 4; HUMAN checkpoint)

**Files:**
- Modify: `conf/sec-edgar-local.json` (`execution`, `runtime.release_manifest`)
- Modify: `specs/evidence/d5-release/release.md`

**Interfaces:**
- Consumes: D2's reserve and Task 9's `<D5>`.
- Produces: the new effective-config SHA-256, which Task 11 and the Handoff name.

- [ ] **Step 1: Edit the config.** In `conf/sec-edgar-local.json`, set `execution` to:

```json
  "execution": {
    "max_run_seconds": 3600,
    "dispatch_reserve_seconds": RESERVE
  }
```

Write D2's reserve integer in place of `RESERVE`. Set `runtime.release_manifest` to `/Users/lowell/Projects/sec-edgar-local/releases/sha256=<D5>/release.json`. Change nothing else.

- [ ] **Step 2: Offline preflight and hash on the D5 interpreter.**

```bash
cd /Users/lowell/Projects/sec-edgar-local
release=releases/sha256=<D5>
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -c "
from pathlib import Path
from sec_edgar_ingest.config import admit_dispatch_reserve, load_config
from sec_edgar_ingest.runtime import preflight_current
from sec_edgar_ingest.storage.contracts import deployment_binding
settings = load_config(Path('conf/sec-edgar-local.json'))
print('reserve', admit_dispatch_reserve(settings))
print('release', preflight_current(Path(settings.runtime.release_manifest)).release_id)
print('effective', settings.config_sha256)
print('binding', deployment_binding(settings))"
git diff conf/sec-edgar-local.json
```

Expected: `reserve` is D2's integer, `release` is `<D5>`, and `effective` is a new SHA-256. The diff shows exactly two changed values. `binding` holds no `execution` field (B8). Run no launcher command: `prepare_invocation` writes logs.

- [ ] **Step 3: Owner checkpoint (HUMAN).** Show the owner the diff and the Step 2 output. Ask for approval of the live-config selection. Stop until the owner answers. Log the answer as D4.

- [ ] **Step 4: Record and commit.** Append to `release.md` a section `## Live-config selection` with the commit (filled after committing), the effective-config SHA-256, the reserve, and the binding output. Then:

```bash
git add conf/sec-edgar-local.json specs/evidence/d5-release/release.md
git commit -m "chore(config): select the D5 release with the approved dispatch reserve"
```

Add the commit hash to `release.md` in the next commit (Task 11), not by amending.

---

### Task 11: Parent-spec amendments (spec §8)

**Files:**
- Modify: `specs/sec-filing-index-ingestion-spec.md` (§4.7 near :267, §4.8 table and selection paragraph near :297–322, §4.9 near :334–338)
- Modify: `specs/evidence/d5-release/release.md` (the Task 10 commit hash)

**Interfaces:**
- Consumes: D2, `<D5>`, the Task 10 effective SHA-256 and commit, and the Task 7 answer.

- [ ] **Step 1: §4.7.** Replace:

```text
A new launcher invocation creates a new result and may
continue eligible unresolved work.
```

with:

```text
A new launcher invocation creates a new result and may
continue eligible unresolved work. A workflow run stops starting members at its deadline minus
`execution.dispatch_reserve_seconds`, records each member not started as pending
(`workflow_deferred`), and writes its durable result. So a deadline deferral reports exit 3 or 4.
A member already running at that time completes. (Stage 1a, plan 4.)
```

- [ ] **Step 2: §4.8 table.** After the row `| Execution | Live maximum 3,600 seconds; launcher default 3,300 seconds. |`, add:

```text
| Dispatch reserve | `execution.dispatch_reserve_seconds=RESERVE`. Required for a new live workflow run; floor FLOOR seconds (release constant), below `max_run_seconds`. The launcher refuses a timeout at or below it. (Stage 1a, plan 4.) |
```

Write D2's integers in place of `RESERVE` and `FLOOR`.

- [ ] **Step 3: §4.8 selection.** Replace the selected-manifest code block's path line with `/Users/lowell/Projects/sec-edgar-local/releases/sha256=<D5>/release.json`. Then replace:

```text
The post-completion release-only edit produces effective-config SHA-256
`088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d`, confirmed by offline preflight.
```

with:

```text
Stage 1a (plan 4) selected the D5 release `<D5>` and added the dispatch reserve, at commit
`<Task 10 commit>`. The effective-config SHA-256 is `<Task 10 SHA-256>`, confirmed by offline preflight.
The earlier release-only edit that selected `fc68adef…` produced `088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d`.
```

Write the full release ID, commit hash and SHA-256 in place of the bracketed names.

- [ ] **Step 4: §4.9 rollback limit.** After the paragraph that ends `never substitute the new parent release.`, add (with the Task 7 answer):

```text
Release `fc68adef…` refuses the configs, receipts and child results that a D5 live run writes. Its
settings reject the unknown `execution.dispatch_reserve_seconds` key, and it reports a D5
sibling-completion receipt as `legacy_member_unresolved`, so each such run ends `incomplete`. After a
D5 live run has written to a store, selecting `fc68adef…` again for that store is unsupported. The
D5 release continues `fc68adef…`-origin pending work. (Stage 1a, plan 4;
[two-release evidence](evidence/d5-release/two-release.md).)
```

If Task 7 recorded a different answer, write that answer instead.

- [ ] **Step 5: Verify and commit.** Run:

```bash
grep -n "Stage 1a, plan 4" specs/sec-filing-index-ingestion-spec.md
```

Expected: three matches, in §4.7, the §4.8 table row and §4.9. The §4.8 selection paragraph reads "Stage 1a (plan 4)" and does not match. Then add the Task 10 commit hash to `release.md` and commit:

```bash
git add specs/sec-filing-index-ingestion-spec.md specs/evidence/d5-release/release.md
git commit -m "docs(specs): amend the parent spec for the D5 release and its limits"
```

---

## After the last task

Run the writing-plans Plan Completion Protocol, step 3a included. The `## Handoff to later stages` section must name every value the plan 2 revision must change (spec §7):

- Global Constraints: the release `<D5>`, the effective-config SHA-256, and the reserve and floor.
- The Task 1 tool's release-internal imports: re-verify `scripts/baseline-campaign.py` against `<D5>`. `workflows/results._validate_report` and `contracts.MemberResult` changed (P2).
- The Task 3 values and slice configs: regenerate `conf/stage2/*.json` with the reserve key and the D5 manifest. Every slice config needs the key, because admission refuses a keyless live config.
- The Task 4 gate: the `campaign.md` Release gate reads against the D5 release, and the stop rules read durable result fields (a deadline deferral is exit 3 or 4, never exit 5).
- The §4.8 coordination values: expected unchanged (3 requests/second, one active collector, 60/20/2-second lease policy). Confirm against the final `conf/sec-edgar-local.json`.
- Plan 3 DF6: the D5 release is built, so the platform member may now merge to `main` under plan 3's Merge gate.
- Traps: the rollback limit in §4.9. Admission refuses keyless live configs. Measurement limits are in `measurement.md`.

Remove the `stage1a-bounded-drain` worktree after the retire commit (finishing-a-development-branch).
