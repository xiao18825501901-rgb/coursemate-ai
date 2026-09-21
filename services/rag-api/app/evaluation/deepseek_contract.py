"""Verified DeepSeek API contract and per-role payload builders.

This module is the single source of truth for the DeepSeek generation contract
in CourseMate.  Every value here was read from the official DeepSeek API
reference on the verification date below; nothing is inferred from a model's
self-description, an SDK type signature, or an out-of-date cache.

Verified sources (all fetched 2026-09-21, UTC+08:00):

* https://api-docs.deepseek.com/updates/           -> model alias + release
* https://api-docs.deepseek.com/guides/responses_api/ -> Responses API contract
* https://api-docs.deepseek.com/api/create-response/  -> Responses body/fields
* https://api-docs.deepseek.com/guides/vision/     -> image schema + limits
* https://api-docs.deepseek.com/guides/thinking_mode/ -> native thinking toggle
* https://api-docs.deepseek.com/guides/json_mode/  -> Chat Completions JSON mode
* https://api-docs.deepseek.com/quick_start/pricing/   -> model + features

Anything not documented on those pages is marked UNKNOWN, never invented.
"""

from __future__ import annotations

from typing import Any, Literal

VERIFICATION_DATE = "2026-09-21"

# The current stable, default generation model.  ``deepseek-flash`` is the API
# alias for DeepSeek-V4.1-Flash (released 2026-09-10); the retired
# ``deepseek-v4-flash`` / ``deepseek-v4-flash-vision-exp`` names route to it.
MODEL_ALIAS = "deepseek-flash"
MODEL_VERSION = "DeepSeek-V4.1-Flash"

API_HOST = "api.deepseek.com"
API_BASE_URL = "https://api.deepseek.com"

# Endpoint paths relative to API_BASE_URL (documented on the pages above).
CHAT_COMPLETIONS_PATH = "/chat/completions"
RESPONSES_PATH = "/responses"

# Documented image contract (Vision guide + create-response reference).  The
# field is ``detail`` (low/high/original/auto); there is NO ``max_pixels``.
IMAGE_FORMATS = ("JPEG", "PNG", "GIF", "WebP")
IMAGE_DETAIL_LEVELS = ("low", "high", "original", "auto")
# Documented upper bound: every image is resized so it consumes at most 1024
# tokens.  Used only for the conservative preflight estimate, never as a limit.
IMAGE_TOKENS_PER_INPUT = 1024

# Native reasoning control.  Thinking mode is ON by default; the product keeps
# native reasoning explicitly OFF and implements its own two-stage plan->work,
# so every generation role disables it explicitly rather than silently relying
# on the provider default (which would leak chain-of-thought items).
REASONING_DISABLED = {"effort": "none"}
# Chat Completions spelling of the same explicit "native thinking off" policy.
THINKING_DISABLED = {"type": "disabled"}


class DeepSeekCapabilityError(Exception):
    """A role requested a capability DeepSeek does not document for its protocol.

    Raised instead of silently switching provider (e.g. falling back to Qwen or
    OpenAI).  The message names the role, capability and protocol so the failure
    is actionable without echoing credentials or private content.
    """

    def __init__(self, role: str, capability: str, protocol: str, *, detail: str = "") -> None:
        self.role = role
        self.capability = capability
        self.protocol = protocol
        message = (
            f"DeepSeek capability '{capability}' for role '{role}' is not available "
            f"on the {protocol} protocol"
        )
        if detail:
            message += f": {detail}"
        super().__init__(message)


# --------------------------------------------------------------------------
# Capability matrix (role x capability x evidence level).  Evidence levels:
#   OFFLINE_CONTRACT  - read and pinned from the official reference pages above.
#   LIVE_VERIFIED     - proven against the real API (none yet: no credentials).
#   NOT_RUN           - requires a real credential/authorization to exercise.
# --------------------------------------------------------------------------

EvidenceLevel = Literal["OFFLINE_CONTRACT", "LIVE_VERIFIED", "NOT_RUN"]

# Every generation role resolves to deepseek-flash.  There is no per-role model
# string to drift: a role either uses this alias or raises a typed error.
ROLE_MODEL = "deepseek-flash"

# Protocol each role uses by default (documented on the reference pages).
ROLE_PROTOCOL: dict[str, str] = {
    "ui_teach": "responses",
    "ui_exercise": "responses",  # json_schema structured output -> Responses text.format
    "ui_explanation": "responses",
    "ui_classification": "responses",
    "learning_structured": "responses",  # V3 plan/unit/problem/grade structured outputs
    "coverage_review": "chat_completions",
    "rag_qa": "responses",
    "agent": "responses",
}

