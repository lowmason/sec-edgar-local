# Task 15 renewed native offline acceptance

This is fresh observed evidence for implementation `3ca50c78558bbf072a4eb75412af7d58a9e0f61b` after the reviewed command-admission/runtime fixes. L01-L11/L13 pass their renewed offline cases. **Independent renewal review and controller implementation-review.md remain pending. L12 is `not_run`; no genuine SEC HTTP occurred.** The historical Task 14 935-test result and release 900952 are preserved and not relabeled as proof of this payload.

Full machine-readable [renewal record](offline-renewal-task15.json), SHA256 `5b7c8b0719ae070b6b1fd339883bcb984eddf985f44420b2059c277dff53dfdb`. Evidence root `/private/tmp/sec-local-task15-renewal`. Its `discovery.tests` / `test_results` contain every exact test ID; `matrix` records per-case IDs/statuses; `releases` / `artifact_cache` / `evidence_files` hold complete payload/artifact inventories and hashes. Current index contains 5,494 output files. `.sdd/1-sec-edgar-local-spec/task-15-renewal-report.md` provides compact query pointers and the rerunnable validation command.

## Frozen complete gate

The complete checker ran once as `/bin/sh -x scripts/check-sec-edgar-ingest.sh`: **exit 0, 952 unique tests across 60 modules, 0 failures/errors/skips; unittest 3338.799s, total 3341.057s**. Interval `2026-10-18T21:38:43.206551+00:00` to `2026-10-18T22:34:24.392196+00:00`. Shell tracing preserves actual wheel/sdist, every console/module help/version, compileall and final diff commands. Separate streams:

- `/private/tmp/sec-local-task15-renewal/logs/full-check.stdout` — SHA256 `23ec715cb1a2b234c9a5c1cb24d0d40a70bbe76e6083327f23240f495472b8e8`.
- `/private/tmp/sec-local-task15-renewal/logs/full-check.stderr` — SHA256 `095b496299a94744e2f04e970d265158a75ed684853219ab4685e81b95babe85`.
- `full-check-command.json`, `full-check-result.json`, `environment.json`, `discovery.json`, `frozen-before.json`, `frozen-after.json` retain exact invocation/environment/counts and byte comparisons.

Fresh project environment is `/private/tmp/sec-local-task15-renewal/project-env`; PATH is only `/private/tmp/sec-local-task15-renewal/bin:/usr/bin:/bin`. Explicit `UV_OFFLINE=1`, `UV_PYTHON_DOWNLOADS=never`, absolute verified cache/catalog and all six earlier rich proof hooks plus admission trace are frozen. No Azure/MSAL distribution or az/docker/bicep executable is available. Exact native toolchain: `3.14.0 (main, Oct 14 2025, 21:10:22) [Clang 20.1.4 ]`; `macOS-26.6.2-arm64-arm-64bit-Mach-O`; `uv 0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin)`. Python lookup `/Users/lowell/Projects/sec-edgar-local/.venv/bin/python` was recorded before setup. Backend `uv_build 0.12.24`, SHA256 `7a0f45941530c468e9b354e6f0f8e83668b6960a331bf3c311d7232ac33888ea`; Requests 2.34.2 / PyArrow 25.0.1/build policy and lock remain unchanged. Setup completed offline using existing verified caches, with no dependency upgrade.

Dynamic discovery adds 17 methods and removes 0 versus Task 14. Historical source disposition mappings remain unchanged; `disposition-delta.json` supplies exact current IDs/module hashes and the delta. No inherited 935 count or focused selection replaces this complete gate.

## Clean exact-revision build without altering owner config

The original checkout intentionally retains its untracked `conf/sec-edgar-local.json`; SHA256 `5949b1e717565115ecd47a101c8823d0dd7353e9d2eade79e77f887db0b86573`. It was never hidden, moved, deleted, changed or staged. To meet the unchanged strict clean-build rule, an independent Git clone using pack transport/no hardlinks/shared alternates checked out **exact 3ca50c detached and clean** at `/private/tmp/sec-local-task15-renewal/clean-fork`. Every tracked file equals the destination's tracked bytes. `clean-fork-verification.json` preserves that complete comparison; clone clean status is verified before and after build. The owner config is not in the clone.

The clone's `prepare-native-release.py` built the new accepted production candidate into the prescribed original destination `releases/sha256=<ID>/venv`. Fresh actual independent committed A/B snapshots add only B's committed benign resource; all common package bytes/parser/schema match and locks are equal. Wheel/release IDs differ. No venv move/copy, manifest rewrite or installed file mutation manufactured identity.

