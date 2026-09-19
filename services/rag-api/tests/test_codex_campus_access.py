import pytest
from test_current_change_features import UI, auth, client, make_course, wait_terminal


def test_campus_restriction_covers_existing_histories_and_original_api(client):
    make_course(client)
    conv = client.post(f'{UI}/conversations', headers=auth('token-a'),
                      json={'course': 'cs3481', 'lane': 'teach'}).json()
    run = client.post(f"{UI}/conversations/{conv['id']}/runs", headers=auth('token-a'),
                     json={'text': 'Explain', 'request_id': 'campus-boundary-run'}).json()
    wait_terminal(client, run['id'])
    ui = client.app.state.ui_extension_app
    ui.state.db.execute("UPDATE cmui_verification SET verified=0 WHERE owner='user-a'")
    paths = [f"{UI}/conversations/{conv['id']}",
             f'{UI}/pairs?course_id=cs3481',
             f"{UI}/runs/{run['id']}", f"{UI}/runs/{run['id']}/events",
             '/api/courses/cs3481/documents', f'{UI}/courses/cs3481/knowledge']
    results = {path: client.get(path, headers=auth('token-a')).status_code for path in paths}
    for path, code in results.items():
        assert code in (403, 404), (path,code)
    assert client.get(f'{UI}/courses', headers=auth('token-a')).status_code == 200
    assert client.get(f'{UI}/courses/cs3481', headers=auth('token-a')).status_code == 200
    private = client.post(f'{UI}/courses', headers=auth('token-a'), json={'name':'Private'}).json()
    assert client.get(f"{UI}/courses/{private['id']}/files", headers=auth('token-a')).status_code == 200


