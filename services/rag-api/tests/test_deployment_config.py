from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[3]


def test_netlify_config_emits_static_site_security_headers() -> None:
    config = (REPOSITORY_ROOT / "netlify.toml").read_text(encoding="utf-8")

    assert "Strict-Transport-Security = \"max-age=31536000; includeSubDomains\"" in config
    assert "X-Content-Type-Options = \"nosniff\"" in config
    assert "X-Frame-Options = \"DENY\"" in config
    assert "Referrer-Policy = \"strict-origin-when-cross-origin\"" in config
    assert "Permissions-Policy = \"camera=(), microphone=(), geolocation=()\"" in config


def test_default_playwright_config_uses_an_isolated_rag_copy() -> None:
    config = (REPOSITORY_ROOT / "playwright.config.ts").read_text(encoding="utf-8")

    assert "prepare_full_e2e.py" in config
    assert "RAG_DATABASE_PATH" in config
    assert "RAG_UPLOAD_DIR" in config
    assert "path.join(repositoryRoot, \"work\"" in config


def test_render_template_keeps_v3_off_and_declares_the_locked_primary_model() -> None:
    config = (REPOSITORY_ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "key: V3_ENABLED\n        value: \"false\"" in config
    assert config.count("value: qwen3.8-max") == 2
    assert "key: V3_MODEL_BASE_URL\n        sync: false" in config
    assert "key: AGENT_MODEL_BASE_URL\n        sync: false" in config
    assert "key: V3_DAILY_MODEL_CALLS_PER_USER" in config
    assert "key: AGENT_CHAT_REQUESTS_PER_DAY" in config
