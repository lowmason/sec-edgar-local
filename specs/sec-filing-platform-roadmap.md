> For agentic workers: REQUIRED SKILL: derive-roadmap — resume via its
> reconcile step; route each unticked stage per its ROUTING line; never plan
> this document wholesale.

**Status:** Provisional, 2026-10-21. The stage partition waits for the owner's review. Four open
questions go with that review (see Open questions). The partition below applies their defaults. No
stage is approved, and this roadmap authorizes no SEC request.

## Gap analysis

**Project:** `/Users/lowell/Projects/sec-edgar-local`.
**Source:** [Filing platform spec](sec-filing-platform.md) at `25f8c57`, which the owner approved on
2026-10-21. IDs R1–R31 and V1–V17 are its Requirements and Verification items. Locators `(M …)` and
`(C …)` keep the spec's meaning.
**Package boundary:** [ADR 0001](adr/0001-build-the-filing-platform-as-its-own-workspace-package.md)
(Accepted). Its required safeguards and follow-on items are rows below, because stages must discharge
them.
**Separate roadmap:** This roadmap stands alone. It adds no stage to the
[ingestion roadmap](sec-filing-index-ingestion-roadmap.md). Catalog-side work that the platform needs
is staged here, with a stated dependency on the catalog.

Search boundary: `packages/`, `scripts/`, `conf/`, the root `pyproject.toml` and `specs/`. No
platform package exists. No code there handles Feed archives, inline XBRL document sets,
`submissions.zip`, `<PRIVATE-TO-PUBLIC>` or an exchange calendar. The spec's status line says that
nothing is implemented. `specs/deferred_items.md` does not exist. Other facts found:

- The live store holds catalog generations for 16 filing quarters of 2021–2026 only
  ([findings](findings/sec-filing-submissions-findings.md) §2).
- The manual 2026-10-15 Feed download (findings §4.2) is no longer at `/tmp/sec-filings` (checked
  2026-10-21).
- Plan 2's Handoff calls this spec "awaiting owner review"
  (`specs/plans/2-sec-filing-index-ingestion-spec.md:1678`). That line is stale. The spec is approved
  (spec line 6).

Paths without a directory are under `packages/sec-edgar-ingest/src/sec_edgar_ingest/`. The Note
column names the stage or stages that close each row.