def test_revoked_historical_owner_cannot_read_or_write_campus_content_paths(client):
    make_course(client)
    uploaded = client.post(f'{UI}/courses/cs3481/files', headers=auth('token-a'), files={'file': ('scope.md', b'# Synthetic authorized notes\n\nTransactions preserve consistency across database operations.', 'text/markdown')})
    assert uploaded.status_code == 201, uploaded.text
    fid = uploaded.json()['id']
    workspace = client.post('/api/learning/workspaces', headers=auth('token-a'), json={'course_id': 'cs3481'})
    assert workspace.status_code == 200, workspace.text
    wid = workspace.json()['id']
    legacy = client.post('/api/conversations', headers=auth('token-a'), json={'course_id': 'cs3481'})
    assert legacy.status_code == 201, legacy.text
    legacy_id = legacy.json()['id']
    canary = 'SYNTHETIC-CAMPUS-ANSWER-CANARY'
    with client.app.state.qa_service.database.connect() as connection:
        connection.execute('INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)',
                           ('msg_campus_denied_canary', legacy_id, 'assistant', canary))
        connection.execute('UPDATE conversations SET title=? WHERE id=?', (canary, legacy_id))
    assert canary in client.get(f'/api/conversations/{legacy_id}', headers=auth('token-a')).text
    pair = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    run = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'), json={'pair_id': pair['id'], 'request_id': 'campus-exercise-setup'})
    assert run.status_code == 202, run.text
    wait_terminal(client, run.json()['id'])
    db = client.app.state.ui_extension_app.state.db
    exercise = db.one('SELECT id FROM cmui_exercises WHERE run=?', (run.json()['id'],))['id']
    revealed = client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a'), json={'request_id': 'campus-reveal-setup'})
    assert revealed.status_code == 200
    step = revealed.json()['steps'][0]['step_id']
    detail = client.post(f'{UI}/exercises/{exercise}/steps/{step}/explanation', headers=auth('token-a'), json={'request_id': 'campus-explain-setup'})
    assert detail.status_code == 202, detail.text
    wait_terminal(client, detail.json()['run'])
    explanation = detail.json()['id']
    db.execute("UPDATE cmui_verification SET verified=0 WHERE owner='user-a'")
    denied_detail = client.get(f'/api/conversations/{legacy_id}', headers=auth('token-a'))
    assert canary not in denied_detail.text, 'original V3 history leaked previously authorized campus answer'
    reads = [f'{UI}/courses/cs3481/files/{fid}/content', f'{UI}/courses/cs3481/files/{fid}/content?download=true',
             f'{UI}/courses/cs3481/files/{fid}/text', f'{UI}/courses/cs3481/comments',
             f'{UI}/courses/cs3481/knowledge/node-x/assessment', f'{UI}/courses/cs3481/bridges',
             f'{UI}/exercises/{exercise}', f'{UI}/explanations/{explanation}',
             f'/api/learning/workspaces/{wid}/documents', f'/api/learning/workspaces/{wid}/knowledge',
             f'/api/learning/workspaces/{wid}/events', f'/api/learning/workspaces/{wid}/state',
             '/api/conversations?courseId=cs3481', f'/api/conversations/{legacy_id}']
    results = [(path, client.get(path, headers=auth('token-a')).status_code) for path in reads]
    writes = [(f'{UI}/courses/cs3481/comments', {'text': 'blocked comment', 'request_id': 'campus-comment-denied'}),
              (f'{UI}/courses/cs3481/knowledge/node-x/assessment/session', {'request_id': 'campus-assessment-denied'}),
              (f'{UI}/courses/cs3481/exercises', {'pair_id': pair['id'], 'request_id': 'campus-exercise-denied'}),
              (f'{UI}/exercises/{exercise}/reveal', {'request_id': 'campus-reveal-denied'}),
              (f'{UI}/exercises/{exercise}/steps/{step}/explanation', {'request_id': 'campus-explain-denied'}),
              (f'{UI}/explanations/{explanation}/messages', {'text': 'blocked followup', 'request_id': 'campus-followup-denied'}),
              ('/api/qa/chat', {'course_id': 'cs3481', 'question': 'retrieve synthetic notes'}),
              ('/api/learning/workspaces', {'course_id': 'cs3481'})]
    results.extend((path, client.post(path, headers=auth('token-a'), json=payload).status_code) for path, payload in writes)
    assert all(code == 403 for _, code in results), [(path, code) for path, code in results if code != 403]
    unfiltered = client.get('/api/conversations', headers=auth('token-a'))
    assert unfiltered.status_code == 200
    assert canary not in unfiltered.text, 'unfiltered history leaked revoked campus conversation title'
    assert client.get(f'{UI}/courses/cs3481', headers=auth('token-a')).status_code == 200
    private = client.post(f'{UI}/courses', headers=auth('token-a'), json={'name': 'CS3481', 'code': 'CS3481'})
    assert private.status_code == 201
    own_id = private.json()['id']
    assert client.post(f'{UI}/courses/{own_id}/files', headers=auth('token-a'), files={'file': ('private.md', b'private content', 'text/markdown')}).status_code == 201
    assert client.post(f'{UI}/conversations', headers=auth('token-a'), json={'course': own_id, 'lane': 'teach'}).status_code == 201


@pytest.mark.parametrize('operation', ['rename', 'delete'])
def test_revoked_campus_actor_cannot_mutate_legacy_history(client, operation):
    make_course(client)
    created = client.post('/api/conversations', headers=auth('token-a'), json={'course_id': 'cs3481'})
    assert created.status_code == 201, created.text
    conversation_id = created.json()['id']
    original = client.get(f'/api/conversations/{conversation_id}', headers=auth('token-a')).json()
    client.app.state.ui_extension_app.state.db.execute("UPDATE cmui_verification SET verified=0 WHERE owner='user-a'")
    path = f'/api/conversations/{conversation_id}'
    if operation == 'rename':
        response = client.patch(path, headers=auth('token-a'), json={'title': 'Denied title mutation'})
    else:
        response = client.delete(path, headers=auth('token-a'))
    assert response.status_code == 403, response.text
    with client.app.state.qa_service.database.connect() as connection:
        persisted = connection.execute('SELECT title FROM conversations WHERE id=?', (conversation_id,)).fetchone()
    assert persisted is not None, 'denied delete removed historical data'
    assert persisted['title'] == original['title'], 'denied rename changed historical data'
