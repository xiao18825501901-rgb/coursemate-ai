"""Cross-worker cancellation must close silent upstream generators, not just rows."""
import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from test_current_change_features import UI, auth, client, make_course, wait_terminal, FakeAuthVerifier, FakeEmbeddingProvider  # noqa: F401


@pytest.mark.parametrize('stage', ['exercise', 'explanation', 'explanation-general-cancel'])
def test_cross_worker_cancel_closes_silent_upstream(client, monkeypatch, stage):
    make_course(client)
    pair = client.post(f'{UI}/pairs', headers=auth('token-a'), json={'course': 'cs3481'}).json()
    entered = threading.Event(); closed = threading.Event()

    async def silent(*args, **kwargs):
        try:
            entered.set()
            await asyncio.Event().wait()
            yield {'kind': 'delta', 'text': 'unreachable'}
        finally:
            closed.set()

    provider = client.app.state.ui_extension_app.state.provider
    if stage == 'exercise':
        monkeypatch.setattr(provider, 'generate_exercise', silent)
        response = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                               json={'pair_id': pair['id'], 'request_id': 'silent-crossworker-exercise'})
        assert response.status_code == 202, response.text
        run_id = response.json()['id']
        cancel_path = f'{UI}/runs/{run_id}/cancel'
    else:
        response = client.post(f'{UI}/courses/cs3481/exercises', headers=auth('token-a'),
                               json={'pair_id': pair['id'], 'request_id': 'prepare-crossworker-exercise'})
        assert response.status_code == 202, response.text
        wait_terminal(client, response.json()['id'])
        db = client.app.state.ui_extension_app.state.db
        exercise = db.one('SELECT id FROM cmui_exercises WHERE run=?', (response.json()['id'],))['id']
        revealed = client.post(f'{UI}/exercises/{exercise}/reveal', headers=auth('token-a'), json={'request_id': 'prepare-crossworker-reveal'})
        assert revealed.status_code == 200, revealed.text
        step = revealed.json()['steps'][0]['step_id']
        monkeypatch.setattr(provider, 'generate_explanation', silent)
        response = client.post(f'{UI}/exercises/{exercise}/steps/{step}/explanation', headers=auth('token-a'), json={'request_id': 'silent-crossworker-explanation'})
        assert response.status_code == 202, response.text
        run_id = response.json()['run']; explanation_id = response.json()['id']
        cancel_path = f'{UI}/explanations/{explanation_id}/cancel'
        if stage == 'explanation-general-cancel':
            cancel_path = f'{UI}/runs/{run_id}/cancel'
    assert entered.wait(2), 'upstream generator never started'
    # A second application owns a distinct jobs map and cannot task.cancel the
    # first application's in-memory task. Only persisted cancellation is shared.
    sibling_app = create_app(settings=client.app.state.settings, embedding_provider=FakeEmbeddingProvider(), auth_verifier=FakeAuthVerifier())
    with TestClient(sibling_app) as sibling:
        cancelled = sibling.post(cancel_path, headers=auth('token-a'))
        assert cancelled.status_code == 200, cancelled.text
        assert closed.wait(4), 'terminal DB row alone is insufficient: silent upstream remained open'
        assert wait_terminal(client, run_id)['status'] == 'cancelled'
        if stage.startswith('explanation'):
            detail = client.get(f'{UI}/explanations/{explanation_id}', headers=auth('token-a')).json()
            assert detail['status'] == 'cancelled'
