"""Question Engine stage 4: one evidence-bound author call and a private candidate answer.

The provider sees only the server-authored blueprint and the Stage-2 evidence pack.  The model
cannot choose ownership, verification, publication or grades, and its answer is kept behind an
explicit private boundary.  This module does not persist or publish a candidate; Stage 7 owns the
READY transaction after independent solve and validation.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import Field, StringConstraints, model_validator

from app.errors import ApiError
from app.learning.models import Contract, Identifier, Text
from app.learning.provider import (
    ProviderCallFailure,
    schema_error_summary,
    structured_input_hash,
)
from app.learning.question_blueprint import Hex64, QuestionBlueprint
from app.learning.question_evidence import QuestionEvidencePack
from app.learning.task_spec import (
    REGISTERED_PROFILES,
    StudentVisibleTaskSpec,
    TaskContractDraft,
    TaskSpecError,
    build_task_spec,
)

QUESTION_AUTHOR_PROMPT_VERSION: Final = "question-author.v5"
QUESTION_AUTHOR_SCHEMA_VERSION: Final = "question-author-output.v4"
RULE_VIOLATION_POLICY_VERSION: Final = "question-rule-violation-policy-v1"
PROMPT_PATH: Final = Path(__file__).with_name("prompts") / "question_author_v5.md"

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def point_marks_basis_points(value: Any) -> int:
    """Return an exact 1..10000 basis-point mark value for a dynamic item."""

    if type(value) not in (int, float):
        raise ValueError("Point marks must be a numeric basis-point value")
    scaled = Decimal(str(value)) * 100
    if (
        not scaled.is_finite()
        or scaled != scaled.to_integral_value()
        or not 1 <= scaled <= 10_000
    ):
        raise ValueError("Point marks must exactly represent 1 to 10000 basis points")
    return int(scaled)


class AuthorGenerationError(RuntimeError):
    """Stable Stage-4 refusal that never echoes provider bodies or private answer text."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        provider_run: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider_run = provider_run


class AuthorSolutionStep(Contract):
    ordinal: int = Field(ge=1, le=12)
    operation: Text
    result: Text
    explanation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=20, max_length=6000)
    ]
    source_refs: list[Identifier] = Field(min_length=1, max_length=20)


class DistractorRationale(Contract):
    """Private, evidence-bound explanation of why one MCQ option is wrong."""

    option_index: int = Field(ge=0, le=9)
    misconception: Text
    explanation: Text
    source_refs: list[Identifier] = Field(min_length=1, max_length=20)


class RuleViolationAnalysis(Contract):
    """Private proof that a rule-violation question uses a real course rule.

    The quotation is optional, for the same reason a reviewer citation is: the
    reviewer selects the span and the server owns the text.  Requiring a
    character-exact transcription of a long rule rejected four of seventy item
    slots in one bounded evaluation -- every one of them a complete, otherwise
    usable paid response -- and the rule the field was there to prove is that the
    cited span really states the rule, which the span binding establishes on its
    own.  A quotation that *is* supplied must still match the frozen text exactly.
    """

    proposed_statement: Text
    rule_source_ref: Identifier
    rule_quote: Text | None = None
    correction: Text
    explanation: Text


class QuestionAuthorOutput(Contract):
    """The model-authored fields; everything authoritative remains in the blueprint."""

    schema_version: Literal["question-author-output.v4"] = QUESTION_AUTHOR_SCHEMA_VERSION
    question_text: Text
    options: list[ShortText] = Field(default_factory=list, max_length=10)
    candidate_answer: Text = Field(repr=False)
    correct_option_index: int | None = Field(default=None, ge=0, le=9)
    distractor_rationales: list[DistractorRationale] = Field(default_factory=list, max_length=9)
    rule_violation_analysis: RuleViolationAnalysis | None = None
    solution_steps: list[AuthorSolutionStep] = Field(min_length=1, max_length=12, repr=False)
    source_refs: list[Identifier] = Field(min_length=1, max_length=20)
    # The author's statement of what the learner can see.  Optional so a stored
    # row written before this field existed still validates and still reproduces
    # its own revision identity; the identity function drops the key when it is
    # absent rather than hashing a null the old payload never had.
    #
    # Held as a plain mapping here and validated separately, because a contract
    # that does not satisfy its own schema is a diagnosable fact about the
    # contract.  Validating it inline would collapse that into a blanket
    # "the author output was invalid" and make the failure impossible to attribute
    # -- which is exactly what happened on the first live run.
    task_contract: dict[str, Any] | None = None

    @model_validator(mode="after")
    def consecutive_steps_and_unique_sources(self) -> QuestionAuthorOutput:
        if [step.ordinal for step in self.solution_steps] != list(
            range(1, len(self.solution_steps) + 1)
        ):
            raise ValueError("solution step ordinals must be consecutive from one")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("question source references must be unique")
        return self


