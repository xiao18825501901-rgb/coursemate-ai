from __future__ import annotations

from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
MODEL_STUDIO_HOSTS = frozenset({"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"})


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
            or not (hostname in MODEL_STUDIO_HOSTS or hostname.endswith(".maas.aliyuncs.com"))
        ):
            raise ValueError
    except ValueError as error:
        raise ValueError("Model Studio base URL is invalid or outside the V3 allowlist.") from error
    return validated
