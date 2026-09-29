"""The student-visible task contract, and the bounded profiles that can certify it.

The previous design asked a reviewer whether a question was under-specified.  That
question is not answerable from the stem alone, because "under-specified" means
"something the answer depends on is not visible to the student", and nothing in
the pipeline recorded what *was* visible.  So the judgement drifted: reviewers
listed conventions a competent reader supplies, the same item passed in one run
and failed in the next, and the measured precision/recall frontier held no point
that was both safe and usable.

This module puts the missing fact in the pipeline.  A task contract states, in
typed form, every element the answer turns on and the role each element plays:

* GIVEN               -- a real premise of the exercise
* EXERCISE_ASSUMPTION -- a convention the exercise stipulates; public, and never
                         in conflict with the course material
* SOURCE_RULE         -- a rule that must be traceable to a supplied source span
* CLAIM_TO_CRITIQUE   -- a statement the student is asked to judge; it is *not* a
                         premise, so its being wrong never makes the item
                         self-contradictory

Those are not labels a model may apply freely: the roles decide what the server
checks.  A SOURCE_RULE without a span id is refused.  A CLAIM_TO_CRITIQUE is
excluded from the premise set by construction.  And the projection the student
sees is *rendered from the contract*, so a condition cannot exist in a private
rubric and be invisible in the stem.

Completeness is then a positive, per-profile statement rather than a reviewer
opinion.  A profile names the roles, conventions and checks that make an item of
that shape answerable; an item outside every registered profile is NOT_SUPPORTED
and stays under review, which is the correct outcome for a shape nobody has
qualified.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from app.learning.models import Contract, Identifier

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.learning.question_blueprint import QuestionBlueprint as QuestionBlueprintLike

SCHEMA_VERSION: Final = "student-visible-task.v1"
PROJECTION_VERSION: Final = "public-projection.v1"
COMPLETENESS_VERSION: Final = "task-completeness.v1"

TaskRole = Literal[
    "GIVEN",
    "EXERCISE_ASSUMPTION",
    "SOURCE_RULE",
    "CLAIM_TO_CRITIQUE",
]
FactOrigin = Literal["PROBLEM_DATA", "COURSE_SOURCE", "EXERCISE_CONVENTION"]
Equivalence = Literal[
    "EXACT",
    "NUMERIC_TOLERANCE",
    "SET_UNORDERED",
    "BAG_UNORDERED",
    "ORDERED_LIST",
    "SEMANTIC_RUBRIC",
]
ConventionKey = Literal[
    "DIALECT",
    "DATA_COMPLETENESS",
    "NULL_SEMANTICS",
    "DUPLICATE_ROWS",
    "ROW_ORDER",
    "ROUNDING",
    "UNITS",
    "BOUNDARY_INCLUSION",
    "SELF_INCLUSION",
    "ANSWER_FORM",
]

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
Hex64 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

ROLE_PREMISE: Final[frozenset[str]] = frozenset({"GIVEN", "EXERCISE_ASSUMPTION", "SOURCE_RULE"})
ROLE_NOT_A_PREMISE: Final[frozenset[str]] = frozenset({"CLAIM_TO_CRITIQUE"})


class TaskSpecError(RuntimeError):
    """A task contract could not be built.  The code names the failing fact."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TaskFact(Contract):
    """One element of the task, with the role it plays for the student."""

    fact_id: Identifier
    role: TaskRole
    origin: FactOrigin
    statement: ShortText
    source_span_id: Identifier | None = None

    @model_validator(mode="after")
    def the_role_decides_what_is_required(self) -> TaskFact:
        if self.role == "SOURCE_RULE" and not self.source_span_id:
            raise ValueError("a source rule must name the span that states it")
        if self.origin == "COURSE_SOURCE" and not self.source_span_id:
            raise ValueError("a course-sourced fact must name its span")
        return self

    @property
    def is_premise(self) -> bool:
        """A claim the student is asked to critique is never a premise."""
        return self.role in ROLE_PREMISE


