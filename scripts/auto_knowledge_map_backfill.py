"""Reconcile and optionally drain CourseJesus automatic knowledge-map jobs.

This command reads only the current application database and indexed chunks. It
never scans import folders or downloads new material. Queue-only mode is free;
``--drain`` is refused unless the two production feature gates are both set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG_ROOT = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_ROOT))

from app.config import Settings
from app.main import create_app


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drain", action="store_true", help="run queued jobs until empty")
    parser.add_argument("--inventory", type=Path, help="append one JSON record per target/job")
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=0,
        help="maximum jobs to run in this invocation; 0 drains every claimable job",
    )
    parser.add_argument(
        "--worker-id",
        default=f"backfill-{os.getpid()}",
        help="durable lease owner label",
    )
    return parser.parse_args()


def emit(handle: object, record: dict[str, object]) -> None:
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    print(line, flush=True)
    if handle is not None:
        handle.write(line + "\n")  # type: ignore[attr-defined]
        handle.flush()  # type: ignore[attr-defined]


def main() -> int:
    args = arguments()
    if args.max_jobs < 0:
        raise SystemExit("--max-jobs must be zero or a positive integer")
    settings = Settings()
    if args.drain and not (
        settings.auto_knowledge_map_enabled and settings.auto_knowledge_map_allow_billable
    ):
        raise SystemExit(
            "--drain requires AUTO_KNOWLEDGE_MAP_ENABLED=true and "
            "AUTO_KNOWLEDGE_MAP_ALLOW_BILLABLE=true"
        )
    application = create_app(settings=settings)
    service = application.state.auto_knowledge_map
    handle = None
    if args.inventory:
        args.inventory.parent.mkdir(parents=True, exist_ok=True)
        handle = args.inventory.open("a", encoding="utf-8", newline="\n")
    try:
        emit(handle, {"kind": "reconcile", "counts": service.reconcile(force=True)})
        drained = 0
        if args.drain:
            while True:
                if args.max_jobs and drained >= args.max_jobs:
                    break
                result = service.run_once(args.worker_id)
                if result is None:
                    break
                drained += 1
                emit(handle, {"kind": "job", **result})
        with application.state.database.connect() as connection:
            for row in connection.execute(
                "SELECT target_key,course_id,workspace_id,owner_user_id,target_kind,status,"
                "corpus_fingerprint,active_job_id,active_tree_version_id,"
                "readable_document_count,unreadable_document_count,message,updated_at "
                "FROM auto_knowledge_targets ORDER BY course_id,target_kind,target_key"
            ):
                emit(handle, {"kind": "target", **dict(row)})
            for row in connection.execute(
                "SELECT job_id,target_key,corpus_fingerprint,status,tree_version_id,"
                "source_snapshot_hash,result_hash,model_calls_made,detail_json,created_at "
                "FROM auto_knowledge_job_receipts ORDER BY created_at,job_id"
            ):
                record = dict(row)
                record["detail"] = json.loads(record.pop("detail_json"))
                emit(handle, {"kind": "receipt", **record})
            target_counts = {
                str(row["status"]): int(row["count"])
                for row in connection.execute(
                    "SELECT status,COUNT(*) AS count FROM auto_knowledge_targets "
                    "GROUP BY status ORDER BY status"
                )
            }
            job_counts = {
                str(row["status"]): int(row["count"])
                for row in connection.execute(
                    "SELECT status,COUNT(*) AS count FROM auto_knowledge_jobs "
                    "GROUP BY status ORDER BY status"
                )
            }
            totals = connection.execute(
                "SELECT COUNT(*) AS jobs,COALESCE(SUM(model_calls_made),0) AS model_calls,"
                "COALESCE(SUM(repair_calls_made),0) AS repair_calls FROM auto_knowledge_jobs"
            ).fetchone()
            artifacts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM auto_knowledge_job_artifacts"
                ).fetchone()[0]
            )
            emit(
                handle,
                {
                    "kind": "summary",
                    "jobs_drained_this_run": drained,
                    "target_statuses": target_counts,
                    "job_statuses": job_counts,
                    "job_count": int(totals["jobs"]),
                    "model_calls_recorded": int(totals["model_calls"]),
                    "repair_calls_recorded": int(totals["repair_calls"]),
                    "artifact_count": artifacts,
                },
            )
    finally:
        if handle is not None:
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
