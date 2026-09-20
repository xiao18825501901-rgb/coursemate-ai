"""Regression contracts for the four current product changes.

These use the integrated deterministic provider fixture; they do not claim a
live Qwen call or a production deployment.
"""
from fastapi.testclient import TestClient

from test_current_change_features import UI, auth, client, make_course


def test_retired_cross_pane_actions_preserve_read_only_history_surface(client: TestClient) -> None:
    make_course(client)
    create = client.post(
        f"{UI}/courses/cs3481/bridges", headers=auth("token-a"),
        json={"problem_message": "message-historic", "step": 1,
              "question": "为什么这样做？", "node": "node-x"},
    )
    assert create.status_code == 410
    assert create.json()["detail"]["code"] == "CROSS_PANE_ACTION_RETIRED"

    returned = client.patch(f"{UI}/bridges/bridge-historic/return", headers=auth("token-a"))
    assert returned.status_code == 410
    assert client.get(f"{UI}/courses/cs3481/bridges", headers=auth("token-a")).status_code == 200


def test_layout_strengths_are_independent_and_theme_is_server_persisted(client: TestClient) -> None:
    make_course(client)
    saved = client.put(
        f"{UI}/courses/cs3481/layout", headers=auth("token-a"),
        json={"ratio": 0.5, "teach_strength": "high", "problem_strength": "max"},
    )
    assert saved.status_code == 200, saved.text
    restored = client.get(f"{UI}/courses/cs3481/layout", headers=auth("token-a")).json()
    assert restored["teach_strength"] == "high"
    assert restored["problem_strength"] == "max"

    assert client.get(f"{UI}/me/preferences", headers=auth("token-a")).json()["theme"] == "light"
    changed = client.put(f"{UI}/me/preferences", headers=auth("token-a"), json={"theme": "dark"})
    assert changed.status_code == 200 and changed.json()["theme"] == "dark"
    assert client.get(f"{UI}/me/preferences", headers=auth("token-a")).json()["theme"] == "dark"
    assert client.get(f"{UI}/me/preferences", headers=auth("token-b")).json()["theme"] == "light"


def test_next_run_receives_and_persists_the_selected_reasoning_strength(client: TestClient) -> None:
    make_course(client)
    conversation = client.post(
        f"{UI}/conversations", headers=auth("token-a"),
        json={"course": "cs3481", "lane": "problem"},
    )
    assert conversation.status_code == 201, conversation.text

    started = client.post(
        f"{UI}/conversations/{conversation.json()['id']}/runs", headers=auth("token-a"),
        json={"text": "请完整解题", "request_id": "strength-contract-0001",
              "reasoning_strength": "high"},
    )
    assert started.status_code == 202, started.text
    assert started.json()["reasoning_strength"] == "high"
    # The deterministic fixture has no synthetic Qwen price; it must not
    # masquerade as a configured dollar baseline.
    assert started.json()["application_budget_usd"] is None

    restored = client.get(f"{UI}/runs/{started.json()['id']}", headers=auth("token-a"))
    assert restored.status_code == 200, restored.text
    assert restored.json()["reasoning_strength"] == "high"
