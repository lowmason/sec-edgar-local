# SEC EDGAR filing platform methodology

> For agentic workers: when specs/sec-filing-platform-critique.md exists beside this
> file, REQUIRED SKILL: describe-critique-methodology (synthesize mode) —
> do not draft a spec directly.

The system builds and maintains, above the filing-index catalog described in
specs/sec-filing-index-ingestion-methodology.md (the catalog spec), a point-in-time store of
the filings themselves. For every submission the catalog lists it acquires the SEC's complete
submission file and keeps the original bytes; parses the submission envelope into a header
record with its acceptance instant, its filers and its documents; extracts as-filed XBRL facts
and typed ownership records from the documents that carry them; derives deterministic events
from current-report items, amendments and exhibits; and publishes everything, one calendar
quarter of filing dates at a time, as immutable generations that can be read as they were known
at any instant. This document describes the method as math and prose, independent of its code.
It treats the system as running on the same host and stores as the catalog: the same local
store of immutable files, the same transactional store of versioned records and the same lease
record, so that every request either system sends to the SEC passes through the catalog's
governor (its C2).

**Evidence status.** The system is being built now. Nothing in this document has run against
the live SEC, and no component has been measured: submission file sizes, header and document
irregularities, parse-refusal rates, fact and record counts, throughput, storage and runtime
are all unknown. The catalog it consumes is implemented and tested offline (see the catalog
spec). The only measured figures used here are the catalog's sampled row counts and the
governor's rate ceiling; every other number is a selected limit. The SGML, XBRL and XML layouts
described below are the design's reading of the SEC's published formats and have not yet been
checked against retained real submissions; fixing the parsers against such a sample is the
first evaluation step of P3, P5 and P6. Scope is acquisition, envelope parsing, entity
attributes, XBRL facts, ownership XML, the point-in-time store and deterministic events.
Model-based extraction, narrative sectioning and text-change measures are out of scope and will
be specified separately; this document fixes only the provenance contract they must meet (P9).

## Component inventory

| Component (by methodological role) | Estimand / output | Consumes |
|---|---|---|
| P1. Submission selection and acquisition plan | The ordered, budgeted set $\mathcal{W}$ of submissions to acquire in a run, each with its location, aliases, tier and reason; one outcome per planned submission | The pinned catalog vector $\vec{g}$; the tier table $\nu_F$; carry-over $\mathcal{P}$; budget $b$ and the deadline |
| P2. Submission acquisition and retention | For each planned submission one validated snapshot $x_y$ of the complete submission file, original bytes retained, pinned to the plan | P1's plan; C2's permission to send; earlier accepted snapshots |
| P3. Envelope parsing and document split | The submission record $\Sigma_y$ and document set $\mathcal{D}_y$ of each snapshot, or refusal of the submission with a line and reason | Retained bytes; $\nu_E$, $\nu_I$ |
| P4. Entity attribute history | As-filed attribute observations per CIK, ticker observation intervals, and the as-of operator over them | $\Sigma_y$ of every parsed submission; ticker-file snapshots |
| P5. Structured fact extraction | The as-filed fact set $F_y$ and cover record of each XBRL-bearing document, or refusal of that document | $\mathcal{D}_y$; $\nu_X$ |
| P6. Ownership record extraction | Typed records $\Upsilon_y$ from Forms 3/4/5, Schedule 13D/G and 13F XML documents, or refusal of that document | $\mathcal{D}_y$; $\nu_O$ |
| P7. Point-in-time store, views and publication | The generation $\Gamma_q$ of each quarter; the view operators $\mathrm{Known}_t$, $\mathrm{AsOf}_t$, $\mathrm{First}$, $\mathrm{Current}$; session assignment $s(\cdot)$; tombstones, approval and rollback records | P3–P6 and P8 outputs; $\vec{g}$ and its lineage; $\nu_{\mathrm{cal}}$ |
| P8. Event derivation and linkage | Level-A and level-B event records $\mathcal{E}_y$ with provenance; amendment, exhibit and follow-up links | $\Sigma_y$, $\mathcal{D}_y$, $\Upsilon_y$, cover records; $\nu_I$ |
| P9. Provenance grading, evidence contract and review | The level of every derived field; evidence spans re-verifiable against retained bytes; review records | P3–P8 outputs; operator reviews |
| P10. Workflow composition and run accounting | Backfill, daily, audit and replay runs; per-submission work units; a run report with coverage accounting and one run outcome | P1–P9; $\vec{g}$; configured $q_0$, $q_1$, $b$; the run deadline |

## Composition

Symbols are defined in the Notation section below; symbols of the catalog spec keep their
meaning. A run pins $t^\star$, the catalog vector $\vec{g} = (g_q)_{q \le q^\star}$ — each
coordinate read and verified under the catalog's reader contract (its C6, step 1) — and the
version vector $\nu$, then composes the components through immutable, content-addressed
references. No stage follows a mutable "latest", and no stage follows the catalog's pointers
after the pin.

$$
\mathcal{A} = \bigcup_{q \le q^\star} A_q[g_q], \qquad
R_y = \{\, k \in \mathcal{A} : a(k) = a_y \,\}, \qquad
\mathcal{Y} = \{\, y : R_y \ne \emptyset \,\}, \qquad
\mathcal{W} = \mathrm{Plan}(\mathcal{Y},\ \mathcal{P},\ \lambda,\ b).
$$

For each $y \in \mathcal{W}$, in plan order and under the governor:

$$
x_y = \mathrm{Acquire}(y), \quad
(\Sigma_y, \mathcal{D}_y) = \mathrm{Envelope}(x_y;\ \nu_E, \nu_I), \quad
\Phi_y = \mathrm{Entity}(\Sigma_y), \quad
F_y = \mathrm{Facts}(\mathcal{D}_y;\ \nu_X), \quad
\Upsilon_y = \mathrm{Own}(\mathcal{D}_y;\ \nu_O), \quad
\mathcal{E}_y = \mathrm{Events}(\Sigma_y, \mathcal{D}_y, \Upsilon_y;\ \nu_I, \nu_{\mathrm{cal}}),
$$

every output addressed by $\theta_y = (\sigma_y, h_{x_y}, \nu)$ and carrying
$(a_y, t^{\mathrm{acc}}_y, d_y)$. A submission belongs to the quarter of its catalog filing
date, $Q(d_y)$, whatever periods its contents describe. The platform generation of quarter $q$
advances by union only:

$$
\Gamma_q^{+} = \Gamma_q \ \cup\ \{\, \theta_y : y \text{ complete under } \nu,\ Q(d_y) = q \,\}
\ \cup\ \mathrm{Tomb}_q(\vec{g}),
$$

where $\mathrm{Tomb}_q(\vec{g})$ holds a tombstone for each submission dated in $q$ every one of
whose rows the catalog withdrew between the previously pinned vector and $\vec{g}$. The pointer
$\Pi^{\mathcal{P}}_q$ moves only by conditional replace on its version; a lost replace re-reads,
merges and retries at most $n_{\mathrm{pub}}$ times. Readers derive every time-dependent view
from the stored rows, never from the publication order:

$$
\mathrm{Known}_t(S) = \{\, z \in S : t^{\mathrm{acc}}_{y(z)} \le t \ \wedge\
\neg\,\mathrm{tomb}(y(z), t) \,\}, \qquad
\mathrm{AsOf}_t(\kappa) = \max_{\succ_{\mathrm{acc}}} \{\, \varphi \in \mathrm{Known}_t(F) :
\kappa(\varphi) = \kappa \,\}, \qquad
s(t) = \min\{\, j : \mathrm{close}(j) > t \,\},
$$

with $\succ_{\mathrm{acc}}$ ordering by acceptance instant, then accession number (P7). The
published state at any instant is the vector $(\Gamma_q)_{q \le q^\star}$. Each coordinate
changes atomically; the vector does not. A reader that needs a reproducible multi-quarter view
records the vector it read together with $\vec{g}$ and $\nu$. Only acquisition reaches the SEC
(P2, the ticker-file snapshot of P4 and the evaluation cross-checks of P5 and P6), and only
through the governor. Parsing, extraction, event derivation, publication and every view read
retained bytes and stored rows only.

## Cross-component assumptions

1. **The catalog is the only filing list.** A submission is acquired only if the pinned
   catalog lists it, and discovery of filings is the catalog spec's job. *Breaks if:* the
   catalog is incomplete, stale or wrong about a row; the platform inherits the gap and cannot
   see it. Catalog disagreements found while parsing (P3) are recorded as gaps, never used to
   acquire anything.
2. **One coordination domain, shared with the catalog.** The same governor, lease record and
   stores serve both systems, so both draw on one request budget and one owner-wide SEC
   ceiling. *Breaks if:* any process or tool sends SEC requests outside the governor (catalog
   spec, cross-component assumption 1).
3. **Accession identifies a submission; the complete submission file is its authority.** The
   same accession under every filer's path serves the same bytes, and every document of the
   filing is inside that one file. *Breaks if:* the SEC serves different bytes under different
   filer paths, or omits a document from the complete file; the audit run's alias check (P2,
   P10) is the only detection.
4. **Acceptance is the public-availability instant.** The header's acceptance instant is taken
   as the instant after which the filing was public on EDGAR. *Breaks if:* dissemination lagged
   acceptance, or the same information was public earlier elsewhere (a press release, an
   exchange notice). The platform records EDGAR timing only and makes no claim about first
   public disclosure.
5. **Submissions are immutable after dissemination.** Corrections arrive as new accessions
   (amendments) or as catalog withdrawals, not as changed bytes under the same accession.
   *Breaks if:* the SEC changes bytes in place (the header carries a date of last change); the
   change is seen only when the path is fetched again, which reuse mode never does and audit
   mode does for a sample.
