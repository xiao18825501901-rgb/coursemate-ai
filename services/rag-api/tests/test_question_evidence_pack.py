"""Stage 2 evidence packs stay inside the Teaching Item's cited source scope."""

from __future__ import annotations

import hashlib
import pathlib

import pytest

from app.config import Settings
from app.db import Database
from app.learning.question_blueprint import TeachingObjective
from app.learning.question_evidence import (
    EvidencePackAccess,
    EvidencePackError,
    build_evidence_pack,
)

COURSE = "course-evidence"
PRIVATE_COURSE = "course-evidence-private"
NODE = "node-evidence"
OWNER = "user-a"
SPEC_HASH = "a" * 64


def make_db(tmp_path: pathlib.Path) -> Database:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=200,
        chunk_overlap=20,
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )
    database = Database(settings)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,"
            "publication_status) VALUES(?,? ,?,'user','private','private')",
            (COURSE, "Evidence course", OWNER),
        )
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,"
            "publication_status) VALUES(?,? ,?,'user','private','private')",
            (PRIVATE_COURSE, "Private evidence", OWNER),
        )
        connection.execute(
            "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
            "VALUES('workspace-evidence',?,?,?)",
            (OWNER, COURSE, PRIVATE_COURSE),
        )
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES(?,?,?,'Density clustering','Synthetic','CS',"
            "'ATOMIC','PRIVATE')",
            (NODE, COURSE, OWNER),
        )
    return database


def add_source(
    database: Database,
    *,
    course_id: str,
    document_id: str,
    chunk_id: str,
    content: str,
    hash_char: str,
    locator_value: str,
) -> str:
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,"
            "sha256,byte_size,status,chunk_count) VALUES(?,?,?,?,'text/markdown','.md',"
            "?,?, 'ready',1)",
            (
                document_id,
                course_id,
                f"{document_id}.md",
                f"{document_id}.md",
                hash_char * 64,
                len(content.encode()),
            ),
        )
        version = connection.execute(
            "SELECT id FROM document_versions WHERE document_id=?", (document_id,)
        ).fetchone()
        assert version is not None
        connection.execute(
            "INSERT INTO chunks(id,document_id,course_id,ordinal,content,locator_type,"
            "locator_value,section,embedding) VALUES(?,?,?,0,?,'page',?,'DBSCAN','[]')",
            (chunk_id, document_id, course_id, content, locator_value),
        )
        return str(version["id"])


def objective(*evidence_ids: str) -> TeachingObjective:
    return TeachingObjective(
        node_id=NODE,
        spec_version=1,
        spec_content_hash=SPEC_HASH,
        item_id="objective-density",
        requirement="REQUIRED",
        objective="计算 epsilon 邻域并区分核心点、边界点与噪声点",
        acceptance="所有点的分类与步骤均可由课程定义核验",
        evidence_ids=tuple(evidence_ids),
    )


def access(**overrides: str) -> EvidencePackAccess:
    values = {
        "owner_user_id": OWNER,
        "course_id": COURSE,
        "private_course_id": PRIVATE_COURSE,
    }
    values.update(overrides)
    return EvidencePackAccess(**values)


def test_pack_contains_only_cited_chunks_in_declared_order(tmp_path: pathlib.Path) -> None:
    database = make_db(tmp_path)
    private_version = add_source(
        database,
        course_id=PRIVATE_COURSE,
        document_id="doc-private",
        chunk_id="chunk-private",
        content="Private worked example: count each point itself in minPts.",
        hash_char="b",
        locator_value="7",
    )
    course_version = add_source(
        database,
        course_id=COURSE,
        document_id="doc-course",
        chunk_id="chunk-course",
        content="Official definition: a core point has at least minPts neighbours.",
        hash_char="c",
        locator_value="3",
    )
    add_source(
        database,
        course_id=COURSE,
        document_id="doc-unselected",
        chunk_id="chunk-unselected",
        content="This source is in the course but not cited by the Teaching Item.",
        hash_char="d",
        locator_value="99",
    )

    pack = build_evidence_pack(
        database,
        objective=objective("chunk-private", "chunk-course"),
        access=access(),
    )

    assert pack.evidence_ids == ["chunk-private", "chunk-course"]
    assert [fragment.evidence_id for fragment in pack.fragments] == pack.evidence_ids
    assert [fragment.document_version_id for fragment in pack.fragments] == [
        private_version,
        course_version,
    ]
    assert [fragment.source_scope for fragment in pack.fragments] == [
        "WORKSPACE_PRIVATE",
        "OWNER_COURSE",
    ]
    assert [fragment.locator for fragment in pack.fragments] == ["page:7", "page:3"]
    assert "unselected" not in " ".join(fragment.content for fragment in pack.fragments)
    assert [entry.locator for entry in pack.source_scope()] == ["page:7", "page:3"]


