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


def test_rag_chat_and_embedding_provider_settings_are_independently_overridable(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://legacy.example/v1")
    monkeypatch.setenv("RAG_CHAT_API_KEY", "chat-key")
    monkeypatch.setenv("RAG_CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("RAG_CHAT_MODEL", "chat-model")
    monkeypatch.setenv("RAG_EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("RAG_EMBEDDING_BASE_URL", "https://embedding.example/v1")
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "embedding-model")

    settings = Settings(_env_file=None)

    assert settings.rag_chat_api_key is not None
    assert settings.rag_chat_api_key.get_secret_value() == "chat-key"
    assert settings.rag_chat_base_url == "https://chat.example/v1"
    assert settings.rag_chat_model == "chat-model"
    assert settings.rag_embedding_api_key is not None
    assert settings.rag_embedding_api_key.get_secret_value() == "embedding-key"
    assert settings.rag_embedding_base_url == "https://embedding.example/v1"
    assert settings.rag_embedding_model == "embedding-model"


def test_rag_provider_settings_fall_back_to_legacy_openai_variables(
    monkeypatch: Any,
) -> None:
    for variable in (
        "RAG_CHAT_API_KEY",
        "RAG_CHAT_BASE_URL",
        "RAG_CHAT_MODEL",
        "RAG_EMBEDDING_API_KEY",
        "RAG_EMBEDDING_BASE_URL",
        "RAG_EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(variable, raising=False)
    settings = Settings(
        _env_file=None,
        openai_api_key="legacy-key",
        openai_base_url="https://legacy.example/v1",
        openai_chat_model="legacy-chat",
        openai_embedding_model="legacy-embedding",
    )

    assert settings.rag_chat_api_key is not None
    assert settings.rag_chat_api_key.get_secret_value() == "legacy-key"
    assert settings.rag_chat_base_url == "https://legacy.example/v1"
    assert settings.rag_chat_model == "legacy-chat"
    assert settings.rag_embedding_api_key is not None
    assert settings.rag_embedding_api_key.get_secret_value() == "legacy-key"
    assert settings.rag_embedding_base_url == "https://legacy.example/v1"
    assert settings.rag_embedding_model == "legacy-embedding"


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
    for variable in (
        "RAG_CHAT_API_KEY",
        "RAG_CHAT_BASE_URL",
        "RAG_CHAT_MODEL",
        "RAG_EMBEDDING_API_KEY",
        "RAG_EMBEDDING_BASE_URL",
        "RAG_EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(variable, raising=False)
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


def test_application_wires_independent_rag_provider_credentials(
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
    create_app(
        settings=Settings(
            _env_file=None,
            openai_api_key=None,
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            rag_chat_api_key="chat-key",
            rag_chat_base_url="https://chat.example/v1",
            rag_chat_model="chat-model",
            rag_embedding_api_key="embedding-key",
            rag_embedding_base_url="https://embedding.example/v1",
            rag_embedding_model="embedding-model",
        ),
        auth_verifier=AuthStub(),
    )

    assert calls["answer"] == {
        "api_key": "chat-key",
        "model": "chat-model",
        "base_url": "https://chat.example/v1",
    }
    assert calls["embedding"] == {
        "api_key": "embedding-key",
        "model": "embedding-model",
        "base_url": "https://embedding.example/v1",
    }
