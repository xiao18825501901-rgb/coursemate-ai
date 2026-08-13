from pathlib import Path
from typing import Any

from app.config import Settings
from app.main import create_app
from app.rag.answers import OpenAIAnswerProvider
from app.rag.embeddings import DeterministicEmbeddingProvider, OpenAIEmbeddingProvider


class RecordingOpenAI:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def __call__(self, **kwargs: str) -> object:
        self.calls.append(kwargs)
        return object()


def test_settings_reads_openai_base_url(monkeypatch: Any) -> None:
    endpoint = "https://workspace.example.com/compatible-mode/v1"
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)

    settings = Settings(_env_file=None, openai_api_key=None)

    assert settings.openai_base_url == endpoint


def test_embedding_provider_configures_only_a_non_empty_base_url(monkeypatch: Any) -> None:
    import app.rag.embeddings as embedding_module

    sdk = RecordingOpenAI()
    monkeypatch.setattr(embedding_module, "OpenAI", sdk)

    custom = OpenAIEmbeddingProvider(
        api_key="placeholder-key",
        model="test-embedding-model",
        base_url="https://workspace.example.com/compatible-mode/v1",
    )
    default = OpenAIEmbeddingProvider(
        api_key="placeholder-key",
        model="test-embedding-model",
        base_url="",
    )

    assert custom.client is not None
    assert default.client is not None
    assert sdk.calls == [
        {
            "api_key": "placeholder-key",
            "base_url": "https://workspace.example.com/compatible-mode/v1",
        },
        {"api_key": "placeholder-key"},
    ]


def test_answer_provider_configures_only_a_non_empty_base_url(monkeypatch: Any) -> None:
    import app.rag.answers as answer_module

    sdk = RecordingOpenAI()
    monkeypatch.setattr(answer_module, "OpenAI", sdk)

    OpenAIAnswerProvider(
        api_key="placeholder-key",
        model="test-chat-model",
        base_url="https://workspace.example.com/compatible-mode/v1",
    )
    OpenAIAnswerProvider(
        api_key="placeholder-key",
        model="test-chat-model",
        base_url=None,
    )

    assert sdk.calls == [
        {
            "api_key": "placeholder-key",
            "base_url": "https://workspace.example.com/compatible-mode/v1",
        },
        {"api_key": "placeholder-key"},
    ]


def test_injected_clients_remain_unchanged() -> None:
    client = object()

    embedding_provider = OpenAIEmbeddingProvider(
        api_key="placeholder-key",
        model="test-embedding-model",
        client=client,  # type: ignore[arg-type]
        base_url="https://ignored.example.com/v1",
    )
    answer_provider = OpenAIAnswerProvider(
        api_key="placeholder-key",
        model="test-chat-model",
        client=client,  # type: ignore[arg-type]
        base_url="https://ignored.example.com/v1",
    )

    assert embedding_provider.client is client
    assert answer_provider.client is client


def test_application_passes_base_url_to_both_rag_providers(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    import app.main as main_module

    calls: dict[str, dict[str, str | None]] = {}

    def embedding_factory(**kwargs: str | None) -> DeterministicEmbeddingProvider:
        calls["embedding"] = kwargs
        return DeterministicEmbeddingProvider()

    class AnswerStub:
        def stream_answer(
            self, *, question: str, context: str, instructions: str
        ) -> Any:
            yield "answer"

    def answer_factory(**kwargs: str | None) -> AnswerStub:
        calls["answer"] = kwargs
        return AnswerStub()

    class AuthStub:
        def authenticate(self, request: Any) -> str:
            return "user-a"

    monkeypatch.setattr(main_module, "OpenAIEmbeddingProvider", embedding_factory)
    monkeypatch.setattr(main_module, "OpenAIAnswerProvider", answer_factory)
    endpoint = "https://workspace.example.com/compatible-mode/v1"

    create_app(
        settings=Settings(
            _env_file=None,
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            openai_api_key="placeholder-key",
            openai_base_url=endpoint,
        ),
        auth_verifier=AuthStub(),
    )

    assert calls["embedding"]["base_url"] == endpoint
    assert calls["answer"]["base_url"] == endpoint
