# SEC filing submissions — Findings

**Status:** Exploration findings, 2026-10-19/20. Nothing here was designed, approved, or implemented.
§4.5 was corrected and §4.6–4.7 were added on 2026-10-20 after a second check of the extracted feed.
**Project:** `/Users/lowell/Projects/sec-edgar-local`.
**Related:** [Filing-index ingestion spec](../sec-filing-index-ingestion-spec.md),
[completed local design](../completed/sec-edgar-local-spec.md) §5.

This document records one session of exploration. The session examined the live local store, checked
whether it holds filing documents, and inspected one SEC daily feed archive by hand. This is input for
any later design of filing-document ingestion. It does not authorize live traffic or change the
current ingestion contract.

## 1. Questions

1. What does the ignored `data/` directory hold?
2. Does the store hold the filing documents, for example
   `edgar/data/2488/0001950047-26-010251.txt` (2026 Q4)?
3. What does the SEC daily feed archive for 2026-10-15 contain, and does it match the daily index
   that the store ingested?

## 2. The `data/` store

`data/` is the default live store (`storage.root = ../data` relative to `conf/sec-edgar-local.json`).
Git ignores it. [Completed local design §5](../completed/sec-edgar-local-spec.md) defines the layout.
At inspection time it held about 12 MB from one bounded acceptance run, `accept-38bf7c024e0fd5ac`
(2026-10-18).

| Path | Contents at inspection |
|---|---|
| `state.sqlite3` (+ `-wal`, `-shm`) | `records` table: `SourceState` 140, `Attempts` 24, `ActivePointers` 16. `sentinel_journal`: 1 row. The WAL file was empty. |
| `objects/worksets/` | Discovery listings and receipts; source, snapshot, and transformed worksets. Names are content hashes (`sha256=…`). |
| `objects/staging/` | Downloaded HTTP bodies and receipts for each collect attempt, kept before promotion. |
| `objects/raw/sec/indexes/` | 3 retained SEC files: `kind=quarterly/period=2024Q1/…/master.zip`, `kind=daily/period=2026-10-14/…/master.idx`, `kind=daily/period=2026-10-15/…/master.idx`. |
| `objects/observations/` | Parsed `rows.parquet` + `manifest.json`. The path includes the source, raw hash, parser version, and schema version. |
| `objects/curated/sec/filing_index/` | 21 published generations across 16 filing quarters (2021–2026). Each generation has `part-00000.parquet`, `changes.parquet`, and `manifest.json`. |
| `objects/runs/` | 42 durable child-command records (`command.json`, `admission.json`, `result.json`). |
| `objects/quarantine/` | 1 error. The 2024Q1 quarterly `master.zip` failed transform: `line 88043: conflicting duplicate logical key`, `retryable: false`. |
| `objects/locks/sec-owner-lowell-mason/` | `binding.json` (store binding) and `sentinel.json`. |
| `objects/runtime/native/sha256=…/` | Audit copy of the native release manifest. |

Observations:

- Objects are immutable. Publication creates a new `generation=<hash>/` and moves the quarter's
  `ActivePointers` row conditionally. There are 21 generations but 16 pointers because some quarters
  have earlier, superseded generations.
- The binding records the resolved root. Copying or moving `data/` is unsupported. A backup needs
  writers to be stopped (design §5).

## 3. Filing documents are not in the store

The store holds index entries only. No object path contains `edgar/data/` and no filing `.txt` exists.

The sample accession `0001950047-26-010251` occurs as:

- Two lines in the 2026-10-15 raw `master.idx`: one under CIK 2488 (ADVANCED MICRO DEVICES INC)
  and one under CIK 1622864 (Norrod Forrest Eugene), both form `144`, filed `20261015`.
- Two rows in the current 2026 Q4 curated generation (`generation=ad6652941…`, 6,577 rows). The
  earlier Q4 generation (3,125 rows) does not contain them.

Curated schema: `cik`, `company_name`, `form_type`, `archive_path`, `filing_date`,
`accession_number`, `source_id`, `source_sha256`, `parser_version`, `schema_version`.

Findings:

- `archive_path` gives the filing location on sec.gov. No component fetches it.
- One filing can produce more than one index row (one for each CIK). A join on `accession_number`
  alone counts such filings two times.
- The specs do not explicitly put filing documents in or out of scope. The source code has no
  document-fetch path. The only use of `archive_path` is in
  `packages/sec-edgar-ingest/src/sec_edgar_ingest/etl/parser.py`, where a regex extracts the
  accession from the path. No fetch is visible in the store or the run records.

## 4. SEC daily feed archive, 2026-10-15

### 4.1 Location

The URL `https://www.sec.gov/Archives/edgar/Feed/2026/4/20261015.nc.tar.gz` returned HTTP 403.
EDGAR returns 403 for a path that does not exist. The correct quarter directory is `QTR4`:

```
https://www.sec.gov/Archives/edgar/Feed/2026/QTR4/20261015.nc.tar.gz
```

