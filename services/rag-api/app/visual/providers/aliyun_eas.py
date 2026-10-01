from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.visual.providers.base import (
    ProviderJob,
    ProviderResult,
    ProviderState,
    ProviderStatus,
    RendererTemporarilyUnavailable,
)
from app.visual.workflows import Workflow


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderAuthenticationError(RuntimeError):
    pass


class ProviderProtocolError(RuntimeError):
    pass


class ProviderRendererUnavailable(RendererTemporarilyUnavailable):
    pass


class AlibabaEASComfyProvider:
    """Pinned ComfyUI API adapter for one private Alibaba EAS service."""

    name = "aliyun_eas"

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        token: str | None = None,
        workflow: Workflow | None = None,
        timeout_seconds: float = 30.0,
        max_output_bytes: int = 10 * 1024 * 1024,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = (endpoint or "").rstrip("/")
        self._token = token or ""
        self.workflow = workflow
        self.max_output_bytes = max_output_bytes
        self._client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
        self._cancelled: set[str] = set()
        self._history: dict[str, dict[str, object]] = {}

    def _configured(self) -> Workflow:
        if not self.endpoint or not self._token or self.workflow is None:
            raise ProviderNotConfigured("NOT_CONFIGURED")
        if not self.workflow.workflow_file or not self.workflow.output_node_id:
            raise ProviderNotConfigured("WORKFLOW_NOT_CONFIGURED")
        return self.workflow

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        self._configured()
        try:
            response = self._client.request(
                method,
                self.endpoint + path,
                headers={"Authorization": self._token},
                json=json_body,
                params=params,
            )
        except httpx.TimeoutException as error:
            raise ProviderProtocolError("PROVIDER_TIMEOUT") from error
        except httpx.HTTPError as error:
            raise ProviderProtocolError("PROVIDER_NETWORK_ERROR") from error
        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError("EAS_AUTHENTICATION_FAILED")
        # Alibaba documents these responses as rejected before inference:
        # rate limited (429), queue discarded (450), or no healthy backend
        # (503). They are the only HTTP responses that this adapter exposes as
        # safe for bounded resubmission of the same deterministic prompt id.
        if response.status_code in {429, 450, 503}:
            raise ProviderRendererUnavailable(
                f"EAS_HTTP_{response.status_code}",
                status_code=response.status_code,
                safe_to_retry=True,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderProtocolError(f"EAS_HTTP_{response.status_code}")
        return response

    def _workflow_payload(self, compiled: dict[str, object]) -> dict[str, object]:
        workflow = self._configured()
        workflow_file = workflow.workflow_file
        if workflow_file is None:
            raise ProviderNotConfigured("WORKFLOW_NOT_CONFIGURED")
        workflow_bytes = workflow_file.read_bytes()
        actual_sha256 = hashlib.sha256(workflow_bytes).hexdigest()
        if not workflow.workflow_sha256 or not hmac.compare_digest(
            actual_sha256, workflow.workflow_sha256
        ):
            raise ProviderProtocolError("WORKFLOW_SHA256_MISMATCH")
        graph = cast(dict[str, Any], json.loads(workflow_bytes.decode("utf-8")))
        bindings = {name: (node_id, field) for name, node_id, field in workflow.input_bindings}
        for name in workflow.allowed_inputs:
            if name not in compiled:
                continue
            if name not in bindings:
                raise ProviderProtocolError("UNBOUND_WORKFLOW_INPUT")
            node_id, field = bindings[name]
            try:
                graph[node_id]["inputs"][field]
                graph[node_id]["inputs"][field] = compiled[name]
            except (KeyError, TypeError) as error:
                raise ProviderProtocolError("INVALID_WORKFLOW_BINDING") from error
        checkpoint = graph.get("4", {}).get("inputs", {}).get("ckpt_name")
        if checkpoint != workflow.checkpoint:
            raise ProviderProtocolError("CHECKPOINT_MISMATCH")
        return cast(dict[str, object], graph)

    def job_id_for(self, idempotency_key: str) -> str:
        return str(uuid5(NAMESPACE_URL, idempotency_key))

    def submit(self, compiled: dict[str, object], *, idempotency_key: str) -> ProviderJob:
        provider_id = self.job_id_for(idempotency_key)
        response = self._request(
            "POST",
            "/prompt",
            json_body={
                "prompt": self._workflow_payload(compiled),
                "client_id": provider_id,
                "prompt_id": provider_id,
            },
        )
        try:
            payload = response.json()
            prompt_id = payload["prompt_id"]
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderProtocolError("MALFORMED_SUBMIT_RESPONSE") from error
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ProviderProtocolError("MALFORMED_SUBMIT_RESPONSE")
        if not hmac.compare_digest(prompt_id, provider_id):
            raise ProviderProtocolError("PROMPT_ID_MISMATCH")
        return ProviderJob(prompt_id)

    def get_status(self, provider_job_id: str) -> ProviderStatus:
        if provider_job_id in self._cancelled:
            return ProviderStatus(ProviderState.CANCELLED)
        response = self._request("GET", f"/history/{provider_job_id}")
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderProtocolError("MALFORMED_HISTORY") from error
        if payload == {}:
            return ProviderStatus(ProviderState.RUNNING)
        if not isinstance(payload, dict) or provider_job_id not in payload:
            raise ProviderProtocolError("MALFORMED_HISTORY")
        item = payload[provider_job_id]
        if not isinstance(item, dict):
            raise ProviderProtocolError("MALFORMED_HISTORY")
        self._history[provider_job_id] = item
        status = item.get("status") or {}
        if not isinstance(status, dict):
            raise ProviderProtocolError("MALFORMED_HISTORY")
        status_text = str(status.get("status_str") or "").lower()
        if status_text in {"error", "failed"}:
            return ProviderStatus(ProviderState.FAILED, "PROVIDER_FAILED")
        if status.get("completed") is True or item.get("outputs"):
            return ProviderStatus(ProviderState.COMPLETED)
        return ProviderStatus(ProviderState.RUNNING)

    def get_result(self, provider_job_id: str) -> ProviderResult:
        workflow = self._configured()
        output_node_id = workflow.output_node_id
        if output_node_id is None:
            raise ProviderNotConfigured("WORKFLOW_NOT_CONFIGURED")
        item = self._history.get(provider_job_id)
        if item is None:
            status = self.get_status(provider_job_id)
            if status.state is not ProviderState.COMPLETED:
                raise ProviderProtocolError("RESULT_NOT_READY")
            item = self._history[provider_job_id]
        try:
            outputs = cast(dict[str, Any], item["outputs"])
            output = cast(dict[str, Any], outputs[output_node_id])
            image = output["images"][0]
            filename = image["filename"]
            subfolder = image.get("subfolder", "")
            output_type = image.get("type", "output")
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderProtocolError("MISSING_WORKFLOW_OUTPUT") from error
        response = self._request(
            "GET",
            "/view",
            params={
                "filename": str(filename),
                "subfolder": str(subfolder),
                "type": str(output_type),
            },
        )
        mime_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if mime_type != "image/png":
            raise ProviderProtocolError("INVALID_OUTPUT_TYPE")
        content = response.content
        if len(content) > self.max_output_bytes:
            raise ProviderProtocolError("OUTPUT_TOO_LARGE")
        return ProviderResult(
            content=content,
            mime_type=mime_type,
            width=None,
            height=None,
            duration_seconds=None,
            model_version=workflow.model_version,
            semantic_validation="LIMITED",
        )

    def cancel(self, provider_job_id: str) -> None:
        self._cancelled.add(provider_job_id)
