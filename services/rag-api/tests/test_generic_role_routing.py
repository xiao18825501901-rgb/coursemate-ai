from pydantic import SecretStr

from app.config import Settings
from app.learning.orchestrator import LearningOrchestrator
from app.ui_extension.mount import _coverage_reviewer, _ui_settings


def qualified_settings(**updates):
    settings = Settings(
        _env_file=None,
        app_env="development",
        generic_llm_enabled=True,
        cj_qwen_api_key=SecretStr("TEST_ONLY-placeholder"),
        cj_qwen_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        cj_qwen_capability_receipt_id="TEST_ONLY-capability",
        cj_qwen_secret_generation_id="TEST_ONLY-generation",
        v3_model="deepseek-flash",
        v3_model_api_key=SecretStr("TEST_ONLY-tree-placeholder"),
        v3_model_base_url="https://api.deepseek.com",
    )
    return settings.model_copy(update=updates)


def test_private_map_keeps_tree_provider_while_interactive_roles_use_generic_provider():
    orchestrator = object.__new__(LearningOrchestrator)
    orchestrator.tree_provider = object()
    orchestrator.provider = object()

    assert orchestrator.provider_for("BACKGROUND_AUTO_MAP") is orchestrator.tree_provider
    assert orchestrator.provider_for("INTERACTIVE") is orchestrator.provider


def test_ui_qwen_route_uses_independent_generic_secret_not_tree_secret(monkeypatch):
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "qwen")
    monkeypatch.setenv("CMUI_ALLOW_BILLABLE", "true")
    monkeypatch.delenv("CMUI_QWEN_API_KEY", raising=False)
    monkeypatch.delenv("CMUI_QWEN_BASE_URL", raising=False)

    ui = _ui_settings(qualified_settings())

    assert ui.provider_mode == "qwen"
    assert ui.qwen_model == "qwen3.8-max"
    assert ui.qwen_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert ui.qwen_key == "TEST_ONLY-placeholder"
    assert ui.qwen_key != "TEST_ONLY-tree-placeholder"


def test_coverage_review_uses_same_qualified_generic_qwen_route(monkeypatch):
    monkeypatch.setenv("CMUI_COVERAGE_REVIEWER", "model")
    monkeypatch.setenv("CMUI_ALLOW_BILLABLE", "true")

    reviewer = _coverage_reviewer(qualified_settings())

    assert reviewer.model == "qwen3.8-max"
