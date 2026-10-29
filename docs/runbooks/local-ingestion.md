# Manual local ingestion

Finish [native setup](native-setup.md) first. Live execution uses a non-editable installed wheel in `releases/sha256=<release-id>/venv`. Each native application process must use `-I -B -X pycache_prefix=/dev/null` before its first application import. No checkout imports, application PYTHONPATH, dependency sync/resolution/install or interpreter download occurs during a run.

Only after the release ID exists, create `conf/sec-edgar-local.json` from the checked fixture config. This prepares configuration and performs no ingestion:

```sh
project=$(pwd -P)
release="$project/releases/sha256=RELEASE_ID"
.venv/bin/python - "$release/release.json" <<'PY'
import json, pathlib, sys
path = pathlib.Path('conf/sec-edgar-local.json')
value = json.loads(pathlib.Path('conf/sec-edgar-local-fixture.json').read_text())
value['storage'] = {'backend': 'local', 'root': '../data'}
value['logging'] = {'root': '../logs'}
value['acquisition'] = {'mode': 'live'}
value['runtime'] = {'kind': 'native', 'release_manifest': str(pathlib.Path(sys.argv[1]).resolve())}
value['etl']['parser_version'] = 'sec-index-parser-v1'
value['backfill'] = {'start_quarter': '2020Q1', 'end_quarter': 'open'}
with path.open('x') as stream: json.dump(value, stream, indent=2); stream.write('\n')
PY
```

Keep config version `sec-local-config-v1`, schema `sec-index-v1`, withdrawal approval true, backfill `2020Q1` to `open`, daily handoff `2026-10-01`, owner User-Agent `Lowell Mason sec-edgar-ingest mason.lowell@mac.com`, namespace `sec-owner-lowell-mason`, 3 requests/second and one collector. A lower positive rate is permitted; higher rates are refused. Preserve five total attempts, 2-second base/120-second capped jittered backoff honoring longer server delays, 15/60-second connect/read timeouts, 90-second exchange limit, 67,108,864 received-byte/536,870,912 expanded-byte limits, finite 60-second lease, 20-second renewal and 2-second uncertainty bound.

Paths resolve against the original config parent. The launcher archives normalized absolute paths and hashes that effective config; it records the original input-byte hash separately. Logical object keys remain safe relative POSIX paths. A fresh `sec-local-binding-v1` store binds root, mode, issuer, policies and storage contract, excluding release/parser/range/IDs. Never repoint an existing store to another root, import old state or change mode to reuse a fixture store.

The owner has declared this the sole live issuer externally. The launcher cannot inspect or stop other collectors or Azure. Collector commands on the same bound root coordinate using one fixed lease with pacing/cooldowns, fencing and positive HTTP-child drain confirmation. Different roots do not coordinate, even with the same namespace. The operating declaration must remain true across all collectors. Live operation still requires the separate accepted release, harness, configuration, budget and later activation gates.

Manual launcher workflows:

```sh
scripts/sec-edgar-local backfill --config "$project/conf/sec-edgar-local.json"
scripts/sec-edgar-local daily --config "$project/conf/sec-edgar-local.json" --timeout-seconds 3300
scripts/sec-edgar-local reconcile --config "$project/conf/sec-edgar-local.json"
```

The default config is located relative to the launcher project from any cwd; an explicit relative `--config` resolves from the calling cwd. Default timeout is 3300 seconds; require `0 < N <= execution.max_run_seconds`, whose live value is 3600. The launcher also refuses `N <= execution.dispatch_reserve_seconds` (D5 and 1b releases). Admission refuses a live config with no `execution.dispatch_reserve_seconds`. It also refuses a value outside `floor <= value < execution.max_run_seconds`. The floor is 480 s and the live reserve is 1800 s, set from measured member costs (Stage 1b). The launcher generates fresh IDs/deadline each invocation and pins its supplementary range. The engine's saved context/result is authoritative. No automatic scheduling is supplied. Workflow backfill freezes an inclusive range; `open` resolves once per invocation. Daily catches up from the configured handoff with retained unresolved exact work. Reconcile refreshes supported quarterly originals and uses the same validation/approval rules.

