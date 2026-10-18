# sec-edgar-local

A native local fork of SEC filing-index ingestion, distribution/import `sec-edgar-ingest` / `sec_edgar_ingest` version 0.2.0. It retains immutable SEC index originals, transforms validated observations, and publishes captured per-quarter Parquet generations with reconciliation, withdrawal approval and recorded rollback.

The first supported host is this Mac: CPython 3.14, macOS arm64, and a native filesystem with working SQLite locking and atomic filesystem operations. There is one workspace package. Runtime dependencies are Requests 2.34.2, PyArrow 25.0.1 and their exact locked transitives. No cloud SDK, CLI, container service or cloud fallback is required.

Start with [native setup](docs/runbooks/native-setup.md), then [manual local ingestion](docs/runbooks/local-ingestion.md). Keep [recovery](docs/runbooks/local-recovery.md) and [release upgrades](docs/runbooks/release-upgrades.md) with operational evidence. Dependencies/artifacts are prepared explicitly before the offline checks:

```sh
uv sync --locked
sh scripts/check-sec-edgar-ingest.sh
```

The complete check fails if its declared offline artifacts are absent. Test-only `SEC_LOCAL_PROOF_CACHE` and `SEC_LOCAL_PROOF_CATALOG` are described in setup. Ingestion uses an immutable non-editable installed release and never syncs dependencies. No scheduling or notifications are installed.

L01–L11/L13 have [renewed passing offline evidence](specs/evidence/local-port/offline-renewal-task15.md). The separate [genuine SEC acceptance record](specs/evidence/local-port/sec-acceptance.md) records an L12 pass established by a reviewed supplemental offline adjudication of the preserved genuine attempt; the original run and verification remain incomplete with exit 12. This bounded result does not establish historical coverage or authorize further live runs. The preserved generated default config still references the old `900952a8…` release and was not selected for this acceptance case; further operation requires explicit reviewed release/config selection, budgets and operating gates.
