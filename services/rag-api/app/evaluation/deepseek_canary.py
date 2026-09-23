"""DeepSeek generation canary: a small, fail-closed, billable-opt-in live check.

Why this exists: requirement 11 fixes the batch cost ceiling *before* any real
model test, and requirement 13 needs one small real DeepSeek canary step.  The
Qwen canary (``v3_model_canary.py``) already proved the shape of a bounded,
checkpointed canary; this module is the DeepSeek counterpart.

It is pure logic only - no network, no CLI, no credentials.  It:

* declares one ``CanaryRole`` per migrated production role, each with its
  protocol, whether structured output is required, whether an image is attached,
  and which prompt/template loader it uses (reusing ``app/cm_update/templates``
  for the template ids and the 题目/详解 prompts - the prompt text is never
  copied here);
* builds DeepSeek-native request bodies for both protocols with native thinking
  explicitly disabled and images attached via the documented ``detail`` field;
* validates a payload fail-closed against the DeepSeek contract (no Qwen-only
  fields, an allow-listed base URL, a ``deepseek-*`` alias, an exact endpoint);
* prices a worst-case run from explicit owner-supplied prices - which are never
  invented here - and validates a response into typed evidence.

Streaming consumption is deliberately NOT exercised here: it is already covered
by ``tests/test_deepseek_provider_roles.py``.  The canary asks for one complete,
validated response per role so the response validator stays simple and honest.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

from app.cm_update import templates
from app.cm_update.exercise_contract import EXERCISE_RESPONSE_FORMAT
from app.evaluation.deepseek_contract import (
    CHAT_COMPLETIONS_PATH,
    RESPONSES_PATH,
    chat_completions_body,
    chat_completions_image_part,
    json_schema_text_format,
    responses_body,
    responses_image_part,
)
from app.evaluation.model_benchmark import (
    calculate_cost_ceiling,
    conservative_input_token_ceiling,
)
from app.evaluation.provider_safety import validate_deepseek_base_url
from app.learning.compiler import assessment_template
from app.brand import BRAND

Protocol = Literal["chat_completions", "responses"]

QWEN_ONLY_FIELDS = ("enable_thinking", "max_pixels")
DEFAULT_MAX_OUTPUT_TOKENS = 4_000
PROTOCOL_OVERHEAD_TOKENS = 512
IMAGE_DETAIL_DEFAULT = "auto"
ARTIFACT_VERSION = "deepseek-live-canary-v1"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CanaryContractError(ValueError):
    """A canary call violates the verified DeepSeek contract before it is sent."""


class UnusableResponseError(CanaryContractError):
    """A provider response could not be turned into usable canary evidence."""


# ---------------------------------------------------------------------------
# Prices (explicit owner inputs only - never invented constants)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeepSeekPrices:
    input_price_per_million: float
    output_price_per_million: float
    currency: str = "USD"


def validate_prices(prices: DeepSeekPrices | None) -> None:
    """Fail-closed price validation; missing or non-positive prices are refused."""
    if prices is None:
        raise CanaryContractError(
            "DeepSeek prices are required to compute a cost ceiling and were not supplied."
        )
    if not math.isfinite(prices.input_price_per_million) or not math.isfinite(
        prices.output_price_per_million
    ):
        raise CanaryContractError("DeepSeek prices must be finite.")
    if prices.input_price_per_million <= 0 or prices.output_price_per_million <= 0:
        raise CanaryContractError(
            "DeepSeek input and output prices must both be positive; none are invented here."
        )


# ---------------------------------------------------------------------------
# Role plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanaryRole:
    role: str
    protocol: Protocol
    structured: bool
    image: bool
    prompt_source: str
    instruction: Callable[[], str]


def _knowledge_qa_instruction() -> str:
    return (
        f"You are {BRAND.name}'s grounded Q&A. Answer using only the supplied course "
        "material, cite sources with [S1]-style markers, and do not invent citations."
    )


def _plan_instruction() -> str:
    return templates.plan_writer_instruction()


def _work_instruction() -> str:
    return "Execute the validated teaching prompt and produce the visible teaching explanation."


def _classification_instruction() -> str:
    ids = ", ".join(templates.registry("V2").keys())
    return (
        "Classify the course into exactly one of the professional teaching templates "
        f"or OTHER. Template ids: {ids}. Only output the requested JSON object."
    )


def _exercise_instruction() -> str:
    return templates.exercise_prompt() + "\n\n" + templates.exercise_runtime_contract()


def _problem_instruction() -> str:
    return templates.problem_prompt()


def _explanation_instruction() -> str:
    return templates.explanation_prompt()


def _image_instruction() -> str:
    # The image-problem lane reuses the owner's 题目 prompt, same as production.
    return templates.problem_prompt()


def _assessment_instruction() -> str:
    return assessment_template()[0]


def _coverage_review_instruction() -> str:
    return (
        "Review the teaching content against the given REQUIRED items. For each item "
        "output covered / partial / not_covered / uncertain, with an evidence quote "
        "for covered items. Only use the supplied item ids."
    )


def role_plan() -> tuple[CanaryRole, ...]:
    """The ordered canary plan: every migrated production role, exactly once.

    Protocols mirror production: grounded QA and coverage review run over Chat
    Completions; the plan->work pair, classification, exercise.v2, 题目, 详解,
    image understanding and the assessment reference run over Responses.
    """
    return (
        CanaryRole(
            "KNOWLEDGE_QA",
            "chat_completions",
            structured=False,
            image=False,
            prompt_source="app/rag/answers.py::stream_answer (runtime instructions)",
            instruction=_knowledge_qa_instruction,
        ),
        CanaryRole(
            "PLAN",
            "responses",
            structured=False,
            image=False,
            prompt_source="app/cm_update/provider.py::planner_messages",
            instruction=_plan_instruction,
        ),
        CanaryRole(
            "WORK",
            "responses",
            structured=False,
            image=False,
            prompt_source="app/cm_update/provider.py::work_messages",
            instruction=_work_instruction,
        ),
        CanaryRole(
            "CLASSIFICATION",
            "responses",
            structured=True,
            image=False,
            prompt_source="templates.registry('V2') template ids (01..14, OTHER)",
            instruction=_classification_instruction,
        ),
        CanaryRole(
            "EXERCISE_V2",
            "responses",
            structured=True,
            image=False,
            prompt_source="templates.exercise_prompt() + templates.exercise_runtime_contract()",
            instruction=_exercise_instruction,
        ),
        CanaryRole(
            "PROBLEM",
            "responses",
            structured=False,
            image=False,
            prompt_source="templates.problem_prompt() (题目 prompt)",
            instruction=_problem_instruction,
        ),
        CanaryRole(
            "EXPLANATION",
            "responses",
            structured=False,
            image=False,
            prompt_source="templates.explanation_prompt() (详解 prompt)",
            instruction=_explanation_instruction,
        ),
        CanaryRole(
            "IMAGE_UNDERSTANDING",
            "responses",
            structured=False,
            image=True,
            prompt_source="templates.problem_prompt() + image detail (vision)",
            instruction=_image_instruction,
        ),
        CanaryRole(
            "ASSESSMENT_REFERENCE",
            "responses",
            structured=True,
            image=False,
            prompt_source="app/learning/compiler.py::assessment_template()",
            instruction=_assessment_instruction,
        ),
        CanaryRole(
            "COVERAGE_REVIEW",
            "chat_completions",
            structured=False,
            image=False,
            prompt_source="app/learning/coverage_review.py::deepseek_review_invoke",
            instruction=_coverage_review_instruction,
        ),
    )


ROLE_BY_NAME: dict[str, CanaryRole] = {role.role: role for role in role_plan()}


def template_ids(version: str = "V2") -> tuple[str, ...]:
    """The real professional template ids plus OTHER, straight from the registry."""
    return tuple(templates.registry(version).keys())


# ---------------------------------------------------------------------------
# Structured-output descriptors
# ---------------------------------------------------------------------------

_ASSESSMENT_REFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reference_solution": {"type": "string"},
        "grading_feedback": {"type": "string"},
    },
    "required": ["reference_solution", "grading_feedback"],
    "additionalProperties": False,
}


def _classification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "template_id": {"type": "string", "enum": list(template_ids())},
            "decision": {"type": "string", "enum": ["classified", "other"]},
            "degree_level": {
                "type": "string",
                "enum": ["undergraduate", "graduate", "unknown"],
            },
            "confidence": {"type": ["number", "null"]},
            "alternatives": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["template_id", "decision", "degree_level", "reason"],
        "additionalProperties": False,
    }


def structured_text_format(role: CanaryRole) -> dict[str, Any]:
    """The Responses ``text.format`` json_schema descriptor for a structured role."""
    if role.role == "EXERCISE_V2":
        return json_schema_text_format(
            "coursemate_exercise_v2", EXERCISE_RESPONSE_FORMAT["json_schema"]["schema"]
        )
    if role.role == "CLASSIFICATION":
        return json_schema_text_format("coursemate_classification_v1", _classification_schema())
    if role.role == "ASSESSMENT_REFERENCE":
        return json_schema_text_format(
            "coursemate_assessment_reference_v1", _ASSESSMENT_REFERENCE_SCHEMA
        )
    raise CanaryContractError(f"role {role.role!r} has no structured text format")


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _synthetic_user_content(role: CanaryRole) -> str:
    """A small, synthetic, non-private user input per role (never copied text)."""
    if role.role == "CLASSIFICATION":
        return json.dumps(
            {
                "course": {"name": "Data Science", "code": "CS3481"},
                "description": "Statistical inference and data analysis",
            },
            ensure_ascii=False,
        )
    if role.role == "EXERCISE_V2":
        return json.dumps(
            {
                "course": {"name": "Data Science", "code": "CS3481"},
                "target_node": {"title": "DBSCAN"},
            },
            ensure_ascii=False,
        )
    if role.role == "ASSESSMENT_REFERENCE":
        return json.dumps(
            {"problem": "Explain DBSCAN core points", "student_answer": "A core point."},
            ensure_ascii=False,
        )
    if role.role == "COVERAGE_REVIEW":
        return json.dumps(
            {
                "items": [
                    {
                        "item_id": "x1",
                        "requirement": "REQUIRED",
                        "objective": "o",
                        "acceptance": "a",
                    }
                ],
                "teaching_content": "content",
            },
            ensure_ascii=False,
        )
    return f"Run the {BRAND.name} " + role.role + " contract on this synthetic canary input."


def build_role_payload(
    role: CanaryRole,
    *,
    model: str,
    max_output_tokens: int,
    image_data_url: str | None = None,
    image_detail: str | None = IMAGE_DETAIL_DEFAULT,
) -> dict[str, Any]:
    """Build one DeepSeek-native request body for a role.

    Native thinking is disabled by the shared contract builders
    (``chat_completions_body`` / ``responses_body``).  Structured output rides the
    Responses ``text.format`` json_schema; images attach with ``detail`` only.
    """
    instructions = role.instruction()
    user_content = _synthetic_user_content(role)
    if role.protocol == "chat_completions":
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_content},
        ]
        if role.image:
            if not image_data_url:
                raise CanaryContractError(f"role {role.role!r} requires an image data URL")
            messages[-1]["content"] = [
                {"type": "text", "text": user_content},
                chat_completions_image_part(image_data_url, detail=image_detail),
            ]
        return chat_completions_body(
            model=model,
            messages=messages,
            max_tokens=max_output_tokens,
            stream=False,
        )
    input_value: Any = user_content
    if role.image:
        if not image_data_url:
            raise CanaryContractError(f"role {role.role!r} requires an image data URL")
        input_value = [
            {"type": "input_text", "text": user_content},
            responses_image_part(image_data_url, detail=image_detail),
        ]
    return responses_body(
        model=model,
        input=input_value,
        instructions=instructions,
        max_output_tokens=max_output_tokens,
        stream=False,
        text_format=structured_text_format(role) if role.structured else None,
    )


# ---------------------------------------------------------------------------
# Fail-closed validation
# ---------------------------------------------------------------------------


def _flatten_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _flatten_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _flatten_keys(item)
    return keys


def validate_model_alias(model: str) -> None:
    """Reject any model alias that is not the verified ``deepseek-*`` family."""
    if not model or not model.startswith("deepseek-"):
        raise CanaryContractError(
            f"model alias {model!r} is not a DeepSeek 'deepseek-*' alias"
        )


def validate_payload(
    payload: dict[str, Any],
    *,
    model: str,
    base_url: str,
    endpoint_path: str,
) -> None:
    """Fail-closed validation of one canary call before it is sent.

    Rejects any Qwen-only field, a non-DeepSeek base URL, a non-``deepseek-*``
    alias, or an endpoint path outside the two documented DeepSeek endpoints.
    """
    qwen_keys = _flatten_keys(payload) & set(QWEN_ONLY_FIELDS)
    if qwen_keys:
        raise CanaryContractError(f"Qwen-only field(s) present: {sorted(qwen_keys)}")
    validate_model_alias(model)
    try:
        validate_deepseek_base_url(base_url)
    except ValueError as error:
        raise CanaryContractError(str(error)) from error
    if endpoint_path not in (CHAT_COMPLETIONS_PATH, RESPONSES_PATH):
        raise CanaryContractError(
            f"endpoint path {endpoint_path!r} is not an allow-listed DeepSeek endpoint"
        )


def endpoint_for(base_url: str, protocol: Protocol) -> str:
    """The exact allow-listed DeepSeek endpoint URL for a protocol."""
    return base_url.rstrip("/") + (
        RESPONSES_PATH if protocol == "responses" else CHAT_COMPLETIONS_PATH
    )


# ---------------------------------------------------------------------------
# Cost ceiling
# ---------------------------------------------------------------------------


def _input_token_ceiling(payload: dict[str, Any], *, protocol_overhead_tokens: int) -> int:
    # One UTF-8 byte per token; the serialized body already embeds the instructions,
    # synthetic input and (for vision) the full image data URL, so this over-counts
    # rather than under-counts - a deliberately conservative, tokenizer-independent cap.
    return conservative_input_token_ceiling(
        "",
        json.dumps(payload, ensure_ascii=False),
        protocol_overhead_tokens=protocol_overhead_tokens,
    )


def total_cost_ceiling(plan: CanaryPlan, prices: DeepSeekPrices | None) -> float:
    """The whole-run worst-case monetary ceiling, built on ``calculate_cost_ceiling``."""
    validate_prices(prices)
    assert prices is not None
    return round(
        sum(
            calculate_cost_ceiling(
                [call.input_token_ceiling],
                max_output_tokens_per_case=call.max_output_tokens,
                input_price_per_million=prices.input_price_per_million,
                output_price_per_million=prices.output_price_per_million,
            )
            for call in plan.calls
        ),
        8,
    )


def refusal_message(*, currency: str, ceiling: float, max_cost: float) -> str | None:
    """Pure fail-closed refusal decision: refuse when the ceiling exceeds the cap."""
    if not math.isfinite(ceiling) or not math.isfinite(max_cost) or ceiling > max_cost:
        return (
            f"Refusing provider calls: conservative {currency} cost ceiling "
            f"{ceiling:.8f} exceeds approved maximum {max_cost:.8f}."
        )
    return None


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanaryCall:
    role: str
    protocol: Protocol
    endpoint: str
    payload: dict[str, Any]
    input_token_ceiling: int
    max_output_tokens: int
    worst_case_cost: float | None


@dataclass(frozen=True, slots=True)
class CanaryPlan:
    model: str
    base_url: str
    calls: tuple[CanaryCall, ...]


def plan_canary(
    *,
    model: str,
    base_url: str,
    prices: DeepSeekPrices | None,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    image_data_url: str | None = None,
    image_detail: str | None = IMAGE_DETAIL_DEFAULT,
    protocol_overhead_tokens: int = PROTOCOL_OVERHEAD_TOKENS,
) -> CanaryPlan:
    """Build the ordered call plan.

    ``prices`` may be ``None`` for a pure preflight (input-token ceilings only;
    each call's ``worst_case_cost`` stays ``None``).  Any monetary ceiling is
    computed by ``total_cost_ceiling``, which requires explicit prices and fails
    when they are missing or invalid.
    """
    validate_model_alias(model)
    validated_base_url = validate_deepseek_base_url(base_url)
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive.")
    if prices is not None:
        validate_prices(prices)
    calls: list[CanaryCall] = []
    for role in role_plan():
        payload = build_role_payload(
            role,
            model=model,
            max_output_tokens=max_output_tokens,
            image_data_url=image_data_url if role.image else None,
            image_detail=image_detail,
        )
        endpoint_path = (
            RESPONSES_PATH if role.protocol == "responses" else CHAT_COMPLETIONS_PATH
        )
        validate_payload(
            payload, model=model, base_url=validated_base_url, endpoint_path=endpoint_path
        )
        ceiling = _input_token_ceiling(payload, protocol_overhead_tokens=protocol_overhead_tokens)
        worst_case_cost = (
            calculate_cost_ceiling(
                [ceiling],
                max_output_tokens_per_case=max_output_tokens,
                input_price_per_million=prices.input_price_per_million,
                output_price_per_million=prices.output_price_per_million,
            )
            if prices is not None
            else None
        )
        calls.append(
            CanaryCall(
                role=role.role,
                protocol=role.protocol,
                endpoint=endpoint_for(validated_base_url, role.protocol),
                payload=payload,
                input_token_ceiling=ceiling,
                max_output_tokens=max_output_tokens,
                worst_case_cost=worst_case_cost,
            )
        )
    return CanaryPlan(model=model, base_url=validated_base_url, calls=tuple(calls))


# ---------------------------------------------------------------------------
# Response validation and execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidatedResponse:
    model: str
    input_tokens: int
    output_tokens: int
    text: str
    structured: dict[str, Any] | None


def validate_response(role: CanaryRole, raw: dict[str, Any]) -> ValidatedResponse:
    """Extract observed model id, usage, text and (when structured) parsed JSON.

    Raises :class:`UnusableResponseError` when the response cannot be turned into
    usable evidence - never crashes, never invents usage.
    """
    if not isinstance(raw, dict):
        raise UnusableResponseError("response is not a JSON object")
    if role.protocol == "responses":
        if raw.get("status") != "completed":
            raise UnusableResponseError(f"response status {raw.get('status')!r} is not completed")
        model = str(raw.get("model") or "")
        usage = raw.get("usage") or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        text = str(raw.get("output_text") or "")
    else:
        choices = raw.get("choices") or []
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise UnusableResponseError("response lacks a usable choices entry")
        choice = choices[0]
        if choice.get("finish_reason") not in (None, "stop"):
            raise UnusableResponseError(f"finish_reason {choice.get('finish_reason')!r}")
        model = str(raw.get("model") or "")
        usage = raw.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        text = str((choice.get("message") or {}).get("content") or "")
    if not model:
        raise UnusableResponseError("response is missing the observed model id")
    structured: dict[str, Any] | None = None
    if role.structured:
        if not text.strip():
            raise UnusableResponseError("structured response is empty")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as error:
            raise UnusableResponseError(
                f"structured output is not valid JSON: {error.msg}"
            ) from error
        if not isinstance(parsed, dict):
            raise UnusableResponseError("structured output is not a JSON object")
        structured = parsed
    elif not text.strip():
        raise UnusableResponseError("response text is empty")
    return ValidatedResponse(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        text=text,
        structured=structured,
    )


Transport = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CanaryCallResult:
    role: str
    status: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    observed_model: str | None
    cost: float
    structured_output: dict[str, Any] | None = None
    error_class: str | None = None


def run_canary_call(
    call: CanaryCall,
    *,
    transport: Transport,
    prices: DeepSeekPrices,
    clock: Callable[[], float] = perf_counter,
) -> CanaryCallResult:
    """Execute one call through the injected transport and validate it.

    The transport performs the network request (the real one lives in the CLI);
    this function only orchestrates, times and validates.  A transport or
    contract failure becomes a typed ``failed`` result - never a crash.
    """
    role = ROLE_BY_NAME[call.role]
    started = clock()
    try:
        raw = transport(call.endpoint, call.payload)
    except Exception as error:  # noqa: BLE001 - the failure is recorded as typed evidence
        return CanaryCallResult(
            role=call.role,
            status="failed",
            latency_ms=round((clock() - started) * 1000, 3),
            input_tokens=0,
            output_tokens=0,
            observed_model=None,
            cost=0.0,
            error_class=type(error).__name__,
        )
    latency_ms = round((clock() - started) * 1000, 3)
    try:
        validated = validate_response(role, raw)
    except CanaryContractError as error:
        return CanaryCallResult(
            role=call.role,
            status="failed",
            latency_ms=latency_ms,
            input_tokens=0,
            output_tokens=0,
            observed_model=None,
            cost=0.0,
            error_class=type(error).__name__,
        )
    cost = round(
        (validated.input_tokens * prices.input_price_per_million
         + validated.output_tokens * prices.output_price_per_million)
        / 1_000_000,
        8,
    )
    return CanaryCallResult(
        role=call.role,
        status="completed",
        latency_ms=latency_ms,
        input_tokens=validated.input_tokens,
        output_tokens=validated.output_tokens,
        observed_model=validated.model,
        cost=cost,
        structured_output=validated.structured,
    )


def actual_cost(results: list[CanaryCallResult]) -> float:
    """The estimated cost actually incurred across completed calls."""
    return round(sum(result.cost for result in results), 8)


def call_evidence(result: CanaryCallResult) -> dict[str, Any]:
    """One per-call evidence record (never contains credentials or prompt text)."""
    record: dict[str, Any] = {
        "role": result.role,
        "status": result.status,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "observed_model": result.observed_model,
        "cost": result.cost,
    }
    if result.structured_output is not None:
        record["structured_output"] = result.structured_output
    if result.error_class is not None:
        record["error_class"] = result.error_class
    return record


def build_evidence(
    plan: CanaryPlan,
    results: list[CanaryCallResult],
    *,
    prices: DeepSeekPrices | None,
    status: str,
    live_verification: str,
    started_at: str,
    finished_at: str | None = None,
    approved_max_cost: float | None = None,
) -> dict[str, Any]:
    """Assemble the complete evidence record for a run (or a partial checkpoint)."""
    ceiling = total_cost_ceiling(plan, prices) if prices is not None else None
    return {
        "artifact_version": ARTIFACT_VERSION,
        "status": status,
        "live_verification": live_verification,
        "started_at": started_at,
        "finished_at": finished_at,
        "provider": "DEEPSEEK_API",
        "model": plan.model,
        "base_url": plan.base_url,
        "plan": [
            {
                "role": call.role,
                "protocol": call.protocol,
                "endpoint": call.endpoint,
                "input_token_ceiling": call.input_token_ceiling,
                "max_output_tokens": call.max_output_tokens,
                "worst_case_cost": call.worst_case_cost,
            }
            for call in plan.calls
        ],
        "prices": (
            {
                "currency": prices.currency,
                "input_price_per_million": prices.input_price_per_million,
                "output_price_per_million": prices.output_price_per_million,
                "price_basis": "OWNER_SUPPLIED_AT_RUN_TIME",
            }
            if prices is not None
            else None
        ),
        "cost_ceiling": ceiling,
        "approved_max_cost": approved_max_cost,
        "actual_estimated_cost": actual_cost(results),
        "calls": [call_evidence(result) for result in results],
        "manual_review_status": "REQUIRED" if results else "NOT_APPLICABLE",
    }


def run_canary(
    plan: CanaryPlan,
    *,
    transport: Transport,
    prices: DeepSeekPrices,
    on_call: Callable[[list[CanaryCallResult]], None] | None = None,
) -> list[CanaryCallResult]:
    """Execute the full plan through the injected transport, checkpointing per call."""
    results: list[CanaryCallResult] = []
    for call in plan.calls:
        results.append(run_canary_call(call, transport=transport, prices=prices))
        if on_call is not None:
            on_call(list(results))
        if results[-1].status != "completed":
            # Fail-closed: a failed or malformed call stops the run.  There is
            # no retry and no resume, so no further provider calls are made.
            break
    return results