# Capability x evidence level, one row per (role, protocol, capability).
CAPABILITY_MATRIX: dict[str, dict[str, EvidenceLevel]] = {
    # Chat Completions capabilities (documented for deepseek-flash).
    "chat_completions": {
        "text": "OFFLINE_CONTRACT",
        "text_streaming": "OFFLINE_CONTRACT",
        "json_object_response_format": "OFFLINE_CONTRACT",
        "json_schema_response_format": "NOT_RUN",  # json_schema documented on Responses, not Chat Completions
        "image_input": "OFFLINE_CONTRACT",
        "tool_calls": "OFFLINE_CONTRACT",
        "thinking_toggle": "OFFLINE_CONTRACT",
        "usage": "OFFLINE_CONTRACT",
    },
    # Responses API capabilities (documented for deepseek-flash).
    "responses": {
        "text": "OFFLINE_CONTRACT",
        "text_streaming": "OFFLINE_CONTRACT",
        "text_format_json_schema": "OFFLINE_CONTRACT",
        "image_input": "OFFLINE_CONTRACT",
        "function_tools": "OFFLINE_CONTRACT",
        "function_call_replay": "OFFLINE_CONTRACT",
        "reasoning_effort_control": "OFFLINE_CONTRACT",
        "usage_including_cached_and_reasoning": "OFFLINE_CONTRACT",
        "status_completed_incomplete_failed": "OFFLINE_CONTRACT",
    },
    # Live verification (requires a real DeepSeek credential + authorized budget).
    "live": {
        "text_streaming_live": "NOT_RUN",
        "structured_json_schema_live": "NOT_RUN",
        "image_vision_live": "NOT_RUN",
        "tool_call_replay_live": "NOT_RUN",
        "pricing_and_billing_live": "NOT_RUN",
    },
}


def json_schema_text_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Build the Responses ``text.format`` structured-output descriptor.

    DeepSeek documents ``text.format`` values ``{"type": "text"}`` (default),
    ``{"type": "json_object"}`` and ``{"type": "json_schema", "name": ..., "schema": ...}``.
    There is no documented ``strict`` flag, so none is sent.
    """
    return {"type": "json_schema", "name": name, "schema": schema}


def chat_completions_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    stream: bool,
    response_format: dict[str, Any] | None = None,
    thinking_disabled: bool = True,
) -> dict[str, Any]:
    """Build a DeepSeek Chat Completions request body.

    Qwen-only fields (``enable_thinking``, ``max_pixels``) are never emitted.
    Native thinking is explicitly disabled (``thinking: {"type": "disabled"}``)
    to preserve the product's two-stage plan->work contract.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens,
    }
    if thinking_disabled:
        body["thinking"] = THINKING_DISABLED
    if response_format is not None:
        format_type = response_format.get("type")
        if format_type == "json_object":
            body["response_format"] = response_format
        elif format_type == "json_schema":
            raise DeepSeekCapabilityError(
                "generic",
                "json_schema_response_format",
                "chat_completions",
                detail="use the Responses text.format json_schema instead",
            )
        else:
            raise DeepSeekCapabilityError(
                "generic",
                f"response_format type {format_type!r}",
                "chat_completions",
                detail="only json_object is documented",
            )
    return body


def responses_body(
    *,
    model: str,
    input: Any,
    instructions: str | None = None,
    max_output_tokens: int,
    stream: bool,
    text_format: dict[str, Any] | None = None,
    reasoning: dict[str, Any] | None = REASONING_DISABLED,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a DeepSeek Responses API request body.

    Qwen-only fields are never emitted.  ``text.format`` carries the optional
    json_schema structured-output descriptor; ``reasoning`` is explicitly set to
    ``{"effort": "none"}`` (native thinking off).
    """
    body: dict[str, Any] = {
        "model": model,
        "input": input,
        "stream": stream,
        "max_output_tokens": max_output_tokens,
    }
    if instructions is not None:
        body["instructions"] = instructions
    if text_format is not None:
        body["text"] = {"format": text_format}
    if reasoning is not None:
        body["reasoning"] = reasoning
    if tools is not None:
        body["tools"] = tools
    return body


def chat_completions_image_part(data_url: str, *, detail: str | None = None) -> dict[str, Any]:
    """Chat Completions image content part.  ``detail`` only; no ``max_pixels``."""
    image_url: dict[str, Any] = {"url": data_url}
    if detail is not None:
        image_url["detail"] = detail
    return {"type": "image_url", "image_url": image_url}


def responses_image_part(data_url: str, *, detail: str | None = None) -> dict[str, Any]:
    """Responses ``input_image`` content part.  Flat ``image_url`` + ``detail``."""
    part: dict[str, Any] = {"type": "input_image", "image_url": data_url}
    if detail is not None:
        part["detail"] = detail
    return part
