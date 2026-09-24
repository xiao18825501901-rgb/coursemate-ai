"""Independent (blind) solve: the request builder that cannot see the author's answer.

The Question Engine's fifth stage solves the finished question in an **independent context** and
compares that solution with the author's. That comparison is only evidence if the two really were
independent, and independence here is not a property of the model or of the prompt wording — it is
a property of *what was sent*. Two calls to the same model are information isolation, never
statistical independence and never a second expert (the plan says so, and this module does not
pretend otherwise).

So the isolation is enforced where it can be checked: a **closed field whitelist**. The payload the
blind solver receives is built from `BLIND_SOLVE_FIELDS` and nothing else, options are plain text
(so a structured option carrying a `correct` flag cannot even be passed), and
`assert_no_answer_leak` scans the serialized request for the strings that must not be there — the
author's solution, the correct-option marker, a student's answer, a previous critique's correction,
or a rubric field with the answer key in it. Sentinel tests prove that the guard rejects those leak
channels. The provider path projects only public question fields and exact Stage-2 evidence content,
so it never accepts an arbitrary caller-supplied rule bag that could smuggle private answer text.

The provider adapter below preserves that closed boundary: it sends exactly the request payload,
permits only the verified DeepSeek Responses path for live calls, and returns a revision-bound
receipt. Persistence and publication remain the responsibility of the Stage-7 transaction.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import Field, StringConstraints, model_validator

from app.errors import ApiError
from app.learning.models import Contract
from app.learning.provider import ProviderCallFailure
from app.learning.question_author import AuthoredQuestionCandidate
from app.learning.question_evidence import QuestionEvidencePack

BLIND_SOLVER_PROMPT_VERSION: Final = "blind-solver.v1"
BLIND_SOLVER_SCHEMA_VERSION: Final = "blind-solve-output.v1"
PROMPT_PATH: Final = Path(__file__).with_name("prompts") / "blind_solver_v1.md"

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]

# The closed whitelist. A field that is not here cannot reach the blind solver, which is the whole
# point: the way a blind solve stops being blind is by growing "one more helpful field".
BLIND_SOLVE_FIELDS: Final[tuple[str, ...]] = (
    "question_text",
    "options",
    "allowed_rules",
    "task",
)

# Field names that must never appear anywhere in a blind-solve payload. They are checked by key as
# well as by value, because a payload that carries `"correct_option": "B"` is exactly as leaky as
# one whose prose mentions it.
FORBIDDEN_FIELD_NAMES: Final[tuple[str, ...]] = (
    "author_solution",
    "answer",
    "answer_key",
    "correct_option",
    "correct_options",
    "student_answer",
    "grading",
    "rubric",
    "critique",
    "reasoning",
)

DEFAULT_TASK: Final[str] = (
    "Solve the question below independently. Show the steps you used. If the question is "
    "ambiguous, under-specified or not solvable as written, say so explicitly instead of "
    "assuming the missing information."
)


class BlindSolveLeak(RuntimeError):
    """Raised when something that could reveal the answer reaches the blind-solve request."""


class BlindSolveError(RuntimeError):
    """Stable Stage-5 refusal that never echoes a private provider body."""

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


@dataclass(frozen=True)
class BlindSolveRequest:
    """The only thing the blind solver is allowed to see.

    `options` are **plain strings**: a caller that holds structured options with a correctness flag
    has to project them to text first, and that projection is where the flag is dropped.
    """

    question_text: str
    options: tuple[str, ...] = ()
    allowed_rules: tuple[str, ...] = ()
    task: str = DEFAULT_TASK

    def __post_init__(self) -> None:
        if not self.question_text.strip():
            raise ValueError("a blind solve needs the finished question text")
        for name, values in (("options", self.options), ("allowed_rules", self.allowed_rules)):
            for value in values:
                if not isinstance(value, str):
                    raise TypeError(
                        f"{name} must contain plain strings; a structured option carrying a "
                        f"correctness flag would defeat the isolation this module exists for"
                    )

    def payload(self) -> dict[str, object]:
        """The exact mapping that may be sent, in the whitelist's order."""
        return {
            "question_text": self.question_text,
            "options": list(self.options),
            "allowed_rules": list(self.allowed_rules),
            "task": self.task,
        }

    def input_hash(self) -> str:
        """Stable identity of the request, so a receipt can be tied to what was actually solved."""
        canonical = json.dumps(self.payload(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


class BlindSolveStep(Contract):
    ordinal: int = Field(ge=1, le=12)
    operation: ShortText
    result: ShortText
    explanation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=20, max_length=6000)
    ]


