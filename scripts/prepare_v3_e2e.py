"""Create synthetic-only E2E state. Never open the actual course database."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/rag-api"))

from app.config import Settings
from app.db import Database
from app.learning.workspaces import join_course

OWNER = "v3-e2e-owner"
ASSESSMENT_NODE = "e2e-assessment-node"


def seed_assessment_fixture(db: Database) -> None:
    join_course(db, "cs3481", OWNER, 10)
    item = {
        "item_id": "principle",
        "requirement": "REQUIRED",
        "objective": "Explain the synthetic assessment concept",
        "acceptance": "Answer one bounded synthetic check",
        "evidence_ids": [],
    }
    content = json.dumps([item], ensure_ascii=False, sort_keys=True)
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes("
            "id,course_id,owner_user_id,title,description,major,kind,status) "
            "VALUES(?,'cs3481',?,'Assessment Addition',"
            "'Synthetic browser-only assessment node','CS','ATOMIC','PRIVATE')",
            (ASSESSMENT_NODE, OWNER),
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES(?,1,?,?)",
            (ASSESSMENT_NODE, content, hashlib.sha256(content.encode()).hexdigest()),
        )
        sources = [
            ("OFFICIAL", None, "OFFICIAL"),
            ("WORKSPACE_PRIVATE", OWNER, "OWNER_AUTHORED"),
            ("MODEL_GENERATED", OWNER, "DETERMINISTIC"),
            ("EXTERNAL_INSPIRED", OWNER, "HUMAN_REVIEWED"),
            ("OFFICIAL", None, "OFFICIAL"),
        ]
        for ordinal, (source, owner, verification) in enumerate(sources, start=1):
            question_id = f"e2e-question-{ordinal}"
            prompt = f"Synthetic assessment question {ordinal}: type correct."
            answer = {"accepted": ["correct"], "case_sensitive": False}
            question_content = json.dumps(
                {"prompt": prompt, "answer": answer},
                sort_keys=True,
            )
            connection.execute(
                "INSERT INTO assessment_question_revisions("
                "id,course_id,owner_user_id,family_id,revision,source_kind,"
                "question_type,difficulty,prompt_text,options_json,answer_json,"
                "validation_status,verification_method,content_hash,created_by_user_id) "
                "VALUES(?,'cs3481',?,?,1,?,'SHORT_TEXT',?,?,'[]',?,'VALIDATED',?,?,?)",
                (
                    question_id,
                    owner,
                    f"e2e-family-{ordinal}",
                    source,
                    ordinal,
                    prompt,
                    json.dumps(answer),
                    verification,
                    hashlib.sha256(question_content.encode()).hexdigest(),
                    owner or "E2E_FIXTURE_ADMIN",
                ),
            )
            connection.execute(
                "INSERT INTO assessment_rubric_criteria("
                "question_revision_id,criterion_id,node_id,spec_version,item_id,"
                "dimension,max_fraction,description,deterministic_rule_json) "
                "VALUES(?,'correctness',?,1,'principle','CONCEPT',100,"
                "'Matches the synthetic fixture answer.','{}')",
                (question_id, ASSESSMENT_NODE),
            )


def main() -> None:
    target = Path(sys.argv[1]).resolve()
    if not target.is_relative_to(ROOT / "work") or target.exists():
        raise ValueError("A fresh directory under work is required")
    db = Database(
        Settings(
            database_path=target / "rag.db",
            upload_dir=target / "uploads",
            v3_enabled=True,
        )
    )
    db.initialize()
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,publication_status) "
            "VALUES('cs3481','Synthetic CS3481 fixture','published')"
        )
    seed_assessment_fixture(db)


if __name__ == "__main__":
    main()
