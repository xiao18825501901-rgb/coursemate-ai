import hashlib
import json
from test_current_change_features import UI, auth, client, make_course, wait_terminal


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
