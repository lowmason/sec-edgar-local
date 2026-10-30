# Stage 2 pre-campaign integrity record

**Date:** 2026-10-21 (UTC). **Plan:** [plan 2](../../plans/2-sec-filing-index-ingestion-spec.md), Task 2.
No SEC request was sent. No writer ran during this task.

## Integrity findings (before any change)

- The live root held 160 files against the 155 in the L12 inventory
  ([files-before.json](pre-campaign/files-before.json)).
- One immutable object differed from L12: the 2021Q1 generation `887cfe89…` manifest. It had mtime
  2026-10-19 08:57 local, 5,655 bytes, SHA-256 `16529f52…`. L12 recorded 5,100 bytes, `a445d0a8…`.
  The difference is whitespace only. The cause is not established.
- Five `.DS_Store` files were present. Their hashes are in files-before.json.
- The L12 external evidence directory `/private/tmp/sec-local-task16-acceptance-20261018` was absent. A
  disk-wide search on 2026-10-21 found no copy. The committed
  [machine evidence](../local-port/sec-acceptance.json) keeps its recorded hashes and inventory.
- Note on the writer check (Step 1). The check `pgrep -fl 'sec_edgar_ingest|sec-edgar-local|local-bootstrap'`
  did not print `no writer`. It printed four processes, because the pattern `sec-edgar-local` also matches the
  project path in a command line. None of the four is a store writer:
  - PIDs 59845, 60048 and 60052: the VS Code Python formatter servers (autopep8, black, isort). They run on
    the project's `.venv` Python.
  - PID 60366: the Antigravity hub (`agy --hub … --add-dir=/Users/lowell/Projects/sec-edgar-local`).

  `lsof +D data` listed no open file under `data/`. The planning session for plan 2 confirmed this reading and told the executing session to continue. A narrower check,
  `pgrep -fl -- '-m sec_edgar_ingest|scripts/sec-edgar-local|local-bootstrap|local_bootstrap'`, printed nothing
  immediately before the backup copy and again immediately before the manifest write.

## Backup

- Path: `/Users/lowell/Projects/sec-edgar-local/backups/stage2-pre-campaign-20261021T180646Z`. Raw
  stopped-writer copy `data-raw/` and SQLite backup-API copy `state.sqlite3` (SHA-256
  `9512176e279a320440b88f25519b9da4dfb73883816d4f52827b3da26bddc79f`).
- The raw copy matches the live root byte for byte ([backup-files.json](pre-campaign/backup-files.json)).

## Restoration (owner decisions O2 and O3)

- The manifest was rewritten with its canonical bytes after hash checks of both the drifted and
  the canonical bytes. The drifted copy remains in the backup.
- The five `.DS_Store` files were removed.

## Verification

- All 155 L12-inventoried files match again, and no other file exists
  ([files-after.json](pre-campaign/files-after.json)).
- The 2021Q1 pointer binds `a445d0a8…`, 5,100 bytes. The validated read returns 4 rows.

## Known-answer checks

- Offline preflight: effective config `088403cb…`, release `fc68adef…`, range 2015Q1–open.
  Config file bytes `cad77e29d681e47a6cfb5658b7ddd13c50b6d55f17e0e315f30c2878cf8da0c4`.
- [audit.json](pre-campaign/audit.json): 10 transport attempts, 10 URLs, 4,946,565 received bytes,
  ordinal 1 only. This equals L12.
- [coverage.json](pre-campaign/coverage.json): 48 requested units without a campaign result. 16 published
  quarters, all daily-only, total 6,744 validated rows. This equals the L12 latest-capture total.

## Known-answer checks on release 9fa189a0… (plan 2 Revision 1)

- [1b/preflight.json](pre-campaign/1b/preflight.json): effective config `db62e7fb…`, release `9fa189a0…`,
  range 2015Q1–open, reserve 1800. Config file bytes `de6c0dd9…`.
- Slice generator: `2015Q1`–`open` reproduces `db62e7fb…`. The 13 configs in `conf/stage2/1b/` match
  plan 2, F13.
- [1b/audit.json](pre-campaign/1b/audit.json): 10 transport attempts, 10 URLs, 4,946,565 received bytes,
  ordinal 1 only. This equals L12.
- [1b/coverage-integrity.json](pre-campaign/1b/coverage-integrity.json) and
  [1b/coverage-full.json](pre-campaign/1b/coverage-full.json): 48 requested units without a campaign
  result; 16 published quarters, all daily-only. The full check reads 6,744 rows, the L12 latest-capture
  total. The integrity check reads no row.
- [1b/timing.json](pre-campaign/1b/timing.json): no workflow result yet, 0 `WorkflowChildCall` rows.
- [1b/files.json](pre-campaign/1b/files.json): 153 files. Against L12, only SQLite journal state changed.

## Known-answer checks after the 2020Q1 range change (plan 2 Revision 2)

- The live config now starts at `2020Q1` (plan 2, D10). File bytes `bfdf2985…`, effective config `2512fdcb…`.
- [rev2/preflight.json](pre-campaign/rev2/preflight.json): effective config `2512fdcb…`, release `9fa189a0…`,
  range 2020Q1–open, reserve 1800.
- Slice generator: `2020Q1`–`open` reproduces `2512fdcb…`. The 8 configs left in `conf/stage2/1b/` keep
  their plan 2 F13 hashes and equal the live config except for the range. The five 2015–2019 configs were
  removed (plan 2, O18).
- [rev2/audit.json](pre-campaign/rev2/audit.json): 10 transport attempts, 10 URLs, 4,946,565 received bytes,
  ordinal 1 only. This equals L12.
- [rev2/coverage-integrity.json](pre-campaign/rev2/coverage-integrity.json) and
  [rev2/coverage-full.json](pre-campaign/rev2/coverage-full.json): 28 requested units without a campaign
  result; 16 published quarters, all daily-only and all inside the range. The full check reads 6,744 rows.
  The integrity check reads no row.
- [rev2/timing.json](pre-campaign/rev2/timing.json): no workflow result yet, 0 `WorkflowChildCall` rows.
- [rev2/files.json](pre-campaign/rev2/files.json): 153 files. Against L12, only SQLite journal state changed.
