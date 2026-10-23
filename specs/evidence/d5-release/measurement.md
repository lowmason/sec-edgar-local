# D5 drain measurement (Stage 1a, plan 4 Task 2)

**Date:** 2026-10-22 20:09 UTC to 2026-10-23 07:49 UTC (the full run). **Release:** `fc68adef…` installed interpreter, `-I -B -X pycache_prefix=/dev/null`.
**Work directory:** `fixture-data/d5-measure-full-20261022T200909Z` (git-ignored, under the project). No SEC request was sent. `data/` was opened only by `count`. Its only change is the mtime of the `data/` directory itself. `state.sqlite3` has an identical SHA-256 before and after.

## Run status: the full run did not finish

The full run failed. It wrote no report. The timings below come from the durable `Attempts` records in the scenario stores (`scripts/measure-d5-drain.py rebuild`, stdlib only, read-only). The in-process timers were lost with the process.

| Scenario | What happened |
|---|---|
| `open` (81 daily sources, one `daily` run) | 24 members completed. Member 25 was in its `publish` child when the run reached its hard deadline (2026-10-23 01:59:10 UTC). The run ended `state_conflict`, "child shutdown/drain was not confirmed", with no workflow result. This is the F8 and F11 failure that this stage must fix. |
| `closed` baseline (23 quarters, 2021Q1–2026Q3, one `backfill` run) | 2 members completed. The third member's `transform` child had finished (about 07:39 UTC) and no `publish` attempt was recorded. So that member was in the engine gap at the hard deadline (2026-10-23 07:49:15 UTC). The run ended `state_conflict` with the same message. |
| `closed` daily steps (measure 1 and the 14-quarter fan-out) | Not run. The second `closed` config was written at about 07:51 UTC, but no stderr log or report exists for that invocation, so the process ended during or just after the baseline's failure. I have no traceback, because the output was in the owner's terminal. |
| `finish` (48 quarters) | Not run. |

So measure 1 (back-dated rebuild) and the fan-out have no value. Measure 2 has the 1 and 10 marks only. Measure 3 (the finish step) was measured in a separate run, below.

No sleep or wake event occurred in the run window (`pmset -g log`). Machine load was about 4 to 7 at the start, from other sessions. I have no load record for the later hours.

## Inputs
Counted bodies (counts.json): 2024Q1 quarterly, 370,321 rows, 4,262,821 bytes. Daily 2026-10-14 has 3,220 rows and 2026-10-15 has 3,652 rows.
Synthetic bodies: quarterly 370,321 rows, daily 3,652 rows. Fixture acquisition, parser `sec-index-parser-v1`.

## Results (rebuilt from the stores)

Seconds. A "child" is a native `collect`, `transform` or `publish` process. "Member wall" runs from a member's `collect` start to the next member's `collect` start. "Engine gap" is the part of that wall time after the member's last child ended, before the next `collect` started. No child runs in it.

### Open quarter, daily members (`open`)

| Sources already in the quarter | Publish child | Member wall | Engine gap |
|---|---|---|---|
| 0 | 11.6 | 107.8 | 84.4 |
| 1 | 33.0 | 172.4 | 127.1 |
| 10 | 226.3 | 816.4 | 577.6 |
| 23 (last completed) | 457.9 | 1,590.1 | 1,121.0 |
| 40 and 80 | not reached | not reached | not reached |

Linear fit over the 24 completed members: publish = 24.0 + 18.8 × n seconds, and member wall = 143.4 + 62.8 × n seconds, where n is the number of sources already in the quarter. Transform stayed at 2.5 to 2.8 s and collect below 0.1 s.
Extrapolated, not measured: n = 40 gives a publish child of about 777 s and a member wall of about 2,655 s. n = 80 gives about 1,530 s and about 5,170 s.
At n = 23, the three children are 29% of the member wall. The engine gap is the rest. It also grows with n.

### Full-size closed quarters, quarterly members (`closed` baseline)

| Member | Transform | Publish | Member wall | Engine gap |
|---|---|---|---|---|
| 1st of 23 | 250.0 | 1,139.3 | 9,470.5 | 7,372.2 |
| 2nd of 23 | 247.3 | 1,515.8 | 10,657.5 | 8,186.6 |

