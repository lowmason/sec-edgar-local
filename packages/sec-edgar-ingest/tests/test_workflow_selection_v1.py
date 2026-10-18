"""Foreign selection and image contexts refuse without opening historical stores."""
from network_guard import install
install()

import hashlib
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from support_checked import workflow_fixture
from sec_edgar_ingest.storage.contracts import Conflict
from sec_edgar_ingest.workflows.contracts import LOCAL_CONTRACT
from sec_edgar_ingest.workflows.results import freeze_workflow, freeze_selection, _validate_selection


def snapshot(store, objects):
    with closing(sqlite3.connect(store.database)) as database:
        logical = tuple(database.iterdump())
    tree = {str(path.relative_to(objects.directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in objects.directory.rglob('*') if path.is_file()}
    return tree, logical


class ForeignSelectionTests(unittest.TestCase):
    def test_old_selection_versions_and_image_contexts_refuse_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            settings, context, pack, store, objects = workflow_fixture(Path(directory))
            self.addCleanup(store.close)
            invocation = {'contract_version': LOCAL_CONTRACT, 'command': context.command,
                          'today': context.pinned_on.isoformat(),
                          'fixture_sha256': hashlib.sha256(pack.read_bytes()).hexdigest(),
                          'pinned_end_quarter': '2026Q4'}
            freeze_workflow(context, invocation, store, objects)
            base = {'contract_version': LOCAL_CONTRACT, 'format_version': 'sec-local-workflow-selection-v1',
                    'context': context.to_mapping(), 'invocation': invocation,
                    'members': [], 'jobs': [], 'member_provenance': [], 'already_complete': [],
                    'superseded': [], 'discovery_call': None, 'discovery_error': None,
                    'parent_ref': None, 'parent_provenance': None, 'discovery_session': None,
                    'required_units': [], 'halted': True, 'requested_quarters': ['2026Q4'],
                    'directories': [], 'boundary_before': None,
                    'gaps': [{'code': 'internal_error', 'message': 'before dispatch', 'retryable': False,
                              'source_id': None, 'details': {}}],
                    'discovered_sources': 0, 'unresolved_before': 0}
            base['discovery_error'] = base['gaps'][0]
            _validate_selection(base, context, invocation, store, objects)
            foreign_context = {k: v for k, v in context.to_mapping().items() if k != 'runtime'}
            foreign_context.update(image_digest='sha256:' + 'f' * 64, format_version='sec-acquisition-v1')
            for name, changed in [('v1', {**base, 'format_version': 'sec-workflow-selection-v1'}),
                                  ('v2', {**base, 'format_version': 'sec-workflow-selection-v2'}),
                                  ('image', {**base, 'context': foreign_context}),
                                  ('missing superseded', {k: v for k, v in base.items() if k != 'superseded'})]:
                with self.subTest(name=name):
                    before = snapshot(store, objects)
                    with self.assertRaises((ValueError, Conflict)):
                        freeze_selection(context, changed, store, objects)
                    self.assertEqual(snapshot(store, objects), before)
