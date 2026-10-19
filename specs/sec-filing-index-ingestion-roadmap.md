> For agentic workers: REQUIRED SKILL: derive-roadmap — resume via its
> reconcile step; route each unticked stage per its ROUTING line; never plan
> this document wholesale.

## Gap analysis

**Project:** `/Users/lowell/Projects/sec-edgar-local`.
**Rewritten:** 2026-10-18, replacing the copied Azure roadmap in place.
**Source:** [Local filing-index spec](sec-filing-index-ingestion-spec.md). Requirement and gate IDs
below refer to its §§3 and 7. **Status:** local stage partition proposed for review; no remaining
stage is started or approved for execution by this rewrite. The owner requested inclusion of a
future local scheduling phase; its design remains open.

The native port is complete, not a scaffold. Its [retired plan](plans/completed/1-sec-edgar-local-spec.md)
and [final completion review](evidence/local-port/completion-review.md) control delivery status.
The checked local Stage 1 below is a retrospective mapping to that completed plan; it does not
import parent-project stage numbers, replay their history, or create a new completion claim.
The current config now selects `fc68adef…` (§4.8 of the spec); acceptance-time old-default statements
remain historical. No deferred-items file exists at this review boundary; the completed port
records nothing deferred.

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

## Stages

Order follows dependency and evidence needs: accept operational baseline coverage before daily
catch-up and initial reconciliation, then design/enable unattended operation. This retains the
parent rollout's baseline-before-activation intent while replacing its completed implementation
and cloud deployment stages. Scheduling is included by the owner's rewrite instruction; this
partition and each stage's execution still need their normal review. It contains no implementation
task list and does not reopen the completed 16-task native plan.

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

- [ ] Stage 2: Baseline campaign and coverage decision
      Objective: Produce an accepted written finding on the requested historical baseline, including every unresolved exception.
      Spec: §§4.2–4.9, 5–6, 7 G2.
      Gap closed: G2.
      Consumes: Stage 1 evidence, the explicitly selected native release/current config, the intended range, and preserved live-root evidence.
      Produces: A reviewed finite campaign scope/budget, per-invocation results/captures, a source-and-quarter coverage inventory, and an explicit complete-or-incomplete operating decision.
      Exit: Every requested baseline unit is accounted for by validated publication or a named gap/quarantine with owner disposition; original port acceptance evidence remains intact.
      ROUTING: writing-plans

- [ ] Stage 3: Daily catch-up acceptance
      Objective: Establish accepted manual daily continuation over the handoff and retained pending inventory.
      Spec: §§4.2–4.9, 5, 7 G3.
      Gap closed: G3.
      Consumes: Stage 2 coverage decision and explicit exceptions, retained discovery boundaries/pending work, and selected native release/current config.
      Produces: A dated catch-up report with exact results/captures, boundary evidence, and unresolved-work disposition usable by later scheduling.
      Exit: Handoff-to-current daily discovery and pending units are accounted for without skipping failed directories or erasing older gaps; the owner accepts the reported coverage/limits.
      ROUTING: writing-plans

- [ ] Stage 4: Manual reconciliation acceptance
      Objective: Establish accepted operational reconciliation and operator handling before unattended reconciliation.
      Spec: §§4.2, 4.4, 4.6–4.9, 5, 7 G4.
      Gap closed: G4.
      Consumes: Stages 2–3 reports/exceptions, selected native release/config, and retained candidate/history/approval/rollback contracts.
      Produces: A reconciliation report with exact source/candidate/generation evidence and accepted change, gate, revert, quarantine, and recovery dispositions.
      Exit: The reviewed range has a retained manual refresh outcome, every unresolved candidate/gap has explicit disposition, and required approvals name exact authority without bypassing refusal rules.
      ROUTING: writing-plans

- [ ] Stage 5: Local scheduling and observed-operation acceptance
      Objective: Design and validate unattended local invocation of the accepted workflows.
      Spec: §§2.2–2.3, 3 R13, 4.7–4.10, 5–6, 7 G5.
      Gap closed: R13; G5.
      Consumes: Stages 2–4 accepted operating reports/limits and the existing native launcher; no scheduler mechanism or cadence is assumed approved.
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

The owner reviews this local partition before Stage 2. Rewriting these files starts no campaign,
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
