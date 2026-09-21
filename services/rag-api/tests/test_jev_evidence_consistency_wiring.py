"""EvidenceConsistency wiring: module C changes the evidence pack and the prompt.

Proves the two hard rules of the module-C call site inside
``V3DomainAdapter._retrieve`` and the teaching prompt assembly:

* the ``sources`` list is byte-identical under off/shadow/unavailable and with no
  Jev at all — a deterministic per-source ``jev_consistency`` field is always
  present and identical, and the conflict channel ``jev_conflict_with`` is absent,
  so the assembled teaching prompt is unchanged;
* a genuine SAME_CONTEXT_CONTRADICTION (mode ``on``) keeps both sources, marks both
  with ``jev_conflict_with``, and adds a bounded conflict note to the prompt, while
  DIFFERENT_ASSUMPTIONS and VERSION_OR_TASK_DIFFERENCE never do.

Only the offline :class:`FakeTransport` runs here.
"""

from __future__ import annotations

from jev_fixtures import make_jev_database

from app.cm_update.provider import TEACH_DIRECT_INSTRUCTION, QwenProvider, conflict_note
from app.config import Settings
from app.jev.catalog import load_catalog
from app.jev.errors import JevUnavailableError
from app.jev.evidence_consistency import COMPATIBLE, VERSION_OR_TASK_DIFFERENCE
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.ui_extension.domain import V3DomainAdapter

CATALOG = load_catalog()

# The citation audit (module D) annotates these two keys; they are outside module
# C's scope, so the byte-identity comparison strips them to isolate module C.
_CITATION_KEYS = ("jev_citation_support", "jev_selected_span")


def _strip_citation(sources: list[dict]) -> list[dict]:
    return [{k: v for k, v in source.items() if k not in _CITATION_KEYS} for source in sources]


def _retrieve_sources(adapter: V3DomainAdapter, query: str) -> list[dict]:
    return adapter._retrieve("user-a", {"course": "jev-course", "query": query})  # noqa: SLF001


def _service(database, responder, *, modes=None) -> SemanticDecisionService:
    gateway = JevGateway(
        transport=FakeTransport(responder),
        catalog=CATALOG,
        modes=modes or {},
        receipt_store=SqlReceiptStore(database),
    )
    return SemanticDecisionService(gateway)


def _benign(call):
    key = next(iter(call.questions))
    return JevResult(answers={key: JevAnswer(noul=0.5)})


def _failing(call):
    raise JevUnavailableError("down")


def _contradiction(call):
    key = next(iter(call.questions))
    if key == "evidence.consistency.v1":
        return JevResult(answers={key: JevAnswer(choice="SAME_CONTEXT_CONTRADICTION")})
    return JevResult(answers={key: JevAnswer(noul=0.5)})


def _different_assumptions(call):
    key = next(iter(call.questions))
    if key == "evidence.consistency.v1":
        return JevResult(answers={key: JevAnswer(choice="DIFFERENT_ASSUMPTIONS")})
    return JevResult(answers={key: JevAnswer(noul=0.5)})


class _Hit:
    def __init__(
        self,
        chunk_id: str,
        document_id: str,
        *,
        content: str = "",
        version: str = "",
        section: str = "s",
    ) -> None:
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.filename = f"{document_id}.md"
        self.locator_type = "page"
        self.locator_value = "1"
        self.section = section
        self.content = content
        self.version = version


class _FixedRetriever:
    def __init__(self, hits: list[_Hit]) -> None:
        self.hits = hits

    def retrieve(self, *, course_id, query, top_k, access):  # noqa: ANN001
        if access.scope == "official":
            return list(self.hits)
        return []

    def retrieve_structured(self, *, course_id, reference, top_k, access=None):  # noqa: ANN001
        return []


def _adapter(database, tmp_path, service, retriever) -> V3DomainAdapter:
    settings = Settings(
        database_path=database.path,
        upload_dir=database.upload_dir,
        admin_user_ids="",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
        top_k=2,
    )
    return V3DomainAdapter(
        database=database,
        settings=settings,
        ingestion=None,
        learning=None,
        retriever=retriever,  # type: ignore[arg-type]
        jev=service,
    )


def _seed_course_and_workspace(database) -> None:
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,"
            "publication_status,display_type,requires_student_verification) "
            "VALUES('jev-course','Jev Course',NULL,'official','public','published','campus',1)"
        )
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,publication_status) "
            "VALUES('jev-private','My workspace files','user-a','user','private','private')"
        )
        connection.execute(
            "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
            "VALUES('ws-1','user-a','jev-course','jev-private')"
        )


