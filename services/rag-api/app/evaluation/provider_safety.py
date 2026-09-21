from __future__ import annotations

from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
# Source: https://help.aliyun.com/en/model-studio/base-url
MODEL_STUDIO_HOSTS = frozenset(
    {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
        "cn-hongkong.dashscope.aliyuncs.com",
    }
)
MODEL_STUDIO_WORKSPACE_SUFFIXES = (
    ".cn-beijing.maas.aliyuncs.com",
    ".ap-southeast-1.maas.aliyuncs.com",
    ".ap-northeast-1.maas.aliyuncs.com",
    ".eu-central-1.maas.aliyuncs.com",
    ".us-east-1.maas.aliyuncs.com",
    ".cn-hongkong.maas.aliyuncs.com",
)


def _is_backend_model_studio_host(hostname: str) -> bool:
    if hostname in MODEL_STUDIO_HOSTS:
        return True
    if hostname.startswith(("trial.", "token-plan.")):
        return False
    return any(hostname.endswith(suffix) for suffix in MODEL_STUDIO_WORKSPACE_SUFFIXES)


def validate_provider_base_url(
    value: str | None,
    *,
    allow_insecure_loopback: bool,
) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("Provider base URL is invalid or unsafe.") from error
    is_valid_scheme = parsed.scheme == "https" or (
        allow_insecure_loopback and parsed.scheme == "http" and hostname in LOOPBACK_HOSTS
    )
    if (
        not is_valid_scheme
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or port is not None
        and not 1 <= port <= 65_535
    ):
        raise ValueError("Provider base URL is invalid or unsafe.")
    return value


def validate_model_studio_base_url(value: str | None) -> str:
    """Validate the exact HTTPS compatible-mode endpoint accepted by V3."""
    try:
        validated = validate_provider_base_url(
            value,
            allow_insecure_loopback=False,
        )
        if validated is None:
            raise ValueError
        parsed = urlsplit(validated)
        hostname = parsed.hostname or ""
        if (
            parsed.port not in (None, 443)
            or parsed.path.rstrip("/") != "/compatible-mode/v1"
            or not _is_backend_model_studio_host(hostname)
        ):
            raise ValueError
    except ValueError as error:
        raise ValueError("Model Studio base URL is invalid or outside the V3 allowlist.") from error
    return validated


# Source: https://api-docs.deepseek.com/ (base_url for the OpenAI-compatible
# Chat Completions and Responses endpoints).  DeepSeek exposes no per-region
# workspace hosts, so the allowlist is a single explicit host.
DEEPSEEK_API_HOSTS = frozenset({"api.deepseek.com"})


def validate_deepseek_base_url(value: str | None) -> str:
    """Validate the exact HTTPS DeepSeek API base URL accepted by generation roles.

    This rule sits ALONGSIDE ``validate_model_studio_base_url``; it does not
    loosen the shared HTTPS/credential/query/fragment checks and it does not turn
    the app into an arbitrary-URL proxy.  The host must be the official
    ``api.deepseek.com`` and the path must be empty (or ``/``); a ``/v1`` or
    region-style path is rejected so a misconfigured base URL fails loudly.
    """
    try:
        validated = validate_provider_base_url(
            value,
            allow_insecure_loopback=False,
        )
        if validated is None:
            raise ValueError
        parsed = urlsplit(validated)
        hostname = parsed.hostname or ""
        path = parsed.path.rstrip("/")
        if (
            hostname not in DEEPSEEK_API_HOSTS
            or parsed.port not in (None, 443)
            or path not in ("",)
        ):
            raise ValueError
    except ValueError as error:
        raise ValueError("DeepSeek base URL is invalid or outside the DeepSeek allowlist.") from error
    return validated