class BlindSolveOutput(Contract):
    """Independent result only; it has no authority to grade or publish a question."""

    schema_version: Literal["blind-solve-output.v1"] = BLIND_SOLVER_SCHEMA_VERSION
    solvability: Literal["SOLVABLE", "AMBIGUOUS", "UNDER_SPECIFIED", "UNSOLVABLE"]
    conclusion: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12000)
    ]
    steps: list[BlindSolveStep] = Field(min_length=1, max_length=12)
    assumptions: list[ShortText] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def step_ordinals_are_consecutive(self) -> BlindSolveOutput:
        if [step.ordinal for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("blind-solve step ordinals must be consecutive from one")
        return self


class BlindSolveProviderRun(Contract):
    model: ShortText
    provider: ShortText
    protocol: ShortText
    region: ShortText
    role: Literal["QUESTION_BLIND_SOLVER"]
    template_version: Literal["blind-solver.v1"]
    schema_version: Literal["blind-solve-output.v1"]
    input_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    started_at: ShortText
    finished_at: ShortText
    latency_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    provider_response_id: ShortText | None = None
    status: Literal["COMPLETED"]
    error_class: None = None

    @model_validator(mode="after")
    def deepseek_or_labelled_fixture_only(self) -> BlindSolveProviderRun:
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
            raise ValueError("blind-solve receipts must be DeepSeek or labelled test fixtures")
        return self


class BlindSolveProvider(Protocol):
    def generate(
        self,
        schema: type[BlindSolveOutput],
        *,
        instructions: str,
        context: dict[str, object],
        role: str,
        template_version: str,
        schema_version: str,
    ) -> tuple[BlindSolveOutput, dict[str, Any]]: ...


def assert_no_answer_leak(
    request: BlindSolveRequest | Mapping[str, object],
    forbidden_values: Sequence[str] = (),
) -> None:
    """Refuse a blind-solve request that carries a known answer or a forbidden field.

    `forbidden_values` are the concrete strings the caller must not leak — the author's solution
    text, the correct option, a student's answer, a critique's correction, a rubric's answer key.
    Empty strings are ignored: a caller that passes its whole answer set should not have to filter
    the blanks, and an empty sentinel would match everything.

    Raises:
        BlindSolveLeak: naming what was found, by field or by sentinel, never echoing the secret
            itself into the message.
    """
    payload = request.payload() if isinstance(request, BlindSolveRequest) else dict(request)
    # Forbidden names are checked first so that a payload carrying `correct_option` is reported as
    # what it is — an answer leak — rather than as a mere unknown field.
    lowered = {str(key).casefold() for key in payload}
    forbidden_keys = sorted(name for name in FORBIDDEN_FIELD_NAMES if name in lowered)
    if forbidden_keys:
        raise BlindSolveLeak(f"blind-solve payload carries forbidden fields: {forbidden_keys}")
    unknown = sorted(set(payload) - set(BLIND_SOLVE_FIELDS))
    if unknown:
        raise BlindSolveLeak(
            f"blind-solve payload has fields outside the whitelist: {unknown}. "
            f"Allowed: {list(BLIND_SOLVE_FIELDS)}"
        )

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).casefold()
    hits: list[str] = []
    for index, value in enumerate(forbidden_values):
        text = (value or "").strip()
        if not text:
            continue
        if text.casefold() in serialized:
            # The sentinel's *index* is reported, not its content: this message can end up in a
            # log, and the sentinel is normally a piece of the answer.
            hits.append(f"sentinel #{index}")
    if hits:
        raise BlindSolveLeak(
            "blind-solve payload contains text from the answer side: "
            + ", ".join(hits)
            + ". The author's solution, the correct option, a student answer, a critique's "
            "correction and any rubric key must not reach the independent solve."
        )


