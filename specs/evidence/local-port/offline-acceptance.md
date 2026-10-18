# Fresh isolated native offline acceptance

Observed offline cases L01-L11/L13 pass for implementation `1a5b103e31aa0fd85c3cf5f0e8d1cd6edd66a3b4`. Independent Task14 review is pending. **L12 is `not_run`**; no genuine SEC HTTP occurred. Task15 technical release review and Task16 bounded live gates remain.

The machine-readable [acceptance record](offline-acceptance.json) contains exact commands, per-method results, complete manifests/payload hashes, dependencies, process identities, captures, schemas and the hashed evidence-file index. Its SHA256 is `f32fdd6cd861cb0daaf71f2f0f870f0755eff7b109a7ed47218b22337e1b8db1`. Evidence root: `/private/tmp/sec-local-task14-acceptance`.

## Frozen check and toolchain

The complete `/bin/sh scripts/check-sec-edgar-ingest.sh` ran once with explicit `environment.json`: a fresh `/private/tmp/sec-local-task14-acceptance/project-env`, constrained PATH `/private/tmp/sec-local-task14-acceptance/bin:/usr/bin:/bin`, `UV_OFFLINE=1`, `UV_PYTHON_DOWNLOADS=never`, absolute proof cache/catalog, and all six native/workflow/upgrade/HTTP/latency retention hooks. No az/docker/bicep executable was on that PATH; neither source-check nor installed graph contains Azure/MSAL.

Fresh discovery and execution match exactly: **935 unique methods in60 modules, 0 failures/errors/skips, OK in3350.561s**. Overall checker exit0 in3352.907s, from `2026-10-18T19:37:37.646247+00:00` to `2026-10-18T20:33:30.522513+00:00`. The sequential checker completed wheel+sdist, console/module helps/version, compileall and final diff check. Exact script hash/order is frozen; stdout and stderr are retained separately:

- `/private/tmp/sec-local-task14-acceptance/logs/full-check.stdout`, SHA256 `23ec715cb1a2b234c9a5c1cb24d0d40a70bbe76e6083327f23240f495472b8e8`.
- `/private/tmp/sec-local-task14-acceptance/logs/full-check.stderr`, SHA256 `385bc452032473059adf478510f73a431291dfd03da13148554b0d2a4d31b83a`.
- `full-check-command.json`, `full-check-result.json`, `frozen-before.json`, `frozen-after.json`, `discovery.json` under the evidence root. Tracked bytes, selected harness/catalog/environment/config hashes compare unchanged.

CPython `3.14.0 (main, Oct 14 2025, 21:10:22) [Clang 20.1.4 ]`; platform `macOS-26.6.2-arm64-arm-64bit-Mach-O`; interpreter identity `{'cache_tag': 'cpython-314', 'implementation': 'cpython', 'platform_tag': 'macosx_26_6_arm64', 'version': '3.14.0'}`. Lookup returned `/Users/lowell/Projects/sec-edgar-local/.venv/bin/python` before setup. `uv 0.13.1 (Homebrew 2026-10-14 aarch64-apple-darwin)`. Build backend `uv_build 0.12.24`, artifact SHA256 `7a0f45941530c468e9b354e6f0f8e83668b6960a331bf3c311d7232ac33888ea`. Requests2.34.2, PyArrow25.0.1 and build policy `uv_build>=0.12.15,<0.13.0` are unchanged. Lock SHA256 `e3d3dac9971ed75bdc5864ebd8c422c2e34bd24236a9a77bbadb6a87cddf1bbb`.

## Actual committed releases

| Role | Release ID | Git revision | Wheel SHA256 |
| --- | --- | --- | --- |
| a | `7c2695c8634c3c0167c1e2a6787ea70e0a22df915ed62924bdacbb1453325569` | `1b4b6a01ca2e01b90f2ee9c202449001175c0536` | `26434e353d20510c552acc86f622b86fd82f3e23d1c4987f3021fd3a46c78af2` |
| accepted | `900952a82380297c3e51677b185b17bb179d2beef61e4b0929007f67a09e97bb` | `1a5b103e31aa0fd85c3cf5f0e8d1cd6edd66a3b4` | `26434e353d20510c552acc86f622b86fd82f3e23d1c4987f3021fd3a46c78af2` |
| b | `e56e55f54c55ab212607e69ec598e5a52e0a69bada9840e5b792e2df163949a0` | `7648d8e9e87ebe373bc44c7c789b1c030a005962` | `c54b09225a0c43f3beedefeb1292360e7ef82bec1a0084f6ca0fa35c1ecded6a` |

