from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.visual.providers.aliyun_eas import (
    AlibabaEASComfyProvider,
    ProviderAuthenticationError,
    ProviderProtocolError,
)
from app.visual.providers.base import ProviderState
from app.visual.workflows import WorkflowRegistry

REGISTRY = Path(__file__).parents[1] / "app" / "visual" / "workflows" / "registry.example.json"


def _provider(handler) -> AlibabaEASComfyProvider:
    registry = WorkflowRegistry.load(REGISTRY)
    workflow = registry.select_by_id("coursejesus-comfy-image-v1", "1")
    return AlibabaEASComfyProvider(
        endpoint="https://eas.example.invalid",
        token="secret-token-must-not-leak",
        workflow=workflow,
        timeout_seconds=3.0,
        max_output_bytes=1024 * 1024,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _compiled() -> dict[str, object]:
    return {
        "positive_prompt": "a grounded CPU pipeline illustration",
        "negative_prompt": "watermark, unsafe text",
        "seed": 123,
        "width": 768,
        "height": 512,
        "steps": 24,
        "cfg": 7.5,
    }


def test_submit_uses_raw_eas_authorization_and_only_allowlisted_bindings() -> None:
    expected_prompt_id = _provider(lambda _request: httpx.Response(500)).job_id_for(
        "visual-job-1"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/prompt"
        assert request.headers["authorization"] == "secret-token-must-not-leak"
        body = json.loads(request.content)
        assert set(body) == {"prompt", "client_id", "prompt_id"}
        assert body["prompt_id"] == expected_prompt_id
        assert body["client_id"] == expected_prompt_id
        prompt = body["prompt"]
        assert prompt["4"]["inputs"]["ckpt_name"] == "Anything-v5.0-PRT-RE.safetensors"
        assert prompt["6"]["inputs"]["text"] == _compiled()["positive_prompt"]
        assert prompt["7"]["inputs"]["text"] == _compiled()["negative_prompt"]
        assert prompt["3"]["inputs"]["seed"] == 123
        assert prompt["3"]["inputs"]["steps"] == 24
        assert prompt["3"]["inputs"]["cfg"] == 7.5
        assert prompt["5"]["inputs"]["width"] == 768
        assert prompt["5"]["inputs"]["height"] == 512
        return httpx.Response(200, json={"prompt_id": expected_prompt_id})

    job = _provider(handler).submit(_compiled(), idempotency_key="visual-job-1")
    assert job.id == expected_prompt_id


def test_submit_rejects_a_different_prompt_id_from_comfyui() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200, json={"prompt_id": "11111111-1111-4111-8111-111111111111"}
        )
    )
    with pytest.raises(ProviderProtocolError, match="PROMPT_ID_MISMATCH"):
        provider.submit(_compiled(), idempotency_key="visual-job-1")


@pytest.mark.parametrize("status", [429, 450, 503])
def test_explicit_gateway_rejection_is_a_safe_renderer_wait(status: int) -> None:
    from app.visual.providers.aliyun_eas import ProviderRendererUnavailable

    provider = _provider(lambda _request: httpx.Response(status, text="not accepted"))
    with pytest.raises(ProviderRendererUnavailable) as caught:
        provider.submit(_compiled(), idempotency_key="visual-job-1")
    assert caught.value.safe_to_retry is True
    assert caught.value.status_code == status


@pytest.mark.parametrize("status", [401, 403])
def test_submit_rejects_invalid_eas_token_without_exposing_it(status: int) -> None:
    provider = _provider(lambda _request: httpx.Response(status, text="denied"))
    with pytest.raises(ProviderAuthenticationError) as caught:
        provider.submit(_compiled(), idempotency_key="visual-job-1")
    assert "secret-token" not in str(caught.value)


def test_history_and_view_complete_the_exact_output_node() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"safe-image"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "secret-token-must-not-leak"
        if request.url.path == "/history/provider-job-1":
            return httpx.Response(
                200,
                json={
                    "provider-job-1": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "9": {
                                "images": [
                                    {
                                        "filename": "ComfyUI_00001_.png",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
        assert request.url.path == "/view"
        assert request.url.params["filename"] == "ComfyUI_00001_.png"
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    provider = _provider(handler)
    assert provider.get_status("provider-job-1").state is ProviderState.COMPLETED
    result = provider.get_result("provider-job-1")
    assert result.content == png
    assert result.mime_type == "image/png"
    assert result.model_version == "Anything-v5.0-PRT-RE.safetensors"


def test_empty_history_is_running_and_malformed_history_fails_closed() -> None:
    running = _provider(lambda _request: httpx.Response(200, json={}))
    assert running.get_status("provider-job-1").state is ProviderState.RUNNING

    malformed = _provider(lambda _request: httpx.Response(200, json={"unexpected": []}))
    with pytest.raises(ProviderProtocolError, match="MALFORMED_HISTORY"):
        malformed.get_status("provider-job-1")


def test_output_size_limit_is_enforced_before_publication() -> None:
    huge = b"\x89PNG\r\n\x1a\n" + b"x" * (1024 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/history/"):
            return httpx.Response(
                200,
                json={
                    "provider-job-1": {
                        "status": {"completed": True},
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": "large.png", "subfolder": "", "type": "output"}
                                ]
                            }
                        },
                    }
                },
            )
        return httpx.Response(200, content=huge, headers={"content-type": "image/png"})

    with pytest.raises(ProviderProtocolError, match="OUTPUT_TOO_LARGE"):
        _provider(handler).get_result("provider-job-1")


def test_cancel_is_local_only_and_makes_no_network_request() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    provider = _provider(handler)
    provider.cancel("provider-job-1")
    assert calls == 0
    assert provider.get_status("provider-job-1").state is ProviderState.CANCELLED


def test_submit_refuses_a_workflow_changed_after_registry_load(tmp_path: Path) -> None:
    registry = WorkflowRegistry.load(REGISTRY)
    workflow = registry.select_by_id("coursejesus-comfy-image-v1", "1")
    assert workflow.workflow_file is not None
    copied = tmp_path / "workflow.json"
    copied.write_bytes(workflow.workflow_file.read_bytes())
    provider = AlibabaEASComfyProvider(
        endpoint="https://eas.example.invalid",
        token="secret-token-must-not-leak",
        workflow=replace(workflow, workflow_file=copied),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("a changed workflow must not reach the network")
            )
        ),
    )
    copied.write_text("{}", encoding="utf-8")

    with pytest.raises(ProviderProtocolError, match="WORKFLOW_SHA256_MISMATCH"):
        provider.submit(_compiled(), idempotency_key="visual-job-1")


def test_settings_allow_only_the_official_eas_shared_gateway_over_http() -> None:
    endpoint = (
        "http://synthetic-visual-service.1234567890123456."
        "cn-hangzhou.pai-eas.aliyuncs.com"
    )
    settings = Settings(
        v3_enabled=True,
        visual_engine_enabled=True,
        visual_provider="aliyun_eas",
        visual_eas_endpoint=endpoint,
        visual_eas_token=SecretStr("secret-token-must-not-leak"),
    )
    assert settings.visual_eas_endpoint == endpoint

    for rejected in (
        "http://example.com",
        endpoint + "/prompt",
        endpoint + "?token=not-allowed",
    ):
        with pytest.raises(ValueError, match="COMFYUI_EAS_ENDPOINT"):
            Settings(
                v3_enabled=True,
                visual_engine_enabled=True,
                visual_provider="aliyun_eas",
                visual_eas_endpoint=rejected,
                visual_eas_token=SecretStr("secret-token-must-not-leak"),
            )