| Req | Verdict | Evidence | Note |
|---|---|---|---|
| R1 | missing | none found | Each stage covers its components' M Pn.e criteria. R1 closes at the completion review. |
| R2 | missing | none found. The catalog reader exists (`etl/reader.py`). | Selection: Stage 11. Coverage: Stage 12. |
| R3 | missing | none found | Rules 1, 2, 5: Stage 5. Rule 7: Stage 6. Rules 3, 4, 6: Stage 11. |
| R4 | missing | One lane. It serves `daily` first and the rest in arrival order (`coordination.py:194`, `models.py:347`). Guards are constants of 90 s and 64 MiB (`config.py:26-27`). Live mode requires an exact match (`config.py:241-242`). | Stage 4. |
| R5 | missing | none found | Catalog-side exchange: Stage 4. Platform transport: Stage 5. |
| R6 | missing | The R4 guard constants. | Guard: Stage 4. Routing to the bulk lane: Stage 5. |
| R7 | missing | none found | URL class: Stage 4. Snapshot: Stage 5. P3 cross-check: Stage 7. P4 and P8 use: Stage 9. Planning use: Stage 11. V4: Stage 6. |
| R8 | missing | none found | P3 cross-check: Stages 1, 7. P1 tier: Stage 11. V5: Stage 6. |
| R9 | missing | none found | Header state: Stages 1, 7. Revision on rows: Stage 8. Refetch: Stage 11. V6: Stage 6. |
| R10 | missing | none found | Stage 8. |
| R11 | missing | none found | Stage 8. V7, V8: Stage 6. |
| R12 | missing | none found | Stage 8. |
| R13 | missing | none found | Stage 8. |
| R14 | missing | none found | Stage 7. |
| R15 | missing | none found. The critique quotes fragments of the PDS spec v2.0, but not its DTD (critique lines 25, 114, 128). | Draft: Stage 1. Freeze: Stage 7. V9: Stage 6. |
| R16 | missing | none found | Draft: Stage 1. Freeze: Stage 7. V10: Stage 6. |
| R17 | missing | none found | Stage 9. |
| R18 | missing | none found | Draft: Stage 2. Freeze: Stage 7. V11: Stage 6. |
| R19 | missing | none found | Draft: Stage 2. Freeze: Stage 7. V12: Stage 6. |
| R20 | missing | none found | Draft: Stage 2. Freeze: Stage 7. V11: Stage 6. |
| R21 | missing | none found | Stage 10. |
| R22 | missing | none found | Draft: Stage 3. Freeze: Stage 7. |
| R23 | missing | none found | Draft: Stage 3. Freeze: Stage 7. |
| R24 | missing | none found | Draft: Stage 3. Freeze: Stage 7. |
| R25 | missing | none found | Stage 9. |
| R26 | missing | The catalog's protocol exists (`etl/publication.py:65`). It imports catalog modules (ADR 0001, Context item 5). | Compressed retention: Stage 5. Protocol reuse: Stage 8, after ADR 0002 (Stage 4). |
| R27 | missing | none found | Stage 10. |
| R28 | missing | none found | Stage 8. |
| R29 | missing | none found | Composition: Stage 11. Operation: Stage 13. |
| R30 | missing | none found | Measurement: Stage 6. Owner budget: Stage 12. |
| R31 | missing | none found | Composition: Stage 11. Backfill: Stage 12. Daily: Stage 13. |
| V1 | missing | not run | Stage 6. |
| V2 | missing | not run | Stage 6 (owner decision D3). |
| V3 | missing | not run | Stage 6 (D3). |
| V4 | missing | not run | Stage 6 (D3). |
| V5 | missing | not run | Stage 6. |
| V6 | missing | not run | Stage 6. |
| V7 | missing | not run. The 2026-10-15 archive with the 101 tagged submissions is not retained locally. | Stage 6. |
| V8 | missing | not run | Stage 6. |
| V9 | missing | not run | Stage 6. Q3 bounds the sample years. |
| V10 | missing | not run | Stage 6. |
| V11 | missing | not run | Stage 6 under the Q2 default. Stage 2 if the owner answers Q2 "no". |
| V12 | missing | not run | Stage 6 under the Q2 default. Stage 2 if the owner answers Q2 "no". |
| V13 | missing | not run | Stage 2. |
| V14 | missing | not run | Stage 8. |
| V15 | missing | not run | Stage 3. |
| V16 | missing | not run | Stage 10. |
| V17 | missing | not run | Stage 12. |
| ADR 0001: platform package | missing | `pyproject.toml:19-20` lists one member. | Stage 1. |
| ADR 0001: import direction and export diff | missing | none found | Stage 1. Each later stage that changes dependencies repeats the diff. |
| ADR 0001: platform URL classes | missing | `urls.py:55-56` and `urls.py:62-63` accept index paths only. | Stage 4. |
| ADR 0001: protocol-version guard and shared validator | missing | `coordination.py` has no governor protocol version. | Stage 4. |
| ADR 0001: multi-application releases | missing | `runtime.py:130-131` rejects other applications. `release.py:260` requires one application wheel. `release.py:233-235` reads `uv.lock`. | Stage 4. |
| ADR 0002 | missing | not written | Stage 4. |

No row is implemented-as-specified, implemented-differently, in-code-but-not-in-spec or
out-of-repo. The catalog code cited for R2, R4, R6 and R26 is the base that those rows change or
reuse. It is not a platform implementation.

## Open questions

