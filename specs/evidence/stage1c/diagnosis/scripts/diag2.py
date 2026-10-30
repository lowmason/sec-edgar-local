import json, sys
from pathlib import Path
from sec_edgar_ingest.storage.local import LocalObjectStore, LocalStateStore
from sec_edgar_ingest.storage.contracts import REGISTRY_PATH
from sec_edgar_ingest.workflows.completion import evaluate_member

root = Path(sys.argv[1]); target = sys.argv[2]
binding = json.loads((root / 'objects' / REGISTRY_PATH).read_bytes())
objects = LocalObjectStore(root, binding=binding, create=False)
store = LocalStateStore(root, binding=binding, create=False)
m = next(r.to_mapping()['value'] for r in store.scan('WorkflowMember', {}) if r.to_mapping()['value']['member_id'] == target)
print('source:', json.dumps(m['source']))
ev = evaluate_member(m, 'sec-index-parser-v1', 'sec-index-v1', store, objects)
print('complete:', ev.complete, 'obligations:', len(ev.obligations))
for g in ev.gaps:
    print('gap:', json.dumps(g.to_mapping(), default=str))
pub = json.loads((root/'objects/runs/sec/8305a3d9-54a1-46ae-863c-af8227118417/publish/wf-b03b2ccf51c7391d1694e1f7779b419a33721352/result.json').read_bytes())
print('publish result keys:', sorted(pub))
r = pub.get('result', pub)
print('publish outcome:', r.get('outcome'), 'quarters:', r.get('quarters'), 'gaps:', r.get('gaps'))
