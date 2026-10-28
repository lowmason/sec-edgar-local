# 1b member-cost measurement (Stage 1b, plan 5 Task 12)

**Date:** 2026-10-28, 11:09:45 UTC to 15:44:54 UTC (4 h 35 min for the four scenarios).
**Release:** `9fa189a0bea3c6545e7bce5b82d266d601abe2c3a35a66a58a8b8378d2bc283b` (the 1b release, from Task 11). The installed interpreter ran with `-I -B -X pycache_prefix=/dev/null`.
**Work directory:** `fixture-data/s1b-measure-20261028T110945Z` (git-ignored, under the project). The pointer file is `fixture-data/s1b-measure-latest.txt`.
**Network:** No SEC request was sent. All scenarios used fixture acquisition and fresh stores. `data/` was not touched.
**Result:** All four scenarios ended `complete` with the expected exits. `summarize` reported no incomplete scenario, so the proposal is not null.

## Inputs
- Command: `scripts/measure-d5-drain.py scenario --name <name> --scale full`, run for `open`, `closed`, `authority` and `finish` in this order, one at a time. The driver was `fixture-data/run-s1b-measure.sh` under `caffeinate -i`.
- Bodies (synthetic, from `specs/evidence/d5-release/counts.json`): a quarterly body of 370,321 rows and a daily body of 3,652 rows. Parser `sec-index-parser-v1`.
- `open`: 81 daily sources in one open quarter, one `daily` run.
- `closed`: a `backfill` of 23 quarters, 2021Q1 to 2026Q3. 14 quarters carry a full-size body: 2021Q1, 2021Q2, 2021Q3, 2021Q4, 2022Q1, 2022Q2, 2023Q3, 2024Q4, 2025Q1, 2025Q2, 2025Q3, 2025Q4, 2026Q1 and 2026Q3. The other 9 quarters are not in the `closed_quarters` input. Then a `daily` run with 2 members: measure 1 back-dates one row into one closed quarter, and the fan-out back-dates one row into each of the 14 quarters.
- `authority`: 10 full-size daily files for 2026Q3, then one quarterly file. It lists 90% of the daily keys and adds its own rows up to the full size. The full rebuild stops at the withdrawal gate. The exit is 10 (`awaiting_approval`) by design.
- `finish`: 48 quarters from 2015Q1 with 50 rows each.
- Flags in every report: `isolated` 1, `dont_write_bytecode` true, `pycache_prefix` `/dev/null`. Every report has `scale` `full` and the 1b release ID.
- Machine: 14 cores, AC power. Hash of each file:

| File | SHA-256 |
|---|---|
| `open-report.json` | `302411d474be4097d50573ffdb3223c3d45d3338729313a406225eed74c3e7f8` |
| `closed-report.json` | `fe17bc9b8cc6bf4ea83bcb91676e579925fca64f84f1439a1d14bbaf8168e7f5` |
| `authority-report.json` | `0a0aaad32b23ebfad152cd1bedf4021b9fca1b4bf4d7be173768026657f80e71` |
| `finish-report.json` | `b3b8e8535ca294bdb7707d185f1b36950b23ee0cf3348462498aaf02f5e21808` |
| `measurement.json` (the `summarize` output, copied here) | `f561da783fdfa84df77ffeb47ba59fc15fc1fae2822162587d1dd0b5e34d88a0` |
| `driver.log` | `a570ed25d75a1926f79210e8301300f8d6b2a9e4bd96c50df3787dadc5b5753b` |

## Results
Seconds. "Member wall" runs from the member's `sibling_completion` call to the return of its durable receipt (spec §6). A "child" is a native `collect`, `transform` or `publish` process. The load figures are the 1-minute load average, sampled at each member boundary.

