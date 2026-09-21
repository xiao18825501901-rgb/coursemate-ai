"""Server-managed decision-definition allowlist.

A client (or a browser) must never be able to submit an arbitrary question
schema or an oversized judgment. The server holds the only source of truth: a
registry of ``(decision_definition_id, definition_version)`` -> canonical
question schema. Every incoming request is validated against that registry and
rejected with ``UNSUPPORTED_DEFINITION`` (unknown definition) or
``INVALID_REQUEST`` (known definition, mismatched schema).

The registry is read from a JSON file the owner manages (``LAYA_DEFINITIONS_PATH``).
Its shape is:

    {
      "definitions": [
        {
          "decision_definition_id": "course-triage",
          "definition_version": "1",
          "compiler_versions": ["1.0.0"],
          "max_questions": 10,
          "max_options_per_question": 20,
          "questions": {
            "department": {
              "type": "choice",
              "instructions": "Which department should handle this request?",
              "criteria": {"billing": "payments, refunds", "technical": "bugs"}
            }
          }
        }
      ]
    }

``compiler_versions`` is optional; when present the submitted ``compiler_version``
must be one of them. An absent/empty registry fails closed (everything unknown).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Global caps a definition entry may not exceed, independent of the settings
# caps (defense in depth: even a compromised registry file stays bounded).
_HARD_MAX_QUESTIONS = 100
_HARD_MAX_OPTIONS = 256


@dataclass(frozen=True)
class RegisteredDefinition:
    decision_definition_id: str
    definition_version: str
    compiler_versions: frozenset[str] = field(default_factory=frozenset)
    max_questions: int = 100
    max_options_per_question: int = 256
    questions: dict[str, Any] = field(default_factory=dict)


class DefinitionsRegistry:
    """Immutable, indexable registry of allowed decision definitions."""

    def __init__(self, definitions: list[RegisteredDefinition]) -> None:
        self._index: dict[tuple[str, str], RegisteredDefinition] = {
            (d.decision_definition_id, d.definition_version): d for d in definitions
        }

    def resolve(
        self, decision_definition_id: str, definition_version: str
    ) -> RegisteredDefinition | None:
        return self._index.get((decision_definition_id, definition_version))

    def __len__(self) -> int:
        return len(self._index)

    @classmethod
    def empty(cls) -> DefinitionsRegistry:
        return cls([])

    @classmethod
    def from_json_file(cls, path: Path | None) -> DefinitionsRegistry:
        if path is None or not Path(path).exists():
            return cls.empty()
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DefinitionsRegistry:
        definitions: list[RegisteredDefinition] = []
        for raw in payload.get("definitions", []):
            if not isinstance(raw, dict):
                continue
            qid = raw.get("decision_definition_id")
            ver = raw.get("definition_version")
            if not isinstance(qid, str) or not isinstance(ver, str) or not qid or not ver:
                continue
            questions = raw.get("questions", {})
            if not isinstance(questions, dict):
                questions = {}
            max_q = raw.get("max_questions", _HARD_MAX_QUESTIONS)
            max_o = raw.get("max_options_per_question", _HARD_MAX_OPTIONS)
            definitions.append(
                RegisteredDefinition(
                    decision_definition_id=qid,
                    definition_version=ver,
                    compiler_versions=frozenset(raw.get("compiler_versions", [])),
                    max_questions=int(min(max_q, _HARD_MAX_QUESTIONS)),
                    max_options_per_question=int(min(max_o, _HARD_MAX_OPTIONS)),
                    questions=questions,
                )
            )
        return cls(definitions)


def _normalise_criteria(criteria: Any) -> Any:
    """Criteria are compared in their canonical form (no silent coercion).

    The server registry is the source of truth; the compiler must submit the
    identical form. A list-of-labels and a dict-of-descriptions are different
    schemas and must not be conflated.
    """
    return criteria


def validate_questions_against(
    entry: RegisteredDefinition,
    submitted: dict[str, Any],
) -> list[str]:
    """Return a list of human-readable validation problems (empty == valid).

    ``submitted`` values are already Pydantic-parsed Question models; we compare
    their serialized form against the canonical schema so id/type/instructions/
    criteria must match exactly (key order irrelevant).
    """
    problems: list[str] = []
    canonical = entry.questions

    if len(submitted) > entry.max_questions:
        problems.append(f"too many questions (limit {entry.max_questions})")
    if len(submitted) != len(canonical):
        problems.append("question id set does not match the registered definition")
        return problems

    for qid, q in submitted.items():
        if qid not in canonical:
            problems.append(f"unknown question id {qid!r}")
            continue
        want = canonical[qid]
        if not isinstance(want, dict):
            problems.append(f"registered definition for {qid!r} is malformed")
            continue
        if q.get("type") != want.get("type"):
            problems.append(f"question {qid!r}: type mismatch")
        if q.get("instructions") != want.get("instructions"):
            problems.append(f"question {qid!r}: instructions mismatch")
        if _normalise_criteria(q.get("criteria")) != _normalise_criteria(want.get("criteria")):
            problems.append(f"question {qid!r}: criteria mismatch")

        # Cardinality guard per question, from the entry's option limit.
        criteria = q.get("criteria")
        opt_count = _option_count(q.get("type"), criteria)
        if opt_count > entry.max_options_per_question:
            problems.append(
                f"question {qid!r}: {opt_count} options exceeds "
                f"limit {entry.max_options_per_question}"
            )
    return problems


def _option_count(qtype: str, criteria: Any) -> int:
    if qtype == "choice":
        if isinstance(criteria, dict):
            return len(criteria)
        if isinstance(criteria, list):
            return len(criteria)
        return 0
    if qtype == "score":
        return len(criteria) if isinstance(criteria, list) else 0
    return 2  # noul is always [false, true]
