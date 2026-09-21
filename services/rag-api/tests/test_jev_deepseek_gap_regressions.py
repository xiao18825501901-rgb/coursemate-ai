"""Formal regressions for the two isolated source probes in the Jev/DeepSeek pack.

The pack proved two behaviours by extracting the exact methods
(`ISOLATED_SOURCE_PROBES.json`):

1. `KnowledgeService._atomic_learning` projected an *already started* learning
   journey with zero coverage as `NOT_STARTED`, because it only looked at
   coverage counts and never at a learning-start fact.
2. `V3DomainAdapter._retrieve` appended the official hits first and truncated at
   `top_k`, so private candidates that were retrieved never reached the output;
   there was no merged global ranking.

These two tests run the REAL services in the REAL app (not the pack's isolated
method extraction) and must fail before the fix and pass after it. They reuse the
established fixtures from the coverage-submission suite so the scenario matches
production wiring (campus access granted, deterministic providers, real V3 schema).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

# Reuse the real harness (fixtures are resolved from this module's namespace).
from test_ui_extension_coverage_submission import (  # noqa: F401
    ITEM_A,
    ITEM_B,
    NODE,
    auth,
    client,
    evidence_rows,
    knowledge_node,
    teach,
)

from app.config import Settings
from app.learning.workspaces import join_course
from app.ui_extension.domain import V3DomainAdapter


# --------------------------------------------------------------- probe 1


def test_probe_started_learning_without_coverage_is_learning(client: TestClient) -> None:
    """Accepted teaching start + zero coverage must project LEARNING."""

    provider = client.app.state.ui_provider  # type: ignore[attr-defined]
    provider.responses.extend(
        [
            "这是一段与两项要求无关的闲聊内容。",
            "这是第一段讲解。说明概念 A 的定义并给出一个例子。具体来说，概念 A 是……",
            "这是第二段讲解。说明概念 B 的定义并给出一个例子。例如，概念 B 在……",
        ]
    )

    # Nothing started, nothing covered → NOT_STARTED (unchanged behaviour).
    assert knowledge_node(client)["progress"] == "NOT_STARTED"

    # An accepted teaching run whose saved content supports none of the REQUIRED
    # items: the journey/start fact is real, coverage stays zero.
    irrelevant = teach(client, "这是一段与两项要求无关的闲聊内容。", "gap-start-000001")
    run = irrelevant["run"]
    assert run["status"] == "completed", run
    receipt = irrelevant["receipt"]
    assert json.loads(receipt["covered_items"] or "[]") == []
    assert len(evidence_rows(client)) == 0

    node = knowledge_node(client)
    learning = node["learning"]
    assert learning["covered_required"] == 0
    assert learning.get("started") is True, learning
    assert learning.get("started_at"), learning
    assert node["progress"] == "LEARNING", node

    # Coverage still drives the later transitions.
    first = teach(client, "这是第一段讲解。说明概念 A 的定义并给出一个例子。具体来说，概念 A 是……", "gap-start-000002")
    assert json.loads(first["receipt"]["covered_items"]) == [ITEM_A]
    node = knowledge_node(client)
    assert node["progress"] == "LEARNING"
    assert node["learning"]["covered_required"] == 1

    second = teach(client, "这是第二段讲解。说明概念 B 的定义并给出一个例子。例如，概念 B 在……", "gap-start-000003")
    assert json.loads(second["receipt"]["covered_items"]) == [ITEM_B]
    node = knowledge_node(client)
    assert node["progress"] == "LEARNED"
    assert node["learning"]["started"] is True


def test_probe_not_started_node_stays_not_started(client: TestClient) -> None:
    """Entering the course must not by itself look like a learning start."""

    node = knowledge_node(client)
    assert node["progress"] == "NOT_STARTED"
    assert node["learning"].get("started") in (False, None)


# --------------------------------------------------------------- probe 2


class _StubRetriever:
    """Returns distinguishable hits per scope with explicit rank order."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.structured: list[dict] = []

    def retrieve(self, *, course_id, query, top_k, access):  # noqa: ANN001
        self.calls.append({"course": course_id, "scope": access.scope, "top_k": top_k})
        prefix = "official" if access.scope == "official" else "private"
        return [_hit(prefix, index) for index in range(1, top_k + 1)]

    def retrieve_structured(self, *, course_id, reference, top_k, access=None):  # noqa: ANN001
        """Explicit locator recall: only the referenced page of the named file."""

        self.structured.append(
            {"course": course_id, "scope": getattr(access, "scope", None), "reference": reference}
        )
        name = str(getattr(reference, "filename", "") or "")
        page = str(getattr(reference, "page", "") or "")
        if not name or not page:
            return []
        prefix = "official" if (getattr(access, "scope", None) == "official") else "private"
        if name.casefold().startswith(prefix):
            return [_hit(prefix, int(page))] if page.isdigit() else []
        return []


