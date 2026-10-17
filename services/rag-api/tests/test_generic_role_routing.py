from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.learning.orchestrator import LearningOrchestrator
from app.rag.answers import QwenAnswerProvider
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


def test_grounded_qa_streams_only_public_qwen_content():
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                reasoning_content="private-plan",
                                tool_calls=None,
                                function_call=None,
                            ),
                            finish_reason=None,
                        )
                    ]
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="grounded",
                                reasoning_content=None,
                                tool_calls=None,
                                function_call=None,
                            ),
                            finish_reason=None,
                        )
                    ]
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                reasoning_content=None,
                                tool_calls=None,
                                function_call=None,
                            ),
                            finish_reason="stop",
                        )
                    ]
                ),
            ]

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    provider = QwenAnswerProvider(
        api_key="TEST_ONLY-placeholder",
        client=client,
    )

    assert list(
        provider.stream_answer(question="q", context="c", instructions="i")
    ) == ["grounded"]
    assert captured["model"] == "qwen3.8-max"
    assert captured["stream"] is True
    assert captured["extra_body"] == {"enable_thinking": False}
    assert captured["stream_options"] == {"include_usage": True}
    assert "private-plan" not in str(captured)


def test_grounded_qa_rejects_unqualified_qwen_endpoint():
    with pytest.raises(ValueError):
        QwenAnswerProvider(
            api_key="TEST_ONLY-placeholder",
            base_url="https://random.example.com/v1",
        )


def test_grounded_qa_rejects_truncated_qwen_stream():
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content="partial",
                    reasoning_content=None,
                    tool_calls=None,
                    function_call=None,
                ),
                finish_reason=None,
            )
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: [chunk])
        )
    )
    provider = QwenAnswerProvider(api_key="TEST_ONLY-placeholder", client=client)

    with pytest.raises(RuntimeError, match="did not complete"):
        list(provider.stream_answer(question="q", context="c", instructions="i"))


def test_application_wires_grounded_qa_to_qualified_generic_route(
    monkeypatch, tmp_path
):
    import app.main as main_module

    captured = {}

    class AnswerStub:
        def stream_answer(self, *, question, context, instructions):
            yield "answer"

    def answer_factory(**kwargs):
        captured.update(kwargs)
        return AnswerStub()

    class AuthStub:
        def authenticate(self, request):
            return "user-a"

    monkeypatch.setattr(main_module, "QwenAnswerProvider", answer_factory)
    application = main_module.create_app(
        settings=qualified_settings(
            rag_provider_mode="openai",
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
        ),
        auth_verifier=AuthStub(),
    )

    assert captured == {
        "api_key": "TEST_ONLY-placeholder",
        "model": "qwen3.8-max",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }
    assert application.state.qa_service.answer_provider.__class__ is AnswerStub
