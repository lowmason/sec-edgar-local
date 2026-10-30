# SEC EDGAR filing-index ingestion methodology

> For agentic workers: when specs/sec-filing-index-ingestion-critique.md exists beside this
> file, REQUIRED SKILL: describe-critique-methodology (synthesize mode) —
> do not draft a spec directly.

The system builds and maintains a catalog of the SEC EDGAR filing indexes: one row per filer
and filing, giving company, form type, filing date and archive path. It ingests a historical
baseline of quarterly indexes and the ongoing daily indexes, keeps every original file it
accepts, and republishes the catalog one calendar quarter at a time as corrections arrive.
This document describes the method as math and prose, independent of its code. It treats the
system as running on one host: several processes (a historical backfill, a daily catch-up and
a weekly reconciliation) share one local store of immutable files, one transactional store of
versioned records, and one lease record that serializes every request to the SEC.

**Evidence status.** The method is implemented and tested offline only. The tests use
hand-built index files and ten real index files (970,622 rows) kept from a bounded
investigation of about 150 requests at no more than 3 per second. No complete run against the
live SEC has happened, so throughput, memory, runtime and behavior over the full historical
range are unmeasured. Scope is the index catalog only. Filing documents, XBRL data, entity
resolution and any serving database are out of scope.

## Component inventory

| Component (by methodological role) | Estimand / output | Consumes |
|---|---|---|
| C1. Source discovery and coverage ledger | The index files the SEC lists for the required periods; one outcome per required directory; the daily boundary $\beta$ | SEC directory listings; earlier pending sources and failed directories; $t^\star$ |
| C2. Shared request governor | One serialized, paced schedule of SEC requests across all processes, with shared server-requested cooldowns and a durable block latch | Request intents from C1 and C3; the coordinating store's clock |
| C3. Acquisition and snapshot retention | For each discovered source, one validated snapshot $x$, original bytes retained, pinned to that discovery | C1's sources; C2's permission to send; earlier accepted snapshots |
| C4. Index parsing and observation normalization | The observation sequence $O_x$ of each snapshot, or refusal of the whole snapshot with a line and reason | Retained snapshot bytes; $\nu_P$, $\nu_S$ |
| C5. Quarter catalog resolution | For each affected quarter: candidate catalog $C_q$, change set $\Delta_q$, gate $\gamma_q$, candidate identity $g'_q$ | C4's observations; the active catalog $A_q$; $t^\star$ |
| C6. Publication, approval and rollback | The active pointer of each quarter, moved only by validated conditional replace; approval, activation and rollback records; generation lineage | C5's candidates; operator approvals and rollbacks |
| C7. Workflow composition and run accounting | Backfill, daily and reconciliation runs; per-source work units; a run report with coverage accounting and one run outcome | C1–C6; configured $q_0$, $q_1$, $d_h$; the run deadline |

## Composition

Symbols are defined in the Notation section below. A run pins $t^\star$ and the versions
$(\nu_P, \nu_S)$, then composes the components through immutable, content-addressed references.
No stage follows a mutable "latest".

$$
\mathcal{W} = \mathrm{Discover}(t^\star), \qquad
x_s = \mathrm{Acquire}(s) \quad (s \in \mathcal{W}), \qquad
O_{x_s} = \mathrm{Parse}(x_s;\ \nu_P, \nu_S).
$$

Rows are partitioned by filing date, not by the file that carried them. A snapshot therefore
touches every quarter its rows fall in, plus every quarter whose active catalog already draws
on an earlier snapshot of the same source:

$$
\mathcal{Q}(x_s) = \{\, Q(d(o)) : o \in O_{x_s} \,\} \ \cup\ \{\, q : \sigma_s \text{ contributes to } A_q \,\}.
$$

For each $q \in \mathcal{Q}(x_s)$ with $q \le q^\star$ (a later quarter is refused):

$$
\mathcal{S}_q = \psi\big(\mathrm{src}(A_q) \cup \{x_s\}\big), \qquad
(C_q, \Delta_q, \gamma_q, \phi_q) = \mathrm{Resolve}_q(\mathcal{S}_q, A_q, m_q), \qquad
g'_q = H(q,\ g_q,\ \phi_q).
$$

The per-quarter update, with the gate as an indicator:

$$
A_q^{+} =
\begin{cases}
A_q & \text{if } \phi_q = \phi(A_q) \quad \text{(unchanged; no new generation)}\\[2pt]
C_q & \text{if } \phi_q \ne \phi(A_q),\ \gamma_q = 0, \text{ and } \Pi_q \text{ still names } g_q\\[2pt]
A_q & \text{if } \gamma_q = 1 \quad \text{(candidate retained, awaiting approval)}
\end{cases}
$$