These four questions form one set for the owner's review of the partition. Each has a default, and
the stages below apply it. Record the owner's answer under each question. Then amend the stages that
the answer changes, and remove the Provisional status.

- **F1 — When the platform package joins the workspace.** The new member edits the root
  `pyproject.toml` (`:19-20`) and the shared `uv.lock`. The next catalog release build reads both
  (`release.py:233-235`). Under D1, that next build is the D5 release. Question: may the package join
  before the D5 release is built? Default: yes, if
  `uv export --package sec-edgar-ingest --no-dev --no-emit-workspace` is byte-identical before and
  after the member is added (ADR 0001, Consequences). Otherwise the package joins after the D5 build.
  Effect if wrong: the platform changes the locked inputs of the release that ingestion Stage 2 waits
  for. Changes: Stage 1 `Consumes`.
  *Owner's answer:* pending.
- **Q2 — SEC documentation under D2.** Stage 1 needs the PDS spec v2.0 and its DTD as the R15 grammar
  source. V11 needs the EDGAR Filer Manual and V12 the EDGAR XBRL Guide. V7 and V8 cite SEC
  documentation too. These documents are on `www.sec.gov`. The governor's URL classes do not admit
  them, and the critique quotes only fragments. Question: does D2 cover documentation reads? This is
  the owner's decision. Default: yes, because D2 says "no exception", and a wrong "yes" only delays
  work while a wrong "no" breaks the owner's rule. Under the default, Stage 4 adds a documentation URL
  class. Stage 1 drafts the grammar from the critique's fragments and the evidence note. V11 and V12
  move to Stage 6, and Stage 7 confirms the grammar against the PDS spec. Alternative: no. Then each
  named document is fetched once by hand and kept under `specs/evidence/` with its URL, date and
  SHA-256. Stage 1 then uses the PDS spec and DTD, and V11 and V12 return to Stage 2. Changes: Stages
  1, 2, 4, 6 and 7.
  *Owner's answer:* pending.
- **Q3 — R2 and the evidence sample.** R2 lets the platform acquire only submissions that the pinned
  catalog lists. V1 stratifies its sample by year, and V9 names a 2015-on sample. The live catalog
  lists 2021–2026 quarters only (findings §2), and ingestion Stage 2 has not run. Question: does R2
  bind Stage 6's sample? Default: yes. Stage 6 draws its sample from submissions that the pinned
  catalog lists when the stage runs. The finding names each year that it could not sample as a limit.
  Stage 12 checks V1 and V9 on each newly accepted year before it publishes that year. Alternative:
  Stage 6 waits for the ingestion Stage 2 coverage decision. Effect if wrong: the parser freeze rests
  on 2021–2026 evidence only, or all evidence waits for the whole catalog baseline. Changes: Stages
  6, 7 and 12.
  *Owner's answer:* pending.
- **Q4 — A build stage that D2 does not name.** D2 puts the release (step 2) directly before the
  evidence (step 3). Live mode requires the native runtime (`config.py:237-238`), and ADR 0001 makes
  the platform use the catalog's validator. So a reviewed release of the platform application with
  governed fetch and retention must exist before the evidence campaign. Question: where does that
  work go? Default: its own stage (Stage 5), between the release and the evidence. This follows the
  repository's pattern of a build stage before a campaign stage. It makes the wait for evidence longer
  than D2 assumed. Alternative (b): fold the fetch work into Stage 6, which then builds and campaigns
  in one cycle. Alternative (c): ship the platform's fetch code in Stage 4's release. That strains
  ADR 0001's rule that a platform change does not cut a catalog release. Effect if wrong: a longer wait for evidence,
  an oversized Stage 6, or a catalog release that carries platform code. Changes: Stages 4, 5 and 6.
  *Owner's answer:* pending.

## Stages

**Order (owner decision D2, 2026-10-21).** The owner chose "No exception": no SEC request goes
outside the governor, even for evidence. Parser work starts on hand-built fixtures in the meantime.
D2 fixes this order:

