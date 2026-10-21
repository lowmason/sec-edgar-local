# Stage 2 Baseline Campaign and Coverage Decision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task via subagent-driven-development (the default) — or executing-plans when your human partner chose inline execution at the handoff. Steps use checkbox (`- [ ]`) syntax for tracking.

> Roadmap: specs/sec-filing-index-ingestion-roadmap.md, Stage 2 — on plan completion, tick the stage and re-validate later stages against what shipped.

**Goal:** Produce an owner-accepted written finding for gate G2. The finding accounts for every requested quarterly baseline unit by a validated publication, or by a named gap, quarantine or gate with an owner disposition. It ends with an explicit complete-or-incomplete operating decision.

**Architecture:** Offline work comes first:

1. A read-only evidence tool (file inventory, transport audit, two-axis coverage), built with TDD against the existing fixture harness.
2. A stopped-writer backup and a hash-verified restoration of one drifted immutable manifest.
3. Known-answer checks against the L12 evidence, range-only slice configs, and the proposed campaign scope and budget.

An owner gate then checks the release and approves the finite scope, budget, window and sole-issuer declaration. After the gate, the operator runs the existing launcher `backfill` workflow once for each range slice. Each slice config differs from the live config only in its backfill range. The operator audits durable transport records after each invocation, and at the end writes the two-axis coverage finding for owner disposition.

**Tech Stack:** Installed native release `fc68adef…` (CPython 3.14.0, macOS arm64, Requests 2.34.2, PyArrow 25.0.1). Stdlib `unittest` under `packages/sec-edgar-ingest/tests/network_guard.py`. SQLite backup API. Launcher `scripts/sec-edgar-local`.

**Spec:** [specs/sec-filing-index-ingestion-spec.md](../sec-filing-index-ingestion-spec.md). This plan implements Stage 2 only: §§4.2–4.9, 5–6 and 7 G2. It plans no work for Stages 3–5.

## Feasibility blocker (read first)

On release `fc68adef…`, the first live invocation has no safe margin inside the runtime limit, and very likely exceeds it. Planning found this from retained native evidence and offline fixtures. It sent no SEC request.

1. The first invocation must carry every pending daily source (F4, F9). On 2026-10-21 that is about 75 sources: L12's 73, plus the business days 2026-10-19 and 2026-10-20 if they are listed. The count grows by one each business day.
2. In L12's genuine run, the native `publish` of the two daily sources took **41.6 s** (2026-10-14) and **187.6 s** (2026-10-15). The source is `specs/evidence/local-port/sec-acceptance.json`, `selected_sources[1].publish` and `selected_sources[2].publish`. The cause of the difference is not established.
3. At the lower value, 75 publishes take about 3,120 s. Collect and transform add about 230 s (L12: 0.6–0.7 s and 2.2–2.6 s for each source). That totals about 3,350 s, before the second processing of each source (F10) and before any growth (F11). The launcher default is 3,300 s and the live maximum is 3,600 s, so even this floor leaves under 10% margin. With about 80 sources by execution day, the floor is about 3,570 s. At the mean of the two observed publishes, the drain needs about 8,800 s, about 2.5 times the live maximum.
4. A run that reaches its deadline is killed and leaves no workflow result (F8). The runner defers undispatched members only when `now >= deadline`, with no margin. So the member in flight at that time becomes `state_conflict`, not a clean deferral. One overrun ends the run with no workflow result, so a run near the limit is not a safe operating point.

Consequence: Tasks 1–3 are offline and remain useful preparation. Task 4's live gate stays closed on this release. The owner routed the blocker at plan review: D5, option (a) of O11. The engine change is outside this plan.

**Status of authority:** This plan authorizes no live traffic.

- Tasks 1 and 3 are offline and send no SEC request.
- Task 2 changes files under `data/`. It runs only after the owner approves defaults O2, O3 and O9 at plan review.
- Task 4 is the owner's live-execution gate. It opens only on a release that clears the feasibility blocker, after a reviewed revision of this plan for that release. Tasks 5–7 run only after the Task 4 approval commit exists.
- Task 8 edits spec text only. It runs only if the owner approves O4, and it does not depend on the campaign.

## Global Constraints

Every task's requirements include these lines.

- Release: `fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec`, manifest `/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/release.json`.
- Live config: `conf/sec-edgar-local.json`, `config_version=sec-local-config-v1`. Effective-config SHA-256 `088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d` (offline preflight, 2026-10-21). Do not edit it.
- Slice configs: `conf/stage2/backfill-<start>-<end>.json`, made only by Task 3's `slice_config` function. Each one equals the live config except for `backfill.start_quarter` and `backfill.end_quarter`. Its storage and logging roots are written as the same absolute paths. The store binding excludes the range (§4.5), so every slice uses the same bound root.
- Observed config facts, 2026-10-21. File-byte SHA-256 is `cad77e29d681e47a6cfb5658b7ddd13c50b6d55f17e0e315f30c2878cf8da0c4`. This differs from the L12 input bytes `2a940f236b2bf37dc1fb4fbef03d0da3c98f663c311231b225961b0c58c3dbbb`, but the effective hash is the same. The file is tracked since commit `001edf5`, although spec §4.8 says "untracked".
- Storage / acquisition: `storage.backend=local`; `acquisition.mode=live`. Data root `/Users/lowell/Projects/sec-edgar-local/data`. Logging root `/Users/lowell/Projects/sec-edgar-local/logs`.
- Backfill / handoff (live config): `2015Q1` through `open`; daily handoff `2026-10-01`.
- SEC identity: `Lowell Mason sec-edgar-ingest mason.lowell@mac.com`. Request policy: 3 requests/second, one active collector.
- HTTP: five total attempts; 2-second base, 120-second local cap with jitter; honor longer server delays. Connect / read / exchange limits 15 / 60 / 90 seconds. Received / expanded limits 67,108,864 / 536,870,912 bytes per response.
- Coordination: namespace `sec-owner-lowell-mason`; 60-second lease, 20-second renewal, 2-second uncertainty.
- Parser / schema: `sec-index-parser-v1` / `sec-index-v1`. Withdrawal approval: `reconciliation.require_withdrawal_approval=true`.
- Execution: live maximum 3,600 seconds; launcher default 3,300 seconds.
- Every native process uses `-I -B -X pycache_prefix=/dev/null`. No checkout application import, dependency sync or install, or interpreter download during a run.
- No parser, schema, runtime, storage or release change. No `--force`. No `approve` or `rollback`. No duplicate-winner selection, pointer edit or object deletion. The single exception is the reviewed Task 2 restoration and `.DS_Store` removal.
- During a campaign window, the launcher is the only SEC client under the owner identity. Do not send manual `curl`, browser or other requests with the owner User-Agent. The sole-issuer declaration covers every other machine and the original `sec-edgar` Azure project.
- Do not open `data/` in an editor, formatter, Finder or Quick Look. Read store contents only through `scripts/baseline-campaign.py` or the release's validated readers.
- Put no campaign evidence under `/tmp` or `/private/tmp`.
- Do not rerun the port's acceptance harness `scripts/accept-sec-native.py` or its adjudicator `scripts/verify-sec-native-adjudication.py`. Do not repeat acceptance (§6).
- Committed evidence goes under `specs/evidence/baseline-campaign/`, apart from `specs/evidence/local-port/` (§8). Raw evidence stays in the ignored `data/`, `logs/` and `backups/` trees. Committed records cite it by path and SHA-256.
- Do not infer completeness from an exit code, latest filing date, directory presence or one nonempty captured quarter (§7). Keep approved incomplete coverage distinct from complete coverage.
- Shell prelude: shell state does not persist between steps, so every shell step below starts with these lines.

```sh
project=/Users/lowell/Projects/sec-edgar-local
release="$project/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec"
native() { "$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null "$@"; }
tool() { native "$project/scripts/baseline-campaign.py" "$@"; }
evidence="$project/specs/evidence/baseline-campaign"
campaign_logs="$project/logs/baseline-campaign"
cd "$project"
```

## Decisions

- **D1** (owner, brief, 2026-10-21): The plan covers roadmap Stage 2 only, scoped to Spec §§4.2–4.9, 5–6 and 7 G2. It plans nothing for Stages 3–5. Applied in: all tasks.
- **D2** (owner, brief, 2026-10-21): Planning sends no SEC request, runs no acquisition, and does not rerun the completed port or the genuine acceptance harness. Plan approval is not live authority. The owner's review of the limits and confirmation of the sole-issuer condition gate live execution. Applied in: Global Constraints, Task 4.
- **D3** (owner, brief, 2026-10-21): The plan consumes findings §§2 and 4.6–4.7 (daily indexes add back-dated rows to old filing quarters) and §5 (2024Q1 quarantine: three conflicting keys that look like combined filings). Applied in: Task 1 (verdict rules), Tasks 6–7.
- **D4** (owner, brief, 2026-10-21): The intended range defaults to the config's `2015Q1`–`open` and needs owner confirmation. Applied in: Task 3 (see O1).
- **D5** (owner, plan review, 2026-10-21): O11 (a). An engine change and a new release come before the Stage 2 live campaign. Tasks 1–3 stay as offline preparation on release `fc68adef…`. Owner's words: "Route O11 (a): an engine change and a new release come before the Stage 2 live campaign. Keep Tasks 1–3 as offline preparation." Applied in: Feasibility blocker, Task 4, After the last task.

## Defaults for owner review

Each default below is applied in the named task. The owner settles each one at plan review. Each answer is logged as a new **D** line above.

- **O1 — Range and slices.** Default: requested range 2015Q1–2026Q4, which is 48 quarterly units. This is the live config's `2015Q1`–`open` on a UTC date in 2026Q4. 2026Q4 is the open quarter, so its quarterly source is quarter-to-date. The campaign runs as range slices (F8, F9). The first slice is the pilot `2026Q4`–`open`. Then ascending slices run from 2015Q1 to 2026Q3, and together they cover the range with no gap or overlap. If the campaign starts on or after 2027-01-01T00:00:00Z, `open` becomes 2027Q1: re-derive the range, the open quarter and every value that names 2026Q4 in the plan revision that Task 4 requires. Alternative: an earlier start, such as the `2010Q1` that the completed design names as a possible later revision. Applied in: Tasks 3 and 5.
- **O2 — 2021Q1 manifest restoration.** Default: after a stopped-writer backup, write the canonical bytes back (Task 2). The canonical re-encoding of the drifted file is SHA-256 `a445d0a8…`, 5,100 bytes, which equals the L12 inventory record. Alternative: leave the file. Then every reader and every publication onto 2021Q1 refuses with `state_conflict`. That includes a future `daily` run whose back-dated rows reach 2021Q1. Applied in: Task 2.
- **O3 — Five `.DS_Store` files in `data/`.** Default: remove them after the backup and record their hashes. Alternative: leave them and accept them as `added` in every inventory comparison. Applied in: Task 2.
- **O4 — Lost L12 external evidence.** `/private/tmp/sec-local-task16-acceptance-20261018` is absent (F3). Spec §6 requires that it be retained. Default: record the loss and amend the spec text (Task 8). What Stage 2 keeps intact is then the committed `specs/evidence/local-port/` records, the immutable live-root objects and the releases. Applied in: Tasks 2 and 8.
- **O5 — Retained daily sources.** The pilot also discovers, collects and publishes every daily body listed under `daily-index/2026/QTR3` and `QTR4` (F4). Default: accept this, budget for it, and report these sources apart from the baseline units for Stage 3. The workflow has no supported way to exclude them. Applied in: Tasks 3, 5 and 7.
- **O6 — Withdrawal gates.** A closed-quarter quarterly source that lacks keys from active daily-only generations proposes withdrawals and stops at `awaiting_approval` (F5). Findings §4.6 shows that such rows can be genuine late releases. Default: approve nothing in Stage 2. The old generation stays active, and each such quarter becomes a named `gated` unit for owner disposition. Approvals belong to Stage 4. Applied in: Tasks 5 and 7.
- **O7 — Discovery-only probe.** Default: no probe. The budget uses the measured 2024Q1 and L12 body sizes, plus margin and stop rules. Alternative: run low-level `discover --mode quarterly` first (about 65 listing requests) to read listed sizes before any body is fetched. Applied in: Task 3.
- **O8 — Budget numbers.** Default: the limits in Task 3's `campaign.json`. Applied in: Tasks 3 and 5.
- **O9 — Backup location.** Default: `/Users/lowell/Projects/sec-edgar-local/backups/stage2-pre-campaign-<UTC stamp>/`, with `backups/` added to `.gitignore`. Applied in: Task 2.
- **O10 — Order effect of the forced pilot.** The pilot runs the daily members before any older quarterly source. Back-dated daily keys therefore become active first in their closed quarters. A closed-quarter quarterly file that lacks such a key then shows as an explicit `gated` unit, with the key in its candidate. In a single full-range run, quarterly sources 2015–2025 would come first. The same keys would then be dropped from publication with no change record (`catalog._resolve`). After any later approval the end state is the same. The difference is visibility against the number of `covered` verdicts. The pilot order is forced while daily sources are pending (F9). A single full-range run is the only alternative, and it cannot fit its deadline (F8, F11). Default: accept the pilot order. In both orders, closed-quarter publication keeps only quarterly-membership keys, and Task 7 must state this as a downstream limitation. Applied in: Tasks 5 and 7.
- **O11 — Routing the feasibility blocker (F11).** Settled by D5: (a).
  - (a) Route an engine change before the live campaign. Candidate fix areas, from reading the code: a dispatch margin in `runner.run_workflow`, a per-invocation member cap, or cheaper daily publication. With a margin or a cap, undispatched members end as `workflow_deferred` before the deadline, and new-ID continuation (`docs/runbooks/local-recovery.md`) drains the rest across invocations. Any of these is an engine change. It needs a new release with its own design and plan, outside Stage 2. After that release exists, revise this plan for it (Global Constraints, Task 3 values, the Task 4 release gate), get owner review, and then run Tasks 4–7.
  - (b) Untested alternative: drain on this release by deliberate deadline expiry and new-ID continuation. Each invocation would end with exit 9 and no workflow result. A kill during a collect can leave an `uncertain` transport attempt. Stop rules 1, 2 and 4 halt on these outcomes. So this route needs its own offline proof and new stop rules, and the recovery runbook names it a recovery path, not an operating mode. This plan does not include it.
  - (c) Stop Stage 2 after Tasks 1–3, or before them.
  - Applied in: Task 4.

