"""Shadow invariance: the three structured modules never change user-visible output.

Each insertion is proved against the hard rule ``shadow means no behaviour change``:

* entity_resolution → byte-identical retrieval order under shadow AND with Jev
  unavailable, plus alias expansion preserving the original query and any explicit
  file/page/question target;
* capability_router → the same default capability (direct_qa) under shadow AND with
  Jev unavailable (no service);
* tool_intent → the same execution decision for a side-effecting tool call under
  shadow AND with Jev unavailable (and read-only/explicit actions never gain a
  confirmation step).

No live Jev call is made; every service uses the offline :class:`FakeTransport`.
"""

from __future__ import annotations

from jev_fixtures import make_jev_database

from app.config import Settings
from app.jev.capability_router import (
    DEFAULT_SKILL,
    CapabilityRequest,
    TeachingCapabilityRouter,
)
from app.jev.catalog import load_catalog
from app.jev.errors import JevUnavailableError
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.jev.tool_intent import (
    ALLOW,
    REQUIRE_CONFIRMATION,
    ToolIntentCheck,
)
from app.ui_extension.domain import V3DomainAdapter

CATALOG = load_catalog()


def _shadow_service(database, responder) -> SemanticDecisionService:
    # No `modes` means every definition resolves to the catalog default ("shadow").
    gateway = JevGateway(
        transport=FakeTransport(responder),
        catalog=CATALOG,
        receipt_store=SqlReceiptStore(database),
    )
    return SemanticDecisionService(gateway)


class _Hit:
    def __init__(self, prefix: str, index: int) -> None:
        self.chunk_id = f"{prefix}-chunk-{index}"
        self.document_id = f"{prefix}-doc-{index}"
        self.filename = f"{prefix}-{index}.md"
        self.locator_type = "page"
        self.locator_value = str(index)
        self.section = "s"
        self.content = f"{prefix} unique evidence {index}"


class _RecordingRetriever:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def retrieve(self, *, course_id, query, top_k, access):  # noqa: ANN001
        self.calls.append({"course": course_id, "scope": access.scope, "query": query})
        prefix = "official" if access.scope == "official" else "private"
        return [_Hit(prefix, i) for i in range(1, top_k + 1)]

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


# --------------------------------------------------------------------------- #
# 1. entity_resolution: alias expansion preserves the original query + target
# --------------------------------------------------------------------------- #