1. P3, P5 and P6 parser work over hand-built fixtures (Stages 1–3).
2. The platform's catalog release (Stage 4).
3. V1, V7, V10 and the real-submission sample (M P3.e), with V2, V3 and V4 under D3 (Stage 6).
4. The parser freeze (Stage 7).

Stage 5 sits between steps 2 and 3. D2 does not name it, and Q4 puts it to the owner.

**Comparison with the spec.** The order departs from the spec's Rollout note (spec lines 451–456) in
two places, and D2 causes both:

- The note says that the retained sample of real submissions "comes first". Here Stages 1–3 start
  parser work over fixtures before the sample exists.
- The note puts evidence before the governor change. Here Stage 4 changes the governor before Stage 6
  gathers evidence.

The note's rule that V1, V7 and V10 block the parser freeze still holds: Stage 7 consumes Stage 6.
The order agrees with the note on the storage gate before backfill (Stage 12) and on catalog coverage
as the bound on platform coverage (Stages 12–13). It does not follow the critique's priority ranking,
which puts acquisition first. No stage can fetch a real file before the platform's catalog release
(ADR 0001, Context items 1–3).

**Parallel work.** Stages 2 and 3 depend on Stage 1 only. Stage 4 depends on Stage 1 and on the D5
release, which is outside this roadmap. Stages 2, 3 and 4 may therefore run at the same time, each in
its own session, when their `Consumes` are met.

**Live gates.** `Consumes` name the inputs needed to plan a stage. A stage that sends SEC requests
needs an owner-approved scope, budget and evidence location before its first live request (spec
Rollout note). Approval of a plan is not live authority.

- [ ] Stage 1: Platform package and envelope parser
      Objective: Add the platform workspace package with a P3 envelope parser that passes hand-built fixtures, with no SEC request.
      Spec: R1 (M P3), R8 (P3 cross-check), R9 (header state), R15, R16. ADR 0001 Decision and Consequences.
      Gap closed: ADR 0001 rows for the platform package, the import direction and the export diff. Draft parts of R8, R9, R15 and R16.
      Consumes: ADR 0001 (Accepted). The F1 answer for when the member joins the workspace. The Q2 answer for the R15 grammar source. Owner decision D2: no SEC request.
      Produces: The named platform package in the workspace. A draft $\nu_E$ that yields $\Sigma_y$, $\mathcal{D}_y$, the header state and the R16 classes for both serializations. An import-direction test.
      Exit: Fixture tests pass for both serializations, line-initial closing tags, retained unknown tags and each R16 class. The import-direction test passes. The ingest export diff is recorded and meets the F1 answer. No SEC request was sent.
      ROUTING: writing-plans

- [ ] Stage 2: XBRL fact extraction over fixtures
      Objective: Build the P5 fact extractor over hand-built fixtures, with no SEC request.
      Spec: R1 (M P5), R18, R19, R20, V13.
      Gap closed: V13. Draft parts of R18, R19 and R20.
      Consumes: Stage 1's $\mathcal{D}_y$ and R16 classes. The Q2 answer for the V11 and V12 sources. ADR 0001: evaluation tools such as Arelle stay in a dev dependency group.
      Produces: A draft $\nu_X$ with IXDS assembly, R18 fact keys, R19 duplicate classes and revision test, and the multi-valued cover record.
      Exit: Each V13 case passes as a fixture test. The ingest export diff is unchanged. No SEC request was sent.
      ROUTING: writing-plans

- [ ] Stage 3: Ownership records over fixtures
      Objective: Build the P6 typed-record extractor over hand-built fixtures, with no SEC request.
      Spec: R1 (M P6), R22, R23, R24, V15.
      Gap closed: V15. Draft parts of R22, R23 and R24.
      Consumes: Stage 1's $\mathcal{D}_y$ and R16 classes.
      Produces: A draft $\nu_O$ with typed records, the R23 13F rules and the R24 amendment row set.
      Exit: Each V15 case passes as a fixture test. No SEC request was sent.
      ROUTING: writing-plans