## Facts established while planning (read-only, 2026-10-21)

- **F1 — Drifted immutable manifest.** The manifest of the only 2021Q1 generation was rewritten. The file is `data/objects/curated/sec/filing_index/year=2021/quarter=1/generation=887cfe89f5fc96113ade4494ec2d727265baaa0dfc69b4ad9c26cbec08d15001/manifest.json`, with mtime 2026-10-19 08:57 local. It is now tab-indented, 5,655 bytes, SHA-256 `16529f52b03e2a0c178b8105ea4e7821a903d258df12b1be79d9142b567900e0`. L12 recorded 5,100 bytes, `a445d0a836208255d238d92434c98e58f83682bd00de5c4a76860ff24a47f11a`. The cause is not established. The pointer binds the manifest hash and byte count (`etl/reader.py` `capture_from_pointer`, `validated_manifest`), so every reader and every publication onto that base refuses 2021Q1. A `state_conflict` is fatal and halts a workflow (`workflows/contracts.py` `FATAL`).
- **F2 — Finder metadata.** The live root has 160 files against L12's 155. The 5 extra files are `.DS_Store` files.
- **F3 — L12 external evidence absent.** `/private/tmp/sec-local-task16-acceptance-20261018` does not exist. A disk-wide search found no copy of `run-b0bfc28dcc7d48e686b12b5253d8a414.json`. The host had restarted about 12.5 hours before the check. `specs/evidence/local-port/sec-acceptance.json` keeps every recorded hash and the full inventory.
- **F4 — Retained daily work joins any backfill.** In quarterly mode, `discovery._inventory` adds a `daily-index` family for every pending source. `runner.select_work` selects every incomplete retained member. A `backfill` therefore also collects and publishes the L12 pending daily bodies and every other body listed in those directories.
- **F5 — Closed-quarter withdrawals.** In closed mode with quarterly membership, `etl/catalog.py` `_resolve` drops proposed keys that are absent from the membership and marks active keys that are absent as `withdrawn`. The gate is then `awaiting_approval`. Task 1's fixture test `test_closed_quarterly_missing_a_late_daily_key_is_gated_not_covered` reproduces exit 10.
- **F6 — The engine's baseline check is not coverage.** `runner.baseline_gaps` reports a gap only when a requested quarter has no readable capture. A quarter published only from back-dated daily rows therefore shows no gap, even when its quarterly source is quarantined. Task 1's fixture test `test_daily_only_generation_never_counts_for_a_quarantined_quarterly_source` reproduces this.
- **F7 — Quarantines are expected.** 2024Q1 is quarantined (line 88043). The completed design (§231) records conflicting observations in retained 2010Q1, 2015Q1 and 2026Q3 specimens, and 2015Q1 and 2026Q3 are in range. Every `backfill` returns nonzero while a quarantine remains. So the stop rules use durable result fields, not "repeat until exit 0".
- **F8 — A run that reaches its deadline leaves no workflow result.** The launcher sends SIGTERM to the engine group at the deadline (`local_cli.py`, supervision loop). The runner checks the deadline only between members, and only as `now >= context.deadline` (`runner.run_workflow`). A checked child that ends after its deadline, or whose drain is not confirmed, is a `Conflict` (`workflows/checked.py` `_check_exit`), which is `state_conflict`. Work must therefore fit inside each invocation with margin. A range-only config is the supported bound. The L12 quarterly config was such a config, and Task 3's generator reproduces its effective SHA-256 `32b4da638464758c2926fc9040e207696a081d452b2af3813ddd36d179441740` exactly.
- **F9 — Pending sources fix the slice order.** Discovery refuses any member whose quarter is after the pinned end (`worksets._validate_source_directory`: "source member is after the pinned endpoint"), which ends the run with `state_conflict`. While daily sources in 2026Q3–Q4 are pending, every backfill slice must end at 2026Q4. So the pilot is `2026Q4`–`open`, and it drains them. After that, slices run in ascending order, so a pending source from slice k is never after slice k+1's end. The rule is confirmed offline in a fixture store.
- **F10 — Each pending daily source is processed twice.** The selection holds both the retained member from the earlier discovery and the new discovery's member for the same source (`runner.select_work`, `combined`). In the 4-source fixture pilot, `process_member` ran 8 times. The second pass is cheaper.
- **F11 — The pilot has no safe margin inside its runtime on this release.** This is the blocker stated at the top.
  - Native evidence: L12's two daily publishes took 41.6 s and 187.6 s (`sec-acceptance.json`, `selected_sources[1..2].publish`). L12's 2024Q1 transform took 11.7 s and stopped as `invalid_source`, so no native closed-quarter publish time exists.
  - Fixture evidence (temporary stores, fixture parser, 20-row synthetic daily bodies, one back-dated row each, checkout package): the pilot took 50–61 s, 119.8 s and 349.9 s for 2, 4 and 8 pending sources. Child-process time was 20.6 s, 38.9 s and 91.3 s. Both grow faster than the source count.
  - Fixture profile at 4 sources: total 132.6 s. `select_work` 6.7 s (`reuse_exact_binding` 0.2 s, `inventory` 0.1 s). `process_member` 85.0 s over 8 calls, of which children 44.0 s. `baseline_gaps` 6.1 s. The cost is per-member processing, not selection.
  - Fixture timings can only underestimate native cost. So no fixture estimate can show the pilot to be feasible.
  - Unmeasured: the native cost of one closed-quarter quarterly publish. An offline estimate of it was stopped unfinished when this blocker made it moot.

## File structure

| Path | Responsibility | Task |
| --- | --- | --- |
| `scripts/baseline-campaign.py` | Read-only evidence tool: `files`, `audit`, `coverage`. Pinned to release `fc68adef…` internals. | 1 |
| `packages/sec-edgar-ingest/tests/test_baseline_campaign.py` | Offline tests: pure rules plus fixture-store workflows. | 1 |
| `.gitignore` | Adds `backups/`. | 2 |
| `backups/stage2-pre-campaign-<stamp>/` (ignored) | Stopped-writer backup: SQLite backup copy and raw copy of `data/`. | 2 |
| `specs/evidence/baseline-campaign/pre-campaign.md`, `pre-campaign/*.json` | Integrity findings, backup, restoration and known-answer results. | 2–3 |
| `conf/stage2/backfill-<start>-<end>.json` | Range-only slice configs. | 3, 5 |
| `specs/evidence/baseline-campaign/campaign.md`, `campaign.json` | Scope, budget, slice plan, stop rules, evidence locations, approval boundary, release gate and owner approval. | 3–4 |
| `specs/evidence/baseline-campaign/invocations.md`, `invocations/<k>-<run-id>.json` | Ledger and record for each invocation. | 5 |
| `specs/evidence/baseline-campaign/final/*.json`, `quarantine/<quarter>.txt` | Final coverage, audit, inventory comparison and conflict enumerations. | 6 |
| `specs/evidence/baseline-campaign/coverage-finding.md` | The G2 finding, dispositions and operating decision. | 7 |
| `specs/sec-filing-index-ingestion-spec.md` | Amendment for F3 and the config observation, only if O4 is approved. | 8 |

---

### Task 1: Read-only campaign evidence tool

**Files:**
- Create: `scripts/baseline-campaign.py`
- Create: `packages/sec-edgar-ingest/tests/test_baseline_campaign.py`

**Interfaces:**
- Consumes: installed `sec_edgar_ingest` APIs of release `fc68adef…`: `config.load_config`, `storage.open_stores(settings, access='operator')`, `etl.state.EtlState`, `etl.reader.capture_quarter / read_quarter / validated_manifest`, `workflows.contracts.WorkflowResult / workflow_path / member_status`, `workflows.results._read / _validate_report`, `discovery.quarter_span`, and `StateStore.scan('TransportAttempt' | 'QuarterPublication', {})`. Do not use `read_workflow_result`: it repairs index records, so it is not read-only.
- Produces (stdout is indented sorted JSON with `format_version: sec-baseline-campaign-evidence-v1`):
  - `files --root PATH [--recorded JSON]` returns `{kind: files, inventory: {root, file_count, byte_count, files[{relative_path, sha256, byte_count}]}, comparison?: {missing, added, changed_immutable, changed_state}}`. Exit 1 when `missing` or `changed_immutable` is nonempty. `--recorded` accepts the L12 machine evidence, an earlier `files` report or a bare inventory.
  - `audit --config PATH [--run-id ID]... [--budget JSON]` returns `{kind: audit, runs{run_id: summary}, total, store_total, breaches?}`. Each summary is `{attempts, distinct_urls, received_bytes, max_ordinal, uncertain, access_denied, statuses, outcomes}`. Exit 1 on any breach.
  - `coverage --config PATH [--result REF]... --start Q --end Q [--open-quarter Q]` returns `{kind: coverage, requested, results, verdicts, complete, units[{quarter, verdict, source, filing_quarter, last_result_gaps}], other_filing_quarters, daily_sources}`. Exit 0. `filing_quarter` includes `membership_source_id`, `source_kinds` and `daily_rows_considered`.
  - Unit verdicts: `covered`, `covered_open_quarter`, `quarantined`, `gated`, `pending`, `failed`, `publication_mismatch`, `source_missing`, `no_campaign_result`. `complete` is true only when every verdict is `covered` or `covered_open_quarter`.
  - Budget file: `{format_version: sec-baseline-campaign-budget-v1, max_invocations, max_request_attempts, max_request_attempts_per_invocation, max_distinct_urls, max_received_bytes}`.

The coverage rule is the core of G2. A requested unit counts as covered only when the quarter's quarterly source member is complete and the active generation names that same source as its `membership_source`. The gate must also be `clear`, and the validated row count must equal the manifest row count and be above zero. A readable quarter alone never counts (F6).

- [ ] **Step 1: Write the failing test**

Create `packages/sec-edgar-ingest/tests/test_baseline_campaign.py`:

