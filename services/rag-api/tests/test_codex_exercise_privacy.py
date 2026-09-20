"""Exercise privacy at the real mounted V3 HTTP boundary; synthetic data only."""
import json

import pytest

from test_current_change_features import (
    UI, auth, client, collect_events, make_course, wait_terminal,
)
from app.cm_update.provider import TestProvider as LocalProvider

MARKER = '【标准答案】'
SECRET = 'ANSWER_CANARY_5'
QUESTION = 'Question: calculate 2 + 3.'
ANSWER = '## Step 1 Compute\n' + SECRET


def structured_payload(question=QUESTION, secret=SECRET):
    return json.dumps({
        'question': question,
        'answer_steps': [{'title': 'Compute', 'text': secret}],
        'references': [],
    }, ensure_ascii=False)


def test_structured_exercise_v2_is_private_persistent_and_source_labelled(client, monkeypatch):
    body = structured_payload()
    async def upstream(self, *args, **kwargs):
        for split in (body[:7], body[7:19], body[19:]):
            yield {'kind': 'delta', 'text': split}
        yield {'kind': 'complete', 'text': body}
    monkeypatch.setattr(LocalProvider, 'generate_exercise', upstream)
    make_course(client)
    pair = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    started = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                          json={'request_id': 'structured-v2-private'}).json()
    run = wait_terminal(client, started['id'])
    events = collect_events(client, started['id'])
    assert run['status'] == 'completed'
    assert SECRET not in json.dumps(events)
    assert SECRET not in json.dumps(run)
    history = client.get(f"{UI}/pairs/{pair['id']}", headers=auth('token-a')).json()
    message = next(message for message in history['problem']['messages'] if message['exercise'])
    assert message['exercise_state']['generation_version'] == 'exercise.v2'
    assert message['exercise_state']['source'] == 'generated'
    assert message['exercise_state']['revealed'] is False
    assert message['exercise_state']['steps'] == []
    exercise = message['exercise']
    revealed = client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a'))
    assert revealed.status_code == 200
    assert SECRET in revealed.text


@pytest.mark.parametrize('body', [
    '{"question":"valid but truncated",',
    json.dumps({'question': QUESTION, 'answer_steps': []}),
    json.dumps({'question': QUESTION, 'answer_steps': [{'title': '', 'text': SECRET}]}),
])
def test_invalid_structured_exercise_v2_fails_closed(client, monkeypatch, body):
    calls = 0
    async def upstream(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        yield {'kind': 'complete', 'text': body}
    monkeypatch.setattr(LocalProvider, 'generate_exercise', upstream)
    make_course(client)
    client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'})
    started = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                          json={'request_id': 'invalid-v2-' + str(abs(hash(body)))}).json()
    run = wait_terminal(client, started['id'])
    assert run['status'] == 'failed'
    assert calls == 1, 'invalid structured output must fail without a paid retry loop'
    assert run['partial_text'] == ''
    assert SECRET not in json.dumps(collect_events(client, started['id']))


@pytest.mark.parametrize('split', range(1, len(MARKER)))
def test_split_answer_marker_never_reaches_http(client, monkeypatch, split):
    async def upstream(self, *args, **kwargs):
        yield {'kind': 'delta', 'text': QUESTION + '\n' + MARKER[:split]}
        yield {'kind': 'delta', 'text': MARKER[split:] + ANSWER}
    monkeypatch.setattr(LocalProvider, 'generate_exercise', upstream)
    make_course(client)
    pair = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    result = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                         json={'request_id': f'split-marker-{split}'} )
    assert result.status_code == 202, result.text
    rid = result.json()['id']
    run = wait_terminal(client, rid)
    events = collect_events(client, rid)
    assert SECRET not in json.dumps(events), 'answer escaped through SSE replay'
    assert SECRET not in run['partial_text']
    assert run['status'] == 'completed', run
    history = client.get(f"{UI}/pairs/{pair['id']}", headers=auth('token-a')).json()
    assert SECRET not in json.dumps(history)
    exercise = next(d['exercise_id'] for k, d in events if k == 'done')
    revealed = client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a'))
    assert SECRET in revealed.text, 'answer must be saved, not discarded'