- [ ] Stage 4: Platform catalog release
      Objective: Cut the owner-reviewed catalog release that lets the platform send requests through the shared governor.
      Spec: R4, R6 (guard), the catalog side of R5 and R7. ADR 0001 Consequences (the Negative safeguards and the Neutral follow-on items). Spec Rollout note (the owner approves the governor change).
      Gap closed: R4. R6 guard. Catalog side of R5 and R7. ADR 0001 rows for URL classes, the protocol-version guard and shared validator, multi-application releases and ADR 0002.
      Consumes: The D5 release, built and reviewed (plan 2 D5, `specs/plans/2-sec-filing-index-ingestion-spec.md:82`), which the ingestion roadmap's next resume stages (plan 2, Handoff, `:1673`). Owner decision D1 (2026-10-21), "D5 first, platform after": the D5 release ships first and carries no platform item, and this release follows as its own reviewed release. It does not wait for the ingestion Stage 2 coverage decision. Stage 1's package as the second application. Plan 2, Handoff (`:1678`): a later catalog campaign revision re-checks the coordination values. The Q2 answer (a documentation URL class under the default) and the Q4 answer.
      Produces: A reviewed release with platform URL classes, a bulk lane, three priorities, a governor protocol version in the lease record, platform governor settings read through the catalog's validator, and multi-application build and verify. Owner decision D3 (2026-10-21), "Ship with V2 open": a failed bulk transfer restarts from the first byte (spec lines 393–394), and bulk guards are sized from recorded Feed sizes (M EN, C C1). ADR 0002 on shared code.
      Exit: The owner approves the governor change and the release. Tests show the three priorities in order, a failed bulk transfer restarted from the first byte, refusal on a protocol-version mismatch, and a two-application build and verify. ADR 0002 is Accepted. The ingest export diff is recorded.
      ROUTING: brainstorming

- [ ] Stage 5: Governed retrieval and retention
      Objective: Release the platform application's governed fetch and retention of Feed archives, complete submission files and `submissions.zip`, tested offline.
      Spec: R1 (M P2), R3 rules 1, 2 and 5, R5, R6 (routing), R7 (snapshot), R26 (compressed retention).
      Gap closed: R3 rules 1, 2 and 5. R5. R6 routing. R7 snapshot. R26 retention part.
      Consumes: Stage 4's release and ADR 0002. Stage 1's header accession parse (R3 rule 1). The Q4 answer.
      Produces: A reviewed release whose platform application fetches and retains snapshots through the governor. Each snapshot record names its serialization and content encoding.
      Exit: Offline tests show members mapped by header accession, separate member snapshots, an archive snapshot record, a new snapshot for a regenerated archive, decoded-byte hashes with the encoding recorded, the identity fallback and oversize routing to the bulk lane. The owner reviews the release. No campaign starts.
      ROUTING: writing-plans

- [ ] Stage 6: Evidence campaign and finding
      Objective: Produce an owner-accepted finding on V1–V12 and a retained real-submission sample from a bounded live campaign through the governor.
      Spec: V1–V10, V11 and V12 (Q2 default), R3 rule 7, R30 (volume measurement), M P3.e, spec Rollout note.
      Gap closed: V1–V12. R3 rule 7. R30 measurement part.
      Consumes: Stage 5's release. The Stage 1–3 drafts, to read the sample. Owner decision D2, step 3. Owner decision D3: V2, V3 and V4 join this stage. A new governed fetch of the 2026-10-15 Feed archive for V7, because the local copy is gone (findings §4.2, checked 2026-10-21). The Q3 answer for the sample years. An owner-approved scope, budget and evidence location.
      Produces: The retained sample (M P3.e) in Stage 5's snapshot format. A finding with one result for each of V1–V12. The measured compressed volume of each quarter for R30.
      Exit: Each of V1–V12 has a recorded result, or a named open item with an owner disposition. The sample manifest is committed. The campaign stayed inside its approved budget.
      ROUTING: writing-plans