6. **Pinned versions.** The version vector $\nu$, the effective configuration and the code build
   identity are fixed at run start and recorded; outputs of different versions are never
   combined, and a view names the version it reads. *Breaks if:* versions mix; replay is then
   neither deterministic nor reproducible (catalog spec, cross-component assumption 5).
7. **Storage semantics** are those of the catalog spec (write-once files, atomic insert-if-absent
   and conditional replace, durable once acknowledged, indefinite retention). *Breaks if:* any
   of these fails. Here the retained bytes are the whole public text of every listed filing for
   the covered range, so growth is unbounded and unmeasured.
8. **Per-submission independence, per-quarter atomicity.** Submissions are acquired, parsed and
   extracted independently; a generation changes one quarter at a time; nothing spans quarters
   atomically. *Breaks if:* a consumer reads "current" across quarters during a run; it can see
   a mix of generations.
9. **Eastern time.** Header timestamps are Eastern local time without an offset. Conversion to
   UTC uses a versioned zone table and keeps the original string. *Breaks if:* the SEC's clock
   or daylight-saving handling differs from the table; the instant is then wrong by the
   difference while the string stays right.

## Notation

Subscripts are dropped when the submission is clear from context. A superscript $+$ marks a
value after one update. Symbols of the catalog spec keep their meaning here: $c$, $p$, $n$,
$f$, $d$, $a$, $k$, $H$, $Q$, $A_q$, $g_q$, $\Pi_q$, $\Delta_q$, $\mathcal{X}_q$, $t^\star$,
$q^\star$, $r$, $\epsilon$, $T_{\mathrm{ex}}$, $N$, $n_{\mathrm{pub}}$, $n_{\max}$, $\delta_0$,
$\delta_{\max}$, $\delta^{\mathrm{srv}}$, $\xi$. Where a symbol below shadows a component-local
symbol of the catalog spec, this document's meaning applies.

| Symbol | Meaning | Domain / units |
|---|---|---|
| $y$ | A submission: one accession number, whose authority is the SEC's complete submission file | — |
| $a_y$ | Accession number of $y$. A catalog row with $a$ null forms a submission keyed by $H(p)$ until its header supplies an accession | string |
| $R_y$ | Filer rows of $y$ in the pinned catalog: $\{k \in \mathcal{A} : a(k) = a_y\}$ | set |
| $d_y$, $f_y$ | Catalog filing date and form type of $y$: the common $d$ and $f$ of $R_y$ | date; string |
| $u_y$ | Canonical location: the archive URL of the complete submission file at the path $p$ of the row in $R_y$ with the smallest $c$; the other paths of $R_y$ are aliases | string |
| $\sigma_y$ | Source identity, $H(u_y)$ | 256-bit hash |
| $x_y$, $h_{x}$, $\tau_x$ | Snapshot of $y$, SHA-256 of its original bytes, first local receipt time of those bytes | — |
| $\lambda(y)$ | Family tier from $f_y$ through $\nu_F$: 1 current reports (8-K and amendments); 2 periodic reports (10-K, 10-Q, their amendments and transition variants); 3 ownership (3, 4, 5, SC 13D, SC 13G, 13F-HR, their amendments); 4 everything else | {1, 2, 3, 4} |
| $b$ | Request budget of a run: the number of requests it may send | integer; configured per workflow |
| $\mathcal{P}$ | Carry-over: submissions planned earlier and not yet complete | set |
| $\vec{g}$ | Catalog vector pinned at run start, $(g_q)_{q \le q^\star}$ | — |
| $\mathcal{A}$ | Pinned catalog, $\bigcup_q A_q[g_q]$ | finite map |
| $\mathcal{Y}$ | Submissions of the pinned catalog | set |
| $\mathcal{W}$ | Plan: the frozen, ordered submissions of one run with their outcomes | — |
| $\nu$ | Version vector $(\nu_E, \nu_X, \nu_O, \nu_I, \nu_F, \nu_{\mathrm{cal}}, \nu_S)$: envelope parser; fact extractor with its namespace and transformation tables; ownership extractor with its code tables; item-label table; tier table; exchange calendar; schema | labels |
| $\theta_y$ | Processing identity $(\sigma_y, h_{x_y}, \nu)$; the provenance every derived row carries | — |
| $\Sigma_y$ | Submission record: header fields, $t^{\mathrm{acc}}_y$, items, filer-role blocks | record |
| $t^{\mathrm{acc}}_y$ | Acceptance instant from the header, converted from Eastern time; the original string is retained | UTC instant |
| $d^{\mathrm{hdr}}_y$, $d^{\mathrm{chg}}_y$, $\rho_y$ | Header filing date, header date of last change, period of report | dates |
| $\mathcal{I}_y$ | Item set of a current report: the item numbers its header labels map to under $\nu_I$ | set |
| $\mathcal{D}_y$ | Document set of $y$ | set |
| $\delta$ | One document: sequence $\delta.\mathrm{seq}$, declared type, file name, description, payload byte range in $x_y$, payload hash $h_\delta$, encoding class | — |
| $\Phi_y$ | Entity attribute observations taken from the filer-role blocks of $\Sigma_y$ | set |
| $F_y$ | As-filed fact set of $y$ | set |
| $\varphi$ | A fact: concept $\chi$, context $\zeta$, unit, decimals $\eta$, value, original string $\omega$, fact id, element path | — |
| $\chi$ | Concept: namespace URI and local name | pair |
| $\zeta$ | Context: entity CIK, period (instant, or start and end), dimension members $\mathbf{m}$ | — |
| $\kappa(\varphi)$ | Cell of a fact: (entity CIK, $\chi$, period, $\mathbf{m}$, unit) | — |
| $\Upsilon_y$ | Typed ownership records of $y$ | set |
| $\mathcal{E}_y$, $e$ | Event records of $y$; one event | — |
| $\mathrm{lvl}(\cdot)$ | Provenance level of a derived field | {A, B, C, D} |
| $\mathrm{ev}$ | Evidence span: $(a_y, \delta.\mathrm{seq}, h_\delta, [\mathrm{start}, \mathrm{end}), H(\text{bytes}))$, offsets into the payload of $\delta$ | — |
| $\Gamma_q$ | Platform generation of quarter $q$: a manifest of accepted processing identities, partition files and tombstones, named by its identity | — |
| $\Pi^{\mathcal{P}}_q$ | Platform pointer record of $q$: names the active $\Gamma_q$, its manifest hash and length, $\nu$ and the $g_q$ it was built against; replaced only conditionally on its version | versioned record |
| $\mathrm{Known}_t$, $\mathrm{AsOf}_t$, $\mathrm{First}$, $\mathrm{Current}$ | View operators (P7) | — |
| $s(\cdot)$ | Session assignment: the first trading session of $\nu_{\mathrm{cal}}$ whose close follows an instant; $s_y = s(t^{\mathrm{acc}}_y)$ | session date |
| $B^{\mathrm{sub}}_{\mathrm{rx}}$ | Guard on received bytes of one submission file | 256 MiB |
| $n_{404}$ | Runs that may see "not found" for a listed submission before it is parked | 3 |
| $m_{\mathrm{aud}}$ | Audit sample: accepted submissions re-fetched per audit run | 200 |
| $q_0$, $q_1$ | Inclusive requested range for backfill | quarters; configured 2015Q1 to open |

## Per-component descriptions

### P1. Submission selection and acquisition plan

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\mathcal{L}$ | Lineage walk: the union of catalog change sets between the previously pinned vector and $\vec{g}$, per quarter | sets of keys |
| $\mathrm{reason}(y)$ | Reason a submission is planned: new, changed rows, carry-over, audit sample | label |
| $\Omega(y)$ | Outcome of a planned submission after the run | {acquired, pending, deferred by budget, deferred as oversize, parked unserved, failed, quarantined, cancelled} |

#### Problem formulation and data-generating story

The pinned catalog holds one row per filer and filing. The design understands the rows as
follows. A filing with several filers appears once per filer, under each filer's CIK
directory, with the same accession number in each path; the complete submission file under
every such path is the same filing. Each closed quarter sampled by the catalog spec holds about
300,000 rows (300,561, 318,647 and 302,315), so the configured range of 48 quarters names on the
order of $1.4 \times 10^7$ rows and somewhat fewer distinct submissions. The share of rows in
each tier is not yet measured.

Acquisition is one request per distinct submission, and every request passes the governor,
whose ceiling is $r/2 = 1.5$ requests per second (catalog spec, C2, step 5). A quarter of
300,000 submissions therefore needs at least $2.0 \times 10^5$ seconds of requests — about 2.3
days of uninterrupted traffic — before download time, retries, catalog traffic and daily runs.
The full range needs at least about 110 days. The plan must therefore choose and order, not
merely enumerate.

**Estimand.** For one run, the ordered set $\mathcal{W}$ of submissions to request, each with
its canonical location, its aliases, its tier and its reason; and, after the run, exactly one
outcome per planned submission. The target is what the pinned catalog lists, never what a
calendar or a form-type count predicts.

#### Estimation / inference procedure

1. **Pin.** Read $\Pi_q$ for every $q \le q^\star$ under the catalog's reader contract. A
   coordinate that fails verification refuses the run. Record $\vec{g}$ and the vector the
   previous completed run of the same workflow pinned.
2. **Submissions.** Group rows by $a$. For each group: $R_y$; $d_y$ and $f_y$ as the common
   values, with a disagreement recorded as a gap and the earliest date and the highest-priority
   tier used; $u_y$ as the path with the smallest $c$ and the other paths as aliases. A row with
   $a$ null is its own submission keyed by $H(p)$.