def test_sources_byte_identical_under_off_shadow_unavailable_and_no_jev(tmp_path) -> None:
    """Module C adds nothing that differs across modes; the prompt stays unchanged."""
    database = make_jev_database(tmp_path, with_courses=True)
    _seed_course_and_workspace(database)
    hits = [
        _Hit("a", "doc-a", content="the derivative rule alpha"),
        _Hit("b", "doc-b", content="the derivative rule beta"),
    ]

    shadow = _adapter(database, tmp_path, _service(database, _benign), _FixedRetriever(hits))
    off = _adapter(
        database,
        tmp_path,
        _service(database, _benign, modes={"evidence.consistency.v1": "off"}),
        _FixedRetriever(hits),
    )
    unavailable = _adapter(
        database, tmp_path, _service(database, _failing), _FixedRetriever(hits)
    )
    no_jev = _adapter(database, tmp_path, None, _FixedRetriever(hits))

    shadow_sources = _retrieve_sources(shadow, "derivative")
    off_sources = _retrieve_sources(off, "derivative")
    unavailable_sources = _retrieve_sources(unavailable, "derivative")
    no_jev_sources = _retrieve_sources(no_jev, "derivative")

    assert shadow_sources and len(shadow_sources) == 2
    # Module C contributes nothing that differs; the only fields that differ are
    # the pre-existing citation-audit annotations (module D), stripped above.
    assert _strip_citation(shadow_sources) == _strip_citation(off_sources)
    assert _strip_citation(shadow_sources) == _strip_citation(unavailable_sources)
    assert _strip_citation(shadow_sources) == _strip_citation(no_jev_sources)

    for sources in (shadow_sources, off_sources, unavailable_sources, no_jev_sources):
        assert [source["id"] for source in sources] == ["S1", "S2"]
        assert all(source["jev_consistency"] == COMPATIBLE for source in sources)
        assert all("jev_conflict_with" not in source for source in sources)
        # No conflict note can appear from a shadow/off/unavailable decision.
        assert conflict_note(sources) is None


def test_real_contradiction_adds_conflict_note_and_keeps_both_sources(tmp_path) -> None:
    database = make_jev_database(tmp_path, with_courses=True)
    _seed_course_and_workspace(database)
    hits = [
        _Hit("a", "doc-a", content="the derivative of x squared is two x"),
        _Hit("b", "doc-b", content="the derivative of x squared is three x"),
    ]
    adapter = _adapter(
        database,
        tmp_path,
        _service(database, _contradiction, modes={"evidence.consistency.v1": "on"}),
        _FixedRetriever(hits),
    )
    sources = _retrieve_sources(adapter, "derivative")

    # Both sources are kept, in the deterministic fused order, with unchanged ids.
    assert [source["id"] for source in sources] == ["S1", "S2"]
    assert sources[0]["jev_conflict_with"] == ["S2"]
    assert sources[1]["jev_conflict_with"] == ["S1"]

    note = conflict_note(sources)
    assert note is not None
    assert "S1" in note and "S2" in note

    provider = QwenProvider(None)
    messages = provider.direct_messages(
        {"name": "c", "code": "c"},
        "derivative",
        {"language": "zh-CN"},
        sources,
        [],
        "teach",
        None,
    )
    assert messages[0]["content"] == TEACH_DIRECT_INSTRUCTION + "\n\n" + note


def test_version_difference_is_signalled_but_never_a_conflict(tmp_path) -> None:
    database = make_jev_database(tmp_path, with_courses=True)
    _seed_course_and_workspace(database)
    hits = [
        _Hit("v1", "doc-a", version="1", content="the pass mark is 60%"),
        _Hit("v2", "doc-a", version="2", content="the pass mark is 40%"),
    ]
    adapter = _adapter(
        database,
        tmp_path,
        _service(database, _contradiction, modes={"evidence.consistency.v1": "on"}),
        _FixedRetriever(hits),
    )
    sources = _retrieve_sources(adapter, "pass mark")

    assert [source["id"] for source in sources] == ["S1", "S2"]
    assert all(source["jev_consistency"] == VERSION_OR_TASK_DIFFERENCE for source in sources)
    assert all("jev_conflict_with" not in source for source in sources)
    assert conflict_note(sources) is None


def test_different_assumptions_is_not_a_conflict(tmp_path) -> None:
    database = make_jev_database(tmp_path, with_courses=True)
    _seed_course_and_workspace(database)
    hits = [
        _Hit("a", "doc-a", content="speed is distance over time"),
        _Hit("b", "doc-b", content="speed depends on the reference frame"),
    ]
    adapter = _adapter(
        database,
        tmp_path,
        _service(database, _different_assumptions, modes={"evidence.consistency.v1": "on"}),
        _FixedRetriever(hits),
    )
    sources = _retrieve_sources(adapter, "speed")

    assert [source["id"] for source in sources] == ["S1", "S2"]
    assert all(source["jev_consistency"] == COMPATIBLE for source in sources)
    assert all("jev_conflict_with" not in source for source in sources)
    assert conflict_note(sources) is None
