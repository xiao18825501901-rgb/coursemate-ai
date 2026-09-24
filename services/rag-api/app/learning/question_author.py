"""Question Engine stage 4: one evidence-bound author call and a private candidate answer.

The provider sees only the server-authored blueprint and the Stage-2 evidence pack.  The model
cannot choose ownership, verification, publication or grades, and its answer is kept behind an
explicit private boundary.  This module does not persist or publish a candidate; Stage 7 owns the
READY transaction after independent solve and validation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import Field, StringConstraints, model_validator

from app.errors import ApiError
from app.learning.models import Contract, Identifier, Text
from app.learning.provider import ProviderCallFailure
from app.learning.question_blueprint import Hex64, QuestionBlueprint
from app.learning.question_evidence import QuestionEvidencePack

QUESTION_AUTHOR_PROMPT_VERSION: Final = "question-author.v3"
QUESTION_AUTHOR_SCHEMA_VERSION: Final = "question-author-output.v3"
RULE_VIOLATION_POLICY_VERSION: Final = "question-rule-violation-policy-v1"
PROMPT_PATH: Final = Path(__file__).with_name("prompts") / "question_author_v3.md"

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


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
    """Private proof that a rule-violation question uses a real course rule."""

    proposed_statement: Text
    rule_source_ref: Identifier
    rule_quote: Text
    correction: Text
    explanation: Text


class QuestionAuthorOutput(Contract):
    """The model-authored fields; everything authoritative remains in the blueprint."""

    schema_version: Literal["question-author-output.v3"] = QUESTION_AUTHOR_SCHEMA_VERSION
    question_text: Text
    options: list[ShortText] = Field(default_factory=list, max_length=10)
    candidate_answer: Text = Field(repr=False)
    correct_option_index: int | None = Field(default=None, ge=0, le=9)
    distractor_rationales: list[DistractorRationale] = Field(default_factory=list, max_length=9)
    rule_violation_analysis: RuleViolationAnalysis | None = None
    solution_steps: list[AuthorSolutionStep] = Field(min_length=1, max_length=12, repr=False)
    source_refs: list[Identifier] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def consecutive_steps_and_unique_sources(self) -> QuestionAuthorOutput:
        if [step.ordinal for step in self.solution_steps] != list(
            range(1, len(self.solution_steps) + 1)
        ):
            raise ValueError("solution step ordinals must be consecutive from one")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("question source references must be unique")
        return self


def _question_revision_identity(
    *,
    blueprint_hash: str,
    evidence_pack_hash: str,
    output: QuestionAuthorOutput,
) -> str:
    revision_payload = {
        "blueprint_hash": blueprint_hash,
        "evidence_pack_hash": evidence_pack_hash,
        "author_output": output.model_dump(mode="json"),
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
    template_version: Literal["question-author.v1", "question-author.v2", "question-author.v3"]
    schema_version: Literal[
        "question-author-output.v1", "question-author-output.v2", "question-author-output.v3"
    ]
    input_hash: Hex64
    started_at: ShortText
    finished_at: ShortText
    latency_ms: int = Field(ge=0)
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

    def revision_identity(self) -> str:
        """Recompute the immutable revision from the split public/private candidate."""
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
        valid_rule = (
            blueprint.question_type == "EXPLANATION"
            and rule_analysis is not None
            and rule_fragment is not None
            and rule_analysis.rule_source_ref in output.source_refs
            and rule_analysis.rule_quote in rule_fragment.content
            and rule_analysis.proposed_statement in output.question_text
        )
        if not valid_rule:
            raise AuthorGenerationError(
                "AUTHOR_OUTPUT_INVALID",
                "The rule-violation question is not bound to an exact course rule.",
            )
    elif rule_analysis is not None:
        raise AuthorGenerationError(
            "AUTHOR_OUTPUT_INVALID",
            "Only the rule-violation policy may return a rule analysis.",
        )


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
    context = {
        "blueprint": blueprint.model_dump(mode="json"),
        "evidence_pack": evidence.model_dump(mode="json"),
    }
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
        raise AuthorGenerationError(
            "AUTHOR_OUTPUT_INVALID", "The private author result failed its contract."
        ) from error

    _assert_output_scope(output, blueprint=blueprint, evidence=evidence)
    blueprint_hash = blueprint.identity()
    evidence_hash = evidence.identity()
    return AuthoredQuestionCandidate(
        blueprint_id=blueprint.blueprint_id,
        blueprint_hash=blueprint_hash,
        evidence_pack_hash=evidence_hash,
        question_revision=_question_revision_identity(
            blueprint_hash=blueprint_hash,
            evidence_pack_hash=evidence_hash,
            output=output,
        ),
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
    )