`Feed/2026/QTR4/index.json` lists one archive for each business day. The listed sizes went from
693,801 KB to 1,603,893 KB for 2026-10-01 through 2026-10-16.

### 4.2 Download

- One GET request, with the configured `sec.user_agent` from `conf/sec-edgar-local.json`.
- HTTP 200, 1,610,242,722 bytes, 251 s. The gzip header gives the original name `20261015.nc.tar`
  and the original size modulo 2^32 as 3,562,448,896.
- Location: `/tmp/sec-filings/20261015.nc.tar.gz`. This was manual and is not part of the store or
  the pipeline.

### 4.3 Archive safety and extraction

- 2,628 entries: 2,627 regular files and the `./` directory. There were no absolute paths, no `..`
  components, and no links.
- Extracted with `--no-same-owner --no-same-permissions` to `/tmp/sec-filings/20261015/`.
  Unpacked size: **20,742,318,080 bytes** (about 20.7 GB, or 19.3 GiB), approximately 13× the
  compressed size. This is the gzip size field plus 4 × 2^32. It agrees with the disk use of the
  extracted tree.

### 4.4 Contents

- There is one file for each submission. The name is `<accession>.nc`, or `<accession>.corrNN` for
  the 101 submissions in §4.6. Each file is SGML: a `<SUBMISSION>`
  header (accession, type, document count, filing date, subject company, filer or reporting owner
  with CIK, SIC, addresses) followed by one or more `<DOCUMENT><TEXT>` blocks.
- Structured forms embed XML. The sample `0001950047-26-010251.nc` (6,530 bytes) is a Form 144. It
  has AMD as subject company (CIK 2488), the reporting owner as CIK 1622864, and one
  `primary_doc.xml` with the `edgarSubmission` Form 144 data (securities to be sold, broker, prior
  3-month sales, plan adoption date).
- There is one feed file for each accession, also when the index has more than one row for it.
- Top form types (from the first `<TYPE>` in the first 300 bytes of each file):

  | Form | Count |
  |---|---|
  | 424B2 | 382 |
  | 4 | 292 |
  | 8-K | 214 |
  | D | 208 |
  | 13F-HR | 197 |
  | D/A | 130 |
  | 144 | 122 |
  | 10-D | 105 |

- File sizes are very uneven. The three largest are 352,590,758, 352,465,075, and 280,005,684 bytes
  (accessions `0001193125-26-422529`, `-422520`, `-422480`).

### 4.5 Reconciliation with the daily index

The distinct accessions from the store's 2026-10-15 `master.idx` were compared with the feed filenames
(without `.nc`):

| Set | Count |
|---|---|
| Index accessions | 2,627 |
| Feed files | 2,627 |
| Exact match | 2,526 |
| Index only | 101 |
| Feed only | 101 |

The 101 differences are a naming difference only. The feed names them `<accession>.corr01`, with
no `.nc` extension (for example `0000000000-23-009731.corr01`). The index has the bare accession.
After the `.corrNN` suffix is removed, the two sets are identical.

The `<ACCESSION-NUMBER>` field in the header of each of the 2,627 files is equal to the accession in
its filename, after the `.nc` or `.corrNN` part is removed.

### 4.6 The `.corr` submissions

All 101 `.corr01` files have a `<PRIVATE-TO-PUBLIC>` tag after `<TIMESTAMP>` in the header. None of
the other 2,526 files has this tag. The tag name and the form types suggest that SEC made these
submissions public on 2026-10-15, after a period when they were not public. SEC documentation was
not checked to confirm this.

Only 22 of the 101 accessions start with `0000000000-`. The others have a filer or filing-agent
prefix (for example `0001193125-`, `0000894189-`, `0001104659-`).

| Accession prefix | Form type (first `<TYPE>`) | Count |
|---|---|---|
| `0000000000-` | UPLOAD | 22 |
| Filer or filing agent | CORRESP | 53 |
| Filer or filing agent | 485APOS | 22 |
| Filer or filing agent | DRS | 2 |
| Filer or filing agent | 486APOS | 1 |
| Filer or filing agent | 485BPOS | 1 |

The accession years are 2021 (32), 2022 (15), 2023 (6), 2024 (2), 2025 (24), and 2026 (22). For
each of the 101, the year of the header `<FILING-DATE>` is equal to the accession year.

The index row has the original filing date, not the publication date. For example,
`0000000000-23-009731` (UPLOAD, VanEck ETF Trust) is in the 2026-10-15 index with filing date
`20230901`. 100 of the 101 have a filing date before 2026-10-01. The exception is the DRS
`0001193125-26-414760`, with filing date `20261006`.

### 4.7 Back-dated rows in the daily index

The 2026-10-15 `master.idx` has 3,652 data rows. Grouped by filing date:

| Filing date | Rows |
|---|---|
| 2026-10-15 | 3,495 |
| 2026-10-01 to 2026-10-14 | 23 |
| Before 2026-10-01 | 134 |