3. **State.** Each submission keeps a record of when it was first and last planned, its
   acquisition status, its latest accepted snapshot and that snapshot's receipt, its last
   error, its tier, the generation vector it was last reconciled against, and the number of
   runs that saw "not found" for it.
4. **Selection.**
   - **Backfill** selects every $y$ with $Q(d_y) \in [q_0, q_1]$ and no accepted snapshot, in
     reuse mode.
   - **Daily** selects every $y$ whose rows entered the catalog since the previously pinned
     vector. The keys come from the lineage walk $\mathcal{L}$ over the catalog's change files
     (its C6, step 6); when the lineage does not connect the two vectors (a rollback
     intervened), the fallback is a full comparison of $\mathcal{A}$ against the state records.
   - **Audit** selects a sample of $m_{\mathrm{aud}}$ accepted submissions, stratified by tier
     and year, in refresh mode, plus every submission whose rows changed under $\mathcal{L}$.
   - **Every mode** adds the carry-over $\mathcal{P}$ and applies row changes: an added filer
     row for an acquired submission adds an alias with no request; a changed $f$ re-tiers and
     re-plans parsing with no request; a changed $p$ under the same $a$ is a new alias and, if
     $u_y$ changed, a refresh; a submission every one of whose rows was withdrawn is cancelled
     and handed to P7 for a tombstone.
5. **Order.** Tier ascending, then $d_y$ descending, then $a_y$ ascending. Carry-over keeps the
   tier it had when first planned. Within the daily workflow the day's own rows precede
   carry-over of the same tier.
6. **Budget and priority.** Dispatch stops when $b$ requests have been sent or the deadline
   is within one exchange; everything undispatched is deferred by budget and becomes
   carry-over. Platform requests carry the governor's "other" priority, so the catalog's daily
   discovery is never delayed by the platform.
7. **Plan result.** $\mathcal{W}$ freezes the run context, $\vec{g}$, the resolved endpoint, the
   ordered submissions with their reasons, and the acquisition mode. It is immutable and
   content-addressed, so later stages refer to one exact plan.
8. **Outcomes.** After dispatch each planned submission has exactly one $\Omega(y)$. A submission
   that saw "not found" in $n_{404}$ consecutive runs is parked as unserved with its evidence and
   leaves the automatic plan; the catalog withdrawing its rows cancels it, and an operator can
   re-plan it.

#### Assumptions and limitations

1. **Accession groups rows correctly.** Rows sharing $a$ are one filing. *Breaks if:* the SEC
   reuses an accession number, or lists one filing under paths with different accessions; the
   platform then merges or splits filings wrongly.
2. **Legacy rows.** A null-accession row is a submission of its own until a header supplies the
   accession (P3). *Breaks if:* two such rows are the same filing; they are merged only after
   both are parsed.
3. **Recent-first order serves nowcasting, not completeness.** A long backfill stays incomplete
   in its oldest quarters for months. Coverage is reported per quarter and tier (P10), never
   inferred from the newest date acquired.
4. **One request budget.** The platform competes with the catalog's own traffic and can only
   ever use what the governor grants. The achievable rate is unmeasured.
5. **Tier by declared form type.** $\lambda$ comes from the catalog's $f$. *Breaks if:* a filer
   misdeclares the form type; the submission is tiered wrongly until the header is parsed, and
   the header's type then re-tiers it for parsing but not for the request already sent.
6. **Not-found semantics.** "Not found" for a listed submission is not evidence of removal
   (catalog spec, cross-component assumption 6); parking after $n_{404}$ runs limits wasted
   requests, and the park has no automatic recovery horizon.

#### Evaluation criteria

- **Listing only.** Every planned submission comes from a row of the pinned catalog; none is
  built from a form-type count, a calendar or the submissions API.
- **Outcomes.** Every planned submission has exactly one outcome, and every failure carries its
  retained evidence.
- **Order and budget.** The dispatch order matches step 5, and no run sends more than $b$
  requests, counting retries, alias checks and the ticker snapshot.
- **Replay.** An exact rerun of a plan reproduces the same $\mathcal{W}$ from the pinned
  vector, without new requests.
- **Pre-run measurement.** Before the first backfill, the per-tier and per-quarter submission
  counts are computed from the retained catalog and recorded with the plan, so the expected
  duration is stated rather than guessed.

#### Open questions for the reviewer

1. Is one request per submission the right acquisition unit for the backfill, given the
   arithmetic above? The SEC also publishes daily dissemination archives, one compressed
   archive per business day holding every submission disseminated that day, and bulk archives
   of older periods; the design understands them as the same submissions in dissemination
   serialization. They would replace about 300,000 requests per quarter with about 63, at the
   cost of exchanges far longer than $T_{\mathrm{ex}}$, bodies far above the byte guards, and a
   second serialization to reconcile with the archive copy (system open question 1).
2. Is recent-first the right order, or should the backfill run oldest-first so that complete
   quarters accumulate from a fixed start?
3. Should platform requests ever carry daily priority at the governor, for example after the
   catalog's daily run has completed, or does the governor need a third priority level?

### P2. Submission acquisition and retention

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\mathrm{pin}(\mathcal{W}, \sigma_y)$ | The pin: the snapshot hash accepted for $y$ in plan $\mathcal{W}$, written once | hash |
| $\mathcal{C}$ | Alias check set: aliases fetched in audit mode and required to be byte-identical to $x_y$ | set |

#### Problem formulation and data-generating story

A request for $u_y$ returns one of seven things:

- a complete submission file;
- a transient failure: timeout, connection failure, truncated body, 429 or a 5xx;
- "not found", for a listed submission that is not served, or no longer served;
- a redirect;
- an access denial: a 403 or a denial page;
- a 200 response whose body is not a submission file, such as an HTML error page;
- a body that exceeds a guard or cannot finish within $T_{\mathrm{ex}}$: an oversize exchange.

Submission files range from a few kilobytes (an ownership form) to tens or hundreds of
megabytes (an annual report with uuencoded graphics, a securitization filing). The
distribution is unmeasured.

**Estimand.** For each planned submission, either exactly one accepted snapshot, or an explicit
status with its evidence retained. The snapshot's bytes are the SEC's original bytes, validated
as a submission file, kept unchanged and pinned to the plan.

#### Estimation / inference procedure

1. **Mode.** In reuse mode (backfill, daily), a submission with an accepted snapshot is pinned to
   its latest one with no request. In refresh mode (audit, or a changed $u_y$), it is fetched
   again.
2. **Classification.**

   | Response | Classification |
   |---|---|
   | 403, or a body that reads as an SEC denial page | access denied: durably halt the run |
   | Retryable transport error or incomplete body | retry |
   | 200 that passes validation (step 4) | received |
   | 200 that fails validation | quarantined as an invalid submission |
   | 404 for a listed submission | pending; the state's not-found count rises by one per run |
   | 3xx | failed; the redirect is not followed |
   | 429 or 5xx | retry |
   | Byte guard or $T_{\mathrm{ex}}$ reached | deferred as oversize; no automatic retry |
   | Anything else | failed |

3. **Retries.** As in the catalog spec (C3, step 3): at most $n_{\max}$ attempts per command
   attempt and URL, counted durably, with wait $\delta_k$ and the server's delay folded into the
   shared $N$. A retry that would be ready at or after the deadline defers the submission
   instead. Every attempt counts against $b$.
4. **Validation before acceptance.**
   - **Transport and envelope**, as in the catalog spec: a complete 200 response; identity
     content encoding; chunked transfer or a declared length, not both, and a declared length
     must match; an allowed content type; at most $B^{\mathrm{sub}}_{\mathrm{rx}}$ bytes; hash
     and length re-verified; not a denial page.
   - **Submission structure:** the body begins with the submission's document line; it contains
     exactly one header block, closed, before the first document block; every document block is
     closed; the body ends with the submission's closing line. The header's accession number
     equals $a_y$, or, for a legacy submission keyed by path, is recorded and becomes $a_y$; if
     that accession already names another submission, the two are merged as aliases and a gap
     is recorded. No restriction to ASCII applies to the body; document payloads are bytes.
5. **Retention.** A valid body is staged under its command attempt, then promoted to a
   content-addressed location keyed by $(a_y, h_x)$ before the submission is marked downloaded.
   Every failed, invalid or oversize body is kept in quarantine with its receipt and
   classification; an oversize attempt keeps the bytes received so far and the elapsed time.
6. **Snapshot record.** Each record holds $\sigma_y$, $h_x$, the byte count, $\tau_x$ and the
   HTTP validators. Bytes already seen map to their existing record, which keeps its first
   receipt time.
7. **Pinning.** $\mathrm{pin}(\mathcal{W}, \sigma_y)$ is written once; the first accepted pin wins.
   A retry completes unpinned submissions and never replaces a pin.
8. **Alias check.** In audit mode, $\mathcal{C}$ holds one alias of each sampled submission
   that has aliases; each is fetched and must be byte-identical to the accepted snapshot. A different body is retained as
   its own snapshot and raises an "alias divergence" gap; neither snapshot is withdrawn.
9. **Crash recovery.** Staging and promotion are checkpointed. Recovery re-validates retained
   bytes against their recorded receipt before using them.

#### Assumptions and limitations

1. **Validation means complete.** A 200 response that passes validation is taken to be the
   complete filing. *Breaks if:* the SEC serves a well-formed but truncated file; it would be
   accepted, and only a later audit fetch could reveal it.
2. **Oversize is manual.** A submission that cannot finish within $T_{\mathrm{ex}}$ or
   $B^{\mathrm{sub}}_{\mathrm{rx}}$ is parked. Raising either limit changes the governor's
   takeover bound $U$ (catalog spec, C2), so an override is an operator decision per
   submission, not a retry. How many submissions this affects is unmeasured.
