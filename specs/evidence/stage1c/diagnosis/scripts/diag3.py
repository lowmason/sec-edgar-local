import json, sys
from pathlib import Path
from sec_edgar_ingest.storage.local import LocalObjectStore, LocalStateStore
from sec_edgar_ingest.storage.contracts import REGISTRY_PATH
from sec_edgar_ingest.models import RunContext
from sec_edgar_ingest.results import result_path
from sec_edgar_ingest.workflows.completion import _legacy_publish_call
from sec_edgar_ingest.etl.contracts import decode_transformed

root = Path(sys.argv[1])
binding = json.loads((root / 'objects' / REGISTRY_PATH).read_bytes())
objects = LocalObjectStore(root, binding=binding, create=False)
store = LocalStateStore(root, binding=binding, create=False)
checked = set()
from sec_edgar_ingest.workflows.checked import _authority
for row in store.scan('WorkflowChildCall', {}):
    v = row.to_mapping()['value']
    call, t = _authority(v, None, objects)
    if t.command == 'publish':
        checked.add(call['result_ref'])
print('checked publish calls:', len(checked))
for row in store.scan('Attempt', {}):
    v = row.to_mapping()['value']
    c = RunContext.from_mapping(v['context'])
    if c.command != 'publish':
        continue
    p = result_path(c)
    tag = 'checked' if p in checked else 'legacy'
    try:
        _legacy_publish_call(c, objects); status = 'ok'
    except Exception as e:
        status = f'{type(e).__name__}: {e}'
    extra = ''
    if tag == 'legacy':
        cmd = json.loads(objects.read(p.rsplit('/',1)[0] + '/command.json'))
        ws = decode_transformed(objects.read(cmd['intent']['workset']))
        extra = f" workset={cmd['intent']['workset'][-80:]} complete={ws.complete} obs={len(ws.observations)}"
    print(tag, c.run_id, c.attempt_id, c.started_at.isoformat(), 'result' if v['result'] is not None else 'NO-RESULT', status if tag=='legacy' else '', extra)
