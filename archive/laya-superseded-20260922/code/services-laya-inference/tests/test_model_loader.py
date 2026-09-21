"""The real loader must select the multilingual checkpoint, not the English root.

The pinned snapshot is a snapshot of the whole repository, so its root also contains
the English checkpoint (`encoder/`, `tokenizer/`, `rl_agent_config.json`). Loading the
root — or counting tokens with the root tokenizer — would silently serve the English
model for Chinese material, which the owner explicitly forbade. These tests pin the
subfolder selection with fake `torch`/`laya`/`transformers` modules, so they run in the
repository venv without the heavy dependencies.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from app.model import LayaModel
from app.settings import Settings


class _FakeLaya(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("laya")
        self.calls: list[dict[str, object]] = []

    def load(self, model: str, **kwargs: object) -> object:  # noqa: ANN401
        self.calls.append({"model": model, **kwargs})
        agent = types.SimpleNamespace(cfg={"max_len": 1024, "head_max_len": 256})

        def predict(state: object, questions: object) -> dict[str, object]:
            return {"model": "fake", "answers": {}, "usage": {"input_tokens": 1}}

        agent.predict = predict  # type: ignore[attr-defined]
        return agent


class _FakeTorch(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("torch")
        self.threads: list[int] = []
        self.interop: list[int] = []

    def set_num_threads(self, value: int) -> None:
        self.threads.append(value)

    def set_num_interop_threads(self, value: int) -> None:
        self.interop.append(value)


@pytest.fixture()
def fake_stack(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    fake_laya, fake_torch = _FakeLaya(), _FakeTorch()
    tokenizer_calls: list[str] = []

    class _AutoTokenizer:
        @staticmethod
        def from_pretrained(path: str) -> object:
            tokenizer_calls.append(path)
            return types.SimpleNamespace(name_or_path=path)

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoTokenizer = _AutoTokenizer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "laya", fake_laya)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    return {"laya": fake_laya, "torch": fake_torch, "tokenizer_calls": tokenizer_calls}


def _snapshot(root: Path, *, with_multilingual: bool = True) -> Path:
    """A whole-repository snapshot: an English root plus (optionally) multilingual/."""
    (root / "encoder").mkdir(parents=True)
    (root / "encoder" / "config.json").write_text("{}", encoding="utf-8")
    (root / "tokenizer").mkdir()
    (root / "tokenizer" / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "rl_agent_config.json").write_text('{"max_len": 1024}', encoding="utf-8")
    if with_multilingual:
        multi = root / "multilingual"
        (multi / "encoder").mkdir(parents=True)
        (multi / "encoder" / "config.json").write_text("{}", encoding="utf-8")
        (multi / "tokenizer").mkdir()
        (multi / "tokenizer" / "tokenizer.json").write_text("{}", encoding="utf-8")
        (multi / "rl_agent_config.json").write_text('{"max_len": 1024}', encoding="utf-8")
    return root


def _settings(model_dir: Path) -> Settings:
    return Settings(
        app_env="test",
        model_backend="real",
        model_dir=model_dir,
        service_token="test-token",
    )


def test_loader_selects_the_multilingual_subfolder(
    tmp_path: Path, fake_stack: dict[str, object]
) -> None:
    snapshot = _snapshot(tmp_path / "snapshot")
    model = LayaModel(_settings(snapshot))

    model.load()

    calls = fake_stack["laya"].calls  # type: ignore[union-attr]
    assert calls == [{"model": str(snapshot), "subfolder": "multilingual"}], calls
    assert model.ready is False  # loaded but not warmed up yet
    model.warmup()
    assert model.ready is True


def test_loader_counts_tokens_with_the_subfolder_tokenizer(
    tmp_path: Path, fake_stack: dict[str, object]
) -> None:
    snapshot = _snapshot(tmp_path / "snapshot")
    model = LayaModel(_settings(snapshot))

    model.load()

    expected = str(snapshot / "multilingual" / "tokenizer")
    assert fake_stack["tokenizer_calls"] == [expected], fake_stack["tokenizer_calls"]
    assert expected != str(snapshot / "tokenizer")  # never the English root tokenizer


def test_loader_refuses_a_snapshot_without_the_multilingual_checkpoint(
    tmp_path: Path, fake_stack: dict[str, object]
) -> None:
    snapshot = _snapshot(tmp_path / "snapshot", with_multilingual=False)
    model = LayaModel(_settings(snapshot))

    with pytest.raises(FileNotFoundError, match="multilingual/rl_agent_config.json"):
        model.load()

    # The English root must never be loaded as a silent substitute.
    assert fake_stack["laya"].calls == []  # type: ignore[union-attr]


def test_loader_applies_the_thread_budget_before_model_construction(
    tmp_path: Path, fake_stack: dict[str, object]
) -> None:
    snapshot = _snapshot(tmp_path / "snapshot")
    settings = _settings(snapshot)
    model = LayaModel(settings)

    model.load()

    assert fake_stack["torch"].threads == [settings.torch_threads]  # type: ignore[union-attr]
    assert fake_stack["torch"].interop == [settings.torch_interop_threads]  # type: ignore[union-attr]