Accepted release was built by `scripts/prepare-native-release.py` from clean committed1a5b103. A/B were built from independent committed snapshots at `/private/tmp/sec-local-task14-acceptance/source`, with exactly one committed resource added forB and no common payload changed; wheel and release IDs differ. No venv was copied/moved or manifest/installed file modified to manufacture identity. `toolchain-and-identities.json`, build command/stream files, `a-b-resource-comparison.json`, and all three byte inventories retain the exact final environments/artifacts. Accepted production and proofB compare byte-identical. ProofA adds six deliberate negative-control bytecode caches, with no preexisting byte, payload or identity changed; exact hashes/test references are in proof-a-cache-accounting.json and the original mismatch inventories. Fresh guarded native preflights for all three releases pass with mandatory source-only argv. No cache is deleted or read as application authority.

## Per-case acceptance

The table cites the current exact test-ID lists and observed all-ok status in JSON; row groups overlap and are not summed. Historical disposition remains unchanged. `disposition-delta.json` records58→60 modules,57 added methods,0 removed historical methods, five changed existing module hashes and the two launcher modules. No old count substitutes for fresh discovery.

| Case | Status | Required observed test methods | Evidence |
| --- | --- | --- | --- |
| L01 | pass | 41 | Fresh non-editable accepted wheel/runtime installation; exact locked graph and wheel payload; no Azure/MSAL distributions or cloud CLI on constrained PATH. |
| L02 | pass | 935 | All935 current discovered methods across60 modules passed, no failures/errors/skips; independently copied retained fixtures hash-verified. Historical inventory delta preserved separately. |
| L03 | pass | 24 | Copied standalone verifier outside both checkouts with guard before app import,11 guarded installed command helps, direct12 console help calls/module version and installed fixture workflow without PYTHONPATH. |
| L04 | pass | 75 | Original-parent relative roots and normalized effective/original hashes; arbitrary cwd; strict invalid config/override refusal before stores/network. |
| L05 | pass | 123 | Real bounded production transport under exact test-only loopback selection; native HTTP spawn main guarded before transport unpickle; fixture pack required/no live fallback; mixed binding refused. |
| L06 | pass | 95 | Native SQLite/reopen/contention/CAS/immutable/crash/lease/fencing/pacing/cooldown/drain/recovery and unchanged3/sec timing progress; source and installed measurements distinguish successful exchange from safe expiry. |
| L07 | pass | 94 | Durable fixture low-level and composed workflows, catch-up/reconcile/approval/rollback/captured nonempty reads; source/generation/count/hash and Parquet schema evidence retained. |
| L08 | pass | 118 | Exact retry rejects changed runtime/config/IDs/intent/deadline; completed replay and unfinished-expired continuation retain distinct authority and outcomes. |
| L09 | pass | 65 | Separate reconstructed disposable app/dependency/interpreter/manifest tamper refusals; actual wrong-transitive refusal with direct pins intact; saved producer identity unchanged. |
| L10 | pass | 89 | Strict round-trips/fields across changed local record families; legacy image envelopes/bindings refused without mutation. |
| L11 | pass | 37 | Installed launcher process fault/signal/deadline/status precedence and separate stream archives; no runtime dependency setup; six extra accepted-runtime cases retain actual PID/events/guard/bytes. |
| L12 | not_run | - | Separate genuine SEC smoke remains Task15/16 reviewed-release/harness/selection/config/budget gate; retained and loopback evidence do not satisfy it. No genuine SEC HTTP in Task14. |
| L13 | pass | 29 | Real committed A/B upgrade: A pending+exact repair under A from B parent, B new work/operator history/approve/rollback/capture, unchanged cached producer, absent A read-versus-execution distinction and corrupt retained manifest refusal. |

## Isolated installed execution and recovery

