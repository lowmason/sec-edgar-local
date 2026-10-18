# Immutable release upgrades and reconstruction

Prepare dependencies and artifacts explicitly as in [native setup](native-setup.md). Build reviewed clean committed code into a new `releases/sha256=<release-id>` environment; never install into an existing accepted venv or sync it during ingestion. Keep original manifests, receipts, wheels/sdists, lock/export, exact runtime wheels and setup evidence. Release identity is not a container image digest and has no compatibility alias.

Before selecting B, stop/confirm old writers and child drain, retain A and its invocation/config/result evidence, and take a consistent backup if required. Review the exact new release, accepted harness, effective config and run budget at the later activation gates. Selecting B in a new config changes its `runtime.release_manifest`; storage root/mode/issuer/policies/storage contract stay bound. Old range/IDs/parser/release are not part of the root binding. New code can read validated historical producer records; old execution still requires A. Verify B with the copied offline harness and a new evidence directory before using it.

A later new-ID invocation under B may continue compatible A-origin pending work and repair A-origin publication evidence through the original checked child authority. A completed exact A attempt replays with A and its unchanged argv/config/IDs/deadline. Do not rewrite retained producer release metadata to B. Captured reads remain bound to exact original manifests even when current pointers change. Unsupported parser/schema transitions must refuse; no old-state import, relocation, force bypass or automatic cleanup is provided.

If an original environment is missing but all retained artifacts remain valid, reconstruct it at its final new release address using the exact matching supported interpreter. This is explicit setup, offline and outside ingestion. Do not copy or move a venv:

```sh
project=$(pwd -P)
manifest=/absolute/retained/releases/sha256=RELEASE_ID/release.json
new_releases=/absolute/recovery/releases
uv run --offline --locked --package sec-edgar-ingest python - "$manifest" "$new_releases" <<'PY'
from pathlib import Path
import sys
from sec_edgar_ingest.release import reconstruct_release
print(reconstruct_release(Path(sys.argv[1]), Path(sys.argv[2]), python=Path(sys.executable)))
PY
```

The source manifest's sibling artifacts must be intact. Reconstruction validates hashes and complete inventories independently of the missing old executable/receipt, requires matching interpreter identity, creates the final content-addressed destination exclusively, then installs from retained artifacts and issues a new installation receipt. Missing artifacts/interpreter mismatch are explicit failures. Preserve the unavailable original location/evidence; a new location does not rewrite saved attempt config or authorize silently redirecting an exact replay. Resolve original-runtime availability through reviewed recovery rather than substituting B or editing retained invocation records.

Rolling back a release selection means choosing a retained verified release for a new invocation/config, subject to compatibility and operating gates. Rolling back quarter data is the separate audited `rollback` operator command in [local ingestion](local-ingestion.md), with exact from/to generations, reason and operator label. Never edit a publication pointer manually.

Fresh installed L01–L11/L13 complete offline acceptance recording is pending Task 14. The test suite includes actual two-release pending/repair/read authority and a disposable real urllib3 version tamper while required direct pins remain intact. These do not establish L12 (`not_run`), historical coverage or live release readiness; later review, release/harness/config selection and budget gates remain.
