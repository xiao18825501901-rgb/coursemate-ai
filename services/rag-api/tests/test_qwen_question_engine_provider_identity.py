import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.learning.blind_solve import BlindSolveProviderRun
from app.learning.deepseek_reviewer import StrongReviewRun
from app.learning.generic_provider import build_generic_provider
from app.learning.provider_identity import verified_structured_provider
from app.learning.question_author import AuthorProviderRun


def run_payload(**updates):
    payload = {
        "model": "qwen3.8-max",
        "provider": "ALIBABA_MODEL_STUDIO_COMPATIBLE",
        "protocol": "chat_completions",
        "region": "ENDPOINT_CN",
        "role": "QUESTION_AUTHOR",
        "template_version": "question-author.v5",
        "schema_version": "question-author-output.v4",
        "input_hash": "a" * 64,
        "started_at": "2026-10-17T00:00:00Z",
        "finished_at": "2026-10-17T00:00:01Z",
        "latency_ms": 1000,
        "input_tokens": 10,
        "output_tokens": 20,
        "provider_response_id": "TEST_ONLY-response",
        "status": "COMPLETED",
        "error_class": None,
    }
    payload.update(updates)
    return payload


def test_exact_qwen_identity_is_accepted_by_all_three_question_engine_receipts():
    assert AuthorProviderRun.model_validate(run_payload()).model == "qwen3.8-max"
    blind = run_payload(
        role="QUESTION_BLIND_SOLVER",
        template_version="blind-solver.v1",
        schema_version="blind-solve-output.v1",
    )
    assert BlindSolveProviderRun.model_validate(blind).model == "qwen3.8-max"
    review = run_payload(
        role="EVIDENCE_AUDIT",
        template_version="evidence-audit.v1",
        schema_version="coursejesus-judge-findings.v3",
    )
    assert StrongReviewRun.model_validate(review).model == "qwen3.8-max"


@pytest.mark.parametrize(
    "updates",
    [
        {"model": "qwen3.8-plus"},
        {"provider": "client-claimed-qwen"},
        {"protocol": "responses"},
        {"region": "ENDPOINT_UNVERIFIED"},
    ],
)
def test_qwen_receipt_rejects_any_non_exact_identity(updates):
    with pytest.raises(ValidationError):
        AuthorProviderRun.model_validate(run_payload(**updates))


def test_live_qwen_adapter_requires_server_capability_and_secret_lineage():
    settings = Settings(
        _env_file=None,
        app_env="development",
        generic_llm_enabled=True,
        cj_qwen_api_key=SecretStr("TEST_ONLY-placeholder"),
        cj_qwen_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        cj_qwen_capability_receipt_id="TEST_ONLY-capability",
        cj_qwen_secret_generation_id="TEST_ONLY-generation",
    )
    assert verified_structured_provider(build_generic_provider(settings)) is True

    unqualified = build_generic_provider(settings)
    unqualified.settings = unqualified.settings.model_copy(
        update={"cj_qwen_capability_receipt_id": ""}
    )
    assert verified_structured_provider(unqualified) is False
