# First-pass methodological review: SEC EDGAR filing platform methodology

The design's provenance discipline is better than most published EDGAR pipelines, but its acquisition plan rests on a request ceiling about 6.7 times lower than the SEC's published limit, it ignores the SEC's daily bulk Feed, and it misreads three SEC formats that would corrupt XBRL extraction (inline XBRL document sets, the `<XBRL>` wrapper, and SEC-generated "processed XBRL" documents). Those should be fixed before any parser is frozen.

## TL;DR

- **Acquisition is the binding error.** The SEC allows 10 requests per second per user; the inherited 1.5 req/s ceiling turns a backfill of about 17–21 days into 110 days. The SEC's daily Feed archives (one `.nc.tar.gz` per business day back to 1995 Q3, about 0.5–6 GB each) would replace about 300,000 requests per quarter with about 61–63 bandwidth-bound downloads and fit both backfill and daily ingestion (C1, C2).
- **XBRL extraction as specified is wrong in four places.** EDGAR processes all inline XBRL attachments of a submission together as one Inline XBRL Document Set (IXDS); the `<XBRL>` wrapper also marks traditional EX-101 instances and taxonomy files; dissemination files contain SEC-generated extracted instances that would double-count facts; and the duplicate-fact rule ignores XBRL International's complete/consistent/inconsistent classes. Adopt Arelle as the reference processor and XBRL US DQC rules for sign and scale (C3, C4, C6, C7).
- **The point-in-time model needs another time axis, and "immutable submissions" is wrong.** SEC Post-Acceptance Corrections change header fields, including filing date and form type, under the same accession; tombstones mix platform detection time into an SEC-time view; and the DERA "Financial Statement and Notes" data sets do carry dimensions and custom tags, contrary to the document, making them the better calibration reference (C5, C8, C10).

## Part 1 — Positioning against the published state of the art

### (a) Large-scale EDGAR acquisition and corpus construction

Published corpora — the Loughran–McDonald SRAF corpus (sraf.nd.edu), OpenEDGAR (Bommarito, Katz & Detterman 2018, arXiv:1806.04973), EDGAR-CORPUS (Loukas et al. 2021, arXiv:2109.14394) — use an index-driven crawl: read the full-index, fetch one file per filing, rate-limited to fair access. The design follows that pattern with stricter provenance (pinned catalog vector, content-addressed snapshots, explicit outcomes), which is ahead of the published tools.

What it ignores:

- **The real rate limit** of 10 requests per second per user (C2).\[1\]\[2\]
- **Bulk channels.** The SEC calls its nightly bulk ZIPs "the most efficient means to fetch large amounts of API data"; the daily Feed and Oldloads archives are documented on "Accessing EDGAR Data" (C1).\[3\]\[4\]
- **Cheap per-filing metadata:** the `.hdr.sgml` header-only file, the `index.json` in every accession directory, and the bulk `submissions.zip`.\[3\]\[4\]

### (b) SGML submission-envelope parsing

The authoritative grammar is the SEC's EDGAR Public Dissemination Service (PDS) Technical Specification (v2.0, March 2025), which enumerates every header and document tag and gives an SGML DTD (§3.4). The design's reading of the archive `.txt` layout agrees with the SEC Webmaster FAQ example, and it is right that item lines carry titles.\[5\]

What it ignores: the published DTD; that the PDS adds header tags over time (Release 25.1.1, March 2025, added `<LEGAL-ENTITY-IDENTIFIER>` and three address tags); the true scope of the `<XBRL>` and `<PDF>` wrappers; the SEC-generated "PROCESSED XBRL" documents marked `<DESCRIPTION>IDEA: XBRL DOCUMENT`; and Post-Acceptance Correction (PAC) semantics.\[6\]

### (c) XBRL / inline XBRL fact extraction and the fact data model

The state of the art is a validating processor (Arelle, certified by XBRL International; the SEC maintains its EDGAR plugins), the Open Information Model (OIM; xBRL-JSON/xBRL-CSV) as the fact model, and formal duplicate and calculation handling (XII Working Group Note on duplicate facts, 2025-01-14; Calculations 1.1, REC 2023-02-22).\[7\]\[8\]\[9\] The design's fact tuple is essentially an OIM fact plus provenance, which is good. It ignores IXDS semantics (Inline XBRL 1.1 §3.1; EDGAR Filer Manual Vol. II §5.2.5), the duplicate classes, taxonomy packages, DQC rules, and the full Transformation Registry.\[10\]

### (d) Point-in-time and bitemporal stores, versioned data lakes

The established model separates valid (event) time — here the acceptance instant — from transaction time, when the store recorded the fact (Jensen & Snodgrass 1999, IEEE TKDE, doi:10.1109/69.755613; SQL:2011 system-versioned and application-time tables, Kulkarni & Michels 2012, SIGMOD Record, doi:10.1145/2380776.2380786). Financial practice does the same: vendor point-in-time fundamentals and the St. Louis Fed's ALFRED vintages keep every vintage with its publication date. The design's `Known_t` is bitemporal in spirit but mixes axes — inclusion uses SEC acceptance time, exclusion uses platform detection time — and stores no transaction time.

For storage, Apache Iceberg, Delta Lake (Armbrust et al. 2020, PVLDB 13(12)), Apache Hudi and DuckLake provide snapshot isolation, time travel and atomic commits; lakeFS and Nessie add multi-table, git-like commits. The design re-implements a subset by hand.

### (e) Insider, beneficial-ownership and 13F structured data

The SEC publishes the Insider Transactions Data Sets, the Form 13F data sets and the EDGAR Ownership XML Technical Specification.\[11\] The academic standard adds cleaned vendor insider data (Thomson Reuters/Refinitiv "cleanse codes" — from my own knowledge, not re-verified) and routine/opportunistic classification (Cohen, Malloy & Pomorski 2012, Journal of Finance 67(3), doi:10.1111/j.1540-6261.2012.01740.x). The design's typed-record extraction is sound but misses the post-2023 13D/G submission types and voluntary XML period, Form 4/A scope heterogeneity, the exact 13F unit rule, and the SEC's 13F restatement-vs-addition semantics.

### (f) Event derivation from filings

The accounting literature treats 8-K item choice as a disclosure decision, not ground truth:

- Lerman & Livnat (2010, Review of Accounting Studies 15(4), doi:10.1007/s11142-009-9108-5) on the post-2004 items.
- Segal & Segal (2016), "Are managers strategic in reporting non-earnings news? Evidence on timing and news bundling," Review of Accounting Studies 21(4):1203–1244, doi:10.1007/s11142-016-9366-y, using "non-earnings 8-K filings from 2005 to 2013."
- He & Plumlee (2020), "Measuring disclosure using 8-K filings," Review of Accounting Studies 25(3):903–962, doi:10.1007/s11142-020-09551-y. It builds "four voluntary and two mandatory disclosure measures for 260,880 firm-quarters from 2005 through 2016."