The 3rd member's `transform` took 247.3 s. No `publish` attempt was recorded for it before the deadline. Discovery took 19.8 s for 23 quarters.

### Slowest member and the finish step

| Measure | Seconds |
|---|---|
| Slowest completed member by wall time (2nd quarterly baseline member). This is collect start to the next collect start, which may differ from P4's `process_member` timer. | 10,657.5 |
| Slowest completed child (publish, same member) | 1,515.8 |
| Finish step, 48 requested quarters (measured separately on 2026-10-23, see below) | 152.2 |
| Closed-quarter rebuild by one back-dated daily row | not measured |
| Fan-out: one daily file back-dating into 14 closed quarters | not measured |

## Proposal (plan 4 default P4)

P4 cannot produce a valid proposal from this record:

- **Floor:** P4 is `max(60, 3 × finish_seconds)`, rounded up to 30 s. The finish step was measured separately (below): 152.2 s, so the floor is **480 s**.
- **Reserve:** P4 sets `2 × slowest member + floor`. With the slowest member at 10,657.5 s, that is at least 21,375 s. The reserve must be below 3,300 s (the launcher default timeout) and below 3,600 s.
- **Fit:** The slowest member does not fit in 3,300 − reserve for any allowed reserve. The open-quarter member with 23 sources (1,590 s) fits only if the reserve is below 1,710 s. The extrapolated 80-source member (about 5,170 s) and both quarterly baseline members (above 9,000 s) exceed the whole 3,300 s timeout.

The spec §6 branch applies: the owner either accepts a limit for Stages 2–3 or adds cheaper publication as a new roadmap stage. The owner also chooses the floor and the reserve, which this record cannot derive.

## Finish step, measured alone (plan 4 Task 2 Step 8b, 2026-10-23)

Run: `scripts/measure-d5-drain.py run --scale full --only finish` on the installed `fc68adef…` interpreter (`-I -B -X pycache_prefix=/dev/null`), launched by the owner. Work directory `fixture-data/d5-measure-finish-20261023T132615Z`. Result file: `finish-measurement.json` (copied from the run). The run took 878 s, exited 0, and completed 48 members (2015Q1 to 2026Q4, 50 rows per quarter, fixture acquisition, no SEC request). Machine load was about 3.5 to 5, and other test runs of this plan shared it.

| Finish step part | Seconds |
|---|---|
| `baseline_gaps` | 28.9 |
| `source_revert_gaps` | 3.1 |
| `summarize` | 0.0 |
| `write_workflow_result` | 120.1 |
| `emit_summary` | 0.0 |
| **Total** | **152.2** |

P4 floor: `max(60, ceil(3 × 152.15 / 30) × 30)` = **480 s**.

Limit: the quarters in this run have 50 rows each. A finish step on a store with full-size quarters can cost more. The member wall time here also grew with the store (5.4 s for the first member, 18.3 s for the 48th), so the in-process engine cost per member rises even with tiny quarters.

## Limits
Fixture timings can only underestimate native cost (plan 2 F11). Synthetic bodies are not SEC bodies, and the L12 publish spread (41.6–187.6 s) is unexplained. The fan-out used the 14 quarters of one retained daily file (findings §4.7). This run did not reach it.
The machine was shared with other sessions, so the absolute seconds include contention. The growth with the number of sources, and the share of engine time outside any child, are the results to rely on.
The cause of the large engine gaps is unknown. They do not come from the child processes. They are time spent in the in-process engine between members, such as member evaluation and receipt work. Stage 1a's cutoff and skip do not change them. This record does not diagnose them.
The extrapolations to 40 and 80 sources assume the linear fit holds. A longer measurement could show otherwise.

## Owner decision
Owner's words (2026-10-23), in order:

1. "D2: the slowest member does not fit, so add cheaper publication as a new roadmap stage. Floor and reserve: <integers, or say to defer them>."
2. After the controller recommended floor 300 s with the reserve deferred to D4: "D2 approved: measure finish only before setting the floor, add a per-member-cost stage before Stage 2 instead of accepting the limit, and continue Stage 1a with a provisional reserve."

Result: the finish step was then measured alone (152.2 s, above). The floor is the P4 rule's value, 480 s, which D1 approved. The reserve is provisional and is set at the Task 10 owner approval (D4). The owner does not accept the limit: a per-member-cost stage goes before Stage 2.