| Role | Release ID | Git revision | Wheel SHA256 |
| --- | --- | --- | --- |
| a | `4e31b5cc4148b90bdc6db38192ae17f08c8072244e5fe2965092682b286b0b44` | `7041903a0615899caf91dc5b01f7be0f2e2b47ff` | `6ab438e51085ea35f8d23273a2f879738fd963af9609a1a328faa89b9567fd0f` |
| accepted | `fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec` | `3ca50c78558bbf072a4eb75412af7d58a9e0f61b` | `6ab438e51085ea35f8d23273a2f879738fd963af9609a1a328faa89b9567fd0f` |
| b | `294779091959f2051988b21502c8d371322cbc9b794f9ecc480533474e5c9f75` | `d0da88cc7b61bae1e8f62e2e1ba02859e5125cd8` | `f6fae176b200db42edf789c594c2c3cc54d97d2ca48a2699345f1fc57486e704` |

Exact final locations, interpreter/dependency identities, lock/wheel/payload hashes and build logs are in JSON. Old Task 14 files/runtimes/tmp and old owner config remain historical. The new `candidate-config.json` is only at the new evidence root, with approved absolute roots `/Users/lowell/Projects/sec-edgar-local/data` / `/Users/lowell/Projects/sec-edgar-local/logs`, the new native manifest and every required live default. Input hash `2a940f236b2bf37dc1fb4fbef03d0da3c98f663c311231b225961b0c58c3dbbb`, normalized effective hash `088403cb55f5b6541502cb07678c5757ffdb13b92fac52a52b6aa663177b7d4d`. No command executed this candidate or created its store/network.

## Fresh per-case matrix

Required method groups overlap; they are not summed. JSON names every exact method and observed all-ok result.

| Case | Status | Current observed methods | Evidence |
| --- | --- | --- | --- |
| L01 | pass | 41 | Fresh noneditable wheel and exact pinned runtime graph; no Azure/MSAL distributions or cloud CLI in constrained PATH. |
| L02 | pass | 952 | Complete current dynamic discovery equals executed all-ok IDs; no skips, omissions or broad cloud exclusions. Original retained bytes hash-verified; historical evidence preserved. |
| L03 | pass | 24 | Copied standalone verifier, installed origins/exact help/console/module entries and installed fixture workflow outside both checkouts with no PYTHONPATH. |
| L04 | pass | 76 | Original-parent config roots, original/effective byte hashes, arbitrary cwd and pre-state/network refusal of invalid settings/overrides. |
| L05 | pass | 123 | Bounded actual production transport under test-only selected loopback; early guarded HTTP spawn/unpickle; required fixture pack and live/fixture binding separation. |
| L06 | pass | 95 | Native SQLite/CAS/reopen/contended/crash/lease/fence/pacing/cooldown/drain/recovery; unchanged 3/sec source and installed progress, safe expiry separate. |
| L07 | pass | 94 | Exact durable low-level/composed/catch-up/reconcile/approval/rollback/capture workflows, nonempty validated rows/schema/raw and generation manifests. |
| L08 | pass | 130 | Stable immutable typed command admission before Attempt; actual independent races and post-admission process death; changed identity/context/intent/deadline refusal, exact replay and expired unfinished continuation. |
| L09 | pass | 65 | Actual disposable app/dependency/interpreter/manifest/transitive tamper refusal, offline reconstruction and unchanged historical producer authority. |
| L10 | pass | 101 | Strict local codecs/fields across all 35 inventory families including additive admission; legacy image/binding and malformed typed/context bytes refuse without mutation. |
| L11 | pass | 37 | Installed launcher statuses/stream/log-failure precedence/signals/deadline/positive drain; no ingestion-time dependency setup. |
| L12 | not_run | - | No genuine SEC HTTP. Technical review and separately reviewed bounded source/harness/config/budget/sole-issuer gates remain; retained/loopback is not genuine acquisition. |
| L13 | pass | 29 | Actual fresh committed A/B upgrade uses A for old-origin pending/repair under B parent, B new work/operators, preserved producer and missing/corrupt old-runtime distinctions. |

## Current fixed admission and actual installed proofs

The full default gate contains all new typed admission/legacy-prewrite regressions, independent first-admission races and process death after admission but before Attempt. `10` retained admission proof JSONs preserve actual PIDs, original canonical context/intent/hash, sole Attempt, race outcomes and zero transport authority. Inventory contains 35 local families including `sec-local-attempt-admission-v1`. Changed execution/runtime/config/intent/deadline and numeric boolean/normalized timestamp aliases refuse without authority mutation; valid exact retry/replay and legacy unique evidence remain supported.