def _revision_payload(output: QuestionAuthorOutput) -> dict[str, Any]:
    """The exact author output that the revision identity covers.

    `task_contract` is excluded, and the boundary is deliberate rather than
    convenient.  The revision identity is what a stored blind solve, receipt and
    provenance row are keyed on; adding a key to it would change the identity of
    every future item and could not be reproduced for the rows already stored,
    which carry no contract at all.

    The contract is instead bound to the item by its own digest: the completeness
    certificate and every hybrid receipt record the public projection digest
    together with the revision hash, so a contract changed under a fixed revision
    invalidates the evidence that cited it instead of quietly continuing to
    describe a different question.  What this does not claim is that a contract
    change alone forces a new revision -- a changed stem or condition does, because
    those are in the identity, and an unchanged stem with a changed contract loses
    the certificate that named it.
    """
    payload = output.model_dump(mode="json")
    payload.pop("task_contract", None)
    return payload


def _question_revision_identity(
    *,
    blueprint_hash: str,
    evidence_pack_hash: str,
    output: QuestionAuthorOutput,
    schema_version: str | None = None,
) -> str:
    """Hash one author output, optionally as an earlier schema version wrote it.

    `schema_version` is an author-output field and therefore part of the hashed
    payload.  Recomputing a *stored* revision with today's constant would compare
    two different payloads and refuse every row authored before a schema bump --
    which is what happened: every stored revision was written under
    `question-author-output.v3` while this code defines `.v4`, so no historical
    candidate could be rebuilt.  Reproducing a row means hashing what that row was
    actually hashed from.
    """
    author_output = _revision_payload(output)
    if schema_version is not None:
        author_output["schema_version"] = schema_version
    revision_payload = {
        "blueprint_hash": blueprint_hash,
        "evidence_pack_hash": evidence_pack_hash,
        "author_output": author_output,
    }
    return hashlib.sha256(
        json.dumps(
            revision_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class PublicAuthoredQuestion(Contract):
    schema_version: Literal["exercise.v2"] = "exercise.v2"
    question_text: Text
    options: list[ShortText] = Field(default_factory=list, max_length=10)
    source_refs: list[Identifier] = Field(min_length=1, max_length=20)
    answer_policy: Literal["HIDDEN_UNTIL_REVEAL", "SOLUTION_ONLY"]


class PrivateCandidateSolution(Contract):
    schema_version: Literal["question-private-solution.v1"] = "question-private-solution.v1"
    candidate_answer: Text = Field(repr=False)
    correct_option_index: int | None = Field(default=None, ge=0, le=9)
    distractor_rationales: list[DistractorRationale] = Field(default_factory=list, max_length=9)
    rule_violation_analysis: RuleViolationAnalysis | None = None
    solution_steps: list[AuthorSolutionStep] = Field(min_length=1, max_length=12, repr=False)
    source_refs: list[Identifier] = Field(min_length=1, max_length=20)


class AuthorProviderRun(Contract):
    model: ShortText
    provider: ShortText
    protocol: ShortText
    region: ShortText
    role: Literal["QUESTION_AUTHOR"]
    template_version: Literal[
        "question-author.v1",
    "question-author.v2",
    "question-author.v3",
    "question-author.v4",
    "question-author.v5",
    ]
    schema_version: Literal[
        "question-author-output.v1",
        "question-author-output.v2",
        "question-author-output.v3",
        "question-author-output.v4",
    ]
    input_hash: Hex64
    started_at: ShortText
    finished_at: ShortText
    latency_ms: int = Field(ge=0)
    # Additive: the phase budgets this call was allowed to use.  Absent on
    # records written before the policy existed, so a stored run still
    # validates; present, it says what connect, read, write and pool were.
    timeouts: dict[str, float] | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    provider_response_id: ShortText | None = None
    status: Literal["COMPLETED"]
    error_class: None = None

    @model_validator(mode="after")
    def deepseek_or_labelled_fixture_only(self) -> AuthorProviderRun:
        fixture = (
            self.model == "FAKE_TEST_ONLY"
            and self.provider == "deterministic"
            and self.protocol == "fixture"
            and self.region == "LOCAL_TEST"
        )
        deepseek = (
            self.model == "deepseek-flash"
            and self.provider == "DEEPSEEK_API"
            and self.protocol == "responses"
            and self.region == "ENDPOINT_DEEPSEEK"
        )
        if not (fixture or deepseek):
            raise ValueError("question author receipts must be DeepSeek or labelled test fixtures")
        return self


class AuthoredQuestionCandidate(Contract):
    schema_version: Literal["authored-question-candidate.v1"] = "authored-question-candidate.v1"
    blueprint_id: Identifier
    blueprint_hash: Hex64
    evidence_pack_hash: Hex64
    question_revision: Hex64
    course_id: Identifier
    node_id: Identifier
    objective_id: Identifier
    question_type: Literal["MCQ_SINGLE", "NUMERIC", "SHORT_TEXT", "EXPLANATION", "CODE"]
    marks: int = Field(ge=1, le=100)
    public_question: PublicAuthoredQuestion
    private_solution: PrivateCandidateSolution = Field(repr=False)
    provider_run: AuthorProviderRun
    # The author's student-visible task contract, when it produced one.  It is not
    # part of the revision identity (see _revision_payload); it is what lets the
    # completeness gate make a positive decision instead of asking a reviewer to
    # guess what the learner can see.
    task_contract: TaskContractDraft | None = None

    def task_spec(self, blueprint: QuestionBlueprint) -> StudentVisibleTaskSpec | None:
        """The server-owned contract for this candidate, or None when it has none."""
        if self.task_contract is None:
            return None
        return build_task_spec(
            self.task_contract,
            blueprint=blueprint,
            question_revision_hash=self.question_revision,
        )

    def revision_identity(self, *, schema_version: str | None = None) -> str:
        """Recompute the immutable revision from the split public/private candidate.

        `schema_version` defaults to the schema this code authors under.  A caller
        reproducing a stored row passes the version recorded on that row instead,
        because the version is inside the hashed payload and the two differ across
        a schema bump.
        """
        if self.public_question.source_refs != self.private_solution.source_refs:
            raise ValueError("public and private candidate source references do not match")
        output = QuestionAuthorOutput(
            question_text=self.public_question.question_text,
            options=self.public_question.options,
            candidate_answer=self.private_solution.candidate_answer,
            correct_option_index=self.private_solution.correct_option_index,
            distractor_rationales=self.private_solution.distractor_rationales,
            rule_violation_analysis=self.private_solution.rule_violation_analysis,
            solution_steps=self.private_solution.solution_steps,
            source_refs=self.public_question.source_refs,
        )
        return _question_revision_identity(
            blueprint_hash=self.blueprint_hash,
            evidence_pack_hash=self.evidence_pack_hash,
            output=output,
            schema_version=schema_version,
        )

    def public_payload(self) -> dict[str, object]:
        """The only candidate representation allowed across the public exercise boundary."""
        return {
            "schema_version": self.public_question.schema_version,
            "blueprint_id": self.blueprint_id,
            "question_revision": self.question_revision,
            "question_type": self.question_type,
            "marks": self.marks,
            **self.public_question.model_dump(mode="json", exclude={"schema_version"}),
        }


class AuthorProvider(Protocol):
    def generate(
        self,
        schema: type[QuestionAuthorOutput],
        *,
        instructions: str,
        context: dict[str, Any],
        role: str,
        template_version: str,
        schema_version: str,
    ) -> tuple[QuestionAuthorOutput, dict[str, Any]]: ...


def _assert_inputs_match(blueprint: QuestionBlueprint, evidence: QuestionEvidencePack) -> None:
    actual_prompt = blueprint.prompt_versions.get("question_author")
    same_identity = (
        blueprint.course_id == evidence.course_id
        and blueprint.node_id == evidence.node_id
        and blueprint.spec_version == evidence.spec_version
        and blueprint.spec_content_hash == evidence.spec_content_hash
        and blueprint.objective_id == evidence.objective_id
        and blueprint.objective_text == evidence.objective_text
        and blueprint.source_scope == evidence.source_scope()
        and actual_prompt == QUESTION_AUTHOR_PROMPT_VERSION
    )
    if not same_identity:
        raise AuthorGenerationError(
            "AUTHOR_INPUT_MISMATCH",
            "The blueprint, evidence pack, or author prompt revision does not match.",
        )


def _assert_output_scope(
    output: QuestionAuthorOutput,
    *,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
) -> None:
    allowed = set(evidence.evidence_ids)
    used = set(output.source_refs)
    used.update(ref for step in output.solution_steps for ref in step.source_refs)
    used.update(ref for item in output.distractor_rationales for ref in item.source_refs)
    if output.rule_violation_analysis is not None:
        used.add(output.rule_violation_analysis.rule_source_ref)
    if not used.issubset(allowed):
        raise AuthorGenerationError(
            "AUTHOR_OUTPUT_OUT_OF_SCOPE",
            "The author output cites evidence outside the objective-scoped pack.",
        )
    if blueprint.question_type == "MCQ_SINGLE":
        correct = output.correct_option_index
        expected_distractors = (
            set(range(len(output.options))) - {correct} if correct is not None else set()
        )
        actual_distractors = [item.option_index for item in output.distractor_rationales]
        if (
            len(output.options) < 2
            or correct is None
            or correct >= len(output.options)
            or len(set(actual_distractors)) != len(actual_distractors)
            or set(actual_distractors) != expected_distractors
            or not blueprint.misconception_targets
            or any(
                item.misconception not in blueprint.misconception_targets
                for item in output.distractor_rationales
            )
        ):
            raise AuthorGenerationError(
                "AUTHOR_OUTPUT_INVALID",
                "The authored MCQ does not bind every distractor to an authorized misconception.",
            )
    elif output.options or output.correct_option_index is not None or output.distractor_rationales:
        raise AuthorGenerationError(
            "AUTHOR_OUTPUT_INVALID",
            "Only a single-choice blueprint may return options or a correct-option index.",
        )
    rule_analysis = output.rule_violation_analysis
    if blueprint.generation_policy_version == RULE_VIOLATION_POLICY_VERSION:
        fragment_by_id = {fragment.evidence_id: fragment for fragment in evidence.fragments}
        rule_fragment = (
            fragment_by_id.get(rule_analysis.rule_source_ref)
            if rule_analysis is not None
            else None
        )
        # The binding is the cited span; a quotation is cross-checked when one is
        # supplied, and its absence is not a defect.
        quote_matches = (
            rule_analysis.rule_quote is None
            or rule_analysis.rule_quote in rule_fragment.content
        ) if (rule_analysis is not None and rule_fragment is not None) else False
        valid_rule = (
            blueprint.question_type == "EXPLANATION"
            and rule_analysis is not None
            and rule_fragment is not None
            and rule_analysis.rule_source_ref in output.source_refs
            and quote_matches
            and rule_analysis.proposed_statement in output.question_text
        )
        if not valid_rule:
            raise AuthorGenerationError(
                "AUTHOR_OUTPUT_INVALID",
                "The rule-violation question is not bound to an exact course rule.",
            )
    elif rule_analysis is not None:
        # A rule analysis under a policy that does not use one is an unused field,
        # and an unused field cannot change any decision.  Rejecting the response
        # over it would throw away a complete paid call; the question's own shape is
        # still checked by the gates that do read it.
        object.__setattr__(output, "rule_violation_analysis", None)


def _failure_from_provider(failure: ProviderCallFailure) -> AuthorGenerationError:
    cause = failure.cause
    if isinstance(cause, ValueError):
        code = "AUTHOR_OUTPUT_INVALID"
    elif isinstance(cause, ApiError) and cause.code == "CONTEXT_BUDGET":
        code = "AUTHOR_INPUT_TOO_LARGE"
    elif isinstance(cause, ApiError) and cause.code in {
        "MODEL_LIVE_BLOCKED",
        "MODEL_ENDPOINT_INVALID",
    }:
        code = "AUTHOR_PROVIDER_BLOCKED"
    else:
        code = "AUTHOR_PROVIDER_FAILED"
    return AuthorGenerationError(
        code,
        "The private author call did not produce a usable candidate.",
        provider_run=failure.run,
    )


def _assert_contract_scope(
    spec: StudentVisibleTaskSpec, *, evidence: QuestionEvidencePack
) -> None:
    """Every span the contract cites must be a span the author was given.

    A contract is the record of what the learner can see, so a fact bound to a
    span that is not in the evidence pack would be a condition the learner cannot
    reach -- exactly the defect the contract exists to make impossible.
    """
    allowed = set(evidence.evidence_ids)
    offending = sorted(
        {
            fact.source_span_id
            for fact in spec.facts
            if fact.source_span_id and fact.source_span_id not in allowed
        }
    )
    if offending:
        raise AuthorGenerationError(
            "AUTHOR_CONTRACT_SCOPE",
            f"The task contract cites spans outside the evidence pack: {offending}",
        )


def author_context(
    blueprint: QuestionBlueprint, evidence: QuestionEvidencePack
) -> dict[str, Any]:
    """The exact context an author call receives, built in exactly one place.

    The persistence stage has to recompute this context's hash to decide whether
    an author receipt is still current, and it used to carry its own copy of the
    structure.  A copy drifts: adding the profile registry here silently made every
    item's author receipt stale, and the symptom was a READY item quietly becoming
    NEEDS_REVIEW with AUTHOR_PROVENANCE_INCOMPLETE.  Both sides now call this.
    """
    return {
        "blueprint": blueprint.model_dump(mode="json"),
        "evidence_pack": evidence.model_dump(mode="json"),
        # The server's own profile registry travels with the request, so the author
        # chooses against the registered requirements rather than from its own idea
        # of what a profile wants.  A live run claimed P-SQL for a NUMERIC item and
        # declared conventions that profile does not accept; the certificate refused
        # it correctly, but the model had been told the profiles exist without being
        # told what each one requires.
        "task_profiles": [
            {
                "profile_id": profile.profile_id,
                "version": profile.version,
                "description": profile.description,
                "question_types": sorted(profile.question_types),
                "required_roles": sorted(profile.required_roles),
                "required_conventions": list(profile.required_conventions),
            }
            for profile in REGISTERED_PROFILES
        ],
    }


def author_input_hash(
    blueprint: QuestionBlueprint, evidence: QuestionEvidencePack
) -> str:
    """The identity an author receipt is bound to, from the same context."""
    return structured_input_hash(
        QuestionAuthorOutput, context=author_context(blueprint, evidence)
    )


def author_question(
    provider: AuthorProvider,
    *,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
) -> AuthoredQuestionCandidate:
    """Generate but do not publish one candidate bound to exact inputs and prompt revision."""
    _assert_inputs_match(blueprint, evidence)
    protocol = getattr(provider, "cache_protocol", None)
    if protocol is not None and protocol != "fixture" and not (
        getattr(provider, "cache_model", None) == "deepseek-flash"
        and getattr(provider, "is_deepseek", False) is True
        and protocol == "responses"
    ):
        raise AuthorGenerationError(
            "AUTHOR_PROVIDER_BLOCKED",
            "Question authoring permits only the verified DeepSeek Responses path.",
        )
    context = author_context(blueprint, evidence)
    try:
        raw_output, raw_run = provider.generate(
            QuestionAuthorOutput,
            instructions=PROMPT_PATH.read_text(encoding="utf-8"),
            context=context,
            role="QUESTION_AUTHOR",
            template_version=QUESTION_AUTHOR_PROMPT_VERSION,
            schema_version=QUESTION_AUTHOR_SCHEMA_VERSION,
        )
        output = QuestionAuthorOutput.model_validate(raw_output)
        run = AuthorProviderRun.model_validate(raw_run)
        if (
            run.template_version != QUESTION_AUTHOR_PROMPT_VERSION
            or run.schema_version != QUESTION_AUTHOR_SCHEMA_VERSION
        ):
            raise ValueError("question author run version does not match the request")
    except ProviderCallFailure as failure:
        raise _failure_from_provider(failure) from failure
    except (OSError, ValueError) as error:
        # The rejection reason is kept in the message so a run can attribute it:
        # the blanket code alone made the first live failure impossible to read.
        raise AuthorGenerationError(
            "AUTHOR_OUTPUT_INVALID",
            f"The private author result failed its contract: {type(error).__name__}: {error}"[:400],
        ) from error

    _assert_output_scope(output, blueprint=blueprint, evidence=evidence)
    draft: TaskContractDraft | None = None
    if output.task_contract is not None:
        try:
            draft = TaskContractDraft.model_validate(output.task_contract)
        except ValueError as error:
            # The failing fields, without their values: that is what makes the
            # refusal actionable rather than a repeatable mystery.
            raise AuthorGenerationError(
                "AUTHOR_CONTRACT_INVALID",
                "The task contract did not satisfy its own schema: "
                + ", ".join(schema_error_summary(error)),
            ) from error
    if draft is not None:
        # A schema-valid contract can still be one the declared profile cannot
        # certify: P-COURSE-RULE requires a SOURCE_RULE and a CLAIM_TO_CRITIQUE
        # fact, and a contract that declares that profile without supplying them
        # passes its own schema and then fails completeness.  It used to fail
        # *after* two paid reviews, which is the most expensive way to learn that
        # the author omitted a role it was told to include -- a campus run lost
        # thirteen of twenty-nine sound items that way.  Checked here, the refusal
        # is immediate, attributable, and free.
        from app.learning.task_spec import profile_by_id

        profile = profile_by_id(draft.profile_id, version=draft.profile_version)
        if profile is not None:
            supplied = {fact.role for fact in draft.facts}
            missing = sorted(profile.required_roles - supplied)
            if missing:
                raise AuthorGenerationError(
                    "AUTHOR_CONTRACT_INCOMPLETE",
                    f"The contract declares {profile.profile_id}, which requires a fact for "
                    + ", ".join(missing)
                    + "; without every required role the item cannot be certified.",
                )
    blueprint_hash = blueprint.identity()
    evidence_hash = evidence.identity()
    revision = _question_revision_identity(
        blueprint_hash=blueprint_hash,
        evidence_pack_hash=evidence_hash,
        output=output,
    )
    if draft is not None:
        try:
            _assert_contract_scope(
                build_task_spec(
                    draft,
                    blueprint=blueprint,
                    question_revision_hash=revision,
                ),
                evidence=evidence,
            )
        except TaskSpecError as error:
            raise AuthorGenerationError(error.code, str(error)) from error
    return AuthoredQuestionCandidate(
        blueprint_id=blueprint.blueprint_id,
        blueprint_hash=blueprint_hash,
        evidence_pack_hash=evidence_hash,
        question_revision=revision,
        course_id=blueprint.course_id,
        node_id=blueprint.node_id,
        objective_id=blueprint.objective_id,
        question_type=blueprint.question_type,
        marks=blueprint.marks,
        public_question=PublicAuthoredQuestion(
            question_text=output.question_text,
            options=output.options,
            source_refs=output.source_refs,
            answer_policy=blueprint.answer_policy,
        ),
        private_solution=PrivateCandidateSolution(
            candidate_answer=output.candidate_answer,
            correct_option_index=output.correct_option_index,
            distractor_rationales=output.distractor_rationales,
            rule_violation_analysis=output.rule_violation_analysis,
            solution_steps=output.solution_steps,
            source_refs=output.source_refs,
        ),
        provider_run=run,
        task_contract=draft,
    )