```python
"""Offline invariants for the read-only Stage 2 baseline-campaign evidence tool."""
from network_guard import install
install()

import contextlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from support import fixture_settings
from support_workflows import BASE, CommandHarness, build_pack, idx

PROJECT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT / 'scripts/baseline-campaign.py'
FULL, DAILY = BASE + 'full-index/', BASE + 'daily-index/'


def tool():
    if not SCRIPT.exists():
        raise AssertionError('missing read-only baseline campaign evidence tool')
    return runpy.run_path(str(SCRIPT))


def row(cik, name, filed, number):
    return (cik, name, '10-K', filed, f'edgar/data/{cik}/0000{cik}-26-{number:06d}.txt')


def campaign_pack(root, quarterly, daily_rows):
    """Quarterly 2026Q2-Q4 plus one daily body on 2026-10-01 under daily-index QTR4."""
    listings = {FULL + 'index.json': [('2026', 'dir')],
                FULL + '2026/index.json': [('QTR2', 'dir'), ('QTR3', 'dir'), ('QTR4', 'dir')],
                DAILY + 'index.json': [('2026', 'dir')],
                DAILY + '2026/index.json': [('QTR3', 'dir'), ('QTR4', 'dir')],
                DAILY + '2026/QTR3/index.json': [],
                DAILY + '2026/QTR4/index.json': [('master.20261001.idx', 'file')]}
    bodies = {DAILY + '2026/QTR4/master.20261001.idx': idx(daily_rows, 'daily')}
    for quarter, rows in quarterly.items():
        listings[FULL + f'2026/QTR{quarter}/index.json'] = [('master.zip', 'file')]
        bodies[FULL + f'2026/QTR{quarter}/master.zip'] = idx(rows, 'quarterly')
    return build_pack(root, listings, bodies, repeats=16)


Q3 = (row('222222', 'Third', '2026-07-01', 3),)
Q4 = (row('333333', 'Fourth', '2026-10-01', 4),)
LATE = row('444444', 'Late release', '20260415', 9)
DAILY_ROWS = (row('333333', 'Fourth', '20261001', 4), LATE)
LATE_KEY_IN_Q2 = (row('111111', 'Second', '2026-04-01', 2), (LATE[0], LATE[1], LATE[2], '2026-04-15', LATE[4]))


class PureRuleTests(unittest.TestCase):
    def setUp(self):
        self.api = tool()

    def test_inventory_comparison_allows_only_sqlite_state_to_change(self):
        recorded = {'files': [{'relative_path': 'state.sqlite3', 'sha256': 'a', 'byte_count': 1},
                              {'relative_path': 'objects/x', 'sha256': 'b', 'byte_count': 1},
                              {'relative_path': 'objects/gone', 'sha256': 'c', 'byte_count': 1}]}
        actual = {'files': [{'relative_path': 'state.sqlite3', 'sha256': 'z', 'byte_count': 2},
                            {'relative_path': 'objects/x', 'sha256': 'b', 'byte_count': 2},
                            {'relative_path': 'objects/new', 'sha256': 'd', 'byte_count': 1}]}
        self.assertEqual(self.api['compare_inventory'](recorded, actual),
                         {'missing': ['objects/gone'], 'added': ['objects/new'],
                          'changed_immutable': ['objects/x'], 'changed_state': ['state.sqlite3']})

    def test_recorded_inventory_reads_l12_evidence_and_files_reports(self):
        inventory = {'files': []}
        read = self.api['recorded_inventory']
        self.assertIs(read({'output_inventory': {'live_root': inventory}}), inventory)
        self.assertIs(read({'inventory': inventory}), inventory)
        self.assertIs(read(inventory), inventory)

    def test_unit_verdicts_never_treat_a_readable_quarter_as_coverage(self):
        verdict = self.api['unit_verdict']
        member = {'source_id': 's', 'outcome': 'success', 'status': 'complete', 'quarantined': False,
                  'quarters': [{'quarter': '2026Q3', 'outcome': 'published'}]}
        view = {'status': 'published', 'membership_source_id': 's', 'gate': 'clear',
                'row_count': 3, 'validated_rows': 3}
        self.assertEqual(verdict('2026Q3', '2026Q4', member, view, False), 'covered')
        self.assertEqual(verdict('2026Q4', '2026Q4', member, view, False), 'covered_open_quarter')
        self.assertEqual(verdict('2026Q3', '2026Q4', None, view, True), 'source_missing')
        self.assertEqual(verdict('2026Q3', '2026Q4', None, view, False), 'no_campaign_result')
        daily_only = {**view, 'membership_source_id': None}
        self.assertEqual(verdict('2026Q3', '2026Q4', member, daily_only, False), 'publication_mismatch')
        self.assertEqual(verdict('2026Q3', '2026Q4', member, {**view, 'validated_rows': 2}, False),
                         'publication_mismatch')
        refused = {**member, 'outcome': 'quarantined', 'status': 'failed', 'quarantined': True}
        self.assertEqual(verdict('2026Q3', '2026Q4', refused, daily_only, False), 'quarantined')
        gated = {**member, 'outcome': 'awaiting_approval', 'status': 'pending'}
        self.assertEqual(verdict('2026Q3', '2026Q4', gated, view, False), 'gated')
        self.assertEqual(verdict('2026Q3', '2026Q4', {**member, 'outcome': 'deferred', 'status': 'pending'},
                                 view, False), 'pending')
        self.assertEqual(verdict('2026Q3', '2026Q4', {**member, 'outcome': 'retry_exhausted', 'status': 'failed'},
                                 view, False), 'failed')

    def test_budget_breaches_name_each_exceeded_limit(self):
        budget = {'format_version': 'sec-baseline-campaign-budget-v1', 'max_invocations': 1,
                  'max_request_attempts': 10, 'max_request_attempts_per_invocation': 4,
                  'max_distinct_urls': 10, 'max_received_bytes': 100}
        quiet = {'attempts': 3, 'distinct_urls': 3, 'received_bytes': 50, 'access_denied': 0, 'uncertain': 0}
        check = self.api['check_budget']
        self.assertEqual(check({'runs': {'r1': quiet}, 'total': quiet}, budget), [])
        loud = {'attempts': 5, 'distinct_urls': 3, 'received_bytes': 101, 'access_denied': 1, 'uncertain': 0}
        fields = [(item['scope'], item['field'])
                  for item in check({'runs': {'r1': loud, 'r2': quiet}, 'total': loud}, budget)]
        self.assertEqual(fields, [('campaign', 'received_bytes'), ('r1', 'attempts'),
                                  ('campaign', 'invocations'), ('campaign', 'access_denied')])
        with self.assertRaises(ValueError):
            check({'runs': {}, 'total': quiet}, {**budget, 'format_version': 'other'})


class FixtureStoreTests(unittest.TestCase):
    def setUp(self):
        self.api = tool()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def harness(self, quarterly, daily_rows=DAILY_ROWS):
        settings = fixture_settings(backfill={'start_quarter': '2026Q2', 'end_quarter': 'open'},
            daily={'start_date': '2026-10-01'}, etl={'parser_version': 'fixture-index-parser-v1'},
            http={'retry_base_seconds': 0.001, 'retry_cap_seconds': 0.001},
            fixture={'allow_clock_override': True, 'allow_deadline_override': False})
        h = CommandHarness(self.root, campaign_pack(self.root / 'pack', quarterly, daily_rows), settings)
        self.addCleanup(h.close)
        return h

    def run_tool(self, h, *argv):
        h.close()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.api['main'](list(argv))
        return code, json.loads(stdout.getvalue())

    def coverage(self, h, *refs):
        flags = [item for ref in refs for item in ('--result', ref)]
        return self.run_tool(h, 'coverage', '--config', str(h.config), *flags,
                             '--start', '2026Q2', '--end', '2026Q4', '--open-quarter', '2026Q4')

    def test_backfill_units_separate_quarantine_from_quarterly_coverage(self):
        conflict = (row('111111', 'Second', '2026-04-01', 2), row('111111', 'Changed', '2026-04-01', 2))
        h = self.harness({2: conflict, 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 3, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'])
        self.assertEqual(code, 0)
        verdicts = {unit['quarter']: unit['verdict'] for unit in report['units']}
        self.assertEqual(verdicts, {'2026Q2': 'quarantined', '2026Q3': 'covered',
                                    '2026Q4': 'covered_open_quarter'})
        self.assertFalse(report['complete'])
        self.assertEqual(report['units'][0]['filing_quarter']['status'], 'unpublished')
        self.assertIn('baseline_publication_missing', report['units'][0]['last_result_gaps'])

    def test_daily_only_generation_never_counts_for_a_quarantined_quarterly_source(self):
        conflict = (row('111111', 'Second', '2026-04-01', 2), row('111111', 'Changed', '2026-04-01', 2))
        h = self.harness({2: conflict, 3: Q3, 4: Q4})
        self.assertEqual(h.invoke('daily', run='d1', attempt='a1')[0], 0, h.calls[-1])
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 3, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'])
        unit = report['units'][0]
        # The engine's own baseline check sees a readable 2026Q2 and reports no missing publication.
        self.assertNotIn('baseline_publication_missing', unit['last_result_gaps'])
        self.assertEqual(unit['filing_quarter']['status'], 'published')
        self.assertIsNone(unit['filing_quarter']['membership_source_id'])
        self.assertEqual(unit['filing_quarter']['source_kinds'], {'daily': 1})
        self.assertEqual(unit['verdict'], 'quarantined')

    def test_closed_quarterly_missing_a_late_daily_key_is_gated_not_covered(self):
        h = self.harness({2: (row('111111', 'Second', '2026-04-01', 2),), 3: Q3, 4: Q4})
        code, daily = h.invoke('daily', run='d1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 10, h.calls[-1])
        code, report = self.coverage(h, daily['result_ref'], message['result_ref'])
        unit = report['units'][0]
        self.assertEqual(unit['verdict'], 'gated')
        self.assertIsNone(unit['filing_quarter']['membership_source_id'])
        self.assertEqual([item['period'] for item in report['daily_sources']], ['2026-10-01'])

    def test_closed_quarterly_that_lists_the_late_key_covers_the_quarter(self):
        h = self.harness({2: LATE_KEY_IN_Q2, 3: Q3, 4: Q4})
        self.assertEqual(h.invoke('daily', run='d1', attempt='a1')[0], 0, h.calls[-1])
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        code, report = self.coverage(h, message['result_ref'])
        self.assertTrue(report['complete'])
        view = report['units'][0]['filing_quarter']
        self.assertEqual(view['source_kinds'], {'daily': 1, 'quarterly': 1})
        self.assertEqual((view['daily_rows_considered'], view['validated_rows']), (1, 2))

    def test_audit_counts_each_run_and_refuses_over_budget(self):
        h = self.harness({2: (row('111111', 'Second', '2026-04-01', 2),), 3: Q3, 4: Q4})
        code, message = h.invoke('backfill', run='r1', attempt='a1')
        self.assertEqual(code, 0, h.calls[-1])
        # Five full-index listings (root, year, three quarters) and three quarterly bodies.
        budget = self.root / 'budget.json'
        budget.write_text(json.dumps({'format_version': 'sec-baseline-campaign-budget-v1', 'max_invocations': 1,
            'max_request_attempts': 8, 'max_request_attempts_per_invocation': 8,
            'max_distinct_urls': 8, 'max_received_bytes': 10 ** 9}))
        code, report = self.run_tool(h, 'audit', '--config', str(h.config), '--run-id', 'r1',
                                     '--budget', str(budget))
        self.assertEqual(code, 0, report)
        run = report['runs']['r1']
        self.assertEqual((run['attempts'], run['distinct_urls'], run['max_ordinal']), (8, 8, 1))
        self.assertEqual((run['uncertain'], run['access_denied'], run['statuses']), (0, 0, {'200': 8}))
        self.assertGreater(run['received_bytes'], 0)
        budget.write_text(json.dumps({**json.loads(budget.read_text()), 'max_request_attempts': 7}))
        code, report = self.run_tool(h, 'audit', '--config', str(h.config), '--run-id', 'r1',
                                     '--budget', str(budget))
        self.assertEqual(code, 1)
        self.assertEqual(report['breaches'], [{'scope': 'campaign', 'field': 'attempts',
                                               'observed': 8, 'limit': 7}])

    def test_files_report_refuses_a_rewritten_immutable_object(self):
        root = self.root / 'store'
        (root / 'objects').mkdir(parents=True)
        (root / 'objects/manifest.json').write_bytes(b'{"a":1}')
        (root / 'state.sqlite3').write_bytes(b'one')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.api['main'](['files', '--root', str(root)]), 0)
        recorded = self.root / 'recorded.json'
        recorded.write_text(stdout.getvalue())
        (root / 'state.sqlite3').write_bytes(b'two')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.api['main'](['files', '--root', str(root), '--recorded', str(recorded)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())['comparison']['changed_state'], ['state.sqlite3'])
        (root / 'objects/manifest.json').write_bytes(b'{\n\t"a": 1\n}')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.api['main'](['files', '--root', str(root), '--recorded', str(recorded)]), 1)
        self.assertEqual(json.loads(stdout.getvalue())['comparison']['changed_immutable'], ['objects/manifest.json'])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```sh
