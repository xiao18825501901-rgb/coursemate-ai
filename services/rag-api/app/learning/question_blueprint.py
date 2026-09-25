"""The single-question blueprint: what one question is *for*, decided before it is written.

Stage 3 of the Question Engine (and stage 1's output) as a contract the rest of the pipeline can
check. The rule that shapes every field here: **a question is only as good as the objective it
serves and the evidence it may use**, so both are inputs to generation rather than things a
generated question is later judged against.

Three deliberate constraints, each of which the plan calls out:

* **Single question, not the five-slot blueprint.** The five-question assessment already has its own
  blueprints and grade policies in the assessment runtime; this object describes *one* item and is
  never a substitute for them. `exercise.v2` and `AssessmentService` are reused unchanged.
* **The three control dimensions stay separate.** `bloom_target` is the cognitive task,
  `target_difficulty` is the preset difficulty of the item, and the user's reasoning strength is an
  application setting that does not appear here at all. Remember is not "easy", Create is not
  "hard", and the most expensive setting does not mean the hardest question.
* **Nothing is invented about the learner.** `empirical_difficulty` exists and is pinned to `None`:
  with no independent attempts there is no measured difficulty, and the field's presence is a
  reminder that a preset difficulty is a target, not a measurement.

`extra="forbid"` comes from the shared `Contract`, which is what keeps a model from granting itself
an owner, an official verification level or a grade: those keys simply do not exist here.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Annotated, Final, Literal, cast

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.learning.models import Contract, Identifier, Text

SCHEMA_VERSION: Final = "question-blueprint.v1"

BloomTarget = Literal["REMEMBER", "UNDERSTAND", "APPLY", "ANALYZE", "EVALUATE", "CREATE"]

# Reused verbatim from the existing assessment vocabulary (migration 017), so a blueprint cannot
# introduce a question type the rest of the product has no column, rubric or renderer for.
QuestionType = Literal["MCQ_SINGLE", "NUMERIC", "SHORT_TEXT", "EXPLANATION", "CODE"]

AnswerForm = Literal["SINGLE_CHOICE", "NUMERIC_VALUE", "SHORT_ANSWER", "WORKED_STEPS", "CODE_BLOCK"]

# The type decides the form. A blueprint that asks for a numeric question but a short-answer form is
# internally contradictory, and catching it here is cheaper than catching it in a grader.
EXPECTED_FORM_BY_TYPE: Final[dict[str, str]] = {
    "MCQ_SINGLE": "SINGLE_CHOICE",
    "NUMERIC": "NUMERIC_VALUE",
    "SHORT_TEXT": "SHORT_ANSWER",
    "EXPLANATION": "WORKED_STEPS",
    "CODE": "CODE_BLOCK",
}

DifficultyFeature = Literal["STEPS", "CONCEPTS", "HINTS", "REPRESENTATION", "COMPUTATION"]

VisibilityPolicy = Literal["COURSE", "OWNER_ONLY", "SHARED_SNAPSHOT"]

AnswerPolicy = Literal["HIDDEN_UNTIL_REVEAL", "SOLUTION_ONLY"]

Hex64 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

# An objective must name an action a learner can perform, not a topic. This is a *heuristic* and is
# labelled as one: it refuses a bare noun ("DBSCAN") while accepting either language. It is
# deliberately not a model call — a rule answers this, so no Jev decision and no generation cost is
# spent on it.
OBSERVABLE_ACTION_MARKERS: Final[tuple[str, ...]] = (
    "compute", "calculate", "classify", "distinguish", "compare", "explain", "derive", "prove",
    "identify", "trace", "apply", "construct", "design", "find", "determine", "solve",
    "计算", "判断", "区分", "比较", "解释", "推导", "证明", "识别", "追踪", "应用", "构造", "设计",
    "给出", "求出", "说明", "分析",
)


def objective_is_observable(text: str) -> bool:
    """True when the objective names an action, rather than a topic or a noun phrase."""
    lowered = text.casefold()
    return any(marker in lowered for marker in OBSERVABLE_ACTION_MARKERS)


class SourceScopeEntry(Contract):
    """One piece of evidence the question may be built from, with its provenance.

    `content_hash` is the document version's own hash, so a blueprint can be shown to have been
    written against the material it cites — the plan's rule that a source snapshot is part of the
    question's identity rather than a footnote added afterwards.
    """

    document_id: Identifier
    version: int = Field(ge=1)
    locator: Annotated[str, StringConstraints(max_length=200)] = ""
    content_hash: Hex64


class QuestionBlueprint(Contract):
    schema_version: Literal["question-blueprint.v1"] = SCHEMA_VERSION
    blueprint_id: Identifier
    course_id: Identifier
    node_id: Identifier
    spec_version: int = Field(ge=1)
    spec_content_hash: Hex64
    objective_id: Identifier
    objective_text: Text
    source_scope: list[SourceScopeEntry] = Field(min_length=1)
    bloom_target: BloomTarget
    target_difficulty: int = Field(ge=1, le=5)
    difficulty_features: list[DifficultyFeature] = Field(min_length=1)
    # Present on purpose and pinned to None: no independent attempts have been measured, so no
    # empirical difficulty exists and a preset must not be presented as one.
    empirical_difficulty: None = None
    question_type: QuestionType
    expected_answer_form: AnswerForm
    marks: int = Field(ge=1, le=100)
    scoring_criteria: list[Text] = Field(min_length=1)
    assumptions: list[Text] = Field(default_factory=list)
    conditions: list[Text] = Field(default_factory=list)
    unit_conventions: list[Text] = Field(default_factory=list)
    misconception_targets: list[Text] = Field(default_factory=list)
    question_family_id: Identifier
    variant_seed: int | None = None
    visibility_policy: VisibilityPolicy = "COURSE"
    answer_policy: AnswerPolicy = "HIDDEN_UNTIL_REVEAL"
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    generation_policy_version: Identifier

    @field_validator("objective_text")
    @classmethod
    def observable_objective(cls, value: str) -> str:
        """Attach an invalid objective to its actual field, not the model root."""

        if not objective_is_observable(value):
            raise ValueError(
                "objective_text must name an observable action (e.g. compute, distinguish, 解释, "
                "判断, not a bare topic): " + value[:80]
            )
        return value

    @model_validator(mode="after")
    def checks(self) -> QuestionBlueprint:
        expected = EXPECTED_FORM_BY_TYPE[self.question_type]
        if self.expected_answer_form != expected:
            raise ValueError(
                f"question_type {self.question_type} requires expected_answer_form "
                f"{expected}, got {self.expected_answer_form}"
            )
        if self.question_type == "MCQ_SINGLE" and self.answer_policy == "SOLUTION_ONLY":
            raise ValueError("a single-choice question cannot be published solution-only")
        return self

    def identity(self) -> str:
        """Stable hash of the blueprint, so a generated question can name what it was built from."""
        canonical = json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class ObjectiveResolutionError(RuntimeError):
    """Raised when a node cannot yield an objective a question could be built for."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TeachingObjective:
    """The resolved target of one question: a real teaching item in a real, immutable spec."""

    node_id: str
    spec_version: int
    spec_content_hash: str
    item_id: str
    requirement: str
    objective: str
    acceptance: str
    evidence_ids: tuple[str, ...]