3. **Receipt time is local.** $\tau_x$ orders revisions by first local receipt, as in the
   catalog spec; the header's date of last change is kept but does not order revisions.
4. **Guards are selected limits.** $B^{\mathrm{sub}}_{\mathrm{rx}}$ is four times the catalog's
   guard and has no measured basis.
5. **Denial is per run** (catalog spec, C2, assumption 6).

#### Evaluation criteria

- **Acceptance.** No snapshot is accepted without full validation and hash-verified retention.
- **Failure evidence.** Every failed, invalid or oversize body is retained with its
  classification.
- **Retries.** Retries are bounded, counted durably, deferred near the deadline and charged to
  the budget.
- **Pins.** An exact retry of a command attempt resumes without replacing any pin.
- **Aliases.** On the audit sample, the alias divergence rate is measured and reported.

#### Open questions for the reviewer

1. Should refresh use conditional requests (entity tag, last-modified) so that an audit of an
   unchanged submission costs no body?
2. Is the complete submission file the right raw object, or the per-document archive directory
   of the filing, which avoids uuencoded payloads at the cost of one request per document and a
   directory listing (system open question 2)?
3. What should the oversize policy be: a separate budgeted lane with longer limits, or permanent
   exclusion of filings above a size?

### P3. Envelope parsing and document split

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\ell$ | Physical line number of a header field in $x_y$ | integer |
| $\mathcal{B}_y$ | Filer-role blocks of the header: one per (role, CIK) | set |
| $\mathrm{enc}(\delta)$ | Encoding class of a document payload | {text, xml, inline-xbrl, uuencoded, other} |

#### Problem formulation and data-generating story

**File layout.** The design understands a complete submission file as follows, in order:

- a document line and a header block. The header block opens with the acceptance line, then
  labeled lines (accession number, conformed submission type, public document count, conformed
  period of report, zero or more item-information lines, filed-as-of date, date as of change),
  then one or more filer-role blocks. A role is one of filer, filed by, filed for, subject
  company, reporting owner or issuer; each block carries company or owner data (conformed name,
  CIK, standard industrial classification, IRS number, state of incorporation, fiscal year
  end), filing values (form type, act, file number, film number), business and mail addresses,
  and zero or more former-name blocks with a date of name change;
- one or more document blocks, each with a declared type, a sequence, a file name, an optional
  description and a text payload. A payload is HTML or plain text, an XML document, an inline
  XBRL document wrapped in an XBRL element, or a uuencoded binary (graphics, PDFs, archives);
- the submission's closing line.

**What the fields mean.** The acceptance line is the instant EDGAR accepted the submission, in
Eastern time. The filed-as-of date is the filing date the SEC assigned; the design understands that for
most forms a submission accepted after the day's cutoff receives the next business day, and it
records both dates and relies on neither for the other. The period of report is the date the filing describes: a period end for
a periodic report, the date of the earliest event reported for a current report. Item
information lines carry the SEC's item titles, not item numbers. The public document count is
the SEC's count of public documents in the filing.

**Estimand.** For each snapshot, the submission record $\Sigma_y$ and the document set
$\mathcal{D}_y$, every field tied to its line or byte range and its original text; or a refusal
of the whole submission, with the first failing line and its reason.

#### Estimation / inference procedure

1. **Structure.** Require the document line, exactly one header block before the first
   document block, balanced document blocks, and the closing line. A file with no document
   block is refused.
2. **Header fields.**
   - Each labeled line is split at its first colon; the label is matched against a known-label
     table of $\nu_E$. An unknown label is retained verbatim as a (label, value, $\ell$) triple
     and counted; it does not refuse.
   - Required: accession number, conformed submission type, filed-as-of date and the
     acceptance line. A missing or malformed required field refuses the submission.
   - The accession number matches ten digits, two, then six, joined by hyphens. Dates are eight
     digits and real calendar dates. The acceptance line is fourteen digits, converted from
     Eastern time to $t^{\mathrm{acc}}_y$ with the original string retained; it must not be
     later than $\tau_x$.
   - Within role blocks the CIK is zero-padded to $c$; the SIC, IRS number, state, fiscal year
     end, file and film numbers are kept as listed; a former-name block yields (former name,
     date of name change). All header lines must be ASCII.
3. **Items.** Each item-information line is retained verbatim and mapped by $\nu_I$ to an item
   number. An unmapped label gives a null item with its label and is counted as a gap; it
   does not refuse.
4. **Documents.** For each document block: the type, sequence, file name and description are
   read from the lines before the payload; the payload is the bytes strictly between the
   payload's opening and closing lines; the sequence must be a positive integer, unique in the
   submission. The payload's byte range in $x_y$ and its hash $h_\delta$ are recorded.
   $\mathrm{enc}(\delta)$ is set by inspection: uuencoded if the payload starts with a uuencode
   begin line; inline-xbrl if it starts with the XBRL wrapper; xml if it starts with an XML
   declaration; text otherwise. Documents are byte ranges of the retained snapshot, not
   separate files; a uuencoded payload is decoded on demand, with begin and end markers and
   line lengths verified, and a decode failure is a document gap, not a submission refusal.
5. **Cross-checks against the catalog** (gaps, never refusals, except the first): the header
   accession equals $a_y$ (a mismatch refuses, because identity is wrong); $d^{\mathrm{hdr}}_y$
   equals $d_y$; the conformed submission type equals $f_y$; the set of role-block CIKs
   contains every $c$ of $R_y$; the number of document blocks equals the declared count.
6. **Provenance.** Every header field carries $\ell$; every document carries its byte range;
   $\Sigma_y$ and $\mathcal{D}_y$ are addressed by $\theta_y$.
7. **Output.** The record and document set are stored immutably with their counts: documents,
   documents per encoding class, role blocks, unknown labels, unmapped items. After writing,
   every stored field is read back and re-derived from the retained bytes, and the counts are
   checked.
8. **Replay.** A new $\nu_E$ or $\nu_I$ is a new processing identity, re-parsed from retained
   bytes without any request.

#### Assumptions and limitations

1. **The layout holds.** The grammar above is the design's reading of the format and has not
   been fixed against real files. *Breaks if:* real headers use labels, nesting or encodings
   outside it; the refusal rate is then high until $\nu_E$ is revised, which the evaluation
   below measures first.
2. **Acceptance is required.** A header without an acceptance line is refused. *Breaks if:*
   older filings in a future range lack it; they would need a separate rule, and the
   point-in-time views could not place them.
3. **Payload delimiters are unambiguous.** A payload never contains the closing delimiter of
   its own block. *Breaks if:* a document embeds it; the split then truncates the document
   and misreads the rest of the file, which the balanced-blocks check should refuse.
4. **Declared count equals block count.** *Breaks if:* the SEC's count excludes non-public
   documents or counts differently; the check then raises gaps on valid files and is
   downgraded to informational.
5. **Form type and tier.** The header's conformed submission type governs parsing; the catalog's
   $f$ governed the request. A disagreement is recorded and the header wins for extraction.
6. **No entity resolution.** Names and attributes are taken as listed (P4).

#### Evaluation criteria

- **Round trip.** Every stored field re-derives exactly from its line or byte range, and stored
  counts match.
- **Example files.** Small hand-built submissions cover: every role kind; several filers; an
  uuencoded graphic; an inline XBRL document and a traditional instance; a missing acceptance
  line (refused); an unknown label (retained); an unmapped item label (gap); documents with and
  without a description; a legacy file keyed by path whose header supplies the accession.
- **Real files.** Before the first live run, a bounded investigation retains a sample of real
  submissions stratified by tier and year. The grammar is fixed against it, the refusal rate
  and the unknown-label and unmapped-item rates on the sample are recorded, and the sample is
  kept as a regression set.

#### Open questions for the reviewer

1. Do the header fields of the complete submission file agree with the dissemination-feed
   serialization and with the submissions API's acceptance time and items? If any disagree,
   which is authoritative?
2. Should an unknown header label refuse the submission, as an unknown preamble label refuses
   an index file in the catalog spec, or be retained as here?
3. Is the payload-delimiter assumption safe for HTML documents that quote markup?

### P4. Entity attribute history

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\phi$ | An attribute observation: (CIK, role, attribute, value, $t^{\mathrm{acc}}_y$, $a_y$) | — |
| $\mathcal{T}$ | Ticker observations: (CIK, ticker, exchange, first receipt, last receipt) | set |
| $\mathrm{Attr}_t(c, \text{attribute})$ | The value of an attribute of CIK $c$ as known by $t$ | value |

#### Problem formulation and data-generating story

EDGAR has no point-in-time entity endpoint. The header of every submission carries its filers'
attributes as they stood at acceptance: conformed name, SIC, state of incorporation, fiscal
year end, IRS number, addresses, and former names with dates of change. The SEC separately
publishes a current ticker-to-CIK file and, through the submissions API, current tickers and
exchanges; both are "latest" views with no history. Tickers are reused, filers change names
and CIKs are never reused, so CIK is the only stable key.

**Estimand.** For each CIK, the sequence of attribute observations in acceptance order, the
ticker observation intervals, and the as-of operator over them. The target is what the filer
and the SEC stated when, not a reconciled "true" attribute.

#### Estimation / inference procedure

1. **Observations.** From each parsed $\Sigma_y$, one $\phi$ per (role-block CIK, attribute)
   with a non-empty value, and one former-name observation per former-name block. All are
   level A.
2. **Storage.** Observations are stored with $\theta_y$; nothing is de-duplicated at write
   time, so a stale repeated value is still an observation.
