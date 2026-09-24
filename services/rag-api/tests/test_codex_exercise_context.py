from test_current_change_features import (
    UI, auth, client, make_course, seed_question_objective, wait_terminal,
)


def test_exercise_uses_explicit_pair_not_last_updated(client):
    make_course(client)
    with client.app.state.database.connect() as db:
        for node, title in [('current-node', 'Current topic'), ('recent-node', 'Other topic')]:
            db.execute("INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,major,kind,status) VALUES(?,'cs3481','user-a',?,'Definition evidence','CS','ATOMIC','PRIVATE')", (node, title))
    seed_question_objective(client, 'current-node', 'Current topic')
    seed_question_objective(client, 'recent-node', 'Other topic')
    pairs = []
    for node in ['current-node', 'recent-node']:
        pair = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
        response = client.post(f"{UI}/pairs/{pair['id']}/bind", headers=auth('token-a'), json={'node': node})
        assert response.status_code == 200, response.text
        pairs.append(pair['id'])
    response = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                           json={'pair_id': pairs[0], 'request_id': 'current-pair-exercise'})
    assert response.status_code == 202, response.text
    assert wait_terminal(client, response.json()['id'])['status'] == 'completed'
    ui_db = client.app.state.ui_extension_app.state.db
    exercise = ui_db.one('SELECT * FROM cmui_exercises WHERE run=?', (response.json()['id'],))
    assert exercise['node'] == 'current-node'
    with client.app.state.database.connect() as db:
        provenance = db.execute(
            'SELECT node_id FROM question_engine_provenance WHERE question_revision_id=?',
            (exercise['question_revision_id'],),
        ).fetchone()
    assert provenance['node_id'] == 'current-node'
    replay = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                         json={'pair_id': pairs[1], 'request_id': 'current-pair-exercise'})
    assert replay.status_code == 409
    assert ui_db.one('SELECT COUNT(*) AS n FROM cmui_exercises')['n'] == 1
    ambiguous = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                            json={'request_id': 'ambiguous-pair-exercise'})
    assert ambiguous.status_code == 409


def test_integrated_bind_rejects_invented_node(client):
    make_course(client)
    pair = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    response = client.post(f"{UI}/pairs/{pair['id']}/bind", headers=auth('token-a'),
                           json={'node': 'not-a-real-node'})
    assert response.status_code == 404, response.text