Accepted standalone verifier ran outside both original checkouts with copied self-contained support, no PYTHONPATH, and native `-I -B -X pycache_prefix=/dev/null` before first app import. PID `74125`, interpreter `/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/venv/bin/python`, import root `/Users/lowell/Projects/sec-edgar-local/releases/sha256=fc68adef9eb5909e4c97e1fb4cf5bb96915721d5bf4a533bbc782e5cc551f7ec/venv/lib/python3.14/site-packages`. Its exact guard has only the preverified selected release exception, with both original source roots denied before app imports. Policy and early evidence propagate into checked stages and HTTP spawned-main before application-class unpickle; actual module origins are in the selected installed release. Clean setup clone is never an application import path.

Eleven guarded installed command helps and exact console bootstrap bytes pass; separate direct root + 11 console helps and module version pass from unrelated cwd. Actual offline reconstruction and four disposable app/dependency/interpreter/manifest tamper refusals pass, preserving accepted originals. Wrong transitive urllib3 0.0.0 refuses with direct pins intact. Accepted fixture sequence records 4 durable workflow reports, 7 captures, 4 distinct captured generations and 7 captured logical rows including repeated reads. Exact contexts/result/call identities, raw/manifest hashes and validation outputs are retained. All published/observation data are nonempty. 12 Parquet artifacts have observed row/schema/hash records; an empty change stream is separate from nonempty source/publication rows.

Actual renewed A/B upgrade uses installed A for A-origin pending collection and exact repair under installed B parent, then B for new processing/publishing and history/approve/rollback/capture. Pending A exit 3 → B exit 0 captures 1 row; repair A exit 9 → B exit 0 captures 2; B approval 1 row and rollback restores 2. Cached producer bytes remain A, missing A permits history/capture but refuses execution before a new call, and corrupt retained manifest refuses historical read. Full exact process policies/PIDs and source/generation/counts are in `upgrade`/`native_processes` and original evidence reports.

## Unchanged timing and launcher behavior

Both measurements use production 3/sec, unchanged one-third-second start window, no fixture timing override and only exact test-selected loopback origins. Safe expiry has no socket start/request and is never completed acquisition.

| Measurement | Completed acquisition | Safe permit_expired | Dispatch-to-socket starts |
| --- | --- | --- | --- |
| installed-latency.json | 2 | 1 | safe expiry, 0.170425s, 0.166804s |
| latency.json | 3 | 0 | 0.070313s, 0.068256s, 0.069722s |

Accepted installed launcher retained normal 5, stdout/stderr archive failure 9, SIGINT/SIGTERM engine 5 and deadline engine 11, with actual PID/argv/module hash, raw stdout/stderr hashes, durable result and positive child drain. Complete launcher default coverage also passed; no ingestion-time dependency sync/install/download occurred.

## Fixed optional scanner on original retained map

The **current committed helper** ran once on a new copied original 85-entry retained map. No alias additions or source/raw/map/helper edits were needed. All copied files remain byte-identical. It preserves original matrix/inspection ID/URL/hash/length, canonical listing and available-alias equality, row/date/selected-row checks. Ten complete retained receipts contain exactly 51 conflicts across 2010Q1 / 2015Q1 / 2026Q3; expected scanner exit 1 records source-blocked quarantine with no traceback. These are retained offline parses, not genuine acquisition or publication/coverage claims.

| Receipt | Period | Parsed rows | Conflicts | Parse status | Raw SHA256 |
| --- | --- | --- | --- | --- | --- |
| SEC-0141 | 2010Q1 | 300561 | 21 | blocked | `aca38d21ee64795f6095c86c0424f94e16a322a4ec0eb6fd38d2e5d6f86822de` |
| SEC-0142 | 2015Q1 | 318647 | 24 | blocked | `984c3130c617c11d085a4deff77a01c21b1113d5bb4c8b2173f5f87eb9f2a728` |
| SEC-0143 | 2026Q3 | 302315 | 6 | blocked | `393a535f84b71ed34845f67aa5e5275ecc86afeb1a6558ad5623b0d7d0babe71` |
| SEC-0144 | 2026Q4 | 12479 | 0 | accepted | `ca5f8a7b9ed1689a334f204456a7ecc70a63176506e9d20f9d149cd11d1201b8` |
| SEC-0145 | 2026Q4 | 12479 | 0 | accepted | `ca5f8a7b9ed1689a334f204456a7ecc70a63176506e9d20f9d149cd11d1201b8` |
| SEC-0146 | 2026-09-30 | 3594 | 0 | accepted | `8ec83de06534af79673887618c0125184a76e9a3db79843c95d3558561ddd018` |
| SEC-0147 | 2026-10-01 | 5527 | 0 | accepted | `529aabd8111461c373b409da01e106a75662af200ac75f9545106a55b4d8ba17` |
| SEC-0148 | 2026-10-02 | 7159 | 0 | accepted | `17f223abb09fc7488947f0ca9e4686167927a09a2f342d8bcefd0d445fdbc3eb` |
| SEC-0149 | 2025-12-31 | 3084 | 0 | accepted | `a5f5bd3f0ea83804b13b3a89f57273ddff78c0eefd0cbc302ecc81400408029b` |
| SEC-0150 | 2026-01-02 | 4777 | 0 | accepted | `caaf4ed84be07de97f100a3e04afbb03f4c28d080faf892b35a20e2e96125ba7` |

