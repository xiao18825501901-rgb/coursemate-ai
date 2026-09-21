"""Offline tests for the DeepSeek generation canary.

No network: every provider interaction goes through a fake transport, and the
CLI is exercised only via ``--preflight-only`` or refusal paths that return
before any client is built.  These tests pin the fail-closed contract - no
Qwen-only fields, native thinking disabled, explicit owner prices, a ceiling
computed before any call, and credentials that never reach the evidence file.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.cm_update import templates
from app.evaluation.deepseek_canary import (
    ROLE_BY_NAME,
    CanaryContractError,
    DeepSeekPrices,
    UnusableResponseError,
    build_evidence,
    build_role_payload,
    plan_canary,
    refusal_message,
    role_plan,
    run_canary,
    template_ids,
    total_cost_ceiling,
    validate_payload,
    validate_response,
)
from app.evaluation.model_benchmark import calculate_cost_ceiling

ROOT = Path(__file__).parents[3]
RUNNER = ROOT / "scripts" / "run_deepseek_canary.py"
BASE_URL = "https://api.deepseek.com"
IMAGE_DATA_URL = "data:image/png;base64," + base64.b64encode(b"tiny-canary-png").decode()
QWEN_ONLY = ("enable_thinking", "max_pixels")


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


def _prices() -> DeepSeekPrices:
    return DeepSeekPrices(2.0, 8.0, "USD")


# ---------------------------------------------------------------------------
# Role plan
# ---------------------------------------------------------------------------


def test_role_plan_covers_every_migrated_production_role_once() -> None:
    plan = role_plan()
    roles = [role.role for role in plan]
    expected = {
        "KNOWLEDGE_QA",
        "PLAN",
        "WORK",
        "CLASSIFICATION",
        "EXERCISE_V2",
        "PROBLEM",
        "EXPLANATION",
        "IMAGE_UNDERSTANDING",
        "ASSESSMENT_REFERENCE",
        "COVERAGE_REVIEW",
    }
    assert len(roles) == len(set(roles)) == 10
    assert set(roles) == expected

    by_name = {role.role: role for role in plan}
    assert by_name["KNOWLEDGE_QA"].protocol == "chat_completions"
    assert by_name["COVERAGE_REVIEW"].protocol == "chat_completions"
    for role_name in (
        "PLAN",
        "WORK",
        "CLASSIFICATION",
        "EXERCISE_V2",
        "PROBLEM",
        "EXPLANATION",
        "IMAGE_UNDERSTANDING",
        "ASSESSMENT_REFERENCE",
    ):
        assert by_name[role_name].protocol == "responses"
    assert by_name["CLASSIFICATION"].structured is True
    assert by_name["EXERCISE_V2"].structured is True
    assert by_name["ASSESSMENT_REFERENCE"].structured is True
    assert by_name["IMAGE_UNDERSTANDING"].image is True
    assert all(not role.image for role in plan if role.role != "IMAGE_UNDERSTANDING")


def test_role_plan_references_real_template_and_prompt_loaders() -> None:
    by_name = {role.role: role for role in role_plan()}
    assert by_name["PROBLEM"].instruction() == templates.problem_prompt()
    assert by_name["EXPLANATION"].instruction() == templates.explanation_prompt()
    assert by_name["PLAN"].instruction() == templates.plan_writer_instruction()

    exercise = by_name["EXERCISE_V2"].instruction()
    assert templates.exercise_prompt() in exercise
    assert templates.exercise_runtime_contract() in exercise

    classification = by_name["CLASSIFICATION"].instruction()
    for template_id in template_ids():
        assert template_id in classification


def test_template_ids_match_the_registry() -> None:
    ids = template_ids()
    assert ids == tuple(templates.registry("V2").keys())
    assert len(ids) == 15
    assert set(ids) == {f"{i:02d}" for i in range(1, 15)} | {"OTHER"}


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def test_chat_completions_payload_is_deepseek_native_and_thinking_disabled() -> None:
    payload = build_role_payload(
        ROLE_BY_NAME["KNOWLEDGE_QA"], model="deepseek-flash", max_output_tokens=512
    )
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["stream"] is False
    assert not (_flatten_keys(payload) & set(QWEN_ONLY))


def test_responses_payload_is_deepseek_native_and_reasoning_disabled() -> None:
    payload = build_role_payload(
        ROLE_BY_NAME["PLAN"], model="deepseek-flash", max_output_tokens=512
    )
    assert payload["model"] == "deepseek-flash"
    assert payload["reasoning"] == {"effort": "none"}
    assert "input" in payload and "max_output_tokens" in payload
    assert not (_flatten_keys(payload) & set(QWEN_ONLY))


def test_every_role_payload_emits_only_deepseek_native_fields() -> None:
    for role in role_plan():
        payload = build_role_payload(
            role,
            model="deepseek-flash",
            max_output_tokens=512,
            image_data_url=IMAGE_DATA_URL if role.image else None,
        )
        keys = _flatten_keys(payload)
        assert not (keys & set(QWEN_ONLY)), role.role
        if role.protocol == "chat_completions":
            assert payload["thinking"] == {"type": "disabled"}
        else:
            assert payload["reasoning"] == {"effort": "none"}
        validate_payload(
            payload,
            model="deepseek-flash",
            base_url=BASE_URL,
            endpoint_path="/chat/completions"
            if role.protocol == "chat_completions"
            else "/responses",
        )


def test_exercise_v2_payload_uses_text_format_json_schema_without_strict() -> None:
    payload = build_role_payload(
        ROLE_BY_NAME["EXERCISE_V2"], model="deepseek-flash", max_output_tokens=512
    )
    fmt = payload["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["name"] == "coursemate_exercise_v2"
    assert "strict" not in fmt
    assert not (_flatten_keys(payload) & set(QWEN_ONLY))


def test_image_payload_attaches_detail_and_never_max_pixels() -> None:
    payload = build_role_payload(
        ROLE_BY_NAME["IMAGE_UNDERSTANDING"],
        model="deepseek-flash",
        max_output_tokens=512,
        image_data_url=IMAGE_DATA_URL,
        image_detail="low",
    )
    parts = payload["input"]
    image_part = next(part for part in parts if part.get("type") == "input_image")
    assert image_part["image_url"] == IMAGE_DATA_URL
    assert image_part["detail"] == "low"
    assert not (_flatten_keys(payload) & set(QWEN_ONLY))


def test_image_role_requires_an_image_data_url() -> None:
    with pytest.raises(CanaryContractError):
        build_role_payload(
            ROLE_BY_NAME["IMAGE_UNDERSTANDING"],
            model="deepseek-flash",
            max_output_tokens=512,
        )


# ---------------------------------------------------------------------------
# Fail-closed validation
# ---------------------------------------------------------------------------


def _valid_payload() -> dict:
    return build_role_payload(
        ROLE_BY_NAME["PROBLEM"], model="deepseek-flash", max_output_tokens=512
    )


def test_validator_rejects_qwen_only_fields() -> None:
    for field in QWEN_ONLY:
        payload = {**_valid_payload(), field: False}
        with pytest.raises(CanaryContractError):
            validate_payload(
                payload,
                model="deepseek-flash",
                base_url=BASE_URL,
                endpoint_path="/responses",
            )


def test_validator_rejects_non_deepseek_base_url() -> None:
    with pytest.raises(CanaryContractError):
        validate_payload(
            _valid_payload(),
            model="deepseek-flash",
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            endpoint_path="/responses",
        )


def test_validator_rejects_non_deepseek_alias() -> None:
    with pytest.raises(CanaryContractError):
        validate_payload(
            _valid_payload(),
            model="qwen3.8-max",
            base_url=BASE_URL,
            endpoint_path="/responses",
        )


def test_validator_rejects_bad_endpoint_path() -> None:
    with pytest.raises(CanaryContractError):
        validate_payload(
            _valid_payload(),
            model="deepseek-flash",
            base_url=BASE_URL,
            endpoint_path="/v1/responses",
        )


# ---------------------------------------------------------------------------
# Cost ceiling
# ---------------------------------------------------------------------------


def test_total_cost_ceiling_builds_on_calculate_cost_ceiling() -> None:
    prices = _prices()
    plan = plan_canary(
        model="deepseek-flash",
        base_url=BASE_URL,
        prices=prices,
        image_data_url=IMAGE_DATA_URL,
    )
    ceiling = total_cost_ceiling(plan, prices)
    expected = round(
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
    assert ceiling == expected
    assert ceiling > 0
    for call in plan.calls:
        assert call.worst_case_cost == calculate_cost_ceiling(
            [call.input_token_ceiling],
            max_output_tokens_per_case=call.max_output_tokens,
            input_price_per_million=prices.input_price_per_million,
            output_price_per_million=prices.output_price_per_million,
        )


def test_plan_canary_and_cost_ceiling_fail_without_prices() -> None:
    plan = plan_canary(
        model="deepseek-flash", base_url=BASE_URL, prices=None, image_data_url=IMAGE_DATA_URL
    )
    assert all(call.worst_case_cost is None for call in plan.calls)
    with pytest.raises(CanaryContractError):
        total_cost_ceiling(plan, None)
    with pytest.raises(CanaryContractError):
        total_cost_ceiling(plan, DeepSeekPrices(0.0, 0.0, "USD"))


def test_refusal_message_refuses_when_ceiling_exceeds_max_cost() -> None:
    assert refusal_message(currency="USD", ceiling=1.5, max_cost=1.0) is not None
    assert "exceeds approved maximum" in refusal_message(
        currency="USD", ceiling=1.5, max_cost=1.0
    )
    assert refusal_message(currency="USD", ceiling=1.0, max_cost=1.0) is None
    assert refusal_message(currency="USD", ceiling=0.5, max_cost=1.0) is None


def test_plan_canary_computes_the_ceiling_before_any_call() -> None:
    prices = _prices()
    plan = plan_canary(
        model="deepseek-flash",
        base_url=BASE_URL,
        prices=prices,
        image_data_url=IMAGE_DATA_URL,
    )
    assert len(plan.calls) == 10
    assert all(call.input_token_ceiling > 0 for call in plan.calls)
    assert all(call.worst_case_cost is not None for call in plan.calls)
    assert total_cost_ceiling(plan, prices) > 0


# ---------------------------------------------------------------------------
# Response validation and execution
# ---------------------------------------------------------------------------


def _responses_response(text: str) -> dict:
    return {
        "model": "deepseek-flash",
        "status": "completed",
        "output_text": text,
        "usage": {"input_tokens": 7, "output_tokens": 8},
    }


def test_validate_response_extracts_model_usage_and_structured_payload() -> None:
    validated = validate_response(
        ROLE_BY_NAME["EXERCISE_V2"],
        _responses_response('{"question": "q", "answer_steps": [], "references": []}'),
    )
    assert validated.model == "deepseek-flash"
    assert validated.input_tokens == 7
    assert validated.output_tokens == 8
    assert validated.structured == {"question": "q", "answer_steps": [], "references": []}


def test_validate_response_raises_typed_error_on_malformed_response() -> None:
    with pytest.raises(UnusableResponseError):
        validate_response(ROLE_BY_NAME["KNOWLEDGE_QA"], {"unexpected": "shape"})
    with pytest.raises(UnusableResponseError):
        validate_response(
            ROLE_BY_NAME["EXERCISE_V2"],
            _responses_response("this is not json"),
        )


def _fake_transport(endpoint: str, payload: dict) -> dict:
    if "/chat/completions" in endpoint:
        return {
            "model": "deepseek-flash",
            "choices": [{"message": {"content": "answer [S1]"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }
    structured = payload.get("text", {}).get("format", {}).get("type") == "json_schema"
    text = '{"template_id": "03", "decision": "classified"}' if structured else "answer"
    return _responses_response(text)


def test_fake_transport_yields_a_complete_evidence_record() -> None:
    prices = _prices()
    plan = plan_canary(
        model="deepseek-flash",
        base_url=BASE_URL,
        prices=prices,
        image_data_url=IMAGE_DATA_URL,
    )
    results = run_canary(plan, transport=_fake_transport, prices=prices)
    evidence = build_evidence(
        plan,
        results,
        prices=prices,
        status="LIVE_CALLS_COMPLETED_MANUAL_REVIEW_REQUIRED",
        live_verification="PENDING_HUMAN_QUALITY_REVIEW",
        started_at="2026-09-21T00:00:00Z",
        approved_max_cost=1.0,
    )

    assert len(results) == len(plan.calls) == 10
    assert all(result.status == "completed" for result in results)
    assert len(evidence["calls"]) == 10
    assert all(call["observed_model"] == "deepseek-flash" for call in evidence["calls"])
    assert evidence["cost_ceiling"] > 0
    assert evidence["live_verification"] == "PENDING_HUMAN_QUALITY_REVIEW"
    assert evidence["plan"] and len(evidence["plan"]) == 10


def test_malformed_transport_yields_a_typed_failure_without_crashing() -> None:
    prices = _prices()
    plan = plan_canary(
        model="deepseek-flash",
        base_url=BASE_URL,
        prices=prices,
        image_data_url=IMAGE_DATA_URL,
    )

    def malformed_transport(endpoint: str, payload: dict) -> dict:
        return {"unexpected": "shape"}

    results = run_canary(plan, transport=malformed_transport, prices=prices)
    assert len(results) == 1  # fail-closed: stops after the first malformed response
    assert results[0].status == "failed"
    assert results[0].error_class == "UnusableResponseError"


def test_evidence_never_contains_credentials() -> None:
    prices = _prices()
    sentinel = "sk-deepseek-canary-sentinel-123"
    plan = plan_canary(
        model="deepseek-flash",
        base_url=BASE_URL,
        prices=prices,
        image_data_url=IMAGE_DATA_URL,
    )
    results = run_canary(plan, transport=_fake_transport, prices=prices)
    evidence = build_evidence(
        plan,
        results,
        prices=prices,
        status="LIVE_CALLS_COMPLETED_MANUAL_REVIEW_REQUIRED",
        live_verification="PENDING_HUMAN_QUALITY_REVIEW",
        started_at="2026-09-21T00:00:00Z",
    )
    rendered = json.dumps(evidence, ensure_ascii=False)
    assert sentinel not in rendered
    assert "api_key" not in rendered.casefold()
    assert "authorization" not in rendered.casefold()
    assert "bearer" not in rendered.casefold()


# ---------------------------------------------------------------------------
# CLI (subprocess)
# ---------------------------------------------------------------------------


def _run_cli(tmp_path: Path, *extra: str, key: str | None = None) -> tuple:
    output = tmp_path / "evidence.json"
    command = [sys.executable, str(RUNNER), "--out", str(output), *extra]
    env = {name: value for name, value in os.environ.items() if name != "DEEPSEEK_API_KEY"}
    if key is not None:
        env["DEEPSEEK_API_KEY"] = key
    process = subprocess.run(
        command, check=False, capture_output=True, text=True, env=env
    )
    return process, output


def test_cli_preflight_exits_zero_without_key_and_never_writes_output(
    tmp_path: Path,
) -> None:
    process, output = _run_cli(tmp_path, "--preflight-only")
    assert process.returncode == 0, process.stdout + process.stderr
    assert "preflight" in process.stdout.casefold()
    assert "input-token ceiling" in process.stdout
    assert "deepseek-flash" in process.stdout
    assert not output.exists()


def test_cli_refuses_billable_without_a_key(tmp_path: Path) -> None:
    process, output = _run_cli(tmp_path, "--allow-billable")
    assert process.returncode == 2
    assert "DEEPSEEK_API_KEY" in process.stdout
    assert not output.exists()


def test_cli_refuses_when_the_ceiling_exceeds_max_cost(tmp_path: Path) -> None:
    process, output = _run_cli(
        tmp_path,
        "--allow-billable",
        "--input-price-per-million",
        "1",
        "--output-price-per-million",
        "1",
        "--max-cost",
        "0.00000001",
        "--currency",
        "USD",
        key="not-a-real-key",
    )
    assert process.returncode == 2
    assert "exceeds approved maximum" in process.stdout
    assert "not-a-real-key" not in process.stdout + process.stderr
    assert not output.exists()
