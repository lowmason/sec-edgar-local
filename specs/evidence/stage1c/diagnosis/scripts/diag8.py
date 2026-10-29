# With the diag7 rule patched in memory, count registered members that evaluate complete
# and have no WorkflowMemberResult receipt. Scratch copy only.
import json, runpy, sys
from pathlib import Path
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
ns = runpy.run_path('/tmp/stage1c-scripts/diag7.py')
store, objects, comp = ns['store'], ns['objects'], ns['comp']
receipts = {r.to_mapping()['value']['member_id'] for r in store.scan('WorkflowMemberResult', {})}
complete = []
for row in store.scan('WorkflowMember', {}):
    m = row.to_mapping()['value']
    ev = comp.evaluate_member(m, 'sec-index-parser-v1', 'sec-index-v1', store, objects)
    if ev.complete and m['member_id'] not in receipts:
        complete.append((m['source']['period'], m['member_id'][:12]))
print('members complete without a receipt:', len(complete))
for item in sorted(complete):
    print(' ', *item)
