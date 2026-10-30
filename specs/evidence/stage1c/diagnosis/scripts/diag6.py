# Independent full-path rebuild of each quarter the halted publish wrote, compared row by row
# with the stored generation. Runs on the scratch copy only.
import hashlib, json, sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from sec_edgar_ingest.storage.local import LocalObjectStore, LocalStateStore
from sec_edgar_ingest.storage.contracts import REGISTRY_PATH
from sec_edgar_ingest.models import RunContext, canonical_json
import sec_edgar_ingest.etl.catalog as catalog
from sec_edgar_ingest.etl.contracts import GenerationCapture, IndexRow
from sec_edgar_ingest.etl.manifest import read_manifest, iter_file_rows
from sec_edgar_ingest.etl.reader import capture_quarter, checked_manifest
from sec_edgar_ingest.etl.state import EtlState

catalog._check_deadline = lambda context: None  # the original deadline has passed; the experiment ignores it
root = Path(sys.argv[1])
binding = json.loads((root / 'objects' / REGISTRY_PATH).read_bytes())
objects = LocalObjectStore(root, binding=binding, create=False)
store = LocalStateStore(root, binding=binding, create=False)
pub = json.loads(objects.read('runs/sec/8305a3d9-54a1-46ae-863c-af8227118417/publish/wf-b03b2ccf51c7391d1694e1f7779b419a33721352/result.json'))
context = RunContext.from_mapping(pub['context'])
state = EtlState(store)
ok = True
for q in pub['quarters']:
    quarter = q['quarter']
    capture = capture_quarter(quarter, objects, state)
    new = checked_manifest(capture, objects)
    assert new.generation_id == q['generation_id']
    base = None
    if new.base_generation_id is not None:
        ref = capture.manifest_ref.replace(new.generation_id, new.base_generation_id)
        body = objects.read(ref)
        base = read_manifest(GenerationCapture(quarter, new.base_generation_id, ref, hashlib.sha256(body).hexdigest(), len(body)), objects)
        base_release = base.context.runtime['release_sha256'][:8] if hasattr(base, 'context') and base.context else '?'
    with TemporaryDirectory(prefix='stage1c-full-') as d, closing(catalog._database(Path(d) / 'c.sqlite')) as db:
        catalog._load_observations(db, new.sources, quarter, new.membership_source, objects, context)
        catalog._load_active(db, base, objects)
        counts = catalog._resolve(db, new.quarter_mode, new.membership_source)
        expected = {(c, p): pl for c, p, pl in db.execute('SELECT cik,path,payload FROM proposed')}
    data = next(f for f in new.files if f.role == 'data')
    actual = {}
    with closing(iter_file_rows(data, objects)) as rows:
        for value in rows:
            row = IndexRow(**value)
            actual[row.cik, row.archive_path] = canonical_json(row.to_mapping())
    same = actual == expected
    ok &= same
    print(quarter, 'mode=%s' % new.quarter_mode, 'base=%s' % (new.base_generation_id or 'none')[:12],
          'sources=%d' % len(new.sources), 'rows=%d' % len(actual), 'full=%d' % len(expected),
          'EQUAL' if same else 'DIFFER (missing=%d extra=%d changed=%d)' % (
              len(expected.keys() - actual.keys()), len(actual.keys() - expected.keys()),
              sum(1 for k in actual.keys() & expected.keys() if actual[k] != expected[k])))
print('ALL_EQUAL' if ok else 'SOME_DIFFER')