A lost conditional replace re-reads $A_q$ and recomputes, at most $n_{\mathrm{pub}}$ times. An
operator approval later sets $A_q^{+} = C_q$ only if the approval names $(q, g'_q, h_{\mu_q})$,
$\Pi_q$ still names $g_q$, and no snapshot of $\mu_q$'s source with a later receipt and
different bytes exists.

The published state at any instant is the vector of active generations $(g_q)_{q \le q^\star}$.
Each coordinate changes atomically; the vector does not. A reader that needs a reproducible
multi-quarter view records the vector it read. A run's outcome is a reduction over its work
units and gaps (C7). Only discovery and acquisition reach the SEC, and only through the
governor (C2). Parsing, resolution and publication read retained bytes only.

## Cross-component assumptions

1. **One coordination domain.** Every process that sends requests to the SEC on the owner's
   behalf uses the same coordinating store and lease record. *Breaks if:* a process or tool
   outside the domain (another store, a manual download) adds traffic the governor cannot see,
   and the owner-wide SEC ceiling can be exceeded.
2. **Bounded clocks.** Each reading of the coordinating store's clock lies within an interval
   no wider than $\epsilon$, and each process's wall clock and monotonic clock agree within
   $\epsilon$ for the run. The method stops when it detects a violation. *Breaks if:* a clock
   is wrong but self-consistent; pacing and takeover safety then rest on a false bound.
3. **Content identity and revision order.** Equal SHA-256 means equal source content, and the
   order of first local receipt orders a source's revisions. *Breaks if:* the SEC serves an
   older revision after a newer one and those bytes were never seen before; selection then keeps
   the wrong revision (C7 detects only returns to bytes already seen). Cosmetic byte changes
   cause rebuilds but no data change.
4. **Filing date assigns the quarter.** Each row belongs to the quarter of its filing date,
   whatever file carried it. *Breaks if:* a row's filing date changes between revisions; the key
   is then added to the new quarter while the old quarter keeps it as an unresolved absence, or
   proposes to withdraw it under closed membership, so the union of quarterly catalogs can hold
   the key twice.
5. **Pinned versions.** Parser version, schema version, effective configuration and code build
   identity are fixed at run start and recorded; outputs of different versions are never
   combined. *Breaks if:* versions mix; replay is then neither deterministic nor reproducible.
6. **Listings show existence, not absence.** A listed file exists or will be served. An unlisted
   file, a failed listing or an HTTP failure is never treated as evidence that a filing was
   removed. *Breaks if:* a listed file is never served; it then stays pending indefinitely (C1).
   The policy's cost is delay, not false removal: removals are learned only from closed-quarter
   membership (C5).
7. **Storage semantics.** Files are write-once (a second write must be byte-identical); records
   support atomic insert-if-absent and conditional replace by version, durable once
   acknowledged; everything is retained indefinitely. *Breaks if:* any of these fails; updates
   can be lost, generations torn, or the basis for replay lost.
8. **Per-quarter independence.** Quarters advance independently, and a run may advance some
   quarters and not others. *Breaks if:* a consumer reads "current" across several quarters
   during a run; it can see a mix of old and new generations.

## Notation

Subscripts are dropped when the source or snapshot is clear from context. A superscript $+$
marks a value after one update, as in $A_q^{+}$ or $\beta^{+}$.

| Symbol | Meaning | Domain / units |
|---|---|---|
| $s$ | A source: one SEC index file at one location | — |
| $\kappa_s$ | Kind of $s$: quarterly (one quarter's master index in the full-index family, a ZIP archive) or daily (one business day's master index, plain text) | {quarterly, daily} |
| $\rho_s$ | Period of $s$: its quarter if quarterly, its date if daily | quarter or date |
| $u_s$ | Canonical location of $s$: one exact HTTPS URL on the SEC origin | string |
| $\sigma_s$ | Source identity, $H(u_s)$ | 256-bit hash |
| $H$ | SHA-256 over a canonical serialization | — |
| $x$ | Snapshot: one accepted copy of a source's original bytes | — |
| $x_s$ | The snapshot of source $s$ pinned in the current run | snapshot |
| $h_x$ | SHA-256 of the original bytes of $x$ | 256-bit hash |
| $\tau_x$ | First local receipt time of $h_x$ for its source; identical bytes keep their first time | UTC instant |
| $k$ | Logical key $(c, p)$ | — |
| $c$ | CIK as a 10-digit, zero-padded decimal string | string |
| $p$ | Archive path relative to the EDGAR Archives root, case preserved | string |
| $n$ | Company name as listed | string |
| $f$ | Form type as listed, including amendment suffixes | string |
| $d$ | Filing date | calendar date |
| $a$ | Accession number, or null when the path does not carry one | string or null |
| $v$ | Business fields $(c, n, f, d, p, a)$ | — |
| $\nu_P$, $\nu_S$ | Parser version and schema version | labels |
| $\theta_x$ | Processing identity $(\sigma_s, h_x, \nu_P, \nu_S)$; also the provenance each row carries | — |
| $o$ | Observation: $(k, v, \theta_x, \ell, \omega)$; $k(o)$ and $d(o)$ are its key and filing date | — |
| $\ell$ | Physical line number of an observation in its file | integer |
| $\omega$ | The five original field strings of an observation | strings |
| $O_x$ | Observation sequence parsed from $x$ | sequence |
| $Q$ | Quarter function: $Q(d)$ is the calendar quarter containing date $d$ | quarter |
| $t^\star$ | The run's pinned date, fixed once at run start | date |
| $q^\star$ | The open quarter, $Q(t^\star)$ | quarter |
| $m_q$ | Mode of quarter $q$: open if $q = q^\star$, closed if $q < q^\star$; $q > q^\star$ is refused | {open, closed} |
| $A_q$ | Active catalog of $q$: key to row (business fields plus provenance) | finite map |
| $g_q$ | Identity of the active generation of $q$ | hash |
| $\Pi_q$ | Pointer record of $q$: names $g_q$, its manifest hash and length, and $\phi(A_q)$; replaced only conditionally on its version | versioned record |
| $\mathrm{src}$ | $\mathrm{src}(A_q)$ is the set of snapshots that contributed to $A_q$, as its manifest records | set |
| $\psi$ | Per-source snapshot selection (C5) | map |
| $\mathcal{S}_q$ | Selected contributing snapshots for a candidate of $q$ | set |
| $\mu_q$ | Membership snapshot: the selected snapshot of the quarterly source whose period is $q$, if any | snapshot or none |
| $M_q$ | Membership key set: keys of rows in $O_{\mu_q}$ dated in $q$ | set |
| $K_q$ | Proposed key set (C5) | set |
| $C_q$ | Candidate catalog of $q$ | finite map |
| $\Delta_q$ | Change set of $C_q$ against $A_q$ | — |
| $\gamma_q$ | Gate: 1 if $C_q$ needs approval before it can become active | {0, 1} |
| $\phi_q$ | Source fingerprint of a candidate; $\phi(A_q)$ is the active one | hash |
| $g'_q$ | Candidate generation identity, $H(q, g_q, \phi_q)$ | hash |
| $n_{\mathrm{pub}}$ | Conditional-replace attempts per publication | 5 |
| $\mathcal{W}$ | Discovery result: the frozen sources and directory outcomes of one discovery | — |
| $\mathcal{Q}$ | $\mathcal{Q}(x)$ is the set of quarters a snapshot affects | set of quarters |
| $\mathrm{Discover}$, $\mathrm{Acquire}$, $\mathrm{Parse}$, $\mathrm{Resolve}$ | The maps of C1, C3, C4 and C5; $\mathrm{Resolve}_q$ acts on quarter $q$ | maps |
| $\beta$ | Daily discovery boundary | date |
| $d_h$ | Daily handoff date | date; configured 2026-10-01 |
| $q_0$, $q_1$ | Inclusive requested range for backfill and reconciliation; $q_1$ may be "open", resolved once to $q^\star$ | quarters; configured 2015Q1 to open, 2010Q1 intended |
| $r$ | Request-rate target | 3 per second, no bursts |
| $\epsilon$ | Clock-uncertainty bound | 2 s |
| $T_{\mathrm{ex}}$ | Whole-exchange deadline of one request | 90 s |

## Per-component descriptions

### C1. Source discovery and coverage ledger

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $z$ | A directory: a family root, a year directory or a quarter directory | — |
| $\mathcal{Z}$ | Required directories of a run | set |
| $\Omega$ | $\Omega(z)$ is the outcome of directory $z$ | {available, no new sources, failed} |
| $\mathcal{P}$ | Carry-over: sources listed earlier but not yet accepted, and directories that failed earlier | set |

#### Problem formulation and data-generating story

Under the EDGAR Archives root the SEC publishes two families of master indexes. The design
understands its guidance as follows.

- **full-index.** One directory per year and quarter. Each quarter directory holds that
  quarter's master index in several representations, one of them a ZIP archive. The open
  quarter's file is a quarter-to-date index that grows as the quarter proceeds. The SEC rebuilds
  the full and quarterly indexes weekly to incorporate corrections and removals, so a closed
  quarter's file can change after the quarter ends.
- **daily-index.** One directory per year and quarter, each holding one master index per
  business day, named with its date. The SEC starts processing a day's index around 22:00
  Eastern, and processing normally takes several hours. Daily files do not reflect later
  removals.

Each directory has a machine-readable listing of its immediate children with name, type, size
and a modification label. Days without filings have no file. A directory for a new year or
quarter appears only when the SEC creates it, and a listing request can fail transiently.

**Estimand.** The set of index files the SEC lists, at discovery time, in the directories a run
needs, with one outcome per needed directory. The target is what is listed, not what a calendar
predicts.

#### Estimation / inference procedure

1. **Required directories $\mathcal{Z}$.**
   - Backfill and reconciliation: the full-index root, plus the year and quarter directories of
     every quarter in $[q_0, q_1]$.
   - Daily: the daily-index root, plus the year and quarter directories of every quarter from
     $Q(\beta)$ through $q^\star$, plus $q^\star$ and the quarter before it. The first run uses
     $Q(d_h)$ in place of $Q(\beta)$.
   - Every mode adds the directories of the carry-over $\mathcal{P}$, in their own family.
2. **Parent-authorized traversal.** Read the root, then years, then quarters. Request a child
   only when the parent's actual listing names it with the expected name and type. A required
   child missing from its parent's listing, or under a failed parent, is a failed directory,
   never an empty one.
3. **Listing validation.** A listing must name its own directory. It must list only immediate,
   safe children: no traversal, separators, escapes or control characters. Each child's name,
   type and reference must agree exactly, and duplicates are refused. The listing body is
   retained by content hash with its receipt.
4. **Selection.**
   - In a quarterly directory, select the ZIP master index.
   - In a daily directory, select every plain-text master index named with an eight-digit date
     in that directory's quarter, whatever the date.
   - Other representations are ignored with a recorded reason, and a directory that lists only
     unsupported representations fails.
   - The copy of the current quarter's index at the full-index root is recorded as an
     alternative and not used.
5. **Outcomes.** $\Omega(z)$ takes one of three values:
   - available: at least one source selected;
   - no new sources: a valid listing with nothing selected;
   - failed: an HTTP failure, an invalid listing, a missing child or a failed ancestor.
6. **Discovery result.** $\mathcal{W}$ freezes the run context, the resolved endpoint, the
   selected sources, the directory outcomes and the acquisition mode: reuse earlier accepted
   snapshots, or refresh. It is immutable and content-addressed, so later stages refer to one
   exact discovery.
7. **Boundary.** After a daily discovery, $\beta^{+} = \max(\beta, t^\star)$ if no outcome
   failed, and $\beta^{+} = \beta$ otherwise. A failed read therefore keeps every later run
   re-listing from the old boundary.
8. **Resumption.** Per-directory progress is checkpointed with its retained listing. An
   interrupted discovery resumes by re-validating saved listings instead of requesting them
   again.
9. **Source state.** Each discovered source keeps a record of when it was first seen, its last
   discovery, its acquisition status, its latest downloaded snapshot with that snapshot's
   receipt time, and its last error.

#### Assumptions and limitations

1. **Listed files become retrievable.** A listed file that returns "not found" stays pending,
   and later runs retry it. *Breaks if:* a file stays listed but is never served; it then
   stays pending forever, because there is no recovery horizon.
2. **No removal evidence.** Listings are never evidence of removal, by design. Removals are
   invisible to discovery; C5 learns them only from closed-quarter membership.
3. **Not-yet-created directories fail.** A required directory that does not exist yet counts as
   a failure, for example a new quarter's directory early in the quarter. It holds $\beta$ and
   makes runs incomplete until the SEC creates it.
4. **Overlap replay.** The first daily run lists whole quarter directories, including days
   before $d_h$, so it replays its overlap with the baseline. C5's keying removes the
   duplicates; no calendar cutover is relied on.
5. **One representation per family.** Only ZIP quarterly files and plain-text daily files are
   supported.
6. **No timing assumptions.** No SEC publication time or retention period for historical daily
   files is assumed, and a run schedule does not establish freshness.

#### Evaluation criteria

- **Outcomes.** Every required directory has exactly one outcome, and every failure carries its
  retained evidence.
- **Boundary.** $\beta$ never passes a failed read.
- **Sources.** Every source comes from an actual listing; none is built from the calendar.
- **Empty versus failed.** A valid empty listing is distinguished from a failure.
- **Replay.** An exact rerun of a discovery reproduces the same discovery result from retained
  listings, without new requests.

#### Open questions for the reviewer

1. Is listing traversal the right way to learn which index files exist? The alternatives are
   constructing expected file names, or another EDGAR product.
2. How, and after how long, should a source that stays listed but unretrievable be retired?
3. Should a directory that is simply not created yet, at the start of a quarter or year, be
   distinguished from a failed read?

### C2. Shared request governor

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $[\underline{t}, \overline{t}]$ | One reading of the coordinating store's clock, as an interval; accepted only if $\overline{t} - \underline{t} \le \epsilon$ | UTC interval |
| $j$ | Index of a request in the global order | integer |
| $t_j$ | Dispatch start of request $j$ | UTC instant |
| $\hat{t}_j$ | Bound charged for request $j$'s dispatch: the end of its dispatch window, $\overline{t} + 1/r$ at reservation | UTC instant |
| $\hat{e}_j$ | Upper bound of the confirmed completion (full drain) of request $j$ | UTC instant |
| $D_j$ | Time from request $j$'s reservation to its confirmed drain | seconds |
| $N$ | Shared not-before instant | UTC instant |
| $U$ | Unsafe-until: the latest instant at which a request of the current lease holder could still be in flight | UTC instant |
| $U_{\text{prev}}$ | $U$ as the previous lease holder left it | UTC instant |
| $E$ | Earliest safe start after a change of lease holder | UTC instant |
| $\overline{t}_{\text{acq}}$ | Upper bound of the time at which the current lease was acquired | UTC instant |
| $L$ | Lease duration | 60 s |
| $R$ | Lease renewal interval | 20 s |
| $T_c$, $T_r$ | Connect and read timeouts | 15 s, 60 s |

#### Problem formulation and data-generating story

The SEC's published guidance caps automated access at 10 requests per second per user,
across all machines, and asks for a declared User-Agent that identifies the requester with a
contact address. Faster access can draw throttling responses or a temporary denial, served as
a 403 or as an HTML page. Several local processes can need the SEC at once, for example the
daily run while a backfill or reconciliation is in progress. Processes can crash, stall or
lose their lease in the middle of a request.

**Estimand.** A global order of request start times, $t_j < t_{j+1}$ for every $j$, across all
processes, such that:

1. at most one request is in flight at any time;
2. consecutive requests are at least $1/r$ apart, with $r$ well under the ceiling and no
   bursts;
3. every process honors every server-requested delay;
4. properties 1–3 survive crashes, lease expiry and bounded clock error;
5. daily work is served before other waiting work.

#### Estimation / inference procedure

1. **Time.** Every safety comparison uses the conservative end of a clock interval:
   $\overline{t}$ for "has happened by", $\underline{t}$ for "has not happened yet". An interval
   wider than $\epsilon$, or drift between wall clock and monotonic clock beyond $\epsilon$,
   stops the run.
2. **Queue.** A request first enqueues a ticket with its priority (daily or other), its enqueue
   time and an expiry at its deadline. The waiting ticket with the smallest
   (not daily, enqueue time, ticket identity) is served, and expired tickets are dropped. A daily
   run's discovery, and the collection of what it discovered, carry daily priority.
3. **Lease.** The served requester acquires a lease of $L$ seconds on the single lease record,
   re-checks under the lease that it is still the one served, and increments an epoch. It
   renews every $R$ seconds. Before each renewal it extends $U$ to cover the lease's possible
   new expiry plus $T_{\mathrm{ex}} + \epsilon$. A failed renewal, or any doubt that it still
   holds the lease, cancels its turn.
4. **One request per turn.** A turn reserves exactly one request, whose earliest start is

   $$t_{j+1} \ \ge\ \max\big(N,\ E,\ \hat{t}_j + 1/r\big).$$

   At reservation the record stores $\hat{t}_{j+1} = \overline{t} + 1/r$ and raises $U$ to
   the request's latest possible end plus $\epsilon$. The request must start within its
   dispatch window, $1/r$ long, and end within $T_{\mathrm{ex}}$.
5. **Pacing after completion.** When the response is fully drained,
   $N \leftarrow \max(N, \hat{e}_j + 1/r)$. With step 4, consecutive reservations are at least
   $\max(2/r,\ D_j + 1/r)$ apart. By this rule the achievable rate is at most $r/2$, which is
   1.5 per second, even for instantaneous exchanges. The live rate is unmeasured.
6. **Takeover.** A new lease holder may start at $E = U_{\text{prev}}$ if the previous holder
   released cleanly, meaning it confirmed drain and finalized the record in the same transaction
   as the release. Otherwise
   $E = \max\big(U_{\text{prev}},\ \overline{t}_{\text{acq}} + T_{\mathrm{ex}} + \epsilon\big)$: the
   new holder waits out any request the previous holder might still have in flight.
7. **Bounded exchange.** Each request runs in an isolated process with these limits:
   - a hard, operating-system-enforced deadline;
   - timeouts $T_c$ and $T_r$;
   - a cap on received bytes;
   - no redirect following, no content decoding, and no inherited proxy or credential
     settings.

   A request whose end cannot be positively confirmed counts as lost ownership, and $U$ is
   kept.
8. **Shared cooldown.** A server-requested delay (C3) moves $N$ forward for every process.
9. **Block latch and halts.**
   - A server delay that cannot be represented sets a durable latch on the lease record, which
     refuses every later request from any process. The latch has no expiry and no reset
     operation; clearing it is an explicit policy decision outside the method.
   - An access denial (C3) durably halts the run that received it.

#### Assumptions and limitations

1. **No bypass.** No process sends SEC requests outside the governor (cross-component
   assumption 1).
2. **Clock bounds hold** (cross-component assumption 2). *Breaks if:* the bounds are wrong;
   a takeover could then overlap a lost holder's in-flight request.
3. **Per-request overhead.** Each request is its own lease turn, so queue, lease and record
   operations add overhead to every request. That overhead is unmeasured.
4. **Rate cap.** Charging the end of the dispatch window, and pacing again after drain, caps the
   rate at $r/2$ even on a fast network.
5. **Late process start.** The isolated process must start within the dispatch window,
   $1/r \approx 0.33$ s. Under heavy host load it can start too late; the request is then
   abandoned, and its source waits for a later run.
6. **Denial is per run.** An access denial halts only the run that saw it. No cooldown across
   processes follows, so each concurrent run spends one request to discover the same denial.

#### Evaluation criteria

- **Safety.** No two requests overlap in time across processes, including across lease loss and
  takeover.
- **Spacing.** The gap from each confirmed completion to the next start is at least $1/r$.
  Retries and listing requests count against the same budget.
- **Delays and stops.** Every process honors every server delay. A denial stops its run, and
  the latch stops all runs.
- **Liveness.** When the lease is free, the served ticket proceeds, and daily tickets are served
  first.
- **Not yet measured.** The achieved request rate and the per-request overhead in a live run.

#### Open questions for the reviewer

1. Is single-flight pacing with spacing after completion, effectively at most $r/2$, more
   conservative than SEC guidance requires? Would a token bucket, or limited concurrency under
   the same ceiling, be accepted practice?
2. How does the lease, epoch and unsafe-until scheme compare with fencing tokens, given that the
   SEC endpoint cannot check a token?
3. Should an access denial impose a cooldown shared by all processes? If so, how long, given SEC
   practice?

### C3. Acquisition and snapshot retention

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $n_{\max}$ | Total attempts per command attempt and URL, including the first | 5 |
| $\delta_0$ | Retry backoff base | 2 s |
| $\delta_{\max}$ | Local cap on the backoff | 120 s |
| $\delta_k$ | Wait before the $k$-th retry | seconds |
| $\delta^{\mathrm{srv}}$ | Server-requested delay (Retry-After) | seconds |
| $\xi$ | Jitter, drawn uniformly from $[0, 1)$ | — |
| $B_{\mathrm{rx}}$ | Guard on received bytes | 64 MiB |
| $B_{\mathrm{exp}}$ | Guard on expanded (decompressed) bytes | 512 MiB |
| $b$ | $b(\mathcal{W}, \sigma)$ is the pin: the snapshot hash accepted for source $\sigma$ in discovery $\mathcal{W}$, written once | hash |

#### Problem formulation and data-generating story

A request for a listed source $s$ returns one of six things:

- a complete, valid index;
- a transient failure: timeout, connection failure, truncated body, 429 or a 5xx;
- "not found", for a listed file that is not served yet;
- a redirect;
- an access denial: a 403 or a denial page;
- a 200 response whose body is not a valid index, such as an HTML error page, an unexpected
  encoding, or a truncated or malformed archive.

**Estimand.** For each source in a discovery, either exactly one accepted snapshot, or an
explicit pending or failed status with its evidence retained. The snapshot's bytes are the SEC's
original bytes, validated, kept unchanged and pinned to that discovery.

#### Estimation / inference procedure

1. **Mode.** In reuse mode (backfill, daily), a source that already has an accepted snapshot is
   pinned to its latest one with no request. In refresh mode (reconciliation), every source is
   fetched again.
2. **Classification.**

   | Response | Classification |
   |---|---|
   | 403, or a body that reads as an SEC denial page | access denied: durably halt the run |
   | Retryable transport error or incomplete body | retry |
   | 200 that passes validation (step 4) | received |
   | 200 that fails validation | quarantined as an invalid source |
   | 404 for a listed source | pending; a later run retries it |
   | 404 for a directory listing | failed |
   | 3xx | failed; the redirect is not followed |
   | 429 or 5xx | retry |
   | Anything else | failed |

3. **Retries.** At most $n_{\max}$ attempts per command attempt and URL, counted durably so a
   restarted process continues the count. The $k$-th retry waits

   $$\delta_k = \max\Big(\xi \cdot \min\big(\delta_{\max},\ \delta_0\, 2^{k-1}\big),\ \delta^{\mathrm{srv}}\Big),$$

   and the wait becomes the shared $N$ of C2. If the retry would be ready at or after the
   command deadline, the source is deferred (pending) instead.
4. **Validation before acceptance.**
   - **Transport and envelope:**
     - a complete 200 response;
     - identity content encoding only;
     - chunked transfer or a declared length, not both, and a declared length must match;
     - an allowed content type;
     - at most $B_{\mathrm{rx}}$ bytes;
     - hash and length re-verified;
     - not an HTML or XML page, and not denial text.
   - **Quarterly archive:** a ZIP archive with exactly one regular, unencrypted, DEFLATE member
     named as the master index. It is decompressed as a stream, its CRC and size are checked,
     and its expanded size must be at most $B_{\mathrm{exp}}$.
   - **Text, both families:**
     - ASCII only, with no control characters other than tab, carriage return and line feed;
     - CRLF line endings for quarterly files and LF for daily files;
     - exactly one header line, followed by at least one line that is not a separator.
5. **Retention.** A valid body is staged under its command attempt. It is then promoted to a
   content-addressed location keyed by kind, period and $h_x$, before the source is marked
   downloaded. Every failed or invalid body is kept in quarantine with its receipt and
   classification. An invalid body is never accepted as an empty index.
6. **Snapshot record.** Each record holds $\sigma$, $h_x$, the byte count, $\tau_x$ and the
   HTTP validators: entity tag, last-modified, content type and encoding. Bytes already seen
   map to their existing record, which keeps its first receipt time. The source's state still
   records the latest receipt.
7. **Pinning.** $b(\mathcal{W}, \sigma)$ is written once, and the first accepted pin wins. A
   retry completes unpinned sources and never replaces a pin. An immutable snapshot set is
   emitted for the later stages only when three things hold: every source is pinned,
   discovery was complete, and no gap occurred.
8. **Crash recovery.** Staging and promotion are checkpointed. Recovery re-validates retained
   bytes against their recorded receipt before using them.

#### Assumptions and limitations

1. **Validation means complete.** A 200 response that passes validation is taken to be a
   complete index. *Breaks if:* the SEC serves a well-formed but truncated file, such as a
   partial rebuild; it would be accepted. For closed quarters, C5's approval gate is the
   backstop.
2. **Daily files are rarely fetched again.** A daily run never re-fetches an accepted daily
   file. A reconciliation run, however, refreshes every daily file in any daily directory it
   lists because that directory still holds a pending source (C1, step 1). One pending daily
   source therefore causes that quarter's daily files to be downloaded again. Corrections are
   expected to arrive through quarterly files, not through daily files.
3. **Receipt time is local.** $\tau_x$ is the local receipt time, not an SEC revision time.
   HTTP validators are kept but do not order revisions.
4. **Guards are not measured bounds.** The byte guards and $T_{\mathrm{ex}}$ are selected
   limits. The largest quarterly ZIP seen was 3.9 MB, 28.7 MB expanded, and expansion ratios
   ranged from 6.3 to 8.0.
5. **Strict rules, small sample.** The envelope rules are strict; any non-ASCII byte is
   refused, for example. Only the ten retained real files have been checked against them.

#### Evaluation criteria

- **Acceptance.** No snapshot is accepted without full validation and hash-verified retention.
- **Failure evidence.** Every failed or invalid body is retained with its classification.
- **Retries.** Retries are bounded, counted durably and deferred near the deadline.
- **Pins.** An exact retry of a command attempt resumes without replacing any pin.

#### Open questions for the reviewer

1. Should refresh use conditional requests (entity tag, last-modified) to avoid re-downloading
   unchanged quarterly files?
2. Are the validation rules right for historical indexes, or likely to refuse valid files? The
   rules in question are strict ASCII, a single archive member and strict line endings.

### C4. Index parsing and observation normalization

#### Notation

No symbols beyond the shared table.

#### Problem formulation and data-generating story

**File layout.** A master index file has these parts, in order:

- an optional preamble of blank lines and labeled lines (Description:, Last Data Received:,
  Comments:, Anonymous FTP:, Cloud HTTP:);
- a header;
- a line of dashes;
- one row per filer and filing, with five pipe-separated fields: CIK, company name, form type,
  date filed and file name.

The quarterly header reads CIK|Company Name|Form Type|Date Filed|Filename, with dates as
YYYY-MM-DD. The daily header ends in File Name, with dates as YYYYMMDD.

**What the rows mean.** A filing with several filers appears once per filer, each under its own
CIK and path. Amendments carry their own form type and accession number. A daily file can list
filings dated in earlier quarters: the daily index dated 2026-09-30 includes a row dated
2025-08-25.

**Observed sample.** Ten real files were scanned in full, 970,622 rows in all. Every row had
five fields and an accession-style path, and no path without an accession number was seen. The
sample's three closed-quarter quarterly files have 300,561, 318,647 and 302,315 rows. They
repeat a logical key $k$ with conflicting values 21, 24 and 6 times. Of those 51 conflicts, 45
differ only in form type and 6 only in company name. Under the rule in step 5 below, all three
files are refused whole.

**Estimand.** For each snapshot, every row as a normalized observation tied to its line and
original text; or a refusal of the whole snapshot, with the first failing line and its reason.

#### Estimation / inference procedure

1. **Structure.** Allow only the known preamble labels, then require the family's exact header
   and a line of dashes. Every line after that must be a data row: no blank rows and no repeated
   header. A file with no rows is refused.
2. **Field rules.**
   - Trim the fields. No field may contain a non-ASCII byte, a control character, a tab or a
     line break.
   - The CIK is 1 to 10 digits, zero-padded to $c$.
   - Company name and form type must be non-empty and are kept as listed; there is no entity
     resolution.
   - The filing date must use the family's format and be a real calendar date.
   - The path must be a safe relative path: not absolute, with no traversal, empty segments,
     backslashes, control characters or escapes.
   - When the path lies under the edgar/data tree with a numeric CIK segment, that segment must
     equal the row's CIK.
   - $a$ is extracted only when the path has exactly the form edgar, data, the CIK, then a file
     named by an accession number (ten digits, two, then six, joined by hyphens) with the
     text-file extension. Otherwise $a$ is null, and the row stays usable.
3. **Key.** $k = (c, p)$. Company name and date never identify a filing, and a changed path is
   a different key.
4. **Provenance.** Each observation carries $\theta_x$, its line number $\ell$ and its original
   fields $\omega$.
5. **Duplicates within a snapshot.** Duplicates of $k$ with identical normalized fields
   collapse in the catalog, but every observation is kept. Duplicates of $k$ with different
   fields refuse the whole snapshot.
6. **Refusal.** Any row error refuses the whole snapshot; there is no partial source. The line,
   the reason and the raw bytes are retained in quarantine.
7. **Output.** Observations are stored immutably, addressed by $\theta_x$, with row counts,
   distinct-key counts and per-quarter row counts. After writing, every stored observation is
   read back and re-derived from its $\omega$, and the counts are checked.
8. **Replay.** A new $\nu_P$ or $\nu_S$ is a new processing identity, re-parsed from retained
   bytes without any request.

#### Assumptions and limitations

1. **The key identifies a row.** $k = (c, p)$ is assumed to identify one catalog row.
   *Breaks if:* the SEC lists the same $(c, p)$ with different form types or names, as the
   sample shows. Step 5 then refuses every sampled closed quarter, so no real closed quarter
   can publish today.
2. **Null accession numbers are untested on real data.** They are supported, but only invented
   examples exist, and no legacy path family has been checked on real files.
3. **One bad row blocks a quarter.** The rules are strict enough that a single bad row makes a
   whole quarter's index unusable.
4. **No name reconciliation.** Company names are taken as listed in each row; nothing reconciles
   them across rows or over time.

#### Evaluation criteria

- **Round trip.** Every stored observation re-derives exactly from its original fields, and
  stored counts match.
- **Example files.** Small hand-built example files cover:
  - both families;
  - amendments and null accession numbers;
  - identical and conflicting duplicates;
  - unsafe paths and malformed dates;
  - rows dated in another quarter.
- **Real files.** Full scans of the retained real files match their recorded row counts and
  date ranges, and reproduce the refusals.

#### Open questions for the reviewer

1. What are the 51 conflicts in EDGAR terms? Candidates include one filing listed under two form
   types, a renamed filer, or an artifact of how the index is built.
2. Should refusal be per row, quarantining bad rows within an error budget, instead of per
   file?

### C5. Quarter catalog resolution

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\succ$ | Precedence order on observations of one key (step 5) | strict order |
| $\hat{o}_q$ | $\hat{o}_q(k)$ is the winning observation of key $k$ in quarter $q$ | observation |
| $\mathcal{U}_q$ | Keys kept as unresolved absences | set |
| $\mathcal{X}_q$ | Keys withdrawn | set |

#### Problem formulation and data-generating story

For quarter $q$, the target is the SEC's current catalog of rows dated in $q$: the key set,
and each key's current fields. Three kinds of evidence overlap:

- **The quarterly file of $q$.** Once $q$ is closed, the design treats it as the authority on
  membership, because the SEC rebuilds it weekly with corrections and removals.
- **Daily files.** Each is fixed once published and does not reflect later removals.
- **Quarterly files of other quarters** that carry rows dated in $q$.

Each source can have several snapshots over time.

**Estimand.** $A_q$ estimates that target. The rules must avoid four errors:

- treating absence as removal (after a failed request, from a partial quarter-to-date file, or
  in an open quarter that is still filling);
- creating duplicate filings from overlapping sources;
- silently mixing parser versions;
- producing output that cannot be reproduced.

#### Estimation / inference procedure

1. **Contributing set.** Start from $\mathrm{src}(A_q)$ plus the incoming snapshots.
2. **Selection $\psi$: one snapshot per source.**
   - Equal hashes are the same input. If both were processed under the same versions, their
     outputs must match, or the build is refused.
   - Otherwise the later $\tau$ wins. Different hashes with equal $\tau$ are refused as
     ambiguous.
   - A selected snapshot not yet processed under the run's $(\nu_P, \nu_S)$ is first re-parsed
     from its retained bytes.
3. **Membership.** $\mu_q$ is the selected snapshot of the quarterly source whose period is
   $q$. More than one is refused. If $\mu_q$ has no rows dated in $q$, it is refused as an
   invalid source.
4. **No-op.** If the selection's fingerprint equals $\phi(A_q)$, the result is "unchanged" and
   no generation is built.
5. **Precedence.** Among observations $o$ of $k$ from $\mathcal{S}_q$ with $Q(d) = q$, compare
   the tuple $\big(\mathbb{1}[\kappa = \text{quarterly}],\ \rho,\ \tau\big)$ lexicographically;
   higher wins, and remaining ties go to the smaller $\sigma$:

   $$\hat{o}_q(k) = \max\nolimits_{\succ}\ \{\, o \in O_x : x \in \mathcal{S}_q,\ k(o) = k,\ Q(d(o)) = q \,\}.$$

   - Any quarterly file outranks any daily file.
   - Between quarterly files, the later period wins, then the later receipt.
   - Between daily files, the later date wins, then the later receipt, then the smaller source
     identity.
6. **Proposed keys.** If $m_q$ is closed and $\mu_q$ exists, $K_q = M_q$. Otherwise $K_q$ is
   every key that has a winner.
7. **Classification.** For each $k \in A_q$:

   $$\mathrm{absent}(k) \iff k \notin K_q \ \lor\ \big(m_q = \text{open} \ \land\ \mu_q \text{ exists} \ \land\ k \notin M_q\big).$$

   - **Withdrawn.** If $m_q$ is closed and $\mu_q$ exists, the absent keys are withdrawn:
     $\mathcal{X}_q = \{k \in A_q : \mathrm{absent}(k)\}$.
   - **Unresolved absences.** Otherwise the absent keys are unresolved absences:
     $\mathcal{U}_q = \{k \in A_q : \mathrm{absent}(k)\}$. They stay in $C_q$ with their prior
     row and provenance unchanged, even when a newer observation of the key exists.
   - **Kept keys.** Every other key in $A_q \cap K_q$ takes its winner's row. It is
     **updated** if any of $(n, f, d, a)$ differs. If only $\theta$ differs, it counts as
     provenance refreshed. Otherwise it is unchanged.
   - **Added.** Every key in $K_q \setminus A_q$ is added.

   So $C_q$ is defined on $(K_q \cup \mathcal{U}_q) \setminus \mathcal{X}_q$. $\Delta_q$ lists
   the added, updated, withdrawn and unresolved-absence keys, each with full before and after
   rows.
8. **Gate.** $\gamma_q = \mathbb{1}\big[m_q = \text{closed} \ \land\ \mathcal{X}_q \ne \emptyset\big]$.
   An open quarter never withdraws.
9. **Identity.**

   $$\phi_q = H\big(q,\ \mathcal{S}_q \text{ sorted by } \sigma,\ m_q,\ \mu_q,\ \text{the retained basis}\big), \qquad g'_q = H(q,\ g_q,\ \phi_q).$$

   - Each element of $\mathcal{S}_q$ enters with its source, snapshot, $\tau$, versions, output
     hash and counts.
   - The retained basis is $g_q$ when $\mathcal{U}_q \ne \emptyset$, and none otherwise.
   - Run identities and timestamps never enter, so identical inputs on the same base give the
     same $g'_q$.
   - The base does enter, so the same content on a different base is a different candidate.
10. **Outputs.** The outputs are sorted catalog and change files, written as Parquet, plus a
    manifest. The manifest names:
    - $q$, $g'_q$, $g_q$, $\phi_q$ and the versions;
    - the complete $\mathcal{S}_q$, $m_q$ and $\mu_q$;
    - every file with its hash, length and row count;
    - the change counts and the gate.
11. **Independent check.** Before any record can refer to the candidate, a separate procedure
    re-reads every output and recomputes the result. It checks that:
    - every output row is either a selected observation's row or, for an unresolved absence,
      the exact base row;
    - the precedence order holds;
    - with closed membership, the key set equals $M_q$ exactly, and otherwise every winner's key
      is present;
    - every change re-derives from its before and after rows;
    - all counts agree.

#### Assumptions and limitations

1. **Closed-quarter authority.** Once $q$ is closed, the quarterly file of $q$ is assumed
   complete for keys dated in $q$. *Breaks if:* the SEC lists rows for $q$ elsewhere; those
   rows are excluded (system open question 3).
2. **Mode comes from the run date.** $m_q$ comes from $t^\star$, not from the data. Nothing
   requires $\mu_q$ to have been received after $q$ ended (system open question 3).
3. **Quarterly before daily.** A later daily row cannot change a key that a quarterly file
   carries until that quarterly file is refreshed.
4. **Receipt order.** Selection uses first receipt. Identical bytes keep their first $\tau$, so a
   return to older bytes is not selected; C7 reports it instead.
5. **Frozen absences.** An unresolved absence keeps its base row, even when a newer daily
   observation of the key exists.
6. **No lower bound on quarters.** A row dated before $q_0$ creates or updates its own,
   earlier quarter, under the rules for a quarter without membership.
7. **Business fields only.** Change classes compare business fields only. Provenance changes are
   counted, not reported as updates.

#### Evaluation criteria

- **Determinism.** The same inputs, versions and base give the same $g'_q$, and a repeat
  publishes nothing.
- **Independent recomputation.** The step 11 check passes for every candidate.
- **Safety.**
  - No key is withdrawn without closed membership, and an open quarter never shrinks.
  - An unresolved absence keeps its exact base row.
  - An empty or invalid membership file is refused before it can produce a candidate.
- **Complete change record.** Every difference between base and candidate appears exactly once
  in $\Delta_q$.

#### Open questions for the reviewer

1. Is the precedence order defensible? Two points matter most: a later quarter's quarterly file
   outranks $q$'s own file for a key dated in $q$, and every quarterly row outranks every daily
   row.
2. Should an unresolved absence keep its base row, or take newer evidence for the same key?

### C6. Publication, approval and rollback

#### Notation

| Symbol | Meaning | Domain / units |
|---|---|---|
| $\alpha$ | Approval record: quarter, candidate, base, fingerprint, membership hash $h_{\mu_q}$, gate-record hash, manifest hash and length, approver, time | record |
| $\Lambda$ | $\Lambda(g)$ is the lineage of generation $g$: $g$, its base, that base's base, and so on | sequence |

#### Problem formulation and data-generating story

**Goals.**

- Readers always see a complete, validated generation for each quarter.
- Concurrent publishers never lose an update.
- A closed quarter loses keys only through an explicit approval of that exact change.
- Any earlier state can be restored by an explicit, recorded move.
- No history is erased.

A failure can strike at any point, including between writing files and moving the pointer.

#### Estimation / inference procedure

1. **Reader contract.**
   - Read $\Pi_q$, then the manifest it names, then exactly the files that manifest lists.
     Never enumerate stored files.
   - Verify hashes, lengths, schemas, counts, quarter assignment and key uniqueness. A failed
     check fails the read, with no fallback to an older generation.
   - Generations are retained indefinitely, so a recorded $(q, g, \text{manifest hash})$ stays
     readable after the pointer moves. A consumer of several quarters records that vector.
2. **Publish.** Read $\Pi_q$ and its version, then build and check a candidate against that
   base (C5).
   - **Gated ($\gamma_q = 1$).** Write a gate record naming $q$, $g'_q$, $g_q$, $\phi_q$,
     $h_{\mu_q}$, the manifest and the change file. Report "awaiting approval" and leave the
     pointer alone.
   - **Otherwise.** Replace $\Pi_q$ conditionally on the version read. After a lost race,
     re-read the winner, rebuild against the new base and re-evaluate the gate. After
     $n_{\mathrm{pub}}$ lost races, or at the deadline, stop and report a publication conflict.
     A candidate built on an old base never becomes current.
3. **Commit boundary.** The conditional replace of $\Pi_q$ is the only commit.
   - A crash before the replace leaves an unreferenced generation.
   - A crash after it leaves committed data. Ancillary indexes (per-source published flags,
     publication receipts) are rebuilt from the committed manifest; they are never a second
     authority.
4. **Approval.** An operator names $q$, $g'_q$ and $h_{\mu_q}$. The checks run in this order:
   - If $g'_q$ is not a gated candidate whose content and gate record validate, refuse.
   - If $h_{\mu_q}$ does not equal its membership snapshot's hash, refuse.
   - If $\Pi_q$ already names $g'_q$, the result is unchanged.
   - If $\Pi_q$ no longer names the candidate's base, the result is stale.
   - If the membership source has a later snapshot with different bytes, the result is stale,
     because the candidate would withdraw keys on evidence the SEC no longer serves.

   Otherwise, write $\alpha$ (the first approval wins), write an activation record ahead of
   the move, and replace $\Pi_q$ conditionally. Because $g'_q$ hashes its base and fingerprint,
   an approval cannot carry over to another candidate, another base or a later download.
   Readers accept a gated generation only together with its exact $\alpha$.
5. **Rollback.** An operator names $q$, a from-generation, a to-generation, their own name and
   a reason. The checks run in this order:
   - If $q$ has no pointer, refuse.
   - If $\Pi_q$ already names the to-generation, the result is unchanged.
   - If $\Pi_q$ does not name the from-generation, the result is stale.
   - If the to-generation is not a strict ancestor of the from-generation in $\Lambda$, refuse.

   Otherwise, validate the target as a reader would, write the rollback record ahead of the
   move, and replace $\Pi_q$ conditionally. A rollback is not a pin: later publications build
   forward from the restored generation, and approvals and candidates remain.
6. **History.** The lineage, newest first, gives each generation's mode, gate, counts,
   membership hash, change file and approval. Together with the rollback and activation records,
   it is the quarter's change history.

#### Assumptions and limitations

1. **Linearizable replace.** Conditional replace on one record is linearizable, and all
   publishers and operators share one store.
2. **Per-quarter atomicity only.** No change spans quarters atomically.
3. **Trusted, informed approvers.** The approval request lists every withdrawn key's prior row,
   and the operator can see whether the SEC still serves the membership bytes. No second
   approver is required.
4. **Unbounded retention.** Storage grows with every snapshot and generation, and no retention
   policy has been chosen.
5. **Records are attempts.** A record written ahead of a pointer move records an attempt, not a
   result. The pointer and the lineage decide what took effect.

#### Evaluation criteria

- **Crash safety.** Faults are injected before the files are complete, before the pointer moves
  and just after it moves. In every case readers see only complete generations, and repair
  after the commit restores the indexes without a second advance.
- **Races.** Competing publishers never lose an update, and a lost race re-evaluates the gate
  against the new base.
- **Approval binding.**
  - A wrong hash is refused.
  - A moved base is stale.
  - A later download supersedes the candidate.
  - A repeat is idempotent.
- **Rollback.** Only ancestors are accepted, a repeat is idempotent, and a moved pointer is
  stale.
- **Durability.** Every written object is read back and hash-verified before anything refers
  to it.

#### Open questions for the reviewer

1. How does per-quarter generation-and-pointer publication compare with open table formats that
   offer snapshot isolation, time travel and multi-partition commits? Would adopting one change
   the design?
2. What evidence should an approver see before a withdrawal? Can any class of withdrawal be
   approved automatically?

### C7. Workflow composition and run accounting

#### Notation

No symbols beyond the shared table.

#### Problem formulation and data-generating story

Three workflows share C1–C6 and differ only in which sources they select:

- **Backfill:** the requested range $[q_0, q_1]$, in reuse mode.
- **Daily:** catch-up from $\beta$, in reuse mode.
- **Reconciliation:** the requested range, in refresh mode.

The intended schedule is a daily run in the early morning, US Eastern, after the SEC's
overnight daily-index processing, and a weekly reconciliation. A run can be interrupted at any
point, run out of time, or meet an outage that spans several quarters.

**Estimand.** Progress per source file that never loses older unresolved work, and a run
report stating exactly what is complete, pending, failed, quarantined or awaiting approval.
Coverage is never inferred from the latest filing date seen.

#### Estimation / inference procedure

1. **Pinning.** Before any work, a run freezes:
   - its command, run and attempt identities;
   - $t^\star$ and the resolved endpoint;
   - the effective configuration and its hash;
   - the code build identity, $\nu_P$ and $\nu_S$;
   - an absolute deadline.

   An exact replay of a completed attempt returns its stored report and sends no request. A
   replay whose frozen values differ is refused. A finished attempt is immutable, so retrying a
   failure needs a new attempt. Nothing retries automatically.
2. **Work units.** Each discovered source becomes its own unit, with an immutable discovery
   result holding only that source. The unit is the checkpoint and retry unit. A run selects:
   - the current discovery's units;
   - every earlier unit that is not complete under the current versions, except an older unit
     that only awaits publication and that a later completed download of the same source has
     superseded.
3. **Processing.** Units run one at a time, ordered by period and then source identity. Each
   unit is:
   1. collected (C3) under its original acquisition settings;
   2. parsed (C4) under the run's versions;
   3. published (C5, C6) to every affected quarter.

   Separate runs proceed concurrently. They coordinate only through C2 and through C6's
   conditional replace.
4. **Completion.** A unit is complete when, for every affected quarter, the active generation
   holds either its exact observation, or a strictly later observation of the same source under
   the same versions (a different hash with a later $\tau$).
5. **Stops.**
   - A denial, lost ownership or a block latch stops further acquisition in the run.
   - The deadline leaves undispatched units pending.
   - After a crash past a pointer move, the publish step stays resumable, and the unit is not
     finalized until repair is done.
6. **Revert detection.** For each processed source and affected quarter, raise a "source
   reverted" gap when all three of these hold:
   - the latest downloaded hash differs from the active selected hash;
   - the latest hash was first received before the active one;
   - the active one was received before the latest download.

   The remedy is an operator rollback (C6) to a generation built from the reverted-to bytes, if
   one exists.
7. **Report.** The report counts two things:
   - source units: discovered, downloaded, transformed, complete, pending, failed and
     quarantined;
   - quarter operations: published, unchanged and awaiting approval.

   It also lists every gap with its evidence, $\beta$ before and after, and each quarter's
   captured generation. Complete, pending and failed partition the units. Quarantined is a
   subset of failed, and awaiting approval a subset of pending.
8. **Run outcome.** The first rule that applies wins:
   1. fatal: access blocked, ownership lost, state conflict or internal error;
   2. quarantined: every unit was refused, and every gap stems from those refusals;
   3. incomplete: any gap or failed unit remains;
   4. awaiting approval: the only unresolved work is gated, even beside complete units;
   5. incomplete, when other pending work sits beside complete units; otherwise pending;
   6. no new sources: a daily run that discovered nothing, had nothing unresolved before and
      published nothing;
   7. success if any quarter was published; otherwise unchanged.
9. **Coverage rule.** A requested quarter whose listing is valid but holds no index is an
   unresolved baseline unit. Baseline coverage is complete only when every requested quarter is
   accounted for.

#### Assumptions and limitations

1. **Sequential units.** Units within a run are processed one at a time. Parallelism comes only
   from separate runs, which share one request budget.
2. **One correction channel.** Weekly reconciliation is the only way corrections reach closed
   quarters. It re-downloads every quarterly file in the range: at the intended 2010Q1 start,
   68 files totaling about 210 MB by their listed sizes.
3. **Schedule is not freshness.** A schedule does not establish freshness. A run with no new
   sources is distinct from a failed discovery, and a weekend alone is not staleness.
4. **Gated runs repeat.** A gated candidate is staged again by every run, so each run reports
   awaiting approval until an operator acts.

#### Evaluation criteria

- **Catch-up.** Outages that span several quarters, a fourth-to-first-quarter transition and an
  older backlog all catch up without losing pending work.
- **Coverage accounting.** Valid-empty and failed outcomes stay distinct, and no maximum date
  stands in for coverage.
- **Report integrity.** A stored report re-derives its outcome from its own contents.
- **Replay.** An exact replay of a completed run sends no requests and returns the same report.
- **Shared path.** Backfill, daily and reconciliation use the same acquisition, parsing and
  publication path.

#### Open questions for the reviewer

1. Is weekly re-download of every quarterly file the right reconciliation strategy? The
   alternatives are conditional requests, or some SEC signal of which quarters changed.
2. Is the run-outcome taxonomy adequate for operations? Is "awaiting approval" sound as a
   distinct outcome?

## Open questions for the reviewer

1. **Conflicting duplicates within a file block real data.** All three sampled closed-quarter
   files list the key $(c, p)$ more than once with conflicting fields: 21, 24 and 6 times. Of
   those 51, 45 differ only in form type and 6 only in company name. Because a conflict refuses
   the whole file, every sampled closed quarter is blocked. What do these rows mean in EDGAR?
   Which conflict policy and which key are state of the art?
2. **Logical identity.** Is $(c, p)$ the right key, or should it be built on the accession
   number? Weigh three cases: filings listed under several filer CIKs; path changes, which are
   now an addition plus a possible withdrawal; and legacy paths without an accession number.
3. **Closed-quarter membership.** By the rules in C5, steps 3, 6 and 7:
   - A row dated in $q$ that appears only in another period's file, or only in daily files
     received after $\mu_q$, cannot enter $q$'s closed catalog. The filing-date partition then
     keeps it out of every other quarter. Does EDGAR place a filing disseminated late in the
     quarterly file of its filing date, or of its dissemination date?
   - Should a quarter-to-date snapshot received before $q$ ended count as closed-quarter
     membership? Until a later refresh, it would propose withdrawing keys that the daily files
     of the quarter's last days had already added. Rows from those days that were not yet
     published would be excluded with no change record.
4. **Absence in the open quarter.** A key added from daily files after the latest
   quarter-to-date snapshot is absent from that snapshot by construction. Until the next
   refresh it is reported as an unresolved absence in every later generation, frozen at its
   first row. Should absence be judged against receipt times, for example by ignoring keys
   first seen after $\tau_{\mu_q}$?
5. **Revision order.** Is first local receipt the right order of revisions? Alternatives include
   the SEC's HTTP validators, the file's own "Last Data Received" line, or comparing content.
   How should restored older bytes be treated?
6. **Withdrawals.** Requiring human approval for every closed-quarter withdrawal is
   conservative by design. How does it compare with tombstones, bitemporal or valid-time
   modeling, or corroboration rules? What operator burden does it imply at the expected rate of
   SEC corrections?
7. **Publication protocol.** Per-quarter generations behind a conditional pointer resemble the
   write-audit-publish pattern and the commit protocols of open table formats. Would a standard
   table format give the same guarantees, including multi-quarter atomicity, with less custom
   machinery?
8. **Request governance.** Is the governor's effective ceiling of about $r/2$, with
   single-flight pacing after each completion, appropriate given the SEC's 10-per-second
   guidance? What throughput should the initial backfill expect: 68 quarterly files, plus about
   two quarters of daily files for the catch-up?
9. **Evaluation.** How should catalog quality be measured against an independent EDGAR source?
   Candidate measures are recall and precision of keys, agreement of fields, correction latency
   and false-withdrawal rate. Which reference source is best?
10. **Source choice.** Are the master indexes the right input for a filing catalog? Compare
    other EDGAR products: company or form indexes, bulk submission metadata, and feed archives.

## Evidence note: SEC filing submissions findings

This note adds evidence from `specs/findings/sec-filing-submissions-findings.md` (2026-10-19/20). It
does not change the method above. The evidence comes from one daily index (2026-10-15) and the feed
archive for the same day. Other days were not checked.

- **C4, rows dated in earlier quarters.** The 2026-10-15 daily index has 3,652 rows. 134 of them
  (110 distinct keys, from 109 accessions) have a filing date before 2026-10-01. They fall in 14
  filing quarters, from 2021Q1 to 2026Q3. 100 of the 109 accessions are submissions that the feed
  archive marks `<PRIVATE-TO-PUBLIC>`. Their form types are CORRESP, UPLOAD, 485APOS, DRS, 486APOS
  and 485BPOS. The tag name suggests that they were not public when filed and that the SEC published
  them on that day. SEC documentation was not checked. The other 9 are amendments (`TA-1/A`, `MA/A`,
  `MA-I/A`, `MA-A`) dated 2026-08-27 to 2026-09-30. Each index row carries the original filing date,
  not the publication date. For example, `0000000000-23-009731` (UPLOAD) has filing date `20230901`.
  Findings §§4.6–4.7.
- **C5, effect on closed quarters.** The local store has no accepted quarterly snapshot for any of
  the 14 quarters. Under step 6, all 110 keys entered their quarters' catalogs, and the curated
  generations of those quarters hold all of them. A later backfill makes each quarter's quarterly
  file its membership file $\mu_q$. If $M_q$ does not list these keys, step 7 withdraws them, and
  step 8 gates the candidate. A back-dated row received after $\mu_q$ cannot enter the closed
  catalog. The two daily indexes in the store together touch exactly the 16 curated quarters. The 5
  quarters that both touch are exactly the 5 quarters with a superseded generation. Findings §4.7.
- **System open question 3.** The evidence shows that the daily index uses the original filing date
  for submissions published late. It does not show whether the SEC adds these rows to the quarterly
  file of their filing date. One request for a closed quarter's quarterly file, for example 2021Q1,
  would test this. That request was not sent.
- **System open question 10, feed archives.** The 2026-10-15 feed archive is 1,610,242,722 bytes
  compressed and 20,742,318,080 bytes unpacked. Listed daily sizes for 2026-10-01 to 2026-10-16 are
  about 0.7–1.6 GB. The archive holds 2,627 files, one for each accession, and the largest file is
  352,590,758 bytes. A file is named `<accession>.nc`, or `<accession>.corrNN` for the 101
  `<PRIVATE-TO-PUBLIC>` submissions. The header `<ACCESSION-NUMBER>` agrees with the filename in all
  2,627 files. After the `.corrNN` suffix is removed, the accessions equal the distinct accessions
  of the daily index. One archive exceeds $B_{\mathrm{rx}}$ by about 24× and $B_{\mathrm{exp}}$ by
  about 39×. Findings §§4.2–4.5 and §6.
