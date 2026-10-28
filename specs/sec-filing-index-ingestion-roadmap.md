> For agentic workers: REQUIRED SKILL: derive-roadmap — resume via its
> reconcile step; route each unticked stage per its ROUTING line; never plan
> this document wholesale.

## Gap analysis

**Project:** `/Users/lowell/Projects/sec-edgar-local`.
**Rewritten:** 2026-10-18, replacing the copied Azure roadmap in place.
**Source:** [Local filing-index spec](sec-filing-index-ingestion-spec.md). Requirement and gate IDs
below refer to its §§3 and 7. **Status:** local stage partition proposed for review; no remaining
stage is started or approved for execution by this rewrite. The owner approved the partition at
resume, 2026-10-21, with the Stage 2 `Consumes` amendment below. Approval of the partition does not
authorize live execution of any stage. The owner requested inclusion of a
future local scheduling phase; its design remains open. **Resume, 2026-10-22:** inserted Stage 1a
(the D5 release) was approved by the owner with defaults (i)–(iii) under Open questions. **Resume,
2026-10-27:** inserted Stage 1b (per-member cost, plan 4 D2) was approved by the owner as proposed
under Open questions.

The native port is complete, not a scaffold. Its [retired plan](plans/completed/1-sec-edgar-local-spec.md)
and [final completion review](evidence/local-port/completion-review.md) control delivery status.
The checked local Stage 1 below is a retrospective mapping to that completed plan; it does not
import parent-project stage numbers, replay their history, or create a new completion claim.
The current config now selects the D5 release (§4.8 of the spec; plan 4, Handoff; Resolved at resume,
2026-10-27); acceptance-time old-default statements remain historical. The completed port records
nothing deferred; plan 4's deferred items are in `specs/deferred_items.md` (plan 4, Handoff; Resolved
at resume, 2026-10-27).

Search boundary: this checkout's runtime/tests, current config, runbooks, retired local design/plan,
and retained port evidence. Live stores were not opened to measure new coverage, and no acquisition,
acceptance, or scheduler was run for this rewrite. A `missing` operational verdict means no accepted
report establishing that gate was found here, not that the underlying command is absent.