def test_empty_or_missing_sources_refuse_with_source_insufficient(tmp_path: pathlib.Path) -> None:
    database = make_db(tmp_path)
    for target in (objective(), objective("chunk-missing")):
        with pytest.raises(EvidencePackError) as refusal:
            build_evidence_pack(database, objective=target, access=access())
        assert refusal.value.code == "SOURCE_INSUFFICIENT"


def test_an_uncited_course_chunk_is_never_added_as_fallback(tmp_path: pathlib.Path) -> None:
    database = make_db(tmp_path)
    add_source(
        database,
        course_id=COURSE,
        document_id="doc-fallback",
        chunk_id="chunk-fallback",
        content="A relevant-looking fallback must not broaden an empty objective.",
        hash_char="e",
        locator_value="4",
    )
    with pytest.raises(EvidencePackError) as refusal:
        build_evidence_pack(database, objective=objective(), access=access())
    assert refusal.value.code == "SOURCE_INSUFFICIENT"


def test_course_and_owner_boundaries_are_rechecked(tmp_path: pathlib.Path) -> None:
    database = make_db(tmp_path)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,"
            "publication_status) VALUES('course-other-main','Other','user-b','user',"
            "'private','private')"
        )
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,"
            "publication_status) VALUES('course-other-private','Other private','user-b','user',"
            "'private','private')"
        )
        connection.execute(
            "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
            "VALUES('workspace-other','user-b','course-other-main','course-other-private')"
        )
    add_source(
        database,
        course_id="course-other-private",
        document_id="doc-other",
        chunk_id="chunk-other",
        content="Another user's private source.",
        hash_char="f",
        locator_value="1",
    )

    for source_access in (
        access(),
        access(private_course_id="course-other-private"),
    ):
        with pytest.raises(EvidencePackError) as refusal:
            build_evidence_pack(
                database,
                objective=objective("chunk-other"),
                access=source_access,
            )
        assert refusal.value.code == "SOURCE_INSUFFICIENT"


def test_revoked_material_evidence_is_not_generation_input(tmp_path: pathlib.Path) -> None:
    database = make_db(tmp_path)
    version_id = add_source(
        database,
        course_id=COURSE,
        document_id="doc-revoked",
        chunk_id="chunk-revoked",
        content="This evidence was later revoked.",
        hash_char="1",
        locator_value="8",
    )
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO material_evidence(id,node_id,document_version_id,chunk_id,"
            "owner_user_id,source_scope,locator_type,locator_value,status) "
            "VALUES('evidence-revoked',?,?,?,?, 'OWNER_COURSE','page','8','REVOKED')",
            (NODE, version_id, "chunk-revoked", OWNER),
        )

    with pytest.raises(EvidencePackError) as refusal:
        build_evidence_pack(
            database,
            objective=objective("chunk-revoked"),
            access=access(),
        )
    assert refusal.value.code == "SOURCE_INSUFFICIENT"


def test_excerpt_is_bounded_but_bound_to_the_full_chunk_hash(tmp_path: pathlib.Path) -> None:
    database = make_db(tmp_path)
    full_content = "core-point-definition-" * 40
    add_source(
        database,
        course_id=COURSE,
        document_id="doc-long",
        chunk_id="chunk-long",
        content=full_content,
        hash_char="2",
        locator_value="11",
    )

    first = build_evidence_pack(
        database,
        objective=objective("chunk-long"),
        access=access(),
        excerpt_limit=80,
    )
    second = build_evidence_pack(
        database,
        objective=objective("chunk-long"),
        access=access(),
        excerpt_limit=80,
    )

    fragment = first.fragments[0]
    assert len(fragment.content) == 80
    assert fragment.truncated is True
    assert fragment.source_content_sha256 == hashlib.sha256(full_content.encode()).hexdigest()
    assert fragment.excerpt_sha256 == hashlib.sha256(fragment.content.encode()).hexdigest()
    assert first.identity() == second.identity()
