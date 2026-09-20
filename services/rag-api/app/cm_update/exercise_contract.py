"""Versioned contracts for generated diagnostic exercises.

The owner-imported Word prompt remains the pedagogical source.  This module is
the runtime transport boundary: it separates the public question from the
private answer before anything is persisted or replayed to the browser.
"""
from __future__ import annotations

import hashlib
import json
import re

from .steps import answer_steps_parse

EXERCISE_VERSION_V2 = "exercise.v2"
EXERCISE_VERSION_V1 = "exercise.v1"
LEGACY_ANSWER_MARKER = "【标准答案】"

EXERCISE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "coursemate_exercise_v2",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "answer_steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "text": {"type": "string"},
                        },
                        "required": ["title", "text"],
                        "additionalProperties": False,
                    },
                },
                "references": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["question", "answer_steps", "references"],
            "additionalProperties": False,
        },
    },
}


class ExerciseContractError(ValueError):
    pass


def _stable_step(step: dict, ordinal: int) -> dict:
    title = step.get("title")
    text = step.get("text")
    if not isinstance(title, str) or not title.strip() or len(title) > 300:
        raise ExerciseContractError("INVALID_EXERCISE_ANSWER")
    if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
        raise ExerciseContractError("INVALID_EXERCISE_ANSWER")
    title, text = title.strip(), text.strip()
    anchor = hashlib.sha256(
        json.dumps([ordinal, title, text], ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return {"step_id": anchor, "ordinal": ordinal, "title": title, "text": text}


def parse_exercise_output(raw: str, allowed_references: set[str] | None = None) -> dict:
    """Validate V2 JSON, with a fail-closed parser for the old V1 delimiter.

    V1 support exists only for controlled legacy adapters and historical
    compatibility.  The live Qwen adapter always requests and records V2.
    """
    if not isinstance(raw, str) or len(raw) > 200_000:
        raise ExerciseContractError("EXERCISE_TOO_LARGE")
    value = raw.strip()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        if set(payload) != {"question", "answer_steps", "references"}:
            raise ExerciseContractError("INVALID_EXERCISE_SCHEMA")
        question = payload["question"]
        raw_steps = payload["answer_steps"]
        references = payload["references"]
        if not isinstance(question, str) or not 20 <= len(question.strip()) <= 30_000:
            raise ExerciseContractError("INVALID_EXERCISE_QUESTION")
        if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 20:
            raise ExerciseContractError("INVALID_EXERCISE_ANSWER")
        if not all(isinstance(item, dict) and set(item) == {"title", "text"} for item in raw_steps):
            raise ExerciseContractError("INVALID_EXERCISE_ANSWER")
        if not isinstance(references, list) or not all(
            isinstance(item, str) and re.fullmatch(r"S[1-9]\d*", item) for item in references
        ):
            raise ExerciseContractError("INVALID_EXERCISE_REFERENCES")
        if allowed_references is not None and not set(references).issubset(allowed_references):
            raise ExerciseContractError("INVALID_EXERCISE_REFERENCES")
        return {
            "version": EXERCISE_VERSION_V2,
            "question": question.strip(),
            "steps": [_stable_step(step, ordinal) for ordinal, step in enumerate(raw_steps, 1)],
            "references": list(dict.fromkeys(references)),
        }

    if value.count(LEGACY_ANSWER_MARKER) != 1:
        raise ExerciseContractError("INVALID_EXERCISE_BOUNDARY")
    question, answer = (part.strip() for part in value.split(LEGACY_ANSWER_MARKER, 1))
    steps = answer_steps_parse(answer)
    if not question or not answer:
        raise ExerciseContractError("EMPTY_EXERCISE")
    if not steps:
        raise ExerciseContractError("INVALID_EXERCISE_ANSWER")
    return {"version": EXERCISE_VERSION_V1, "question": question, "steps": steps, "references": []}