def resolve_objective(
    connection: sqlite3.Connection,
    *,
    node_id: str,
    spec_version: int | None = None,
    item_id: str | None = None,
    requirement: str = "REQUIRED",
) -> TeachingObjective:
    """Read the objective a question is for, from the rows that already define it.

    Target selection, in the plan's sense, ends here: either the caller names an item, or this
    returns the first item of the newest spec that meets `requirement` — never a node title, and
    never something invented. Every refusal carries a stable code so a caller can react to it:

    * `NO_TEACHING_SPEC` — the node has no spec at all (nothing to teach yet);
    * `NO_REQUIRED_ITEM` — the spec exists but declares no item of that requirement;
    * `OBJECTIVE_NOT_IN_SPEC` — the requested item is not part of that spec version.
    """
    if spec_version is None:
        row = connection.execute(
            "SELECT MAX(version) AS version FROM teaching_specs WHERE node_id = ?", (node_id,)
        ).fetchone()
        latest = row["version"] if row is not None else None
        if latest is None:
            raise ObjectiveResolutionError(
                "NO_TEACHING_SPEC", f"node {node_id!r} has no teaching specification"
            )
        spec_version = int(latest)

    spec = connection.execute(
        "SELECT content_hash FROM teaching_specs WHERE node_id = ? AND version = ?",
        (node_id, spec_version),
    ).fetchone()
    if spec is None:
        raise ObjectiveResolutionError(
            "NO_TEACHING_SPEC", f"node {node_id!r} has no specification version {spec_version}"
        )

    columns = "item_id, requirement, objective, acceptance, evidence_ids_json"
    if item_id is None:
        item = connection.execute(
            f"SELECT {columns} FROM teaching_items"
            " WHERE node_id = ? AND spec_version = ? AND requirement = ? ORDER BY ordinal LIMIT 1",
            (node_id, spec_version, requirement),
        ).fetchone()
        if item is None:
            raise ObjectiveResolutionError(
                "NO_REQUIRED_ITEM",
                f"node {node_id!r} spec {spec_version} declares no {requirement} teaching item",
            )
    else:
        item = connection.execute(
            f"SELECT {columns} FROM teaching_items"
            " WHERE node_id = ? AND spec_version = ? AND item_id = ?",
            (node_id, spec_version, item_id),
        ).fetchone()
        if item is None:
            raise ObjectiveResolutionError(
                "OBJECTIVE_NOT_IN_SPEC",
                f"teaching item {item_id!r} is not part of {node_id!r} spec {spec_version}",
            )

    evidence_ids: tuple[str, ...] = ()
    raw_ids = item["evidence_ids_json"]
    if raw_ids:
        parsed = json.loads(str(raw_ids))
        if isinstance(parsed, list):
            evidence_ids = tuple(str(value) for value in parsed)
    return TeachingObjective(
        node_id=node_id,
        spec_version=int(spec_version),
        spec_content_hash=str(spec["content_hash"]),
        item_id=str(item["item_id"]),
        requirement=str(item["requirement"]),
        objective=str(item["objective"]),
        acceptance=str(item["acceptance"]),
        evidence_ids=evidence_ids,
    )


