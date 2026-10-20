# SEC filing submissions — Findings

**Status:** Exploration findings, 2026-10-19/20. Nothing here was designed, approved, or implemented.
**Project:** `/Users/lowell/Projects/sec-edgar-local`.
**Related:** [Filing-index ingestion spec](sec-filing-index-ingestion-spec.md),
[completed local design](completed/sec-edgar-local-spec.md) §5.

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
Git ignores it. [Completed local design §5](completed/sec-edgar-local-spec.md) defines the layout.
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
- The specs do not explicitly put filing documents in or out of scope. The source code was not
  checked for a document-fetch path. No such fetch is visible in the store or the run records.

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
  Unpacked size: **about 19 GB**, approximately 12× the compressed size.

### 4.4 Contents

- There is one file, `<accession>.nc`, for each submission. Each file is SGML: a `<SUBMISSION>`
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

The 101 differences are a naming difference only. The feed names them `<accession>.corr01.nc`
(for example `0000000000-23-009731.corr01.nc`); the index has the bare accession. All 101 have the
`0000000000-` prefix and accession years 2023–2025. After the `.corrNN` suffix is removed, the two
sets are identical. The document type of these 101 files was not checked.

## 5. Implications for any filing-document design

These are constraints that were observed. They are not decisions.

1. **Key normalization.** To get the accession from a feed filename, remove `.nc` and any `.corrNN`
   suffix. An unnormalized join loses about 4% of a day's submissions.
2. **Size.** A day is about 0.7–1.6 GB compressed and about 19 GB unpacked for 2026-10-15. Single
   files can exceed 350 MB. The current HTTP limits (67,108,864 received bytes, 536,870,912 expanded
   bytes) are for index files. A daily feed archive exceeds the received-byte limit by about 24×.
   Any design must choose new limits explicitly, or select documents per filing instead of by day.
3. **Streaming.** Full extraction is wasteful. A reader can stream tar members and filter by form
   type or accession before it writes.
4. **Granularity.** One document per accession, but possibly more than one index row per
   accession (one per CIK). Curated filing-document data needs a clear key and a clear relation to
   the `filing_index` rows.
5. **Untrusted input.** Treat archives as untrusted. Check member paths and types before extraction
   (this session found no problems).
6. **Policy.** Feed downloads use the same SEC User-Agent and rate budget (3 requests/second, one
   active collector) as index collection.

## 6. Open questions

- Should the pipeline ingest filing documents? If yes, should it use daily feed archives or fetch
  individual `archive_path` URLs?
- Which form types are in scope?
- What are the document types and semantics of the `0000000000-…​.corrNN` submissions?
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

The extracted tree in `/tmp/sec-filings/` is temporary. Delete it when inspection is done.
