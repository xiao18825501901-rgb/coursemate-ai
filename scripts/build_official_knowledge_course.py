#!/usr/bin/env python
"""M6D4 ops driver: build one full official course knowledge DRAFT.

Resumable via the plan ledger; idempotent; enforces the authorized attempt and
reserved-token ceilings per run. Real Qwen calls happen ONLY through
LearningOrchestrator.generate (reservations ledger). Retrieval uses the
deterministic embedding provider so no embedding API spend occurs.

Usage (run on the server with production env exported):
  python scripts/build_official_knowledge_course.py \
      --course cs3481 --plan work/m6d4/plan-cs3481.json \
      --operation-id m6d4-cs3481 \
      --attempt-ceiling 120 --reserved-ceiling 480000 \
      --json-out work/m6d4/result-cs3481.json
"""

import argparse
import json
import sys
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.learning.orchestrator import LearningOrchestrator
from app.models import OfficialKnowledgeCourseBuild, OfficialKnowledgeCoursePlan
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.rag.retrieval import HybridRetriever
from app.repositories.chunks import ChunkRepository
from app.services.official_knowledge_course_builder import OfficialKnowledgeCourseBuilder
from app.services.official_knowledge_draft_builder import OfficialKnowledgeDraftBuilder


def ledger(database: Database) -> tuple[int, int]:
    with database.connect() as connection:
        attempts = connection.execute(
            "SELECT COUNT(*) FROM learning_model_call_reservations"
        ).fetchone()[0]
        reserved = connection.execute(
            "SELECT COALESCE(SUM(reserved_output_tokens),0) "
            "FROM learning_model_call_reservations"
        ).fetchone()[0]
    return int(attempts), int(reserved)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", required=True)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--max-model-calls-per-batch", type=int, default=2)
    parser.add_argument("--max-reserved-output-tokens-per-batch", type=int, default=8000)
    parser.add_argument("--attempt-ceiling", type=int, default=120)
    parser.add_argument("--reserved-ceiling", type=int, default=480000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    settings = Settings()
    database = Database(settings)
    database.initialize()
    orchestrator = LearningOrchestrator(
        database,
        settings,
        HybridRetriever(ChunkRepository(database), DeterministicEmbeddingProvider()),
    )
    node_builder = OfficialKnowledgeDraftBuilder(database, settings, orchestrator)
    builder = OfficialKnowledgeCourseBuilder(database, settings, orchestrator, node_builder)
    raw_plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if isinstance(raw_plan, dict) and "plan" in raw_plan:
        raw_plan = raw_plan["plan"]
    plan = OfficialKnowledgeCoursePlan.model_validate(raw_plan)
    payload = OfficialKnowledgeCourseBuild(
        operation_id=args.operation_id,
        plan=plan,
        max_model_calls_per_batch=args.max_model_calls_per_batch,
        max_reserved_output_tokens_per_batch=args.max_reserved_output_tokens_per_batch,
        dry_run=args.dry_run,
    )
    admin_user_id = sorted(settings.admin_user_id_set)[0]
    attempts_before, reserved_before = ledger(database)
    result = None
    try:
        result = builder.build(args.course, payload, admin_user_id=admin_user_id)
        status = 0
    except Exception as error:  # noqa: BLE001 - ops driver boundary
        print(f"BUILD_FAILED {type(error).__name__}: {error}")
        status = 1
    attempts_after, reserved_after = ledger(database)
    delta_attempts = attempts_after - attempts_before
    delta_reserved = reserved_after - reserved_before
    print(f"RUN_ATTEMPTS_DELTA={delta_attempts}")
    print(f"RUN_RESERVED_DELTA={delta_reserved}")
    print(f"CEILING_OK={delta_attempts <= args.attempt_ceiling and delta_reserved <= args.reserved_ceiling}")
    if result is not None:
        print("RESULT", result.model_dump_json())
        if args.json_out:
            args.json_out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return status


if __name__ == "__main__":
    sys.exit(main())
