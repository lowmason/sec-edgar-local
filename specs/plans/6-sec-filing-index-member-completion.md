# Member-Completion Conflict Fix and the 1c Release Implementation Plan

**Status: AWAITING OWNER REVIEW (2026-10-29).** This plan authorizes no SEC request.

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task via subagent-driven-development (the default) — or executing-plans when your human partner chose inline execution at the handoff. Steps use checkbox (`- [ ]`) syntax for tracking.

> Roadmap: specs/sec-filing-index-ingestion-roadmap.md, Stage 1c — on plan completion, tick the
> stage and re-validate later stages against what shipped.

Approval of this spec authorizes no SEC request, live run or campaign. The plan 2 revision, written
against the 1c release, and its Task 4 owner gate stay the only route to live traffic.

(The two paragraphs above are the spec's §9 Rollout note, copied verbatim.)

**Goal:** Ship a reviewed native release (the 1c release) on which a finished publish Attempt with an incomplete input no longer poisons member completion, the completion conflict names its gaps, and a member whose completion check cannot pass stops before any child runs.

**Architecture:** The work has three parts.

1. In `workflows/completion.py`, a new builder makes the legacy publish call descriptor without the complete-input refusal (M1). The inventory loop of `_publish_calls` refuses an incomplete input only for a call that it keeps (M2). Every other caller keeps `_legacy_publish_call` unchanged.
2. In `workflows/processing.py`, one helper formats gaps. The `:96` conflict carries them (M3). A member whose first evaluation has no obligation and a non-retryable gap stops before dispatch (M4).
3. The 1c release is built from clean `main`, verified offline, checked against the halted store on a scratch copy, and selected in the live config at an owner checkpoint (M7, M8). The parent spec and the runbook are amended (§7).

The code lands on a feature branch in a worktree. It merges to `main` after the full gate, a whole-branch review and an owner checkpoint. The release, the replay, the live-config selection and the amendments run on `main`.

**Tech Stack:** Python 3.14 (CPython 3.14.0, macOS arm64). SQLite through `sqlite3`. Stdlib `unittest` under `packages/sec-edgar-ingest/tests/network_guard.py`. `uv` offline and locked. Installed releases under `releases/sha256=<id>/`.

**Spec:** [specs/sec-filing-index-member-completion.md](../sec-filing-index-member-completion.md) (Stage 1c, approved 2026-10-29 at `097bea1`). Parent spec: [specs/sec-filing-index-ingestion-spec.md](../sec-filing-index-ingestion-spec.md). Inputs: the [Stage 1c diagnosis](../evidence/stage1c/diagnosis/diagnosis.md), [plan 2](2-sec-filing-index-ingestion-spec.md) D12 and Handoff bullet "Task 5 halt (2026-10-29)", [completed plan 5](completed/5-sec-filing-index-per-member-cost.md).

## Global Constraints

Copied from the spec. Every task's requirements include this section.

- No SEC request, live run, or change under `data/` (spec §2). The live repair runs only in the plan 2 revision, under its own owner gate (spec §9).
- No recovery command, and no edit of a pointer, Attempt or object. The repair is a normal re-run (spec §2, §4.2).
- M6: generations, manifests, receipts, member evidence, selection (`sec-local-workflow-selection-v1`), Attempts, effective config, outcomes and exit codes do not change format. Existing receipts stay valid byte for byte. Exact replay returns identical bytes.
- Only `workflows/completion.py` and `workflows/processing.py` change in `src` (spec §4.1). `workflows/legacy.py` and the runner's evaluations (`runner.py:87`, `:204`, `:262`) stay as they are.
- M1 and M2: only the inventory loop of `_publish_calls` uses the new builder. `read_legacy_publish`, `_call_context`, `_read_document` (`completion.py:228`) and `legacy.bootstrap_legacy` (`workflows/legacy.py:160`) keep calling `_legacy_publish_call`.
- M7: the 1c release is built by `build_release` from clean committed `main`. The package version stays `0.2.0`. `uv.lock` and the requirement lines of `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` are byte-identical to the 1b build inputs, with no platform member. The 1b build revision is `50423a404fb50a959b3ca4077301117d32804cc6`. The 1b release (`9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b`), the D5 release (`aa8de1ac…`), `fc68adef…` and older releases are retained (§4.9).
- M8: the live config selects the 1c release at an owner checkpoint. `execution.dispatch_reserve_seconds` stays 1800. Offline preflight passes, and the new effective-config SHA-256 is recorded.
- No platform item. The platform workspace member stays off `main` until the 1c release is built (S2).
- Tests use stdlib `unittest` under `network_guard.py`. Write each test before its implementation (spec §5).
- The full gate is `scripts/check-sec-edgar-ingest.sh`. It takes about 75 minutes, so run it in the background.
- The F17 fixture stays deferred (S1). The `permit_expired` refusal goes to the plan 2 revision through the Handoff (spec §4.3 item 6).

Execution environment (planning facts, not spec text):

- Tasks 1–4 run on branch `stage1c-member-completion` in the worktree `/Users/lowell/Projects/sec-edgar-local/.claude/worktrees/stage1c-member-completion` (using-git-worktrees). Leave the existing worktree `.claude/worktrees/platform-stage1-1973ff` alone. A worktree has no `releases/` or `data/`. So every test and gate command in the worktree sets `SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache`. Release paths are absolute paths into the main checkout.
- Tasks 5–8 run in the main checkout `/Users/lowell/Projects/sec-edgar-local` on `main`, after the Task 4 merge.
- In a worktree, `uv run --offline --locked` cannot build an environment, and the main venv holds a `.pth` path to the main checkout's source (plan 4, Tasks 3 and 5; plan 5). So create a shadow venv once, in "Before Task 1" Step 3:

  ```bash
  WT=/Users/lowell/Projects/sec-edgar-local/.claude/worktrees/stage1c-member-completion
  /Users/lowell/.local/share/uv/python/cpython-3.14.0-macos-aarch64-none/bin/python3.14 -m venv /tmp/s1c-venv
  printf '%s\n%s\n' "$WT/packages/sec-edgar-ingest/src" /Users/lowell/Projects/sec-edgar-local/.venv/lib/python3.14/site-packages > /tmp/s1c-venv/lib/python3.14/site-packages/s1c.pth
  /tmp/s1c-venv/bin/python -I -c "import sec_edgar_ingest, pyarrow; print(sec_edgar_ingest.__file__, pyarrow.__version__)"
  printf '%s\n' '#!/tmp/s1c-venv/bin/python' 'import sys' 'from sec_edgar_ingest.cli import main' 'sys.exit(main())' > /tmp/s1c-venv/bin/sec-edgar-ingest
  chmod +x /tmp/s1c-venv/bin/sec-edgar-ingest
  mkdir -p "$WT/releases" && ln -s /Users/lowell/Projects/sec-edgar-local/releases/artifact-cache "$WT/releases/artifact-cache"
  ```

  Expected: a path under `$WT/packages/sec-edgar-ingest/src`, and `25.0.1`. If the path is in the main checkout, put the worktree line first and check again.
- Test command, from the worktree root (replace `<target>` with a module, class or test name):

  ```bash
  SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache /tmp/s1c-venv/bin/python packages/sec-edgar-ingest/tests/network_guard.py <target> -v
  ```

## Decisions

- **D1** (owner, brief, 2026-10-29): the Exit reproduction tests the real cause only. The F17 fixture stays deferred (spec S1). Applied in: Task 1, Global Constraints, After the last task (deferred items).
- **D2** (owner, brief, 2026-10-29): the platform member stays off `main` until the 1c release is built (spec S2). Applied in: Global Constraints, Task 4 Step 4, Task 5 Step 3, Handoff (platform bullet).
- **D3** (owner, brief, 2026-10-29): the approach is "fix + explain + stop", M1–M4 (spec S3). Applied in: Tasks 2 and 3.

## Defaults for owner review

Planning settled these points. Each one is plan-level: none changes what the spec requires. Each is applied in the tasks as written. The owner approves or changes each one at plan review.

- **P1 — Builder shape and name.** The builder is `completion._legacy_publish_descriptor(context, objects) -> tuple[dict, TransformedWorkset]`. It returns the descriptor and the decoded input, so the refusal needs no second read. One helper, `completion._require_complete_input(workset)`, raises today's message. `_legacy_publish_call` and the kept-call branch of the loop both call it, so the message stays the same in both places.
  - Consequence (not an M1 breach): today the complete-input check runs before the input-versions check. In the builder, the versions check comes first. So for an Attempt whose input is both incomplete and of other versions, `_legacy_publish_call` now says "legacy publish input versions differ" instead of "legacy unfinished publication has no complete publishable input". Both are `Conflict`, and every caller wraps or passes them the same way. No test asserts either message (F5). The live store has no such Attempt (diagnosis `diag3`).
  - Applied in: Task 2.
- **P2 — The 1b interpreter for §5 items 1 and 4.** The gate test builds the 1b application from its source revision `50423a4` with `support_release.origin_release`, as plan 5 P6 built the D5 origin. That keeps the gate self-contained in a worktree, which has no `releases/`. `main`'s `src` equals that revision (F1), so the application payload is the 1b payload. The spec's words "the retained 1b release interpreter (`9fa189a0…`)" are met by one extra evidence run of the same test class on the installed `releases/sha256=9fa189a0…/release.json`, through the environment variable `SEC_LOCAL_1B_RELEASE` (Task 4 Step 3). Alternative: make the installed release the only interpreter, and skip the test when it is absent. Applied in: Tasks 1 and 4.
- **P3 — Message formats.** One helper, `processing._gap_text(gaps) -> str`, joins `f'{gap.code}: {gap.message}'` with `'; '`.
  - M3: `child completion lacks all affected quarter/repair evidence: <gap text>`. When the evaluation has no gap, the message is the stock text alone.
  - M4: `member <member_id> completion check cannot pass before dispatch: <gap text of the non-retryable gaps>`.
  - A gap's code and message already pass `require_text`, and `member_id` is a hash. So each message is one line, and `error_text` returns it unchanged.
  - Applied in: Task 3.
- **P4 — The reproduction fixture.** Planning probe 2026-10-29 (F2) showed the recipe on today's code, which is the 1b source:
  - `simple_pack`, with both quarterly bodies (`full-index` QTR3 and QTR4) replaced by bodies that hold a conflicting duplicate key. The daily body stays clean. `quarter_pack(conflicting=…)` and `simple_pack(conflicting=True)` would make the daily body conflict too.
  - Standalone `discover --mode quarterly`, `collect`, `transform` (exit 7, `invalid_source`, input `complete=False` with 0 observations), then a standalone `publish` (exit 3, `incomplete`, `quarters: []`). This is the L12 2024Q1 shape.
  - Then one `daily` workflow: its daily member publishes 2026Q4 and the run ends exit 9, `state_conflict`.
  - The finished standalone Attempts also register two quarterly members through `bootstrap_legacy` (F4). They are quarantined. They sort after the daily member, so the daily member runs first.
  - Applied in: Task 1.
- **P5 — Test-first across tasks.** Task 1 writes the reproduction and repair tests before the fix. Its two 1c-side tests carry `@unittest.expectedFailure`, so Task 1's commit keeps the gate green. Task 2 removes both decorators: an unexpected success fails the run, so the removal cannot be skipped. Applied in: Tasks 1 and 2.
- **P6 — M1 byte identity uses an independent oracle.** After the refactor, `_legacy_publish_call` calls the builder, so comparing the two proves nothing. The test builds the expected descriptor from the persisted `command.json` and the Attempt context, as the 1b code builds it, and compares canonical bytes and SHA-256. It covers the three legacy publish shapes that the existing fixtures create: a finished complete publish (`test_local_workflow_contracts.py:336–349`), an unfinished one (`test_workflow_completion.py`, "ordinary public publish failure"), and the L12 shape. Applied in: Task 2.
- **P7 — The repair path that §5 item 4 observes.** The test asserts M5 without conditions: no pointer moves, the member's capture is under `already_complete`, its source is in `already_complete_sources`, and no repair record exists. It also asserts the §4.2 path: the member is not in `selection['jobs']` and gets no receipt. If only a §4.2 path assertion fails while every M5 assertion holds, change that assertion to the observed path, add a `> Deviation:` line, and name the path in `reproduction.md`. Spec §4.2 allows this. Applied in: Tasks 1 and 4.
- **P8 — Existing tests and the stop rule.** M4 can turn a run that used to dispatch and then fail at `:96` into a stop before dispatch. If an existing test now fails because of M4, stop and ask. Never weaken that test. Applied in: Task 3.

## Facts established while planning (read-only, 2026-10-29)

- **F1 — `main` equals the 1b source.** `git diff 50423a4 HEAD -- packages/sec-edgar-ingest/src uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml` is empty. Since `50423a4`, `main` changed only `specs/`, `conf/stage2/`, `scripts/baseline-campaign.py` and `tests/test_baseline_campaign.py`. The 1b release's `git_revision` is `50423a404fb50a959b3ca4077301117d32804cc6`. `pyproject.toml` has `members = ["packages/sec-edgar-ingest"]`.
- **F2 — Planning probe.** Script and output: `fixture-data/s1c-plan-probes/probe.py` and `probe.out` (git-ignored, temporary stores only). On today's code:
  - The P4 recipe gives: transform exit 7 (`invalid_source`, `complete=False`, 0 observations, 2 failures); publish exit 3, Attempt result `incomplete` with `quarters: []`; no pointer; then `daily` exit 9, `state_conflict`, `result_ref` null; pointer 2026Q4 moved; the daily member evaluates with the exact gap "ordinary publication authority inventory uncertain: legacy unfinished publication has no complete publishable input" (retryable false), and has no `WorkflowMemberResult` row.
  - With the M2 rule patched in memory, the same daily member evaluates complete with no obligation and no gap.
  - With `EvidenceFixture`: a transform of a conflicting quarterly body gives `complete=False` and 0 observations. A standalone publish of it finishes `incomplete` with `quarters: []`, and `_publish_calls` raises today's inventory message. A standalone publish with `sec_edgar_ingest.cli.run_publish` patched to raise `PublicationRepairPending([], [], [])` exits 9 and leaves the Attempt result null.
  - The repair-authority path is `worksets/sec/workflow-repair-authority/call-sha256=<key>/obligation.json`.
- **F3 — `WorkflowMembers.completed` raises on a poisoned store.** It calls `outstanding_repairs`, which runs `_publish_calls`. Tests on a 1b-written store count `WorkflowMemberResult` rows directly.
- **F4 — `bootstrap_legacy` registers members from finished standalone Attempts.** In the probe, the `daily` run had three members: the daily 2026-10-01 source and the quarterly 2026Q3 and 2026Q4 sources of the standalone chain.
- **F5 — No test asserts the messages that change.** `grep` finds no test that asserts "child completion lacks", "authority inventory uncertain", "no complete publishable input" or "input versions differ". `test_local_workflow_contracts.py:346` calls `_legacy_publish_call` on an unfinished complete Attempt.
- **F6 — The campaign tool.** `scripts/baseline-campaign.py` imports `workflows.contracts`, `workflows.results` (`_read`, `_validate_report`), `etl.reader`, `etl.state`, `discovery`, `config` and `storage`. It does not import `completion` or `processing` directly. The campaign stop rules read the workflow `outcome` (`campaign.md`, rule 3), not the error text.
- **F7 — Live config.** `conf/sec-edgar-local.json` selects `9fa189a0…`. Its effective-config SHA-256 is `2512fdcb999a302d93de84315d45e4e44d0bb942d5165698b64c371fc42b5be5` (plan 2 Revision 2; parent spec §4.8). The reserve is 1800 s, and the floor is 480 s.
- **F8 — Gate baseline.** The 1b gate ran 1108 tests in 71 modules. `test_baseline_campaign.py` has gained 4 tests since (11 to 15), so `main` should run about 1112 tests in 71 modules. This plan adds two modules.
- **F9 — `releases/`** holds `49b7a2ed…`, `900952a8…`, `9fa189a0…`, `aa8de1ac…`, `d718ae5f…`, `fc68adef…`, `artifact-cache` and `task14-guard-proofs`.
- **F10 — The three members that appear as already complete** (diagnosis `diag8`; full IDs from `outputs/live-data-before.sha256`):
  - `3554e8efb093532572ea5a35a1bf627a175784f0eac74b92e0777cb2e5d461ff`, daily 2026-07-01, the halted member of invocation 1 (source `924fd5f5b380e8a8603bab21b91edcd9408962b3a25fe812f067b25777063d58`).
  - `dc790624e85455feb79174c5d0ccbcab31c2b54c2e8b9de01ff503b551270a30`, daily 2026-10-14 (L12).
  - `00c1f46d1f14a72ba1a949f89ff9bc93cb0b95109ace8de6e2799b40af95a4c6`, daily 2026-10-15 (L12).

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/completion.py` | `_legacy_publish_descriptor` (M1), `_require_complete_input`, `_legacy_publish_call`, the `_publish_calls` legacy loop (M2) | 2 |
| `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py` | `_gap_text`, the stop before dispatch (M4), the `:96` gap text (M3) | 3 |
| `packages/sec-edgar-ingest/tests/support_release.py` | `ONE_B_REVISION` | 1 |
| `packages/sec-edgar-ingest/tests/test_release_1c.py` (new) | §5 items 1 and 4, on the 1b interpreter and the 1c code | 1, 2 |
| `packages/sec-edgar-ingest/tests/test_member_completion.py` (new) | §5 items 2, 3, 5 and 6 | 2, 3 |
| `specs/evidence/stage1c/gate.md`, `reproduction.md` (new) | Branch gate, §5 items 1 and 4 | 4 |
| `specs/evidence/stage1c/release.md` (new), `replay/` (new) | Spec §6 items 2–7 | 5–8 |
| `conf/sec-edgar-local.json` | M8 | 7 |
| `specs/sec-filing-index-ingestion-spec.md`, `docs/runbooks/local-recovery.md` | §7 amendments | 8 |

---

## Before Task 1

- [ ] **Step 1: Plan review (HUMAN).** The owner reviews the plan and answers P1–P8. Log the answer as D4 in `## Decisions`, in the owner's words. Apply each plan-level change the owner asks for, and re-run the writing-plans Self-Review on what changed.
- [ ] **Step 2: Commit the review changes on `main`.** The plan itself was committed on `main` at planning. The worktree is cut from `main`, so commit the reviewed plan, with D4, before Step 3:

```bash
cd /Users/lowell/Projects/sec-edgar-local
git add specs/plans/6-sec-filing-index-member-completion.md
git commit -m "docs(plans): record the owner review of plan 6"
```

- [ ] **Step 3: Create the worktree and the shadow venv.** Use the using-git-worktrees skill for branch `stage1c-member-completion` at `.claude/worktrees/stage1c-member-completion`. Then run the shadow-venv commands in Global Constraints, "Execution environment".

---

### Task 1: Reproduction and repair tests (spec §5 items 1 and 4)

**Files:**
- Modify: `packages/sec-edgar-ingest/tests/support_release.py` (after `D5_REVISION`)
- Create: `packages/sec-edgar-ingest/tests/test_release_1c.py`

**Interfaces:**
- Consumes: `support_release.origin_release(project, cache, revision=…)`, `support_release.proof_releases(project, cache)`, `support_workflows.CommandHarness`, `simple_pack`, `replace_pack_body`, `idx`, `BASE`.
- Produces: `support_release.ONE_B_REVISION`; `test_release_1c.MemberCompletionReleaseTests`, whose two 1c-side tests carry `@unittest.expectedFailure` until Task 2.

- [ ] **Step 1: Add the 1b revision constant.** In `support_release.py`, after the `D5_REVISION` line, add:

```python
ONE_B_REVISION = '50423a404fb50a959b3ca4077301117d32804cc6'  # source revision of the 1b release 9fa189a0…
```

- [ ] **Step 2: Write the tests.** Create `packages/sec-edgar-ingest/tests/test_release_1c.py`:

```python
"""Stage 1c §5 items 1 and 4: the member-completion conflict on the 1b release, and its repair on the 1c code.

The store has the shape of the live store at invocation 1: a finished standalone publish Attempt whose
input workset is incomplete (the L12 2024Q1 shape), then a daily workflow member that publishes.
"""
from network_guard import install
install()

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from support import fixture_settings
from support_process import CheckedRunner
from support_workflows import BASE, CommandHarness, idx, replace_pack_body, simple_pack
from sec_edgar_ingest.config import Settings
from sec_edgar_ingest.etl.contracts import decode_transformed
from sec_edgar_ingest.models import canonical_json, to_mapping_value
from sec_edgar_ingest.runtime import isolated_environment, native_python_argv
from sec_edgar_ingest.workflows.completion import evaluate_member
from sec_edgar_ingest.workflows.contracts import COMPLETE
from sec_edgar_ingest.workflows.members import WorkflowMembers
from sec_edgar_ingest.workflows.results import read_workflow_result

TODAY = date(2026, 10, 7)


class MemberCompletionReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support_release import ONE_B_REVISION, origin_release, proof_releases
        from sec_edgar_ingest.runtime import preflight
        project = Path(__file__).resolve().parents[3]
        cache = project / 'releases/artifact-cache'
        # Plan 6 P2: the gate builds the 1b application from its revision. The evidence run sets
        # SEC_LOCAL_1B_RELEASE to the installed release.json of 9fa189a0… instead.
        installed = os.environ.get('SEC_LOCAL_1B_RELEASE')
        cls.one_b = preflight(Path(installed)) if installed else origin_release(project, cache, revision=ONE_B_REVISION)
        _, cls.current = proof_releases(project, cache)

    def scratch(self):
        """A temporary root whose cleanup runs after the harness stores close (addCleanup is LIFO)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def poisoned(self):
        """A store with a finished standalone publish whose input is incomplete, and a clean daily source."""
        root = self.scratch()
        pack = simple_pack(root / 'pack')
        for quarter, day in ((3, '2026-07-01'), (4, '2026-10-01')):
            archive = f'edgar/data/123456/0000123456-26-00000{quarter}.txt'
            rows = (('123456', 'Example', '10-K', day, archive), ('123456', 'Changed', '10-K', day, archive))
            replace_pack_body(pack, BASE + f'full-index/2026/QTR{quarter}/master.zip', idx(rows, 'quarterly'))
        settings = fixture_settings(backfill={'start_quarter': '2026Q3', 'end_quarter': 'open'},
            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        h = CommandHarness(root, pack, settings)
        self.addCleanup(h.close)
        code, found = h.invoke('discover', ('--mode', 'quarterly', '--discovery-id', 'l12-shape'), run='l12-find')
        self.assertEqual(code, 0, h.calls[-1])
        code, collected = h.invoke('collect', ('--workset', found['source_workset_ref']), run='l12-collect')
        self.assertEqual(code, 0, h.calls[-1])
        code, transformed = h.invoke('transform', ('--workset', collected['snapshot_workset_ref']), run='l12-transform')
        self.assertEqual((code, transformed['outcome']), (7, 'invalid_source'), h.calls[-1])
        ref = transformed['transformed_workset_ref']
        workset = decode_transformed(h.objects.read(ref))
        self.assertEqual((workset.complete, len(workset.observations)), (False, 0))
        code, published = h.invoke('publish', ('--workset', ref), run='l12-publish')
        self.assertEqual((code, published['outcome']), (3, 'incomplete'), h.calls[-1])
        attempt = next(r.to_mapping()['value'] for r in h.store.scan('Attempt', {})
                       if r.to_mapping()['value']['context']['run_id'] == 'l12-publish')
        self.assertEqual((attempt['result']['outcome'], attempt['result']['quarters']), ('incomplete', []))
        self.assertEqual(self.pointers(h), [])
        return h

    def release_run(self, h, release, run_id):
        """One `daily` workflow parent in the release's own installed interpreter."""
        value = h.settings.to_mapping()
        value['runtime'] = {'kind': 'native', 'release_manifest': str(release.directory / 'release.json')}
        config = h.root / (run_id + '.json')
        config.write_bytes(canonical_json(to_mapping_value(Settings.from_mapping(value).to_mapping())))
        deadline = datetime.now(timezone.utc) + timedelta(seconds=1800)
        argv = [*native_python_argv(release.python), '-m', 'sec_edgar_ingest', 'daily',
                '--config', str(config), '--run-id', run_id, '--execution-id', 'manual', '--attempt-id', 'a',
                '--deadline', deadline.isoformat(), '--today', TODAY.isoformat(), '--fixture-pack', str(h.pack)]
        result = CheckedRunner()(release.python, argv, deadline=deadline, environ=isolated_environment())
        return result.returncode, json.loads(result.stdout.decode().splitlines()[-1])

    def versions(self, h):
        return h.settings.etl.parser_version, h.settings.etl.schema_version

    def pointers(self, h):
        return [row.to_mapping() for row in h.store.scan('QuarterPublication', {})]

    def quarters(self, h):
        return sorted(row.to_mapping()['value']['quarter'] for row in h.store.scan('QuarterPublication', {}))

    def receipts(self, h, value):
        """Receipt rows, counted directly: `WorkflowMembers.completed` raises on a poisoned store (plan 6 F3)."""
        parser, schema = self.versions(h)
        return len(tuple(h.store.scan('WorkflowMemberResult', {'member_id': value['member_id'],
                                                               'parser_version': parser, 'schema_version': schema})))

    def daily_member(self, h):
        values = [v for v in WorkflowMembers(h.store, h.objects).inventory()[0] if v['source']['kind'] == 'daily']
        self.assertEqual(len(values), 1, values)
        return values[0]

    def test_the_1b_release_halts_after_its_publish_moves_a_pointer(self):
        """§5 item 1, first half: on the 1b release the member's publish moves 2026Q4, then the run halts."""
        h = self.poisoned()
        code, message = self.release_run(h, self.one_b, 'one-b')
        self.assertEqual((code, message['outcome'], message['result_ref']), (9, 'state_conflict', None), message)
        value = self.daily_member(h)
        self.assertEqual(self.quarters(h), ['2026Q4'])
        self.assertEqual(self.receipts(h, value), 0)

    @unittest.expectedFailure  # Plan 6 Task 2 removes this decorator.
    def test_the_1c_code_completes_the_member_on_the_same_store(self):
        """§5 item 1, second half: the 1c code completes the member with all affected quarter evidence."""
        h = self.poisoned()
        code, message = self.release_run(h, self.current, 'one-c')
        self.assertNotEqual(code, 9, message)
        report = read_workflow_result(message['result_ref'], h.store, h.objects)
        value = self.daily_member(h)
        member = next(m for m in report.members if m.member_id == value['member_id'])
        self.assertIn(member.outcome, COMPLETE)
        self.assertEqual(self.receipts(h, value), 1)
        self.assertEqual(self.quarters(h), ['2026Q4'])
        capture = next(c for c in report.intent['completion_captures'] if c['member']['member_id'] == value['member_id'])
        self.assertEqual(capture['affected_quarters'], ['2026Q4'])
        self.assertEqual([q['quarter'] for q in capture['quarters']], ['2026Q4'])

    @unittest.expectedFailure  # Plan 6 Task 2 removes this decorator.
    def test_a_1c_rerun_completes_the_halted_member_and_moves_no_pointer(self):
        """§5 item 4 and M5: the store that the 1b release left, re-run on the 1c code."""
        h = self.poisoned()
        code, _ = self.release_run(h, self.one_b, 'one-b')
        self.assertEqual(code, 9)
        value = self.daily_member(h)
        pointers = self.pointers(h)
        self.assertEqual(len(pointers), 1)
        self.assertEqual(self.receipts(h, value), 0)
        code, message = self.release_run(h, self.current, 'repair')
        self.assertNotEqual(code, 9, message)
        # M5: no pointer moves a second time, and the member's capture is under already_complete.
        self.assertEqual(self.pointers(h), pointers)
        report = read_workflow_result(message['result_ref'], h.store, h.objects)
        self.assertIn(value['source']['source_id'], report.intent['already_complete_sources'])
        selection = json.loads(h.objects.read(report.intent['selection']['ref']))
        self.assertIn(value['member_id'], [c['member']['member_id'] for c in selection['already_complete']])
        self.assertEqual(tuple(h.store.scan('WorkflowRepairObligation', {})), ())
        self.assertFalse((Path(h.settings.storage.root) / 'objects/worksets/sec/workflow-repair-authority').exists())
        self.assertTrue(evaluate_member(value, *self.versions(h), h.store, h.objects).complete)
        # Spec §4.2 path (plan 6 P7): the member is selected as complete, so no child runs and no receipt is written.
        self.assertNotIn(value['member_id'], [job['member']['member_id'] for job in selection['jobs']])
        self.assertNotIn(value['member_id'], [m.member_id for m in report.members])
        self.assertEqual(self.receipts(h, value), 0)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 3: Run the module.** It builds the 1b origin release and the proof releases first (several minutes).

Run: the test command with `test_release_1c`.
Expected: `OK (expected failures=2)`. `test_the_1b_release_halts_after_its_publish_moves_a_pointer` passes, because today's code is the 1b code. If a `poisoned` assertion fails, the fixture differs from the planning probe (F2). Stop and report the failing line. Do not change the fixture to make the 1b test pass.

- [ ] **Step 4: Commit.**

```bash
git add packages/sec-edgar-ingest/tests/support_release.py packages/sec-edgar-ingest/tests/test_release_1c.py
git commit -m "test: reproduce the member-completion conflict on the 1b release"
```

---

### Task 2: The inventory fix (M1, M2; spec §5 items 2 and 3)

**Files:**
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/completion.py:451–478` (`_legacy_publish_call`) and `:551–566` (the legacy loop of `_publish_calls`)
- Create: `packages/sec-edgar-ingest/tests/test_member_completion.py`
- Modify: `packages/sec-edgar-ingest/tests/test_release_1c.py` (remove the two `@unittest.expectedFailure` lines)

**Interfaces:**
- Consumes: `support_workflow_evidence.EvidenceFixture` (`invoke`, `snapshot_input`, `revised_member`, `config`, `workflow`, `store`, `objects`, `value`), `quarterly_bytes`.
- Produces: `completion._legacy_publish_descriptor(context, objects) -> tuple[dict, TransformedWorkset]`; `completion._require_complete_input(workset) -> None`; `_legacy_publish_call(context, objects) -> dict` with unchanged signature. In `test_member_completion.py`: the module constants `INVENTORY`, `REFUSAL`, `STOCK` and the helper `conflicting_bytes(day)`, which Task 3 reuses.

- [ ] **Step 1: Write the failing tests.** Create `packages/sec-edgar-ingest/tests/test_member_completion.py`:

```python
"""Stage 1c M1–M4: the legacy publish inventory, the completion conflict text and the stop before dispatch."""
from network_guard import install
install()

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from support_workflow_evidence import EvidenceFixture, quarterly_bytes
from sec_edgar_ingest.cli import main
from sec_edgar_ingest.etl.commands import PublicationRepairPending
from sec_edgar_ingest.etl.contracts import decode_transformed
from sec_edgar_ingest.models import RunContext, canonical_json, to_mapping_value
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows import completion
from sec_edgar_ingest.workflows.completion import evaluate_member
from sec_edgar_ingest.workflows.contracts import LOCAL_CONTRACT

INVENTORY = 'ordinary publication authority inventory uncertain: '
REFUSAL = 'legacy unfinished publication has no complete publishable input'
STOCK = 'child completion lacks all affected quarter/repair evidence'


def conflicting_bytes(day):
    """A quarterly body whose two rows share one key with different values, so its transform is quarantined."""
    body = ('CIK|Company Name|Form Type|Date Filed|Filename\r\n-----\r\n'
            f'123456|A|10-K|{day}|edgar/data/123456/a.txt\r\n'
            f'123456|B|10-K|{day}|edgar/data/123456/a.txt\r\n').encode()
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w') as archive:
        info = zipfile.ZipInfo('master.idx', (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, body)
    return target.getvalue()


def call_key(call):
    return hashlib.sha256(canonical_json(to_mapping_value(call))).hexdigest()


def expected_descriptor(context, objects):
    """The legacy descriptor as the 1b code builds it, from the persisted command (plan 6 P6 oracle)."""
    result_ref = f'runs/sec/{context.run_id}/publish/{context.attempt_id}/result.json'
    frozen = json.loads(objects.read(result_ref.rsplit('/', 1)[0] + '/command.json'))
    return {'contract_version': LOCAL_CONTRACT, 'format_version': 'sec-local-workflow-legacy-publish-v1',
            'context': context.to_mapping(), 'intent': frozen['intent'], 'input_ref': frozen['intent']['workset'],
            'result_ref': result_ref}


class Rewritten:
    """An object-store view that returns other bytes for one path."""

    def __init__(self, objects, path, body):
        self.objects, self.path, self.body = objects, path, body

    def read(self, path):
        return self.body if path == self.path else self.objects.read(path)

    def __getattr__(self, name):
        return getattr(self.objects, name)


class WithObligation:
    """A state-store view that holds a WorkflowRepairObligation row under one call key."""

    def __init__(self, store, key):
        self.store, self.key = store, key

    def get(self, kind, key):
        if (kind, key) == ('WorkflowRepairObligation', self.key):
            return object()
        return self.store.get(kind, key)

    def __getattr__(self, name):
        return getattr(self.store, name)


class LegacyInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = EvidenceFixture(Path(self.temp.name) / '.fixture-state')
        self.addCleanup(self.f.close)

    def evaluate(self):
        return evaluate_member(self.f.value, self.f.workflow.parser_version, self.f.workflow.schema_version,
                               self.f.store, self.f.objects)

    def transform(self, body, seconds=0):
        _, _, result = self.f.invoke('transform', self.f.snapshot_input(body, seconds))
        return result.transformed_workset_ref

    def standalone_publish(self, workset_ref, run_id, patches=()):
        """A public `publish` command outside any workflow: it leaves a legacy publish Attempt."""
        arguments = ['publish', '--config', str(self.f.config), '--run-id', run_id,
                     '--execution-id', run_id + '-execution', '--attempt-id', run_id + '-publish',
                     '--deadline', self.f.workflow.deadline.isoformat(), '--today', '2026-10-06',
                     '--workset', workset_ref]
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = main(arguments)
        row = next(r for r in self.f.store.scan('Attempt', {}) if r.value['context']['run_id'] == run_id)
        value = row.to_mapping()['value']
        return code, RunContext.from_mapping(value['context']), value

    def unfinished(self):
        return (patch('sec_edgar_ingest.cli.run_publish', side_effect=PublicationRepairPending([], [], [])),)

    def finished_incomplete(self):
        """The L12 2024Q1 shape: a finished publish whose input holds no observation."""
        ref = self.transform(conflicting_bytes('2026-07-01'))
        workset = decode_transformed(self.f.objects.read(ref))
        self.assertEqual((workset.complete, workset.observations), (False, ()))
        code, context, value = self.standalone_publish(ref, 'l12-shape')
        self.assertEqual((code, value['result']['outcome'], value['result']['quarters']), (3, 'incomplete', []))
        return ref, context

    def publish_member(self):
        """A later revision of the member publishes through the checked child, as invocation 1 did."""
        self.f.revised_member()
        ref = self.transform(quarterly_bytes('2026-07-01'), seconds=1)
        code, _, _ = self.f.invoke('publish', ref)
        self.assertEqual(code, 0)

    def test_the_descriptor_bytes_are_unchanged_for_accepted_attempts(self):
        """§5 item 2 (M1): for each accepted legacy shape, the builder's bytes and call key equal the 1b bytes."""
        complete = self.transform(quarterly_bytes('2026-07-01'))
        _, finished, _ = self.standalone_publish(complete, 'accepted-finished')
        self.f.revised_member()
        changed = self.transform(quarterly_bytes('2026-07-01', 'Changed'), seconds=1)
        _, unfinished, value = self.standalone_publish(changed, 'accepted-unfinished', self.unfinished())
        self.assertIsNone(value['result'])
        for context in (finished, unfinished):
            with self.subTest(run=context.run_id):
                expected = expected_descriptor(context, self.f.objects)
                built, workset = completion._legacy_publish_descriptor(context, self.f.objects)
                self.assertTrue(workset.complete)
                self.assertEqual(canonical_json(to_mapping_value(built)), canonical_json(to_mapping_value(expected)))
                self.assertEqual(call_key(built), call_key(expected))
                self.assertEqual(call_key(completion._legacy_publish_call(context, self.f.objects)), call_key(expected))

    def test_the_builder_does_not_refuse_an_incomplete_input(self):
        """M1: the builder builds the L12 shape. `_legacy_publish_call` still refuses it with today's message."""
        _, context = self.finished_incomplete()
        built, workset = completion._legacy_publish_descriptor(context, self.f.objects)
        self.assertFalse(workset.complete)
        self.assertEqual(canonical_json(to_mapping_value(built)),
                         canonical_json(to_mapping_value(expected_descriptor(context, self.f.objects))))
        with self.assertRaisesRegex(Conflict, f'^{REFUSAL}$'):
            completion._legacy_publish_call(context, self.f.objects)

    def test_a_finished_publish_with_an_incomplete_input_is_not_kept(self):
        """§5 item 3 (M2): the inventory builds it, does not keep it, and the member completes."""
        ref, _ = self.finished_incomplete()
        self.assertNotIn(ref, [call['input_ref'] for call in completion._publish_calls(self.f.store, self.f.objects)])
        self.publish_member()
        evaluation = self.evaluate()
        self.assertTrue(evaluation.complete, evaluation.gaps)
        self.assertEqual((evaluation.obligations, evaluation.gaps), ((), ()))

    def test_an_unfinished_publish_with_an_incomplete_input_is_kept_and_refused(self):
        """§5 item 3 and spec §4.3 item 1: a kept call with an incomplete input still raises today's message."""
        ref = self.transform(conflicting_bytes('2026-07-01'))
        _, _, value = self.standalone_publish(ref, 'unfinished-incomplete', self.unfinished())
        self.assertIsNone(value['result'])
        with self.assertRaisesRegex(Conflict, f'^{INVENTORY}{REFUSAL}$'):
            completion._publish_calls(self.f.store, self.f.objects)

    def test_a_repair_record_keeps_a_finished_incomplete_call_and_refuses_it(self):
        """§5 item 3: a WorkflowRepairObligation row or a repair authority keeps the call, and it is refused."""
        _, context = self.finished_incomplete()
        key = call_key(expected_descriptor(context, self.f.objects))
        with self.subTest('WorkflowRepairObligation row'), self.assertRaisesRegex(Conflict, f'^{INVENTORY}{REFUSAL}$'):
            completion._publish_calls(WithObligation(self.f.store, key), self.f.objects)

        def authority(call_sha256, objects):
            return {'call_sha256': call_sha256} if call_sha256 == key else None
        with self.subTest('repair authority'), patch.object(completion, '_read_repair_authority', side_effect=authority), \
                self.assertRaisesRegex(Conflict, f'^{INVENTORY}{REFUSAL}$'):
            completion._publish_calls(self.f.store, self.f.objects)

    def test_a_changed_command_or_input_address_is_still_uncertain(self):
        """§5 item 3 and spec §4.3 item 2: every other builder check still runs on a call that is not kept."""
        _, context = self.finished_incomplete()
        command_path = f'runs/sec/{context.run_id}/publish/{context.attempt_id}/command.json'
        frozen = json.loads(self.f.objects.read(command_path))
        workset_path = frozen['intent']['workset']
        frozen['intent']['force'] = 'changed'
        changed_command = Rewritten(self.f.objects, command_path, canonical_json(to_mapping_value(frozen)))
        with self.subTest('command'), \
                self.assertRaisesRegex(Conflict, f'^{INVENTORY}legacy publish frozen intent differs$'):
            completion._publish_calls(self.f.store, changed_command)
        self.f.revised_member()
        other = self.transform(quarterly_bytes('2026-07-01'), seconds=1)
        changed_input = Rewritten(self.f.objects, workset_path, self.f.objects.read(other))
        with self.subTest('input address'), \
                self.assertRaisesRegex(Conflict, f'^{INVENTORY}legacy publish transformed input address differs$'):
            completion._publish_calls(self.f.store, changed_input)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run them to verify the expected failures.**

Run: the test command with `test_member_completion`.
Expected: `test_the_descriptor_bytes_are_unchanged_for_accepted_attempts` and `test_the_builder_does_not_refuse_an_incomplete_input` fail with `AttributeError: … has no attribute '_legacy_publish_descriptor'`. `test_a_finished_publish_with_an_incomplete_input_is_not_kept` fails with `Conflict: ordinary publication authority inventory uncertain: legacy unfinished publication has no complete publishable input`. The other three tests pass, because they guard behavior that stays.

- [ ] **Step 3: Implement M1.** In `completion.py`, replace the whole `_legacy_publish_call` function (`:451–478`) with:

```python
def _legacy_publish_descriptor(context, objects):
    """Build the legacy publish call and read its input, without the complete-input refusal (Stage 1c, M1)."""
    if context.command != 'publish':
        raise Conflict('legacy repair context is not a publish command')
    settings = Settings.from_mapping(context.to_mapping()['effective_config'])
    if context.pinned_on is None or pin_context(settings, context, context.pinned_on)[0] != context:
        raise Conflict('legacy publish context is not exactly pinned')
    path = result_path(context)
    command_path = path.rsplit('/', 1)[0] + '/command.json'
    body = objects.read(command_path)
    frozen = parse_json(body)
    if (not isinstance(frozen, dict) or set(frozen) != {'context', 'intent'}
            or canonical_json(to_mapping_value(frozen)) != body or frozen['context'] != context.to_mapping()):
        raise Conflict('legacy publish frozen command differs from exact Attempt context')
    intent = frozen['intent']
    if (not isinstance(intent, dict) or set(intent) != {'command', 'today', 'workset', 'force'}
            or intent['command'] != 'publish' or intent['force'] is not None
            or intent['today'] not in (None, context.pinned_on.isoformat())):
        raise Conflict('legacy publish frozen intent differs')
    workset = decode_transformed(objects.read(intent['workset']))
    if transformed_ref(workset) != intent['workset']:
        raise Conflict('legacy publish transformed input address differs')
    if (workset.context.parser_version, workset.context.schema_version) != (
            context.parser_version, context.schema_version):
        raise Conflict('legacy publish input versions differ')
    call = {'contract_version': LOCAL_CONTRACT, 'format_version': LEGACY_PUBLISH_FORMAT, 'context': context.to_mapping(),
            'intent': intent, 'input_ref': intent['workset'], 'result_ref': path}
    return call, workset


def _require_complete_input(workset):
    if not workset.complete:
        raise Conflict('legacy unfinished publication has no complete publishable input')


def _legacy_publish_call(context, objects):
    call, workset = _legacy_publish_descriptor(context, objects)
    _require_complete_input(workset)
    return call
```

- [ ] **Step 4: Implement M2.** In `_publish_calls`, replace the body of the legacy loop's `try` block:

```python
            context = RunContext.from_mapping(value['context'])
            if context.command != 'publish' or result_path(context) in checked_paths:
                continue
            call = _legacy_publish_call(context, objects)
            _transformed_input(call['input_ref'], None, objects)
            call_key = hashlib.sha256(canonical_json(to_mapping_value(call))).hexdigest()
            if (value['result'] is None
                    or store.get('WorkflowRepairObligation', call_key) is not None
                    or _read_repair_authority(call_key, objects) is not None):
                legacy.append(call)
```

with:

```python
            context = RunContext.from_mapping(value['context'])
            if context.command != 'publish' or result_path(context) in checked_paths:
                continue
            call, workset = _legacy_publish_descriptor(context, objects)
            _transformed_input(call['input_ref'], None, objects)
            call_key = hashlib.sha256(canonical_json(to_mapping_value(call))).hexdigest()
            # Stage 1c (M2): only a kept call must have a complete input. A finished Attempt with an
            # incomplete input and no repair record moved no pointer, so it is not an obligation.
            if (value['result'] is None
                    or store.get('WorkflowRepairObligation', call_key) is not None
                    or _read_repair_authority(call_key, objects) is not None):
                _require_complete_input(workset)
                legacy.append(call)
```

The `except` clause stays, so a refusal keeps today's wrapped message.

- [ ] **Step 5: Run the unit tests.**

Run: the test command with `test_member_completion`.
Expected: 6 tests, `OK`.

- [ ] **Step 6: Remove the expected-failure markers.** In `test_release_1c.py`, delete both lines `    @unittest.expectedFailure  # Plan 6 Task 2 removes this decorator.`.

Run: the test command with `test_release_1c`.
Expected: 3 tests, `OK`. If only a §4.2 path assertion of `test_a_1c_rerun_completes_the_halted_member_and_moves_no_pointer` fails while every M5 assertion before it passes, apply P7: change that assertion to the observed path, and add a `> Deviation:` line under this step.

- [ ] **Step 7: Run the neighbors.**

Run: the test command with `test_workflow_completion test_workflow_legacy test_local_workflow_contracts test_workflow_processing test_release_origin`.
Expected: `OK`. These modules exercise the other callers of `_legacy_publish_call`.

- [ ] **Step 8: Commit.**

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/completion.py packages/sec-edgar-ingest/tests/test_member_completion.py packages/sec-edgar-ingest/tests/test_release_1c.py
git commit -m "fix(workflows): keep a finished publish with an incomplete input out of the repair inventory"
```

---

### Task 3: The gap text and the stop before dispatch (M3, M4; spec §5 items 5 and 6)

**Files:**
- Modify: `packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py:20–30` (`process_member` start), `:94–96` (the completion conflict)
- Modify: `packages/sec-edgar-ingest/tests/test_member_completion.py` (new class `ProcessMemberTests`, new imports)

**Interfaces:**
- Consumes: `test_member_completion.STOCK`; `support_process.checked_dispatcher`, `checked_clock`, `checked_fault`; `support_workflows.CommandHarness`, `simple_pack`.
- Produces: `processing._gap_text(gaps) -> str`. The M3 and M4 message formats of P3.

- [ ] **Step 1: Write the failing tests.** In `test_member_completion.py`, add these imports after the existing ones:

```python
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from support_process import checked_clock, checked_dispatcher, checked_fault
from support_workflows import CommandHarness, simple_pack
from sec_edgar_ingest.config import pin_context
from sec_edgar_ingest.models import Error, error_text, require_text
from sec_edgar_ingest.runtime import configured_descriptor
from sec_edgar_ingest.workflows.contracts import CompletionEvaluation
from sec_edgar_ingest.workflows.processing import process_member
from sec_edgar_ingest.workflows.provenance import project_member
from sec_edgar_ingest.worksets import decode_source_workset
```

Then add this class before `if __name__ == '__main__':`:

```python
class ProcessMemberTests(unittest.TestCase):
    EVALUATE = 'sec_edgar_ingest.workflows.processing.evaluate_member'

    def scratch(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def prepare(self):
        """One fresh daily member, as in test_workflow_processing.ProcessingTests.prepare."""
        root = self.scratch()
        h = CommandHarness(root, simple_pack(root / 'pack'))
        self.addCleanup(h.close)
        now = datetime.now(timezone.utc)
        context = RunContext('processing', 'manual', 'daily', 'a', h.settings.etl.parser_version,
            h.settings.etl.schema_version, h.settings.config_sha256, now, now + timedelta(seconds=1800), 'daily',
            runtime=configured_descriptor(h.settings), format_version='sec-local-run-context-v1')
        context = pin_context(h.settings, context, date(2026, 10, 7))[0]
        dispatcher = checked_dispatcher(context, h.settings, h.pack, root, h.store, h.objects)
        found = dispatcher.execute('discover', 'discover', h.settings,
                                   ('--mode', 'daily', '--discovery-id', 'processing-daily'))
        parent = decode_source_workset(h.objects.read(found.result.source_workset_ref))
        value = project_member(found.result.source_workset_ref, parent.members[0].source_id, h.store, h.objects)
        return h, context, dispatcher, value

    def gap(self, code, message, retryable, value):
        return Error(code, message, retryable, value['source']['source_id'],
                     {'type': 'Conflict'} if code == 'state_conflict' else {})

    def test_the_completion_conflict_names_each_gap_in_order(self):
        """§5 item 5 (M3): one line, the stock text, then each gap's code and message in order."""
        h, context, dispatcher, value = self.prepare()
        gaps = (self.gap('publication_pending', 'affected quarter has no publication', True, value),
                self.gap('state_conflict', INVENTORY + REFUSAL, False, value))
        seen = []

        def second_incomplete(*args):
            seen.append(args)
            return evaluate_member(*args) if len(seen) == 1 else CompletionEvaluation(False, None, (), gaps)
        with patch(self.EVALUATE, side_effect=second_incomplete), self.assertRaises(Conflict) as raised:
            process_member(value, context, dispatcher, h.store, h.objects)
        expected = (f'{STOCK}: publication_pending: affected quarter has no publication; '
                    f'state_conflict: {INVENTORY}{REFUSAL}')
        self.assertIs(type(raised.exception), Conflict)
        self.assertEqual(str(raised.exception), expected)
        self.assertEqual(error_text(raised.exception), expected)
        require_text(expected, 'message')
        self.assertEqual(len(seen), 2)

    def test_a_non_retryable_gap_stops_the_member_before_dispatch(self):
        """§5 item 6 (M4): no child runs and no pointer moves. Only the non-retryable gaps are named."""
        h, context, dispatcher, value = self.prepare()
        gaps = (self.gap('state_conflict', 'first fixture conflict', False, value),
                self.gap('publication_pending', 'affected quarter has no publication', True, value),
                self.gap('state_conflict', 'second fixture conflict', False, value))
        dispatched = []
        with patch(self.EVALUATE, return_value=CompletionEvaluation(False, None, (), gaps)), \
                patch.object(dispatcher, 'execute', side_effect=lambda *args: dispatched.append(args)), \
                self.assertRaises(Conflict) as raised:
            process_member(value, context, dispatcher, h.store, h.objects)
        self.assertEqual(str(raised.exception),
                         f"member {value['member_id']} completion check cannot pass before dispatch: "
                         'state_conflict: first fixture conflict; state_conflict: second fixture conflict')
        self.assertEqual(dispatched, [])
        self.assertEqual(tuple(h.store.scan('QuarterPublication', {})), ())

    def test_retryable_gaps_dispatch_as_today(self):
        """§5 item 6 (M4): a member that starts with only retryable gaps runs its children."""
        h, context, dispatcher, value = self.prepare()
        pending = (self.gap('transform_pending', 'member has no current Processing identity', True, value),)
        seen = []

        def first_pending(*args):
            seen.append(args)
            return CompletionEvaluation(False, None, (), pending) if len(seen) == 1 else evaluate_member(*args)
        with patch(self.EVALUATE, side_effect=first_pending):
            processed = process_member(value, context, dispatcher, h.store, h.objects)
        self.assertEqual(processed.result.outcome, 'success')
        self.assertEqual(len(processed.result.child_refs), 3)

    def test_obligations_take_the_repair_path_even_with_a_non_retryable_gap(self):
        """§5 item 6, mixed case (M4): obligations repair as today; the :96 check stays the final guard."""
        with tempfile.TemporaryDirectory() as tmp:
            f = EvidenceFixture(Path(tmp) / '.fixture-state')
            try:
                _, _, transformed = f.invoke('transform', f.snapshot_input(quarterly_bytes('2026-07-01')))
                with checked_fault(f.root):
                    code, _, result = f.invoke('publish', transformed.transformed_workset_ref)
                self.assertEqual((code, result), (9, None))
                pointers = [r.to_mapping() for r in f.store.scan('QuarterPublication', {})]
                clock = f.workflow.deadline + timedelta(seconds=1)
                fresh = replace(f.workflow, attempt_id='fresh-repair', started_at=clock,
                                deadline=clock + timedelta(seconds=3600))
                dispatcher = checked_dispatcher(fresh, f.settings, f.pack, f.root.parent, f.store, f.objects)
                seen = []

                def mixed(*args):
                    evaluation = evaluate_member(*args)
                    if seen:
                        return evaluation
                    seen.append(evaluation)
                    self.assertEqual(len(evaluation.obligations), 1)
                    extra = Error('state_conflict', 'fixture non-retryable gap', False,
                                  f.value['source']['source_id'], {'type': 'Conflict'})
                    return replace(evaluation, gaps=evaluation.gaps + (extra,))
                with checked_clock(f.root, clock), patch('sec_edgar_ingest.cli.Clock.now', return_value=clock), \
                        patch(self.EVALUATE, side_effect=mixed):
                    processed = process_member(f.value, fresh, dispatcher, f.store, f.objects)
                self.assertIn(processed.result.outcome, ('success', 'unchanged'))
                self.assertEqual(len(processed.evidence['resolutions']), 1)
                self.assertEqual([r.to_mapping() for r in f.store.scan('QuarterPublication', {})], pointers)
            finally:
                f.close()
```

- [ ] **Step 2: Run them to verify the expected failures.**

Run: the test command with `test_member_completion.ProcessMemberTests`.
Expected: `test_the_completion_conflict_names_each_gap_in_order` fails: the message is the stock text alone. `test_a_non_retryable_gap_stops_the_member_before_dispatch` fails: `dispatched` is not empty, or a different exception is raised. The other two pass, because they guard behavior that stays.

- [ ] **Step 3: Implement.** In `processing.py`, add this function after the `ProcessedMember` class:

```python
def _gap_text(gaps) -> str:
    """Each gap as `code: message`, in order, on one line (Stage 1c, M3 and M4)."""
    return '; '.join(f'{gap.code}: {gap.message}' for gap in gaps)
```

In `process_member`, after the line `initial = evaluate_member(value, context.parser_version, context.schema_version, store, objects)`, add:

```python
    # Stage 1c (M4): with no obligation to repair, a non-retryable gap means completion cannot pass,
    # so stop before any child runs. Obligations keep the repair path; the final check stays the guard.
    blocking = tuple(gap for gap in initial.gaps if not gap.retryable)
    if blocking and not initial.obligations:
        raise Conflict(f"member {value['member_id']} completion check cannot pass before dispatch: "
                       f'{_gap_text(blocking)}')
```

Replace:

```python
    if result.outcome in COMPLETE and not evaluated.complete:
        raise Conflict('child completion lacks all affected quarter/repair evidence')
```

with:

```python
    if result.outcome in COMPLETE and not evaluated.complete:
        stock = 'child completion lacks all affected quarter/repair evidence'
        raise Conflict(f'{stock}: {_gap_text(evaluated.gaps)}' if evaluated.gaps else stock)
```

- [ ] **Step 4: Run the stage tests.**

Run: the test command with `test_member_completion test_release_1c`.
Expected: 13 tests, `OK`.

- [ ] **Step 5: Guard the existing workflow tests (P8).**

Run: the test command with `test_workflow_processing test_workflow_runner test_workflow_acceptance test_workflow_drain test_local_failures test_reconcile_workflow test_workflow_completion test_release_origin test_release_1b`.
Expected: `OK`. If a test fails because a member now stops before dispatch, stop and ask the owner. Do not change that test.

- [ ] **Step 6: Commit.**

```bash
git add packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py packages/sec-edgar-ingest/tests/test_member_completion.py
git commit -m "fix(workflows): name completion gaps and stop a member that cannot complete before dispatch"
```

---

### Task 4: Full gate, evidence, whole-branch review and merge to main (spec §5 item 8; HUMAN checkpoint)

**Files:**
- Create: `specs/evidence/stage1c/gate.md`, `specs/evidence/stage1c/reproduction.md`

**Interfaces:**
- Consumes: the branch after Tasks 1–3.
- Produces: `main` holding the reviewed change, from which Task 5 builds.

- [ ] **Step 1: Run the full gate in the background.** From the worktree root, with `run_in_background`. Two `test_local_launcher.InstalledLauncherTests` need a `.venv` in the worktree (plan 5, `specs/evidence/stage1b/gate.md`, deviation 2), so link it first and remove it after the gate:

```bash
ln -s /Users/lowell/Projects/sec-edgar-local/.venv .venv
env -u PYTHONDONTWRITEBYTECODE UV_PROJECT_ENVIRONMENT=/tmp/s1c-venv UV_NO_SYNC=1 SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache sh scripts/check-sec-edgar-ingest.sh > /Users/lowell/Projects/sec-edgar-local/fixture-data/stage1c-gate.log 2>&1; echo "exit $?" >> /Users/lowell/Projects/sec-edgar-local/fixture-data/stage1c-gate.log
```

Expected: the log ends with `exit 0`, and unittest prints `OK`. The count is about 1112 (F8) plus 13 new tests, in 73 modules: 71 plus `test_member_completion` and `test_release_1c`. Record the exact count. Do not change `src` while the gate runs. If the gate fails for a reason other than a test, stop and ask. Do not move the gate after the merge. Then run `rm .venv`. It is a symlink, never staged.

- [ ] **Step 2: Record the gate.** Create `specs/evidence/stage1c/gate.md` with the branch, the gated commit, the command and environment, the start and end times, the `Ran N tests in S s` line, `OK` and the module count. List any environment deviation. Commit:

```bash
git add specs/evidence/stage1c/gate.md
git commit -m "docs(evidence): record the Stage 1c branch gate"
```

- [ ] **Step 3: Evidence run on the installed 1b release (P2).** From the worktree root:

```bash
SEC_LOCAL_1B_RELEASE=/Users/lowell/Projects/sec-edgar-local/releases/sha256=9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b/release.json SEC_LOCAL_PROOF_CACHE=/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache /tmp/s1c-venv/bin/python packages/sec-edgar-ingest/tests/network_guard.py test_release_1c -v > /Users/lowell/Projects/sec-edgar-local/fixture-data/stage1c-installed-1b.log 2>&1; echo "exit $?" >> /Users/lowell/Projects/sec-edgar-local/fixture-data/stage1c-installed-1b.log
```

Expected: 3 tests, `OK`, `exit 0`. The 1b-side runs use the installed `9fa189a0…` interpreter.

- [ ] **Step 4: Write the reproduction evidence.** Create `specs/evidence/stage1c/reproduction.md` with:
  1. `## Store shape`: the P4 recipe, and the line "This is the shape of the L12 2024Q1 Attempt (diagnosis, Cause item 4)."
  2. `## Item 1: fails on the 1b release, passes on the 1c code`: the test names. Name the gate run, which used the 1b application built from `50423a4`, and the Step 3 run, which used the installed `9fa189a0…`. The 1b run ends exit 9, `state_conflict`, with pointer 2026Q4 moved and no member receipt. The 1c run completes the member with its 2026Q4 capture.
  3. `## Item 4: repair (M5)`: the pointer list is unchanged, the member is under `already_complete` and in `already_complete_sources`, and no repair record exists. Name the path the test observed (spec §4.2), and any P7 deviation.
  4. `## Limits`: "Fixture packs only. The F17 shape (a 1b incremental publish on an `fc68adef…` base) is not tested (spec S1). The live store's evidence for it is the diagnosis's full-rebuild comparison of data rows."
  5. The line "No SEC request was sent. Nothing was written under `data/`."

```bash
git add specs/evidence/stage1c/reproduction.md
git commit -m "docs(evidence): record the Stage 1c reproduction and repair proofs"
```

- [ ] **Step 5: Whole-branch review.** Use the requesting-code-review skill. It dispatches the `code-reviewer` agent on `main..stage1c-member-completion`, against the spec, this plan and its Decisions. Name these review focuses:
  - M1 byte identity and the P1 order consequence.
  - M2: every other caller still uses `_legacy_publish_call`.
  - M4: the stop fires only with no obligation and a non-retryable gap.
  - M6: no format, outcome or exit-code change.

  Fix each accepted finding with a test, re-run the affected modules, and commit. If a fix changes `src`, re-run Step 1 and update `gate.md`.

- [ ] **Step 6: Check that the branch carries no platform member (M7, D2).**

```bash
git -C /Users/lowell/Projects/sec-edgar-local show stage1c-member-completion:pyproject.toml | grep -n 'members'
git -C /Users/lowell/Projects/sec-edgar-local diff --stat 50423a404fb50a959b3ca4077301117d32804cc6 stage1c-member-completion -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml
git -C /Users/lowell/Projects/sec-edgar-local diff --stat main stage1c-member-completion -- packages/sec-edgar-ingest/src
```

Expected: `members = ["packages/sec-edgar-ingest"]`, no output from the second command, and the third lists only `workflows/completion.py` and `workflows/processing.py`.

- [ ] **Step 7: Owner checkpoint (HUMAN).** Show the owner `gate.md`, `reproduction.md`, the review result and `git log --oneline main..stage1c-member-completion`. Ask for approval to merge the branch into `main` before the release build. Stop until the owner answers. Log the answer as a Decision, with the owner's words.

- [ ] **Step 8: Merge.** In the main checkout:

```bash
cd /Users/lowell/Projects/sec-edgar-local
git status --porcelain --untracked-files=all
git merge --ff-only stage1c-member-completion || git merge --no-ff stage1c-member-completion -m "merge: Stage 1c member-completion fix"
git status --porcelain --untracked-files=all
```

Expected: both `git status` calls print nothing. If `main` gained commits that touch the changed files, stop and ask before merging. Keep the worktree until Task 8 ends.

---

### Task 5: Build and verify the 1c release (M7; spec §6 items 2–4)

Run in the main checkout on `main`.

**Files:**
- Create: `specs/evidence/stage1c/release.md`

**Interfaces:**
- Consumes: clean committed `main` after Task 4.
- Produces: `releases/sha256=<1C>/`. Its ID, manifest path and `git_revision` feed Tasks 6–8 and the Handoff.

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

Expected: one printed path, `…/releases/sha256=<1C>`. Record `<1C>`.

- [ ] **Step 3: Check identity, lock and export against the 1b build inputs (M7, D2).** `runtime-requirements.txt` holds a comment with a random temporary path, so compare the requirement lines only.

```bash
cd /Users/lowell/Projects/sec-edgar-local
C=releases/sha256=<1C>
B=releases/sha256=9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b
cmp "$C/uv.lock" "$B/uv.lock" && echo lock-identical
[ "$(grep -v '^#' "$C/runtime-requirements.txt" | shasum -a 256)" = "$(grep -v '^#' "$B/runtime-requirements.txt" | shasum -a 256)" ] && echo export-lines-identical
git diff --exit-code 50423a404fb50a959b3ca4077301117d32804cc6 HEAD -- uv.lock pyproject.toml packages/sec-edgar-ingest/pyproject.toml && echo inputs-identical
python3 -c "import json,sys; ids=[json.load(open(p))['identity'] for p in sys.argv[1:]]; [print(i['application']['version'], i['git_revision'], sorted(d['name'] for d in i['dependencies'])) for i in ids]" "$C/release.json" "$B/release.json"
```

Expected: `lock-identical`, `export-lines-identical`, `inputs-identical`. Both versions are `0.2.0`. The 1c `git_revision` equals Step 1's revision. The two dependency name lists are equal, with no platform package.

- [ ] **Step 4: Offline verification on the 1c interpreter.** The harness guard refuses any path inside a checkout, and the verifier's children inherit the working directory (plan 4). So the harness and evidence go under a directory outside the checkout:

```bash
cd /Users/lowell/Projects/sec-edgar-local
project=$(pwd -P)
release="$project/releases/sha256=<1C>"
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
cp -R "$outside/evidence" "$project/fixture-data/s1c-verify-evidence"
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -c "import sys; from pathlib import Path; from sec_edgar_ingest.runtime import preflight_current; print(preflight_current(Path(sys.argv[1])).release_id)" "$release/release.json"
```

Expected: the verifier prints JSON with `"exit": 0` and `"release_id": "<1C>"`. `preflight_current` prints `<1C>`.

- [ ] **Step 5: Confirm retention (§4.9).**

```bash
ls /Users/lowell/Projects/sec-edgar-local/releases
```

Expected: `sha256=49b7a2ed…`, `sha256=900952a8…`, `sha256=9fa189a0…`, `sha256=aa8de1ac…`, `sha256=d718ae5f…`, `sha256=fc68adef…` and `sha256=<1C>`, plus `artifact-cache` and `task14-guard-proofs` (F9).

- [ ] **Step 6: Write the release evidence.** Create `specs/evidence/stage1c/release.md` with:
  1. `## Release`: the 1c release ID, its manifest path and its `git_revision` (§6 item 2).
  2. `## Locked inputs (M7)`: the Step 3 results: identical lock, export lines and inputs against the 1b build inputs, version `0.2.0`, and no platform package (§6 item 3).
  3. `## Offline verification`: the verifier JSON, the preflight output and the evidence directory, with 1b, D5, `fc68adef…` and older releases kept (§6 item 4).
  4. The line "No SEC request was sent. Verification used fixture acquisition only."

```bash
git add specs/evidence/stage1c/release.md
git commit -m "docs(evidence): record the 1c release build and offline verification"
```

---

### Task 6: Diagnosis replay on a scratch copy (spec §5 item 7; §6 item 5)

Run in the main checkout on `main`. This step reads `data/` once to copy it, and writes nothing under it. It is release evidence, not part of the gate.

**Files:**
- Create: `specs/evidence/stage1c/replay/diag2-evaluate-member.txt`, `replay/diag5-obligations-pointers.txt`, `replay/live-data-before.sha256`, `replay/live-data-after.sha256`
- Modify: `specs/evidence/stage1c/release.md`

**Interfaces:**
- Consumes: `<1C>` from Task 5; `specs/evidence/stage1c/diagnosis/scripts/diag2.py` and `diag5.py`, unchanged.
- Produces: the §6 item 5 replay record.

- [ ] **Step 1: Confirm that no writer runs.**

```bash
pgrep -fl -- '-m sec_edgar_ingest|scripts/sec-edgar-local|local-bootstrap|local_bootstrap'
```

Expected: no output. If a writer runs, stop and ask.

- [ ] **Step 2: Hash `data/`, then make a fresh scratch copy.** Use the method of the diagnosis's `live-data-before.sha256`: one `shasum -a 256` line per file, with paths relative to `data/`, sorted.

```bash
cd /Users/lowell/Projects/sec-edgar-local
W=/tmp/stage1c-replay-$(date -u +%Y%m%dT%H%M%SZ)
mkdir "$W"
(cd data && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$W/live-data-before.sha256"
cp -Rp data "$W/data"
echo "$W"
```

Record `$W`.

- [ ] **Step 3: Run the two scripts on the 1c interpreter.** Root binding as in the diagnosis: each script opens the copy with its stored binding and takes the root as its first argument.

```bash
cd /Users/lowell/Projects/sec-edgar-local
R=releases/sha256=<1C>
D=specs/evidence/stage1c/diagnosis
"$R/venv/bin/python" -I -B -X pycache_prefix=/dev/null "$D/scripts/diag2.py" "$W/data" 3554e8efb093532572ea5a35a1bf627a175784f0eac74b92e0777cb2e5d461ff > "$W/diag2-evaluate-member.txt" 2>&1
"$R/venv/bin/python" -I -B -X pycache_prefix=/dev/null "$D/scripts/diag5.py" "$W/data" > "$W/diag5-obligations-pointers.txt" 2>&1
grep -n 'complete:\|gap:' "$W/diag2-evaluate-member.txt"
diff "$W/diag5-obligations-pointers.txt" "$D/outputs/diag5-obligations-pointers.txt" && echo pointers-equal
```

Expected: `complete: True obligations: 0`, and no `gap:` line. `pointers-equal`. If `diag5` differs, stop and report the diff.

- [ ] **Step 4: Confirm `data/` is unchanged.**

```bash
cd /Users/lowell/Projects/sec-edgar-local
(cd data && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$W/live-data-after.sha256"
cmp "$W/live-data-before.sha256" "$W/live-data-after.sha256" && echo data-unchanged
```

Expected: `data-unchanged`. Under plan 2 D7, only `state.sqlite3-wal` and `state.sqlite3-shm` may differ. If they do, record it. If any other line differs, stop and ask.

- [ ] **Step 5: Record and commit.** Copy the four files to `specs/evidence/stage1c/replay/`. Append a section `## Diagnosis replay (§5 item 7)` to `release.md`, with the scratch path, the interpreter, the member ID, the `diag2` result, the `pointers-equal` result, the `data-unchanged` result and the line "The committed diagnosis scripts ran unchanged." Then:

```bash
cd /Users/lowell/Projects/sec-edgar-local
mkdir -p specs/evidence/stage1c/replay
cp "$W/diag2-evaluate-member.txt" "$W/diag5-obligations-pointers.txt" "$W/live-data-before.sha256" "$W/live-data-after.sha256" specs/evidence/stage1c/replay/
git add specs/evidence/stage1c/replay specs/evidence/stage1c/release.md
git commit -m "docs(evidence): replay the Stage 1c diagnosis on the 1c release"
```

Remove the scratch copy afterwards with `rm -rf "$W"`. It is a copy that this task made.

---

### Task 7: Select the 1c release in the live config (M8; spec §6 item 6; HUMAN checkpoint)

**Files:**
- Modify: `conf/sec-edgar-local.json` (`runtime.release_manifest` only)
- Modify: `specs/evidence/stage1c/release.md`

**Interfaces:**
- Consumes: `<1C>`.
- Produces: the new effective-config SHA-256 and the selection commit, which Task 8 and the Handoff name.

- [ ] **Step 1: Edit the config.** In `conf/sec-edgar-local.json`, set `runtime.release_manifest` to `/Users/lowell/Projects/sec-edgar-local/releases/sha256=<1C>/release.json`. Change nothing else. `execution.dispatch_reserve_seconds` stays 1800 (M8).

- [ ] **Step 2: Offline preflight and hash on the 1c interpreter.**

```bash
cd /Users/lowell/Projects/sec-edgar-local
release=releases/sha256=<1C>
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

Expected: `floor 480`, `reserve 1800`, `release <1C>`, and `effective` a new SHA-256 (before: `2512fdcb999a302d93de84315d45e4e44d0bb942d5165698b64c371fc42b5be5`, F7). The diff shows one changed value. `binding` holds no `execution` field. Run no launcher command, because `prepare_invocation` writes logs.

- [ ] **Step 3: Owner checkpoint (HUMAN).** Show the owner the diff and the Step 2 output. Ask for approval of the live-config selection. Stop until the owner answers. Log the answer as a Decision, with the owner's words. The approval authorizes no SEC traffic (spec §9).

- [ ] **Step 4: Record and commit.** Append a section `## Live-config selection` to `release.md`, with the effective-config SHA-256, the floor, the reserve, the binding output and the line "No SEC request was sent in this stage." Then:

```bash
git add conf/sec-edgar-local.json specs/evidence/stage1c/release.md
git commit -m "chore(config): select the 1c release"
```

Add the commit hash to `release.md` in the Task 8 commit, not by amending.

---

### Task 8: Parent-spec and runbook amendments (spec §7; §6 items 6 and 7)

**Files:**
- Modify: `specs/sec-filing-index-ingestion-spec.md` (§4.7, §4.8 selected manifest and selection text, §4.9)
- Modify: `docs/runbooks/local-recovery.md` (row "Crash after pointer update")
- Modify: `specs/evidence/stage1c/release.md` (the Task 7 commit hash, the closing statement)

**Interfaces:**
- Consumes: `<1C>`, the Task 7 SHA-256 and commit, and the Task 4 and Task 7 Decisions.

- [ ] **Step 1: §4.7.** After the paragraph that ends `while preserving the actual engine status where known.`, add this paragraph:

```text
A finished publish Attempt whose input workset is incomplete, with no repair record, moved no pointer.
It is not a repair obligation. A member stops before any child dispatch when its first completion
check reports no obligation and a non-retryable gap. The conflict names the member and each such gap,
and no pointer moves. When a completed child leaves a member incomplete, the conflict names each gap
of the completion check. (Stage 1c, plan 6.)
```

- [ ] **Step 2: §4.8 selected manifest.** In the code block under `The selected manifest is:`, replace the path line with `/Users/lowell/Projects/sec-edgar-local/releases/sha256=<1C>/release.json`.

- [ ] **Step 3: §4.8 selection text.** Before the paragraph that begins `Stage 1b (plan 5) selected the 1b release`, add:

```text
Stage 1c (plan 6) selected the 1c release `<1C>` at commit `<Task 7 commit>`. The reserve stays at
1800 s. The effective-config SHA-256 is `<Task 7 SHA-256>`, confirmed by offline preflight.
```

Then make three edits in the following text:
  1. `Stage 1b (plan 5) selected the 1b release` becomes `Before that, Stage 1b (plan 5) selected the 1b release`.
  2. `The effective-config SHA-256 is now` becomes `The effective-config SHA-256 was then`.
  3. In the next paragraph, `Before that, Stage 1a (plan 4) selected` becomes `Earlier, Stage 1a (plan 4) selected`.

Write the full release ID, commit hash and SHA-256 in place of the bracketed names.

- [ ] **Step 4: §4.9.** After the paragraph that ends `[two-release evidence](evidence/stage1b/two-release.md).)`, add:

```text
The 1c release changes no generation, manifest, receipt, member evidence, selection, Attempt or config
format, and no outcome or exit code (M6). The 1b release can still read a store that the 1c release
wrote. But on a store that holds a finished publish Attempt with an incomplete input, such as the live
store, the 1b release fails the member-completion check. So selecting the 1b release again for that
store is unsupported. (Stage 1c, plan 6; §4.3 item 7 of the
[1c spec](completed/sec-filing-index-member-completion.md).)
```

- [ ] **Step 5: Runbook.** In `docs/runbooks/local-recovery.md`, replace the row:

```text
| Crash after pointer update | Re-run through the checked publish/workflow boundary to repair immutable result/index completion. Do not advance the pointer a second time. A pointer without member completion remains a repair obligation. |
```

with:

```text
| Crash after pointer update | Re-run through the checked publish/workflow boundary to repair immutable result/index completion. Do not advance the pointer a second time. A pointer without member completion remains a repair obligation. The completion conflict names each gap of the completion check. A member whose first completion check reports a non-retryable gap and no obligation stops before any child runs, so it leaves no pointer to repair. (Stage 1c.) |
```

- [ ] **Step 6: Close the release evidence.** In `release.md`, add the Task 7 commit hash to `## Live-config selection`. End the file with a section `## Statement` that holds the line "No SEC request was sent in Stage 1c. Nothing was written under `data/`." (§6 item 7).

- [ ] **Step 7: Verify and commit.**

```bash
grep -n "Stage 1c, plan 6" specs/sec-filing-index-ingestion-spec.md
grep -n "sha256=9fa189a0" specs/sec-filing-index-ingestion-spec.md
grep -n "(Stage 1c.)" docs/runbooks/local-recovery.md
```

Expected: two matches for the first grep (§4.7, §4.9), no match for the second inside the selected-manifest code block, and one match for the third. Then:

```bash
git add specs/sec-filing-index-ingestion-spec.md docs/runbooks/local-recovery.md specs/evidence/stage1c/release.md
git commit -m "docs(specs): amend the parent spec and recovery runbook for the 1c release"
```

---

## After the last task

Run the writing-plans Plan Completion Protocol, step 3a included.

**Deferred items** (spec §6). In `specs/deferred_items.md`, section `5-sec-filing-index-per-member-cost — 2026-10-28`, under "Two-release proof covers only first-generation 1b stores", add one line: "Stage 1c (plan 6): the live store now holds such generations: eight incremental 1b generations on `fc68adef…` bases, from invocation 1. The Stage 1c diagnosis compared their data rows with a full rebuild and found them equal; change rows were not compared (`specs/evidence/stage1c/diagnosis/diagnosis.md`). The item stays open." Add no new item unless execution finds one.

**Roadmap.** Do not edit Stage 1c's Exit. The roadmap resume amends it to the real cause (spec §6, S1).

Remove the `stage1c-member-completion` worktree and `/tmp/s1c-venv` after the retire commit (finishing-a-development-branch).

## Handoff to later stages

Fill each `<…>` token from the evidence at plan completion. The 1c spec is `specs/completed/sec-filing-index-member-completion.md` after the retire commit.

- **Stage 2 (baseline campaign; the plan 2 revision).** Consumes, as built:
  - Release `<1C>` (manifest `releases/sha256=<1C>/release.json`, `git_revision` `<1C revision>`), selected in the live config at commit `<Task 7 commit>`. Effective-config SHA-256 `<Task 7 SHA-256>`. Reserve 1800 s. Floor 480 s. Evidence: `specs/evidence/stage1c/release.md`, `gate.md`, `reproduction.md`.
  - The plan 2 revision must change: its Global Constraints (release and effective-config SHA-256); the slice configs, regenerated for the 1c manifest (today `conf/stage2/1b/backfill-2020Q1-2020Q4.json` through `backfill-2025Q1-2025Q4.json`, `backfill-2026Q1-2026Q3.json` and `backfill-2026Q4-open.json`, eight files bound to `9fa189a0…`); `scripts/baseline-campaign.py`, re-verified against `<1C>` (plan 2 Task 1 Steps 4–5); and the `campaign.md` Release gate, read against `<1C>`.
  - Changed modules: `workflows/completion.py` and `workflows/processing.py` only. The tool imports `workflows.results._validate_report`, which reaches `completion`, so the re-verify runs (F6). No result format changed (M6). The stop rules read the workflow `outcome`, so the longer conflict text does not touch them.
  - Repair of member `3554e8efb093532572ea5a35a1bf627a175784f0eac74b92e0777cb2e5d461ff` and ledger row k = 1: on `<1C>`, the next invocation evaluates this member complete. It lists the member's capture under `already_complete`, and its source (`924fd5f5…`) under `already_complete_sources`. No child runs for it, and no pointer moves (spec §4.2; `reproduction.md`, item 4 path: `<observed path>`). Task 5 treats that as completion of the runbook's repair obligation. Row k = 1 of `specs/evidence/baseline-campaign/invocations.md` stays as recorded: exit 9, `state_conflict`. It is not re-run.
  - Three sources appear as already complete in every invocation, because these members have no `WorkflowMemberResult` receipt: the daily members `3554e8ef…` (2026-07-01), `dc790624e85455feb79174c5d0ccbcab31c2b54c2e8b9de01ff503b551270a30` (2026-10-14) and `00c1f46d1f14a72ba1a949f89ff9bc93cb0b95109ace8de6e2799b40af95a4c6` (2026-10-15) (F10). The campaign ledger and the `coverage` tool must count them as complete without a receipt, and must not count them as new work in each invocation.
  - The skipped daily-index listing: in invocation 1, the `discover` child's request for `https://www.sec.gov/Archives/edgar/daily-index/index.json` was refused at 13:40:42Z with `permit_expired` ("child refused a stale dispatch window"), status 0, empty body (`quarantine/discovery/sha256=e3b0c442…`). The local design treats a safely refused expired permit as an explicit deferral (spec §4.3 item 6). The revision must account for the listing that was skipped.
  - The campaign window ends 2026-11-05T13:00:00Z. The open quarter must stay 2026Q4 (before 2027-01-01T00:00:00Z).
  - Traps: (a) the stop before dispatch (M4) ends the command with `state_conflict`, exit 9 and no workflow result, as invocation 1 did, but no child runs and no pointer moves. The message names the member and its gaps. (b) On a poisoned store, the `discover` child still sends its requests before the first member stops (spec §8, second call). (c) Selecting the 1b release again for the live store is unsupported (parent §4.9). (d) Plan 5's traps still apply (plan 5, Handoff, Stage 2 bullet).
  - Deferred into this stage: none new. "Two-release proof covers only first-generation 1b stores" stays open in section `5-sec-filing-index-per-member-cost — 2026-10-28`, with the Stage 1c note.
- **Stages 3, 4 and 5.** Consume `<1C>` wherever they name the 1b release (roadmap default (ix)), with the same config, reserve and floor as Stage 2. Each later invocation lists the three members above as already complete. Trap (a) of the Stage 2 bullet applies to every workflow command.
- **Platform roadmap (not a stage of this roadmap).** S2 is satisfied once `<1C>` is built. The platform member may then merge to `main` under plan 3's Merge gate. That merge belongs to the platform roadmap.
- **Roadmap resume.** Amend Stage 1c's Exit to the real cause (spec S1). Its first clause still names the F17 shape, which the diagnosis ruled out.