- [ ] Stage 7: Parser freeze
      Objective: Revise the P3, P5 and P6 drafts against the retained sample and freeze their versions.
      Spec: R7 (P3 cross-check), R8 and R9 (P3 parts), R14, R15, R16, R18–R20, R22–R24. M P3.e, M P5.e, M P6.e. Spec Rollout note (V1, V7 and V10 block the freeze).
      Gap closed: R14. R15, R16, R18–R20 and R22–R24 in full. R7, R8 and R9 P3 parts.
      Consumes: Stage 6's finding and sample. The Stage 1–3 drafts. The Q3 answer.
      Produces: Frozen $\nu_E$, $\nu_X$ and $\nu_O$ versions, with the sample as regression fixtures.
      Exit: Each frozen version parses the whole sample, and each refusal has a recorded reason. The grammar, the parsed time fields and the extraction carriers follow the V1, V7 and V10 results. Each R14 disagreement is recorded as a gap.
      ROUTING: writing-plans

- [ ] Stage 8: Point-in-time store and views
      Objective: Publish per-quarter platform generations with the four times, tombstones and both view clocks.
      Spec: R1 (M P7, M P9 evidence contract), R9 (revision on rows), R10–R13, R26 (protocol reuse, decoded-byte spans), R28, V14.
      Gap closed: R10–R13. R28. V14. R26 protocol part. R9 row part.
      Consumes: ADR 0002 (Stage 4). Stage 6's V7 and V8 results for R11 rules 2 and 3. Stage 7's frozen producers. Stage 5's retained snapshots.
      Produces: Generations that grow by union, with "moved" and "withdrawn" tombstones. $\mathrm{Known}^{\mathrm{SEC}}_t$, $\mathrm{Known}^{\mathrm{plat}}_t$, $\mathrm{AsOf}_t$, $\mathrm{First}$ and $\mathrm{Current}$. A frozen $\nu_{\mathrm{cal}}$.
      Exit: Each V14 sequence passes. A generation publishes by conditional replace in a fixture store. Evidence spans verify against decoded retained bytes. $\nu_{\mathrm{cal}}$ is frozen as a versioned table.
      ROUTING: writing-plans

- [ ] Stage 9: Entity history and events
      Objective: Derive P4 attribute and ticker histories and P8 events from the frozen producers' outputs.
      Spec: R1 (M P4, M P8), R7 (P4 observations, P4 and P8 cross-checks), R17, R25.
      Gap closed: R17. R25. R7 P4 and P8 parts.
      Consumes: Stage 7's frozen producers (header, cover record, Forms 3, 4 and 5). Stage 8's views and $\nu_{\mathrm{cal}}$. Stage 5's `submissions.zip` snapshot.
      Produces: Entity observations and ticker intervals timed at $t^{\mathrm{pub}}$. Events with $\nu_I$ and their links.
      Exit: Sample and fixture tests show ticker observations from both R17 sources, a $\nu_I$ with effective date ranges and Item 8.01 marked, and one event row per item.
      ROUTING: writing-plans

- [ ] Stage 10: Publication quality gates
      Objective: Decide whether a frozen $\nu_X$ is fit to publish, and review level-B fields under a stated policy.
      Spec: R1 (M P9 review), R21, R27, V16.
      Gap closed: R21. R27. V16.
      Consumes: Stage 7's frozen $\nu_X$ and Stage 6's sample. Stage 5's release for governed fetches of SEC-hosted references: taxonomy packages, DERA data sets and companyfacts (D2). Stage 9's level-B producers. An owner-approved scope and budget for those fetches.
      Produces: An evaluation against the three R21 references. A threshold fixed on the regression sample before the first publication. Level-B review records.
      Exit: A $\nu_X$ version meets the V16 conditions, or is recorded as not fit with its residuals. Each level-B producer version has a review record with its sample size and error bound.
      ROUTING: brainstorming

