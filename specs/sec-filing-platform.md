# SEC EDGAR filing platform — Design Spec

> For agentic workers: REQUIRED NEXT SKILL: derive-roadmap — do not plan
> this spec directly and do not split it into per-subsystem plans.

**Status:** Synthesized 2026-10-21 and awaiting owner review. Nothing is implemented. This spec
authorizes no live SEC traffic.
**Project:** `/Users/lowell/Projects/sec-edgar-local`.
**Roadmap:** none yet. derive-roadmap writes `specs/sec-filing-platform-roadmap.md`. Platform work
never adds stages to the [ingestion roadmap](sec-filing-index-ingestion-roadmap.md).

Build the point-in-time filing platform above the filing-index catalog. For every submission that
the catalog lists, the platform keeps the SEC's original bytes and parses the envelope. It extracts
as-filed XBRL facts and ownership records and derives deterministic events. It publishes immutable
per-quarter generations that read as they were known at any instant. The
[methodology description](sec-filing-platform-methodology.md) is the base design. This spec amends
it where the [first-pass critique](sec-filing-platform-critique.md) or the repository's own
evidence showed it wrong or weak. These are the four largest changes:

- Acquire through the SEC daily Feed, not one request per submission.
- Process inline XBRL as document sets.
- Treat headers as revisable.
- Keep SEC time, public time and platform time apart.

**Design provenance.** The sources are the methodology description
`specs/sec-filing-platform-methodology.md` (commit `6fafce2`) and its critique
`specs/sec-filing-platform-critique.md` (commit `d681dad`). The critique is a first pass with no
adjudication in Chat. This session triaged its 34 points. On 2026-10-21 the owner approved every
verdict and chose option A for both open decisions: Q1, the acquisition unit, and Q2, the storage
scope. Locators:

- `(M P5.p1)` is methodology component P5, procedure step 1. `.f` is the problem formulation, `.a` an
  assumption, `.e` the evaluation criteria and `.q` an open question.
- `(M XA4)` is cross-component assumption 4, `(M SQ1)` system open question 1, `(M EN)` the evidence
  note and `(M notation)` the shared notation table.
- `(C C5)` is critique point C5. `(C §3 P9.2)` is a Part 3 answer and `(C §4.8)` a Part 4 item.
- `triage:` marks a verdict that was not a plain accept. `local count` marks a check made during
  triage against the stored indexes, with no SEC request.

Symbols are the methodology's. The requirements define the few new ones where they first appear.

## Motivation

The methodology was written before any component ran. The critique and the local checks found
errors that would corrupt data or stall acquisition.

- **Acquisition does not finish in useful time.** The stored 2024Q1 index lists 245,683 distinct
  submissions in 370,321 rows (local count). The governor sends one request at a time, and the
  next start waits until the current download drains. Download time therefore adds to request
  time. One Feed day was 20.7 GB unpacked and arrived at 6.4 MB/s on one link (M EN). At these
  figures, per-submission backfill takes about 3–5 days per quarter, or about 2 days with gzip.
  The Feed takes about 3–6.5 hours per quarter (C C1, C C2, triage Q1).
- **XBRL extraction is wrong for most current filings.** Inline XBRL documents form one set
  (C C3). The `<XBRL>` tag also marks traditional XBRL files, and SEC-generated instances would
  double every fact (C C4). A rounding difference counts as an inconsistency (C C6).
- **Two load-bearing assumptions fail.** Post-acceptance corrections change header fields under
  the same accession (C C5). Some submissions become public years after acceptance (M EN). The
  views mix SEC time with platform time (C C10).
- **Sizes break the guards.** Three files on one day exceed the 256 MiB guard, and the SEC states
  a 400 MB maximum (C C9, M EN). One quarter is about 1.0–1.9 TB uncompressed at 2024–26 volumes
  (C C25, triage: corrected with measured figures).
- **Form names changed.** The stored 2024Q1 index lists 226 rows under `SCHEDULE 13D` and
  `SCHEDULE 13G` types. The daily indexes of 2026-10-14 and 2026-10-15 list only those names
  (local count, C C13).

## Core principle — retained bytes are the authority, and every time is named

Every stored value re-derives from retained bytes through a versioned producer (M composition,
M P9). Every view states which clock it reads: SEC acceptance, public availability or platform
publication. No view presents one clock as another (C C10, C C16, M EN). Where a requirement rests
on an unverified fact about the SEC, it says so and names the check that settles it.

