import sys, time, hashlib, json
from pathlib import Path
from sec_edgar_ingest.storage import open_stores
from sec_edgar_ingest.config import load_config
from sec_edgar_ingest.etl.state import EtlState
from sec_edgar_ingest.etl.reader import capture_from_pointer, read_manifest
from sec_edgar_ingest.etl import manifest as M
from sec_edgar_ingest.storage.local import LocalObjectStore, LocalStateStore
from sec_edgar_ingest.storage.contracts import REGISTRY_PATH
root = Path(sys.argv[1]).resolve()
binding = json.loads((root / 'objects' / REGISTRY_PATH).read_bytes())
store = LocalStateStore(root, binding=binding, create=False)
objects = LocalObjectStore(root, binding=binding, create=False)
state = EtlState(store)
out = {}
for q in ('2021Q1', '2021Q2', '2021Q3'):
    p = state.pointer(q)
    if p is None:
        out[q] = None; continue
    cap = capture_from_pointer(p)
    t = time.monotonic(); man = read_manifest(cap, objects); t_read = time.monotonic() - t
    t = time.monotonic()
    for ref in man.files:
        objects.verify(ref.path, ref.sha256, ref.byte_count)
    t_hash = time.monotonic() - t
    t = time.monotonic(); M.validate_files(man, objects); t_files = time.monotonic() - t
    t = time.monotonic(); M._validate_row_origins(man, objects); t_origins = time.monotonic() - t
    out[q] = dict(read_manifest=t_read, hash_files=t_hash, validate_files=t_files, row_origins=t_origins,
                  n_files=len(man.files), n_sources=len(man.sources))
    print(q, out[q], flush=True)
print(json.dumps(out))
