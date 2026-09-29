"""Review-only recovery for candidates whose authoring is already complete.

    # what is available
    python scripts/review_existing_candidates.py --database <copy> --list

    # the review card an owner needs to decide the one case a model cannot
    python scripts/review_existing_candidates.py --database <copy> --card <row-id>

    # run the hybrid review and record the receipt (billable provider calls)
    python scripts/review_existing_candidates.py --database <copy> --review <row-id>

The card is generated without any provider call, so it can be produced for every
candidate first and reviewed at the owner's convenience.  Nothing is published by
this script: it writes review receipts, never a question.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.learning.candidate_recovery import (  # noqa: E402
    CandidateRecoveryError,
    deterministic_report_for,
    list_recoverable,
    recover_candidate,
)
from app.learning.human_review_card import CARD_QUESTIONS, build_card_prompt  # noqa: E402


def _database(path: str, *, allow_live: bool) -> Database:
    """Open the target database, refusing the live one unless asked.

    This guard exists because the mistake it prevents was made: a helper sourced
    the deployment environment, which points ``RAG_DATABASE_PATH`` at the live
    file, and a migration was applied to production by accident.  The migration
    was purely additive, but a tool that reviews and records receipts must not be
    able to reach production just because an environment happened to say so.
    """
    resolved = Path(path).resolve()
    if not allow_live:
        import os

        live = os.environ.get("RAG_DATABASE_PATH")
        if live and Path(live).resolve() == resolved:
            raise SystemExit(
                json.dumps(
                    {
                        "status": "REFUSED",
                        "code": "REFUSES_LIVE_DATABASE",
                        "message": (
                            "this path is the live RAG_DATABASE_PATH; pass "
                            "--allow-live-database only when that is genuinely intended"
                        ),
                    }
                )
            )
    settings = Settings()
    return Database(
        settings.model_copy(
            update={
                "database_path": resolved,
                "upload_dir": resolved.parent / "uploads",
            }
        )
    )


def _card_payload(record) -> dict[str, object]:
    """The card an owner reviews.  Contains the item; callers must not log it."""
    prompt = build_card_prompt(
        question_revision_hash=record.candidate.question_revision,
        question_type=record.blueprint.question_type,
        stem=record.candidate.public_question.question_text,
        options=tuple(record.candidate.public_question.options),
        source_spans=tuple(
            {"evidence_id": fragment.evidence_id, "content": fragment.content}
            for fragment in record.evidence.fragments
        ),
    )
    report = deterministic_report_for(record)
    return {
        "question_revision_id": record.question_revision_id,
        "question_revision_hash": record.candidate.question_revision,
        "publication_status": record.publication_status,
        "readiness_reason": record.readiness_reason,
        "question_type": record.blueprint.question_type,
        "marks": record.blueprint.marks,
        "conditions": record.blueprint.conditions,
        "deterministic_gates": {
            gate.gate: gate.status for gate in report.hard_gates
        },
        "stem": prompt.stem,
        "options": list(prompt.options),
        "source_spans": list(prompt.source_spans),
        "open_questions": list(CARD_QUESTIONS),
        "how_to_answer": (
            "For each thing the answer depends on, record {datum, stated_in_stem, "
            "answer_changes_if_absent} and, when the last is true, the consequence: "
            "the concrete different answer that would result.  The card passes the "
            "item only when nothing the answer turns on is missing."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--card")
    parser.add_argument("--review")
    parser.add_argument("--out", default="")
    parser.add_argument("--max-output-tokens", type=int, default=4000)
    parser.add_argument(
        "--allow-live-database",
        action="store_true",
        help="permit the path that RAG_DATABASE_PATH points at (default: refuse)",
    )
    args = parser.parse_args()

    database = _database(args.database, allow_live=args.allow_live_database)

    if args.list:
        rows = list_recoverable(database, limit=args.limit)
        print(
            json.dumps(
                {
                    "candidates": [
                        {
                            "question_revision_id": row["question_revision_id"],
                            "course_id": row["course_id"],
                            "node_id": row["node_id"],
                            "question_type": row["question_type"],
                            "publication_status": row["publication_status"],
                            "readiness_reason": row["readiness_reason"],
                            "created_at": row["created_at"],
                        }
                        for row in rows
                    ]
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    target = args.card or args.review
    if not target:
        parser.error("one of --list, --card or --review is required")

    try:
        record = recover_candidate(database, question_revision_id=target)
    except CandidateRecoveryError as error:
        print(json.dumps({"status": "REFUSED", "code": error.code, "message": str(error)}))
        return 3

    if args.card:
        payload = _card_payload(record)
        if args.out:
            # The card contains private course material; the caller chooses a
            # protected location and nothing is printed beyond the summary.
            Path(args.out).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(
            json.dumps(
                {
                    "status": "CARD_READY",
                    "question_revision_id": record.question_revision_id,
                    "question_revision_hash": record.candidate.question_revision,
                    "question_type": record.blueprint.question_type,
                    "stem_chars": len(str(payload["stem"])),
                    "options": len(payload["options"]),  # type: ignore[arg-type]
                    "source_spans": len(payload["source_spans"]),  # type: ignore[arg-type]
                    "deterministic_gates": payload["deterministic_gates"],
                    "written_to": args.out or None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    # --review: the real billable path.
    from app.learning.deepseek_reviewer import DeepSeekStrongReviewer
    from app.learning.hybrid_quality import HybridQualityService
    from app.learning.provider import LearningProvider

    settings = Settings()
    provider = LearningProvider(
        settings.model_copy(update={"database_path": Path(args.database)})
    )
    reviewer = DeepSeekStrongReviewer(
        provider,
        model_alias=settings.v3_model,
        max_output_tokens=args.max_output_tokens,
    )
    service = HybridQualityService(database, reviewer)
    try:
        outcome = service.review(
            candidate=record.candidate,
            blueprint=record.blueprint,
            evidence=record.evidence,
            blind_receipt=record.blind_receipt,
            deterministic_report=deterministic_report_for(record),
            owner_user_id=record.owner_user_id,
            workspace_id=record.workspace_id,
            course_id=record.course_id,
            node_id=record.node_id,
            spec_version=record.spec_version,
        )
    except Exception as error:  # noqa: BLE001 - reported as a typed refusal
        print(
            json.dumps(
                {
                    "status": "REVIEW_FAILED",
                    "code": getattr(error, "code", type(error).__name__),
                }
            )
        )
        return 4
    print(
        json.dumps(
            {
                "status": "REVIEWED" if outcome else "NOT_ELIGIBLE",
                "accepted": outcome.accepted if outcome else False,
                "receipt_id": outcome.receipt_id if outcome else None,
                "case_outcomes": outcome.case_outcomes if outcome else {},
                "reasons": list(outcome.reasons) if outcome else [],
                "qualification_id": outcome.qualification_id if outcome else None,
                "human_card_id": outcome.human_card_id if outcome else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