class TaskConvention(Contract):
    key: ConventionKey
    statement: ShortText


class StudentVisibleTaskSpec(Contract):
    """Everything the answer turns on, in a form the server can check and render."""

    schema_version: Literal["student-visible-task.v1"] = SCHEMA_VERSION
    spec_id: Identifier
    spec_version: int = Field(ge=1)
    question_revision_hash: Hex64
    objective_id: Identifier
    question_type: Literal["MCQ_SINGLE", "NUMERIC", "SHORT_TEXT", "EXPLANATION", "CODE"]
    marks: float = Field(gt=0, le=100)
    bloom_target: Literal["REMEMBER", "UNDERSTAND", "APPLY", "ANALYZE", "EVALUATE", "CREATE"]
    task_boundary: ShortText
    facts: list[TaskFact] = Field(min_length=1, max_length=40)
    conventions: list[TaskConvention] = Field(default_factory=list, max_length=20)
    answer_equivalence: Equivalence
    equivalence_note: ShortText | None = None
    profile_id: str | None = Field(default=None, max_length=60)
    profile_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def the_contract_is_internally_consistent(self) -> StudentVisibleTaskSpec:
        ids = [fact.fact_id for fact in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("fact ids must be unique within a task contract")
        keys = [convention.key for convention in self.conventions]
        if len(keys) != len(set(keys)):
            raise ValueError("a convention may be stated once")
        if self.answer_equivalence == "SEMANTIC_RUBRIC" and not self.equivalence_note:
            raise ValueError("a rubric equivalence must say what it accepts")
        return self

    def premises(self) -> list[TaskFact]:
        return [fact for fact in self.facts if fact.is_premise]

    def claims_to_critique(self) -> list[TaskFact]:
        return [fact for fact in self.facts if not fact.is_premise]

    def convention_keys(self) -> frozenset[str]:
        return frozenset(convention.key for convention in self.conventions)


class TaskContractDraft(Contract):
    """What the author proposes about the task; the server owns the identity.

    A draft has no revision hash and no projection: those are computed after the
    candidate revision is known, so a model can never name the item it will be
    attached to.
    """

    task_boundary: ShortText
    facts: list[TaskFact] = Field(min_length=1, max_length=40)
    conventions: list[TaskConvention] = Field(default_factory=list, max_length=20)
    answer_equivalence: Equivalence
    equivalence_note: ShortText | None = None
    profile_id: str | None = Field(default=None, max_length=60)
    profile_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> TaskContractDraft:
        ids = [fact.fact_id for fact in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("fact ids must be unique within a task contract")
        keys = [convention.key for convention in self.conventions]
        if len(keys) != len(set(keys)):
            raise ValueError("a convention may be stated once")
        return self


class PublicProjection(Contract):
    """The exact text the student sees, rendered from the contract by the server.

    The digest is what a qualification, a receipt or a review may cite.  Two items
    with the same digest showed the student the same conditions, and an item whose
    contract changed cannot keep an older digest.
    """

    schema_version: Literal["public-projection.v1"] = PROJECTION_VERSION
    question_revision_hash: Hex64
    task_boundary: ShortText
    premises: list[str] = Field(default_factory=list, max_length=40)
    claims_to_critique: list[str] = Field(default_factory=list, max_length=20)
    conventions: list[str] = Field(default_factory=list, max_length=20)
    answer_equivalence: Equivalence
    text: ShortText
    text_digest: Hex64
    renderer_version: str = PROJECTION_VERSION


def build_task_spec(
    draft: TaskContractDraft,
    *,
    blueprint: QuestionBlueprintLike,
    question_revision_hash: str,
) -> StudentVisibleTaskSpec:
    """Bind an author's draft to the server-owned facts of the item.

    The blueprint decides the parts a model must not be able to rewrite: the
    objective, the question type, the marks and the cognitive task.  A draft that
    names a profile this server has not registered is refused rather than
    reconciled, so an unqualified shape cannot describe itself as covered.
    """
    if draft.profile_id is not None and profile_by_id(
        draft.profile_id, version=draft.profile_version
    ) is None:
        raise TaskSpecError(
            "TASK_PROFILE_UNREGISTERED",
            "The contract names a profile this server has not registered.",
        )
    return StudentVisibleTaskSpec(
        spec_id=f"taskspec-{question_revision_hash[:24]}",
        spec_version=1,
        question_revision_hash=question_revision_hash,
        objective_id=blueprint.objective_id,
        question_type=blueprint.question_type,
        marks=blueprint.marks,
        bloom_target=blueprint.bloom_target,
        task_boundary=draft.task_boundary,
        facts=list(draft.facts),
        conventions=list(draft.conventions),
        answer_equivalence=draft.answer_equivalence,
        equivalence_note=draft.equivalence_note,
        profile_id=draft.profile_id,
        profile_version=draft.profile_version,
    )


def condition_facts(*, conditions: list[str], source_span_ids: list[str]) -> list[TaskFact]:
    """Turn the blueprint's server-authored conditions into GIVEN facts.

    The blueprint is server-authored and already part of the revision identity, so
    its conditions are premises the author cannot leave out of the projection.  A
    condition that names exactly one supplied span is bound to that span.
    """
    facts: list[TaskFact] = []
    for index, condition in enumerate(conditions, start=1):
        bound = next((span for span in source_span_ids if span and span in condition), None)
        facts.append(
            TaskFact(
                fact_id=f"blueprint-condition-{index}",
                role="GIVEN",
                origin="PROBLEM_DATA",
                statement=condition,
                source_span_id=bound,
            )
        )
    return facts


_PREMISE_PREFIX: Final[dict[str, str]] = {
    "GIVEN": "Given:",
    "EXERCISE_ASSUMPTION": "For this exercise:",
    "SOURCE_RULE": "Course rule:",
}
_CLAIM_HEADING: Final = (
    "Statement to evaluate (it is the subject of the task, not a premise the task accepts):"
)


def render_public_projection(spec: StudentVisibleTaskSpec) -> PublicProjection:
    """Render the student-facing condition block from the typed contract.

    Every premise and every convention appears, in a fixed order, under a label
    that says what role it plays.  A statement the student is asked to critique is
    rendered separately and labelled as such, so it cannot be read as a premise.
    Nothing is dropped and nothing is added: the renderer has no way to express a
    condition the contract does not contain.
    """
    premises: list[str] = []
    for role in ("GIVEN", "EXERCISE_ASSUMPTION", "SOURCE_RULE"):
        for fact in spec.facts:
            if fact.role == role:
                premises.append(f"{_PREMISE_PREFIX[role]} {fact.statement}")
    claims = [fact.statement for fact in spec.claims_to_critique()]
    conventions = [f"{item.key}: {item.statement}" for item in spec.conventions]

    blocks: list[str] = [spec.task_boundary]
    if premises:
        blocks.append("\n".join(premises))
    if conventions:
        blocks.append("\n".join(conventions))
    if claims:
        blocks.append(_CLAIM_HEADING + "\n" + "\n".join(claims))
    text = "\n\n".join(block for block in blocks if block.strip()).strip()
    return PublicProjection(
        question_revision_hash=spec.question_revision_hash,
        task_boundary=spec.task_boundary,
        premises=premises,
        claims_to_critique=claims,
        conventions=conventions,
        answer_equivalence=spec.answer_equivalence,
        text=text,
        text_digest=sha256(text.encode()).hexdigest(),
        renderer_version=PROJECTION_VERSION,
    )


# --------------------------------------------------------------------------- profiles


@dataclass(frozen=True)
class TaskProfile:
    """A shape of task whose completeness the server can certify positively.

    A profile is a *registration*, not a model claim.  It names the question types
    it covers, the fact roles that must be present, the conventions that must be
    stated, and the checker and renderer versions the certificate is bound to.
    Anything outside every profile returns NOT_SUPPORTED, and NOT_SUPPORTED is
    never a pass.
    """

    profile_id: str
    version: int
    description: str
    question_types: frozenset[str]
    required_roles: frozenset[str]
    required_conventions: tuple[str, ...]
    renderer_version: str
    checker: str
    languages: frozenset[str]


P_SQL: Final = TaskProfile(
    profile_id="P-SQL",
    version=1,
    description=(
        "A relational task over a schema and rows stated in the item, under a "
        "declared dialect, with the equivalence of two results declared."
    ),
    question_types=frozenset({"MCQ_SINGLE", "SHORT_TEXT", "CODE", "EXPLANATION"}),
    required_roles=frozenset({"GIVEN"}),
    required_conventions=("DIALECT", "DATA_COMPLETENESS", "DUPLICATE_ROWS", "ROW_ORDER"),
    renderer_version=PROJECTION_VERSION,
    checker="sql_oracle.v1",
    languages=frozenset({"en", "zh", "mixed"}),
)

P_DISCRETE: Final = TaskProfile(
    profile_id="P-DISCRETE",
    version=1,
    description=(
        "A finite graph, counting or clustering task over data given in the item, "
        "with its boundary and self-inclusion conventions stated."
    ),
    question_types=frozenset({"NUMERIC", "SHORT_TEXT", "EXPLANATION", "MCQ_SINGLE"}),
    required_roles=frozenset({"GIVEN"}),
    required_conventions=("DATA_COMPLETENESS", "BOUNDARY_INCLUSION"),
    renderer_version=PROJECTION_VERSION,
    checker="bounded_discrete.v1",
    languages=frozenset({"en", "zh", "mixed"}),
)

P_COURSE_RULE: Final = TaskProfile(
    profile_id="P-COURSE-RULE",
    version=1,
    description=(
        "A task whose answer is decided by a rule stated in a supplied source span, "
        "with the claim under evaluation marked as such."
    ),
    question_types=frozenset({"EXPLANATION", "SHORT_TEXT", "MCQ_SINGLE"}),
    required_roles=frozenset({"SOURCE_RULE", "CLAIM_TO_CRITIQUE"}),
    required_conventions=("ANSWER_FORM",),
    renderer_version=PROJECTION_VERSION,
    checker="source_span_binding.v1",
    languages=frozenset({"en", "zh", "mixed"}),
)

REGISTERED_PROFILES: Final[tuple[TaskProfile, ...]] = (P_SQL, P_DISCRETE, P_COURSE_RULE)


def profile_by_id(profile_id: str, *, version: int | None = None) -> TaskProfile | None:
    for profile in REGISTERED_PROFILES:
        if profile.profile_id == profile_id and (version is None or profile.version == version):
            return profile
    return None


class CompletenessCheck(Contract):
    name: str = Field(min_length=1, max_length=80)
    status: Literal["PASS", "FAIL"]
    detail: ShortText


class CompletenessEvidence(Contract):
    """Positive evidence that an item is answerable within a registered profile.

    This is the certificate the ambiguity gate may accept *instead of* a hunt for a
    counterexample.  It is issued by code, bound to the profile, the renderer and
    the public projection digest, and it says NOT_SUPPORTED rather than guessing
    when the item is outside every registered shape.  It is deliberately not a
    model-produced boolean: no field here can be set by a reviewer.
    """

    schema_version: Literal["task-completeness.v1"] = COMPLETENESS_VERSION
    status: Literal["COMPLETE_FOR_REGISTERED_PROFILE", "INCOMPLETE", "NOT_SUPPORTED"]
    profile_id: str | None = None
    profile_version: int | None = None
    renderer_version: str
    checker: str | None = None
    projection_digest: Hex64
    question_revision_hash: Hex64
    required_conventions: list[str] = Field(default_factory=list, max_length=20)
    checks: list[CompletenessCheck] = Field(default_factory=list, max_length=24)

    @property
    def certifies(self) -> bool:
        return self.status == "COMPLETE_FOR_REGISTERED_PROFILE"

    def identity(self) -> str:
        payload = {
            "status": self.status,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "renderer_version": self.renderer_version,
            "checker": self.checker,
            "projection_digest": self.projection_digest,
            "question_revision_hash": self.question_revision_hash,
            "required_conventions": sorted(self.required_conventions),
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def _check(name: str, passed: bool, detail: str) -> CompletenessCheck:
    return CompletenessCheck(name=name, status="PASS" if passed else "FAIL", detail=detail)


def certify_completeness(
    spec: StudentVisibleTaskSpec,
    *,
    projection: PublicProjection,
    available_span_ids: Iterable[str],
    reviewable_language: str = "en",
) -> CompletenessEvidence:
    """Decide, from the contract alone, whether a registered profile covers it.

    Every check is a fact about the contract or about the frozen evidence.  A
    failing check is recorded by name; the caller reports the certificate as it
    stands and never upgrades an INCOMPLETE or NOT_SUPPORTED result.
    """
    profile = (
        profile_by_id(spec.profile_id or "", version=spec.profile_version)
        if spec.profile_id
        else None
    )
    checks: list[CompletenessCheck] = []
    if profile is None:
        return CompletenessEvidence(
            status="NOT_SUPPORTED",
            renderer_version=PROJECTION_VERSION,
            projection_digest=projection.text_digest,
            question_revision_hash=spec.question_revision_hash,
            checks=[
                _check(
                    "registered_profile",
                    False,
                    "the item names no registered profile version",
                )
            ],
        )

    checks.append(
        _check(
            "question_type_in_profile",
            spec.question_type in profile.question_types,
            f"profile {profile.profile_id} covers {sorted(profile.question_types)}",
        )
    )
    present_roles = frozenset(fact.role for fact in spec.facts)
    for role in sorted(profile.required_roles):
        checks.append(
            _check(
                f"role_present:{role}",
                role in present_roles,
                f"the contract must state at least one {role}",
            )
        )
    stated = spec.convention_keys()
    for key in profile.required_conventions:
        checks.append(
            _check(
                f"convention_stated:{key}",
                key in stated,
                f"an item of this shape must state the {key} convention",
            )
        )
    span_ids = set(available_span_ids)
    dangling = sorted(
        fact.fact_id
        for fact in spec.facts
        if fact.source_span_id and fact.source_span_id not in span_ids
    )
    checks.append(
        _check(
            "source_spans_exist",
            not dangling,
            "every cited span id is present in the frozen evidence pack"
            if not dangling
            else f"unknown span ids on: {dangling}",
        )
    )
    missing_from_projection = [
        fact.fact_id for fact in spec.premises() if fact.statement not in projection.text
    ]
    checks.append(
        _check(
            "premises_are_student_visible",
            not missing_from_projection,
            "every premise is rendered into the public projection"
            if not missing_from_projection
            else f"premises missing from the projection: {missing_from_projection}",
        )
    )
    checks.append(
        _check(
            "projection_matches_contract",
            projection.question_revision_hash == spec.question_revision_hash
            and projection.renderer_version == profile.renderer_version,
            "the projection was rendered from this contract by the registered renderer",
        )
    )
    checks.append(
        _check(
            "language_in_profile",
            reviewable_language in profile.languages,
            f"profile {profile.profile_id} is qualified for {sorted(profile.languages)}",
        )
    )
    failed = [check.name for check in checks if check.status == "FAIL"]
    return CompletenessEvidence(
        status="COMPLETE_FOR_REGISTERED_PROFILE" if not failed else "INCOMPLETE",
        profile_id=profile.profile_id,
        profile_version=profile.version,
        renderer_version=projection.renderer_version,
        checker=profile.checker,
        projection_digest=projection.text_digest,
        question_revision_hash=spec.question_revision_hash,
        required_conventions=list(profile.required_conventions),
        checks=checks,
    )
