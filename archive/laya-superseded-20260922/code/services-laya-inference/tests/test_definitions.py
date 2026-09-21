"""Server-managed definition allowlist behaviour."""

from __future__ import annotations

from app.definitions import DefinitionsRegistry, validate_questions_against


def _registry() -> DefinitionsRegistry:
    return DefinitionsRegistry.from_dict(
        {
            "definitions": [
                {
                    "decision_definition_id": "course-triage",
                    "definition_version": "1",
                    "compiler_versions": ["1.0.0", "1.1.0"],
                    "max_questions": 10,
                    "max_options_per_question": 20,
                    "questions": {
                        "department": {
                            "type": "choice",
                            "instructions": "Which department?",
                            "criteria": {"billing": "payments", "technical": "bugs"},
                        },
                        "churn": {"type": "noul", "instructions": "cancel?"},
                    },
                }
            ]
        }
    )


def test_resolve_known_and_unknown() -> None:
    reg = _registry()
    assert reg.resolve("course-triage", "1") is not None
    assert reg.resolve("course-triage", "2") is None
    assert reg.resolve("nope", "1") is None


def test_empty_registry_fails_closed() -> None:
    reg = DefinitionsRegistry.empty()
    assert reg.resolve("anything", "1") is None


def test_missing_registry_file_fails_closed(tmp_path) -> None:
    reg = DefinitionsRegistry.from_json_file(tmp_path / "absent.json")
    assert len(reg) == 0


def test_valid_questions_match() -> None:
    reg = _registry()
    entry = reg.resolve("course-triage", "1")
    submitted = {
        "department": {
            "type": "choice",
            "instructions": "Which department?",
            "criteria": {"billing": "payments", "technical": "bugs"},
        },
        "churn": {"type": "noul", "instructions": "cancel?"},
    }
    assert validate_questions_against(entry, submitted) == []


def test_mismatched_instructions_rejected() -> None:
    reg = _registry()
    entry = reg.resolve("course-triage", "1")
    submitted = {
        "department": {
            "type": "choice",
            "instructions": "DIFFERENT",
            "criteria": {"billing": "payments", "technical": "bugs"},
        },
        "churn": {"type": "noul", "instructions": "cancel?"},
    }
    problems = validate_questions_against(entry, submitted)
    assert any("instructions mismatch" in p for p in problems)


def test_extra_question_rejected() -> None:
    reg = _registry()
    entry = reg.resolve("course-triage", "1")
    submitted = {
        "department": {
            "type": "choice",
            "instructions": "Which department?",
            "criteria": {"billing": "payments", "technical": "bugs"},
        },
        "churn": {"type": "noul", "instructions": "cancel?"},
        "extra": {"type": "noul", "instructions": "intruder"},
    }
    problems = validate_questions_against(entry, submitted)
    assert any("id set does not match" in p for p in problems)


def test_options_over_limit_rejected() -> None:
    reg = _registry()
    entry = reg.resolve("course-triage", "1")
    many = {f"k{i}": f"v{i}" for i in range(30)}
    submitted = {
        "department": {"type": "choice", "instructions": "Which department?", "criteria": many},
        "churn": {"type": "noul", "instructions": "cancel?"},
    }
    problems = validate_questions_against(entry, submitted)
    assert any("exceeds limit" in p for p in problems)


def test_choice_criteria_form_is_exact() -> None:
    # A list-of-labels submission must NOT match a dict-of-descriptions
    # canonical: different schema, different meaning.
    reg = _registry()
    entry = reg.resolve("course-triage", "1")
    submitted = {
        "department": {
            "type": "choice",
            "instructions": "Which department?",
            "criteria": ["billing", "technical"],
        },
        "churn": {"type": "noul", "instructions": "cancel?"},
    }
    problems = validate_questions_against(entry, submitted)
    assert any("criteria mismatch" in p for p in problems)


def test_choice_list_criteria_matches_list_canonical() -> None:
    reg = DefinitionsRegistry.from_dict(
        {
            "definitions": [
                {
                    "decision_definition_id": "d",
                    "definition_version": "1",
                    "questions": {
                        "q": {"type": "choice", "instructions": "pick", "criteria": ["a", "b"]}
                    },
                }
            ]
        }
    )
    entry = reg.resolve("d", "1")
    submitted = {"q": {"type": "choice", "instructions": "pick", "criteria": ["a", "b"]}}
    assert validate_questions_against(entry, submitted) == []
