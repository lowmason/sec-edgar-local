# Per-member cost and the 1b release — Stage 1b Design Spec

**Status:** approved; awaiting its plan (writing-plans).
**Approval:** Approved by the owner, 2026-10-27, as committed at `35f96b9`. Owner's words: "I approve the
written Stage 1b spec as committed at 35f96b9."
**Project:** `/Users/lowell/Projects/sec-edgar-local`.
**Parent spec:** [SEC filing-index ingestion](sec-filing-index-ingestion-spec.md) (§§3 R5, R9, R12; 4.2, 4.6–4.9; 5–6; 9).
**Roadmap:** [ingestion roadmap](sec-filing-index-ingestion-roadmap.md), Stage 1b.
**Inputs:** [D5 measurement](evidence/d5-release/measurement.md), [finish measurement](evidence/d5-release/finish-measurement.json),
[plan 4](plans/completed/4-sec-filing-index-bounded-drain.md) D2, D4 and Handoff, `specs/deferred_items.md`
section `4-sec-filing-index-bounded-drain — 2026-10-27`, and the [engine-gap diagnosis](evidence/stage1b/diagnosis.md).

## 1. Purpose

On the D5 release, no reserve lets a full-size quarterly member fit one invocation (plan 4 D2). Full-size
quarterly members took more than 9,000 s, and most of that was engine time outside any child.

The diagnosis found the cause. The engine runs a full content check of a quarter generation
(`validated_manifest`, about 415 s for a 370,321-row quarter) about 12 times for each member. It also
fully checks every published quarter in the store on each `evaluate_member` call
(`_affected_quarters`). The finish step and the `publish` child repeat the same check. A check of the
same generation's hashes takes about 0.01 s.

This stage removes the repeated checks, makes a rebuild of a quarter that only gains new sources
incremental, measures every member class on the new release, and sets the reserve from those costs.
It ships the change as a reviewed native release, called the 1b release below.

## 2. Scope

In scope:

- An integrity check that reads no rows, and the move of engine-side checks to it (C1, C2).
- An incremental, columnar rebuild path for eligible quarters, with its equivalence check (C4–C6).
- One full check per full-rebuild candidate in the `publish` child (C3).
- The measurement, the floor constant, the reserve rule and an owner checkpoint (§6).
- The 1b release, its offline verification and the live-config selection (§7).
- Parent-spec amendments (§8).

Out of scope:

- Any change to the generation, manifest, receipt, selection or config formats, or to `read_quarter`.
- A new workflow outcome or exit code.
- A columnar full-rebuild path. If the first publication of a full-size quarter fails the fit gate, it
  can become a new roadmap stage (§6).
- A fix for the history-scan cost (§6 measures it; the fix is deferred).
- Any SEC request, live run, or change under `data/`.
- Any platform item. The platform workspace member stays off `main` until the 1b release is built (S3).

## 3. Requirements