The 134 rows before 2026-10-01 come from 109 accessions. 100 are `.corr` submissions from §4.6.
The other 9 are `.nc` amendments (`TA-1/A`, `MA/A`, `MA-I/A`, `MA-A`) with filing dates from
2026-08-27 to 2026-09-30.

The back-dated rows fall in 14 filing quarters: 2021Q1–Q4, 2022Q1–Q2, 2023Q3, 2024Q4, 2025Q1–Q4,
2026Q1, and 2026Q3. The 2026-10-14 index has rows in 2025Q3, 2025Q4, 2026Q1, 2026Q2, 2026Q3, and
2026Q4. Together, the two daily indexes cover exactly the 16 curated quarters in §2. The quarters
that both indexes cover (2025Q3, 2025Q4, 2026Q1, 2026Q3, 2026Q4) are exactly the 5 quarters with
two generations. This agrees with 21 generations for 16 pointers. Which run published each
generation was not checked in the run records.

## 5. Implications for any filing-document design

These are constraints that were observed. They are not decisions.

1. **Key normalization.** To get the accession from a feed filename, remove the `.nc` extension or
   the `.corrNN` suffix. The two do not occur together. An unnormalized join loses 101 of 2,627
   submissions (3.8%) for 2026-10-15. The header `<ACCESSION-NUMBER>` field gives the accession
   without a filename rule.
2. **Size.** A day is about 0.7–1.6 GB compressed and about 20.7 GB unpacked for 2026-10-15. Single
   files can exceed 350 MB. The current HTTP limits (67,108,864 received bytes, 536,870,912 expanded
   bytes) are for index files. A daily feed archive exceeds the received-byte limit by about 24× and
   the expanded-byte limit by about 39×. Any design must choose new limits explicitly, or select
   documents per filing instead of by day.
3. **Streaming.** Full extraction is wasteful. A reader can stream tar members and filter by form
   type or accession before it writes.
4. **Granularity.** One feed file per accession, but possibly more than one index row per
   accession (one per CIK). One feed file can hold more than one `<DOCUMENT>`. Curated filing-document data needs a clear key and a clear relation to
   the `filing_index` rows.
5. **Untrusted input.** Treat archives as untrusted. Check member paths and types before extraction
   (this session found no problems).
6. **Policy.** Feed downloads use the same SEC User-Agent and rate budget (3 requests/second, one
   active collector) as index collection.
7. **Back-dated rows.** A daily index or feed can contain submissions with filing dates in old
   quarters (§4.7). Data partitioned by filing date gets changes to old partitions from each daily
   run. The publication date (the feed or index day) and the filing date are different values.

## 6. Open questions

- Should the pipeline ingest filing documents? If yes, should it use daily feed archives or fetch
  individual `archive_path` URLs?
- Which form types are in scope?
- Does SEC documentation confirm the meaning of `<PRIVATE-TO-PUBLIC>` and `.corrNN` (§4.6)? Can
  `NN` be greater than `01`?
- How can a user tell back-dated rows (§4.7) from rows filed on the index day? Curated rows carry
  `source_id`, which is a hash (for example `cd8ecb90…` on 2021Q1 rows), not a date. Does the store
  map `source_id` to the index day, or should `filing_index` have a publication-day column?
- Is the feed/index match in §4.5 true on other days? Only 2026-10-15 was checked.
- How should the 2024Q1 quarterly quarantine (`conflicting duplicate logical key`, line 88043) be
  resolved? It is separate from filing documents, but it was observed in the same session.

## 7. Reproduction

```sh
UA="$(python3 -I -c "import json;print(json.load(open('conf/sec-edgar-local.json'))['sec']['user_agent'])")"
mkdir -p /tmp/sec-filings
curl -sS --fail -A "$UA" -o /tmp/sec-filings/20261015.nc.tar.gz \
  https://www.sec.gov/Archives/edgar/Feed/2026/QTR4/20261015.nc.tar.gz
tar -tvzf /tmp/sec-filings/20261015.nc.tar.gz | cut -c1 | sort | uniq -c   # entry types
mkdir -p /tmp/sec-filings/20261015
tar -xzf /tmp/sec-filings/20261015.nc.tar.gz -C /tmp/sec-filings/20261015 \
  --no-same-owner --no-same-permissions
```

The §4.6 checks read the start of each `.corr01` file (run in `/tmp/sec-filings/20261015/`):

```sh
for f in *.corr01; do head -c 300 "$f" | grep -c PRIVATE-TO-PUBLIC; done | sort | uniq -c
for f in *.corr01; do head -c 300 "$f" | grep -m1 -o '<TYPE>[^<]*'; done | sort | uniq -c
ls *.corr01 | cut -c1-11 | sort | uniq -c   # accession prefixes
```

The extracted tree in `/tmp/sec-filings/` is temporary. Delete it when inspection is done.