## Requirements

`(open)` stands for `(open — resolved by verification, not argument)`. Each `(open)` names the
Verification bullet that discharges it.

### Base design

**R1 — The methodology is the base design.** Components P1–P10 behave as the methodology
describes, except where a requirement below changes them. Each component's evaluation criteria are
requirements too (M P1.e–P10.e).

### Acquisition (P1, P2)

**R2 — The catalog stays the only listing.** A submission is acquired only when the pinned
catalog lists it (M XA1, M P1.e). Feed members, `submissions.zip` and SEC data sets annotate or
check catalog submissions. They never create one. A Feed member that the pinned catalog does not
list is recorded as a gap. The platform covers a quarter only after the catalog accepts it
(M XA1).

**R3 — Acquire through the daily Feed.** Backfill and daily runs acquire the SEC daily Feed
archive, one per business day, and split it into submission snapshots (C C1, M SQ1, M P1.q1).

- (chosen) The Feed for bulk acquisition. Per-submission fetch of the complete submission file
  stays as the repair path for gaps, audit and oversize work (C C1, triage Q1 option A).
- (rejected) Per-submission fetch only, with gzip and a higher governor rate (C C2, Q1 option B).
- (rejected) Per-submission fetch only at the current governor: about 90–250 days of backfill
  (Q1 option C).

Rules:

1. A member maps to its submission by the header accession, not by its file name. File names are
   `<accession>.nc` or `<accession>.corrNN` (M EN).
2. Each snapshot records its serialization: Feed member or complete submission file. Members are
   retained as separate compressed snapshots, so a reader reaches one submission without its
   archive. The archive's hash, size and member list form its own snapshot record. Whether the
   archive bytes are also kept after the members verify is decided at the storage gate (R30).
3. Backfill takes every Feed archive of a quarter's business days, newest quarter first (C C18).
   A catalog submission that no archive of its quarter holds goes to the repair path.
4. On the repair path, order is quarter-major, newest first (C C18, M P1.p5).
5. A regenerated archive has a new hash, so it is a new archive snapshot (C C1, C §4.10).
6. Feed archives do not reflect later removals. Removals come only from catalog withdrawals
   (C C1, M P10.a2).
7. On a sample, Feed members are compared with complete submission files by document payload hash
   (C C1, C §3 system 1). (open: V1)

**R4 — The governor gains a bulk lane and a third priority.** This changes the catalog's shared
governor (catalog methodology C2):

- A bulk lane has its own exchange deadline and byte guards, sized from the Feed listings. Archives
  reach about 6.1 GB (C C1). Transfers resume after failure (C C1). (open: V2)
- Three priorities apply: catalog daily, then platform daily, then backfill and audit
  (C §3 system 10, C §3 P1.3, M P1.q3, M SQ10).
- The owner-wide rate target stays r = 3 per second (C C2, triage Q1 option A). The methodology
  never called the resulting 1.5 per second the SEC's limit. It is the governor's own ceiling
  (C §4.8, triage: framing rejected).

The bulk lane also carries `submissions.zip` (R7) and oversize repairs (R6).

**R5 — Per-submission transport.** Repair fetches request gzip content encoding. The platform
hashes and retains the decoded bytes as the original bytes and records the content encoding
(C C19, M P2.p4). It sends conditional requests when the SEC returns validators (C §3 P2.1).
Without gzip support, identity encoding stays. (open: V3)

**R6 — Size guards.** The per-submission byte guard is at least 400 MB plus a margin (C C9, M EN).
A submission that cannot finish within the per-request deadline moves to the bulk lane. It is not
parked by default, and no size excludes a submission for good (C §3 P2.3, M P2.q3).

**R7 — Planning metadata.** A nightly `submissions.zip` snapshot, fetched through the bulk lane,
gives size, acceptance time, items and XBRL flags per accession (C C17, C §3 P4.1).

- The plan uses it for pre-run size totals, oversize pre-screening and routing hints (M P1.e).
- P3, P4 and P8 use it as a cross-check, never as an input (C §3 P3.1).
- P4 takes former names, tickers and exchanges from it as observations, timed at the snapshot
  receipt (M P4.q1).
- `.hdr.sgml` is the header-only refetch (R9, R29).

(open: V4)

