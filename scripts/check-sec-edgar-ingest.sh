#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$project_root"
export UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never
SEC_LOCAL_PROOF_CACHE=${SEC_LOCAL_PROOF_CACHE:-"$project_root/releases/artifact-cache"}
export SEC_LOCAL_PROOF_CACHE
case "$SEC_LOCAL_PROOF_CACHE" in /*) ;; *) printf '%s\n' 'SEC_LOCAL_PROOF_CACHE must be absolute' >&2; exit 2 ;; esac
uv run --offline --locked --package sec-edgar-ingest python packages/sec-edgar-ingest/tests/network_guard.py discover -s packages/sec-edgar-ingest/tests -p 'test_*.py' -v
# Validate retained artifacts and generate constraints from the verified backend hash.
constraints=$(mktemp "${TMPDIR:-/tmp}/sec-local-build-constraints.XXXXXX")
trap 'rm -f "$constraints"' EXIT HUP INT TERM
uv run --offline --locked --package sec-edgar-ingest python - "$SEC_LOCAL_PROOF_CACHE" "$constraints" <<'PY'
import json, pathlib, sys
from sec_edgar_ingest.release import BUILD_VERSION, prepare_artifact_cache
cache = pathlib.Path(sys.argv[1])
prepare_artifact_cache(pathlib.Path('uv.lock'), pathlib.Path(sys.executable), cache, offline=True)
build, = (item for item in json.loads((cache / 'artifacts.json').read_text())['artifacts'] if item['role'] == 'build')
pathlib.Path(sys.argv[2]).write_text(f'uv_build=={BUILD_VERSION} --hash=sha256:{build["sha256"]}\n')
PY
uv build --offline --package sec-edgar-ingest --wheel --sdist --force-pep517 \
  --no-index --find-links "$SEC_LOCAL_PROOF_CACHE/build" --build-constraints "$constraints" \
  --require-build-hashes --preview-features build-dependency-hashes
uv run --offline --locked --package sec-edgar-ingest sec-edgar-ingest --help
for command in discover collect transform publish backfill daily reconcile candidates approve history rollback; do
  uv run --offline --locked --package sec-edgar-ingest sec-edgar-ingest "$command" --help >/dev/null
done
uv run --offline --locked --package sec-edgar-ingest python -m sec_edgar_ingest --version
uv run --offline --locked --package sec-edgar-ingest python -m sec_edgar_ingest --help
uv run --offline --locked --package sec-edgar-ingest python -m compileall -q packages/sec-edgar-ingest/src
git -c core.whitespace=cr-at-eol diff --check
