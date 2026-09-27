import hashlib
import json
from datetime import UTC, datetime, timedelta

from test_current_change_features import (
    UI,
    auth,
    client as imported_client,
    make_course,
    wait_terminal,
)

# Re-export the imported pytest fixture so this module's tests can request it.
client = imported_client


def test_reopening_node_restores_one_pair_without_new_model_run(client):
    make_course(client)
    spec=json.dumps([{'item_id':'required-a','requirement':'REQUIRED','objective':'Explain node','acceptance':'Definition','evidence_ids':[]}])
    with client.app.state.database.connect() as db:
        db.execute('INSERT INTO teaching_specs(node_id,version,content_json,content_hash) VALUES(?,1,?,?)',
                   ('node-x',spec,hashlib.sha256(spec.encode()).hexdigest()))
    first=client.post(f'{UI}/courses/cs3481/nodes/node-x/open',headers=auth('token-a'),json={})
    assert first.status_code==200,first.text
    wait_terminal(client,first.json()['run'])
    again=client.post(f'{UI}/courses/cs3481/nodes/node-x/open',headers=auth('token-a'),json={})
    assert again.status_code==200,again.text
    assert again.json()['pair_id']==first.json()['pair_id']
    db=client.app.state.ui_extension_app.state.db
    assert len(db.all('SELECT id FROM cmui_runs WHERE owner=?',('user-a',)))==1
    assert db.one('SELECT teaching_mode FROM cmui_runs')['teaching_mode']=='thinking'


def test_compact_node_selects_one_primary_legacy_pair_without_merging_history(
    client, monkeypatch
):
    make_course(client)
    spec = json.dumps(
        [
            {
                'item_id': 'required-compact',
                'requirement': 'REQUIRED',
                'objective': 'Explain the compact unit',
                'acceptance': 'Explain the integrated method',
                'evidence_ids': [],
            }
        ]
    )
    with client.app.state.database.connect() as db:
        db.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,major,kind,status) "
            "VALUES('node-compact','cs3481','user-a','Compact unit','Integrated unit','CS','ATOMIC','PRIVATE')"
        )
        db.execute(
            'INSERT INTO teaching_specs(node_id,version,content_json,content_hash) VALUES(?,1,?,?)',
            ('node-compact', spec, hashlib.sha256(spec.encode()).hexdigest()),
        )

    ui_db = client.app.state.ui_extension_app.state.db
    older = datetime.now(UTC) - timedelta(minutes=5)
    newer = datetime.now(UTC) - timedelta(minutes=1)
    with ui_db.connect(True) as db:
        for pair_id, conversation_id, node_id, updated_at in (
            ('pair-old-a', 'conv-old-a', 'node-x', older.isoformat()),
            ('pair-old-b', 'conv-old-b', 'node-y', newer.isoformat()),
        ):
            db.execute(
                'INSERT INTO cmui_conversations(id,owner,course,lane,title,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?)',
                (conversation_id, 'user-a', 'cs3481', 'teach', pair_id, updated_at, updated_at),
            )
            db.execute(
                'INSERT INTO cmui_pairs(id,owner,course,teach_conversation,title,bound_node,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (pair_id, 'user-a', 'cs3481', conversation_id, pair_id, node_id, updated_at, updated_at),
            )

    domain = client.app.state.ui_extension_app.state.domain
    original_call = domain.call

    async def compact_tree(operation, subject, payload, authorization):
        if operation == 'knowledge.tree':
            return [
                {
                    'id': 'node-compact',
                    'title': 'Compact unit',
                    'kind': 'ATOMIC',
                    'legacy_node_ids': ['node-x', 'node-y'],
                }
            ]
        return await original_call(operation, subject, payload, authorization)

    monkeypatch.setattr(domain, 'call', compact_tree)
    opened = client.post(
        f'{UI}/courses/cs3481/nodes/node-compact/open', headers=auth('token-a'), json={}
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()['pair_id'] == 'pair-old-b'
    wait_terminal(client, opened.json()['run'])

    pairs = ui_db.all(
        'SELECT id,bound_node,teach_conversation FROM cmui_pairs WHERE owner=? AND course=? ORDER BY id',
        ('user-a', 'cs3481'),
    )
    assert pairs == [
        {'id': 'pair-old-a', 'bound_node': 'node-x', 'teach_conversation': 'conv-old-a'},
        {'id': 'pair-old-b', 'bound_node': 'node-compact', 'teach_conversation': 'conv-old-b'},
    ]
    links = ui_db.all(
        'SELECT legacy_node,pair,is_primary FROM cmui_compact_pair_links '
        'WHERE compact_node=? ORDER BY legacy_node',
        ('node-compact',),
    )
    assert links == [
        {'legacy_node': 'node-x', 'pair': 'pair-old-a', 'is_primary': 0},
        {'legacy_node': 'node-y', 'pair': 'pair-old-b', 'is_primary': 1},
    ]