**R8 — Combined filings.** A submission may carry more than one form type. Then $f_y$ is a set and
its tier is the highest-priority tier of the set. A set that the header confirms is not a gap
(M EN, M P1.p2, M P3.p5). (open: V5)

### Identity, revisions and time

**R9 — Headers are revisable, documents are not.** This replaces cross-component assumption 5
(M XA5, C C5).

- A submission's header state is identified by $(a_y, v)$. The header revision $v$ counts distinct
  header states in order of first receipt. Every derived row carries $v$ beside $\theta_y$.
- The document payload hashes $h_\delta$ are the immutable layer. Evidence spans therefore survive a
  header revision (C C5, M P9.a3).
- A changed filing date, form type or other header field is a new revision, not a gap
  (C C5, M P3.p5).
- When the lineage walk shows a changed filing date or form type for an acquired submission, the
  plan refetches its header (C C5, C C23, M P1.p4).

(open: V6)

**R10 — A moved submission leaves its old quarter explicitly.** Generations grow by union only
(M composition, M P7.p3). When the pinned catalog moves a submission to another quarter, the old
quarter gains a tombstone with reason "moved" and the target quarter. The new quarter gains the
submission under its new header revision (C C5, triage: accept, with this mechanism). Any other
tombstone has reason "withdrawn" (M P7.p5).

**R11 — Four times per submission.** Every submission and event row stores these times:

- $t^{\mathrm{acc}}$, the acceptance instant from the header (M P3.p2).
- $t^{\mathrm{pub}}$, the public-availability instant, with its rule and precision (C C16, M EN).
- $\tau_x$, the first local receipt (M P2.p6, C C16).
- $t^{\mathrm{tx}}$, the first platform publication: when a generation first included the row
  (C C10).

$t^{\mathrm{pub}}$ follows these rules:

1. By default $t^{\mathrm{pub}} = t^{\mathrm{acc}}$, at second precision (C C16).
2. A submission tagged `<PRIVATE-TO-PUBLIC>` takes the day of the first Feed archive or daily index
   that carries it, at day precision (M EN). If the platform holds neither, it takes the receipt
   time of the first catalog generation that listed the submission, as an upper bound (C C16).
   (open: V7)
3. An acceptance after the dissemination cutoff takes the next business day, at day precision, if
   V8 confirms next-day dissemination (C C16). (open: V8)

**R12 — Views name their clock.** Two operators replace $\mathrm{Known}_t$ (C C10, M P7.p6):

- $\mathrm{Known}^{\mathrm{SEC}}_t$ admits rows with $t^{\mathrm{pub}} \le t$. It excludes a row
  whose removal interval (R13) ended at or before $t$, and it flags a row when $t$ falls inside
  that interval.
- $\mathrm{Known}^{\mathrm{plat}}_t$ admits rows with $t^{\mathrm{tx}} \le t$. It excludes rows
  tombstoned in a generation published at or before $t$. It reproduces what a run at $t$ could
  read.

$\mathrm{AsOf}_t$, $\mathrm{First}$ and $\mathrm{Current}$ use $\mathrm{Known}^{\mathrm{SEC}}_t$ by
default and accept $\mathrm{Known}^{\mathrm{plat}}_t$ as a parameter. Session assignment $s(\cdot)$
applies to $t^{\mathrm{pub}}$. A view option treats acceptances within a configured window before
the close as next-session (C C16).

**R13 — Tombstones carry an interval.** A tombstone stores the last catalog generation that listed
the submission, the first that did not, their receipt times and $t^{\mathrm{det}}$
(C C26, M P7.a2, M P7.q3). No SEC-side removal time exists outside the fee-based dissemination
feed (C C26).

**R14 — Eastern time cross-check.** The acceptance times in `submissions.zip` (R7) check the
Eastern-to-UTC conversion of $t^{\mathrm{acc}}$. A disagreement is a gap (C C17, M XA9).

### Envelope parsing (P3)

**R15 — Two serializations, one grammar source.** P3 parses the tagged dissemination format of
Feed members and the labeled-line format of the complete submission file.

- The grammar comes from the SEC's Public Dissemination Service technical specification and its
  DTD (C §1b, C §3 P3.3).
- A document block ends only at a line-initial closing tag (C §3 P3.3, M P3.a3).
- Unknown labels and tags are retained, not refused (C §3 P3.2, M P3.p2, M P3.q2).
- The header fields of the two formats are compared on the V1 sample (C §3 P3.1, M P3.q1).
- Required fields stay as M P3.p2 states. (open: V9)