@dataclass(frozen=True)
class BlindSolveReceipt:
    """What a completed blind solve must record to be usable as evidence.

    The two revisions are separate on purpose: editing the question invalidates the solve
    (`is_current_for`), and a receipt whose question revision is not the one being published is
    not evidence about that question.
    """

    input_hash: str
    question_revision: str
    model_version: str
    output: str
    status: str
    provider_run: BlindSolveProviderRun | None = None

    def is_current_for(self, question_revision: str, input_hash: str | None = None) -> bool:
        """True only when this solve was run against the revision now under validation."""
        return (
            self.status == "completed"
            and bool(self.output.strip())
            and self.question_revision == question_revision
            and (input_hash is None or self.input_hash == input_hash)
        )


def _failure_from_provider(failure: ProviderCallFailure) -> BlindSolveError:
    cause = failure.cause
    if isinstance(cause, ValueError):
        code = "BLIND_SOLVER_OUTPUT_INVALID"
    elif isinstance(cause, ApiError) and cause.code == "CONTEXT_BUDGET":
        code = "BLIND_SOLVER_INPUT_TOO_LARGE"
    elif isinstance(cause, ApiError) and cause.code in {
        "MODEL_LIVE_BLOCKED",
        "MODEL_ENDPOINT_INVALID",
    }:
        code = "BLIND_SOLVER_PROVIDER_BLOCKED"
    else:
        code = "BLIND_SOLVER_PROVIDER_FAILED"
    return BlindSolveError(
        code,
        "The independent solver did not produce a usable result.",
        provider_run=failure.run,
    )


def run_blind_solve(
    provider: BlindSolveProvider,
    *,
    candidate: AuthoredQuestionCandidate,
    evidence: QuestionEvidencePack,
) -> BlindSolveReceipt:
    """Run one answer-free independent solve and bind its receipt to the candidate revision."""
    evidence_matches = (
        candidate.evidence_pack_hash == evidence.identity()
        and candidate.course_id == evidence.course_id
        and candidate.node_id == evidence.node_id
        and candidate.objective_id == evidence.objective_id
        and set(candidate.public_question.source_refs).issubset(evidence.evidence_ids)
    )
    if not evidence_matches:
        raise BlindSolveError(
            "BLIND_SOLVER_INPUT_MISMATCH",
            "The candidate and objective-scoped evidence pack do not match.",
        )

    protocol = getattr(provider, "cache_protocol", None)
    fixture = (
        protocol == "fixture"
        and getattr(provider, "cache_model", None) == "FAKE_TEST_ONLY"
        and getattr(provider, "cache_region", None) == "LOCAL_TEST"
    )
    deepseek = (
        getattr(provider, "cache_model", None) == "deepseek-flash"
        and getattr(provider, "is_deepseek", False) is True
        and protocol == "responses"
        and getattr(provider, "cache_region", None) == "ENDPOINT_DEEPSEEK"
    )
    if not (fixture or deepseek):
        raise BlindSolveError(
            "BLIND_SOLVER_PROVIDER_BLOCKED",
            "Independent solving permits only the verified DeepSeek Responses path.",
        )

    request = BlindSolveRequest(
        question_text=candidate.public_question.question_text,
        options=tuple(candidate.public_question.options),
        allowed_rules=tuple(fragment.content for fragment in evidence.fragments),
    )
    assert_no_answer_leak(request)
    try:
        raw_output, raw_run = provider.generate(
            BlindSolveOutput,
            instructions=PROMPT_PATH.read_text(encoding="utf-8"),
            context=request.payload(),
            role="QUESTION_BLIND_SOLVER",
            template_version=BLIND_SOLVER_PROMPT_VERSION,
            schema_version=BLIND_SOLVER_SCHEMA_VERSION,
        )
        output = BlindSolveOutput.model_validate(raw_output)
        run = BlindSolveProviderRun.model_validate(raw_run)
    except ProviderCallFailure as failure:
        raise _failure_from_provider(failure) from failure
    except (OSError, ValueError) as error:
        raise BlindSolveError(
            "BLIND_SOLVER_OUTPUT_INVALID",
            "The independent solver result failed its contract.",
        ) from error

    rendered = json.dumps(
        output.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return BlindSolveReceipt(
        input_hash=request.input_hash(),
        question_revision=candidate.question_revision,
        model_version=run.model,
        output=rendered,
        status="completed",
        provider_run=run,
    )
