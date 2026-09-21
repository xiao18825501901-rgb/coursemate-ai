"""Zero-egress proof: the Laya semantic layer never reaches TypeSafe or Qwen.

These tests patch the network layer (``urllib.request``) and the import system, then
run the semantic layer across every mode — including a transport failure — and assert
the only outbound attempt is our own Laya node. They are real assertions on an HTTP
client spy, not comments.
"""

from __future__ import annotations

import ast
import builtins
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from app.jev.catalog import load_catalog
from app.jev.errors import JevRetiredError
from app.jev.gateway import SdkTransport
from app.jev.models import JevCall, JevQuestion
from app.laya.adapter import (
    FakeLayaTransport,
    HttpLayaTransport,
    LayaConfig,
    LayaGateway,
    laya_question,
)
from app.laya.models import LayaRequest, LayaScope

REPO = Path(__file__).parent.parent
CATALOG = load_catalog()
CHOICE = CATALOG.get("intent.next_action.v1")
CHOICE_IDS = ("CONTINUE", "ANSWER_ONLY", "OTHER")

# Host fragments that must never appear in any outbound URL.
BLOCKED_HOST_FRAGMENTS = ("typesafe", "qwen", "dashscope", "aliyuncs", "modelstudio", "modelscope")


def _request() -> LayaRequest:
    question = laya_question(CHOICE, criteria={cid: "" for cid in CHOICE_IDS})
    return LayaRequest(
        definition_id=CHOICE.key,
        definition_version="1.0.0-design",
        state={"message": "继续"},
        questions={CHOICE.key: question},
        deadline_ms=0,
        request_id="r1",
        compiler_version="c1",
        model_revision="rev1",
    )


def _choice_responder(choice: str):
    def responder(req: LayaRequest) -> dict:
        return {
            "answers": {
                req.definition_id: {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": {cid: (1.0 if cid == choice else 0.0) for cid in CHOICE_IDS},
                    "confidence": 1.0,
                }
            },
            "usage": {"input_tokens": 10, "output_tokens": 0},
        }

    return responder


class _MemoryStore:
    def __init__(self) -> None:
        self.receipts: list[Any] = []

    def save(self, receipt: Any) -> None:
        self.receipts.append(receipt)

    def lookup(self, definition_id: str, scope: LayaScope, *, model_revision: str) -> dict | None:
        return None


# ------------------------------------------------------------------ static source proof
def test_no_module_imports_typesafe_sdk() -> None:
    modules = list((REPO / "app" / "jev").glob("*.py")) + list((REPO / "app" / "laya").glob("*.py"))
    assert modules, "expected app/jev and app/laya modules"
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("typesafe_sdk"), path
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith("typesafe_sdk"), path


def test_jev_gateway_source_has_no_typesafe_construction() -> None:
    src = (REPO / "app" / "jev" / "gateway.py").read_text(encoding="utf-8")
    assert "typesafe_sdk" not in src
    assert "TYPESAFE_API_KEY" not in src
    assert "TypeSafeClient(" not in src
    assert "api.typesafe.ai" not in src


# ------------------------------------------------------------------ dynamic egress proof
def test_semantic_layer_zero_egress_to_typesafe_or_qwen(monkeypatch) -> None:
    attempted: list[str] = []

    def blocking_urlopen(*args: Any, **kwargs: Any) -> None:
        url = args[0].full_url if args and hasattr(args[0], "full_url") else str(args[0])
        attempted.append(url)
        raise urllib.error.URLError("blocked by test spy")

    monkeypatch.setattr(urllib.request, "urlopen", blocking_urlopen)

    # Prove nothing in the production import graph imports typesafe_sdk.
    real_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        assert not name.startswith("typesafe_sdk"), f"typesafe_sdk import attempted: {name}"
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    # 1. Run the semantic layer across every mode with a fake transport (no network).
    for mode in ("off", "shadow", "on", "advisory"):
        transport = FakeLayaTransport(_choice_responder("CONTINUE"))
        gateway = LayaGateway(
            transport=transport,
            catalog=CATALOG,
            modes={CHOICE.key: mode},
            receipt_store=_MemoryStore(),
        )
        gateway.decide(_request(), scope=LayaScope(owner_scope_hash="o"), fallback="OTHER")

    # 2. Run a live transport failure through HttpLayaTransport (only the Laya node URL).
    class FailingOpener:
        def open(self, req: object, timeout: float | None = None) -> None:  # noqa: ARG002
            attempted.append(req.full_url)
            raise urllib.error.URLError("blocked")

    http = HttpLayaTransport(
        LayaConfig(base_url="http://laya-node.internal"), opener=FailingOpener()
    )
    gateway = LayaGateway(transport=http, catalog=CATALOG, modes={CHOICE.key: "on"})
    decision = gateway.decide(_request(), scope=LayaScope(owner_scope_hash="o"), fallback="OTHER")
    assert decision.fallback_reason == "unavailable"

    # 3. The retired TypeSafe transport raises and never touches the network.
    with pytest.raises(JevRetiredError):
        SdkTransport(api_key="anything").call(
            JevCall(state={}, questions={"q": JevQuestion("q", "Noul", "is this x?")}),
            timeout_seconds=1.0,
        )

    # Every outbound attempt is our Laya node; none is a blocked host.
    assert attempted, "expected at least the Laya node attempt"
    for url in attempted:
        host = url.lower()
        assert not any(fragment in host for fragment in BLOCKED_HOST_FRAGMENTS), url
        assert "laya-node.internal" in host, url