**R16 — Classify documents by type and root.** The encoding class comes from the declared type and
the root element after unwrapping `<XBRL>` (C C4, M P3.p4).

- `<XBRL>`-wrapped EX-101 instances, schemas and linkbases are traditional XBRL, not inline XBRL.
- Documents described as `IDEA: XBRL DOCUMENT` are SEC-generated. They are retained and classified
  but never extracted. The SEC-extracted instance among them is kept as an evaluation reference
  (C C4, R21).

(open: V10)

### Entity history (P4)

**R17 — Ticker history from as-filed symbols.** Level-A ticker observations come from two sources
(C C20, M P4.q2):

- Cover-page trading-symbol and exchange facts, per security (R19).
- The issuer trading symbol in Forms 3, 4 and 5.

Each observation is timed at its submission's $t^{\mathrm{pub}}$. These sources add to the
ticker-file snapshots (M P4.p4) and to R7. Cover tagging phased in from 2019 to 2021 by filer
status, and early 8-Ks are exempt (C C20, C §4.7). Names are not reconciled across CIKs
(M P4.p5, C §3 system 6).

### Structured facts (P5)

**R18 — Inline XBRL document sets.** P5 assembles every inline XBRL document of a submission into
one Inline XBRL Document Set (IXDS) before extraction (C C3, M P5.p1).

- Contexts, units and continuations resolve across the set.
- Exhibits that the EDGAR Filer Manual processes separately, such as filing-fee exhibits, form
  their own sets.
- Facts are keyed by (accession, header revision, IXDS, fact id) (C C3, M P5.p4, M P7.a6).
- An unresolved reference refuses the set.

(open: V11)

**R19 — Duplicates, cells, revisions and the cover record.**

- Within an IXDS, duplicates are classed complete, consistent or inconsistent, per the XBRL
  International note on duplicate facts. A consistent group keeps its most accurate value
  (C C6, M P5.p4).
- The cell $\kappa$ gains the language of a non-numeric fact. Decimals stays out of the cell and
  only decides consistency (C C6, triage: accept, modified).
- Across filings, a later value is a revision only when the value intervals implied by decimals do
  not intersect (C C6).
- $\mathrm{AsOf}_t$ stays latest-accepted. A revision-flagged view joins $\mathrm{First}$
  (C C6, C §3 system 5, C §3 P7.2, M P7.q2).
- The cover record is multi-valued by dimension: shares outstanding per class, and symbol and
  exchange per security (C C12, M P5.p5).
- A fact's entity is the context identifier, qualified by the legal-entity axis member when one is
  present (C C12, M SQ5). (open: V12)

**R20 — Complete transformation registry.** $\mathcal{R}$ holds every Transformation Registry
version that the EDGAR Filer Manual permits, plus the SEC's own transformations. A null value then
marks a filer error, not a coverage gap (C C7, C §3 P5.2, M P5.a2). (open: V11)

**R21 — References for fact accuracy.** A version of $\nu_X$ is evaluated against these
references, in order (C C7, C C8, C §3 system 9, M SQ9):

1. Arelle's output for the same IXDS, and the SEC-extracted instance (R16), per accession.
2. The DERA Financial Statement and Notes data sets, which include custom tags and dimensions.
3. Companyfacts.

Standard taxonomy packages are fetched once and retained as content-addressed artifacts. Arelle
and the DQC sign and scale rules use them (C C7, triage: accept in part). The stored fact model
stays taxonomy-free (M P5.a1). A version of $\nu_X$ is fit to publish when four conditions hold
(C §3 system 9):

- Exact agreement with reference 1 on non-dimensional numeric facts, above a threshold fixed on the
  regression sample before the first publication.
- An explanation for every residual.
- No unexplained sign or scale disagreement.
- Coverage measured in both directions.

The methodology's description of the DERA data sets is corrected (C C8, C §4.1).

### Ownership records (P6)

**R22 — Schedule 13D and 13G types.** $\nu_F$ tiers both type families as ownership: the legacy
`SC 13D` and `SC 13G`, and the structured `SCHEDULE 13D` and `SCHEDULE 13G`, each with amendments
(C C13, local count). P6 detects XML schedules per document, never by a date (M P6.p1). A schedule
without XML yields no typed record (M P6.a3, C §3 system 7 rejected). The 10 p.m. cutoff for these
forms enters the reading of the filed-as-of date (C C13, M P3.f).