3. **As-of.** $\mathrm{Attr}_t(c, \cdot)$ is the value of the observation with the greatest
   $t^{\mathrm{acc}}_y \le t$, ties broken by accession number; it is undefined before the first
   observation. A reader may ask instead for the full sequence.
4. **Tickers.** The SEC's ticker file is a planned source like any other: one request per daily
   run through the governor, validated, retained as a snapshot. $\mathcal{T}$ holds, per
   (CIK, ticker, exchange), the receipt of the first and the latest snapshot that listed it.
   Nothing is claimed before the first snapshot, and an interval closes only when a later
   snapshot omits the triple.
5. **No reconciliation.** Names are not matched across CIKs or over time; the former-name
   observations are the only link the design records.

#### Assumptions and limitations

1. **Header attributes can be stale.** A filer's profile is updated by the filer; a name change
   may appear only in later filings. *Breaks if:* a consumer reads $\mathrm{Attr}_t$ as the
   date the attribute changed; it is the date it was observed.
2. **SIC is the SEC's assignment** at acceptance, kept as listed.
3. **Tickers have no backfill.** Ticker history before the first snapshot is unknown to the
   platform. *Breaks if:* a consumer needs a ticker at a past date; an external source is
   required (system open question 6).
4. **Reporting owners are entities too.** Owner data in ownership forms yields observations for
   individual CIKs; the platform stores them as filed and applies no additional handling.

#### Evaluation criteria

- **Round trip.** $\mathrm{Attr}_{t^{\mathrm{acc}}_y}$ reproduces the header values of any
  parsed submission $y$.
- **Tickers.** Every triple present in any retained ticker snapshot has an interval, and every
  interval is bounded by receipts of retained snapshots.
- **Example sequences.** Hand-built submissions cover a name change with and without a
  former-name block, and a CIK appearing in several roles.

#### Open questions for the reviewer

1. Should the submissions API be snapshotted per CIK as well, for former names and exchanges,
   at one request per CIK?
2. What external source, if any, should supply ticker history before the first snapshot?

### P5. Structured fact extraction

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\mathcal{N}$ | Standard namespace table of $\nu_X$: the namespace URIs of the SEC-accepted standard taxonomies; a concept outside it is an extension | set |
| $\mathcal{R}$ | Transformation registry table of $\nu_X$: inline XBRL format names and their value transformations | map |
| $\mathrm{sc}$, $\mathrm{sg}$ | Inline scale and sign attributes of a numeric fact | integer; {+, −} |
| $\mathrm{cov}_y$ | Cover record: the typed document-and-entity facts of the cover page | record |

#### Problem formulation and data-generating story

The design understands XBRL in submissions as follows. A filing carries structured facts in
one of three ways: a traditional instance document (an XML document whose root is an XBRL
element, with contexts, units and facts as elements); an inline XBRL document (the primary
HTML document with facts marked up in place and its contexts and units in a resources block,
wrapped in an XBRL element inside the payload); or not at all. Periodic reports and, since
2019, cover pages of current reports and other forms carry inline XBRL. A context names the
entity by its CIK, a period as an instant or a start and end, and optional dimension members.
A numeric fact names a context, a unit and a precision in decimals, and in inline form also a
scale, a sign and a format whose transformation turns the displayed text into a value. A
non-numeric fact carries text or escaped markup. Concepts are qualified names; filers may
define their own concepts in an extension taxonomy alongside the standard ones.

The SEC's companyfacts and frames endpoints publish facts derived from the same documents but
only for standard concepts, only without dimensions, only with the filing date rather than the
acceptance instant, and as a rebuilt "latest" view. The DERA financial-statement data sets are
quarterly extracts with the same provenance limits. Neither is replayable from bytes the
platform holds, so both serve as cross-checks and never as inputs.

**Estimand.** For each XBRL-bearing document, every fact as filed — concept, context, unit,
decimals, value, original string, id and element path — and the cover record; or a refusal of
that document with its reason. The target is what the filer tagged, not a comparable or
corrected value.

#### Estimation / inference procedure

1. **Carriers.** A document is a carrier if $\mathrm{enc}(\delta)$ is inline-xbrl, or xml with
   an XBRL root element. A submission may hold several carriers; each is processed alone.
2. **Contexts and units.** Parse every context (id, entity scheme and identifier, period,
   dimension members as (axis, member) pairs or typed values) and every unit (measures, or a
   numerator and denominator). An entity scheme other than the SEC's CIK scheme, or an
   identifier that is not among the role-block CIKs, is a gap, not a refusal.
3. **Facts.**
   - **Instance:** every element outside the XBRL, link and XLink namespaces that carries a
     context reference is a fact; its value is its text.
   - **Inline:** every numeric and non-numeric fact element, continuation chains joined in
     order, excluded ranges removed, hidden facts included and marked hidden. A numeric fact's
     value is $\mathrm{sg} \cdot \mathcal{R}[\text{format}](\text{text}) \cdot 10^{\mathrm{sc}}$,
     kept as a decimal string; an absent format means a plain decimal number; a format absent from $\mathcal{R}$ leaves
     the value null with a reason, and the fact is retained with $\omega$.
   - Every fact must resolve its context and unit references; an unresolved reference refuses
     the carrier.
   - The concept is resolved through the document's namespace declarations to $\chi$; an
     extension is flagged as such by $\mathcal{N}$.
   - Footnotes and their links are retained with the facts they annotate.
4. **Keys.** A fact's id is its own if present, otherwise
   $H(\chi, \zeta, \text{unit}, \omega, \text{element path})$. Two facts in one carrier with the
   same cell and the same value are both kept; the same cell with different values are both kept
   and the cell is flagged inconsistent within the filing.
5. **Cover record.** From the document-and-entity-information facts: document type, period end,
   fiscal year and period focus, amendment flag, registrant name and CIK, shares outstanding
   with their date, public float with its date, and the number of employees where tagged. Each
   field keeps its fact id.
6. **Provenance.** Each fact carries $\theta_y$, $\delta.\mathrm{seq}$ and its element path;
   an inline fact also carries the byte range of its element in the payload, which is its
   evidence span.
7. **Output.** Facts and the cover record are stored immutably with counts: facts, numeric
   facts, null-valued facts by reason, extensions, dimensional facts, contexts, units. After
   writing, every stored fact is read back and re-derived from the retained bytes, and the
   counts are checked.
8. **Replay.** A new $\nu_X$ — including a changed $\mathcal{N}$ or $\mathcal{R}$ — is a new
   processing identity, re-parsed from retained bytes.

#### Assumptions and limitations

1. **No taxonomy semantics.** Concepts are qualified names only. Labels, data types,
   calculation and presentation relationships and definition arcs are not resolved, so no
   calculation check runs and no concept is validated against its taxonomy. *Breaks if:* a
   consumer needs aggregation rules or label text; those come from a later taxonomy layer.
2. **Transformations are a table.** $\mathcal{R}$ covers the formats seen in the sample. *Breaks
   if:* a filing uses a format outside it; its numeric values are null until $\nu_X$ grows,
   which the null-by-reason counts expose.
3. **Scale and sign are trusted.** A misdeclared scale or sign produces a wrong value with
   correct provenance. The companyfacts cross-check is the only detection.
4. **As-filed only.** Facts are not de-duplicated across filings, not restated, not mapped to
   standard concepts, not adjusted for fiscal calendars. Comparability is a consumer's task
   over the views of P7.
5. **Carrier refusal is per document.** A refused carrier leaves $\Sigma_y$, the other documents
   and the submission's events intact; the fact set of $\theta_y$ is marked refused for that
   carrier.

#### Evaluation criteria

- **Round trip.** Every stored fact re-derives exactly from its element, and stored counts
  match.
- **Example documents.** Hand-built carriers cover: an instance and an inline document with the
  same facts; dimensional and typed-dimension contexts; scale, negative sign and a format
  outside $\mathcal{R}$; continuations, exclusions and hidden facts; an extension concept; an
  entity mismatch; a duplicate cell with equal and with differing values.
- **Agreement with companyfacts.** On the real sample, for non-dimensional standard-concept
  numeric facts, the value and period per (accession, concept, unit) are compared with the
  SEC's companyfacts response for the same accession, requested through the governor. The
  disagreement rate and its reasons (scale, sign, format, period) and the coverage gap in each
  direction are recorded. The comparison is evidence about $\nu_X$, not an input to any fact.
- **Counts.** Every refused carrier carries its reason and the first failing element.

#### Open questions for the reviewer

1. When should taxonomy semantics be added, and from which taxonomy packages, given that
   taxonomy files live on hosts outside the governor's domain?
2. Should a format outside $\mathcal{R}$ refuse the carrier rather than null the fact?
3. Is companyfacts an adequate reference for calibration, given that it drops extensions and
   dimensions, or should the DERA data sets or a vendor be used as well (system open
   question 9)?

### P6. Ownership record extraction

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\mathcal{K}$ | Transaction-code table of $\nu_O$: transaction codes and their economic class | map |
| $\mathcal{V}$ | Value-unit table of $\nu_O$: the unit of 13F information-table values by schema version and filing date | map |
| $r^{\mathrm{own}}$ | One typed record: $(a_y, \delta.\mathrm{seq}, \text{table}, \text{row index}, \text{fields}, \text{original strings})$ | — |

#### Problem formulation and data-generating story

Three ownership families are filed as XML, and the design understands them as follows.

