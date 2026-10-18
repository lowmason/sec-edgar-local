# Native setup and offline verification

Supported host: this Mac, CPython 3.14 on macOS arm64, native filesystem with SQLite locking and atomic rename/exclusive-create semantics. Keep `requires-python >=3.14` and `.python-version` 3.14. Windows, shared/network filesystems, old-state migration and store relocation are unsupported. Use a fresh store. The source baseline is retained by Git object identity; never copy a moving upstream checkout.

From the project root, explicit dependency setup may fetch the exact locked artifacts. Interpreter downloads are a separate deliberate setup decision; these examples use the already installed 3.14 interpreter:

```sh
export UV_PYTHON_DOWNLOADS=never
uv sync --locked
project=$(pwd -P)
python="$project/.venv/bin/python"
cache="$project/releases/artifact-cache"
uv run --offline --locked --package sec-edgar-ingest python scripts/prepare-native-release.py \
  --project "$project" --python "$python" --artifact-cache "$cache" --prepare-cache-only
```

The cache-only operation explicitly obtains the lock-selected public runtime wheels and uv_build 0.12.24. It is setup, not ingestion or a default check. It records exact filename/URL/SHA-256, lock and native interpreter identity in `artifacts.json`; it retains `runtime/`, `build/`, and hash-bearing `build-requirements.txt`. The backend metadata range stays `uv_build>=0.12.15,<0.13.0`. No opportunistic upgrades. Tool evidence currently records CPython 3.14.0 and uv 0.13.1; each release records its actual interpreter, uv and backend versions.

A production build requires a clean committed project, including untracked nonignored files. Commit reviewed work before this command:

```sh
uv run --offline --locked --package sec-edgar-ingest python scripts/prepare-native-release.py \
  --project "$project" --releases "$project/releases" --python "$python" \
  --artifact-cache "$cache" --offline
```

The builder checks lock freshness, builds wheel and sdist offline with force-PEP517, no-index, pinned backend hash constraints and build-hash enforcement. It installs runtime requirements with hashes, then the application wheel non-editably with no dependencies. The create-only result is `releases/sha256=<release-id>/`: `release.json`, `installation.json`, `venv/`, `wheels/` (wheel and source sdist), `artifacts/`, `uv.lock`, `runtime-requirements.txt`, and setup evidence. Retain the entire directory. Release identity covers source revision, application wheel/payload, lock, exact complete runtime graph and interpreter identity. A matching complete release is verified/reused; incomplete/conflicting directories fail without overwrite or cleanup.

After a release ID exists, prepare the live config as in [local ingestion](local-ingestion.md). Build/setup and check commands never imply authority to run genuine SEC traffic.

Complete offline checks from the project root:

```sh
export UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never
export SEC_LOCAL_PROOF_CACHE="$cache"
sh scripts/check-sec-edgar-ingest.sh
```

`SEC_LOCAL_PROOF_CACHE` must be absolute; default is project `releases/artifact-cache`. All shared proof factory callers use this input. Missing cache/artifacts fail, with no skip or fetching. With no catalog, tests commit independent A/B source snapshots and build actual installed releases offline. These disposable factory environments are deleted at process exit.

To retain proof environments for a later acceptance process, reconstruct them into their final durable location while the factory process is still alive. Do not copy or move a venv. Run this explicit setup snippet from the project root, with a new absolute `proof_root`:

```sh
proof_root=/private/tmp/sec-local-proof-retained
uv run --offline --locked --package sec-edgar-ingest python - "$proof_root" <<'PY'
import json, pathlib, shutil, sys
project = pathlib.Path.cwd().resolve()
sys.path.insert(0, str(project / 'packages/sec-edgar-ingest/tests'))
from network_guard import install
install()
from support_release import proof_releases
from workflow_proof import harness_files
from sec_edgar_ingest.release import reconstruct_release
root = pathlib.Path(sys.argv[1])
if not root.is_absolute(): raise ValueError('proof root must be absolute')
root.mkdir(parents=True, exist_ok=False)
a, b = proof_releases(project, project / 'releases/artifact-cache')
releases = [reconstruct_release(p.directory / 'release.json', root / 'releases',
            python=pathlib.Path(sys.executable)) for p in (a, b)]
harness = root / 'harness'
source = project / 'packages/sec-edgar-ingest/tests'
for path in harness_files():
    target = harness / path.relative_to(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
(root / 'catalog.json').write_text(json.dumps({
    'format_version': 'sec-local-proof-catalog-v1',
    'a_manifest': str(releases[0] / 'release.json'),
    'b_manifest': str(releases[1] / 'release.json'), 'harness': str(harness)}, indent=2) + '\n')
print(root / 'catalog.json')
PY
export SEC_LOCAL_PROOF_CATALOG="$proof_root/catalog.json"
sh scripts/check-sec-edgar-ingest.sh
```

Unset `SEC_LOCAL_PROOF_CATALOG` when preparing a fresh pair; an existing catalog deliberately reuses the declared releases. The optional catalog file and every referenced path must be absolute. Its exact four fields and version above are required, as are distinct real preflighted A/B releases and exact installed inventories. The explicitly selected test-only harness is copied and actually executed by the isolated verifier. Cache/catalog environment variables are test-harness inputs, never production configuration. A standalone equivalent uses the chosen release's installed Python:

```sh
release=/absolute/releases/sha256=RELEASE_ID
"$release/venv/bin/python" -I -B -X pycache_prefix=/dev/null \
  "$project/scripts/verify-native-release.py" --release "$release" \
  --harness "$proof_root/harness" --evidence /absolute/new/evidence
```

Evidence directories are create-only. The verifier installs network_guard before application imports, copies only declared test support, runs outside both checkouts without application PYTHONPATH, checks full wheel/lock/export/installed inventories and all eleven installed module helps (with exact shell console bootstrap bytes verified), then executes the fixture workflow/captured reader proof. Default tests also cover real transitive tamper, two-release continuation/repair, launcher logging and signal behavior. They permit only explicitly selected loopback test traffic. L01–L11/L13 fresh complete installed acceptance is pending Task 14; L12 genuine SEC acceptance remains `not_run` and separate. No fixture proof establishes historical coverage or readiness for live activation.