class _Hit:
    def __init__(self, prefix: str, index: int) -> None:
        self.chunk_id = f"{prefix}-chunk-{index}"
        self.document_id = f"{prefix}-doc-{index}"
        self.filename = f"{prefix}-{index}.md"
        self.locator_type = "page"
        self.locator_value = str(index)
        self.section = "s"
        self.content = f"{prefix} unique evidence {index}"


def _hit(prefix: str, index: int) -> _Hit:
    return _Hit(prefix, index)


def _merge_adapter(client: TestClient, *, top_k: int) -> tuple[V3DomainAdapter, _StubRetriever]:
    application = client.app
    retriever = _StubRetriever()
    settings = Settings(
        database_path=application.state.settings.database_path,
        upload_dir=application.state.settings.upload_dir,
        admin_user_ids=application.state.settings.admin_user_ids,
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=application.state.settings.ui_web_dir,
        top_k=top_k,
    )
    adapter = V3DomainAdapter(
        database=application.state.database,
        settings=settings,
        ingestion=application.state.ingestion_service,
        learning=application.state.learning,
        retriever=retriever,  # type: ignore[arg-type]
    )
    return adapter, retriever


def test_probe_retrieval_merges_private_candidates_before_top_k(client: TestClient) -> None:
    """Private candidates must compete in ONE global ranking, not be appended last."""

    database = client.app.state.database
    created = client.post(
        "/api/courses",
        headers=auth("Bearer admin-token"),
        json={"id": "merge-course", "name": "Merge Course", "description": "Notes"},
    )
    assert created.status_code == 201, created.text
    join_course(database, "merge-course", "user-a", 10)

    adapter, retriever = _merge_adapter(client, top_k=2)
    sources = adapter._retrieve("user-a", {"course": "merge-course", "query": "private supplement example"})  # noqa: SLF001

    assert [call["scope"] for call in retriever.calls] == ["official", "mine"], retriever.calls
    assert len(sources) == 2, sources
    document_ids = [source["document_id"] for source in sources]
    assert any(document_id.startswith("private") for document_id in document_ids), (
        "official hits filled top_k before the merged ranking: "
        f"{document_ids}"
    )
    # Public reference ids stay sequential and server-assigned.
    assert [source["id"] for source in sources] == ["S1", "S2"]


def test_probe_exact_target_is_not_replaced_by_rank(client: TestClient) -> None:
    """An explicit file/page locator keeps its slot in the merged ranking."""

    database = client.app.state.database
    created = client.post(
        "/api/courses",
        headers=auth("Bearer admin-token"),
        json={"id": "exact-course", "name": "Exact Course", "description": "Notes"},
    )
    assert created.status_code == 201, created.text
    join_course(database, "exact-course", "user-a", 10)

    adapter, _ = _merge_adapter(client, top_k=2)
    for query in ("official-2.md", "official-2.md page 2", "第 2 页 official-2.md"):
        sources = adapter._retrieve("user-a", {"course": "exact-course", "query": query})  # noqa: SLF001
        names = [source["name"] for source in sources]
        assert "official-2.md" in names, (query, names)
