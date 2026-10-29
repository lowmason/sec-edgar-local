import json, sys
from pathlib import Path
from sec_edgar_ingest.storage.local import LocalObjectStore, LocalStateStore
from sec_edgar_ingest.storage.contracts import REGISTRY_PATH, Conflict
import sec_edgar_ingest.workflows.completion as comp
from sec_edgar_ingest.models import RunContext

orig = comp._legacy_publish_call
FINISHED = set()
def patched(context, objects):
    # Experiment only: treat a finished Attempt whose input is incomplete as not a repair candidate.
    try:
        return orig(context, objects)
    except Conflict as e:
        if 'no complete publishable input' in str(e) and context.attempt_id in FINISHED:
            raise KeyError('skip finished incomplete-input publish')  # caught? no -> handled below
        raise
root = Path(sys.argv[1]); target = sys.argv[2]
binding = json.loads((root / 'objects' / REGISTRY_PATH).read_bytes())
objects = LocalObjectStore(root, binding=binding, create=False)
store = LocalStateStore(root, binding=binding, create=False)
# Reimplement the legacy loop with the result check first.
orig_scan = store.scan
def scan(kind, filt):
    rows = list(orig_scan(kind, filt))
    if kind != 'Attempt':
        return rows
    keep = []
    for r in rows:
        v = r.to_mapping()['value']
        c = RunContext.from_mapping(v['context'])
        if c.command == 'publish' and v['result'] is not None:
            try:
                orig(c, objects)
            except Conflict:
                continue  # finished, harmless: drop from the experiment's view
        keep.append(r)
    return keep
store.scan = scan
m = next(r.to_mapping()['value'] for r in orig_scan('WorkflowMember', {}) if r.to_mapping()['value']['member_id'] == target)
ev = comp.evaluate_member(m, 'sec-index-parser-v1', 'sec-index-v1', store, objects)
print('complete:', ev.complete, 'obligations:', len(ev.obligations))
for g in ev.gaps:
    print('gap:', json.dumps(g.to_mapping(), default=str))
if ev.capture:
    print('affected_quarters:', ev.capture['affected_quarters'])
    print('quarter captures:', len(ev.capture['quarters']))