The SEC is also moving item choice. On 21 May 2024, Erik Gerding, Director of the Division of Corporation Finance, said the Division "encourages the company to disclose that cybersecurity incident under a different item of Form 8-K (for example, Item 8.01)" when the incident is not material. The design labels header items as filer-declared, but it does not version the item table by effective date or treat Item 8.01 as a catch-all.

### (g) Provenance, evidence spans and extraction grading

W3C PROV-DM (2013) is the interchange standard for entity/activity/agent provenance. For generated text, the attribution literature (Rashkin et al., Computational Linguistics 2023, arXiv:2112.12870) sets the bar: "attributable to identified sources." The design's hash-verified byte-offset evidence spans are stronger than common practice; what it lacks is a PROV mapping and a statistical review policy.

## Part 2 — Numbered critique points

All points are first-pass and not yet adjudicated; ranked by expected value; C-numbers are stable.

### C1. Use the SEC daily Feed as the bulk acquisition unit for backfill and daily runs

- **Component:** P1, P2, P10; catalog constraint (governor, T_ex, byte guards).
- **Category:** adopt a better method.
- **Finding:** `/Archives/edgar/Feed/` holds one `YYYYMMDD.nc.tar.gz` per filing day from 1995 Q3 onward.\[3\]\[12\]\[13\]\[14\]
  - **Sizes and timing.** 2024 Q1 has 61 files, mostly 0.6–2 GB, ranging from about 0.5 GB to 4.9 GB (28 March 2024). 2025 Q1 peaks at about 6.1 GB.\[15\] Files were posted around 22:15–23:06 ET on the filing day.\[16\]
  - **Serialization.** The 2006 SEC README describes each archived filing as "a separate filing submission (without the binary feed header)". That is the PDS SGML serialization, not the archive `.txt` "labelled line" header.
  - **Cost.** A quarter costs about 61–63 requests and roughly 100 GB compressed (my estimate) instead of about 300,000 requests. The daily run could take one Feed file the same evening.
  - **What the design must add:**
    - a governor bulk lane with its own T_ex and byte limits and resumable transfer;
    - a reconciler that maps each `.nc` member to its catalog accession and compares document payload hashes against an archive-copy sample;
    - handling of Feed quirks: removals made on later days "will not be reflected in any previous daily, feed, or oldload index"; the 2025 Q1 files were regenerated in May 2025; and one file (20250324, about 100 MB) looks anomalously small.
  - Per-submission fetch stays as the repair path.
- **Expected value:** high — removes months of traffic and makes daily runs nearly request-free.
- **Sources:** SEC, "Accessing EDGAR Data," https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data; SEC Feed index, https://www.sec.gov/Archives/edgar/Feed/2024/QTR1/index.json (retrieved Oct 2026); SEC Oldloads listing, https://www.sec.gov/Archives/edgar/Oldloads/2022/QTR3/; SEC EDGAR README (2006, secondary copy via GitHub SamKogan/Edgar_Scrape).
- **Status:** first-pass — not yet adjudicated.

### C2. The inherited 1.5 req/s ceiling is unsupported by SEC policy; recompute at the published limit

- **Component:** P1 arithmetic, P10 assumption 4; catalog constraint (governor C2, r/2).
- **Category:** fix an error.
- **Finding:** The SEC publishes 10 requests per second per user across all machines. Over-limit traffic is throttled until the rate stays below threshold for 10 minutes. The SEC does not state the status code; community reports say 403.
  - **Recomputed backfill** at 300,000 submissions per quarter:

    | Rate | Per quarter | 48 quarters |
    |---|---|---|
    | 10 req/s (SEC limit) | about 8.3 h | 16.7 days |
    | 8 req/s (prudent) | about 10.4 h | 20.8 days |
    | 1.5 req/s (document) | 2.3 days | about 111 days |

  - **Recommendation.** Set the owner-wide ceiling at about 8 req/s, keeping the catalog's priority. That changes the 110-day figure, the "budget-limited is normal" outcome and the ordering rationale.
  - **Not verified:** whether the catalog's r = 3 was chosen for reasons the platform document does not show.
- **Expected value:** high — one configuration change cuts wall time about 6.7-fold even without C1.
- **Sources:** SEC, "Accessing EDGAR Data" (above); SEC Developer Resources, https://www.sec.gov/about/developer-resources; SEC Internet Security Policy, https://www.sec.gov/privacy.htm#security.
- **Status:** first-pass — not yet adjudicated.

### C3. Inline XBRL Document Sets: "each carrier is processed alone" breaks context and unit resolution

- **Component:** P5 steps 1 and 3, P7 assumption 6.
- **Category:** fix an error.
- **Finding:** EFM Vol. II §5.2.5 says: "A submission may have more than one attached document formatted using Inline XBRL. Inline XBRL formatted attachments are processed and validated together as an Inline XBRL Document Set (IXDS), as defined by section 3.1 of the Inline XBRL 1.1 Specification, producing a single target instance document." The 2019 EFM change explicitly allowed tagged content in more than one iXBRL attachment.\[17\]
  - **Why it breaks.** In an IXDS, contexts and units in one document's `ix:resources` serve facts in another, and continuations can cross documents. The rule "an unresolved reference refuses the carrier" will therefore refuse valid filings.
  - **Fix.** Assemble the IXDS per submission first, then extract. The exception is exhibit types such as filing-fee exhibits, which the EFM says are "processed and validated separately from the IXDS of the primary document."
  - **Keys.** Key facts by (accession, IXDS id, fact id), not δ.seq.
- **Expected value:** high — multi-document iXBRL would otherwise produce systematic refusals or silent fact loss.
- **Sources:** SEC, EDGAR Filer Manual Vol. II ch. 5 (June 2025), https://www.sec.gov/files/edgar/filermanual/edgarfilermmanual-vol2-c5.pdf; XBRL International, Inline XBRL 1.1 (2013), §3.1.
- **Status:** first-pass — not yet adjudicated.

### C4. Encoding classification misreads the `<XBRL>` wrapper and ignores SEC-generated processed-XBRL documents

- **Component:** P3 step 4 (enc), P5 step 1, P3 step 5 (document count).
- **Category:** fix an error.
- **Finding:**
  - **The wrapper is not specific to inline XBRL.** The PDS spec says filer-provided documents "with `<TYPE>` matching EX-101.* … are marked by an `<XBRL>` indicator tag." Traditional instances, schemas and linkbases therefore also start with the wrapper, and "inline-xbrl if it starts with the XBRL wrapper" mislabels them.
  - **The dissemination file contains SEC outputs.** These are R*.htm, FilingSummary.xml, uuencoded Financial_Report.xlsx and `{accession}-xbrl.zip`, MetaLinks.json, and an SEC-generated `{…}_htm.xml` extracted instance.
  - **Double counting.** That instance has an XBRL root, so the rule "xml with an XBRL root element" makes it a second carrier. Every inline fact would be counted twice, and the within-filing duplicate rule would fire.
  - **Fix.** Classify by declared TYPE plus root element after unwrapping. Exclude `DESCRIPTION = IDEA: XBRL DOCUMENT` documents from extraction, but keep `_htm.xml` as a free SEC-side reference for C7/C8.
  - **Document count.** Check whether PUBLIC DOCUMENT COUNT counts processed documents.
  - **Not verified:** that the archive `.txt` contains exactly the processed documents the PDS spec describes for `.dissem` files.