### Scenario status and load
| Scenario | Start (UTC) | End (UTC) | Engine calls (exit) | Members | Load range (1 min) |
|---|---|---|---|---|---|
| `open` | 11:09:45 | 11:29:12 | `daily` (0) | 81 | 2.67 to 18.66 |
| `closed` | 11:29:12 | 15:17:42 | `backfill` (0), `daily` (0) | 23 and 2 | 1.68 to 11.09 |
| `authority` | 15:17:42 | 15:36:11 | `daily` (0), `backfill` (10, by design) | 10 and 1 | 6.25 to 9.62 |
| `finish` | 15:36:11 | 15:44:54 | `backfill` (0) | 48 | 1.90 to 2.86 |

### Open quarter, daily members (`open`)
n is the number of sources already in the quarter.

| n | Member wall |
|---|---|
| 1 | 8.8 |
| 10 | 9.7 |
| 40 | 12.8 |
| 80 | 16.2 |

The whole `open` call took 1,165.9 s for 81 members.

### Closed quarters, first publications (`closed` baseline)
Fourteen quarters with a full-size body, in run order:

| Quarter | Member wall | | Quarter | Member wall |
|---|---|---|---|---|
| 2021Q1 | 960.1 | | 2025Q1 | 918.6 |
| 2021Q2 | 965.3 | | 2025Q2 | 978.5 |
| 2021Q3 | **1,010.9** (slowest) | | 2025Q3 | 1,009.2 |
| 2021Q4 | 962.1 | | 2025Q4 | 992.8 |
| 2022Q1 | 935.8 | | 2026Q1 | 990.8 |
| 2022Q2 | 917.8 | | 2026Q3 | 990.8 |
| 2023Q3 | 911.9 | | | |
| 2024Q4 | 932.3 | | | |

The 14 members range from 911.9 s to 1,010.9 s. The other 9 quarters each took 5.1 s to 7.4 s: 2022Q3 5.1, 2022Q4 5.2, 2023Q1 5.3, 2023Q2 5.3, 2023Q4 5.5, 2024Q1 5.6, 2024Q2 5.6, 2024Q3 5.7 and 2026Q2 7.4. The whole `backfill` call took 13,602.6 s (3 h 47 min).

### Closed quarters, back-dated rows (`closed` daily run)
| Measure | Member wall |
|---|---|
| Measure 1: one row back-dated into one closed quarter | 16.7 |
| Fan-out: one row back-dated into each of the 14 closed quarters | 21.0 |

The whole `daily` call took 101.1 s for 2 members.

### Authority member (`authority`)
| Member | Member wall |
|---|---|
| 2026Q3 quarterly, full rebuild that gains the quarterly authority and stops at the gate | 985.4 |

The 10 daily members before it took 8.8 s to 12.9 s each. The `backfill` call took 998.1 s.

### Finish step
The finish step is the sum of the labelled timings `baseline_gaps`, `source_revert_gaps`, `summarize`, `write_workflow_result` and `emit_summary`.

| Call | Finish step |
|---|---|
| `closed` baseline (`closed-0`) | 37.0 |
| `closed` daily run (`closed-1`) | 2.9 |
| `finish` scenario, 48 quarters (`finish-0`) | **97.8** (largest) |

### Slowest member
`2021Q3`, quarterly, first publication in the `closed` baseline, outcome `success`. Member wall 1,010.9 s. Its children: `collect` 2.0 s, `transform` 287.5 s and `publish` 719.5 s. The 1-minute load was 5.04 at its start and 5.33 at its end.

### History scan (S4)
The fit uses per-member engine seconds (member wall minus the children) against the `WorkflowChildCall` rows at the member start. It is a linear fit.

| Scenario | Points | Slope (s per row) | Intercept (s) | At 400 rows | At 1,200 rows |
|---|---|---|---|---|---|
| `open` | 81 | 0.0253 | 0.65 | 10.8 | 31.0 |
| `closed` | 25 | 0.0290 | 1.38 | 13.0 | 36.2 |
| `authority` | 11 | 0.0236 | 0.56 | 10.0 | 28.9 |
| `finish` | 48 | 0.0218 | 2.07 | 10.8 | 28.3 |

