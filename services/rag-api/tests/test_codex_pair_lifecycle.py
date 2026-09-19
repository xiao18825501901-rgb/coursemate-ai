"""Independent real-mounted API regressions for R08 and R13, no paid calls."""
import asyncio
import hashlib
import json
import threading

from test_current_change_features import UI, auth, client, make_course, wait_terminal  # noqa: F401


def test_legacy_lane_creation_does_not_merge_unrelated_histories(client):
    make_course(client)
    teach = client.post(f'{UI}/conversations', headers=auth('token-a'),
                        json={'course': 'cs3481', 'lane': 'teach', 'title': 'Independent teaching'})
    problem = client.post(f'{UI}/conversations', headers=auth('token-a'),
                          json={'course': 'cs3481', 'lane': 'problem', 'title': 'Independent problem'})
    assert teach.status_code == problem.status_code == 201
    pairs = client.get(f'{UI}/pairs', headers=auth('token-a'), params={'course_id': 'cs3481'}).json()
    assert len(pairs) == 2, 'legacy creates without an explicit pairing must remain separate single-lane histories'
    assert all(not (p['teach_conversation'] and p['problem_conversation']) for p in pairs)


def test_explicit_pair_lane_creation_targets_requested_pair_without_overwrite(client):
    make_course(client)
    pair_a = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    pair_b = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    created = client.post(f'{UI}/conversations', headers=auth('token-a'),
                          json={'course': 'cs3481', 'lane': 'teach', 'pair_id': pair_a['id']})
    assert created.status_code == 201, created.text
    a = client.get(f"{UI}/pairs/{pair_a['id']}", headers=auth('token-a')).json()
    b = client.get(f"{UI}/pairs/{pair_b['id']}", headers=auth('token-a')).json()
    assert a['teach']['conversation']['id'] == created.json()['id'] and b['teach'] is None
    again = client.post(f'{UI}/conversations', headers=auth('token-a'),
                        json={'course': 'cs3481', 'lane': 'teach', 'pair_id': pair_a['id']})
    assert again.status_code in (200, 201, 409), again.text
    restored = client.get(f"{UI}/pairs/{pair_a['id']}", headers=auth('token-a')).json()
    assert restored['teach']['conversation']['id'] == created.json()['id'], 'a second request must reuse or conflict, never overwrite the lane'


def test_prebound_first_node_teaching_forces_thinking_once(client):
    make_course(client)
    spec = json.dumps([{'item_id': 'required-a', 'requirement': 'REQUIRED', 'objective': 'Explain synthetic node', 'acceptance': 'Explain definition', 'evidence_ids': []}])
    with client.app.state.database.connect() as db:
        db.execute('INSERT INTO teaching_specs(node_id,version,content_json,content_hash) VALUES(?,1,?,?)',
                   ('node-x', spec, hashlib.sha256(spec.encode()).hexdigest()))
    conv = client.post(f'{UI}/conversations', headers=auth('token-a'), json={'course': 'cs3481', 'lane': 'teach'}).json()
    pair = client.get(f'{UI}/pairs', headers=auth('token-a'), params={'course_id': 'cs3481'}).json()[0]
    bound = client.post(f"{UI}/pairs/{pair['id']}/bind", headers=auth('token-a'), json={'node': 'node-x'})
    assert bound.status_code == 200, bound.text
    started = client.post(f"{UI}/conversations/{conv['id']}/runs", headers=auth('token-a'),
                          json={'text': 'Start this node', 'node_id': 'node-x', 'request_id': 'first-node-once', 'teaching_mode': 'normal'})
    assert started.status_code == 202, started.text
    wait_terminal(client, started.json()['id'])
    ui_db = client.app.state.ui_extension_app.state.db
    assert ui_db.one('SELECT teaching_mode FROM cmui_runs WHERE id=?', (started.json()['id'],))['teaching_mode'] == 'thinking', 'prebinding in the UI must not consume the first-teaching claim'
    replay = client.post(f"{UI}/conversations/{conv['id']}/runs", headers=auth('token-a'),
                         json={'text': 'Start this node', 'node_id': 'node-x', 'request_id': 'first-node-once', 'teaching_mode': 'normal'})
    assert replay.status_code == 202 and replay.json()['id'] == started.json()['id']
    later = client.post(f"{UI}/conversations/{conv['id']}/runs", headers=auth('token-a'),
                        json={'text': 'A short follow-up', 'node_id': 'node-x', 'request_id': 'node-followup-01', 'teaching_mode': 'normal'})
    assert later.status_code == 202, later.text
    wait_terminal(client, later.json()['id'])
    assert ui_db.one('SELECT teaching_mode FROM cmui_runs WHERE id=?', (later.json()['id'],))['teaching_mode'] == 'normal'


def test_cancel_silent_explanation_persists_terminal_window_status(client, monkeypatch):
    make_course(client)
    pair = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    started = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                          json={'request_id': 'cancel-exercise-01', 'pair_id': pair['id']})
    assert started.status_code == 202, started.text
    wait_terminal(client, started.json()['id'])
    ui_db = client.app.state.ui_extension_app.state.db
    exercise = ui_db.one('SELECT id FROM cmui_exercises WHERE run=?', (started.json()['id'],))['id']
    reveal = client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a'), json={'request_id': 'cancel-reveal-01'})
    assert reveal.status_code == 200, reveal.text
    step = reveal.json()['steps'][0]['step_id']
    entered = threading.Event()

    async def silent(*args, **kwargs):
        entered.set()
        await asyncio.sleep(30)
        yield {'kind': 'delta', 'text': 'must not complete after cancellation'}

    monkeypatch.setattr(client.app.state.ui_extension_app.state.provider, 'generate_explanation', silent)
    explanation = client.post(f'{UI}/exercises/{exercise}/steps/{step}/explanation', headers=auth('token-a'),
                              json={'request_id': 'silent-explanation-01'})
    assert explanation.status_code == 202, explanation.text
    assert entered.wait(2), 'controlled silent provider was not entered'
    data = explanation.json()
    cancelled = client.post(f"{UI}/explanations/{data['id']}/cancel", headers=auth('token-a'))
    assert cancelled.status_code == 200, cancelled.text
    assert wait_terminal(client, data['run'])['status'] == 'cancelled'
    restored = client.get(f"{UI}/explanations/{data['id']}", headers=auth('token-a'))
    assert restored.status_code == 200, restored.text
    assert restored.json()['status'] in ('cancelled', 'failed'), 'restored explanation must not remain generating forever'
