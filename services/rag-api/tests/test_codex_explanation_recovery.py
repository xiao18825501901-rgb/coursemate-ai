"""Recover persisted explanation state without starting or charging a provider."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from test_current_change_features import UI, auth, client, make_course, wait_terminal, FakeAuthVerifier, FakeEmbeddingProvider


def seed(client, run_status='generating', heartbeat='1', suffix='crashed'):
    make_course(client)
    pair = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    started = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'), json={'pair_id': pair['id'], 'request_id': 'prepare-recovery-exercise'}).json()
    wait_terminal(client, started['id'])
    db = client.app.state.ui_extension_app.state.db
    exercise = db.one('SELECT id FROM cmui_exercises WHERE run=?', (started['id'],))['id']
    conv = 'recovery-conversation-' + suffix
    run = 'recovery-run-' + suffix
    explanation = 'recovery-explanation-' + suffix
    stamp = '2026-09-19T00:00:00Z'
    with db.connect(True) as conn:
        conn.execute('INSERT INTO cmui_conversations(id,owner,course,lane,title,created_at,updated_at,hidden) VALUES(?,?,?,?,?,?,?,1)',
                     (conv, 'user-a', 'cs3481', 'problem', 'Recovery fixture', stamp, stamp))
        conn.execute('INSERT INTO cmui_runs(id,owner,conversation,request_id,status,user_text,lease_worker,lease_heartbeat,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (run, 'user-a', conv, run, run_status, 'Synthetic explanation', 'other-worker', heartbeat, stamp, stamp))
        conn.execute('INSERT INTO cmui_step_explanations(id,owner,exercise,step_id,answer_version,question,run,status,created_at,updated_at,conversation) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                     (explanation, 'user-a', exercise, 'step-1', 'V1', 'Synthetic question', run, 'generating', stamp, stamp, conv))
    return db, run, explanation


def test_startup_reclaimed_run_does_not_leave_explanation_generating(client):
    db, run, explanation = seed(client)
    sibling = create_app(settings=client.app.state.settings, embedding_provider=FakeEmbeddingProvider(), auth_verifier=FakeAuthVerifier())
    with TestClient(sibling):
        assert db.one('SELECT status FROM cmui_runs WHERE id=?', (run,))['status'] == 'failed'
        assert db.one('SELECT status FROM cmui_step_explanations WHERE id=?', (explanation,))['status'] == 'failed'


@pytest.mark.parametrize('state, heartbeat, expected', [
    ('generating', '9999999999', 'generating'),
    ('generating', '1', 'failed'),
    ('cancelled', '1', 'cancelled'),
    ('completed', '1', 'completed'),
    ('failed', '1', 'failed'),
])
def test_recovery_preserves_live_leases_and_reconciles_terminal_runs(client, state, heartbeat, expected):
    from app.cm_update.explanation_recovery import reclaim_and_reconcile
    db, run, explanation = seed(client, state, heartbeat)
    if expected == 'generating':
        # A retry replaced the previous failed run. Recovery must use the current
        # explanation.run pointer, not any older terminal run in its conversation.
        current = db.one('SELECT conversation FROM cmui_runs WHERE id=?', (run,))
        db.execute('INSERT INTO cmui_runs(id,owner,conversation,request_id,status,user_text,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                   ('previous-failed-run', 'user-a', current['conversation'], 'previous-failed-request', 'failed', 'Previous attempt', 'old', 'old'))
    reclaim_and_reconcile(db, now_epoch=1000, lease_grace_seconds=120, updated_at='recovery-test')
    assert db.one('SELECT status FROM cmui_runs WHERE id=?', (run,))['status'] == expected
    assert db.one('SELECT status FROM cmui_step_explanations WHERE id=?', (explanation,))['status'] == expected
    before = db.one('SELECT updated_at FROM cmui_step_explanations WHERE id=?', (explanation,))
    reclaim_and_reconcile(db, now_epoch=1000, lease_grace_seconds=120, updated_at='retry')
    assert db.one('SELECT updated_at FROM cmui_step_explanations WHERE id=?', (explanation,)) == before