- **Expected value:** high — without it, the fact store is wrong for every iXBRL filing.
- **Sources:** SEC, EDGAR PDS Technical Specification v2.0 (March 2025), §2.3.2, §2.3.5, §2.3.7, https://www.sec.gov/files/edgar/pds_dissemination_spec.pdf.
- **Status:** first-pass — not yet adjudicated.

### C5. Post-Acceptance Corrections change header bytes, filing date and form type in place

- **Component:** cross-component assumptions 3 and 5, P2 pins, P7 quarter assignment Q(d_y), P9 assumption 3; catalog constraint (weekly reconciliation).
- **Category:** fix an error.
- **Finding:** The PDS spec defines PACs as "header tag changes to previously-filed submissions, deletion notices for previously-filed submissions, or form/document type changes … No document text is updated in a PAC."\[6\] `FILED AS OF DATE` is the "EDGAR assigned official filing date, or post acceptance new filing date," and `DATE AS OF CHANGE` is the "Date when the last Post Acceptance occurred."
  - **Consequences under one accession:**
    - the header can change, so h_x changes;
    - the filing date can move, so Q(d_y) and the partition are wrong;
    - the form type can change, so tier and parse rules are wrong.
  - **What survives.** Document payloads stay stable. That saves the evidence-span contract, because spans hash per document.
  - **Fix:**
    - identity = accession plus a header-revision sequence;
    - per-document payload hashes as the immutable layer;
    - header-date disagreements recorded as first-class revisions, not gaps.
  - The SEC rebuilds full and quarterly indexes "weekly, early on Saturday mornings" to absorb PACs, which matches the catalog's weekly reconciliation.
- **Expected value:** high — falsifies a load-bearing assumption affecting partitioning and reproducibility.
- **Sources:** SEC, PDS spec (above), §2 and §3.3.1; SEC, Webmaster FAQ, https://www.sec.gov/about/webmaster-frequently-asked-questions; SEC, "Accessing EDGAR Data" (post-acceptance corrections).
- **Status:** first-pass — not yet adjudicated.

### C6. Adopt XII duplicate-fact classes and fix the cell definition

- **Component:** P5 step 4, P7 AsOf/First, Notation (κ).
- **Category:** adopt a better method.
- **Finding:** XII distinguishes complete, consistent and inconsistent duplicates. Numeric facts with different `decimals` whose values agree after rounding are consistent, not inconsistent.
  - **Within a filing.** The design flags any value difference as inconsistent. That falsely flags every iXBRL filing that tags "1.1 million" and "1,064,000" for the same fact.
  - **Across filings.** The same issue creates pseudo-revisions in AsOf_t when a later comparative rounded to millions "changes" a value first reported in thousands.
  - **Fix:**
    - add decimals and `xml:lang` to fact identity;
    - resolve duplicates within an IXDS per the Working Group Note, keeping the most accurate consistent duplicate;
    - count a cross-filing revision only when fact-value intervals do not intersect (Calculations 1.1).
- **Expected value:** high/medium — prevents systematic false inconsistency and false-restatement signals.
- **Sources:** XBRL International, "Handling Duplicate Facts in XBRL and Inline XBRL 1.0," WGN 2025-01-14, https://www.xbrl.org/WGN/xbrl-duplicates/WGN-2025-01-14/xbrl-duplicates-2025-01-14.html; XBRL International, Calculations 1.1, https://www.xbrl.org/Specification/calculation-1.1/REC-2023-02-22/calculation-1.1-REC-2023-02-22.html.
- **Status:** first-pass — not yet adjudicated.

### C7. Validate the bespoke taxonomy-free parser against Arelle, with DQC rules for sign and scale

- **Component:** P5 assumptions 1–3; system open question 4.
- **Category:** adopt a better method.
- **Finding:**
  - **Reference processor.** Arelle is an XII-certified validating processor supporting Inline XBRL 1.1, Taxonomy Packages 1.0 and xBRL-JSON/CSV, and the SEC maintains its EDGAR plugins. A bespoke parser is defensible for provenance (element paths, byte spans), but its correctness should be measured against Arelle's output for the same IXDS on the regression sample.
  - **Sign and scale.** "Scale and sign are trusted" ignores the free XBRL US Data Quality Committee rules, for example DQC_0015 Negative Values and the scale checks for common stock outstanding and balance-sheet monetary amounts. They run in Arelle.
  - **Taxonomies.** Extension taxonomies are already inside the retained submission. Only standard taxonomies (us-gaap, dei, srt, ifrs) need external packages. These are a few dozen versioned zips that can be retained once as content-addressed artifacts, which largely removes the governor objection.
  - **Transformation registry.** ℛ should be the complete Transformation Registry versions the EFM permits, plus ixt-sec. I did not re-verify which versions are permitted.
- **Expected value:** high — detects the largest known XBRL error classes cheaply and gives a reference implementation.
- **Sources:** Arelle, https://github.com/Arelle/Arelle and https://arelle.org/; XBRL US, "Approved Validation Rules," https://xbrl.us/home/priorities/data-quality/rules-guidance/; XBRL US, DQC_0015, https://xbrl.us/data-rule/dqc_0015/; Debreceny et al. (2010), Journal of Accounting and Public Policy 29(3).
- **Status:** first-pass — not yet adjudicated.

### C8. DERA "Financial Statement and Notes" data sets are mischaracterised and are the better calibration reference

- **Component:** P5 problem formulation and evaluation; system open question 9.
- **Category:** fix an error.
- **Finding:** The document says the DERA sets have "the same provenance limits" as companyfacts. The FSN readme says otherwise:
  - its TAG table includes "all custom taxonomy tags defined in the submissions";
  - "DIM is a data set containing XBRL dimensional tags";
  - the data are "presented without change from the 'as filed' financial reports";
  - it has been updated monthly since November 2020.

  Even the compact Financial Statement Data Sets include custom tags.\[18\] Companyfacts, by contrast, keeps only facts that "use a non-custom taxonomy" and "apply to the entire filing entity," and only for forms 10-Q, 10-K, 8-K, 20-F, 40-F, 6-K and variants. Use FSN plus Arelle or the SEC `_htm.xml` instance as primary per-accession references, with companyfacts secondary.
