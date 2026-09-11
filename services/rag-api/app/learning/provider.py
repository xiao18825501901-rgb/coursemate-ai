import json
from typing import Any, TypeVar
from urllib.parse import urlsplit

from openai import OpenAI
from pydantic import BaseModel

from app.config import Settings
from app.errors import ApiError

Output = TypeVar("Output", bound=BaseModel)


class LearningProvider:
    """Bounded Responses adapter. No provider fallback, automatic retry or external search tools."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.v3_model
        self.client: OpenAI | None = None

    def generate(
        self, schema: type[Output], *, instructions: str, context: dict[str, Any], role: str
    ) -> tuple[Output, dict[str, Any]]:
        settings = self.settings
        if settings.app_env == "test" and settings.rag_provider_mode == "deterministic":
            from app.learning.testing import fixture_output

            return schema.model_validate(fixture_output(schema.__name__, context)), {
                "model": "FAKE_TEST_ONLY",
                "protocol": "fixture",
                "input_tokens": 0,
                "output_tokens": 0,
                "provider_response_id": None,
                "role": role,
            }
        if not settings.v3_model_api_key or not settings.v3_model_base_url:
            raise ApiError(
                503,
                "MODEL_LIVE_BLOCKED",
                "Configure the explicit V3 Model Studio endpoint and key.",
            )
        url = urlsplit(settings.v3_model_base_url)
        host = url.hostname or ""
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.port not in (None, 443)
            or url.path.rstrip("/") != "/compatible-mode/v1"
            or not (
                host.endswith(".maas.aliyuncs.com")
                or host in ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com")
            )
        ):
            raise ApiError(
                503,
                "MODEL_ENDPOINT_INVALID",
                "Use an explicit Model Studio compatible-mode endpoint.",
            )
        if self.client is None:
            self.client = OpenAI(
                api_key=settings.v3_model_api_key.get_secret_value(),
                base_url=settings.v3_model_base_url,
                max_retries=0,
                timeout=90,
            )
        serialized = json.dumps(
            {"authorized_context": context, "required_output_schema": schema.model_json_schema()},
            ensure_ascii=False,
        )
        if len(serialized) > 60000:
            raise ApiError(422, "CONTEXT_BUDGET", "The bounded unit context is too large.")
        response = self.client.responses.create(
            model=self.model,
            instructions=instructions
            + "\nReturn only one valid JSON object matching the supplied schema.",
            input=serialized,
            max_output_tokens=settings.v3_max_output_tokens,
            store=False,
            tools=[],
            stream=False,
        )
        if response.status != "completed":
            raise ApiError(
                502, "MODEL_INCOMPLETE", "Incomplete output was not recorded as teaching coverage."
            )
        output = schema.model_validate_json(response.output_text)
        usage = response.usage
        return output, {
            "model": self.model,
            "protocol": "responses",
            "role": role,
            "input_tokens": usage.input_tokens if usage else 0,
            "output_tokens": usage.output_tokens if usage else 0,
            "provider_response_id": response.id,
        }