cd /Users/lowell/Projects/sec-edgar-local
UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never uv run --offline --locked --package sec-edgar-ingest \
  python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests \
  -p test_baseline_campaign.py -v
```

Expected: `FAILED (errors=10)`. Every error is `AssertionError: missing read-only baseline campaign evidence tool`.

- [ ] **Step 3: Write the implementation**

Create `scripts/baseline-campaign.py`:

```python
"""Read-only Stage 2 baseline-campaign evidence: file inventory, transport audit and coverage.

Run under the selected release interpreter with -I -B -X pycache_prefix=/dev/null. The tool opens
the store with operator access, sends no request and writes nothing under the store root. It uses
release fc68adef... internals (workflow result validation, ETL readers); re-verify it before use
with any other release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

FORMAT = 'sec-baseline-campaign-evidence-v1'
BUDGET_FORMAT = 'sec-baseline-campaign-budget-v1'
MUTABLE_STATE = frozenset({'state.sqlite3', 'state.sqlite3-wal', 'state.sqlite3-shm'})
COVERED = frozenset({'covered', 'covered_open_quarter'})
RANK = {'complete': 0, 'pending': 1, 'failed': 2}
BUDGET_TOTALS = (('attempts', 'max_request_attempts'), ('distinct_urls', 'max_distinct_urls'),
                 ('received_bytes', 'max_received_bytes'))


def dumps(value) -> str:
    return json.dumps(value, sort_keys=True, indent=1) + '\n'


# ---- file inventory -------------------------------------------------------------------------

def file_inventory(root: Path) -> dict:
    files = []
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        files.append({'relative_path': path.relative_to(root).as_posix(), 'sha256': digest,
                      'byte_count': path.stat().st_size})
    return {'root': str(root), 'file_count': len(files),
            'byte_count': sum(item['byte_count'] for item in files), 'files': files}


def recorded_inventory(value: dict) -> dict:
    """Accept the L12 machine evidence, an earlier `files` report, or a bare inventory."""
    if 'output_inventory' in value:
        return value['output_inventory']['live_root']
    return value['inventory'] if 'inventory' in value else value


def compare_inventory(recorded: dict, actual: dict) -> dict:
    """Recorded files must survive byte-identical, except the SQLite state files."""
    before = {item['relative_path']: item for item in recorded['files']}
    after = {item['relative_path']: item for item in actual['files']}
    changed = sorted(path for path in before.keys() & after.keys()
                     if (before[path]['sha256'], before[path]['byte_count'])
                     != (after[path]['sha256'], after[path]['byte_count']))
    return {'missing': sorted(before.keys() - after.keys()),
            'added': sorted(after.keys() - before.keys()),
            'changed_immutable': [path for path in changed if path not in MUTABLE_STATE],
            'changed_state': [path for path in changed if path in MUTABLE_STATE]}


# ---- transport audit ------------------------------------------------------------------------

def summarize_attempts(values: list[dict]) -> dict:
    return {'attempts': len(values),
            'distinct_urls': len({value['url'] for value in values}),
            'received_bytes': sum(value['byte_count'] or 0 for value in values),
            'max_ordinal': max((value['ordinal'] for value in values), default=0),
            'uncertain': sum(value['outcome'] == 'uncertain' for value in values),
            'access_denied': sum(value['status'] == 403 for value in values),
            'statuses': dict(sorted(Counter(str(value['status']) for value in values).items())),
            'outcomes': dict(sorted(Counter(value['outcome'] for value in values).items()))}


def check_budget(audit: dict, budget: dict) -> list[dict]:
    if budget.get('format_version') != BUDGET_FORMAT:
        raise ValueError('unsupported campaign budget format')
    breaches = []
    total = audit['total']
    for field, limit in BUDGET_TOTALS:
        if total[field] > budget[limit]:
            breaches.append({'scope': 'campaign', 'field': field, 'observed': total[field], 'limit': budget[limit]})
    for run_id, summary in audit['runs'].items():
        if summary['attempts'] > budget['max_request_attempts_per_invocation']:
            breaches.append({'scope': run_id, 'field': 'attempts', 'observed': summary['attempts'],
                             'limit': budget['max_request_attempts_per_invocation']})
    if len(audit['runs']) > budget['max_invocations']:
        breaches.append({'scope': 'campaign', 'field': 'invocations', 'observed': len(audit['runs']),
                         'limit': budget['max_invocations']})
    for field in ('access_denied', 'uncertain'):
        if total[field]:
            breaches.append({'scope': 'campaign', 'field': field, 'observed': total[field], 'limit': 0})
    return breaches


def transport_audit(store, run_ids: list[str]) -> dict:
    rows = [row.to_mapping()['value'] for row in store.scan('TransportAttempt', {})]
    runs = {run_id: summarize_attempts([value for value in rows if value['context']['run_id'] == run_id])
            for run_id in run_ids}
    return {'runs': runs,
            'total': summarize_attempts([value for value in rows if value['context']['run_id'] in runs]),
            'store_total': summarize_attempts(rows)}


# ---- coverage -------------------------------------------------------------------------------

def unit_verdict(quarter: str, open_quarter: str | None, member: dict | None, view: dict,
                 source_missing: bool) -> str:
    """One G2 verdict for one requested quarterly source unit."""
    if member is None:
        return 'source_missing' if source_missing else 'no_campaign_result'
    if member['quarantined'] and member['status'] == 'failed':
        return 'quarantined'
    if member['outcome'] == 'awaiting_approval' or any(
            item['quarter'] == quarter and item['outcome'] == 'awaiting_approval' for item in member['quarters']):
        return 'gated'
    if member['status'] != 'complete':
        return member['status']
    if (view['status'] != 'published' or view['membership_source_id'] != member['source_id']
            or view['gate'] != 'clear' or view['row_count'] == 0 or view['validated_rows'] != view['row_count']):
        return 'publication_mismatch'
    return 'covered_open_quarter' if quarter == open_quarter else 'covered'


def member_view(result, member) -> dict:
    from sec_edgar_ingest.workflows.contracts import member_status
    return {'source_id': member.source.source_id, 'kind': member.source.kind, 'period': member.source.period,
            'url': member.source.canonical_url, 'run_id': result.context.run_id,
            'attempt_id': result.context.attempt_id, 'outcome': member.outcome,
            'status': member_status(member.outcome), 'quarantined': member.quarantined,
            'downloaded': member.downloaded, 'transformed': member.transformed,
            'quarters': [{'quarter': item.quarter, 'outcome': item.outcome, 'generation_id': item.generation_id,
                          'candidate_ref': item.candidate_ref} for item in member.quarters],
            'gaps': [{'code': gap.code, 'message': gap.message} for gap in member.gaps]}


def latest_members(results) -> dict:
    """Later invocations supersede earlier ones; inside one result the worst member status wins."""
    latest = {}
    for result in results:
        mine = {}
        for member in result.members:
            view = member_view(result, member)
            held = mine.get(view['source_id'])
            if held is None or RANK[view['status']] > RANK[held['status']]:
                mine[view['source_id']] = view
        latest.update(mine)
    return latest


def quarter_view(quarter: str, objects, state) -> dict:
    from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter, validated_manifest
    try:
        capture = capture_quarter(quarter, objects, state)
        if capture is None:
            return {'quarter': quarter, 'status': 'unpublished'}
        manifest = validated_manifest(capture, objects)
        rows = sum(1 for _ in read_quarter(capture, objects))
    except Exception as error:  # Any refusal is evidence for this quarter, never a crash of the inventory.
        return {'quarter': quarter, 'status': 'capture_invalid', 'error': type(error).__name__ + ': ' + str(error)}
    membership = manifest.membership_source
    return {'quarter': quarter, 'status': 'published', 'capture': capture.to_mapping(),
            'quarter_mode': manifest.quarter_mode, 'gate': manifest.gate, 'row_count': manifest.row_count,
            'validated_rows': rows,
            'membership_source_id': None if membership is None else membership.source.source_id,
            'membership_snapshot_sha256': None if membership is None else membership.snapshot.sha256,
            'source_kinds': dict(sorted(Counter(ref.source.kind for ref in manifest.sources).items())),
            # Closed quarters with a quarterly membership publish only membership keys (catalog._resolve).
            'daily_rows_considered': sum(ref.quarter_counts.get(quarter, 0)
                                         for ref in manifest.sources if ref.source.kind == 'daily')}


def read_results(refs: list[str], store, objects) -> list:
    from sec_edgar_ingest.workflows.contracts import WorkflowResult, workflow_path
    from sec_edgar_ingest.workflows.results import _read, _validate_report
    results = []
    for ref in refs:
        value, _ = _read(ref, objects)
        result = WorkflowResult.from_mapping(value)
        if workflow_path(result.context) != ref:
            raise ValueError('workflow result path differs from its canonical identity: ' + ref)
        _validate_report(result, store, objects)
        results.append(result)
    return sorted(results, key=lambda result: (result.context.started_at, result.context.run_id))


def coverage(store, objects, refs: list[str], start: str, end: str, open_quarter: str | None) -> dict:
    from sec_edgar_ingest.discovery import quarter_span
    from sec_edgar_ingest.etl.state import EtlState
    requested = quarter_span(start, end)
    results = read_results(refs, store, objects)
    for result in results:
        if not set(result.requested_quarters) <= set(requested):
            raise ValueError('a result requested quarters outside the campaign range: ' + result.context.run_id)
    latest = latest_members(results)
    state = EtlState(store)
    published = sorted({row.to_mapping()['value']['quarter'] for row in store.scan('QuarterPublication', {})})
    views = {quarter: quarter_view(quarter, objects, state) for quarter in sorted({*requested, *published})}
    units = []
    for quarter in requested:
        quarterly = [view for view in latest.values() if view['kind'] == 'quarterly' and view['period'] == quarter]
        if len(quarterly) > 1:
            raise ValueError('more than one quarterly source claims ' + quarter)
        member = quarterly[0] if quarterly else None
        asked = [result for result in results if quarter in result.requested_quarters]
        last = asked[-1] if asked else None
        missing = last is not None and any(gap.code == 'baseline_source_missing' and gap.details.get('quarter') == quarter
                                           for gap in last.gaps)
        units.append({'quarter': quarter, 'verdict': unit_verdict(quarter, open_quarter, member, views[quarter], missing),
                      'source': member, 'filing_quarter': views[quarter],
                      'last_result_gaps': [] if last is None else sorted(
                          {gap.code for gap in last.gaps if gap.details.get('quarter') == quarter})})
    verdicts = Counter(unit['verdict'] for unit in units)
    return {'format_version': FORMAT, 'kind': 'coverage', 'requested': {'start': start, 'end': end,
            'open_quarter': open_quarter, 'quarters': len(requested)},
            'results': [{'run_id': result.context.run_id, 'attempt_id': result.context.attempt_id,
                         'command': result.context.command, 'outcome': result.outcome,
                         'counts': dict(result.counts)} for result in results],
            'verdicts': dict(sorted(verdicts.items())),
            'complete': bool(units) and set(verdicts) <= COVERED,
            'units': units,
            'other_filing_quarters': [views[quarter] for quarter in published if quarter not in requested],
            'daily_sources': sorted((view for view in latest.values() if view['kind'] == 'daily'),
                                    key=lambda view: (view['period'], view['source_id']))}


# ---- command line ---------------------------------------------------------------------------

def _open(config: Path):
    from sec_edgar_ingest.config import load_config
    from sec_edgar_ingest.storage import open_stores
    settings = load_config(config.resolve())
    opened = open_stores(settings, access='operator')
    return settings, opened


def _close(opened) -> None:
    for resource in reversed(opened):
        if resource is not None and hasattr(resource, 'close'):
            resource.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='baseline-campaign')
    commands = parser.add_subparsers(dest='command', required=True)
    files = commands.add_parser('files')
    files.add_argument('--root', type=Path, required=True)
    files.add_argument('--recorded', type=Path)
    audit = commands.add_parser('audit')
    audit.add_argument('--config', type=Path, required=True)
    audit.add_argument('--run-id', action='append', default=[])
    audit.add_argument('--budget', type=Path)
    report = commands.add_parser('coverage')
    report.add_argument('--config', type=Path, required=True)
    report.add_argument('--result', action='append', default=[])
    report.add_argument('--start', required=True)
    report.add_argument('--end', required=True)
    report.add_argument('--open-quarter')
    args = parser.parse_args(argv)
    if args.command == 'files':
        actual = file_inventory(args.root.resolve())
        value = {'format_version': FORMAT, 'kind': 'files', 'inventory': actual}
        if args.recorded is not None:
            value['comparison'] = compare_inventory(recorded_inventory(json.loads(args.recorded.read_text())), actual)
        sys.stdout.write(dumps(value))
        return 1 if args.recorded is not None and (value['comparison']['missing']
                                                   or value['comparison']['changed_immutable']) else 0
    _, opened = _open(args.config)
    try:
        if args.command == 'audit':
            value = {'format_version': FORMAT, 'kind': 'audit', **transport_audit(opened[0], args.run_id)}
            breaches = None
            if args.budget is not None:
                breaches = check_budget(value, json.loads(args.budget.read_text()))
                value['breaches'] = breaches
            sys.stdout.write(dumps(value))
            return 1 if breaches else 0
        value = coverage(opened[0], opened[1], args.result, args.start, args.end, args.open_quarter)
        sys.stdout.write(dumps(value))
        return 0
    finally:
        _close(opened)


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run the Step 2 command again.

Expected: `Ran 10 tests` and `OK`, in about 2–3 minutes. The plan's draft passed all 10 tests on 2026-10-21 against the checkout package.

- [ ] **Step 5: Check the tool under the release interpreter, read-only**

This reads files only. It does not open SQLite.

```sh
# prelude (Global Constraints)
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json > /dev/null; echo "exit=$?"
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  | native -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["comparison"]))'
```

Expected: `exit=1`. The comparison has `missing: []` and `changed_state: []`. It has `changed_immutable` equal to exactly the F1 manifest path, and `added` equal to exactly the five `.DS_Store` paths (`.DS_Store`, `objects/.DS_Store`, `objects/raw/.DS_Store`, `objects/raw/sec/.DS_Store`, `objects/raw/sec/indexes/.DS_Store`). Any other difference stops the plan. Report it to the owner.

- [ ] **Step 6: Commit**

The full offline checker is not required, because no file under `packages/sec-edgar-ingest/src` changes and the release is unchanged. Later full checker runs also collect this module.

```sh
git diff --check
git add scripts/baseline-campaign.py packages/sec-edgar-ingest/tests/test_baseline_campaign.py
git commit -m "feat(scripts): add read-only baseline campaign evidence tool"
```

---

### Task 2: Pre-campaign backup and integrity restoration (offline, owner-approved O2, O3, O9)

**Files:**
- Modify: `.gitignore` (append `backups/`)
- Create: `backups/stage2-pre-campaign-<stamp>/` (ignored)
- Create: `specs/evidence/baseline-campaign/pre-campaign/files-before.json`, `backup-files.json`, `files-after.json`
- Create: `specs/evidence/baseline-campaign/pre-campaign.md`
- Modify (data): the F1 manifest. Delete (data): the five `.DS_Store` files.

**Interfaces:**
- Consumes: Task 1 `tool files`; the recovery runbook backup procedure (`docs/runbooks/local-recovery.md`).
- Produces: a verified backup path. A live root whose L12-inventoried files all match L12 again. `pre-campaign.md` sections `Integrity findings`, `Backup`, `Restoration` and `Verification`.

Run this task only after the owner approves O2, O3 and O9. It stays useful under D5, because F1 also blocks any later `daily` run whose back-dated rows reach 2021Q1. No SEC request is involved. Stop at the first unexpected value and report it. Do not improvise a repair.

- [ ] **Step 1: Confirm that no writer runs**

```sh
# prelude (Global Constraints)
pgrep -fl 'sec_edgar_ingest|sec-edgar-local|local-bootstrap' || echo 'no writer'
```

Expected: `no writer`.

- [ ] **Step 2: Record the live root before any change**

```sh
# prelude
mkdir -p "$evidence/pre-campaign"
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  > "$evidence/pre-campaign/files-before.json"; echo "exit=$?"
```

Expected: `exit=1`, with the same comparison as Task 1 Step 5.

- [ ] **Step 3: Make the stopped-writer backup**

```sh
# prelude
grep -qx 'backups/' .gitignore || printf 'backups/\n' >> .gitignore
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$project/backups/stage2-pre-campaign-$stamp"
mkdir -p "$project/backups"
mkdir "$backup"
cp -Rp "$project/data" "$backup/data-raw"
native - "$project/data/state.sqlite3" "$backup/state.sqlite3" <<'PY'
import pathlib, sqlite3, sys
source, target = map(pathlib.Path, sys.argv[1:])
if target.exists(): raise ValueError('backup target must be new')
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(target) as dst: src.backup(dst)
PY
tool files --root "$backup/data-raw" --recorded "$evidence/pre-campaign/files-before.json" \
  > "$evidence/pre-campaign/backup-files.json"; echo "exit=$?"
native -c 'import json,sys; print(json.load(open(sys.argv[1]))["comparison"])' "$evidence/pre-campaign/backup-files.json"
shasum -a 256 "$backup/state.sqlite3"
echo "$backup"
```

Expected: `exit=0`. The comparison is `{'added': [], 'changed_immutable': [], 'changed_state': [], 'missing': []}`. Record the backup path and the `state.sqlite3` backup hash in `pre-campaign.md`.

- [ ] **Step 4: Restore the F1 manifest from its canonical bytes**

```sh
# prelude
native - <<'PY'
import hashlib, json, os
from pathlib import Path
from sec_edgar_ingest.models import canonical_json
target = Path('/Users/lowell/Projects/sec-edgar-local/data/objects/curated/sec/filing_index/year=2021/quarter=1/'
              'generation=887cfe89f5fc96113ade4494ec2d727265baaa0dfc69b4ad9c26cbec08d15001/manifest.json')
drifted = target.read_bytes()
if hashlib.sha256(drifted).hexdigest() != '16529f52b03e2a0c178b8105ea4e7821a903d258df12b1be79d9142b567900e0':
    raise SystemExit('the manifest is not the reviewed drifted bytes; stop')
restored = canonical_json(json.loads(drifted))
if (hashlib.sha256(restored).hexdigest(), len(restored)) != (
        'a445d0a836208255d238d92434c98e58f83682bd00de5c4a76860ff24a47f11a', 5100):
    raise SystemExit('canonical bytes differ from the L12 record; stop')
temporary = target.with_name('.manifest.json.restore')
with temporary.open('xb') as stream:
    stream.write(restored)
    stream.flush()
    os.fsync(stream.fileno())
os.chmod(temporary, 0o600)
os.replace(temporary, target)
directory = os.open(target.parent, os.O_RDONLY)
os.fsync(directory)
os.close(directory)
print(hashlib.sha256(target.read_bytes()).hexdigest(), target.stat().st_size)
PY
```

Expected: `a445d0a836208255d238d92434c98e58f83682bd00de5c4a76860ff24a47f11a 5100`. The drifted bytes stay in `$backup/data-raw/…/manifest.json`.

- [ ] **Step 5: Remove the five `.DS_Store` files (O3)**

```sh
# prelude
for path in .DS_Store objects/.DS_Store objects/raw/.DS_Store objects/raw/sec/.DS_Store objects/raw/sec/indexes/.DS_Store; do
  rm -- "$project/data/$path"
done
```

Expected: no output. `files-before.json` keeps their hashes.

- [ ] **Step 6: Verify the root against L12 before opening the store**

```sh
# prelude
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  > "$evidence/pre-campaign/files-after.json"; echo "exit=$?"
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(v["inventory"]["file_count"], v["comparison"])' "$evidence/pre-campaign/files-after.json"
```

Expected: `exit=0`, file count 155, and empty `added`, `changed_immutable` and `missing`. `changed_state` is empty or lists only SQLite files, which can change when Step 3 reads the database.

- [ ] **Step 7: Verify the restored generation through its pointer**

This opens the store with operator access.

```sh
# prelude
native - <<'PY'
import json
from pathlib import Path
from sec_edgar_ingest.config import load_config
from sec_edgar_ingest.storage import open_stores
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter
settings = load_config(Path('/Users/lowell/Projects/sec-edgar-local/conf/sec-edgar-local.json'))
store, objects, _ = open_stores(settings, access='operator')
try:
    state = EtlState(store)
    pointer = state.pointer('2021Q1').to_mapping()['value']
    capture = capture_quarter('2021Q1', objects, state)
    rows = sum(1 for _ in read_quarter(capture, objects))
    print(json.dumps({'manifest_sha256': pointer['manifest_sha256'], 'manifest_bytes': pointer['manifest_bytes'],
                      'generation_id': capture.generation_id, 'rows': rows}))
finally:
    store.close()
PY
```

Expected: `{"manifest_sha256": "a445d0a836208255d238d92434c98e58f83682bd00de5c4a76860ff24a47f11a", "manifest_bytes": 5100, "generation_id": "887cfe89f5fc96113ade4494ec2d727265baaa0dfc69b4ad9c26cbec08d15001", "rows": 4}`. This matches the 2021Q1 row of the L12 table.

- [ ] **Step 8: Write `specs/evidence/baseline-campaign/pre-campaign.md`**

Write these sections. Use the values printed in Steps 2–7.

```markdown
# Stage 2 pre-campaign integrity record

**Date:** <UTC date of Steps 2–7>. **Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md), Task 2.
No SEC request was sent. No writer ran during this task.

## Integrity findings (before any change)

- The live root held 160 files against the 155 in the L12 inventory
  ([files-before.json](pre-campaign/files-before.json)).
- One immutable object differed from L12: the 2021Q1 generation `887cfe89…` manifest. It had mtime
  2026-10-19 08:57 local, 5,655 bytes, SHA-256 `16529f52…`. L12 recorded 5,100 bytes, `a445d0a8…`.
  The difference is whitespace only. The cause is not established.
- Five `.DS_Store` files were present. Their hashes are in files-before.json.
- The L12 external evidence directory `/private/tmp/sec-local-task16-acceptance-20261018` was absent. A
  disk-wide search on 2026-10-21 found no copy. The committed
  [machine evidence](../local-port/sec-acceptance.json) keeps its recorded hashes and inventory.

## Backup

- Path: `<backup path>`. Raw stopped-writer copy `data-raw/` and SQLite backup-API copy
  `state.sqlite3` (SHA-256 `<hash>`).
- The raw copy matches the live root byte for byte ([backup-files.json](pre-campaign/backup-files.json)).

## Restoration (owner decisions O2 and O3)

- The manifest was rewritten with its canonical bytes after hash checks of both the drifted and
  the canonical bytes. The drifted copy remains in the backup.
- The five `.DS_Store` files were removed.

## Verification

- All 155 L12-inventoried files match again, and no other file exists
  ([files-after.json](pre-campaign/files-after.json)).
- The 2021Q1 pointer binds `a445d0a8…`, 5,100 bytes. The validated read returns 4 rows.
```

- [ ] **Step 9: Commit**

```sh
git add .gitignore specs/evidence/baseline-campaign/pre-campaign.md specs/evidence/baseline-campaign/pre-campaign/
git commit -m "docs(evidence): record pre-campaign backup and manifest restoration"
```

---

### Task 3: Known answers, slice configs and campaign scope and budget (offline)

**Files:**
- Create: `specs/evidence/baseline-campaign/pre-campaign/audit.json`, `coverage.json`
- Modify: `specs/evidence/baseline-campaign/pre-campaign.md` (append `Known-answer checks`)
- Create: `conf/stage2/backfill-2026Q4-open.json`, `conf/stage2/backfill-2015Q1-2015Q2.json`
- Create: `specs/evidence/baseline-campaign/campaign.json`, `campaign.md`

**Interfaces:**
- Consumes: the Task 1 tool and the Task 2 restored root.
- Produces: the `slice_config` shell function (used again in Task 5), the pilot and first-slice configs with their effective hashes, and `campaign.json` and `campaign.md`, which Task 4 gates and Task 5 obeys.

Slice configs and hashes bind to the release that the live config selects. The plan revision for the new release (D5) regenerates them.

- [ ] **Step 1: Offline preflight of the live config**

```sh
# prelude
shasum -a 256 conf/sec-edgar-local.json
native - "$project/conf/sec-edgar-local.json" <<'PY'
import json, sys
from pathlib import Path
from sec_edgar_ingest.config import load_config
from sec_edgar_ingest.runtime import preflight_current
settings = load_config(Path(sys.argv[1]))
verified = preflight_current(Path(settings.runtime.release_manifest))
print(json.dumps({'effective_config_sha256': settings.config_sha256, 'release_id': verified.release_id,
                  'backfill': [settings.backfill.start_quarter, settings.backfill.end_quarter]}))
PY
```

Expected: file hash `cad77e29…`, then `{"effective_config_sha256": "088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d", "release_id": "fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec", "backfill": ["2015Q1", "open"]}`. A changed file hash with the same effective hash is acceptable, but record it. Any other difference stops the plan.

- [ ] **Step 2: Transport known answer**

```sh
# prelude
tool audit --config "$project/conf/sec-edgar-local.json" > "$evidence/pre-campaign/audit.json"; echo "exit=$?"
native -c 'import json,sys; print(json.load(open(sys.argv[1]))["store_total"])' "$evidence/pre-campaign/audit.json"
```

Expected: `exit=0`. `store_total` has `attempts: 10`, `distinct_urls: 10`, `max_ordinal: 1`, `received_bytes: 4946565`, `uncertain: 0` and `access_denied: 0`. These are the L12 values in `sec-acceptance.md` (ten sends, 4,946,565 received bytes, no retries). A different value stops the plan. Report it, because the budget audit would then measure something else.

- [ ] **Step 3: Coverage known answer**

```sh
# prelude
tool coverage --config "$project/conf/sec-edgar-local.json" --start 2015Q1 --end 2026Q4 --open-quarter 2026Q4 \
  > "$evidence/pre-campaign/coverage.json"; echo "exit=$?"
native - "$evidence/pre-campaign/coverage.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
views = [unit['filing_quarter'] for unit in value['units'] if unit['filing_quarter']['status'] == 'published']
print(value['verdicts'], len(views), sum(view['validated_rows'] for view in views),
      sorted({view['membership_source_id'] for view in views}, key=str), value['other_filing_quarters'])
PY
```

Expected: `exit=0`, then `{'no_campaign_result': 48} 16 6744 [None] []`. That is 48 units with no campaign result, 16 published quarters totaling 6,744 rows (the L12 latest-capture total), all daily-only, and no quarter outside the range.

- [ ] **Step 4: Append the known-answer section to `pre-campaign.md`**

```markdown
## Known-answer checks

- Offline preflight: effective config `088403cb…`, release `fc68adef…`, range 2015Q1–open.
  Config file bytes `<hash from Step 1>`.
- [audit.json](pre-campaign/audit.json): 10 transport attempts, 10 URLs, 4,946,565 received bytes,
  ordinal 1 only. This equals L12.
- [coverage.json](pre-campaign/coverage.json): 48 requested units without a campaign result. 16 published
  quarters, all daily-only, total 6,744 validated rows. This equals the L12 latest-capture total.
```

- [ ] **Step 5: Make the pilot and first-slice configs**

The `slice_config` function is defined here and used again in Task 5.

```sh
# prelude
slice_config() {
  native - "$project/conf/sec-edgar-local.json" "$project/conf/stage2" "$1" "$2" <<'PY'
import json, sys
from pathlib import Path
from sec_edgar_ingest.config import load_config
base_path, directory, start, end = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
base = load_config(base_path)
value = json.loads(base_path.read_text())
value['backfill'] = {'start_quarter': start, 'end_quarter': end}
value['storage']['root'] = base.storage.root
value['logging']['root'] = base.logging.root
directory.mkdir(exist_ok=True)
target = directory / f'backfill-{start}-{end}.json'
with target.open('x') as stream:
    json.dump(value, stream, indent=2)
    stream.write('\n')
derived = load_config(target)
expected = base.to_mapping()
expected['backfill'] = {'start_quarter': start, 'end_quarter': end}
if derived.to_mapping() != expected:
    raise SystemExit('slice config differs from the live config beyond the backfill range')
print(target, derived.config_sha256)
PY
}
slice_config 2024Q1 2024Q1 && rm "$project/conf/stage2/backfill-2024Q1-2024Q1.json"
slice_config 2026Q4 open
slice_config 2015Q1 2015Q2
```

Expected: the first line ends with `32b4da638464758c2926fc9040e207696a081d452b2af3813ddd36d179441740`. That is the L12 quarterly config hash, which confirms the generator. That file is then removed, because 2024Q1 is not a slice of this plan. The next two lines each print a path and a new effective hash. Record both hashes in `campaign.md`.

- [ ] **Step 6: Write `specs/evidence/baseline-campaign/campaign.json`**

```json
{
 "format_version": "sec-baseline-campaign-budget-v1",
 "max_distinct_urls": 300,
 "max_invocations": 16,
 "max_received_bytes": 1073741824,
 "max_request_attempts": 1500,
 "max_request_attempts_per_invocation": 700
}
```

- [ ] **Step 7: Write `specs/evidence/baseline-campaign/campaign.md`**

```markdown
# Stage 2 baseline campaign: scope, budget and approval

**Status:** Proposed. Not approved. The release gate is closed. No live invocation may start until the
Release gate section is open and the Approval section is complete and committed.
**Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md).
**Spec:** §§4.2–4.9, 5–6, 7 G2 of the [ingestion spec](../../sec-filing-index-ingestion-spec.md).

## Identity

| Item | Value |
| --- | --- |
| Release | `fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec` |
| Live config | `conf/sec-edgar-local.json`, effective SHA-256 `088403cb…`, file SHA-256 `<Task 3 Step 1>` |
| Pilot config | `conf/stage2/backfill-2026Q4-open.json`, effective SHA-256 `<Task 3 Step 5>` |
| First slice config | `conf/stage2/backfill-2015Q1-2015Q2.json`, effective SHA-256 `<Task 3 Step 5>` |
| Slice generator check | reproduces the L12 quarterly config hash `32b4da63…` |
| Data / log roots | `/Users/lowell/Projects/sec-edgar-local/data` / `…/logs` |
| Pre-campaign backup | `<Task 2 backup path>` |
| Evidence tool | `scripts/baseline-campaign.py` at commit `<Task 1 commit>` |

## Release gate

Closed on release `fc68adef…`. The pilot must drain every pending daily source in one invocation. L12's
native daily publishes took 41.6 s and 187.6 s. So about 75 sources need about 3,350 s at the lower value
and about 8,800 s at the mean, against the 3,600-second live maximum. A run that reaches its deadline leaves
no result (plan 2, F8 and F11). The gate opens only on a release where the pilot's drain fits one invocation
with margin, or where undispatched members defer before the deadline, after a reviewed revision of plan 2
for that release.

## Source scope

- Workflow: launcher `backfill` only, with one slice config for each invocation. No `daily`,
  `reconcile`, low-level command, `approve` or `rollback`.
- Requested units: the quarterly sources 2015Q1–2026Q4, which is 48 units. 2026Q4 is the open quarter.
  Its source is quarter-to-date, and absence from it is not withdrawal authority (§4.4).
- Slice plan (F8, F9). (1) The pilot `2026Q4`–`open` carries every pending daily source as retained work:
  every daily body listed under `daily-index/2026/QTR3` and `QTR4`. L12 left 73 such sources, and more
  business days have been added since. These daily units are not baseline units. The finding reports them
  apart, for Stage 3. (2) Then the first slice `2015Q1`–`2015Q2` measures the per-quarter cost. No native
  closed-quarter publish time exists yet. (3) Then ascending slices run up to 2026Q3, each sized by the
  Task 5 rule. Together the slices cover every quarter exactly once.
- Source quarters and output filing quarters differ (§4.2). Daily rows can be back-dated into old filing
  quarters (findings §4.7).
- Expected exceptions: the 2024Q1 quarantine (line 88043), which is retained and selected again by the
  first slice that reaches it. Possible quarantines for 2015Q1 and 2026Q3 (retained conflict specimens).
  Possible withdrawal gates for closed quarters that hold back-dated daily rows (F5, O10).

## Budget

| Bound | Limit | Enforced by | Basis |
| --- | --- | --- | --- |
| Invocations | 16 | stop rule | pilot invocations, first slice, sized slices, reruns |
| Runtime per invocation | 3,300 s (launcher default) | launcher | live maximum 3,600 s |
| Request rate | 3/s, one collector | coordinator | §4.8 |
| Attempts per URL per command | 5 | downloader | §4.8 |
| Bytes per response | 67,108,864 received / 536,870,912 expanded | downloader | §4.8 |
| Request attempts per invocation | 700 | audit after the invocation | pilot about 7 listings + 1 quarterly + up to about 110 daily bodies; 5 attempts each is about 590 |
| Request attempts, campaign | 1,500 | audit | slices add about 2 + years + quarters listings and one body per quarter |
| Distinct URLs, campaign | 300 | audit | about 1 + 12 + 48 full-index listings, 48 quarterly bodies, 4 daily listings and about 110 daily bodies, about 223 |
| Received bytes, campaign | 1,073,741,824 | audit | about 47 × 4.3 MB + 110 × 0.35 MB, about 240 MB (2024Q1 4,262,821; daily 289,582 and 329,651) |
| Expanded validation bytes, campaign | declared 16 GiB | not counted durably by the launcher; reported after the campaign from retained raw ZIP member sizes | 2024Q1 `master.idx` 33,578,469; L12 counted repeated validation (102,593,106 for 3 bodies) |
| Free disk before each invocation | at least 50 GiB | pre-check | 599 GiB free on 2026-10-21 |
| Store growth | at most 30 GiB | pre-check | whole-quarter generations are rewritten when daily members publish |
| Window | from the approved UTC start, at most 7 days, and ending before 2027-01-01T00:00:00Z | pre-check | `open` must stay 2026Q4 |

The audit checks the aggregate limits between invocations, not inside one. Inside one invocation, the
hard bounds are the runtime, the rate, the per-URL attempt limit and the per-response byte limits.

## Stop rules

After each invocation, apply the first rule that matches.

1. **Halt** on a launcher exit of 2, 6, 8, 9 or 11, or any exit outside 0, 3, 4, 5, 7 and 10.
2. **Halt** when the run left no `result_ref` or no `workflow_summary`. This is a deadline or crash
   (F8). Follow `docs/runbooks/local-recovery.md` with the owner before any further invocation.
3. **Halt** on a workflow outcome of `access_blocked`, `ownership_lost`, `state_conflict` or `internal_error`.
4. **Halt** on any audit breach, any HTTP 403, or any `uncertain` transport attempt.
5. **Halt** when the files comparison against L12 reports `missing` or `changed_immutable`.
6. **Halt** when `workflow_summary.summary_error` is not null.
7. **Rerun the same slice** when any of its units, or any daily source after the pilot, has outcome
   `pending`, `deferred` or `throttled`, and this is the slice's first invocation or its previous
   invocation reduced that count. Halt when a rerun does not reduce it.
8. **Halt** on the second consecutive invocation with `discovery_complete: false`.
9. **Next slice** when quarters remain without a campaign result. Size it by the Task 5 rule.
10. **Finish** when every quarter 2015Q1–2026Q4 has a campaign result and no member has outcome
    `pending`, `deferred` or `throttled`. Quarantined, failed and `awaiting_approval` members are not
    eligible work.

A halt stops the campaign. The operator reports to the owner and does nothing else. A halt is evidence,
not a failure of the plan.

## Evidence locations

- Committed: this directory. `pre-campaign.md`, `invocations.md`, `invocations/<k>-<run-id>.json`,
  `final/`, `quarantine/`, `coverage-finding.md`. Slice configs in `conf/stage2/`.
- Raw and ignored: `data/` (store, durable results), `logs/<run-id>/<attempt-id>/` (launcher evidence),
  `logs/baseline-campaign/` (large tool outputs), `backups/` (pre-campaign backup).

## Approval boundary

- Plan 2's approval authorizes Tasks 1–3 only.
- A live invocation needs all four of these: (1) the Release gate above, open; (2) the Approval section
  below, completed with the owner's words and committed; (3) Task 2 verification with exit 0; (4) the
  sole-issuer declaration below, with its start time.
- Never authorized here: `approve`, `rollback`, `daily`, `reconcile`, a parser, schema, release or live
  config change, a second root, or any SEC request outside the launcher.

## Approval

To be completed in Task 4 with the owner's exact words.
```

- [ ] **Step 8: Commit**

```sh
git add conf/stage2/ specs/evidence/baseline-campaign/
git commit -m "docs(evidence): propose Stage 2 campaign scope, slices and budget"
```

---

### Task 4: Release gate and owner live-execution gate (human checkpoint)

**Files:**
- Modify: `specs/evidence/baseline-campaign/campaign.md` (`Release gate`, `Approval` and `Status` sections)

**Interfaces:**
- Consumes: the Tasks 2–3 commits and the Task 3 Step 1 preflight output (`release_id`).
- Produces: either the closed-gate record that ends the plan, or the approval commit that Task 5 checks before every invocation.

- [ ] **Step 1: Check the release gate**

Read `release_id` from the Task 3 Step 1 output.

- If it is `fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec`, the gate stays closed (F11). Replace the Approval section with `Not opened: F11 blocker on release fc68adef…. Owner routing (D5, plan review, 2026-10-21, verbatim): "Route O11 (a): an engine change and a new release come before the Stage 2 live campaign. Keep Tasks 1–3 as offline preparation."`. Commit as in Step 4, and end the plan here.
- If the owner selected another release, stop. This plan pins `fc68adef…` throughout. First revise the plan for that release: Global Constraints, the Task 1 tool's release-internal imports (re-run Task 1 Steps 4–5), the Task 3 values, and this gate's evidence that the pilot's drain fits one invocation with margin, or that undispatched members defer before the deadline. The owner reviews that revision. Then restart at Task 3.
- Continue to Step 2 only under a reviewed revision whose release gate is open.

- [ ] **Step 2: Present `pre-campaign.md` and `campaign.md` to the owner**

Ask the owner to confirm or change each of these:

1. The range (O1).
2. The budget and stop rules (O8).
3. The runtime per invocation.
4. The window start in UTC.
5. The withdrawal policy (O6) and the order effect (O10).
6. The retained daily sources (O5).
7. The sole-issuer declaration.

Do not suggest that the owner skip any item.

- [ ] **Step 3: Record the owner's answers verbatim**

Replace the Approval section with the following, filled only from the owner's words:

```markdown
## Approval

- Owner: Lowell Mason. Approved on (UTC): <owner's timestamp>.
- Range: <owner's words>. Budget and stop rules: <"as proposed" or the owner's changes>.
- Runtime per invocation: <3300 or another value up to 3600>. Window: starts <UTC>, ends <UTC>.
- Withdrawal policy and order effect: <owner's words>. Retained daily sources: <owner's words>.
- Sole-issuer declaration, verbatim: "<owner's words>"
```

Set `**Status:** Approved for live execution within the limits above.`

If the owner changes a limit, update `campaign.json` in the same commit. If the owner does not approve, stop. The plan then ends at Task 4 with nothing live run.

- [ ] **Step 4: Commit**

```sh
git add specs/evidence/baseline-campaign/campaign.md specs/evidence/baseline-campaign/campaign.json
git commit -m "docs(evidence): record the Stage 2 release gate and owner decision"
```

---

### Task 5: Campaign invocations (live, after Task 4 approval)

**Files:**
- Create: `specs/evidence/baseline-campaign/invocations.md`
- Create: `specs/evidence/baseline-campaign/invocations/<k>-<run-id>.json` (one for each invocation)
- Create: `conf/stage2/backfill-<start>-<end>.json` (each sized slice after the first)
- Create (ignored): `logs/baseline-campaign/coverage-after-<k>.json`, `audit-after-<k>.json`, `files-after-<k>.json`, `launcher-exit-<k>`, `invocation-<k>.json`

**Interfaces:**
- Consumes: the Task 4 approval commit, `campaign.json`, Task 3's slice configs and `slice_config`, and Task 1's `tool audit / coverage / files`.
- Produces: the list of result refs and run IDs for Task 6, in `invocations/*.json`.

The slice order is fixed:

1. The pilot `conf/stage2/backfill-2026Q4-open.json` runs first, and reruns under stop rule 7 until no daily source is pending.
2. Then `conf/stage2/backfill-2015Q1-2015Q2.json`.
3. Each later slice starts at the quarter after the previous slice's end and ends at 2026Q3 at most.

Sizing rule for each later slice:

- `per_quarter` is the largest per-quarter time seen so far: each quarterly slice's elapsed seconds (`ended_at` − `started_at`) divided by its quarter count.
- The slice length is `max(1, min(8, floor(0.5 × timeout / per_quarter)))` quarters.

Repeat Steps 1–7 for k = 1, 2, … until a stop rule says finish or halt. Never start an invocation while another writer runs. Never read the store while the launcher runs.

- [ ] **Step 1: Choose the slice and make its config**

```sh
# prelude
k=$(( $(ls "$evidence"/invocations/*-*.json 2>/dev/null | wc -l) + 1 )); echo "k=$k"
```

For the pilot and the first slice, use the Task 3 configs. Otherwise, apply the sizing rule, define `slice_config` as in Task 3 Step 5, and run `slice_config <start> <end>`. Record the printed effective hash. A rerun under stop rule 7 uses the same config file again.

- [ ] **Step 2: Pre-check**

```sh
# prelude
pgrep -fl 'sec_edgar_ingest|sec-edgar-local|local-bootstrap' || echo 'no writer'
git log -1 --format='%H %s' -- specs/evidence/baseline-campaign/campaign.md
df -g "$project" | tail -1
du -sg "$project/data" | cut -f1
date -u +%Y-%m-%dT%H:%M:%SZ
```

Expected:

- `no writer`.
- The last `campaign.md` commit is the Task 4 approval commit.
- At least 50 GiB available.
- Store growth since pre-campaign (12 MB) of at most 30 GiB.
- The UTC time is inside the approved window and before 2027-01-01T00:00:00Z.
- After the pilot, the last coverage report has no source with outcome `pending`, `deferred` or `throttled` in a quarter after this slice's end (F9).

If any check fails, halt.

- [ ] **Step 3: Run one invocation**

The run can last up to the timeout. Run it in the background with the agent harness's background mode, and wait for the exit notification. Do not poll the SEC or the store meanwhile. Set `config` to this invocation's slice config and `timeout` to the approved value.

```sh
# prelude
k=$(( $(ls "$evidence"/invocations/*-*.json 2>/dev/null | wc -l) + 1 ))
config="$project/conf/stage2/backfill-2026Q4-open.json"   # this invocation's slice config
timeout=3300                                               # the approved value
scripts/sec-edgar-local backfill --config "$config" --timeout-seconds "$timeout"
code=$?
mkdir -p "$campaign_logs"
echo "$code" > "$campaign_logs/launcher-exit-$k"
echo "launcher exit=$code"
```

Expected: an exit code. With quarantines present, 3 is normal (F7).

- [ ] **Step 4: Record the invocation**

```sh
# prelude
k=$(( $(ls "$evidence"/invocations/*-*.json 2>/dev/null | wc -l) + 1 ))
attempt_dir=$(ls -dt "$project"/logs/*/*/ | grep -v '/logs/baseline-campaign/' | head -1)
mkdir -p "$evidence/invocations"
native - "$attempt_dir" "$project/data/objects" "$k" "$(cat "$campaign_logs/launcher-exit-$k")" <<'PY' > "$campaign_logs/invocation-$k.json"
import hashlib, json, sys
from pathlib import Path
directory, objects, k, launcher_exit = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
invocation_bytes = (directory / 'invocation.json').read_bytes()
invocation = json.loads(invocation_bytes)
stdout = [json.loads(line) for line in (directory / 'stdout.jsonl').read_text().splitlines() if line.strip()]
events = []
for line in (directory / 'stderr.jsonl').read_text().splitlines():
    try:
        events.append(json.loads(line))
    except ValueError:
        continue
summaries = [event['fields'] for event in events if event.get('event') == 'workflow_summary']
result_ref = stdout[-1].get('result_ref') if stdout else None
result = json.loads((objects / result_ref).read_bytes()) if result_ref else None
print(json.dumps({'k': k, 'launcher_exit': launcher_exit, 'log_directory': str(directory),
    'invocation_sha256': hashlib.sha256(invocation_bytes).hexdigest(),
    'run_id': invocation['run_id'], 'attempt_id': invocation['attempt_id'], 'command': invocation['command'],
    'release_id': invocation['release_id'], 'config_sha256': invocation['config_sha256'],
    'backfill': invocation['effective_config']['backfill'],
    'started_at': invocation['started_at'], 'deadline': invocation['deadline'],
    'ended_at': None if result is None else result['ended_at'],
    'stdout': stdout, 'result_ref': result_ref,
    'result_sha256': hashlib.sha256((objects / result_ref).read_bytes()).hexdigest() if result_ref else None,
    'workflow_summary': summaries[-1] if summaries else None}, sort_keys=True, indent=1))
PY
run_id=$(native -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$campaign_logs/invocation-$k.json")
cp "$campaign_logs/invocation-$k.json" "$evidence/invocations/$k-$run_id.json"
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(v["release_id"], v["config_sha256"], v["backfill"], v["result_ref"], v["ended_at"], v["workflow_summary"] is not None)' "$evidence/invocations/$k-$run_id.json"
```

Expected: the approved release, the slice config's effective hash from Step 1 or Task 3, the slice range, a non-null `result_ref` and `ended_at`, and `True`. If the release or config hash differs, halt. If `result_ref` is null, apply stop rule 2.

- [ ] **Step 5: Audit the budget**

```sh
# prelude
k=$(ls "$evidence"/invocations/*-*.json | wc -l | tr -d ' ')
flags=$(for f in "$evidence"/invocations/*-*.json; do native -c 'import json,sys; print("--run-id", json.load(open(sys.argv[1]))["run_id"])' "$f"; done)
tool audit --config "$project/conf/sec-edgar-local.json" $flags --budget "$evidence/campaign.json" \
  > "$campaign_logs/audit-after-$k.json"; echo "audit exit=$?"
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(v["total"], v["breaches"])' "$campaign_logs/audit-after-$k.json"
```

Expected: `audit exit=0` and `breaches: []`. Otherwise halt (rule 4).

- [ ] **Step 6: Coverage and integrity after the invocation**

```sh
# prelude
k=$(ls "$evidence"/invocations/*-*.json | wc -l | tr -d ' ')
refs=$(for f in "$evidence"/invocations/*-*.json; do native -c 'import json,sys; v=json.load(open(sys.argv[1])); print("--result", v["result_ref"]) if v["result_ref"] else None' "$f"; done)
tool coverage --config "$project/conf/sec-edgar-local.json" $refs --start 2015Q1 --end 2026Q4 --open-quarter 2026Q4 \
  > "$campaign_logs/coverage-after-$k.json"; echo "coverage exit=$?"
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  > "$campaign_logs/files-after-$k.json"; echo "files exit=$?"
record=$(ls "$evidence"/invocations/"$k"-*.json)
native - "$campaign_logs/coverage-after-$k.json" "$campaign_logs/audit-after-$k.json" "$record" <<'PY'
import json, sys
from pathlib import Path
coverage, audit, record = (Path(item) for item in sys.argv[1:])
value, spent = json.loads(coverage.read_text()), json.loads(audit.read_text())
waiting = ('pending', 'deferred', 'throttled')
eligible = [unit['quarter'] for unit in value['units'] if unit['source'] and unit['source']['outcome'] in waiting]
eligible += [item['period'] for item in value['daily_sources'] if item['outcome'] in waiting]
untouched = [unit['quarter'] for unit in value['units'] if unit['verdict'] == 'no_campaign_result']
entry = json.loads(record.read_text())
entry['after'] = {'verdicts': value['verdicts'], 'eligible': eligible, 'untouched': untouched,
                  'daily_sources': len(value['daily_sources']), 'campaign_total': spent['total']}
record.write_text(json.dumps(entry, sort_keys=True, indent=1) + '\n')
print(json.dumps(entry['after']))
PY
```

Expected: `coverage exit=0` and `files exit=0`. The printed `after` block is now in the invocation record.

- [ ] **Step 7: Decide, log and commit**

Apply the `campaign.md` stop rules in order. Use the launcher exit, `result_ref`, `workflow_summary` (`outcome`, `summary_error`, `discovery_complete`), the audit breaches, the files exit, and the `after` block (`eligible`, `untouched`). For rule 7, compare the length of `eligible` with the previous invocation of the same slice. For rule 9, size the next slice by the sizing rule.

Append one row to `invocations.md`. Create the file with this header on k = 1:

```markdown
# Stage 2 campaign invocations

| k | Slice | Run ID | Launcher exit | Outcome | Elapsed (s) | Complete / pending / failed sources | Published quarters | Attempts (run / campaign) | Received bytes (campaign) | Eligible after | Untouched after | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
```

```sh
# prelude
k=$(ls "$evidence"/invocations/*-*.json | wc -l | tr -d ' ')
git add conf/stage2/ specs/evidence/baseline-campaign/invocations.md specs/evidence/baseline-campaign/invocations/
git commit -m "docs(evidence): record Stage 2 campaign invocation $k"
```

On Rerun or Next slice, go back to Step 1. On Finish, go to Task 6. On Halt, report to the owner with the invocation record and stop the plan here. The owner decides whether Task 6 runs on the evidence so far.

---

### Task 6: Final coverage inventory, integrity and quarantine enumeration (offline)

**Files:**
- Create: `specs/evidence/baseline-campaign/final/coverage.json`, `audit.json`, `files.json`
- Create: `specs/evidence/baseline-campaign/quarantine/<quarter>.txt` (one for each quarantined unit)

**Interfaces:**
- Consumes: the result refs and run IDs in `invocations/*.json`.
- Produces: the inputs for Task 7.

- [ ] **Step 1: Final coverage and audit**

```sh
# prelude
mkdir -p "$evidence/final" "$evidence/quarantine"
refs=$(for f in "$evidence"/invocations/*-*.json; do native -c 'import json,sys; v=json.load(open(sys.argv[1])); print("--result", v["result_ref"]) if v["result_ref"] else None' "$f"; done)
flags=$(for f in "$evidence"/invocations/*-*.json; do native -c 'import json,sys; print("--run-id", json.load(open(sys.argv[1]))["run_id"])' "$f"; done)
tool coverage --config "$project/conf/sec-edgar-local.json" $refs --start 2015Q1 --end 2026Q4 --open-quarter 2026Q4 \
  > "$evidence/final/coverage.json"; echo "coverage exit=$?"
tool audit --config "$project/conf/sec-edgar-local.json" $flags --budget "$evidence/campaign.json" \
  > "$evidence/final/audit.json"; echo "audit exit=$?"
native -c 'import json,sys; v=json.load(open(sys.argv[1])); print(v["verdicts"], v["complete"], len(v["daily_sources"]), [q["quarter"] for q in v["other_filing_quarters"]])' "$evidence/final/coverage.json"
```

Expected: `coverage exit=0` and `audit exit=0`. The verdicts cover exactly 48 units.

- [ ] **Step 2: Final integrity comparison**

```sh
# prelude
tool files --root "$project/data" --recorded specs/evidence/local-port/sec-acceptance.json \
  > "$campaign_logs/files-final.json"; echo "files exit=$?"
shasum -a 256 "$campaign_logs/files-final.json"
native - "$campaign_logs/files-final.json" <<'PY' > "$evidence/final/files.json"
import json, sys
value = json.load(open(sys.argv[1]))
print(json.dumps({'inventory_ref': sys.argv[1], 'file_count': value['inventory']['file_count'],
                  'byte_count': value['inventory']['byte_count'],
                  'comparison': {key: (items if key != 'added' else len(items)) for key, items in value['comparison'].items()}},
                 sort_keys=True, indent=1))
PY
```

Expected: `files exit=0`. `missing` and `changed_immutable` are empty. `changed_state` may list the SQLite files. `added` is a count. The full inventory stays in `logs/` and its SHA-256 goes in the finding.

- [ ] **Step 3: Enumerate conflicts for each quarantined quarterly unit**

The parser stops at the first conflict (L12 record). This step lists every repeated raw key with more than one distinct row, from retained bytes only. Run it for each quarter with verdict `quarantined`:

```sh
# prelude
quarter=2024Q1   # repeat for each quarantined quarter
for zip in "$project"/data/objects/raw/sec/indexes/kind=quarterly/period=$quarter/sha256=*/master.zip; do
  echo "# $zip $(shasum -a 256 "$zip" | cut -d' ' -f1)"
  unzip -p "$zip" master.idx | tr -d '\r' | awk -F'|' 'NF==5 && $1 ~ /^[0-9]+$/ {
      k=$1"|"$5; if (!((k SUBSEP $0) in seen)) {seen[k SUBSEP $0]=1; d[k]++}; r[k]=r[k] NR":"$3"; "}
      END {for (k in d) if (d[k]>1) print k "\t" r[k]}' | sort
done > "$evidence/quarantine/$quarter.txt"
wc -l "$evidence/quarantine/$quarter.txt"
```

Expected for 2024Q1: 4 lines, one header line and 3 key lines. The key lines are CIK 1426332 at lines 88033/88043 and 88035/88044, and CIK 1481241 at lines 98688/98690, as in findings §5.2. Planning checked this output against the retained 2024Q1 ZIP on 2026-10-21. This is a raw-field enumeration. The parser's normalized key could merge more rows, and the record must say so.

- [ ] **Step 4: Commit**

```sh
git add specs/evidence/baseline-campaign/final/ specs/evidence/baseline-campaign/quarantine/
git commit -m "docs(evidence): record final Stage 2 coverage and quarantine enumeration"
```

---

### Task 7: G2 coverage finding, owner dispositions and operating decision

**Files:**
- Create: `specs/evidence/baseline-campaign/coverage-finding.md`

**Interfaces:**
- Consumes: Task 6 outputs, `invocations.md`, `campaign.md` and `pre-campaign.md`.
- Produces: the accepted G2 finding that the roadmap's Stage 2 Exit requires, and that Stages 3–4 consume.

- [ ] **Step 1: Write the finding**

Use these sections in this order. Take every number from the cited JSON files. Do not round counts.

```markdown
# Stage 2 baseline coverage finding (G2)

**Status:** Proposed for owner disposition. **Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md).
**Range:** 2015Q1–2026Q4 (48 quarterly units; 2026Q4 open). **Release:** <approved release>. Slice configs:
see invocations.md.

## 1. Result
One paragraph: the verdict counts from final/coverage.json, `complete` true or false, and the operating
decision proposed in §6.

## 2. Campaign as run
The slices, invocations and window used, and the totals against each campaign.json limit
(final/audit.json). The elapsed time of each pilot invocation against the F11 figures. Unique expanded
bytes: the sum of `master.idx` sizes of the retained quarterly ZIPs, from `unzip -l` on each raw ZIP.
Report it as post hoc, not as enforced.

## 3. Baseline units
One table row per requested quarter: quarter, verdict, source ID (first 12 hex), member outcome,
active generation (first 12 hex), membership source equal to the unit's source (yes/no), validated rows,
daily rows considered.

## 4. Exceptions and dispositions
One subsection per unit whose verdict is not covered or covered_open_quarter. Each gives: the evidence
(gap codes, error message, quarantine file, candidate ref and withdrawn count for gated units), the
downstream limitation, the proposed disposition, and an `Owner disposition:` line that only the
owner's words fill. Proposed dispositions use one of: "accepted named gap", "deferred to a versioned
parser/schema design (Size: design)", "deferred to Stage 4 reconciliation approval review", or
"re-run in a later campaign".

## 5. Other output
- Filing quarters outside the range (other_filing_quarters).
- Daily sources processed as retained work (daily_sources): count, period range, outcomes. These are
  Stage 3 inputs.
- The open quarter 2026Q4: the snapshot receipt time, and the fact that its absences are not withdrawal
  authority.
- Downstream limitation (O10): closed-quarter publication keeps only quarterly-membership keys. A
  back-dated daily row that the quarterly file does not list is not in that quarter's catalog.

## 6. Operating decision
Exactly one of these:
- "Complete: every requested unit is covered (2026Q4 as open quarter-to-date)."
- "Approved incomplete: coverage is accepted with the named exceptions in §4 and these downstream
  limitations: …. Refused rows and sources are not accepted data."
Then the line `Owner decision:`, filled only with the owner's words and date.

## 7. Evidence integrity
- L12-inventoried immutable files are unchanged (final/files.json). SQLite state changed by design.
  Full inventory `logs/baseline-campaign/files-final.json`, SHA-256 `<hash>`.
- Pre-campaign facts: the 2021Q1 manifest restoration and the absent L12 external directory
  ([pre-campaign.md](pre-campaign.md)). Stage 2 cannot restore the absent directory.
```

- [ ] **Step 2: Owner disposition**

Present §§1, 4 and 6 to the owner. Record each disposition and the decision verbatim. Then set `**Status:** Accepted by the owner on <date>.` If the owner rejects the finding or asks for another campaign, stop. Record the request. The plan is then not complete.

- [ ] **Step 3: Commit**

```sh
git add specs/evidence/baseline-campaign/coverage-finding.md
git commit -m "docs(evidence): record accepted Stage 2 baseline coverage finding"
```

---

### Task 8: Spec amendment for the pre-campaign facts (only if the owner approves O4)

**Files:**
- Modify: `specs/sec-filing-index-ingestion-spec.md` (§4.8 and §6). Leave the status line untouched.

**Interfaces:**
- Consumes: the D-line date recorded for O4 at plan review.
- Produces: spec text that matches the facts in F3 and in the config observation.

This task does not depend on the live campaign. It can run right after plan review.

- [ ] **Step 1: Amend §4.8**

Replace:

```text
The config remains untracked. Acceptance-time statements that the preserved default selected
```

with (use the O4 decision date):

```text
The config is tracked in git since commit `001edf5`; its effective-config hash is unchanged
(owner, plan 2, <O4 decision date>). Acceptance-time statements that the preserved default selected
```

- [ ] **Step 2: Amend §6**

Replace:

```text
Retain the live root, releases, committed evidence, and `/private/tmp/sec-local-task16-acceptance-20261018`,
including the original results and separate supplement. Future operational reports add evidence;
```

with:

```text
Retain the live root, releases, and committed evidence. The external directory
`/private/tmp/sec-local-task16-acceptance-20261018`, with the original results and separate supplement,
was found absent on 2026-10-21; its recorded hashes and inventory remain in the committed machine
evidence (owner, plan 2, <O4 decision date>). Future operational reports add evidence;
```

- [ ] **Step 3: Commit**

```sh
git add specs/sec-filing-index-ingestion-spec.md
git commit -m "docs(specs): record tracked config and absent L12 external evidence"
```

---

## After the last task

Run the writing-plans Plan Completion Protocol, step 3a included. Facts known now, for the `## Handoff to later stages` section:

- **If Task 4's release gate stays closed**, Stage 2 is blocked, not complete. The stage stays unticked. The completion protocol records the F11 blocker and the owner's routing (D5) for derive-roadmap at the next resume. Under D5, that resume adds the engine change and its new release ahead of the Stage 2 live campaign, and then a revision of this plan for that release.
- **Stage 3** consumes the daily sources that Stage 2 processed as retained work (O5, F4). It no longer finds the L12 "73 pending" inventory as it was. Its inventory is `final/coverage.json` `daily_sources` plus a fresh discovery. F11 applies to any `daily` invocation too: it carries every pending daily source, natively each one's publish took 40–190 s, and the work must fit inside one invocation.
- **Stage 4** consumes every `gated` unit (F5, O6, O10) and every quarantine disposition that names reconciliation.
- **All later stages** inherit the F1 and F3 constraints: no editor, Finder or `/tmp` use on evidence, and the integrity check `tool files … --recorded …` before live work. They also inherit F8 and F9: work must fit inside one invocation, and no member may be after the pinned end.
- The roadmap's Stage 2 Exit says "original port acceptance evidence remains intact". As shipped, that holds for the committed records, the immutable objects and the releases, but not for the absent `/private/tmp` directory (F3). derive-roadmap reconciles that wording at the next resume.