**R23 — Form 13F units and amendments.** $\mathcal{V}$ keys on the filing date. Reports filed on or
after 2023-01-03, amendments included, state values in dollars (C C14, M P6.a5). A restatement
supersedes its original, and a new-holdings amendment supplements it. A 13F holdings view applies
these rules, and a range check flags likely thousand-fold errors (C C14, M P6.p4).

**R24 — Form 4 amendments.** Amendment rows form a second row set, linked to the original by the
declared original date, the reporting owner and the issuer. A level-B field records the amendment
scope: full, partial, administrative or unknown. No amendment replaces its original by default
(C C15, M P6.q2). The trading-plan checkbox is a level-A field (M P6.f, C C22, triage: rejected
except this field).

### Events (P8)

**R25 — Effective-dated item crosswalk.** $\nu_I$ maps (title, effective date range) to
(regime, number) (C C21, C §3 P8.2, M P8.q2).

- Pre-2004 items keep their own regime. A map to current numbers exists only where the meanings
  match.
- The item table marks Item 8.01 as a catch-all (C C21).
- Events stay one row per item (C §3 P8.1, M P8.q1).
- Follow-up candidates stay at this level (M P8.p6, M P8.q3, C C21, triage: accept in part, move
  to the semantic layer rejected).

### Store and provenance (P7, P9)

**R26 — Keep the catalog's publication protocol.** P7 reuses the catalog's per-quarter generation
and conditional-pointer protocol (M P7.p2–P7.p10).

- (chosen) The catalog's tested protocol, shared by both systems.
- (rejected) An open table format (C C11, M P7.q1). A change of format spans both systems and
  belongs in a design decision record.

Retained bytes are stored compressed. Evidence spans address decoded payload bytes and verify
after decoding (triage Q2 option A, M P9.p2).

**R27 — Review policy and grade detail.** The four levels stay. Each level-B producer records its
pattern id and structural anchor (C §3 P9.1, M P9.q1). Level-B fields get a minimum review policy
(C §3 P9.2, M P9.q2):

- Stratified random review per (producer version, field class).
- A sample size set by a stated error bound, for example zero errors in 59 reviews for 5% at 95%
  confidence.
- A repeat on every change of $\nu$.

**R28 — Maintained calendar.** $\nu_{\mathrm{cal}}$ is generated from a maintained exchange-calendar
library for the New York Stock Exchange, early closes included, and frozen as a versioned table
(C C24, M P7.a4). A PROV-DM mapping is rejected because nothing consumes it yet (C C24, triage:
accept in part).

### Runs and capacity (P10)

**R29 — Targeted audit.** The audit refetches the header of every submission whose catalog rows
changed (R9). It adds a random sample and reports its detection bound by the rule of three. The
alias check stays a small fixed sample (C C23, M P10.q1, M P2.p8).

**R30 — Storage gate.** Before the first backfill, the plan measures the compressed volume of the
requested range from the Feed listings, one listing request per quarter, and records it
(C C25, M P1.e). The owner records a storage budget at that gate. The backfill does not start
before the budget exists (triage Q2 option A). The scope stays every listed submission from 2015Q1
on (M notation). The estimate at 2024–26 volumes is about 1.0–1.9 TB uncompressed, or about
75–150 GB compressed, per quarter (C C25, M EN, triage: corrected with measured figures).

**R31 — Workflow cadence.** The daily run takes that evening's Feed archive after the catalog's
daily run (C C1). The backfill runs as one long-lived process that holds the bulk lane and yields
to the catalog's daily window (C §3 P10.2, M P10.q2). Coverage follows M P10.p9. A late-public
submission lowers its quarter's coverage ratio until it is complete (M EN).

## Verification

Every methodology evaluation criterion holds (R1). These checks are added:

- **V1 — Serialization reconciliation (R3, R15).** On a sample stratified by tier and year, the
  document payload hashes of each Feed member equal those of its complete submission file. Header
  fields agree, or each difference has an explanation.
- **V2 — Resumable transfer (R4).** One test shows whether sec.gov honors range requests on a Feed
  archive. Without them, the bulk lane restarts a failed transfer from the first byte.
- **V3 — Transport (R5).** One per-submission fetch shows whether the Archives return gzip content
  encoding, an entity tag or a last-modified date.
- **V4 — Submissions metadata (R7).** One `submissions.zip` snapshot shows the `items` format and
  the precision of old acceptance times.