## Cache accounting and preservation

Accepted production and B full byte inventories are identical before/after. Proof A has 6 added ordinary cache files from deliberate cache-enabled and optimization-cache negative controls; no preexisting byte/payload/identity changed. Exact paths/hashes/producing test references and actual before/after/delta are retained. No cache is deleted, ignored in the evidence inventory or treated as application authority. Three fresh guard-first native preflights pass using mandatory source-only argv; native lookup bypasses these ordinary caches. This is expected test instrumentation, not an implementation fix or full-tree-A equality claim.

Original config and all three Task14 evidence hashes match their before records. Original source repository remains read-only/clean at `5e8b61cceea7e18c7bc429b80c23a5d95c334c82`; pinned 0e7701a remains extraction authority. Frozen tracked/support/catalog/environment/config bytes compare unchanged. No production/test/dependency/parser/pacing/drain/deadline change was made during renewal. No full repeat occurred. Technical release selection remains the controller's review outcome.

## Supplement commands and review boundary

| Command | Exit | Seconds | Separate output streams |
| --- | --- | --- | --- |
| accepted-standalone-verifier | 0 | 70.361 | `/private/tmp/sec-local-task15-renewal/logs/accepted-standalone-verifier.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-standalone-verifier.stderr` |
| installed-production-latency | 0 | 1.393 | `/private/tmp/sec-local-task15-renewal/logs/installed-production-latency.stdout` / `/private/tmp/sec-local-task15-renewal/logs/installed-production-latency.stderr` |
| disposable-negative-preflights | 0 | 5.120 | `/private/tmp/sec-local-task15-renewal/logs/disposable-negative-preflights.stdout` / `/private/tmp/sec-local-task15-renewal/logs/disposable-negative-preflights.stderr` |
| installed-launcher-faults-signals | 0 | 4.147 | `/private/tmp/sec-local-task15-renewal/logs/installed-launcher-faults-signals.stdout` / `/private/tmp/sec-local-task15-renewal/logs/installed-launcher-faults-signals.stderr` |
| accepted-console-root | 0 | 0.507 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-root.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-root.stderr` |
| accepted-console-discover | 0 | 0.362 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-discover.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-discover.stderr` |
| accepted-console-collect | 0 | 0.366 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-collect.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-collect.stderr` |
| accepted-console-transform | 0 | 0.346 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-transform.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-transform.stderr` |
| accepted-console-publish | 0 | 0.347 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-publish.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-publish.stderr` |
| accepted-console-backfill | 0 | 0.336 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-backfill.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-backfill.stderr` |
| accepted-console-daily | 0 | 0.332 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-daily.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-daily.stderr` |
| accepted-console-reconcile | 0 | 0.344 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-reconcile.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-reconcile.stderr` |
| accepted-console-candidates | 0 | 0.341 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-candidates.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-candidates.stderr` |
| accepted-console-approve | 0 | 0.340 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-approve.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-approve.stderr` |
| accepted-console-history | 0 | 0.342 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-history.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-history.stderr` |
| accepted-console-rollback | 0 | 0.343 | `/private/tmp/sec-local-task15-renewal/logs/accepted-console-rollback.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-console-rollback.stderr` |
| accepted-module-version | 0 | 0.337 | `/private/tmp/sec-local-task15-renewal/logs/accepted-module-version.stdout` / `/private/tmp/sec-local-task15-renewal/logs/accepted-module-version.stderr` |
| retained-original-specimens | 1 | 133.834 | `/private/tmp/sec-local-task15-renewal/logs/retained-original-specimens.stdout` / `/private/tmp/sec-local-task15-renewal/logs/retained-original-specimens.stderr` |

Every command has its expected observed outcome; scanner exit 1 is intentional blocked-source evidence. Validation/report/commit receipts and the two evidence documents exclude themselves from their own hash index to avoid cycles. Only these two renewal evidence files are committed. Independent renewed review precedes controller implementation-review.md and any Task 16 bounded genuine SEC gate; L12 remains `not_run`.