Each launch retains `logs/<run-id>/<attempt-id>/invocation.json`, normalized `config.json`, and byte-preserving separate `stdout.jsonl`/`stderr.jsonl`. Invocation evidence includes original/effective config hashes, release, argv, IDs and UTC deadline. Stdout is the engine's one JSON result; stderr includes structured engine/launcher events. Stream failure returns 9 while retaining actual engine status where possible. SIGINT/SIGTERM/deadline trigger bounded group forwarding/drain; forced cleanup or unavailable ancestry records shutdown uncertainty and cannot manufacture durable completion. Consult [recovery](local-recovery.md) before retrying.

For low-level manual workflows, use the same explicitly selected runtime/config and explicit IDs/deadline:

```sh
deadline=$("$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -c \
  'from datetime import datetime,timedelta,timezone; print((datetime.now(timezone.utc)+timedelta(seconds=3300)).isoformat())')
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -m sec_edgar_ingest backfill \
  --config "$project/conf/sec-edgar-local.json" --run-id manual-backfill-1 \
  --execution-id manual-1 --attempt-id attempt-1 --deadline "$deadline"
```

Choose a fresh valid deadline within the live run allowance at execution time. `daily` and `reconcile` take the same identity arguments. `discover` additionally requires `--mode quarterly|daily --discovery-id ID`; `collect`, `transform` and `publish` require an exact `--workset` reference returned by the preceding command. Discover may take `--refresh`; transform's `--force` rebuilds supported transformations and never bypasses quarantine or approval. `--today` and `--fixture-pack` are explicit fixture-only controls with individually enabled fixture exceptions. Removed provider identity, `--config-env` and `--state-dir` options are refused.

Operator commands open an existing store verify-only; labels are explicit audit text, not authentication:

```sh
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -m sec_edgar_ingest candidates --config "$project/conf/sec-edgar-local.json"
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -m sec_edgar_ingest history --config "$project/conf/sec-edgar-local.json" --quarter 2026Q3
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -m sec_edgar_ingest approve --config "$project/conf/sec-edgar-local.json" --quarter 2026Q3 --generation GENERATION_ID --quarterly-sha256 QUARTERLY_SHA256 --approver 'Lowell Mason'
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null -m sec_edgar_ingest rollback --config "$project/conf/sec-edgar-local.json" --quarter 2026Q3 --from-generation CURRENT_ID --to-generation RETAINED_ID --reason 'Reviewed source reversion' --operator 'Lowell Mason'
```

Review exact candidate rows, withdrawal reason, current history and hashes before approval/rollback. First approval binds one exact candidate generation; newer bytes require new review. A repeated older body can produce `source_reverted` rather than publish. No force bypass, duplicate winner or zero-row exception is supported. Retained whole-source quarantines remain 21 conflicting observations in 2010Q1, 24 in 2015Q1 and 6 in 2026Q3, total 51.

| Exit | Meaning |
|---|---|
| 0 | Completed success, unchanged or no new sources |
| 2 | Invalid configuration/input, unfinished expired deadline or refused approval/rollback |
| 3 | Incomplete/discovery failure |
| 4 | Pending work |
| 5 | Retry/deferred/throttled |
| 6 | Access blocked |
| 7 | Whole-source quarantine/invalid source |
| 8 | Lost ownership |
| 9 | State/internal/publication conflict or required launcher logging failure |
| 10 | Awaiting approval |
| 11 | Stale approval/rollback |

Pending, gated, deferred, quarantined and partially published outcomes stay nonzero. Keep the complete durable result and exact references. L01–L11/L13 have [renewed passing offline evidence](../../specs/evidence/local-port/offline-renewal-task15.md). The separate [genuine SEC acceptance record](../../specs/evidence/local-port/sec-acceptance.md) records an L12 pass established by a reviewed supplemental offline adjudication of the preserved genuine attempt; the original run and verification remain incomplete with exit 12. This bounded result establishes no historical coverage. The preserved generated default config still references the old `900952a8…` release and was not selected for this case; the examples above require explicit reviewed release/config selection, budgets and operating gates before further live operation.