- **V5 — Combined filings (R8).** The headers of the three 2024Q1 key pairs with two form types
  show whether each pair is one submission.
- **V6 — Corrections (R9).** Refetches of submissions whose `DATE AS OF CHANGE` is later than their
  filing date show whether the archive copy changes. SEC documentation or a comparison of
  `.corrNN` members shows what the suffix means.
- **V7 — Late-public submissions (R11).** SEC documentation confirms the meaning of
  `<PRIVATE-TO-PUBLIC>`. The acceptance lines of the 101 tagged submissions of 2026-10-15 show
  which instant they carry. A few of their complete submission files show whether that format
  carries the tag too.
- **V8 — Dissemination cutoff (R11).** SEC documentation, or acceptance times compared with Feed
  days, shows whether a late acceptance is disseminated that evening or on the next business day.
- **V9 — Acceptance lines (R15).** Every submission in the 2015-on sample has an acceptance line
  (C §3 system 7).
- **V10 — SEC-generated documents (R16).** The complete submission files of the sample show whether
  they hold `IDEA: XBRL DOCUMENT` documents and whether the public document count includes them.
- **V11 — Filer Manual tables (R18, R20).** The current EDGAR Filer Manual gives the exhibit types
  processed apart from the IXDS and the permitted Transformation Registry versions.
- **V12 — Axis conventions (R19).** The EDGAR XBRL Guide confirms the per-class and legal-entity
  axis conventions.
- **V13 — XBRL fixtures (R16, R18, R19).** Hand-built and sample submissions cover these cases: a
  multi-document IXDS, a separately processed exhibit, an `<XBRL>`-wrapped traditional instance, an
  SEC-extracted instance that is not counted twice, consistent and inconsistent duplicates, and a
  rounding-only change across filings that is not a revision.
- **V14 — Time model (R10–R13).** Hand-built sequences show three things. A late-public submission
  is absent from $\mathrm{Known}^{\mathrm{SEC}}_t$ before its release day. A moved submission is in
  exactly one quarter at every $t$. $\mathrm{Known}^{\mathrm{plat}}_t$ reproduces a recorded
  earlier read.
- **V15 — Ownership fixtures (R22–R24).** Fixtures cover both 13D and 13G type families, a 13F
  amendment filed after 2023-01-03 for an earlier period, a 13F restatement and addition, and a
  partial Form 4/A.
- **V16 — Fact accuracy gate (R21).** A version of $\nu_X$ publishes only after it meets the R21
  conditions on the regression sample.
- **V17 — Storage gate (R30).** The plan of the first backfill records the measured volume and the
  owner's budget.

## Out of scope

- Model-based extraction, narrative sectioning, text-change measures, and level-C and level-D
  fields (M P9.f).
- A taxonomy semantic layer with labels, calculations and presentation (C C7, triage: deferred).
- An open table format (C C11, rejected). It is a design-decision candidate for both systems.
- Routine-versus-opportunistic insider classification (C C22, rejected).
- Rule-based extraction from pre-XML 13D and 13G schedules (C §3 system 7, rejected).
- A PROV-DM mapping (C C24, rejected).
- A higher governor rate target (C C2, triage Q1 option A).
- Typed Form 144 records. Form 144 carries XML but is not one of P6's families (M EN).
- External ticker or security-master vendors, and name reconciliation across CIKs
  (M P4.q2, C §3 system 6).
- The fee-based Public Dissemination Service feed (C C26).

## Rollout note

- **The governor change opens the rollout.** R4 changes the catalog's shared governor. The
  platform roadmap stages that change as its own work, with a stated dependency on the catalog. No
  stage is added to the ingestion roadmap. The owner approves the change to the shared governor.
- **Evidence comes before parsers.** V1, V7 and V10 block the parser freeze. They decide the
  grammar, the time model and the extraction carriers. The retained sample of real submissions
  (M P3.e) comes first.
- **The storage gate blocks backfill.** V17 must hold before the first backfill.
- **Catalog coverage bounds platform coverage.** The platform covers a quarter only after the
  catalog accepts it (R2). The catalog's baseline campaign is Stage 2 of the ingestion roadmap.
- **No live traffic is authorized here.** Each live campaign needs an explicit scope, a budget and
  retained evidence.
- **This spec stands alone.** It is not a stage of another roadmap, so it carries no roadmap stamp.