- **Forms 3, 4 and 5** are one XML document each: issuer, one or more reporting owners with
  relationship flags, a table of non-derivative holdings or transactions (security title,
  transaction date, deemed execution date, transaction code, shares, price, acquired or
  disposed, post-transaction amount, ownership nature), a table of derivative holdings or
  transactions (conversion or exercise price, exercise and expiration dates, underlying
  security), footnotes referenced by id, remarks and signatures; an amendment names the
  original's date; recent schemas flag trades under a trading plan. XML has been required for
  these forms since 2003.
- **Schedules 13D and 13G** have been XML since December 18, 2024: cover page with subject
  company and CUSIP, reporting persons with amount, percent of class and voting and dispositive
  powers, and the items of the schedule as text. Earlier schedules are HTML or text only and
  yield no typed record.
- **Form 13F-HR** is a primary XML document (cover and summary pages, other managers) plus an
  information-table XML document (per holding: issuer name, class, CUSIP, value, amount and
  its type, put or call, discretion, other managers, voting authority). XML has been required
  since 2013. The design understands that the value unit changed by rule from thousands of
  dollars to dollars for reports filed from 2023; $\mathcal{V}$ records which applies.

**Estimand.** For each ownership XML document, its typed records as filed, with original
strings and element paths; or a refusal of that document with its reason.

#### Estimation / inference procedure

1. **Carriers.** A document is a carrier if $\mathrm{enc}(\delta)$ is xml and its root element
   belongs to one of the three schemas; the schema version is read from the document.
2. **Records.** Each table row becomes one $r^{\mathrm{own}}$ with every field as listed and its
   original string; footnotes are stored once per document and linked by id; cover and summary
   pages become one record each. Field rules of $\nu_O$ check types (dates, decimals, codes,
   flags) and refuse the carrier on a violation.
3. **Classes.** A transaction code is kept as filed (level A); its economic class from
   $\mathcal{K}$ — open-market purchase, open-market sale, award, tax withholding, exercise or
   conversion, disposition to issuer, gift, other — is a separate field at level B. A 13F value
   keeps its as-filed number and a unit from $\mathcal{V}$.
4. **Amendments.** An amendment's declared original date, amendment type (restatement or
   addition for 13F) and sequence are retained for P8; nothing is merged here.
5. **Provenance and output.** Records carry $\theta_y$, $\delta.\mathrm{seq}$ and element paths;
   they are stored immutably with counts, read back and re-derived from retained bytes.
6. **Replay.** A new $\nu_O$ re-parses from retained bytes.

#### Assumptions and limitations

1. **Schemas are the SEC's.** Field rules are the design's reading of the published schemas and
   have not been fixed against real files. *Breaks if:* real documents use elements outside
   the rules; refusal rates are then high until $\nu_O$ is revised.
2. **No full schema validation.** Documents are not validated against the SEC's XSDs, which
   live outside the governor's domain.
3. **Pre-XML schedules are text.** 13D and 13G filed before December 2024 produce no typed
   record; their events (P8) carry only header fields.
4. **Economic class is a rule.** $\mathcal{K}$ encodes a reading of the transaction codes;
   it does not separate routine from opportunistic trades or read footnotes.
5. **13F value units are a table.** *Breaks if:* the rule date or its application to amendments
   is misread; values are then off by a factor of a thousand for a window of filings.

#### Evaluation criteria

- **Round trip.** Every stored record re-derives exactly from its elements, and counts match.
- **Example documents.** Hand-built documents cover each schema, an amendment with an original
  date, a 13F restatement and addition, a derivative table with footnotes, and a document with
  a type violation (refused).
- **Agreement with SEC data sets.** On the real sample, Form 4 transactions and 13F holdings
  are compared with the SEC's insider-transactions and 13F data sets for the same accessions,
  retrieved through the governor; disagreement and coverage rates are recorded as evidence
  about $\nu_O$.

#### Open questions for the reviewer

1. Should pre-XML 13D and 13G schedules receive a rule-based (level B) extraction of amount
   and percent from text, or wait for the model-based layer?
2. How should a Form 4 amendment be read: as a full replacement of the original, as the SEC's
   instructions suggest, or as a second set of rows linked to the first?

### P7. Point-in-time store, views and publication

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\mathcal{M}_q$ | Manifest of $\Gamma_q$: the $g_q$ it corresponds to, $\nu$, the complete processing identities, the partition files with hash, length and row count, the tombstones, and the identity of the generation it extends | record |
| $\mathrm{tomb}(y, t)$ | True if a tombstone for $y$ with detection time at or before $t$ exists | predicate |
| $t^{\mathrm{det}}$ | Detection time of a tombstone: the receipt of the catalog generation that withdrew the last row of $y$ | UTC instant |
| $\succ_{\mathrm{acc}}$ | Order on facts of one cell: acceptance instant, then accession number, higher wins | strict order |
| $\Lambda^{\mathcal{P}}$ | Lineage of a platform generation | sequence |
| $n_{\mathrm{batch}}$ | Complete submissions per publication within a run | 500 |

#### Problem formulation and data-generating story

Every derived row has three times that must never be confused: the instant the filing was
accepted, $t^{\mathrm{acc}}_y$; the dates its contents describe (a period end, a transaction
date, a period of report); and the time the platform processed it. A reader with a cutoff must
see exactly the rows whose filings were public by that cutoff, with the values those filings
carried, even if a later amendment changed them and even if the catalog later withdrew the
filing. Rows are partitioned by the quarter of the catalog filing date, as the catalog is, and
the published state advances one quarter at a time behind a conditional pointer, as the catalog
does. Nothing is ever deleted; withdrawals are tombstones with their own time.

**Estimand.** For each quarter, a validated generation whose rows are exactly the complete
processing identities it names; view operators that, given a cutoff, return what was knowable
then; and a change history from which any earlier generation can be restored by an explicit
move.

#### Estimation / inference procedure

1. **Partitions.** For each quarter and version: submissions, documents, cover records, facts,
   ownership records, entity observations, events and tombstones, each as sorted Parquet files.
   Every row carries $(a_y, t^{\mathrm{acc}}_y, d_y, \theta_y)$ and, for derived fields, its
   level (P9). A row is never updated; a new $\nu$ writes new partitions.
2. **Generation.** $\Gamma_q$ is named by $H(\mathcal{M}_q)$. Its identity enters the
   previous generation's identity, $g_q$, $\nu$ and the sorted set of processing identities, so
   the same content on the same base gives the same identity and run timestamps never enter.
3. **Publish.** Within a run, after every $n_{\mathrm{batch}}$ complete submissions and at the
   end, for each affected quarter: read $\Pi^{\mathcal{P}}_q$ and its version; write the new
   partition files; write $\mathcal{M}_q$ as the union of the active manifest and the new
   entries; run the independent check (step 7); then replace $\Pi^{\mathcal{P}}_q$
   conditionally on the version read. A lost race re-reads the winner, merges by union and
   retries, at most $n_{\mathrm{pub}}$ times; after that the run reports a publication conflict
   and the units stay pending. A manifest built on an old base never becomes current.
4. **Commit boundary.** The conditional replace is the only commit. A crash before it leaves
   unreferenced files; a crash after it leaves committed data, and per-submission published
   flags are rebuilt from the manifest, never the reverse.
5. **Tombstones.** When the lineage walk of P1 shows that every row of $y$ was withdrawn by the
   catalog, a tombstone $(y, g_q^{\mathrm{wd}}, t^{\mathrm{det}})$ is added to the generation of
   $Q(d_y)$, where $g_q^{\mathrm{wd}}$ is the catalog generation that withdrew the last row. The
   bytes and rows of $y$ remain. A withdrawal of some rows only removes aliases.
6. **Views.** A view names the $\nu$ it reads and never mixes versions.
   - $\mathrm{Known}_t(S)$: rows of $S$ with $t^{\mathrm{acc}}_y \le t$ and no tombstone whose
     $t^{\mathrm{det}} \le t$.
   - $\mathrm{AsOf}_t(\kappa)$: the $\succ_{\mathrm{acc}}$-maximal fact of cell $\kappa$ in
     $\mathrm{Known}_t(F)$; equal acceptance instants are resolved by accession number and
     flagged ambiguous. A cell is identified by its period dates and dimension members, never
     by fiscal-year or fiscal-period labels, which are attributes of the cover record.
   - $\mathrm{First}(\kappa)$: the $\succ_{\mathrm{acc}}$-minimal fact of the cell, the value
     first reported.
   - $\mathrm{Current}$: $\mathrm{Known}_{\infty}$, so withdrawn filings are excluded.
   - $s(t)$: the first session of $\nu_{\mathrm{cal}}$ whose close is after $t$; the calendar
     lists each session's close, including early closes, and $s_y$ is stored on every
     submission and event.
7. **Independent check.** Before a pointer can name a generation, a separate procedure
   re-reads every listed file and verifies hashes, lengths, row counts, quarter assignment
   ($Q(d_y) = q$ for every row), that every row's $\theta_y$ is in the manifest's set and
   every set member has rows, that no two rows share a primary key, and that the generation's
   rows are the union of the base's rows and the new entries.
8. **Reader contract.** Read $\Pi^{\mathcal{P}}_q$, then $\mathcal{M}_q$, then exactly the
   files it lists; verify as in step 7; a failed check fails the read with no fallback. A
   consumer of several quarters records the vector $(\Gamma_q)$ it read, with $\vec{g}$ and
   $\nu$.
9. **Rollback.** An operator names $q$, a from-generation, a to-generation, their own name and
   a reason; the to-generation must be a strict ancestor in $\Lambda^{\mathcal{P}}$; the
   rollback record is written ahead of the conditional move. A rollback is not a pin.
10. **Compaction.** Partition files may be rewritten into fewer files only as a new generation
    whose row set, by $(\theta_y, \text{row hash})$, equals the base's exactly; the check in
    step 7 enforces it.

#### Assumptions and limitations

