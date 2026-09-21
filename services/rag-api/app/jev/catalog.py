"""The 12 Jev decision definitions, loaded from an in-repo catalog copy.

``decision_catalog.json`` is the application-owned business spec — it is NOT a
TypeSafe API payload. Each definition is projected into a :class:`DecisionDefinition`
that exposes only the fields the gateway/service actually consume: the primitive
kind (Choice | Noul | Score), the authorized inputs, the criteria/score levels,
instructions, failure policy, and cache scope.

Thresholds stay centralized and are explicitly UNSET until the layer is
calibrated on labelled data. ``probability_is_grade`` is always False and the
default runtime mode is ``shadow`` so a Noul/Score probability can never be
mistaken for a mark or a mastery level.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("decision_catalog.json")


class Primitive:
    """The three TypeSafe question types (verified against docs.typesafe.ai)."""

    CHOICE = "Choice"
    NOUL = "Noul"
    SCORE = "Score"


PRIMITIVES = frozenset({Primitive.CHOICE, Primitive.NOUL, Primitive.SCORE})

# The catalog cache_scope entries map onto receipt columns for cache lookup.
_CACHE_SCOPE_COLUMNS: dict[str, tuple[str, ...]] = {
    "authorization_scope": ("owner_scope_hash",),
    "course": ("course_id",),
    "workspace": ("workspace_id",),
    "material_revision": ("material_revision",),
    "node_spec_version": ("node_id", "spec_version"),
    "question_definition_hash": ("question_hash",),
    "input_hash": ("input_hash",),
    "provider_model_version": ("model_version",),
}


@dataclass(frozen=True)
class DecisionDefinition:
    """One decision definition from the catalog."""

    key: str
    primitive: str
    required_state: tuple[str, ...]
    criteria: dict[str, str] | None
    instructions: str
    failure_policy: str
    cache_scope: tuple[str, ...]

    @property
    def score_levels(self) -> tuple[str, ...]:
        """Ordered Score level keys ("0".."n"), empty for Choice/Noul."""
        if self.primitive != Primitive.SCORE or not self.criteria:
            return ()
        return tuple(sorted(self.criteria, key=lambda level: int(level)))

    def cache_columns(self) -> tuple[str, ...]:
        """Receipt columns that participate in a cache key for this definition."""
        columns: list[str] = []
        for entry in self.cache_scope:
            columns.extend(_CACHE_SCOPE_COLUMNS.get(entry, ()))
        return tuple(dict.fromkeys(columns))


@dataclass(frozen=True)
class Catalog:
    """Immutable view over ``decision_catalog.json``."""

    version: str
    status: str
    probability_is_grade: bool
    default_runtime_mode: str
    thresholds: str
    definitions: dict[str, DecisionDefinition]

    def get(self, key: str) -> DecisionDefinition:
        try:
            return self.definitions[key]
        except KeyError:
            raise KeyError(f"Unknown Jev decision definition: {key}") from None

    def keys(self) -> tuple[str, ...]:
        return tuple(self.definitions)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Catalog":
        raw_path = Path(path) if path is not None else CATALOG_PATH
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        definitions: dict[str, DecisionDefinition] = {}
        for question in payload.get("questions", []):
            key = str(question["key"])
            primitive = str(question["primitive"])
            if primitive not in PRIMITIVES:
                raise ValueError(f"{key}: unknown primitive {primitive!r}")
            criteria = question.get("criteria")
            definitions[key] = DecisionDefinition(
                key=key,
                primitive=primitive,
                required_state=tuple(str(s) for s in question.get("required_state", [])),
                criteria={str(k): str(v) for k, v in criteria.items()} if criteria else None,
                instructions=str(question.get("instructions") or ""),
                failure_policy=str(question.get("failure_policy") or ""),
                cache_scope=tuple(str(s) for s in question.get("cache_scope", [])),
            )
        return cls(
            version=str(payload.get("version") or ""),
            status=str(payload.get("status") or ""),
            probability_is_grade=bool(payload.get("probability_is_grade", False)),
            default_runtime_mode=str(payload.get("default_runtime_mode") or "shadow"),
            thresholds=str(payload.get("thresholds") or "UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA"),
            definitions=definitions,
        )


_DEFAULT_CATALOG: Catalog | None = None


def load_catalog(path: Path | str | None = None) -> Catalog:
    """Return the (cached) catalog, optionally from an explicit path."""
    global _DEFAULT_CATALOG
    if path is None and _DEFAULT_CATALOG is not None:
        return _DEFAULT_CATALOG
    catalog = Catalog.load(path)
    if path is None:
        _DEFAULT_CATALOG = catalog
    return catalog


def definition(primitive: str, criteria: dict[str, Any] | None, instructions: str = "") -> dict[str, Any]:
    """Small helper used by tests to build a synthetic definition without JSON."""
    return {
        "key": "test.decision",
        "primitive": primitive,
        "required_state": [],
        "criteria": criteria,
        "instructions": instructions,
        "failure_policy": "deterministic",
        "cache_scope": ("authorization_scope", "course", "workspace", "material_revision",
                        "node_spec_version", "question_definition_hash", "input_hash",
                        "provider_model_version"),
    }