@pytest.mark.parametrize('body', [QUESTION + ANSWER, QUESTION + '【标准答案' + ANSWER,
                                QUESTION + MARKER + ANSWER + MARKER + 'extra'])
def test_ambiguous_exercise_output_fails_closed(client, monkeypatch, body):
    async def upstream(self, *args, **kwargs):
        for char in body:
            yield {'kind': 'delta', 'text': char}
    monkeypatch.setattr(LocalProvider, 'generate_exercise', upstream)
    make_course(client)
    client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'})
    result = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                         json={'request_id': 'malformed-marker-test'})
    assert result.status_code == 202, result.text
    rid = result.json()['id']
    run = wait_terminal(client, rid)
    assert SECRET not in json.dumps(collect_events(client, rid))
    assert run['partial_text'] == ''
    assert run['status'] == 'failed'


def test_explanation_cannot_reveal_hidden_answer(client):
    make_course(client)
    client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'})
    started = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                          json={'request_id': 'hidden-explanation-test'}).json()
    wait_terminal(client, started['id'])
    events = collect_events(client, started['id'])
    exercise = next(d['exercise_id'] for k, d in events if k == 'done')
    ui = next(r.app for r in client.app.routes if getattr(r, 'path', None) == '/ui-extension')
    row = ui.state.db.one('SELECT answer_steps FROM cmui_exercises WHERE id=?', (exercise,))
    step = json.loads(row['answer_steps'])[0]['step_id']
    response = client.post(f'{UI}/exercises/{exercise}/steps/{step}/explanation',
                           headers=auth('token-a'), json={'request_id': 'guess-hidden-step'})
    assert response.status_code == 403, response.text


def test_historical_plan_event_is_sanitized_on_replay(client):
    make_course(client)
    conv = client.post(f'{UI}/conversations', headers=auth('token-a'),
                      json={'course': 'cs3481', 'lane': 'teach'}).json()
    started = client.post(f"{UI}/conversations/{conv['id']}/runs", headers=auth('token-a'),
                          json={'text': 'Explain', 'request_id': 'historical-plan-test'}).json()
    wait_terminal(client, started['id'])
    ui = next(r.app for r in client.app.routes if getattr(r, 'path', None) == '/ui-extension')
    for kind, payload in [('prompt_ready', {'characters': 20, 'text': 'PRIVATE_PLAN_CANARY'}),
                          ('coverage', {'status': 'failed', 'error': {'debug': 'PRIVATE_PLAN_CANARY'}})]:
        ui.state.db.execute('INSERT INTO cmui_run_events(run,type,data) VALUES (?,?,?)',
                            (started['id'], kind, json.dumps(payload)))
    assert 'PRIVATE_PLAN_CANARY' not in json.dumps(collect_events(client, started['id']))


def test_old_exercise_partial_and_events_cannot_replay_answer(client):
    make_course(client)
    client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'})
    started = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                          json={'request_id': 'legacy-exercise-stream'}).json()
    wait_terminal(client, started['id'])
    ui = next(r.app for r in client.app.routes if getattr(r, 'path', None) == '/ui-extension')
    ui.state.db.execute('UPDATE cmui_runs SET partial_text=? WHERE id=?',
                        ('question ' + SECRET, started['id']))
    ui.state.db.execute('INSERT INTO cmui_run_events(run,type,data) VALUES (?,?,?)',
                        (started['id'], 'delta', json.dumps({'text': SECRET})))
    run = client.get(f"{UI}/runs/{started['id']}", headers=auth('token-a')).json()
    assert SECRET not in json.dumps(run)
    assert SECRET not in json.dumps(collect_events(client, started['id']))