1. **Latest-accepted wins.** $\mathrm{AsOf}_t$ takes the most recently accepted fact of a cell
   whatever form carried it, so a later 10-Q's comparative column outranks an earlier 10-K/A
   for the same cell. *Breaks if:* a consumer expects form rank; it must build its own view
   (system open question 5).
2. **Tombstone time is local.** $t^{\mathrm{det}}$ is when the catalog's reconciliation saw the
   withdrawal, at most about a week after the SEC's removal under the catalog's weekly
   schedule. *Breaks if:* a consumer reads it as the removal time.
3. **Linearizable replace and per-quarter atomicity only**, as in the catalog spec.
4. **Calendar is a table.** $\nu_{\mathrm{cal}}$ covers the sessions of one exchange calendar.
   *Breaks if:* the wrong calendar or a missing early close assigns a session one day off.
5. **Unbounded retention**, and partition growth proportional to the retained text of every
   filing's structured content.
6. **Primary keys.** Facts within a carrier are unique by id (P5, step 4); across carriers of
   one submission, the key includes $\delta.\mathrm{seq}$.

#### Evaluation criteria

- **Determinism.** The same complete set on the same base gives the same generation identity,
  and a repeat publishes nothing.
- **Independent recomputation.** Step 7 passes for every generation.
- **Views.** Hand-built sequences verify: an original, an amendment and a later comparative
  resolve under $\mathrm{AsOf}_t$ at cutoffs before, between and after their acceptances; a
  withdrawn filing is present before $t^{\mathrm{det}}$ and absent after; an acceptance after
  the close, on a holiday and on an early-close day maps to the right session.
- **Crash safety and races.** Faults injected before the files are complete, before the
  pointer moves and just after it moves leave readers seeing only complete generations;
  competing publishers never lose an update.
- **Rollback.** Only ancestors are accepted, a repeat is idempotent, and a moved pointer is
  stale.

#### Open questions for the reviewer

1. Would an open table format with snapshot isolation and multi-partition commits replace the
   per-quarter pointer with less custom machinery (catalog spec, system open question 7)?
2. Is latest-accepted the right rule for $\mathrm{AsOf}_t$, or should a restating amendment
   outrank a later comparative column?
3. Should tombstones carry a second, SEC-side time when the catalog can supply one?

