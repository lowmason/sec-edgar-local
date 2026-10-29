import json, sys
from pathlib import Path
from sec_edgar_ingest.storage.local import LocalObjectStore, LocalStateStore
from sec_edgar_ingest.storage.contracts import REGISTRY_PATH
root = Path(sys.argv[1])
binding = json.loads((root / 'objects' / REGISTRY_PATH).read_bytes())
store = LocalStateStore(root, binding=binding, create=False)
print('WorkflowRepairObligation rows:', len(list(store.scan('WorkflowRepairObligation', {}))))
ptrs = list(store.scan('QuarterPublication', {}))
print('QuarterPublication rows:', len(ptrs))
for p in ptrs:
    v = p.to_mapping()['value']
    print(' ', p.to_mapping().get('key'), {k: v[k] for k in v if k in ('quarter','generation_id','previous_generation_id','base_generation_id')})