def evidence_scope(
    connection: sqlite3.Connection, evidence_ids: tuple[str, ...]
) -> list[SourceScopeEntry]:
    """Resolve Teaching Item evidence chunk ids to their immutable source versions.

    The learning runtime stores chunk ids in ``TeachingItem.evidence_ids``.  Each chunk is bound to
    the exact ``document_versions`` row that produced it by ``chunk_source_versions``; using the
    newest version of a named document would silently move the blueprint to evidence it never
    cited.  Refuse rather than narrowing when any cited chunk has lost that binding.
    """
    entries: list[SourceScopeEntry] = []
    for evidence_id in evidence_ids:
        row = connection.execute(
            "SELECT version.document_id,version.version,version.sha256,"
            "chunk.locator_type,chunk.locator_value "
            "FROM chunks AS chunk JOIN chunk_source_versions AS source "
            "ON source.chunk_id=chunk.id JOIN document_versions AS version "
            "ON version.id=source.document_version_id WHERE chunk.id=?",
            (evidence_id,),
        ).fetchone()
        if row is None:
            raise ObjectiveResolutionError(
                "SOURCE_NOT_FOUND",
                f"evidence chunk {evidence_id!r} has no bound source version",
            )
        entries.append(
            SourceScopeEntry(
                document_id=cast(str, row["document_id"]),
                version=int(row["version"]),
                locator=f"{row['locator_type']}:{row['locator_value']}",
                content_hash=cast(str, row["sha256"]),
            )
        )
    return entries


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def is_hex64(value: str) -> bool:
    """Small helper for callers that hold a hash from elsewhere (a snapshot, a receipt)."""
    return bool(_HEX64.match(value))