def test_alias_expansion_preserves_original_query_and_explicit_target(tmp_path) -> None:
    database = make_jev_database(tmp_path, with_courses=True)
    _seed_course_and_workspace(database)
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE knowledge_nodes (
                id TEXT PRIMARY KEY, course_id TEXT NOT NULL, owner_user_id TEXT,
                status TEXT NOT NULL, title TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE knowledge_node_aliases (
                node_id TEXT NOT NULL, alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL, locale TEXT NOT NULL
            );
            INSERT INTO knowledge_nodes VALUES('node-1','jev-course',NULL,'PUBLISHED','导数');
            INSERT INTO knowledge_node_aliases VALUES('node-1','derivative','derivative','en');
            """
        )

    def responder(call):
        raise AssertionError("expansion is deterministic; Jev must not be reached")

    service = _shadow_service(database, responder)
    retriever = _RecordingRetriever()
    adapter = _adapter(database, tmp_path, service, retriever)

    # No explicit target: the original query is the prefix, and the concept the
    # query names contributes its accepted alias — recall only.
    adapter._retrieve("user-a", {"course": "jev-course", "query": "导数"})  # noqa: SLF001
    official = next(call for call in retriever.calls if call["scope"] == "official")
    assert official["query"].startswith("导数")
    assert "derivative" in official["query"]

    # A query that names no registered concept is NOT expanded: a course-wide alias
    # list is never injected into every question.
    retriever.calls.clear()
    adapter._retrieve("user-a", {"course": "jev-course", "query": "谱聚类是什么"})  # noqa: SLF001
    official = next(call for call in retriever.calls if call["scope"] == "official")
    assert official["query"] == "谱聚类是什么"

    # An explicit file target outranks expansion: the query is unchanged.
    retriever.calls.clear()
    adapter._retrieve("user-a", {"course": "jev-course", "query": "导数 chapter5.pdf"})  # noqa: SLF001
    official = next(call for call in retriever.calls if call["scope"] == "official")
    assert official["query"] == "导数 chapter5.pdf"


# --------------------------------------------------------------------------- #
# 2. entity_resolution: byte-identical fused order under shadow / unavailable
# --------------------------------------------------------------------------- #

def _retrieve_order(adapter: V3DomainAdapter) -> list[str]:
    sources = adapter._retrieve("user-a", {"course": "jev-course", "query": "evidence example"})  # noqa: SLF001
    return [source["document_id"] for source in sources]


def test_fused_order_unchanged_under_shadow_and_unavailable(tmp_path) -> None:
    database = make_jev_database(tmp_path, with_courses=True)
    _seed_course_and_workspace(database)

    def hostile(call):
        key = next(iter(call.questions))
        if key == "retrieval.support.v1":
            return JevResult(answers={key: JevAnswer(score="4")})
        if key == "entity.relation.v1":
            return JevResult(answers={key: JevAnswer(choice="SAME_CONCEPT")})
        if key == "source.select_span.v1":
            return JevResult(answers={key: JevAnswer(choice="S1")})
        return JevResult(answers={key: JevAnswer(noul=0.9)})

    def failing(call):
        raise JevUnavailableError("down")

    shadow = _adapter(database, tmp_path, _shadow_service(database, hostile), _RecordingRetriever())
    unavailable = _adapter(
        database, tmp_path, _shadow_service(database, failing), _RecordingRetriever()
    )
    no_jev = _adapter(database, tmp_path, None, _RecordingRetriever())

    shadow_order = _retrieve_order(shadow)
    unavailable_order = _retrieve_order(unavailable)
    no_jev_order = _retrieve_order(no_jev)

    assert shadow_order == unavailable_order == no_jev_order
    assert shadow_order  # the deterministic fused order was actually produced


# --------------------------------------------------------------------------- #
# 3. capability_router: same default capability under shadow / unavailable
# --------------------------------------------------------------------------- #

def _capability_request() -> CapabilityRequest:
    return CapabilityRequest(
        learner_request="给我讲一下 K-means 聚类",
        product_mode="teach",
        revealed_state=False,
        active_assessment=None,
        pair_binding="pair-1",
        candidate_skills=(),
        mode="normal",
        permissions=frozenset({"teach", "exercise", "assess"}),
        explicit_command=None,
        enabled_skills=None,
        default_skill=DEFAULT_SKILL,
    )


def test_capability_router_default_under_shadow_and_unavailable(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def hostile(call):
        return JevResult(answers={"teaching.capability.v1": JevAnswer(choice="node_lesson")})

    shadow = _shadow_service(database, hostile)
    resolution = TeachingCapabilityRouter(shadow).resolve(
        _capability_request(),
        owner_user_id="user-a",
        authorization_scope="capability",
        course_id="c",
    )
    assert resolution.skill_id == DEFAULT_SKILL
    assert resolution.used_jev is False
    assert resolution.path.startswith("fallback:")

    no_service = TeachingCapabilityRouter(None).resolve(
        _capability_request(),
        owner_user_id="user-a",
        authorization_scope="capability",
        course_id="c",
    )
    assert no_service.skill_id == DEFAULT_SKILL
    assert no_service.used_jev is False
    assert no_service.jev_calls == 0


# --------------------------------------------------------------------------- #
# 4. tool_intent: same execution decision under shadow / unavailable
# --------------------------------------------------------------------------- #

def _authorize(
    check: ToolIntentCheck, *, explicit: bool = False, read_only: bool = False
) -> object:
    return check.authorize(
        user_message="请删除这个文件",
        proposed_tool="delete_document",
        tool_arguments={"target": "doc-1"},
        actor_scope="owner",
        actor_permissions=frozenset({"delete"}),
        required_permissions=frozenset({"delete"}),
        is_read_only=read_only,
        explicit=explicit,
        object_revision="r1",
        current_revision="r1",
        owner_user_id="user-a",
        authorization_scope="tool_intent",
        course_id="c",
    )


def test_tool_intent_same_decision_under_shadow_and_unavailable(tmp_path) -> None:
    database = make_jev_database(tmp_path)

    def hostile(call):
        return JevResult(answers={"tool.intent.v1": JevAnswer(choice="CONSISTENT")})

    shadow = ToolIntentCheck(_shadow_service(database, hostile))
    shadow_side_effect = _authorize(shadow)
    assert shadow_side_effect.verdict == REQUIRE_CONFIRMATION  # shadow: never auto-allow
    assert shadow_side_effect.used_jev is False

    unavailable = ToolIntentCheck(None)
    unavailable_side_effect = _authorize(unavailable)
    assert unavailable_side_effect.verdict == REQUIRE_CONFIRMATION

    # Read-only and explicit legitimate actions never gain a confirmation step,
    # in every mode (shadow or unavailable).
    for check in (shadow, unavailable):
        assert _authorize(check, read_only=True).verdict == ALLOW
        assert _authorize(check, explicit=True).verdict == ALLOW


# --------------------------------------------------------------------------- #
# 5. entity_resolution: relations are recorded as PROPOSED rows, never applied
# --------------------------------------------------------------------------- #

_DUPLICATE_CONTENT = "identical evidence text for two chunks"


class _DuplicateContentRetriever:
    """Two authorized chunks whose bytes are identical (a deterministic duplicate)."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, *, course_id, query, top_k, access):  # noqa: ANN001
        self.queries.append(query)
        hits = []
        for index in (1, 2):
            hit = _Hit("official", index)
            hit.content = _DUPLICATE_CONTENT
            hits.append(hit)
        return hits

    def retrieve_structured(self, *, course_id, reference, top_k, access=None):  # noqa: ANN001
        return []


def _relation_rows(database) -> list[dict]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT left_id, right_id, relation, evidence, status, used_jev, "
            "left_source_version, right_source_version, course_id, material_revision "
            "FROM entity_relations ORDER BY left_id, right_id, relation"
        ).fetchall()
    return [dict(row) for row in rows]