### P8. Event derivation and linkage

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $d^{\mathrm{rep}}_y$ | Reported event date of a current report: its period of report | date |
| $\mathcal{I}^{\mathrm{doc}}_y$ | Items found by pattern in the primary document | set |
| $\delta^{\mathrm{prim}}_y$ | Primary document: the lowest-sequence document whose declared type equals the submission type | document |
| $\mathrm{amends}(y, y')$ | Link: $y$ amends $y'$ | relation |
| $\mathrm{follow}(e, y')$ | Link: $y'$ is a follow-up candidate for event $e$ | relation |

#### Problem formulation and data-generating story

The header already states what a filing is: its form, its filers, its items, its period, its
acceptance. The design turns those statements, and the typed records of P6, into event rows
that downstream work can key on without reading documents: a current-report item, a periodic
report, an insider transaction, a beneficial-ownership report, a holdings report, and a
generic filing event for everything else. Two facts constrain the design. Filers choose which
items a current report declares, so a workforce reduction disclosed only under "other events"
has no item 2.05 event here and never will at this level; recovering it is model work and out
of scope. And amendments are linked to originals by convention rather than by a key, so
linkage is a rule with a stated cardinality, not a certainty.

**Estimand.** For each submission, its event rows with their times (reported, accepted, filed,
first session), subjects, items, exhibits and provenance; and the link relations among
submissions. Every field is level A or B.

#### Estimation / inference procedure

1. **Filing event.** Every parsed submission yields one event of kind "filing" with $f_y$,
   the role-block CIKs, $t^{\mathrm{acc}}_y$, $d_y$, $s_y$ and the submission type from the
   header (level A).
2. **Current reports** (tier 1): one parent event of kind "current report" with
   $d^{\mathrm{rep}}_y$, and one child event per item in $\mathcal{I}_y$ (level A). Each
   document whose declared type begins with the exhibit prefix is attached to the parent as an
   exhibit with its sequence, type and description (level A). The primary document is scanned
   with a versioned pattern for item headings, giving $\mathcal{I}^{\mathrm{doc}}_y$ (level B,
   with an evidence span per heading); the symmetric difference with $\mathcal{I}_y$ is
   recorded as a gap, and the header's items are the events.
3. **Periodic reports** (tier 2): one event of kind "periodic report" with $\rho_y$, the
   amendment flag from $f_y$, and, when a cover record exists, its fiscal labels and period end
   (level A). The event references $\theta_y$, through which the facts are reachable.
4. **Ownership** (tier 3): from $\Upsilon_y$, one event per non-derivative and derivative
   transaction row of a Form 3, 4 or 5, carrying the transaction date as the reported date, the
   code (A) and its class (B), the reporting-owner and issuer CIKs; one event per Schedule 13D
   or 13G with the percent of class and amendment number when typed; one event per 13F-HR with
   the report period and amendment type.
5. **Amendments.** If $f_y$ carries the amendment suffix, candidates $y'$ are earlier-accepted
   submissions with the same base form and, by form: for Forms 3, 4 and 5, the declared
   original date and the same reporting owner and issuer; for periodic reports, the same
   filer CIK and $\rho$; for current reports, the same filer CIK and $d^{\mathrm{rep}}$; for
   13F-HR, the same filer CIK and report period; for schedules, the same subject and filing
   CIKs. $\mathrm{amends}(y, y')$ is written for every candidate, with the candidate count, and
   is unresolved when the count is zero (level B).
6. **Follow-up candidates.** For a current-report item event of a configured set (initially
   item 2.05), $\mathrm{follow}(e, y')$ names the earliest periodic report of the same filer
   with $\rho_{y'} \ge d^{\mathrm{rep}}_y$ and $t^{\mathrm{acc}}_{y'} > t^{\mathrm{acc}}_y$. The
   link claims that $y'$ is the next report, nothing about its content (level B).
7. **Times.** Every event stores the reported date (when the kind has one), $t^{\mathrm{acc}}_y$,
   $d_y$ and $s_y$, and nothing about first public disclosure elsewhere.
8. **Provenance and output.** Events carry $\theta_y$, their level, and for level-B fields
   their evidence spans; they are stored immutably with counts, read back and re-derived.

#### Assumptions and limitations

1. **Header items are the events.** Items are what the filer declared. *Breaks if:* the filer
   omitted an applicable item; the event is missing, and the document pattern only detects
   headings the filer wrote.
2. **Item labels map one-to-one.** $\nu_I$ maps the SEC's current titles; titles have changed
   with rules and will again. *Breaks if:* a title is absent from the table; the item is null
   and counted until $\nu_I$ is revised and replayed.
3. **Amendment linkage is a rule.** Candidates can be several or none. *Breaks if:* a consumer
   treats a link as a key.
4. **Exhibit types are the filer's.** A misdeclared exhibit type is attached as declared.
5. **Period of report semantics differ by form** and are read as the header gives them.

#### Evaluation criteria

- **Round trip.** Every event re-derives from its header fields, typed records or evidence
  spans.
- **Example files.** Hand-built submissions cover: a current report with several items, an
  unmapped title and a heading the header lacks; an amendment chain of each kind, including
  one with no candidate and one with two; a Form 4 with both tables.
- **Real files.** On the real sample, the header-versus-document item agreement rate, the
  amendment resolution rate by form and the unmapped-title rate are recorded.

#### Open questions for the reviewer

1. Should current-report events be one row per item, as here, or one row per submission with
   an item set?
2. How should $\nu_I$ be maintained as item titles change, and should historical titles map
   to current numbers?
3. Are follow-up candidates worth storing at this level, or should the later semantic layer
   own all cross-filing reconciliation?

### P9. Provenance grading, evidence contract and review

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\pi(z)$ | Producer identity of a derived field $z$: the entry of $\nu$ and, for a later model producer, its model, prompt and decoding identities | labels |
| $\alpha^{\mathrm{rev}}$ | Review record: field id, $\theta_y$, verdict, reviewer, time | record |

#### Problem formulation and data-generating story

Consumers of the store will mix fields read from structured elements with fields produced by
rules and, later, by models. A single undifferentiated table hides which is which and turns a
screening score into an assertion. The design grades every derived field and binds every
non-structural field to bytes a reader can re-check.

- **Level A — deterministic.** Read from a structured field by a versioned parser: header
  fields, XML elements, XBRL facts, catalog fields.
- **Level B — rule extracted.** Produced from text by a versioned pattern within a typed
  document: item headings, exhibit classification, transaction-code class, amendment and
  follow-up links.
- **Level C — model extracted.** Produced by a model from text, with evidence. Not produced in
  this build.
- **Level D — inferred.** Scores and classifications over other fields. Not produced in this
  build.

**Estimand.** For every derived field, its level and producer; for every level-B field and
every future level-C field, at least one evidence span that re-verifies against retained
bytes; and, for fields in a review class, their review records.

#### Estimation / inference procedure

1. **Tagging.** Every derived row carries $\mathrm{lvl}$ and $\pi$ per field, or per row where
   all fields share them. A row without them is refused at write.
2. **Evidence spans.** $\mathrm{ev} = (a_y, \delta.\mathrm{seq}, h_\delta, [\mathrm{start},
   \mathrm{end}), H(\text{bytes}))$, with offsets into the payload of $\delta$ as retained in
   $x_y$ (for a uuencoded payload, into the decoded bytes, with the decode verified). A span
   re-verifies when the retained payload still hashes to $h_\delta$ and the bytes in the range
   hash to the recorded value. Level-A fields carry an element path or line number instead.
3. **Producer pinning.** $\pi$ is part of $\nu$; a model producer, when added, extends $\nu$
   with its identities and is replayed like a parser.
4. **Review.** A configured set of (kind, field) pairs forms the review class. A reviewer
   writes $\alpha^{\mathrm{rev}}$ once per field and processing identity; the first record
   wins; a verdict is accept, reject or correct-with-value, and a correction is a new field
   value at level A with the reviewer as producer, never an edit of the model's or rule's
   output. Views expose review status so a consumer can filter to reviewed fields.
5. **Separation.** A level-D score is never written into the row it scores; it is its own row
   that references the inputs by key, so a screen cannot be read as a fact.

#### Assumptions and limitations

1. **Grades are producers, not accuracy.** Level A can be wrong (a misdeclared scale); the
   grade says how a field was made.
2. **Review is manual and unbounded** in this build; no sampling policy is chosen.
3. **Spans assume byte-stable payloads**, which cross-component assumption 5 provides and the
   audit fetch checks.

#### Evaluation criteria

- **Coverage.** Every derived field in every partition has a level and producer; every level-B
  field has at least one span.
- **Re-verification.** Every span in the real sample re-verifies, and a corrupted byte in a
  payload copy makes its spans fail.
- **Review binding.** A repeat review is idempotent; a review names a processing identity and
  does not carry over to a replay under a new $\nu$.

#### Open questions for the reviewer

1. Is a four-level grade the right granularity, or should level B split pattern-only from
   pattern-plus-structure extractions?
2. What review sampling policy should the first model-based layer inherit, and should it be
   fixed here?

### P10. Workflow composition and run accounting

#### Notation

No symbols beyond the shared table.

#### Problem formulation and data-generating story

Four workflows share P1–P9 and differ only in what they select and whether they request:

- **Backfill:** the requested range $[q_0, q_1]$ by tier, in reuse mode, under budget $b$.
- **Daily:** submissions whose rows entered the catalog since the previous pinned vector, in
  reuse mode, plus the ticker-file snapshot.
- **Audit:** a sample of accepted submissions and every submission with changed rows, in
  refresh mode, with alias checks.
- **Replay:** every retained snapshot not yet processed under the run's $\nu$, with no request.

The intended schedule is a daily run after the catalog's daily run, a weekly audit after the
catalog's reconciliation, and a backfill that runs whenever the governor is otherwise idle. A
run can be interrupted, exhaust its budget, run out of time, or meet an outage.

**Estimand.** Progress per submission that never loses older unresolved work, and a run report
stating exactly what is complete, pending by reason, failed, quarantined or parked, per tier
and quarter. Coverage is never inferred from the newest filing date acquired.

#### Estimation / inference procedure

1. **Pinning.** Before any work a run freezes its command, run and attempt identities;
   $t^\star$ and the endpoint; $\vec{g}$ and the previously pinned vector; the effective
   configuration and its hash; the code build identity and $\nu$; $b$; and an absolute
   deadline. An exact replay of a completed attempt returns its stored report and sends no
   request; a replay whose frozen values differ is refused; nothing retries automatically.
2. **Work units.** Each planned submission is its own unit and the checkpoint and retry unit.
   A run selects the plan's units and every earlier unit not complete under the current $\nu$,
   except a unit that only awaits publication and that a later accepted snapshot of the same
   submission has superseded.
3. **Processing.** Units run one at a time, in plan order. Each unit is acquired (P2), parsed
   (P3), its entity observations taken (P4), passed to every extractor whose carrier it holds
   (P5, P6 — by document inspection, not by tier, since cover-page XBRL appears in many
   forms), derived (P8), and published in batches (P7). Separate runs proceed concurrently and coordinate only through
   the governor and the conditional replace.
4. **Completion.** A unit is complete when its snapshot is accepted; its envelope is parsed, or
   refused with evidence; every applicable extractor has finished, or refused its document with
   evidence; its events are derived; and $\theta_y$ is in the active $\Gamma_{Q(d_y)}$ under
   the run's $\nu$. A refused envelope completes the unit as quarantined.
5. **Stops.** A denial, lost ownership or the block latch stops further acquisition in the
   run; the budget leaves undispatched units deferred by budget; the deadline leaves them
   pending; after a crash past a pointer move, the publish step stays resumable and the unit is
   not finalized until repair is done.
6. **Gaps.** Each run lists its gaps with evidence: catalog disagreements, unknown labels,
   unmapped items, entity mismatches, alias divergences, oversize parks, unserved parks,
   in-place changes found by audit (a refreshed snapshot with different bytes), and lineage
   breaks.
7. **Report.** The report counts units by outcome — planned, acquired, parsed, extracted per
   extractor, published, complete, deferred by budget, pending, parked, failed, quarantined —
   per tier and per quarter; quarter operations published and unchanged; tombstones written;
   $\vec{g}$ and $(\Gamma_q)$ before and after. Complete, deferred, pending, parked and failed
   partition the units; quarantined is a subset of complete.
8. **Run outcome.** The first rule that applies wins:
   1. fatal: access blocked, ownership lost, state conflict or internal error;
   2. quarantined: every unit was refused, and every gap stems from those refusals;
   3. incomplete: any failed unit or a gap other than a budget deferral remains;
   4. budget-limited: the only unresolved work is deferred by budget;
   5. pending: other unresolved work remains beside complete units;
   6. no new submissions: a daily run that planned nothing, had nothing unresolved and
      published nothing;
   7. success if any quarter was published; otherwise unchanged.
9. **Coverage rule.** Coverage of a quarter and tier is the count of complete submissions over
   the count the pinned catalog lists, reported with its denominator; a quarter is covered only
   when the ratio is one and no unit of it is parked or failed.

#### Assumptions and limitations

1. **Sequential units**, with parallelism only across runs sharing one request budget.
2. **Two correction channels.** Catalog withdrawals (through the lineage walk) and audit
   refreshes are the only ways the platform learns of removals and in-place changes; both are
   lagged and the audit is a sample.
3. **Schedule is not freshness.** A run with nothing to plan is distinct from a failed pin.
4. **Backfill is long** at the governor's ceiling (P1); budget-limited is its normal outcome.

#### Evaluation criteria

- **Catch-up.** A daily outage spanning several days, a quarter transition and an older
  backlog all catch up through the lineage walk without losing deferred work.
- **Coverage accounting.** Per-tier and per-quarter ratios carry their denominators from the
  pinned catalog, and no newest date stands in for coverage.
- **Report integrity.** A stored report re-derives its outcome from its own contents.
- **Replay.** An exact replay of a completed run sends no requests and returns the same
  report; a version replay processes every retained snapshot without any request.
- **Shared path.** All four workflows use the same acquisition, parsing, extraction and
  publication path.

#### Open questions for the reviewer

1. What audit sample size and stratification detect in-place changes and alias divergence at a
   useful rate, given that each sample costs one request?
2. Should the backfill run as one long-lived process or as scheduled bursts, given lease
   turns and takeover costs at the governor?

## Open questions for the reviewer

1. **Acquisition unit.** One request per submission puts the full backfill at about 110 days
   of uninterrupted traffic at the governor's ceiling, before download time or catalog traffic
   (P1). Daily dissemination archives would cut requests by three to four orders of magnitude
   but need exchanges far longer than $T_{\mathrm{ex}}$, bodies far above the guards, and a
   reconciliation of two serializations. Which unit should the backfill use, and should the
   governor gain a bulk lane with its own limits?
2. **Raw authority.** Is the complete submission file the right object, given uuencoded
   payloads and oversize filings, or the filing's archive directory with one request per
   document? Does either serve bytes that differ by filer path?
3. **Acceptance as the public instant.** The platform keys every view on the header's
   acceptance instant. How closely does dissemination follow acceptance, including during EDGAR
   outages, and should a dissemination time be recorded where the SEC supplies one?
4. **Facts without taxonomies.** Extracting facts by qualified name, without labels,
   calculation or definition relationships, keeps the parser replayable from retained bytes
   but leaves every comparability question to consumers. When should taxonomy packages enter,
   and how are they retained and versioned given that they live outside the governor's domain?
5. **Cell identity and precedence.** A cell is (entity, concept, period, dimensions, unit) and
   $\mathrm{AsOf}_t$ takes the latest-accepted fact. Should an explicit restatement outrank a
   later comparative column, and how should typed dimensions and co-registrant facts be keyed?
6. **Entity history.** CIK is the key and tickers are observed only from the first snapshot
   on. Which external source should supply ticker and exchange history, and should name
   reconciliation across CIKs exist anywhere in the platform?
7. **Pre-XML and legacy inputs.** Schedules 13D and 13G before December 2024 and headers that
   may lack an acceptance line in an extended range yield no typed records or no placement in
   time. Should rule-based extraction cover them, or should they wait for the model layer?
8. **Withdrawal semantics.** Tombstones carry the catalog's detection time, up to a week late,
   and $\mathrm{Known}_t$ uses it. Is that acceptable for point-in-time consumers, and should
   the catalog expose an SEC-side removal time where it can?
9. **Evaluation reference.** Parser accuracy is to be measured against the SEC's own derived
   products — companyfacts, the financial-statement, insider and 13F data sets — each of which
   has provenance limits of its own. Which reference and which metrics (field agreement,
   coverage in each direction, correction latency) should decide that a version of $\nu$ is
   fit to publish?
10. **Budget sharing and priority.** The platform's daily, audit and backfill runs and the
    catalog's runs share one governor with two priorities. Is "other" for all platform traffic
    the right rule, and what is the expected daily request load once the backfill is complete?
