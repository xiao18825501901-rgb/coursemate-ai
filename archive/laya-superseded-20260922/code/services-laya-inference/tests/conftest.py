"""Shared test configuration and fixtures.

Makes the service package importable no matter where pytest is invoked from
(repo root or the service directory).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from app.definitions import DefinitionsRegistry  # noqa: E402
from app.settings import Settings  # noqa: E402

TRIAGE_QUESTIONS = {
    "department": {
        "type": "choice",
        "instructions": "Which department should handle this request?",
        "criteria": {"billing": "payments, refunds", "technical": "bugs, outages"},
    },
    "churn": {
        "type": "noul",
        "instructions": "Does the user threaten to cancel?",
    },
}


@pytest.fixture
def triage_registry() -> DefinitionsRegistry:
    return DefinitionsRegistry.from_dict(
        {
            "definitions": [
                {
                    "decision_definition_id": "course-triage",
                    "definition_version": "1",
                    "compiler_versions": ["1.0.0"],
                    "max_questions": 10,
                    "max_options_per_question": 20,
                    "questions": TRIAGE_QUESTIONS,
                }
            ]
        }
    )


@pytest.fixture
def fake_settings() -> Settings:
    return Settings(model_backend="fake", app_env="test")


@pytest.fixture
def authed_settings() -> Settings:
    return Settings(
        model_backend="fake",
        app_env="test",
        service_token="test-secret-token",
    )
