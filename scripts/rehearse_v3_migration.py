"""Run additive V3 migrations only on a fresh SQLite online-backup copy."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/rag-api"))
from app.config import Settings  # noqa: E402 - repository-local service bootstrap
from app.db import LATEST_V3_SCHEMA_VERSION, Database  # noqa: E402

TABLES = (
    "courses",
    "documents",
    "chunks",
    "ingestion_jobs",
    "conversations",
    "messages",
    "course_teaching_profiles",
    "course_publication_requests",
    "rate_limit_windows",
)


def fingerprints(connection: sqlite3.Connection) -> dict[str, dict[str, object]]:
    result = {}
    for table in TABLES:
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        result[table] = {
            "rows": len(rows),
            "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
        }
    return result


def rehearse(source: Path, target: Path) -> dict[str, object]:
    source, target = source.resolve(), target.resolve()
    if not source.is_file() or target.exists() or not target.is_relative_to(ROOT / "work"):
        raise ValueError("Use an existing source and a fresh isolated target directory under work")
    target.mkdir(parents=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        before = fingerprints(original)
        with sqlite3.connect(target / "rag.sqlite3") as copied:
            original.backup(copied)
    database = Database(
        Settings(
            database_path=target / "rag.sqlite3",
            upload_dir=target / "uploads",
            v3_enabled=True,
        )
    )
    database.initialize()
    database.initialize()
    with sqlite3.connect(target / "rag.sqlite3") as copied:
        after = fingerprints(copied)
        integrity = copied.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = copied.execute("PRAGMA foreign_key_check").fetchall()
        versions = [
            row[0]
            for row in copied.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        v3_invariants = {
            "document_versions": copied.execute(
                "SELECT COUNT(*) FROM document_versions"
            ).fetchone()[0],
            "documents": copied.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "unbound_chunks": copied.execute(
                "SELECT COUNT(*) FROM chunks LEFT JOIN chunk_source_versions "
                "ON chunk_source_versions.chunk_id=chunks.id "
                "WHERE chunk_source_versions.chunk_id IS NULL"
            ).fetchone()[0],
            "invalid_source_owners": copied.execute(
                "SELECT COUNT(*) FROM document_versions WHERE "
                "(source_scope='OFFICIAL' AND owner_user_id IS NOT NULL) OR "
                "(source_scope!='OFFICIAL' AND owner_user_id IS NULL)"
            ).fetchone()[0],
            "problem_index_entries": copied.execute(
                "SELECT COUNT(*) FROM problem_index_entries"
            ).fetchone()[0],
            "learning_problems": copied.execute(
                "SELECT COUNT(*) FROM learning_problems"
            ).fetchone()[0],
            "problem_revisions": copied.execute(
                "SELECT COUNT(*) FROM problem_revisions"
            ).fetchone()[0],
            "learning_solutions": copied.execute(
                "SELECT COUNT(*) FROM learning_solutions"
            ).fetchone()[0],
            "solution_revisions": copied.execute(
                "SELECT COUNT(*) FROM solution_revisions"
            ).fetchone()[0],
            "learning_steps": copied.execute(
                "SELECT COUNT(*) FROM learning_steps"
            ).fetchone()[0],
            "step_knowledge_links": copied.execute(
                "SELECT COUNT(*) FROM step_knowledge_links"
            ).fetchone()[0],
            "learning_bridges": copied.execute(
                "SELECT COUNT(*) FROM learning_bridges"
            ).fetchone()[0],
            "learning_bridge_contexts": copied.execute(
                "SELECT COUNT(*) FROM learning_bridge_contexts"
            ).fetchone()[0],
            "invalid_problem_index_sources": copied.execute(
                "SELECT COUNT(*) FROM problem_index_entries AS problem "
                "LEFT JOIN chunks AS chunk ON chunk.id=problem.chunk_id "
                "LEFT JOIN chunk_source_versions AS source "
                "ON source.chunk_id=problem.chunk_id "
                "LEFT JOIN document_versions AS version "
                "ON version.id=problem.document_version_id "
                "WHERE chunk.id IS NULL OR source.document_version_id IS NULL "
                "OR source.document_version_id!=problem.document_version_id "
                "OR version.id IS NULL OR version.document_id!=chunk.document_id "
                "OR problem.course_id!=chunk.course_id"
            ).fetchone()[0],
            "problems_without_revisions": copied.execute(
                "SELECT COUNT(*) FROM learning_problems AS problem "
                "WHERE NOT EXISTS(SELECT 1 FROM problem_revisions AS revision "
                "WHERE revision.problem_id=problem.id)"
            ).fetchone()[0],
            "solutions_without_revisions": copied.execute(
                "SELECT COUNT(*) FROM learning_solutions AS solution "
                "WHERE NOT EXISTS(SELECT 1 FROM solution_revisions AS revision "
                "WHERE revision.solution_id=solution.id)"
            ).fetchone()[0],
            "legacy_step_links_without_normalized_rows": copied.execute(
                "SELECT COUNT(*) FROM learning_steps AS step, "
                "json_each(json_extract(step.content_json, '$.knowledge_links')) AS link "
                "WHERE json_type(link.value, '$.node_id')='text' "
                "AND json_type(link.value, '$.question_text')='text' "
                "AND json_type(link.value, '$.reason')='text' "
                "AND NOT EXISTS(SELECT 1 FROM step_knowledge_links AS normalized "
                "WHERE normalized.step_id=step.id "
                "AND normalized.ordinal=CAST(link.key AS INTEGER)+1)"
            ).fetchone()[0],
            "bridges_without_contexts": copied.execute(
                "SELECT COUNT(*) FROM learning_bridges AS bridge "
                "WHERE NOT EXISTS(SELECT 1 FROM learning_bridge_contexts AS context "
                "WHERE context.bridge_id=bridge.id)"
            ).fetchone()[0],
            "assessment_question_revisions": copied.execute(
                "SELECT COUNT(*) FROM assessment_question_revisions"
            ).fetchone()[0],
            "assessment_rubric_criteria": copied.execute(
                "SELECT COUNT(*) FROM assessment_rubric_criteria"
            ).fetchone()[0],
            "assessment_blueprint_versions": copied.execute(
                "SELECT COUNT(*) FROM assessment_blueprint_versions"
            ).fetchone()[0],
            "assessment_blueprint_items": copied.execute(
                "SELECT COUNT(*) FROM assessment_blueprint_items"
            ).fetchone()[0],
            "assessment_sessions": copied.execute(
                "SELECT COUNT(*) FROM assessment_sessions"
            ).fetchone()[0],
            "assessment_question_attempts": copied.execute(
                "SELECT COUNT(*) FROM assessment_question_attempts"
            ).fetchone()[0],
            "assessment_exposure_events": copied.execute(
                "SELECT COUNT(*) FROM assessment_exposure_events"
            ).fetchone()[0],
            "performance_evidence": copied.execute(
                "SELECT COUNT(*) FROM performance_evidence"
            ).fetchone()[0],
            "learning_replan_triggers": copied.execute(
                "SELECT COUNT(*) FROM learning_replan_triggers"
            ).fetchone()[0],
            "teaching_unit_remediations": copied.execute(
                "SELECT COUNT(*) FROM teaching_unit_remediations"
            ).fetchone()[0],
            "teaching_plan_performance_triggers": copied.execute(
                "SELECT COUNT(*) FROM teaching_plan_performance_triggers"
            ).fetchone()[0],
            "grade_policy_versions": copied.execute(
                "SELECT COUNT(*) FROM grade_policy_versions"
            ).fetchone()[0],
            "assessment_blueprint_grade_policies": copied.execute(
                "SELECT COUNT(*) FROM assessment_blueprint_grade_policies"
            ).fetchone()[0],
            "grade_snapshots": copied.execute(
                "SELECT COUNT(*) FROM grade_snapshots"
            ).fetchone()[0],
            "requirements_grade_policy_seed": copied.execute(
                "SELECT COUNT(*) FROM grade_policy_versions "
                "WHERE id='gp_requirements_draft_v1' "
                "AND status='DRAFT_UNCONFIGURED' "
                "AND provenance_label='Requirements draft; not an institutional policy' "
                "AND json_array_length(raw_score_bands_json)=0 "
                "AND json_extract(numeric_scale_json,'$[2].letter')='A-' "
                "AND json_type(numeric_scale_json,'$[2].numeric_value')='null'"
            ).fetchone()[0],
            "invalid_frozen_assessment_blueprints": copied.execute(
                "SELECT COUNT(*) FROM assessment_blueprint_versions AS blueprint "
                "WHERE blueprint.status IN ('FROZEN','RETIRED') AND ("
                "(SELECT COUNT(*) FROM assessment_blueprint_items AS item "
                " WHERE item.blueprint_id=blueprint.id)!=5 OR "
                "(SELECT COALESCE(SUM(item.marks),0) "
                " FROM assessment_blueprint_items AS item "
                " WHERE item.blueprint_id=blueprint.id)!=100 OR "
                "(SELECT MIN(item.marks) FROM assessment_blueprint_items AS item "
                " WHERE item.blueprint_id=blueprint.id)="
                "(SELECT MAX(item.marks) FROM assessment_blueprint_items AS item "
                " WHERE item.blueprint_id=blueprint.id))"
            ).fetchone()[0],
            "assessment_sessions_without_five_attempts": copied.execute(
                "SELECT COUNT(*) FROM assessment_sessions AS session "
                "WHERE (SELECT COUNT(*) FROM assessment_question_attempts AS attempt "
                "WHERE attempt.session_id=session.id)!=5"
            ).fetchone()[0],
            "frozen_blueprints_without_grade_policy": copied.execute(
                "SELECT COUNT(*) FROM assessment_blueprint_versions AS blueprint "
                "WHERE blueprint.status IN ('FROZEN','RETIRED') "
                "AND NOT EXISTS(SELECT 1 FROM assessment_blueprint_grade_policies AS policy "
                "WHERE policy.blueprint_id=blueprint.id)"
            ).fetchone()[0],
            "invalid_assessment_policy_bindings": copied.execute(
                "SELECT COUNT(*) FROM assessment_blueprint_grade_policies AS binding "
                "JOIN grade_policy_versions AS policy "
                "ON policy.id=binding.grade_policy_version_id WHERE "
                "(binding.mapping_status='CONFIGURED' "
                " AND policy.status NOT IN ('PUBLISHED','RETIRED')) OR "
                "(binding.mapping_status='UNCONFIGURED' "
                " AND policy.status!='DRAFT_UNCONFIGURED')"
            ).fetchone()[0],
            "invalid_independent_performance_evidence": copied.execute(
                "SELECT COUNT(*) FROM performance_evidence AS evidence "
                "JOIN assessment_sessions AS session "
                "ON session.id=evidence.assessment_session_id "
                "JOIN assessment_question_attempts AS attempt "
                "ON attempt.id=evidence.question_attempt_id "
                "WHERE evidence.independent_eligible=1 AND ("
                "session.mode!='INDEPENDENT' OR session.assistance_status!='UNASSISTED' "
                "OR attempt.assistance!='NONE')"
            ).fetchone()[0],
            "invalid_grade_snapshot_bindings": copied.execute(
                "SELECT COUNT(*) FROM grade_snapshots AS snapshot "
                "JOIN assessment_sessions AS session "
                "ON session.id=snapshot.assessment_session_id "
                "LEFT JOIN assessment_blueprint_grade_policies AS binding "
                "ON binding.blueprint_id=session.blueprint_id "
                "WHERE binding.blueprint_id IS NULL "
                "OR binding.grade_policy_version_id!=snapshot.grade_policy_version_id "
                "OR binding.mapping_status!=snapshot.mapping_status"
            ).fetchone()[0],
        }
    invariants_ok = (
        v3_invariants["document_versions"] == v3_invariants["documents"]
        and v3_invariants["unbound_chunks"] == 0
        and v3_invariants["invalid_source_owners"] == 0
        and v3_invariants["invalid_problem_index_sources"] == 0
        and v3_invariants["problems_without_revisions"] == 0
        and v3_invariants["solutions_without_revisions"] == 0
        and v3_invariants["legacy_step_links_without_normalized_rows"] == 0
        and v3_invariants["bridges_without_contexts"] == 0
        and v3_invariants["requirements_grade_policy_seed"] == 1
        and v3_invariants["invalid_frozen_assessment_blueprints"] == 0
        and v3_invariants["assessment_sessions_without_five_attempts"] == 0
        and v3_invariants["frozen_blueprints_without_grade_policy"] == 0
        and v3_invariants["invalid_assessment_policy_bindings"] == 0
        and v3_invariants["invalid_independent_performance_evidence"] == 0
        and v3_invariants["invalid_grade_snapshot_bindings"] == 0
        and versions == list(range(1, LATEST_V3_SCHEMA_VERSION + 1))
    )
    result = {
        "old_rows_unchanged": before == after,
        "integrity": integrity,
        "foreign_key_violations": len(foreign_keys),
        "versions": versions,
        "v3_invariants": v3_invariants,
        "v3_invariants_ok": invariants_ok,
        "before": before,
        "after": after,
    }
    (target / "migration-evidence.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    if before != after or integrity != "ok" or foreign_keys or not invariants_ok:
        raise RuntimeError("Migration rehearsal failed; inspect local content-free evidence")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rehearse(args.source, args.target)))
