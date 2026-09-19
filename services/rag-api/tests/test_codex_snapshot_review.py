"""Independent review reproductions; synthetic databases only."""
from contextlib import contextmanager
import json

from test_current_change_features import client
from test_codex_knowledge_snapshot import prepared


def test_knowledge_export_is_one_consistent_snapshot_during_tree_publication(client, monkeypatch):
    from app.learning.models import PersonalPlanInput
    from app.learning.snapshot_transfer import export_snapshot
    from app.learning.workspaces import workspace_for
    learning, source, _ = prepared(client)
    scope = workspace_for(learning.db, source, 'user-a')
    original_connect = learning.db.connect
    def plan(version):
        return PersonalPlanInput(operation_id=f'publish-{version}', revision=0, title=f'Tree {version}',
                                 change_reason='Synthetic concurrent publication',
                                 memberships=[{'node_id': 'node-x', 'ordinal': 0, 'spec_version': version}])
    with original_connect() as db:
        learning.knowledge.create_personal_plan(db, scope, plan(1))
    published = False

    class ConnectionProxy:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def execute(self, query, parameters=()):
            nonlocal published
            if not published and query.startswith('SELECT * FROM knowledge_tree_versions WHERE workspace_id='):
                published = True
                # Node/spec reads have finished; another connection publishes
                # a new immutable version before export reads the tree.
                with original_connect() as writer:
                    old = writer.execute("SELECT content_json FROM teaching_specs WHERE node_id='node-x' AND version=1").fetchone()[0]
                    items = json.loads(old)
                    items[0]['objective'] = 'New teaching objective'
                    writer.execute('INSERT INTO teaching_specs VALUES(?,?,?,?)', ('node-x', 2, json.dumps(items), 'b'*64))
                    learning.knowledge.create_personal_plan(writer, scope, plan(2))
            return self.wrapped.execute(query, parameters)

    @contextmanager
    def concurrent_connect():
        with original_connect() as db:
            yield ConnectionProxy(db)

    monkeypatch.setattr(learning.db, 'connect', concurrent_connect)
    snapshot = export_snapshot(learning, source, 'user-a')
    assert published
    specs = {(node['id'], spec['version']) for node in snapshot['nodes'] for spec in node['specs']}
    assert all((member['node_id'], member['spec_version']) in specs
               for member in snapshot['tree']['memberships']), 'export mixed old specs with newly published tree'
