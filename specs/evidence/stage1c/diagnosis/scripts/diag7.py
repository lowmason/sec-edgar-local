# Experiment: the proposed core rule. Build the legacy call without the complete-input refusal,
# and refuse an incomplete input only for an Attempt the inventory keeps. Scratch copy only.
import hashlib, json, sys
from pathlib import Path
from sec_edgar_ingest.storage.local import LocalObjectStore, LocalStateStore
from sec_edgar_ingest.storage.contracts import REGISTRY_PATH, Conflict
import sec_edgar_ingest.workflows.completion as comp
from sec_edgar_ingest.etl.contracts import decode_transformed

orig = comp._legacy_publish_call
def build_only(context, objects):
    try:
        return orig(context, objects)
    except Conflict as error:
        if 'no complete publishable input' not in str(error):
            raise
        comp._INCOMPLETE.add(context.attempt_id)
        # Rebuild the same descriptor the original returns after its remaining checks.
        frozen = json.loads(objects.read(comp.result_path(context).rsplit('/', 1)[0] + '/command.json'))
        intent = frozen['intent']
        return {'contract_version': comp.LOCAL_CONTRACT, 'format_version': comp.LEGACY_PUBLISH_FORMAT,
                'context': context.to_mapping(), 'intent': intent, 'input_ref': intent['workset'],
                'result_ref': comp.result_path(context)}
comp._INCOMPLETE = set()
comp._legacy_publish_call = build_only
root = Path(sys.argv[1]); target = sys.argv[2]
binding = json.loads((root / 'objects' / REGISTRY_PATH).read_bytes())
objects = LocalObjectStore(root, binding=binding, create=False)
store = LocalStateStore(root, binding=binding, create=False)
calls = comp._publish_calls(store, objects)
kept_incomplete = [c for c in calls if not decode_transformed(objects.read(c['input_ref'])).complete]
print('inventory calls kept:', len(calls), 'kept with incomplete input:', len(kept_incomplete))
print('Attempts whose input is incomplete (built, then not kept):', sorted(comp._INCOMPLETE))
m = next(r.to_mapping()['value'] for r in store.scan('WorkflowMember', {}) if r.to_mapping()['value']['member_id'] == target)
ev = comp.evaluate_member(m, 'sec-index-parser-v1', 'sec-index-v1', store, objects)
print('complete:', ev.complete, 'obligations:', len(ev.obligations), 'gaps:', [g.code for g in ev.gaps])