| ID | Requirement |
|---|---|
| C1 | An integrity check of a generation capture reads its manifest and verifies the manifest SHA-256 and byte count, every listed file's SHA-256 and byte count, and, for an `awaiting_approval` gate, the gate record and approval binding that `validated_manifest` checks today. It reads no data or change rows. It refuses with the same error classes as today's checks. |
| C2 | Engine paths use C1 for a generation reached through a committed pointer, a retained capture or a checked `publish` result: `capture_quarter`, `etl.commands._affected_quarters`, `evaluate_member`, `validate_capture`, `read_child_capture` / `_validate_input_output`, `_obligations`, `baseline_gaps`, `source_revert_gaps`, `_validate_report`, and the `publish` child's checks of the previous generation (`publish_quarter`, `build_candidate`). |
| C3 | The full content check stays in `read_quarter` (§4.6 of the parent spec), `approve`, `rollback`, `catalog._existing`, and the pre-pointer check of a full-rebuild candidate. A full-rebuild candidate is fully checked once per build, not twice. |
| C4 | A quarter takes the incremental path only when all of these hold: an active generation exists, with `quarter_mode` equal to the current mode, parser and schema equal to the context's, and gate `clear`; every incoming source's `source_id` is absent from `active.sources`; and no incoming source is the quarter's quarterly membership authority. Every other case takes today's full rebuild. |
| C5 | The incremental build has four inputs: the base data file and the base change file, read as Arrow tables after C1; the incoming observations for the quarter; and, when the quarter has a membership authority, that source's observations limited by a columnar filter to the touched keys. It resolves only the logical keys (CIK and archive path) that the delta touches, with `_resolve`'s rules: ranking (a base row's kind, period and receipt come from `active.sources` by its `source_id`), the closed-quarter membership filter, and the open-quarter non-member absence rule. The absent set is the base change file's `unresolved_absence` keys minus the touched keys that gain a proposed row. Every absent key is re-emitted as `unresolved_absence` and retained, so `retained_from_generation` follows today's rule. It computes change rows and counts relative to the active rows, and writes files with the full path's writer settings. Fingerprint, `generation_id` and manifest fields come from the full path's functions. For every eligible input, its generation is byte-identical to the full rebuild's. |
| C6 | Before the gate and pointer steps, an incremental candidate passes an equivalence check that does not reuse C5's merge code. The base passes C1. The delta rows pass the row-level check. For the touched keys, the expected rows, change rows and counts come from the full path's own resolution code (`_load_observations` and `_resolve`), run over every selected source's observations limited by a columnar filter to those keys, and the base's active rows for those keys. Every other data row equals its base row, and every other change row equals the re-emitted `unresolved_absence` row, compared column by column. |
| C7 | Generations, manifests, receipts, selection (`sec-local-workflow-selection-v1`), effective config and outcomes do not change format. Existing receipts stay valid byte for byte. Exact replay returns identical bytes. |
| C8 | `DISPATCH_RESERVE_FLOOR_SECONDS` = max(480, P4 floor rule), where the P4 floor rule is max(60, 3 × measured finish seconds, rounded up to 30). The finish step is measured at full size on the built 1b release (§6). If the rule gives more than 480, the constant changes in one commit, and the release is rebuilt and re-verified before C10. |
| C9 | The 1b release is built by `build_release` from clean committed `main`. The package version stays `0.2.0`. `uv.lock` and the requirement lines of `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` are byte-identical to the D5 build inputs. The D5 release, `fc68adef…` and older releases are retained (§4.9). |
| C10 | The live config selects the 1b release and sets `execution.dispatch_reserve_seconds` by the §6 rule, at an owner checkpoint. Offline preflight passes, and the new effective-config SHA-256 is recorded. |

## 4. Design

### 4.1 Components

| Unit | Change |
|---|---|
| `etl/reader.py` | C1 integrity check beside `validated_manifest`; `capture_quarter` uses it (C2). `read_quarter` unchanged (C3). |
| `etl/commands.py` `_affected_quarters` | C1 (C2). |
| `workflows/completion.py`, `workflows/checked.py`, `workflows/processing.py`, `workflows/results.py`, `workflows/runner.py` | Engine call sites move to C1 (C2). |
| `etl/publication.py` `publish_quarter` | C1 for the previous generation. One full check of a full-rebuild candidate (C3). C6 for an incremental candidate. |
| `etl/catalog.py` `build_candidate` | C1 for the active generation. Eligibility (C4) selects the incremental path (C5) or today's full path. |
| `etl/manifest.py` | C6 equivalence check. Full checks unchanged. |
| `config.py` | C8 floor constant. |
| `scripts/measure-d5-drain.py` | Extended: §6 scenarios, one process per scenario, load sampling, history-growth fields. |
| `conf/sec-edgar-local.json` | C10. |
| `releases/sha256=<1b id>/` | C9. |

### 4.2 Data flow

1. **Engine.** Selection, the member loop, the B3 cutoff and the B4 skip do not change. Every
   generation check they make is C1, so a member's engine cost no longer grows with quarter size or
   with the number of published quarters.
2. **`publish` child.** For each affected quarter: C1 on the active generation, then C4.
   - Eligible: build the candidate incrementally (C5), then run C6.
   - Not eligible: today's full rebuild, then one full check (C3).
   - Then the gate, the conditional pointer commit and the result, as today.
3. **Finish step.** As today, with C1 checks (C2).
4. **Public readers.** `capture_quarter` pins a generation (C1). `read_quarter` fully checks it before
   it exposes rows, as today.

### 4.3 Errors and edge cases

1. **Changed bytes.** A changed file or manifest fails C1 with today's error class. An engine path
   that reads such a generation reports the same gap or `Conflict` as today.
2. **Replacement, correction, revert.** A new snapshot of a source already in the quarter is not
   eligible (C4). Removing its old rows can reveal a row that the base does not hold, so it takes the full path.
3. **Membership change.** A quarterly authority arriving for a closed quarter takes the full path,
   with today's `unresolved_absence` and withdrawal rules and gate.
4. **Locality.** For an eligible addition, a key's resolution depends on its base row, its delta rows,
   its membership row (if any), and whether the base change file names it `unresolved_absence`. Untouched
   keys keep their rows. No touched key that was present can become absent, because sources only grow and
   membership does not change (C4). The plan proves this against `_resolve` before it builds C5. Oracle
   tests check byte identity. A case where locality fails joins the C4 exclusions.
5. **What C6 guards.** C6 recomputes touched keys with the full path's code, so a C5 logic error is refused
   before the pointer commits. An error that both paths share would pass C6. The oracle tests guard that
   case. A generation that is wrong but committed would fail the full check in a later `read_quarter`.
   Recovery is then `rollback` to its base.
6. **Validator changes.** A generation is content-checked when its pointer commits. A validator fix
   in a later release is not re-applied to older generations by the engine. `read_quarter` still
   applies the current release's full check (S1).
7. **Member overrun.** A member running at the cutoff still completes (parent §4.7). The §6 reserve
   rule bounds this for the measured member classes.
8. **Two releases.** The 1b release continues D5-origin pending work. Because C7 changes no format,
   selecting D5 again for a store that 1b wrote should be supported. The plan tests that direction
   once and records the result in §4.9 either way.

## 5. Verification (offline)

Tests use stdlib `unittest` under `packages/sec-edgar-ingest/tests/network_guard.py`. Write each test
before its implementation.

1. **C1.** Refuses a changed data-file byte, a changed manifest, and an `awaiting_approval` generation
   without its approval. Reads no rows (patched `iter_file_rows` is not called).
2. **Full-check budget.** In a fixture workflow run with no retried candidate, `_validate_row_origins`
   runs exactly once per full-rebuild candidate and on no other path. `read_quarter` still runs it.
3. **Incremental oracle.** For each eligible case, incremental and full builds give identical
   manifest and file SHA-256 values: a daily source added to the open quarter; a back-dated row added
   to a closed quarter that has a membership authority; a new row that beats the winner and one that
   loses; two delta rows with one key; added and updated change rows; a touched key that the base
   retains as `unresolved_absence`, with and without a membership row; an open quarter with a
   membership authority and a non-member touched key; a closed daily-only quarter.
4. **Fallback.** A replacement snapshot, a revert, an incoming quarterly authority, a mode change and
   a gate other than `clear` each take the full path, with today's output.
5. **C6 refusal.** A changed candidate row is refused before the pointer commits.
6. **Two releases.** D5-origin pending work continues on 1b (plan 4's `origin_release` helper; the
   proofs stay order-aware, plan 4 R2). One test selects D5 again for a store that 1b wrote.
7. **Full gate.** `scripts/check-sec-edgar-ingest.sh` passes. The D5 gate count is 1020 tests in 64
   modules. The new tests add to it.

## 6. Measurement, reserve and owner checkpoint

Runs after the 1b release is built and verified, before the live config changes.

- **Runtime:** the installed 1b interpreter with `-I -B -X pycache_prefix=/dev/null`, fresh stores in
  new git-ignored directories under the project, not under `/tmp` or `/private/tmp`. Fixture
  acquisition only.
- **Robustness:** one process per scenario, each writing its own report when it ends. Machine load
  (`vm.loadavg`) sampled at each member boundary and recorded.
- **Inputs:** the D5 synthetic bodies: quarterly 370,321 rows, daily 3,652 rows (`counts.json`).
- **Scenarios and measures:**

  | Scenario | Measure |
  |---|---|
  | `open`: 81 full-size daily sources in 2026Q4 | Member wall at 1, 10, 40 and 80 sources already in the quarter |
  | `closed` baseline: 2021Q1–2026Q3, the 14 findings §4.7 quarters full size | First-publication quarterly member wall |
  | `closed` measure 1 | One daily row back-dated into one closed full-size quarter |
  | `closed` fan-out | One daily file back-dating one row into each of the 14 quarters |
  | `authority` | A full-size quarterly authority arriving into a closed quarter that has a daily-only generation (the live store's 16 quarters, findings §2): full path, active rows loaded, withdrawals and the gate possible |
  | `finish` | Finish step on the `closed` store and on the 48-quarter store |
  | History growth | Per-member engine time against retained `WorkflowChildCall` and `Attempt` rows, projected to about 400 and 1,200 child calls |

- **Member wall:** from the member's entry into the run loop to its durable receipt.
- **Floor:** C8. A floor change touches only the constant, so the member and finish timings taken on
  the first 1b build stay valid for the rebuilt release. The record names both release IDs.
- **Reserve rule:** reserve = 1.25 × slowest member wall + floor, rounded up to 60 s. Fit gate: slowest
  member wall ≤ 3,300 − reserve (the launcher default). At floor 480 the gate holds for a slowest
  member of about 1,250 s or less.
- **Output:** a dated record in `specs/evidence/stage1b/` with every timing, the load samples, the
  proposed floor and reserve, and the fit-gate result.
- **Owner checkpoint:** the owner reviews the record before the floor constant and the live reserve
  are committed. If the gate fails, the plan stops. The owner either approves a named, measured
  limit or adds a columnar full-rebuild path as a new roadmap stage. The plan does not widen this
  stage. The record states that fixture timings can only underestimate native cost (plan 2 F11).
- **Known risk:** the slowest member is probably a full-path quarterly member: a first publication of a
  full-size quarter (estimated about 1,030 s unloaded), or the `authority` case, which also loads the
  active rows. It passes the gate on a quiet machine and fails at the D5
  run's load.

## 7. Release and exit evidence

Record in `specs/evidence/stage1b/`:

1. The 1b release ID, its manifest path and its `git_revision`.
2. The C9 lock and export comparisons against the D5 build inputs, showing no platform member.
3. The offline checker result and `preflight_current` on the 1b release, with D5, `fc68adef…` and
   older releases kept.
4. The measurement record and the owner's checkpoint decision (§6).
5. The commit that selects the 1b release in `conf/sec-edgar-local.json`, and its effective-config SHA-256.
6. A statement that no SEC request was sent.

Exit (roadmap Stage 1b): the fit gate passes on measured costs, or the owner approves a named,
measured limit; the offline checker and preflight pass on the 1b release with D5 and older releases
retained; C7 holds, so the provenance and reader contracts hold (§9 of the parent spec); no SEC
request was sent.

The plan's `## Handoff to later stages` names every value the plan 2 revision must change: the
release, the effective-config SHA-256, the reserve and floor, regenerated `conf/stage2/*.json`, and
the re-verify list for `scripts/baseline-campaign.py` against the 1b release.

**Deferred items.** At plan completion, in section `4-sec-filing-index-bounded-drain — 2026-10-27`:
tick "Per-member cost", "Unmeasured drain costs" and "Provisional live reserve" with their evidence;
record the B4 single-candidate revisit-trigger check against §6; leave the order-aware proofs and
test-hygiene items open. Add a new item for the history-scan cost with its measured slope,
projection and a revisit trigger (S4).

## 8. Parent-spec amendments

The plan's last task applies these to [the parent spec](sec-filing-index-ingestion-spec.md):

- §4.6: the engine's integrity check (C1, C2), the incremental path (C4–C6), and that `read_quarter`
  still fully checks before it exposes rows.
- §4.8: the 1b manifest path, the reserve, the floor, and the new effective-config SHA-256.
- §4.9: the 1b release, and the tested result of selecting D5 again for a 1b-written store.

## 9. Decisions

Owner answers at brainstorming, 2026-10-27:

- **S1** Trust model: "Hash check (Recommended)". After a full content check at publication, engine
  checks accept a generation by its exact hashes. Refined at design section 1 (approved): an
  incremental candidate gets the C6 equivalence check instead of the full re-derivation.
- **S2** Fan-out: "Incremental rebuild (Recommended)".
- **S3** Platform: "Hold platform (Recommended)". The platform member stays off `main` until the 1b
  release is built.
- **S4** History scans: "Measure, defer fix (Recommended)".
- **S5** Approach: "B" (columnar incremental rebuild with delta-only row checks).
- **S6** Design sections 1–5 approved as presented ("Yes" to each), including the 1.25 reserve
  factor and the stop-at-checkpoint rule (section 3).
- Changes after design approval, for the owner's review of this written spec: C5 gains the base
  change file and the membership rows for touched keys (a reading of `_resolve` found both necessary),
  C6 no longer reuses C5's merge code, §4.3 items 4–5 state locality and what C6 guards, and §6 adds
  the `authority` scenario.
- Roadmap defaults (iv)–(vi), approved 2026-10-27: one stage, not an investigation stage plus a build
  stage; the four deferred items; Stage 2 consumes this release.

## 10. Rollout note

> Roadmap: specs/sec-filing-index-ingestion-roadmap.md, Stage 1b — on plan completion, tick the
> stage and re-validate later stages against what shipped.

Approval of this spec authorizes no SEC request, live run or campaign. The plan 2 revision, written
against the 1b release, and its Task 4 owner gate stay the only route to live traffic.
