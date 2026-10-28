# Local recovery and captured reads

Retain invocation/config/argv, engine stdout/stderr, launcher events, release manifest/receipt, durable result references, worksets, object hashes and state evidence before recovery. Inspect the result's exact outcome and counts; pointer movement alone cannot prove completion. A launcher status can differ from engine status after logging failure. Never edit pointers, manufacture completion, select a duplicate winner, glob Parquet or automatically delete partial files.

Use the following distinctions:

| Situation | Recovery boundary |
|---|---|
| Completed exact replay | Run the archived native argv using its original release, config, IDs, deadline and intent. It returns the immutable durable result without HTTP, including after deadline. Preserve original captured generations. |
| Unfinished expired attempt | Retain the old attempt; supply a new valid attempt ID and deadline for the same frozen invocation intent where supported. Do not rewrite the old context/deadline. |
| New-ID continuation | A new launcher invocation generates new IDs and resumes retained unresolved work under current policy. It is a new result, not an exact replay. |
| Pending/partial work | Read exact gaps and frozen workset references; continue eligible work through checked command boundaries. Newer listings do not silently withdraw older unresolved units. |
| Awaiting approval | Review candidates/history and approve the exact generation/hash with explicit audit label, then continue. Approval-gated work stays exit 10 until discharged. |
| Quarantine | Retain the entire source and invalid-observation evidence. No winner selection, parser relaxation, zero-row exception or force bypass; investigate independently. |
| Crash after pointer update | Re-run through the checked publish/workflow boundary to repair immutable result/index completion. Do not advance the pointer a second time. A pointer without member completion remains a repair obligation. |
| Refused incremental candidate | A candidate that the equivalence check refuses stays in the write-once store. A retry with the same inputs runs the full check on it. When that check fails, `publish` reports `invalid_source`, which is not retryable. This holds even after a code fix, unless that fix changes the retained basis. Otherwise the quarter recovers only when its source set or base changes, or when an operator removes that candidate's objects from the object store. |

For exact replay, read `invocation.json` and execute its stored `argv` list without shell interpolation. The original release directory/environment must remain available. Preserve normalized archived config and original byte-hash evidence. New code may validate/read old history and artifacts; executing an old attempt requires its original verified runtime. Missing runtime is an explicit failure. Reconstruct only from retained verified release artifacts using [release upgrades](release-upgrades.md); never substitute a newer runtime identity.

After SIGINT/SIGTERM, forced cleanup, clock uncertainty, lost ownership or an uncertain shutdown, preserve engine/child PID-birth evidence, shutdown events, lease/fence/cooldown state and actual process statuses. Confirm all participating writers/HTTP children stopped before operational recovery. Do not treat a dead engine, closed pipes, expired lease or SIGKILL alone as positive HTTP drain. Do not adjust clocks to bypass uncertainty/fencing; resolve host clock health and allow conservative lease/cooldown policy to work. The launcher cannot prove other collectors on different roots have stopped.

For disk full or I/O failure, stop writers, preserve partial invocation/artifact evidence and obtain capacity on the same supported native filesystem without deleting retained application objects. There is no automatic cleanup or garbage collection. Free unrelated disposable files only under a separately reviewed operational decision. Retry through the command boundary after storage health returns. Corrupt SQLite, binding, object/manifest hash mismatch or conflicting immutable writes require stopped-writer evidence and investigation/restoration, never manual edits to repair pointers or hashes.

Backups require stopped writers and confirmed child drain. Preserve a consistent SQLite snapshot plus its matching entire immutable object tree, binding file, configs, invocation logs and all required original releases. A raw copy of `state.sqlite3` alone while WAL/SHM are live is not a consistent backup. After stopping writers, use SQLite's backup API (or a tested equivalent), preserving source evidence; include any other state files in the stopped-root snapshot. For example, with a new absolute destination:

```sh
.venv/bin/python - /absolute/data/state.sqlite3 /absolute/backup/state.sqlite3 <<'PY'
import pathlib, sqlite3, sys
source, target = map(pathlib.Path, sys.argv[1:])
if target.exists(): raise ValueError('backup target must be new')
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(target) as dst: src.backup(dst)
PY
```

Copy matching immutable objects/binding/logs/releases while writers remain stopped; inventory hashes and test a restoration on the same supported root contract before relying on the backup. Do not omit uncheckpointed WAL/SHM by guessing they are disposable, copy a running venv to a different address, relocate a bound store or migrate an old store. Restoring the original bound root is distinct from unsupported store relocation. Shared/network filesystems and Windows are unsupported.

Readers capture one exact generation before reading. Run the following under the selected installed interpreter with native flags, passing an absolute current config. Operator access verifies an existing store without creating one. The read validates the captured manifest/files/counts before exposing rows, and the saved capture remains stable if a newer generation publishes:

```python
import json
from pathlib import Path
from sec_edgar_ingest.config import load_config
from sec_edgar_ingest.storage import open_stores
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.reader import capture_quarter, read_quarter

settings = load_config(Path('/absolute/conf/sec-edgar-local.json'))
store, objects, _ = open_stores(settings, access='operator')
try:
    capture = capture_quarter('2026Q3', objects, EtlState(store))
    if capture is None:
        raise ValueError('quarter has no published generation')
    validated_count = sum(1 for row in read_quarter(capture, objects))
    print(json.dumps({'capture': capture.to_mapping(), 'validated_rows': validated_count}))
finally:
    store.close()
```

Archive this exact capture/count with the reader's release/config evidence. A valid capture/read is not evidence that every workflow source completed or that historical production coverage exists. L12 remains a separate genuine SEC acceptance run, `not_run` until its own evidence is recorded.
