"""Diagnosis only: run the D5 measure script's smoke scale and count full generation validations.

Counts every in-engine call of etl.manifest._validate_row_origins (the 363 s part of one full
check at full size) by its sec_edgar_ingest call chain. Children are native processes and are
not counted here.
"""
import collections, importlib.util, json, sys, traceback
from pathlib import Path

script = Path('/Users/lowell/Projects/sec-edgar-local/scripts/measure-d5-drain.py')
spec = importlib.util.spec_from_file_location('measure', script)
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)

from sec_edgar_ingest.etl import manifest as M
COUNTS = collections.Counter()
EVENTS = []
original = M._validate_row_origins
def counted(manifest, objects):
    chain = [f.name for f in traceback.extract_stack()[:-1] if 'sec_edgar_ingest' in f.filename]
    key = ' > '.join(chain[-7:])
    COUNTS[key] += 1
    EVENTS.append({'quarter': manifest.quarter, 'n_sources': len(manifest.sources), 'chain': key,
                   'members_done': len(measure.MEMBERS), 'timings_done': len(measure.TIMINGS)})
    return original(manifest, objects)
M._validate_row_origins = counted

out = Path(sys.argv[1])
code = measure.main(['run', '--release-manifest', sys.argv[2], '--work', str(out), '--counts', sys.argv[3], '--scale', 'smoke'])
(out / 'validation-counts.json').write_text(json.dumps({'by_chain': COUNTS.most_common(), 'events': EVENTS}, indent=1))
print('exit', code, 'total', sum(COUNTS.values()))
for k, v in COUNTS.most_common():
    print(v, k)
