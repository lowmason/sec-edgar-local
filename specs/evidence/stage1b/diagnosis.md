# Engine-gap diagnosis (Stage 1b brainstorming, 2026-10-27)

**Purpose:** explain the D5 "engine gap" (`specs/evidence/d5-release/measurement.md`) before the
Stage 1b design. This record is a diagnosis, not acceptance evidence. The Stage 1b plan measures on
the installed 1b release (stage spec §6).
**Network:** no SEC request was sent. `data/` was not opened. Both runs used copies or new stores
under `fixture-data/` (git-ignored).

## 1. Cost of one full content check

Probe: [`probe-full-check.py`](probe-full-check.py), run on the checkout `.venv` interpreter
(`-I -B`) on a copy of the retained D5 `closed` store
(`fixture-data/s1b-probe-20261027T182936Z/store`, copied from
`fixture-data/d5-measure-full-20261022T200909Z/closed/store`). The quarters have 370,321 rows, 2
files and 1 source each. Machine load was not sampled during the probe. It was 1.6 to 1.7 shortly after.

| Quarter | `read_manifest` | Hash of every file | `validate_files` | `_validate_row_origins` |
|---|---|---|---|---|
| 2021Q1 | 0.006 s | 0.009 s | 49.7 s | 366.0 s |
| 2021Q2 | 0.002 s | 0.010 s | 49.2 s | 361.2 s |

One full check (`validated_manifest` → `validate_candidate` → `validate_candidate_content`) of a
full-size quarter is about 415 s. A check of the manifest and file hashes alone is about 0.01 s.
2021Q3 had no pointer: the D5 run ended in its engine gap.

## 2. Number of full checks for each member

Counter: [`count-full-checks.py`](count-full-checks.py). It wraps `etl.manifest._validate_row_origins`
in the engine process and runs `scripts/measure-d5-drain.py run --scale smoke` on the installed D5
release interpreter (`aa8de1ac…6ab4`, `-I -B -X pycache_prefix=/dev/null`). Work directory:
`fixture-data/s1b-count-smoke-20261027T184538Z`. Every scenario exited 0. Children are native
processes, so their own checks are not counted. Summary: [`full-check-counts.json`](full-check-counts.json).

- 517 full checks in the engine over the smoke run (3 `open`, 7 + 2 `closed`, 4 `finish` members).
- Each member fully checks its own quarter about 12 times: `evaluate_member` (`capture_quarter`,
  `validated_manifest`, `validate_capture`), `validate_member_evidence` in `process_member` and again
  in `WorkflowMembers.record` (each calls `read_child_capture` and `validate_capture`), the dispatcher's
  `_check_exit` → `read_child`, and `_obligations` → `_read_publish_call`.
- `etl.commands._affected_quarters` fully checks **every** published quarter in the store on each
  `evaluate_member` call, to read `manifest.sources` only. In the 7-quarter `closed` backfill the
  count per member rose by one for each quarter published: 13, 14, 15, 16, 17, 18.
- The finish step fully checks result quarters again: `baseline_gaps`, `source_revert_gaps`,
  `_validate_report` in `write_workflow_result` and in `read_workflow_result` (19 to 56 checks per
  smoke invocation).

## 3. Agreement with the D5 record

The `closed` baseline members in `measurement.md` had engine gaps of 7,372.2 s and 8,186.6 s. The
count above gives 13 and 14 full checks for members 1 and 2 of a fresh store. At about 415 s each:

| Member | Checks | × 415 s | × 1.37 | Measured gap |
|---|---|---|---|---|
| 1st | 13 | 5,395 s | 7,391 s | 7,372.2 s |
| 2nd | 14 | 5,810 s | 7,960 s | 8,186.6 s |

The factor 1.37 is fitted, not measured. The D5 record has load 4 to 7 at its start only. One factor
fits both members, and the step between them (814 s measured, about 570 s predicted) has the
expected sign and size. The repeated full check is the dominant engine cost.

## 4. The `publish` child (static reading, not counted)

- `publish_quarter` fully checks the previous generation (`validated_manifest(previous)`), and
  `build_candidate` checks it again (`validate_candidate(active)`).
- `build_candidate` runs `validate_files` and `validate_candidate_content` on the new candidate, and
  `publish_quarter` then runs `validate_candidate` on it again.
- A full rebuild reads every source observation of the quarter. So the publish child grows with the
  sources already in the quarter (18.8 s per source on D5 fixtures).

## 5. Second cost class

`_obligations` → `_publish_calls` scans every `WorkflowChildCall` and `Attempt` row on each
`evaluate_member`. `reuse_exact_binding` re-reads the member inventory. With tiny quarters, D5's
finish-only run showed member wall time rising from 5.4 s to 18.3 s over 48 members. This cost
grows with store history, not with quarter size.

## 6. Limits

- The probe used the checkout `.venv`, whose source equals the D5 package source. The counter used
  the installed D5 release. Neither is an acceptance measurement.
- The machine was shared. Absolute seconds include contention. The counts do not depend on load.
- Child-side checks are read from the code, not counted.
- Estimates in the stage spec (about 365 s to build and about 415 s to check one full-size quarter) are
  derived from these numbers and the D5 publish timings. The plan measures them.
