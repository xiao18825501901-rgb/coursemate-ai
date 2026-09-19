import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_current_change_features import UI, auth, client, make_course, wait_terminal


def exercise_setup(client):
    make_course(client)
    pair = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    response = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'), json={'pair_id': pair['id'], 'request_id': 'idempotency-exercise-setup'})
    assert response.status_code == 202, response.text
    wait_terminal(client, response.json()['id'])
    db = client.app.state.ui_extension_app.state.db
    row = db.one('SELECT * FROM cmui_exercises WHERE run=?', (response.json()['id'],))
    steps = json.loads(row['answer_steps'])
    steps.append({**steps[0], 'step_id': 'different-step'})
    db.execute('UPDATE cmui_exercises SET answer_steps=? WHERE id=?', (json.dumps(steps), row['id']))
    return db, row['id'], steps[0]['step_id']


def test_reveal_request_id_replay_conflicts_across_exercises(client):
    db, exercise, _ = exercise_setup(client)
    row = db.one('SELECT * FROM cmui_exercises WHERE id=?', (exercise,))
    row['id'] = 'other-exercise-idempotency'
    db.execute(f"INSERT INTO cmui_exercises({','.join(row)}) VALUES({','.join('?' for _ in row)})", tuple(row.values()))
    payload = {'request_id': 'same-reveal-request'}
    first = client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a'), json=payload)
    assert first.status_code == 200
    replay = client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a'), json=payload)
    assert replay.status_code == 200 and replay.json() == first.json()
    conflict = client.post(f"{UI}/exercises/{row['id']}/reveal", headers=auth('token-a'), json=payload)
    assert conflict.status_code == 409
    assert not db.one('SELECT * FROM cmui_answer_reveals WHERE exercise=?', (row['id'],))


def test_cached_explanation_records_new_request_id_payload_receipt(client):
    _, exercise, step = exercise_setup(client)
    assert client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a')).status_code == 200
    first = client.post(f'{UI}/exercises/{exercise}/steps/{step}/explanation', headers=auth('token-a'), json={'request_id': 'first-explanation-request'})
    assert first.status_code == 202, first.text
    wait_terminal(client, first.json()['run'])
    cached = client.post(f'{UI}/exercises/{exercise}/steps/{step}/explanation', headers=auth('token-a'), json={'request_id': 'cached-explanation-request'})
    assert cached.status_code == 202 and cached.json()['id'] == first.json()['id']
    conflict = client.post(f'{UI}/exercises/{exercise}/steps/different-step/explanation', headers=auth('token-a'), json={'request_id': 'cached-explanation-request'})
    assert conflict.status_code == 409


@pytest.mark.parametrize('same_request', [True, False])
def test_concurrent_explanation_creation_claims_one_run(client, monkeypatch, same_request):
    db, exercise, step = exercise_setup(client)
    assert client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a')).status_code == 200
    domain = client.app.state.ui_extension_app.state.domain
    original = domain.call
    lock = threading.Lock()
    count = 0
    both = threading.Event()

    async def synchronized(operation, *args, **kwargs):
        nonlocal count
        if operation == 'context.retrieve':
            with lock:
                count += 1
                if count == 2:
                    both.set()
            for _ in range(200):
                if both.is_set():
                    break
                await asyncio.sleep(.01)
            assert both.is_set(), 'requests did not overlap before claim'
        return await original(operation, *args, **kwargs)

    monkeypatch.setattr(domain, 'call', synchronized)
    def post(index):
        request_id='concurrent-explanation-request' if same_request else f'concurrent-explanation-request-{index}'
        return client.post(f'{UI}/exercises/{exercise}/steps/{step}/explanation', headers=auth('token-a'), json={'request_id': request_id})
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(post, range(2)))
    assert [response.status_code for response in responses] == [202, 202]
    assert responses[0].json()['run'] == responses[1].json()['run']
    wait_terminal(client, responses[0].json()['run'])
    assert len(db.all('SELECT id FROM cmui_step_explanations WHERE exercise=?', (exercise,))) == 1
    assert len(db.all("SELECT id FROM cmui_runs WHERE request_id LIKE 'concurrent-explanation-request%'")) == 1


def test_stale_explanation_failure_cannot_overwrite_current_retry(client, monkeypatch):
    db, exercise, step = exercise_setup(client)
    assert client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a')).status_code == 200
    entered = threading.Event()
    release = threading.Event()

    async def fails_after_retry(*args, **kwargs):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.005)
        raise RuntimeError('synthetic late failure')
        yield  # Make this an async upstream generator.

    monkeypatch.setattr(client.app.state.ui_extension_app.state.provider, 'generate_explanation', fails_after_retry)
    created = client.post(f'{UI}/exercises/{exercise}/steps/{step}/explanation', headers=auth('token-a'), json={'request_id': 'stale-failure-request'}).json()
    assert entered.wait(2)
    with db.connect(True) as c:
        # Model an already-rebound projection; the superseded worker can still
        # fail before seeing a cancellation signal.
        c.execute('INSERT INTO cmui_conversations(id,owner,course,lane,title,created_at,updated_at,hidden) VALUES(?,?,?,?,?,?,?,1)',
                  ('newer-retry-conversation', 'user-a', 'cs3481', 'problem', 'Newer retry', 'now', 'now'))
        c.execute('INSERT INTO cmui_runs(id,owner,conversation,request_id,status,user_text,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                  ('newer-retry-run', 'user-a', 'newer-retry-conversation', 'newer-retry-request', 'generating', 'Newer retry', 'now', 'now'))
        c.execute("UPDATE cmui_step_explanations SET run='newer-retry-run',status='generating',text='newer text' WHERE id=?", (created['id'],))
    release.set()
    # The old task emits its failure event before its guarded projection cleanup.
    for _ in range(200):
        if db.one("SELECT 1 FROM cmui_run_events WHERE run=? AND type='error'", (created['run'],)):
            break
        threading.Event().wait(.01)
    else:
        pytest.fail('old failure task did not finish')
    detail = db.one('SELECT run,status,text FROM cmui_step_explanations WHERE id=?', (created['id'],))
    assert detail == {'run': 'newer-retry-run', 'status': 'generating', 'text': 'newer text'}
    assert db.one('SELECT error FROM cmui_runs WHERE id=?', (created['run'],))['error'] == 'GENERATION_FAILED'