The largest value is 36.2 s per member at 1,200 rows (the `closed` fit). The 400 and 1,200 values are projections. The most `WorkflowChildCall` rows that a member saw at its start were 241 (`open`), 142 (`finish`), 74 (`closed`) and 32 (`authority`).

### Against the D5 measurement (context only)
The two records do not use the same timer. D5 measured from one member's `collect` start to the next member's `collect` start (`specs/evidence/d5-release/measurement.md`). This record measures from the `sibling_completion` call to the receipt. So the figures below show the scale of the change, not an exact ratio.

| Measure | D5 (`fc68adef…` run) | 1b |
|---|---|---|
| Slowest member | 10,657.5 s | 1,010.9 s |
| Open-quarter member, last measured | 1,590.1 s at n = 23 | 16.2 s at n = 80 |
| Open-quarter member at n = 80 | about 5,170 s (extrapolated) | 16.2 s (measured) |
| Finish step | 152.2 s | 97.8 s |
| Measure 1 and fan-out | not reached | 16.7 s and 21.0 s |

## Proposal
Computed by `summarize` (`cost_proposal`). Nothing here is the owner's decision yet.

| Item | Value |
|---|---|
| Largest finish step | 97.8 s |
| P4 floor rule: max(60, 3 × 97.8 s, rounded up to 30) | 300 s |
| C8 floor: max(480, 300) | **480 s** (unchanged) |
| Slowest member wall | 1,010.9 s |
| Reserve: 1.25 × 1,010.9 s + 480 s = 1,743.6 s, rounded up to 60 | **1,800 s** |
| Fit gate: slowest ≤ 3,300 − 1,800 = 1,500 s | **passes** (1,010.9 s ≤ 1,500 s) |

- The floor does not change. So `config.py` stays as it is, and no gate re-run or release rebuild is needed (Task 12 Step 5 does not apply unless the owner approves a floor above 480).
- The reserve of 1,800 s equals the provisional live value that the owner approved for D5 (`execution.dispatch_reserve_seconds` = 1800, plan 4 D4).
- Room under the fit gate: 489 s at a fixed reserve of 1,800 s. The slowest member could be 48% longer. If the reserve is derived again from a slower member, the gate holds up to a slowest wall of about 1,248 s. That is 23% above the measured value.

## Limits
- Fixture timings can only underestimate native cost (plan 2 F11). The fixture `collect` child took 2.0 s. A native `collect` that reads the SEC index files can take longer. This record does not measure that.
- Machine load. The 1-minute load was 1.68 to 18.66 at member boundaries, across the four scenarios. The slowest member ran at 5.04 to 5.33. The 14 full-size quarters ran from 911.9 s to 1,010.9 s. Five members began and ended at a load below 3 (2022Q1, 2022Q2, 2023Q3, 2024Q4 and 2025Q1). They took 911.9 s to 935.8 s. Three members began at a load of 9 or more (2025Q3, 2025Q4 and 2026Q1). They took 990.8 s to 1,009.2 s. 2025Q2 began at a load of 1.95, the load rose to 9.37 during it, and it took 978.5 s. The quarters differ in history size too, so this is an observation, not a measured load effect.
- Other work on the machine. At Step 0 (11:08 to 11:09 UTC) the 1-minute load was 1.81 to 1.94. About one core of it came from another project's Python job (PID 71263, in `~/.codex/worktrees/acs-targets-design/embedding-data`, 99% CPU). It was not stopped. A check at about 15:45 UTC, when the last scenario ended, found no such process. This record does not show when it stopped. The cause of the higher load later in the run is not identified. The measurement itself starts native children, so it adds load of its own.
- The controller session ran no gate, Codex review, release build or edit of `scripts/measure-d5-drain.py` during the measurement. This record does not exclude other work on the machine, such as other sessions or applications.
- The history-scan cost is measured, not fixed (S4). The projections at 400 and 1,200 rows extend each fit past the 241 rows that the largest run (`open`) reached.
- The full rebuild of a closed quarter stays at about 16 minutes (spec §2: no columnar full-rebuild path in this stage). The authority member and every closed first publication use it.
