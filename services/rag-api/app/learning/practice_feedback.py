"""DeepSeek-only diagnostic feedback and bounded hints for READY practice questions.

The Question Engine owns question scope and persistence.  This module owns only
the two structured model contracts.  Its outputs are formative feedback: they
cannot publish questions, award grades, create performance evidence, or change
learning coverage / ``LEARNED``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from app.learning.models import Contract, Identifier, Text
from app.learning.provider import ProviderCallFailure
from app.learning.question_blueprint import Hex64

PRACTICE_FEEDBACK_PROMPT_VERSION: Final = "practice-feedback.v1"
PRACTICE_FEEDBACK_SCHEMA_VERSION: Final = "practice-feedback-output.v1"
PRACTICE_HINT_PROMPT_VERSION: Final = "practice-hint.v1"
PRACTICE_HINT_SCHEMA_VERSION: Final = "practice-hint-output.v1"

PROMPT_DIRECTORY: Final = Path(__file__).with_name("prompts")
FEEDBACK_PROMPT_PATH: Final = PROMPT_DIRECTORY / "practice_feedback_v1.md"
HINT_PROMPT_PATH: Final = PROMPT_DIRECTORY / "practice_hint_v1.md"

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class PracticeInteractionError(RuntimeError):
    """Stable refusal that never includes a provider body or reference answer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CriterionFeedback(Contract):
    criterion_id: Identifier
    met: bool
    feedback: ShortText


class PracticeFeedbackOutput(Contract):
    schema_version: Literal["practice-feedback-output.v1"] = (
        PRACTICE_FEEDBACK_SCHEMA_VERSION
    )
    verdict: Literal["CORRECT", "PARTIAL", "INCORRECT", "NEEDS_REVIEW"]
    feedback: Text
    strengths: list[ShortText] = Field(default_factory=list, max_length=5)
    gaps: list[ShortText] = Field(default_factory=list, max_length=5)
    next_step: ShortText
    criteria: list[CriterionFeedback] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_criteria(self) -> PracticeFeedbackOutput:
        ids = [item.criterion_id for item in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion feedback ids must be unique")
        return self


class PracticeHintOutput(Contract):
    schema_version: Literal["practice-hint-output.v1"] = PRACTICE_HINT_SCHEMA_VERSION
    hint: Text
    strategy: ShortText


class PracticeProviderRun(Contract):
    model: ShortText
    provider: ShortText
    protocol: ShortText
    region: ShortText
    role: Literal["PRACTICE_FEEDBACK", "PRACTICE_HINT"]
    template_version: Literal["practice-feedback.v1", "practice-hint.v1"]
    schema_version: Literal[
        "practice-feedback-output.v1", "practice-hint-output.v1"
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
    def deepseek_or_labelled_fixture_only(self) -> PracticeProviderRun:
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
            raise ValueError("practice feedback receipts must be DeepSeek or labelled fixtures")
        expected = {
            "PRACTICE_FEEDBACK": (
                PRACTICE_FEEDBACK_PROMPT_VERSION,
                PRACTICE_FEEDBACK_SCHEMA_VERSION,
            ),
            "PRACTICE_HINT": (PRACTICE_HINT_PROMPT_VERSION, PRACTICE_HINT_SCHEMA_VERSION),
        }[self.role]
        if (self.template_version, self.schema_version) != expected:
            raise ValueError("practice provider receipt does not match its role")
        return self


def _provider_failure(failure: ProviderCallFailure, prefix: str) -> PracticeInteractionError:
    cause = failure.cause
    code = getattr(cause, "code", "")
    if code in {"MODEL_LIVE_BLOCKED", "MODEL_ENDPOINT_INVALID"}:
        return PracticeInteractionError(
            f"{prefix}_PROVIDER_BLOCKED", "The verified DeepSeek provider is unavailable."
        )
    return PracticeInteractionError(
        f"{prefix}_PROVIDER_FAILED", "The verified DeepSeek request did not complete."
    )


def generate_practice_feedback(
    provider: Any,
    *,
    context: dict[str, Any],
) -> tuple[PracticeFeedbackOutput, PracticeProviderRun]:
    try:
        output, raw_run = provider.generate(
            PracticeFeedbackOutput,
            instructions=FEEDBACK_PROMPT_PATH.read_text(encoding="utf-8"),
            context=context,
            role="PRACTICE_FEEDBACK",
            template_version=PRACTICE_FEEDBACK_PROMPT_VERSION,
            schema_version=PRACTICE_FEEDBACK_SCHEMA_VERSION,
        )
        return (
            PracticeFeedbackOutput.model_validate(output),
            PracticeProviderRun.model_validate(raw_run),
        )
    except ProviderCallFailure as failure:
        raise _provider_failure(failure, "PRACTICE_FEEDBACK") from failure
    except (OSError, ValueError) as error:
        raise PracticeInteractionError(
            "PRACTICE_FEEDBACK_INVALID",
            "The diagnostic feedback failed its structured contract.",
        ) from error


def _normalise(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _assert_hint_does_not_reveal(
    output: PracticeHintOutput,
    *,
    reference_answer: str,
    solution_steps: list[dict[str, Any]],
) -> None:
    learner_visible_output = _normalise(f"{output.hint}\n{output.strategy}")
    protected = [reference_answer]
    protected.extend(str(step.get("result") or "") for step in solution_steps)
    for value in protected:
        normalized = _normalise(value)
        # Short tokens such as a unit or one digit are too noisy for substring
        # rejection.  The prompt still prohibits disclosure; this deterministic
        # gate catches meaningful verbatim answer/result leakage.
        if len(normalized) >= 6 and normalized in learner_visible_output:
            raise PracticeInteractionError(
                "PRACTICE_HINT_ANSWER_LEAK",
                "The generated hint repeated protected answer material.",
            )


def generate_practice_hint(
    provider: Any,
    *,
    context: dict[str, Any],
) -> tuple[PracticeHintOutput, PracticeProviderRun]:
    try:
        output, raw_run = provider.generate(
            PracticeHintOutput,
            instructions=HINT_PROMPT_PATH.read_text(encoding="utf-8"),
            context=context,
            role="PRACTICE_HINT",
            template_version=PRACTICE_HINT_PROMPT_VERSION,
            schema_version=PRACTICE_HINT_SCHEMA_VERSION,
        )
        parsed = PracticeHintOutput.model_validate(output)
        run = PracticeProviderRun.model_validate(raw_run)
    except ProviderCallFailure as failure:
        raise _provider_failure(failure, "PRACTICE_HINT") from failure
    except (OSError, ValueError) as error:
        raise PracticeInteractionError(
            "PRACTICE_HINT_INVALID", "The practice hint failed its structured contract."
        ) from error
    reference = context["reference_solution"]
    _assert_hint_does_not_reveal(
        parsed,
        reference_answer=str(reference["answer"]),
        solution_steps=list(reference["steps"]),
    )
    return parsed, run