The copied standalone verifier ran from `/private/tmp/sec-local-task14-acceptance/unrelated-cwd` with the accepted native interpreter and `-I -B -X pycache_prefix=/dev/null` before the first app import. Its PID `29532`, executable `/Users/lowell/Projects/sec-edgar-local/releases/sha256=900952a82380297c3e51677b185b17bb179d2beef61e4b0929007f67a09e97bb/venv/bin/python` and import root `/Users/lowell/Projects/sec-edgar-local/releases/sha256=900952a82380297c3e51677b185b17bb179d2beef61e4b0929007f67a09e97bb/venv/lib/python3.14/site-packages` identify the installed wheel; PYTHONPATH is absent. Guard policy has only the exact verified release exception. Both checkout roots deny open/import/exec before application import. The same instrumentation propagates into checked stages and spawned HTTP main before application-class unpickling. Native A/B evidence records ten checked PIDs; upgrade pending/repair records8/15 processes. Exact policies and early guard records are in JSON and retained reports. Source-import provenance remains data.

The installed verifier exercised11 guarded command helps and exact console bootstrap bytes; separate direct root+11 console helps/module version also succeeded outside both checkouts. Fresh reconstruction used retained hash-bearing artifacts offline. Four disposable reconstructed environments refuse app, dependency, interpreter and manifest tampering. A real disposable urllib3 version0.0.0 is refused by both inventory and native verifier while Requests/PyArrow direct pins remain intact. Accepted production bytes and all preexisting A/B bytes are unchanged.

A pending collect exits3 underA then completes underB (1 captured row); exact A publication repair exits9 then completes underB (2 rows). B runs new processing and history/approve/rollback/capture, with one approved row and two restored rows. Cached producer remainsA, absentA still permits history/capture while execution refuses before new call authority, and corrupt retained native manifest refuses historical read. `upgrade-evidence` preserves contexts/call/result refs, original observations, generation/manifest hashes and process policy/PIDs.

Accepted fixture sequence contains4 durable workflow reports and7 captures, 4 distinct captured generations, 7 captured logical rows (repeated captures included). Every captured read is nonempty and validated against exact expected rows. 12 retained Parquet artifacts have actual row counts and exact schemas/hashes recorded. All published data parts and observation files are nonempty; one changes.parquet is an expected empty change stream, separate from published/read row counts. Example actual schema:

```text
change_type: string not null
cik: string not null
archive_path: string not null
before: struct<cik: string not null, company_name: string not null, form_type: string not null, archive_path (... 205 chars omitted)
  child 0, cik: string not null
  child 1, company_name: string not null
  child 2, form_type: string not null
  child 3, archive_path: string not null
  child 4, filing_date: date32[day] not null
  child 5, accession_number: string
  child 6, source_id: string not null
  child 7, source_sha256: string not null
  child 8, parser_version: string not null
  child 9, schema_version: string not null
after: struct<cik: string not null, company_name: string not null, form_type: string not null, archive_path (... 205 chars omitted)
  child 0, cik: string not null
  child 1, company_name: string not null
  child 2, form_type: string not null
  child 3, archive_path: string not null
  child 4, filing_date: date32[day] not null
  child 5, accession_number: string
  child 6, source_id: string not null
  child 7, source_sha256: string not null
  child 8, parser_version: string not null
  child 9, schema_version: string not null
reason: string
```

## Unchanged timing, launcher and retained originals

Both measurements use production3/sec, one-third-second start windows, no fixture timing allowance, unchanged timer/transport code and only test-selected loopback origins. A safe expiry has no socket start/request and is not completed acquisition.

| Measurement | Completed | Safe permit_expired | Observed dispatch-to-socket starts |
| --- | --- | --- | --- |
| installed-latency.json | 2 | 1 | expired, 0.171977s, 0.168902s |
| latency.json | 3 | 0 | 0.096977s, 0.077196s, 0.076233s |

The accepted installed launcher ran six additional retained cases: normal status5; stdout/stderr archive failures9; SIGINT/SIGTERM preserve engine5 and drain children; deadline preserves engine11. Events retain PID/argv, installed local_cli hash, structured errors, raw stdout/stderr hashes and durable result. The full default launcher suite also passed all37 methods including broader status/sink/process-death cases.

Ten complete retained original receipts were rescanned offline under the accepted live parser/schema. Exactly51 conflicting observations remain blocked across2010Q1,2015Q1,2026Q3. Scanner exit1 is expected quarantine evidence, not a test-gate failure. Accepted retained parsing results do not satisfy L12 or assert genuine publication/coverage.

| Receipt | Period | Parsed rows | Conflicts | Source parse | Raw SHA256 |
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

## Transparent setup and evidence-only issues

Primary setup build logs and `setup-attempts.json` retain the initial sandbox cache lookup denial and offline project-sync cache misses. Authorized setup-only locked sync populated missing registry-origin entries; no lock/pin changes occurred. The first orchestration stopped before the suite on the expected generated live config; its exact status/hash was admitted before the single frozen check.