| Req | Verdict | Evidence | Note |
|---|---|---|---|
| R1 | implemented-as-specified | [Runner](../packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/runner.py), [discovery tests](../packages/sec-edgar-ingest/tests/test_discovery.py) | Inclusive quarterly selection and retained gaps; G2 is separate. |
| R2 | implemented-as-specified | [Discovery](../packages/sec-edgar-ingest/src/sec_edgar_ingest/discovery.py), [workflow acceptance tests](../packages/sec-edgar-ingest/tests/test_workflow_acceptance.py) | Outage/overlap/pending handling exists; G3 is separate. |
| R3 | implemented-as-specified | [Parser](../packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/parser.py), [local ETL tests](../packages/sec-edgar-ingest/tests/test_local_etl_contracts.py) | Strict ten-field rows and whole-source refusal. |
| R4 | implemented-as-specified | [Completed local design](completed/sec-edgar-local-spec.md#4-components-and-data-flow), [native preflight tests](../packages/sec-edgar-ingest/tests/test_runtime_preflight.py) | Installed native execution and local SQLite/objects replace cloud services. |
| R5 | implemented-as-specified | [Workflow processing](../packages/sec-edgar-ingest/src/sec_edgar_ingest/workflows/processing.py), [checked child tests](../packages/sec-edgar-ingest/tests/test_workflow_checked.py) | Shared checked acquisition/transform/publish sequence. |
| R6 | implemented-as-specified | [Runtime](../packages/sec-edgar-ingest/src/sec_edgar_ingest/runtime.py), [native dispatch tests](../packages/sec-edgar-ingest/tests/test_native_dispatch.py), [completion review](evidence/local-port/completion-review.md) | Exact replay, original producers, two-release continuation/repair verified. |
| R7 | implemented-as-specified | [Reconciliation tests](../packages/sec-edgar-ingest/tests/test_reconcile_workflow.py), [catalog](../packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/catalog.py) | Corrections/reverts supported; G4 is separate. |
| R8 | implemented-as-specified | [Coordinator](../packages/sec-edgar-ingest/src/sec_edgar_ingest/coordination.py), [coordination tests](../packages/sec-edgar-ingest/tests/test_coordination.py), [live config](../conf/sec-edgar-local.json) | Local pacing/fencing/drain; external sole issuer remains an owner operating fact. |
| R9 | implemented-as-specified | [Publisher](../packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/publication.py), [reader](../packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/reader.py), [workflow completion tests](../packages/sec-edgar-ingest/tests/test_workflow_completion.py) | Per-quarter CAS and validated captures; no global historical-completeness claim. |
| R10 | implemented-as-specified | [Operator commands](../packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/commands.py), [reconciliation acceptance tests](../packages/sec-edgar-ingest/tests/test_reconcile_acceptance.py) | Exact approval, supersession/reverts, and recorded rollback. |
| R11 | implemented-as-specified | [Config tests](../packages/sec-edgar-ingest/tests/test_local_config.py), [launcher tests](../packages/sec-edgar-ingest/tests/test_local_launcher.py), [live config](../conf/sec-edgar-local.json) | Bound paths/policies and archived native invocation evidence. |
| R12 | implemented-as-specified | [Final completion review](evidence/local-port/completion-review.md), [recovery runbook](../docs/runbooks/local-recovery.md) | Renewed offline gate and separate reviewed L12 supplement; originals remain incomplete/exit 12. |
| R13 | missing | [Completed design scope](completed/sec-edgar-local-spec.md#1-outcome-and-boundaries), [launcher](../scripts/sec-edgar-local); no scheduler definitions found in `scripts/` or config | Future local scheduling was outside the port; user now requests a future phase. |
| G1 | implemented-as-specified | [Completed local plan](plans/completed/1-sec-edgar-local-spec.md), [completion review](evidence/local-port/completion-review.md), [current config](../conf/sec-edgar-local.json) | Reviewed release selected; offline preflight passed. No broad coverage inferred. |
| G2 | missing | [Bounded acceptance](evidence/local-port/sec-acceptance.md); no broad accepted baseline report found | Quarterly 2024Q1 quarantine and 73 pending discoveries remain explicit acceptance limits. |
| G3 | missing | [Bounded acceptance](evidence/local-port/sec-acceptance.md); no full handoff-to-current catch-up acceptance found | Two selected daily bodies do not establish complete daily catch-up. |
| G4 | missing | [Offline renewal](evidence/local-port/offline-renewal-task15.md); no broad operational reconciliation acceptance found | Fixture/recovery tests establish behavior, not operational range acceptance. |
| G5 | missing | [Spec §4.10](sec-filing-index-ingestion-spec.md#410-future-local-scheduling); no local scheduler installation or observed schedule evidence found | Neither parent Azure schedules nor a manual run establish local scheduled operation. |

The Azure platform/schedule/identity/deployment requirements were deliberately replaced or excluded
by local spec §§2, 4.1, 4.9–4.10, and 9. They are owned by the original `sec-edgar` project; they
are not missing local implementation tasks. No parent ADR, absent stage spec, cloud API check,
container release, or source-project PR is needed to resume this roadmap.

Resume reconcile, 2026-10-22: no stage carries a new COMPLETE stamp. [Plan 2](plans/2-sec-filing-index-ingestion-spec.md)
is blocked at its Task 4 (Status line, Feasibility blocker); its Handoff (`:1668–1690`) is the carrier for
the amendments below. Engine source under `packages/sec-edgar-ingest/src` is unchanged since the
`fc68adef…` build revision `3ca50c7` (its manifest `git_revision`; empty `git diff 3ca50c7 HEAD`): `runner.run_workflow` still defers only at `now >= deadline` (plan 2 F8). The rubric
verdicts above stand; this resume does not re-run gap analysis.

Resume reconcile, 2026-10-27: Stage 1a carries a new COMPLETE stamp (plan 4). Its Handoff
(`specs/plans/completed/4-sec-filing-index-bounded-drain.md`, `## Handoff to later stages`) amends the
gap-analysis selection line above and Stages 2, 3 and 5 below; Stage 4 is unchanged ("Nothing
differs"). Stage 1a's `Produces` held as built, except that the live reserve is provisional (plan 4
D2, D4). Plan 3 DF6 is now open, but that merge belongs to the platform roadmap. The rubric verdicts
above stand; this resume does not re-run gap analysis.

## Open questions

One change set was put to the owner as a single approve-or-amend at the 2026-10-22 resume:

Insert Stage 1a (the D5 release) ahead of Stage 2, per plan 2 D5 and Handoff `:1673`, and keep every
existing stage number, because plan 2's header and Handoff and the platform roadmap cite them. Proposed
defaults inside that change: (i) Stage 1a carries `Gap closed: none directly`; it removes the F11 blocker
on G2 and G3, and its stage spec proposes any spec amendment it needs (for example to §4.7). (ii) No
separate investigation stage: the unexplained publish-time spread and the unmeasured closed-quarter
publish (plan 2 F11) change only Stage 1a's own design, so its design work measures them offline.
(iii) Stage 1a ends with the reviewed live-config `release_manifest` selection and offline preflight, as
Stage 1 did for `fc68adef…` (§4.8), so the plan 2 revision consumes a fixed effective-config hash. The
amendments to Stages 2–5 cite plan 2 D5 rather than Stage 1a, so they stand however this is answered.

*Owner's answer (2026-10-22):* approved as proposed. Owner's words: "Approve the Stage 1a
insertion with defaults (i)–(iii) as written in the roadmap's Open questions." Approval authorizes no
SEC request or live run.

One change set was put to the owner as a single approve-or-amend at the 2026-10-27 resume:

Insert Stage 1b (per-member cost) ahead of Stage 2, per plan 4 D2 and Handoff, and keep every existing
stage number. Proposed defaults inside that change: (iv) one stage, not an investigation stage plus a
build stage: diagnosing the engine gap and measuring the unmeasured marks change only Stage 1b's own
design, as default (ii) settled for Stage 1a. (v) Stage 1b takes the deferred items "Per-member cost",
"Unmeasured drain costs" and "Provisional live reserve", and the "B4 single-candidate limit" as a
revisit trigger; the test-hygiene and order-aware-proof items stay deferred. (vi) Stage 2 consumes
Stage 1b's release in place of the D5 release, and the plan 2 revision is written against it.

*Owner's answer (2026-10-27):* approved as proposed. Owner's words: "Approve as proposed
(Recommended)". Approval authorizes no SEC request or live run.

## Stages

Order follows dependency and evidence needs: accept operational baseline coverage before daily
catch-up and initial reconciliation, then design/enable unattended operation. This retains the
parent rollout's baseline-before-activation intent while replacing its completed implementation
and cloud deployment stages. Scheduling is included by the owner's rewrite instruction; this
partition and each stage's execution still need their normal review. It contains no implementation
task list and does not reopen the completed 16-task native plan. Proposed Stage 1a follows the same
dependency rule: Stages 2, 3 and 5 each need an invocation that ends with a durable result inside its
deadline (plan 2 F8, F11), so the release that provides it comes first. Stage 1b follows the same
rule: on the D5 release no reserve lets a full-size quarterly member fit one invocation (plan 4 D2),
so the release that cuts per-member cost comes before Stage 2. The spec ranks no stages, so
this order diverges from no spec ranking.

`Consumes` name the inputs needed to plan a stage. Each operational stage's plan must establish
its finite source scope, runtime/request/byte budget, evidence locations, and approval boundary.
Review of those campaign limits and confirmation of the sole-issuer condition are prerequisites
to live execution, not prerequisites to writing the plan that defines them.

- [x] Stage 1: Native local delivery and bounded acceptance
      Objective: Establish the completed native implementation and its reviewed release as the input to operational rollout.
      Spec: §§2.1, 3 R1–R12, 4.1–4.9, 5–6, 7 G1.
      Gap closed: R1–R12 implementation; G1.
      Consumes: The pinned parent import and approved local port design recorded by local plan 1.
      Produces: Native manual workflows/operators, versioned persistence/provenance, renewed offline proofs, and the separate reviewed bounded L12 result.
      Exit: Final local completion review approves the implemented contracts and both acceptance gates, retaining original incomplete run/verification and a separate supplemental pass.
      ROUTING: writing-plans

  > Stage 1: COMPLETE (2026-10-18) — implemented by plan 1 ([completed native local plan](plans/completed/1-sec-edgar-local-spec.md)). This stamp maps the existing completion record; no new stage execution occurred.
  > Next: resume the roadmap.

- [x] Stage 1a: Deadline-safe drain engine change and the D5 release (approved at resume, 2026-10-22)
      Objective: Ship a reviewed native release on which an invocation carrying the pending-source backlog ends with a durable workflow result inside its deadline.
      Spec: §3 R2, R5–R6, R12; §§4.2, 4.7–4.9, 5–6, 9; plan 2 D5, F8, F10, F11.
      Gap closed: None directly; removes the plan 2 F11 blocker that keeps G2 and G3 open.
      Consumes: Stage 1 release `fc68adef…` and its offline gate; plan 2 D5 and Handoff (`:1673–1676`) for the fix areas and measured inputs; the gate condition in `specs/evidence/baseline-campaign/campaign.md`, Release gate; [release upgrades](../docs/runbooks/release-upgrades.md). Platform roadmap D1 ("D5 first, platform after"): the release carries no platform item. Plan 3 DF6: the platform workspace member stays off `main` until this release is built.
      Produces: A stage spec and plan; the engine change with offline tests; the D5 release (its content-addressed release ID, setup and preflight evidence, and review record); the reviewed live-config selection with its effective-config SHA-256; and a plan Handoff that names every value the plan 2 revision must change, including any change to the §4.8 coordination values.
      Exit: Offline evidence on the D5 release shows the release side of the `campaign.md` Release gate: undispatched members defer before the deadline, or the pilot's drain fits one invocation with margin (the stage spec fixes what evidence counts for each; plan 2 F11); the offline checker and offline preflight pass on it, with `fc68adef…` and older releases retained (§4.9); its locked inputs carry no platform member; no SEC request was sent.
      ROUTING: brainstorming

  > Stage 1a: COMPLETE (2026-10-27) — implemented by plan 4 ([completed bounded-drain plan](plans/completed/4-sec-filing-index-bounded-drain.md)). Its Handoff section names what Stages 2–5 consume.
  > Next: resume the roadmap.

- [x] Stage 1b: Per-member cost and its release (approved at resume, 2026-10-27)
      Objective: Ship a reviewed native release on which every member a Stage 2 or Stage 3 invocation dispatches finishes inside one invocation, under a reserve set from measured costs.
      Spec: §3 R5, R9, R12; §§4.2, 4.6–4.9, 5–6, 9; plan 4 D2, D4.
      Gap closed: None directly; removes the plan 4 D2 per-member-cost limit that keeps G2 and G3 open.
      Consumes: The D5 release and its evidence (`specs/evidence/d5-release/`), with `measurement.md` and `finish-measurement.json` as the measured inputs and their stated limits; plan 4 D2, D4 and Handoff, "Next roadmap resume" bullet; `specs/deferred_items.md`, section `4-sec-filing-index-bounded-drain — 2026-10-27`, the four items named by default (v). Platform roadmap D1 and plan 3 DF6: the stage spec settles whether this release's locked inputs carry the platform member.
      Produces: A stage spec and plan; a diagnosis of the engine gap; measurements of the marks plan 4 never reached, or a spec record that they are not needed; the cost change with offline tests; a reviewed release with setup, preflight and review evidence; the reviewed live-config selection with a reserve set from measured costs and its effective-config SHA-256; and a plan Handoff that names every value the plan 2 revision must change.
      Exit: Offline evidence on the new release shows full-size quarterly members and open-quarter daily members at the high marks finishing within the launcher default minus the reserve, or the owner approves a named, measured limit; the offline checker and preflight pass on it, with the D5 release and older releases retained (§4.9); the provenance and reader contracts hold or an explicit versioned transition is reviewed (§9); no SEC request was sent.
      ROUTING: brainstorming

  > Stage 1b: COMPLETE (2026-10-28) — implemented by plan 5 (specs/plans/completed/5-sec-filing-index-per-member-cost.md). Its Handoff section names what Stages 2–5 consume.
  > Next: resume the roadmap.

- [ ] Stage 2: Baseline campaign and coverage decision
      Objective: Produce an accepted written finding on the requested historical baseline, including every unresolved exception.
      Spec: §§4.2–4.9, 5–6, 7 G2.
      Gap closed: G2.
      Consumes: Stage 1 evidence, the explicitly selected native release/current config, the intended range, and preserved live-root evidence. The [submissions findings](findings/sec-filing-submissions-findings.md) §§2, 4.6–4.7: daily indexes add back-dated rows to old filing quarters (Approved at resume, 2026-10-21). Plan 2 Tasks 1–3 and 8 as offline preparation (`4508859`, `7b63168`, `ea482dd`, `780ea51`, `4004f2e`). The D5 release, then a reviewed revision of plan 2 for it before Tasks 4–7, scoped by plan 2, Handoff `:1676` (Resolved at resume, 2026-10-22). The values that revision must change, read against the release selected when it is written: plan 4, Handoff, Stage 2 bullet (Resolved at resume, 2026-10-27). Stage 1b's release and Handoff; the plan 2 revision is written against that release, not the D5 release (default (vi), approved at resume, 2026-10-27).
      Produces: A reviewed finite campaign scope/budget, per-invocation results/captures, a source-and-quarter coverage inventory, and an explicit complete-or-incomplete operating decision.
      Exit: Every requested baseline unit is accounted for by validated publication or a named gap/quarantine with owner disposition; the committed port evidence, immutable live-root objects and releases remain intact, and the absent L12 external directory stays recorded as lost (§6, `780ea51`; plan 2, Handoff; Resolved at resume, 2026-10-22).
      ROUTING: writing-plans

- [ ] Stage 3: Daily catch-up acceptance
      Objective: Establish accepted manual daily continuation over the handoff and retained pending inventory.
      Spec: §§4.2–4.9, 5, 7 G3.
      Gap closed: G3.
      Consumes: Stage 2 coverage decision and explicit exceptions, retained discovery boundaries/pending work, and selected native release/current config. The D5 release, since F11 applies to a `daily` invocation too, and the pending inventory from Stage 2's `final/coverage.json` `daily_sources` plus a fresh discovery (plan 2 D5, O5, F4, Handoff; Resolved at resume, 2026-10-22). The D5 cutoff semantics (parent spec §4.7) and their overrun limit for a member running at the cutoff (plan 4 D4, Handoff, Stage 3 and Stage 5 bullet; Resolved at resume, 2026-10-27).
      Produces: A dated catch-up report with exact results/captures, boundary evidence, and unresolved-work disposition usable by later scheduling.
      Exit: Handoff-to-current daily discovery and pending units are accounted for without skipping failed directories or erasing older gaps; the owner accepts the reported coverage/limits.
      ROUTING: writing-plans

- [ ] Stage 4: Manual reconciliation acceptance
      Objective: Establish accepted operational reconciliation and operator handling before unattended reconciliation.
      Spec: §§4.2, 4.4, 4.6–4.9, 5, 7 G4.
      Gap closed: G4.
      Consumes: Stages 2–3 reports/exceptions, selected native release/config, and retained candidate/history/approval/rollback contracts. Stage 2's `gated` units and reconciliation-bound quarantine dispositions, and the closed-quarter quarterly-membership limit (plan 2 F5, F7, O6, O10, Handoff; Resolved at resume, 2026-10-22).
      Produces: A reconciliation report with exact source/candidate/generation evidence and accepted change, gate, revert, quarantine, and recovery dispositions.
      Exit: The reviewed range has a retained manual refresh outcome, every unresolved candidate/gap has explicit disposition, and required approvals name exact authority without bypassing refusal rules.
      ROUTING: writing-plans

- [ ] Stage 5: Local scheduling and observed-operation acceptance
      Objective: Design and validate unattended local invocation of the accepted workflows.
      Spec: §§2.2–2.3, 3 R13, 4.7–4.10, 5–6, 7 G5.
      Gap closed: R13; G5.
      Consumes: Stages 2–4 accepted operating reports/limits and the existing native launcher; no scheduler mechanism or cadence is assumed approved. The D5 release and plan 2's invocation rules: work fits one invocation (F8), and no member is after the pinned end (F9) (plan 2 D5, Handoff; Resolved at resume, 2026-10-22). The D5 cutoff semantics (parent spec §4.7) and their overrun limit for a member running at the cutoff (plan 4 D4, Handoff, Stage 3 and Stage 5 bullet; Resolved at resume, 2026-10-27).
      Produces: A reviewed scheduler design/implementation, disabled installation and explicit enable/disable records, operating/recovery documentation, and observed scheduled-run evidence.
      Exit: R13 has scheduler-specific verification and accepted actual daily/reconciliation executions linked to durable results/logs; missed-run, overlap, host lifecycle and DST policies are exercised or their approved limits recorded.
      ROUTING: brainstorming

## Stage-spec stamp

Each future stage spec's Rollout note, copied into its plan header, carries:

> Roadmap: specs/sec-filing-index-ingestion-roadmap.md, Stage N — on plan completion, tick the
> stage and re-validate later stages against what shipped.

Completion requires an implementing plan or accepted investigation finding and its evidence. Add:

> Stage N: COMPLETE (YYYY-MM-DD) — implemented by plan <id> (path).
> Next: resume the roadmap.

Do not tick a stage from an exit code, source-project stamp, manual smoke, or this rewrite alone.
Stage 1 is the explicit retrospective exception supported by the already completed local plan.
Future plan handoffs must name changed assumptions for later stages; historical artifacts stay
unchanged when new configuration or operating evidence is added.

## Completion

The owner reviews this local partition before Stage 2, and each inserted stage (1a, 1b) before it is
routed; approving either authorizes no SEC request or live run. Rewriting these files starts no campaign,
installs/enables no schedule, and grants no live-access or budget authorization. On a later request
to resume, use derive-roadmap to reconcile actual completion stamps and route only the first
unticked stage whose planning Consumes are met. Its plan must establish the additional live-execution
gates above before any acquisition. Stage 2 is a planning handoff, not a direction to rerun the
completed port or genuine acceptance harness. Do not plan the whole roadmap as one implementation.

Retire this roadmap/spec only after a final conformance audit accounts for R1–R13 and G1–G5 using
local implementation, operational, and observed-schedule evidence. Keep “approved incomplete
coverage” distinct from complete historical coverage. Unmet requirements need a new stage or an
explicit written deferral in `specs/deferred_items.md`; they do not vanish through retirement.
If parked earlier, retain self-contained remaining work and label the parked status explicitly.

Preserve the existing data root, all releases, retired native plan/design, original incomplete
acceptance results, and separate reviewed supplemental L12 pass. Future evidence is additive;
it never relabels the original execution or turns bounded acquisition into historical coverage.