def _has_relation_store(database) -> bool:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'entity_relations'"
        ).fetchone()
    return row is not None


def _shadow_service_recording(database):
    def responder(call):  # pragma: no cover - deterministic pairs need no Jev call
        raise AssertionError("a content-hash duplicate is decided in code")

    return _shadow_service(database, responder)


def test_duplicate_evidence_is_recorded_as_a_proposed_relation(tmp_path) -> None:
    database = make_jev_database(tmp_path, with_courses=True)
    _seed_course_and_workspace(database)
    retriever = _DuplicateContentRetriever()
    adapter = _adapter(
        database, tmp_path, _shadow_service_recording(database), retriever
    )

    sources = adapter._retrieve("user-a", {"course": "jev-course", "query": "evidence"})  # noqa: SLF001
    assert len(sources) == 2  # the duplicate is NOT merged away on the path

    rows = _relation_rows(database)
    assert len(rows) == 1
    row = rows[0]
    assert row["relation"] == "SAME_CONCEPT"
    assert row["evidence"] == "content_hash"
    assert row["status"] == "PROPOSED"  # the semantic layer never ACCEPTs
    assert row["used_jev"] == 0  # decided in code: zero Jev calls
    assert row["left_id"] <= row["right_id"]  # canonical order
    assert row["left_source_version"] and row["right_source_version"]
    assert row["course_id"] == "jev-course"

    # A second retrieval of the same authorized set is idempotent.
    adapter._retrieve("user-a", {"course": "jev-course", "query": "evidence"})  # noqa: SLF001
    assert _relation_rows(database) == rows


def test_relation_bookkeeping_never_breaks_retrieval_without_the_store(tmp_path) -> None:
    """A database without migration 029 still retrieves the same deterministic order."""

    with_store = make_jev_database(tmp_path / "with-store", with_courses=True)
    _seed_course_and_workspace(with_store)
    without_store = make_jev_database(
        tmp_path / "without-store", with_courses=True, with_entity_relations=False
    )
    _seed_course_and_workspace(without_store)

    with_order = _adapter(
        with_store, tmp_path, _shadow_service_recording(with_store), _DuplicateContentRetriever()
    )._retrieve("user-a", {"course": "jev-course", "query": "evidence"})  # noqa: SLF001
    without_order = _adapter(
        without_store,
        tmp_path,
        _shadow_service_recording(without_store),
        _DuplicateContentRetriever(),
    )._retrieve("user-a", {"course": "jev-course", "query": "evidence"})  # noqa: SLF001

    assert [s["document_id"] for s in with_order] == [
        s["document_id"] for s in without_order
    ]
    assert with_order
    # The store really was absent, so the retrieval above proves the degradation:
    assert not _has_relation_store(without_store)
    assert _has_relation_store(with_store)