The extra launcher evidence driver first expected10 rather than the existing9 logging-failure contract. Its initial tree/streams are preserved. Controller-scoped correction changed only the external assertion and used `launcher-evidence-final`; no production/default-test change or full/passed-proof repeat occurred.

The extra existing specimen scanner initially lacked historical specimen aliases in the copied map. The original failure/copy/streams are preserved. Controller-authorized `retained-harness-final` adds9 explicit aliases covering10 receipts to exact already hash/length/equality-verified listing bytes (85→94 map entries). `specimen-alias-manifest.json` records old/new maps/hashes and every alias. Source map, original85 entries, all body bytes, helper code, live parser/schema remain unchanged. This unused-helper packaging compatibility remains transparent Task15 triage; it is not a production defect. Initial attempts and corrected results are distinct below.

| Supplemental command | Exit | Seconds | Output streams |
| --- | --- | --- | --- |
| accepted-standalone-verifier | 0 | 68.959 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-standalone-verifier.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-standalone-verifier.stderr` |
| installed-production-latency | 0 | 1.476 | `/private/tmp/sec-local-task14-acceptance/logs/installed-production-latency.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/installed-production-latency.stderr` |
| disposable-negative-preflights | 0 | 4.956 | `/private/tmp/sec-local-task14-acceptance/logs/disposable-negative-preflights.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/disposable-negative-preflights.stderr` |
| installed-launcher-faults-signals | 1 | 1.284 | `/private/tmp/sec-local-task14-acceptance/logs/installed-launcher-faults-signals.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/installed-launcher-faults-signals.stderr` |
| installed-launcher-faults-signals-final | 0 | 3.864 | `/private/tmp/sec-local-task14-acceptance/logs/installed-launcher-faults-signals-final.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/installed-launcher-faults-signals-final.stderr` |
| retained-original-specimens | 1 | 0.400 | `/private/tmp/sec-local-task14-acceptance/logs/retained-original-specimens.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/retained-original-specimens.stderr` |
| accepted-console-root | 0 | 0.615 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-root.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-root.stderr` |
| accepted-console-discover | 0 | 0.305 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-discover.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-discover.stderr` |
| accepted-console-collect | 0 | 0.306 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-collect.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-collect.stderr` |
| accepted-console-transform | 0 | 0.308 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-transform.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-transform.stderr` |
| accepted-console-publish | 0 | 0.307 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-publish.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-publish.stderr` |
| accepted-console-backfill | 0 | 0.307 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-backfill.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-backfill.stderr` |
| accepted-console-daily | 0 | 0.311 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-daily.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-daily.stderr` |
| accepted-console-reconcile | 0 | 0.309 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-reconcile.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-reconcile.stderr` |
| accepted-console-candidates | 0 | 0.308 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-candidates.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-candidates.stderr` |
| accepted-console-approve | 0 | 0.313 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-approve.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-approve.stderr` |
| accepted-console-history | 0 | 0.308 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-history.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-history.stderr` |
| accepted-console-rollback | 0 | 0.309 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-rollback.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-console-rollback.stderr` |
| accepted-module-version | 0 | 0.302 | `/private/tmp/sec-local-task14-acceptance/logs/accepted-module-version.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/accepted-module-version.stderr` |
| retained-original-specimens-final | 1 | 132.793 | `/private/tmp/sec-local-task14-acceptance/logs/retained-original-specimens-final.stdout` / `/private/tmp/sec-local-task14-acceptance/logs/retained-original-specimens-final.stderr` |

Prepared `conf/sec-edgar-local.json` remains an explicit untracked setup file; no live command used it. Original/effective config hashes and original-parent absolute roots are archived. It was created after the clean release build. Original source checkout remains read-only/clean at external docs-only `5e8b61cceea7e18c7bc429b80c23a5d95c334c82`; pinned0e7701a remains extraction authority. No old-state import, source cleanup, parser relaxation, migration, pacing/deadline change or genuine SEC request occurred.

## Review boundary

Only the three Task14 evidence files are committed. `.sdd/1-sec-edgar-local-spec/task-14-acceptance-report.md` provides the controller handoff and validation command; historical preflight/guard reports are preserved. JSON/Markdown/report and later commit receipts are excluded from their own evidence index to avoid circular hashes. Independent Task14 review precedes Task15; L12 stays `not_run` and Task16 live gates persist.
