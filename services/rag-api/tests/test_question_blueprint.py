"""The single-question blueprint: what it refuses, and what it resolves from real rows.

Two halves, because the object has two jobs. The contract half checks the refusals that keep a
generated question honest — a bare topic is not an objective, a model cannot grant itself authority,
the type decides the answer form, and the three control dimensions stay separate. The resolver half
drives real `teaching_specs` / `teaching_items` / `document_versions` rows, because "target
selection" that reads nothing is exactly the helper-exists failure this project keeps finding.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db import Database
from app.learning.question_blueprint import (
    EXPECTED_FORM_BY_TYPE,
    ObjectiveResolutionError,
    QuestionBlueprint,
    evidence_scope,
    is_hex64,
    objective_is_observable,
    resolve_objective,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
NODE = "node-blueprint"
COURSE = "cs3481"


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
        # `private`, not `published`: migration 019 locks content writes on a course that is
        # pending or published ("Course content is locked by publication review"), so a fixture
        # that wants to add a document version has to use an unlocked course. That is the same
        # rule the campus import meets, and it is enforced by a trigger, not by this test.
        connection.execute(
            "INSERT INTO courses(id,name,publication_status) VALUES(?,'Synthetic','private')",
            (COURSE,),
        )
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES(?,?,'user-a','Blueprint Node','Synthetic','CS',"
            "'ATOMIC','PRIVATE')",
            (NODE, COURSE),
        )
    return database


def add_spec(
    database: Database, version: int, items: list[dict[str, Any]], hash_value: str = HASH_A
) -> None:
    """Insert a spec whose `content_json` is an array of item objects.

    That shape is not a test convention: the `normalize_new_teaching_spec` trigger in migration 014
    iterates `json_each(content_json)` and derives the `teaching_items` rows from it, which is the
    path the product itself uses. Driving the real normalization is why this fixture does not
    hand-write `teaching_items`.
    """
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) VALUES(?,?,?,?)",
            (NODE, version, json.dumps(items, ensure_ascii=False), hash_value),
        )


def item(
    item_id: str,
    *,
    requirement: str = "REQUIRED",
    objective: str = "计算每个点的 epsilon 邻域，并区分核心点、边界点与噪声点",
    acceptance: str = "所有点的标签与参考解一致",
    evidence_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "requirement": requirement,
        "objective": objective,
        "acceptance": acceptance,
        "evidence_ids": list(evidence_ids),
    }


def add_document(database: Database, document_id: str, versions: tuple[int, ...] = (1,)) -> None:
    """Create a document and the versions the test names, without fighting the schema's own work.

    Creating the document row already produces a first version (the product's own trigger), so this
    inserts only the versions that are still missing — a fixture that hard-codes version 1 collides
    with the trigger rather than testing anything.
    """
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,"
            "sha256,byte_size,status,chunk_count) VALUES(?,?,'lecture.md','lecture.md',"
            "'text/markdown','.md',?,12,'ready',1)",
            (document_id, COURSE, "f" * 64),
        )
        existing = {
            int(row["version"])
            for row in connection.execute(
                "SELECT version FROM document_versions WHERE document_id = ?", (document_id,)
            )
        }
        for version in versions:
            if version in existing:
                continue
            connection.execute(
                "INSERT INTO document_versions(id,document_id,version,course_id,owner_user_id,"
                "source_scope,filename,stored_path,media_type,extension,sha256,byte_size) "
                "VALUES(?,?,?,?,'user-a','OWNER_COURSE','lecture.md','lecture.md','text/markdown',"
                "'.md',?,12)",
                (f"{document_id}-v{version}", document_id, version, COURSE, str(version) * 64),
            )


def blueprint(**overrides: Any) -> QuestionBlueprint:
    values: dict[str, Any] = {
        "blueprint_id": "bp-1",
        "course_id": COURSE,
        "node_id": NODE,
        "spec_version": 1,
        "spec_content_hash": HASH_A,
        "objective_id": "obj-cluster",
        "objective_text": "计算每个点的 epsilon 邻域，并区分核心点、边界点与噪声点",
        "source_scope": [
            {"document_id": "doc-1", "version": 1, "locator": "p.3", "content_hash": HASH_B}
        ],
        "bloom_target": "APPLY",
        "target_difficulty": 3,
        "difficulty_features": ["STEPS", "COMPUTATION"],
        "question_type": "NUMERIC",
        "expected_answer_form": "NUMERIC_VALUE",
        "marks": 15,
        "scoring_criteria": ["核心点判定正确", "边界/噪声区分正确"],
        "question_family_id": "family-density-clustering",
        "generation_policy_version": "gen-policy-v1",
    }
    values.update(overrides)
    return QuestionBlueprint(**values)


# --------------------------------------------------------------------------- contract refusals


def test_a_bare_topic_is_not_an_objective() -> None:
    assert objective_is_observable("DBSCAN") is False
    assert objective_is_observable("聚类") is False
    assert objective_is_observable("计算每个点的邻域并区分核心点与噪声点") is True
    assert objective_is_observable("Distinguish core, border and noise points") is True

    with pytest.raises(ValidationError) as refusal:
        blueprint(objective_text="DBSCAN")
    assert "observable action" in str(refusal.value)


def test_a_model_cannot_grant_itself_authority() -> None:
    """The keys that would let a model decide permissions, verification or grades do not exist."""
    for extra in (
        {"official": True},
        {"verification_level": "VALIDATED"},
        {"owner_user_id": "user-a"},
        {"grade": 15},
        {"answer_key": "D"},
    ):
        with pytest.raises(ValidationError):
            blueprint(**extra)

    with pytest.raises(ValidationError):
        blueprint(marks=0)
    with pytest.raises(ValidationError):
        blueprint(marks=101)


def test_the_three_control_dimensions_stay_separate() -> None:
    # Cognitive task and preset difficulty are independent: nothing couples REMEMBER to easy or
    # CREATE to hard, and the most expensive reasoning setting is not a difficulty input at all.
    blueprint(bloom_target="REMEMBER", target_difficulty=5)
    blueprint(bloom_target="CREATE", target_difficulty=1)

    # A preset difficulty must be justified by named features, and no empirical difficulty may be
    # claimed while no independent attempts have been measured.
    with pytest.raises(ValidationError):
        blueprint(difficulty_features=[])
    with pytest.raises(ValidationError):
        blueprint(empirical_difficulty=3)
    assert blueprint().empirical_difficulty is None


def test_question_type_decides_the_answer_form() -> None:
    for question_type, form in EXPECTED_FORM_BY_TYPE.items():
        blueprint(question_type=question_type, expected_answer_form=form)
    with pytest.raises(ValidationError) as refusal:
        blueprint(question_type="NUMERIC", expected_answer_form="SHORT_ANSWER")
    assert "requires expected_answer_form" in str(refusal.value)


def test_single_choice_cannot_be_solution_only() -> None:
    blueprint(
        question_type="MCQ_SINGLE",
        expected_answer_form="SINGLE_CHOICE",
        answer_policy="HIDDEN_UNTIL_REVEAL",
    )
    with pytest.raises(ValidationError):
        blueprint(
            question_type="MCQ_SINGLE",
            expected_answer_form="SINGLE_CHOICE",
            answer_policy="SOLUTION_ONLY",
        )


def test_source_scope_is_required_and_content_addressed() -> None:
    with pytest.raises(ValidationError):
        blueprint(source_scope=[])
    with pytest.raises(ValidationError):
        blueprint(
            source_scope=[{"document_id": "doc-1", "version": 1, "content_hash": "not-a-hash"}]
        )
    assert is_hex64(HASH_B) is True
    assert is_hex64(HASH_B[:-1]) is False


def test_identity_is_stable_and_changes_with_content() -> None:
    first, second = blueprint(), blueprint()
    assert first.identity() == second.identity()
    assert len(first.identity()) == 64
    assert blueprint(marks=20).identity() != first.identity()
    assert blueprint(objective_id="obj-other").identity() != first.identity()


# --------------------------------------------------------------------------- real-row resolution


def test_resolution_reads_the_newest_spec_and_the_first_required_item(
    tmp_path: pathlib.Path,
) -> None:
    database = make_db(tmp_path)
    add_spec(database, 1, [item("obj-old")], HASH_A)
    add_spec(
        database,
        2,
        [
            item("obj-distract", requirement="RECOMMENDED"),
            item("obj-cluster", evidence_ids=("doc-1",)),
        ],
        HASH_B,
    )

    with database.connect() as connection:
        objective = resolve_objective(connection, node_id=NODE)

    assert objective.spec_version == 2
    assert objective.spec_content_hash == HASH_B
    assert objective.item_id == "obj-cluster"
    assert objective.requirement == "REQUIRED"
    assert objective.evidence_ids == ("doc-1",)
    assert objective_is_observable(objective.objective) is True

    # An explicit item still resolves, and a named-but-absent one is refused with its own code.
    with database.connect() as connection:
        named = resolve_objective(connection, node_id=NODE, item_id="obj-distract")
    assert named.item_id == "obj-distract"
    with database.connect() as connection, pytest.raises(ObjectiveResolutionError) as refusal:
        resolve_objective(connection, node_id=NODE, item_id="obj-ghost")
    assert refusal.value.code == "OBJECTIVE_NOT_IN_SPEC"


def test_resolution_refuses_when_there_is_nothing_to_teach(tmp_path: pathlib.Path) -> None:
    database = make_db(tmp_path)
    with database.connect() as connection, pytest.raises(ObjectiveResolutionError) as refusal:
        resolve_objective(connection, node_id=NODE)
    assert refusal.value.code == "NO_TEACHING_SPEC"
    assert NODE in str(refusal.value)

    # A spec that declares only optional items cannot yield a question target either: silently
    # generating from an OPTIONAL objective would invent the scope of the exercise.
    add_spec(database, 1, [item("obj-optional", requirement="OPTIONAL")])
    with database.connect() as connection, pytest.raises(ObjectiveResolutionError) as refusal:
        resolve_objective(connection, node_id=NODE)
    assert refusal.value.code == "NO_REQUIRED_ITEM"


def test_evidence_scope_uses_the_newest_version_and_refuses_unknown_documents(
    tmp_path: pathlib.Path,
) -> None:
    database = make_db(tmp_path)
    add_document(database, "doc-1", versions=(1, 2, 3))

    with database.connect() as connection:
        scope = evidence_scope(connection, ("doc-1",))
    assert len(scope) == 1
    assert scope[0].version == 3
    assert scope[0].content_hash == "3" * 64

    with database.connect() as connection, pytest.raises(ObjectiveResolutionError) as refusal:
        evidence_scope(connection, ("doc-missing",))
    assert refusal.value.code == "SOURCE_NOT_FOUND"

    # The resolved scope is exactly what the blueprint accepts, so the two cannot drift.
    entry = scope[0].model_dump()
    blueprint(source_scope=[entry])


def test_a_resolved_objective_and_scope_produce_a_valid_blueprint(tmp_path: pathlib.Path) -> None:
    """The two stages compose: real rows in, a blueprint that the contract accepts out."""
    database = make_db(tmp_path)
    add_spec(database, 1, [item("obj-cluster", evidence_ids=("doc-1",))])
    add_document(database, "doc-1", versions=(1,))

    with database.connect() as connection:
        objective = resolve_objective(connection, node_id=NODE)
        scope = evidence_scope(connection, objective.evidence_ids)

    resolved = blueprint(
        objective_id=objective.item_id,
        objective_text=objective.objective,
        spec_version=objective.spec_version,
        spec_content_hash=objective.spec_content_hash,
        source_scope=[entry.model_dump() for entry in scope],
    )
    assert resolved.objective_id == "obj-cluster"
    assert resolved.source_scope[0].document_id == "doc-1"
    assert hashlib.sha256(resolved.identity().encode()).hexdigest() != ""