- **Expected value:** medium-high — a factual error steering evaluation toward the weaker reference.
- **Sources:** SEC, FSN readme, https://www.sec.gov/dera/data/fsnds.pdf; SEC, "Financial Statement and Notes Data Sets," https://www.sec.gov/data-research/financial-statement-notes-data-sets; SEC, FSDS readme, https://www.sec.gov/dera/data/fsds.pdf; SEC, "EDGAR Application Programming Interfaces," https://www.sec.gov/search-filings/edgar-application-programming-interfaces.
- **Status:** first-pass — not yet adjudicated.

### C9. The 256 MiB byte guard sits below the SEC's stated maximum submission size

- **Component:** P2 (B_rx, oversize), Notation; catalog constraint (T_ex, takeover bound U).
- **Category:** fix an error.
- **Finding:** The PDS spec says disseminated submissions "may be as small as 1 KB or as large as 400 MB," with "average submission size … approximately 800 KB."\[6\] 256 MiB (about 268 MB) therefore parks, by design, the largest filings the SEC says exist. They are rare but real: securitization filings and annual reports with large uuencoded exhibits. Set B_rx at or above 400 MB plus margin in a separate oversize lane with its own T_ex, or route such filings to the Feed (C1).
- **Expected value:** medium — a bounded but certain completeness gap; the guard is otherwise unsupported.
- **Sources:** SEC, PDS spec v2.0, §1 (above).
- **Status:** first-pass — not yet adjudicated.

### C10. Make the point-in-time store genuinely bitemporal

- **Component:** P7 (Known_t, tombstones), Composition, cross-component assumption 8.
- **Category:** adopt a better method.
- **Finding:** Known_t admits rows by SEC acceptance time but removes them by t^det, the platform's catalog-receipt time. It therefore reproduces neither "what EDGAR showed at t" nor "what this platform had at t."
  - **Store both times:**
    - valid/event time: acceptance, plus the SEC-side removal time when known;
    - transaction time: when the platform first published each row in a generation.
  - **Offer two operators:**
    - `KnownBySEC_t`, for event studies;
    - `KnownByPlatform_t`, for reproducing what a model run on date t could see.
  - The pinned-vector record supplies transaction time only if every consumer records it. A row-level publication timestamp makes it queryable.
- **Expected value:** medium-high — reproducing past model inputs is the main purpose of a point-in-time store.
- **Sources:** Jensen & Snodgrass (1999), IEEE TKDE 11(1), doi:10.1109/69.755613; Kulkarni & Michels (2012), SIGMOD Record 41(3), doi:10.1145/2380776.2380786; ALFRED, https://alfred.stlouisfed.org/.
- **Status:** first-pass — not yet adjudicated.

### C11. Replace the custom per-quarter pointer with an open table format

