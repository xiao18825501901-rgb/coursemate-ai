import json

import pytest

from test_current_change_features import UI, auth, client, make_course


def prepared(client):
    make_course(client)
    source = client.post('/api/learning/workspaces', headers=auth('token-a'), json={'course_id': 'cs3481'}).json()['id']
    private = client.post(f'{UI}/courses', headers=auth('token-a'), json={'name': 'Snapshot recipient'}).json()['id']
    target = client.post('/api/learning/workspaces', headers=auth('token-a'), json={'course_id': private}).json()['id']
    learning = client.app.state.learning
    with learning.db.connect() as db:
        content = json.dumps([{'item_id': 'original-required', 'requirement': 'REQUIRED', 'objective': 'Explain isolation', 'acceptance': 'Use a transaction example', 'evidence_ids': ['unavailable-source-chunk']}])
        db.execute('INSERT INTO teaching_specs VALUES(?,?,?,?)', ('node-x', 1, content, 'a'*64))
    return learning, source, target


def test_snapshot_preserves_specs_without_copying_learning_state_and_retries(client):
    from app.learning.snapshot_transfer import export_snapshot, import_snapshot
    learning, source, target = prepared(client)
    snapshot = export_snapshot(learning, source, 'user-a')
    result = import_snapshot(learning, target, 'user-a', snapshot, {}, 'synthetic-share')
    again = import_snapshot(learning, target, 'user-a', snapshot, {}, 'synthetic-share')
    assert result['nodes'] == again['nodes']
    assert result['unavailable_evidence']
    with learning.db.connect() as db:
        node = result['nodes']['node-x']
        spec = json.loads(db.execute('SELECT content_json FROM teaching_specs WHERE node_id=?', (node,)).fetchone()[0])
        assert spec[0]['item_id'] == 'original-required'
        assert spec[0]['requirement'] == 'REQUIRED'
        assert spec[0]['evidence_ids'] == []
        assert db.execute('SELECT COUNT(*) FROM teaching_specs WHERE node_id=?', (result['nodes']['node-y'],)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM learning_journeys WHERE workspace_id=?', (target,)).fetchone()[0] == 0


def test_snapshot_export_requires_workspace_owner(client):
    from app.learning.snapshot_transfer import export_snapshot
    learning, source, _ = prepared(client)
    with pytest.raises(Exception) as error:
        export_snapshot(learning, source, 'user-b')
    assert getattr(error.value, 'status_code', getattr(error.value, 'status', None)) == 404


def test_snapshot_copies_exact_tree_order_and_prerequisites_atomically(client):
    from app.learning.snapshot_transfer import export_snapshot, import_snapshot
    from app.learning.models import PersonalPlanInput
    from app.learning.workspaces import workspace_for
    learning, source, target = prepared(client)
    with learning.db.connect() as db:
        db.execute("INSERT INTO teaching_specs SELECT 'node-y',version,content_json,content_hash FROM teaching_specs WHERE node_id='node-x'")
        learning.knowledge.create_personal_plan(db, workspace_for(learning.db, source, 'user-a'), PersonalPlanInput(
            operation_id='snapshot-plan', revision=0, title='Original tree', change_reason='Synthetic snapshot setup',
            memberships=[{'node_id': 'node-y', 'ordinal': 4, 'spec_version': 1}, {'node_id': 'node-x', 'ordinal': 7, 'spec_version': 1}],
            prerequisites=[{'node_id': 'node-x', 'prerequisite_node_id': 'node-y'}]))
    snapshot = export_snapshot(learning, source, 'user-a')
    result = import_snapshot(learning, target, 'user-a', snapshot, {}, 'tree-share')
    assert result['tree_status'] == 'ACTIVE'
    with learning.db.connect() as db:
        members = db.execute('SELECT node_id,ordinal FROM knowledge_tree_memberships WHERE tree_version_id=? ORDER BY ordinal', (result['tree_id'],)).fetchall()
        assert [(m['node_id'], m['ordinal']) for m in members] == [(result['nodes']['node-y'], 4), (result['nodes']['node-x'], 7)]
        edge = db.execute('SELECT node_id,prerequisite_node_id FROM knowledge_prerequisite_edges WHERE tree_version_id=?', (result['tree_id'],)).fetchone()
        assert tuple(edge) == (result['nodes']['node-x'], result['nodes']['node-y'])
    snapshot['tree']['memberships'][0]['spec_version'] = 99
    invalid = import_snapshot(learning, target, 'user-a', snapshot, {}, 'invalid-tree-share')
    assert invalid['tree_status'] == 'DRAFT'
    with learning.db.connect() as db:
        assert db.execute("SELECT id FROM knowledge_tree_versions WHERE workspace_id=? AND status='ACTIVE'", (target,)).fetchone()[0] == result['tree_id']


def test_snapshot_maps_only_authorized_destination_chunks_and_rolls_back_conflict(client):
    from app.learning.snapshot_transfer import export_snapshot, import_snapshot
    from app.learning.workspaces import workspace_for
    learning, source, target = prepared(client)
    scope = workspace_for(learning.db, target, 'user-a')
    uploaded = client.post(f"{UI}/courses/{scope['course_id']}/files", headers=auth('token-a'),
                           files={'file': ('notes.md', b'Transactions isolate concurrent writes and preserve consistency.', 'text/markdown')})
    assert uploaded.status_code == 201, uploaded.text
    with learning.db.connect() as db:
        chunk = db.execute('SELECT c.chunk_id FROM chunk_source_versions c JOIN document_versions d ON d.id=c.document_version_id WHERE d.course_id IN (?,?)', (scope['course_id'], scope['private_course_id'])).fetchone()
    assert chunk is not None, 'real local ingestion did not produce a destination chunk'
    snapshot = export_snapshot(learning, source, 'user-a')
    mapping = {'source-document': {'chunks': {'unavailable-source-chunk': chunk[0]}}}
    result = import_snapshot(learning, target, 'user-a', snapshot, mapping, 'mapped-share')
    assert result['unavailable_evidence'] == []
    with learning.db.connect() as db:
        content = json.loads(db.execute('SELECT content_json FROM teaching_specs WHERE node_id=?', (result['nodes']['node-x'],)).fetchone()[0])
    assert content[0]['evidence_ids'] == [chunk[0]]
    # A changed frozen payload must not rewrite existing specs or partially add nodes.
    snapshot['nodes'].insert(0, {**snapshot['nodes'][-1], 'id': 'new-node-before-conflict'})
    next(n for n in snapshot['nodes'] if n['id'] == 'node-x')['specs'][0]['content_json'] = json.dumps([
        {'item_id': 'changed', 'requirement': 'OPTIONAL', 'objective': 'Changed', 'acceptance': 'Changed', 'evidence_ids': []}])
    with pytest.raises(Exception) as error:
        import_snapshot(learning, target, 'user-a', snapshot, mapping, 'mapped-share')
    assert getattr(error.value, 'code', None) == 'SNAPSHOT_CHANGED'
    with learning.db.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM knowledge_nodes WHERE course_id=?', (scope['course_id'],)).fetchone()[0] == 2