- [ ] Stage 11: Run composition and accounting
      Objective: Compose backfill, daily, audit and replay runs with run reports and coverage accounting, tested offline.
      Spec: R1 (M P1, M P10), R2 (selection), R3 rules 3, 4 and 6, R7 (planning use), R8 (P1 tier), R9 (refetch), R29, R31.
      Gap closed: R2 selection part. R3 rules 3, 4 and 6. R7 planning part. R8 P1 part. R9 refetch part. R29 composition. R31 composition.
      Consumes: Stage 5's release. Stages 7, 8 and 9.
      Produces: Released run workflows with one outcome per run and a coverage ratio per quarter.
      Exit: Fixture runs show selection from the pinned catalog only, a recorded gap for each unlisted Feed member, newest-quarter-first order, repair only when no archive holds a submission, a header refetch after a lineage change, a reported audit detection bound and a backfill that yields to the catalog's daily window.
      ROUTING: writing-plans

- [ ] Stage 12: Storage gate and first backfill
      Objective: Record the storage budget and run the first platform backfill over catalog-accepted quarters.
      Spec: R2 (coverage), R30, R31 (backfill), V17, spec Rollout note.
      Gap closed: R30. V17. R2 coverage part. R31 backfill part.
      Consumes: Stage 11's runs. Stage 10's fit $\nu_X$ version. Stage 6's measured volume. The ingestion roadmap's Stage 2 coverage decision for each quarter in range (R2). The Q3 answer. The owner's storage budget and an owner-approved campaign scope and budget.
      Produces: Published platform generations for accepted quarters. A coverage report by quarter.
      Exit: The backfill plan records the measured volume and the owner's budget before the first backfill request. Each requested quarter is covered, or named as a gap with an owner disposition. No quarter is covered before the catalog accepts it.
      ROUTING: writing-plans

- [ ] Stage 13: Daily continuation acceptance
      Objective: Establish accepted daily platform runs after the catalog's daily run.
      Spec: R29 (operation), R31 (daily).
      Gap closed: R29 operation part. R31 daily part.
      Consumes: Stage 12's coverage report. The ingestion roadmap's Stage 3 daily catch-up acceptance. An owner-approved scope and budget.
      Produces: A daily run report with coverage changes and an audit result.
      Exit: Daily runs take each evening's Feed archive after the catalog's daily run. Each late-public submission lowers its quarter's coverage ratio until that submission is complete. The audit's detection bound is recorded.
      ROUTING: writing-plans

## Stage-spec stamp

Each future stage spec's Rollout note, copied into its plan header, carries:

> Roadmap: specs/sec-filing-platform-roadmap.md, Stage N — on plan completion, tick the stage and
> re-validate later stages against what shipped.

On completion, add this stamp under the stage's entry. The stamp is authoritative:

> Stage N: COMPLETE (YYYY-MM-DD) — implemented by plan <id> (path). Its Handoff section names what <stages> consume.
> Next: resume the roadmap.

Drop the second sentence when the plan has no `## Handoff to later stages` section, or when that
section reads `None`.

## Completion

The owner reviews this partition and the four open questions before Stage 1. Approval of the
partition authorizes no SEC request. After approval, route Stage 1 per its ROUTING line in a fresh
session. On a later resume, reconcile the stage stamps and each completed plan's Handoff. Then route
the first unticked stage whose `Consumes` are met.

Retire this roadmap only after a conformance audit accounts for R1–R31, V1–V17 and the ADR 0001
rows, with evidence from each stage. R1 closes there, when each component's M Pn.e criteria have
evidence. An unmet row needs a new stage, or a written deferral in `specs/deferred_items.md`.
Approved incomplete coverage stays distinct from complete coverage. When this roadmap retires, the
methodology and the critique retire with the spec.