- **Component:** P7 steps 2–10, cross-component assumptions 7–8; P7 open question 1.
- **Category:** adopt a better method.
- **Finding:** Snapshot-isolated commits, time travel, manifest file lists with row counts, compaction and rollback-to-snapshot are standard in Iceberg and Delta Lake. Multi-table atomic commits come from catalog-level transactions (Nessie, lakeFS, DuckLake's SQL catalog). This is from my knowledge of their documentation, not re-verified. Keep the content-addressed raw-bytes store and the independent semantic check, run as a pre-commit validator, and delegate the commit protocol. That removes "nothing spans quarters atomically" and the race and merge logic.
- **Expected value:** medium — less custom code to verify; cross-quarter consistency for free.
- **Sources:** Apache Iceberg spec, https://iceberg.apache.org/spec/; Armbrust et al. (2020), PVLDB 13(12).
- **Status:** first-pass — not yet adjudicated.

### C12. The single-valued cover record and context CIK mishandle multi-class registrants and co-registrants

- **Component:** P5 step 5, Notation (ζ, κ), system open question 5.
- **Category:** fix an error.
- **Finding:**
  - **Multi-class.** Multi-class issuers report `dei:EntityCommonStockSharesOutstanding` per class on `us-gaap:StatementClassOfStockAxis`, so "shares outstanding with their date" collapses classes.
  - **Exchange listing.** `dei:TradingSymbol` and `dei:SecurityExchangeName` are per security: TradingSymbol is required where a symbol exists, and SecurityExchangeName is "required if a fact for TradingSymbol exists."
  - **Co-registrants.** Co-registrant facts share the parent's CIK in the context and are distinguished by `dei:LegalEntityAxis`. Keying entity by context CIK misattributes them.
  - **Fix.** Make the cover record multi-valued by dimension, and derive the cell's entity from (identifier, LegalEntityAxis member).
  - The axis conventions are my reading of EDGAR XBRL Guide practice and were not re-fetched this pass.
- **Expected value:** medium — affects share counts, market-cap denominators and subsidiary-issuer filings.
- **Sources:** XBRL US, "Inline XBRL Cover Page Disclosure" fact sheet, https://xbrl.us/wp-content/uploads/2020/05/inline-coverpage-factsheet.pdf; SEC, EDGAR XBRL Guide (August 2026), https://www.sec.gov/files/edgar/filer-information/specifications/xbrl-guide.pdf.
- **Status:** first-pass — not yet adjudicated.

### C13. Schedules 13D/13G: voluntary XML from 18 December 2023, new submission-type names, 10 p.m. cutoff

- **Component:** P6 (carriers, assumption 3), ν_F, P8 step 5, P3 filed-as-of reading.
- **Category:** fix an error.
- **Finding:** EDGAR Release 23.4 let filers "voluntarily submit submission types Schedule 13D and Schedule 13D/A online in a structured XML format until December 18, 2024, on which date compliance … will be required." It also moved "cut-off times … for Schedule 13D, Schedule 13G, and corresponding amendments, from 5:30 p.m. to 10:00 p.m."
  - **Boundary.** 18 December 2024 is the mandatory date, but XML schedules exist from 18 December 2023, so the boundary must be detected per document.
  - **Submission types.** The XML schedules use submission types named "SCHEDULE 13D/13G" (with /A), distinct from legacy "SC 13D"/"SC 13G". A ν_F that lists only the legacy names tiers them as 4.
  - **Not verified:** the exact full-index strings; check them against the catalog.
- **Expected value:** medium — silent mis-tiering and a mis-dated boundary for a whole family.
- **Sources:** SEC, "EDGAR Release 23.4," https://www.sec.gov/submit-filings/edgar-news-announcements/edgar-release-23-4.
- **Status:** first-pass — not yet adjudicated.

### C14. 13F: key the unit table by filing date (amendments included) and model restatement vs addition

- **Component:** P6 (𝒱, step 4), P8 step 5, P7 views.
- **Category:** fix an error.
- **Finding:**
  - **Unit change.** The SEC FAQ says "The compliance date for the form amendments to Form 13F is January 3, 2023," with values "rounded to the nearest dollar (rather than to the nearest one thousand dollars)." Practitioner guidance confirms that amendments for pre-2023 periods filed after that date use dollars, so 𝒱 must key on filing date, never report period.
  - **Amendment semantics.** For a restatement, "you must resubmit your entire filing, as corrected … your amended filing will supersede your original filing." A new-holdings amendment "will supplement the original filing."
  - **View.** P7 should offer a 13F holdings view that applies these rules. Latest-accepted-per-cell does not fit holdings tables without a cell key.
  - **Range check.** Filer 1,000× scaling errors around the transition are widely reported (secondary sources only), so add a range check.
- **Expected value:** medium — prevents 1,000× errors and wrong holdings aggregation.
- **Sources:** SEC, "Frequently Asked Questions About Form 13F," https://www.sec.gov/rules-regulations/staff-guidance/frequently-asked-questions-about-form-13f; SEC, Form 13F, https://www.sec.gov/files/form13f.pdf.
- **Status:** first-pass — not yet adjudicated.

### C15. Do not read a Form 4/A as a full replacement by default

- **Component:** P6 open question 2, P8 step 5.
- **Category:** fix an error.
- **Finding:** I found no SEC instruction requiring a Form 4/A to restate the entire form, and filed amendments vary:
  - one restates "the amended information in its entirety";
  - another was filed "SOLELY TO ADD THE CONFORMED SIGNATURE";
  - another is "Amended to correct date of grant."

  Full replacement would delete valid rows when an amendment carries only corrected rows. Store amendment rows as a linked second set (via `dateOfOriginalSubmission`, reporting owner and issuer), with a level-B amendment-scope field (full, partial, administrative, unknown).
- **Expected value:** medium — insider-trade counts are sensitive to double-counting or deletion.
- **Sources:** SEC EDGAR Form 4/A (1999), https://www.sec.gov/Archives/edgar/data/0001042351/000091019599000341/0000910195-99-000341.txt; Form 4/A (2002), https://www.sec.gov/Archives/edgar/data/804055/000080405502000147/car302.htm; SEC, Ownership XML Technical Specification, https://www.sec.gov/info/edgar/ownershipxmltechspec.htm.
- **Status:** first-pass — not yet adjudicated.

### C16. Treat acceptance as the EDGAR availability instant only up to a dissemination lag

- **Component:** cross-component assumption 4, P7 s(·), system open question 3.
- **Category:** extend scope.
- **Finding:**
  - **Measured lags.** Rogers, Skinner & Zechman (2017) show that in their Form 4 sample "the majority of filings are available to paying subscribers of the SEC's public dissemination system (PDS) feed before they are posted to the EDGAR website." Prices respond "beginning around 30 seconds before public posting." Bolandnazar, Jackson, Jiang & Mitts (2020) exploit the same early-distribution window.
  - **SEC statements.** An older PDS spec says acceptance-to-dissemination "usually takes no longer than two (2) minutes."\[19\] "Accessing EDGAR Data" says some submissions beginning after 5:30 p.m. ET (10 p.m. for Forms 3/4/5) "will be disseminated the next business day." That wording is ambiguous between index placement and posting; verify it.
  - **What to store.** Store τ_x on every row as the platform-side upper bound.
  - **Session rule.** Offer a session variant that treats acceptances within a configurable window before the close (or after 17:30) as next-session.
- **Expected value:** medium-low — matters for intraday and close-boundary studies.
- **Sources:** Rogers, Skinner & Zechman (2017), Journal of Accounting Research 55(2), doi:10.1111/1475-679X.12167; Bolandnazar et al. (2020), Journal of Finance 75(1), doi:10.1111/jofi.12844; SEC, PDS spec (2010), https://www.sec.gov/info/edgar/pdsdissemspec910.pdf.
- **Status:** first-pass — not yet adjudicated.

### C17. Use bulk submissions metadata, accession `index.json` and `.hdr.sgml` for planning

- **Component:** P1 (pre-run measurement, oversize), P3 cross-checks, P8 item cross-check.
- **Category:** adopt a better method.
- **Finding:** `submissions.zip` (nightly, one request) carries per-filing arrays with keys `accessionNumber, filingDate, reportDate, acceptanceDateTime, act, form, fileNumber, filmNumber, items, core_type, size, isXBRL, isInlineXBRL, isXBRLNumeric, primaryDocument, primaryDocDescription`. These were read from a data.sec.gov submissions JSON for this review.
  - **Uses:**
    - per-tier and per-quarter size totals before the first backfill;
    - oversize pre-screening by `size`;
    - an independent acceptance timestamp to test the Eastern-to-UTC conversion (assumption 9);
    - routing to P5 by isXBRL/isInlineXBRL.
  - **Caveats:**
    - older entries show midnight-Eastern `acceptanceDateTime` (e.g. "2002-02-13T05:00:00.000Z"), so they carry no real time;
    - the `items` format is not verified; the Webmaster FAQ describes numeric codes such as "2.02".
  - This annotates catalog rows without creating them, so "listing only" holds.
  - `.hdr.sgml` gives P3/P4 the header without the payload.\[3\]
- **Expected value:** medium — turns guessed durations and oversize counts into measured ones for a handful of requests.
- **Sources:** SEC, "EDGAR Application Programming Interfaces" (above); SEC, "Accessing EDGAR Data" (paths, `.hdr.sgml`); SEC, Webmaster FAQ (above).
- **Status:** first-pass — not yet adjudicated.

### C18. Order the backfill quarter-major, not tier-major across 48 quarters

- **Component:** P1 step 5, P10 coverage.
- **Category:** adopt a better method.
- **Finding:** Ordering by tier first, then date descending, across the whole range means no quarter reaches coverage 1 until the last tier-4 request. Under the coverage rule, every quarter stays "not covered" for months. Quarter-major order (newest quarter first, all tiers) produces a growing prefix of fully covered quarters while still serving nowcasting. With C1 the question largely disappears.
- **Expected value:** medium — usable complete quarters early at no cost.
- **Sources:** own reasoning from the document's coverage rule (P10 step 9).
- **Status:** first-pass — not yet adjudicated.

### C19. "Identity content encoding" conflicts with the SEC's recommended request headers

- **Component:** P2 step 4; catalog constraint (inherited transport validation).
- **Category:** fix an error.
- **Finding:** The SEC's sample declared-bot headers include `Accept-Encoding: gzip, deflate`.\[3\] Requiring identity encoding forgoes compression of text-heavy bodies, which is several-fold for HTML/SGML (my estimate). Request gzip, decode, and validate and hash the decoded bytes as "the SEC's original bytes," recording Content-Encoding as a transport attribute. Not verified: whether Archives responses actually return `Content-Encoding: gzip`, `ETag` or `Last-Modified`.
- **Expected value:** medium-low — saves bandwidth, not requests.
- **Sources:** SEC, "Accessing EDGAR Data" (fair-access sample headers, above).
- **Status:** first-pass — not yet adjudicated.

### C20. Fill ticker history from as-filed cover-page and Form 3/4/5 symbols

- **Component:** P4 (𝒯, assumption 3); P4 open question 2; system open question 6.
- **Category:** extend scope.
- **Finding:** Two acceptance-timed ticker sources are already in retained submissions:
  - cover-page `dei:TradingSymbol`/`dei:SecurityExchangeName`, under the 2019 FAST Act rule (Release 33-10618);
  - `issuerTradingSymbol` in Forms 3/4/5 XML.

  Cover tagging phased in with iXBRL:
  - large accelerated filers for fiscal periods ending on or after 15 June 2019;
  - accelerated filers from 15 June 2020;
  - all others from 15 June 2021.

  An 8-K filed before a company's first iXBRL 10-Q "need not comply." Together these give level-A ticker observations back to about 2003 for Section 16 issuers, and from 2019–2021 for cover pages.
- **Expected value:** medium — closes most of the ticker-history gap with zero new requests.
- **Sources:** Nelson Mullins (2019), https://www.nelsonmullins.com/insights/blogs/securities-in-a-second/compliance-and-disclosure-interpretations/sec-provides-interpretive-guidance-on-inline-xbrl; XBRL US cover-page fact sheet (above).
- **Status:** first-pass — not yet adjudicated.

### C21. ν_I should be an effective-dated crosswalk, and Item 8.01 a recognised catch-all

- **Component:** P3 step 3, P8 assumptions 1–2, ν_I.
- **Category:** adopt a better method.
- **Finding:**
  - **Numbering history.** Item numbering changed in 2004; pre-2004 items were "1"–"13" per the SEC Webmaster FAQ's code list. Items were added later: 1.04 Mine Safety, and 1.05 Material Cybersecurity Incidents, effective 18 December 2023 (smaller reporting companies 15 June 2024).
  - **Crosswalk.** Map (title, effective date range) to (regime, number) without forcing pre-2004 items onto current numbers. Pre-2004 "Other events" is not one-to-one with 8.01.
  - **Item 8.01 as a catch-all.** Item choice moves with SEC guidance. Erik Gerding's 21 May 2024 statement as Director of the Division of Corporation Finance says the Division "encourages the company to disclose that cybersecurity incident under a different item of Form 8-K (for example, Item 8.01)." Follow-on work to He & Plumlee (2020) treats 8-Ks with items 2.02, 7.01 or 8.01 as voluntary. Event consumers therefore need the 8.01 text layer (model scope), not just header items.
- **Expected value:** medium-low.
- **Sources:** SEC, Form 8-K, https://www.sec.gov/files/form8-k.pdf; Gerding (2024), SEC statement, https://www.sec.gov/news/statement/gerding-cybersecurity-incidents-05212024; He & Plumlee (2020), doi:10.1007/s11142-020-09551-y; SEC, Webmaster FAQ (above).
- **Status:** first-pass — not yet adjudicated.

### C22. Make the insider-data enrichment the design omits at least possible

- **Component:** P6 assumption 4, P8 step 4.
- **Category:** extend scope.
- **Finding:** Two published conventions are absent:
  - the Cohen, Malloy & Pomorski (2012) routine/opportunistic classification, which needs a per-insider history of same-month trades in prior years;
  - the Rule 10b5-1 checkbox from the SEC's 14 December 2022 Rule 10b5-1 amendments. "Section 16 reporting persons will be required to comply with the amendments to Form 4 and Form 5 for reports filed on or after April 1, 2023" (Morrison & Foerster). EDGAR Release 23.1, deployed 20 March 2023, added the checkbox to the Form 4/5 XML. It is a single checkbox per form, not one per transaction.

  Neither needs text models; both are level-B/D derivations over P6 records for a documented downstream view. Calibrate P6 against the SEC Insider Transactions Data Sets (from 2006), which include `AFF10B5ONE`.\[20\]\[21\]
- **Expected value:** low-medium.
- **Sources:** Cohen, Malloy & Pomorski (2012), doi:10.1111/j.1540-6261.2012.01740.x; SEC, Insider Transactions readme, https://www.sec.gov/files/insider_transactions_readme.pdf; Morrison & Foerster summary of the 2022 Rule 10b5-1 amendments.
- **Status:** first-pass — not yet adjudicated.

### C23. Size the audit sample statistically

- **Component:** P10 open question 1, P2 alias check, m_aud.
- **Category:** adopt a better method.
- **Finding:** With n refreshed submissions and zero detections, the 95% upper bound on the per-submission change rate is about 3/n (rule of three). n = 200 bounds it only at 1.5%, so rare in-place changes go undetected.
  - **Target the audit.** Since PACs alter headers only (C5), audit the submissions whose catalog rows changed in the weekly rebuild, and refetch `.hdr.sgml` rather than full bodies.
  - **Alias check.** It is likely low value: the SEC calls the accession-folder path "an alternative symbolic path," which suggests one stored object (unverified). Keep a small fixed sample.
- **Expected value:** low.
- **Sources:** SEC, "Accessing EDGAR Data" (paths); own reasoning (binomial bounds).
- **Status:** first-pass — not yet adjudicated.

### C24. Use a maintained exchange calendar and map provenance to PROV

- **Component:** P7 (ν_cal), P9.
- **Category:** adopt a better method.
- **Finding:**
  - **Calendar.** Use `exchange_calendars` or `pandas_market_calendars` for XNYS sessions, including 13:00 ET early closes, wrapped as a versioned ν_cal snapshot rather than a hand table.
  - **Provenance.** Express θ, π and evidence spans as PROV-DM entities, activities and agents so downstream tools can consume lineage.
- **Expected value:** low.
- **Sources:** exchange_calendars, https://github.com/gerrymanoim/exchange_calendars; pandas_market_calendars, https://github.com/rsheftel/pandas_market_calendars; W3C PROV-DM (2013), https://www.w3.org/TR/prov-dm/.
- **Status:** first-pass — not yet adjudicated.

### C25. Storage is estimable now, not merely "unbounded and unmeasured"

- **Component:** cross-component assumption 7, P7 assumption 5.
- **Category:** fix an error.
- **Finding:** The SEC's stated average of about 800 KB per submission implies about 240 GB uncompressed per 300,000-submission quarter, and about 11.5 TB for 48 quarters. That is consistent with roughly 100 GB per quarter of compressed Feed volume. Both figures are my extrapolations. State this order of magnitude so storage and compaction choices are bounded.
- **Expected value:** low.
- **Sources:** SEC, PDS spec v2.0 §1 (above); SEC Feed index (above).
- **Status:** first-pass — not yet adjudicated.

### C26. Tombstones can carry an SEC-side time only through PDS; otherwise report the bound

- **Component:** P7 assumption 2, P7 open question 3; catalog constraint (weekly reconciliation).
- **Category:** extend scope.
- **Finding:** PAC deletion files carry a `<TIMESTAMP>` "Edgar Dissemination date-time, used for Post Acceptance Corrections only." It is available only to fee-based PDS subscribers. Publicly, the SEC rebuilds full and quarterly indexes weekly on Saturday mornings, so lag is at most about a week after the next rebuild.\[3\] Store the interval (last catalog generation listing the filing, first one not listing it) rather than a single t^det.
- **Expected value:** low.
- **Sources:** SEC, PDS spec v2.0 §3.3.1 (above); SEC, "Accessing EDGAR Data" (above).
- **Status:** first-pass — not yet adjudicated.

## Part 3 — Direct answers to the open questions

### System-level

1. **Acquisition unit.** Use the daily Feed for backfill and daily runs, and keep per-submission fetch for repairs, gaps and audit. Give the governor a bulk lane with its own byte and time limits and resumable transfers. At about 61–63 files per quarter the request budget stops binding, and bandwidth (about 100 GB per quarter compressed, my estimate) becomes the constraint. Reconcile the serializations by comparing document payload hashes on a sample, not headers. (C1, C2, C9)
2. **Raw authority.** Keep the complete submission file (or its Feed equivalent), not the directory. Requests are the binding cost, and the complete file already contains extension taxonomies and SEC processed-XBRL outputs. The SEC's "symbolic path" wording suggests one object under every filer (unverified), so a small alias sample suffices. (C4, C23)
3. **Acceptance as the public instant.** Close but not exact. Measured PDS-before-website gaps were seconds, with prices moving about 30 s before posting, and an older SEC spec says dissemination usually completes within two minutes. Record τ_x and offer a conservative session variant; the SEC supplies no public per-filing dissemination time outside PDS. (C16)
4. **Facts without taxonomies.** Add standard taxonomy packages now: they are few, versioned and retainable once, and extension taxonomies are already in the submission. Use Arelle, with packages loaded offline, as the reference processor and DQC as the sign and scale detector. (C7)
5. **Cell identity and precedence.** Keep latest-accepted for AsOf_t. It matches vendor point-in-time vintages, because later comparatives embody retrospective adjustments. Add First and a "restatement-flagged" view, and suppress pseudo-revisions with interval consistency. Key typed dimensions by canonicalised typed-member XML, and co-registrants by (identifier, LegalEntityAxis member). (C6, C12)
6. **Entity history.** Use as-filed sources first: `dei:TradingSymbol`/`SecurityExchangeName`, Form 3/4/5 `issuerTradingSymbol`, plus daily snapshots of `submissions.zip`. Use a licensed security master such as CRSP only for pre-2003 or non-filer coverage (my own reasoning). Do not reconcile names across CIKs in the platform; leave that to a downstream identity layer. (C17, C20)
7. **Pre-XML and legacy inputs.** For 13D/G, do a narrow level-B extraction of the templated cover-page rows (aggregate amount, percent of class) with evidence spans, and leave everything else to the model layer. Missing acceptance lines do not arise in the 2015+ range. For an extended range, place such filings at end of filed date with a date-precision flag, assigned to the next session. (C13)
8. **Withdrawal semantics.** Acceptable only if made explicit. Store the detection interval and, separately, platform transaction time. An SEC-side removal time exists only in PDS PAC files. (C10, C26)
9. **Evaluation reference.**
   - **Primary:** per-accession agreement with Arelle or the SEC `_htm.xml` instance on the regression sample.
   - **Secondary:** DERA FSN and the Insider Transactions and 13F data sets.
   - **Tertiary:** companyfacts.

   Gate a ν version on three tests: exact agreement on non-dimensional numeric facts above a set threshold, with every residual explained; zero unexplained sign or scale disagreements; and coverage in both directions. The thresholds are my own reasoning. (C7, C8)
10. **Budget and priority.** Use three levels: catalog daily, then platform daily, then backfill and audit. Expected daily load is about 4,700 submissions per business day (300,000 ÷ 63). That is about 52 minutes at 1.5 req/s, about 10 minutes at 8 req/s, or one request with the Feed. (C1, C2)

### P1

1. **Acquisition unit:** no — use the Feed (system question 1). (C1)
2. **Order:** quarter-major, newest first, so complete quarters accumulate; oldest-first is unnecessary. (C18)
3. **Priority:** yes, add a third level, with platform daily above backfill rather than borrowing the catalog's level. (C2)

### P2

1. **Conditional requests:** use them if the SEC returns validators (unverified); the gain is bytes, not requests. Header-only `.hdr.sgml` refetches are the better audit primitive given C5. (C19, C23)
2. **Raw object:** the complete submission file (system question 2). (C4)
3. **Oversize:** a separate budgeted lane with limits at or above the SEC's stated 400 MB maximum, or the Feed; never permanent exclusion. (C9)

### P3

1. **Agreement across sources:** the archive `.txt` header is authoritative for the stored record. The PDS control block and the API `acceptanceDateTime` are cross-checks; the API is useful for testing the time-zone conversion. API `items` (format unverified) cross-check ν_I. Disagreements are gaps, and PAC-driven changes are revisions. (C5, C17)
2. **Unknown header labels:** retain them, as designed. The SEC adds tags (LEI and address tags in March 2025), and refusing would break on every release. (Part 1b)
3. **Payload delimiter:** probably safe, because EDGAR reassembles documents itself. Still, parse with the PDS DTD, anchor on line-initial `</TEXT>`/`</DOCUMENT>`, and verify on the regression sample; I found no SEC guarantee. (C4)

### P4

1. **Per-CIK submissions API:** no — snapshot the nightly bulk `submissions.zip` (one request per day) for former names, tickers and exchanges.\[4\]\[22\] (C17)
2. **Ticker history source:** as-filed cover-page and Form 3/4/5 symbols first; a licensed vendor only for gaps. (C20)

### P5

1. **Taxonomy semantics:** add them now, from FASB/SEC standard packages retained offline; extensions come from the submission. (C7)
2. **Format outside ℛ:** keep nulling the fact, but make ℛ the complete permitted registry set, so a null means a genuine filer error rather than a coverage gap. (C7)
3. **Companyfacts as reference:** not adequate alone. Use Arelle or `_htm.xml` plus DERA FSN, with companyfacts secondary. (C8)

### P6

1. **Pre-XML 13D/G:** a narrow rule-based level-B extraction of cover rows (amount, percent) with evidence spans; the rest goes to the model layer. (C13)
2. **Form 4 amendment:** a linked second row set with an amendment-scope field; do not assume full replacement. (C15)

### P7

1. **Open table format:** yes. Delegate commit, snapshot and rollback, and keep semantic checks as pre-commit validation. (C11)
2. **Latest-accepted rule:** keep it as the default, and add a restatement-precedence view and interval-based revision detection. (C6)
3. **SEC-side tombstone time:** yes when available. Publicly that means only the detection interval; PDS would give PAC timestamps. (C26)

### P8

1. **Rows per item:** one row per item under a submission parent, as designed. This is the standard long format for 8-K item studies.
2. **Maintaining ν_I:** an effective-dated crosswalk that maps historical titles to their historical regime and number, with an optional crosswalk to current numbers only where semantics match. (C21)
3. **Follow-up candidates:** move them to the semantic layer; they assert no fact and duplicate reconciliation logic. (C21)

### P9

1. **Grade granularity:** keep four levels. Record pattern id and structural anchor as producer attributes, and measure precision per producer rather than adding levels. (C24)
2. **Review sampling policy:** fix a minimum here. Use stratified random review per (producer version, field class), sized to a target error bound, and redo it on every ν change. For example, zero errors in 59 reviews bounds the error rate at 5% with 95% confidence. This is my own reasoning. (C23, C24)

### P10

1. **Audit size:** 200 random samples bound change rates only at about 1.5%. Target the audit at catalog-changed rows and header refetches instead. (C23)
2. **Long-lived vs bursts:** with C1 the backfill is about 3,000 bulk downloads, so a long-lived process holding the bulk lane fits. Without C1, use bursts that yield the lease around the catalog's daily window. (C1)

## Part 4 — Claims that appear factually wrong or stale

1. **DERA sets "with the same provenance limits" as companyfacts.** Wrong: FSN includes dimensions and custom tags, is "as filed," and has been monthly since November 2020 (C8).
2. **"Each carrier is processed alone."** Wrong: inline XBRL attachments form one IXDS (C3; EFM Vol. II §5.2.5).\[10\]
3. **"inline-xbrl if it starts with the XBRL wrapper."** Wrong: `<XBRL>` marks all EX-101.* documents, and SEC processed-XBRL documents, including `_htm.xml`, are concatenated into the file (C4; PDS spec §2.3.5–2.3.7).
4. **"Submissions are immutable after dissemination."** Wrong for headers: PACs change header tags, filing date and form type in place (C5; PDS spec §2).\[5\]\[6\]\[23\]
5. **"13D/G XML since December 18, 2024."** Incomplete: that is the mandatory date only. Voluntary XML began 18 December 2023, under new submission-type names, and the cutoff moved to 10 p.m. (C13; EDGAR Release 23.4).
6. **13F unit change "for reports filed from 2023."** Imprecise: it applies to reports filed on or after 3 January 2023, including amendments for earlier periods (C14; SEC Form 13F FAQ).
7. **"Since 2019, cover pages … carry inline XBRL."** Overstated: cover tagging phased in 2019–2021 by filer status, and 8-Ks filed before the first iXBRL 10-Q are exempt (C20).
8. **1.5 req/s as the SEC constraint.** Stale: the SEC permits 10 req/s per user (C2).\[1\]\[2\]
9. **B_rx = 256 MiB.** Below the SEC's stated maximum of about 400 MB (C9).\[6\]
10. **Daily archives hold "the same submissions."** Needs qualification: later removals are not reflected, and archives can be regenerated (C1).\[3\]
11. **Companyfacts characterisation.** Correct on standard taxonomies, no dimensions and a latest view, but it omits that coverage is limited to 10-Q, 10-K, 8-K, 20-F, 40-F, 6-K and variants (C8).

Readings confirmed correct:
- CIKs are never recycled.
- Header item lines carry titles.
- The 5:30 p.m. next-business-day rule applies to most forms, with 10 p.m. for Forms 3/4/5 and 13D/G.
- The inline numeric value formula (sign × transform × 10^scale).
- The accession-number layout.

## Caveats

- **Own-knowledge claims.** These are labelled in the text and should be verified before adjudication: open-table-format capabilities, the multi-class and co-registrant axis conventions, permitted TRR versions, and vendor cleanse codes.
- **Unverified empirical points about EDGAR:**
  - the rate-limit status code;
  - gzip, ETag and Last-Modified on Archives;
  - the `items` format in the submissions JSON;
  - the exact XML 13D/G submission-type strings;
  - whether the archive `.txt` contains the same processed-XBRL documents as `.dissem` files;
  - whether co-filer paths serve one object.
- **Estimates.** Feed volume and storage figures extrapolate from directory listings and SEC-stated averages; they are not measurements.

## Sources

1. [SEC.gov | Privacy Information](https://sec.gov/privacy.htm)
2. [SEC.gov](https://www.sec.gov/about/developer-resources)
3. [SEC.gov | Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
4. [SEC.gov | EDGAR Application Programming Interfaces (APIs)](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
5. [SEC.gov | Webmaster Frequently Asked Questions](https://www.sec.gov/about/webmaster-frequently-asked-questions)
6. <https://www.sec.gov/files/edgar/pds_dissemination_spec.pdf>
7. [GitHub - Arelle/Arelle: Arelle open source XBRL platform · GitHub](https://github.com/Arelle/Arelle)
8. [Handling Duplicate Facts in XBRL and Inline XBRL 1.0](https://www.xbrl.org/WGN/xbrl-duplicates/WGN-2025-01-14/xbrl-duplicates-2025-01-14.html)
9. [Calculations 1.1](https://www.xbrl.org/Specification/calculation-1.1/REC-2023-02-22/calculation-1.1-REC-2023-02-22.html)
10. [June 2025 5-1 EDGAR Filer Manual (Volume II)](https://www.sec.gov/files/edgar/filermanual/edgarfilermmanual-vol2-c5.pdf)
11. [SEC.gov](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets)
12. <https://sec.gov/Archives/edgar/Feed/index.json>
13. <https://sec.gov/Archives/edgar/Feed/1995/index.json>
14. <https://sec.gov/Archives/edgar/Feed/1995/QTR3/index.json>
15. <https://sec.gov/Archives/edgar/Feed/2025/QTR1/index.json>
16. <https://sec.gov/Archives/edgar/Feed/2024/QTR1/index.json>
17. [SEC.gov](https://www.sec.gov/newsroom/whats-new/osd-announcement-11262018-inline-xbrl-requirements-draft-edgar-filer-manual-volume-ii-edgar-filing)
18. [Financial Statement Data Sets Contents 1](https://www.sec.gov/dera/data/fsds.pdf)
19. [EDGAR Public Dissemination Service Technical ...](https://www.sec.gov/info/edgar/pdsdissemspec910.pdf)
20. [Insider Transactions Data Sets Contents](https://www.sec.gov/files/insider_transactions_readme.pdf)
21. [Form 4 Insider Trading in Python: A Filing-Date Event Study](https://blog.quantinsti.com/sec-form-4-insider-trading-python-event-study/)
22. <https://data.sec.gov/submissions/CIK0000320193.json>
23. [ EDGAR ELECTRONIC DATA GATHERING, ANALYSIS, AND RETRIEVAL EDGAR ](https://www.sec.gov/info/edgar/specifications/pds-dissemination-spec022315.pdf)
