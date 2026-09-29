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
from app.db_target import DatabaseTargetError, target_from_environment  # noqa: E402
from app.learning.candidate_recovery import (  # noqa: E402
    CandidateRecoveryError,
    deterministic_report_for,
    list_recoverable,
    recover_candidate,
)
from app.learning.human_review_card import CARD_QUESTIONS, build_card_prompt  # noqa: E402


def _database(
    path: str,
    *,
    allowed_root: str,
    production_paths: tuple[str, ...],
    expected_schema: int | None,
) -> tuple[Database, dict[str, object]]:
    """Establish the target with the strict copy guard, then open it.

    The earlier rule -- refuse when the environment and the argument disagree --
    was necessary and not sufficient.  Two production paths agree with each other
    and are still production; a symlink, a hard link or a case alias names
    production while comparing unequal as text.  The guard therefore refuses a
    target that *is* production whatever the environment says, checks identity
    rather than spelling, keeps the target inside the authorised work root, and
    records the fingerprint of the copy and of the file it came from.
    """
    try:
        target = target_from_environment(
            purpose="QUALIFICATION_RUN",
            explicit_path=path,
            allowed_root=allowed_root,
            production_paths=tuple(production_paths),
            expected_schema=expected_schema,
        )
    except DatabaseTargetError as refusal:
        raise SystemExit(json.dumps(refusal.as_dict(), ensure_ascii=False)) from refusal
    settings = Settings()
    database = Database(
        settings.model_copy(
            update={
                "database_path": target.path,
                "upload_dir": target.path.parent / "uploads",
            }
        )
    )
    return database, target.as_receipt()


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
        "--allowed-root",
        required=True,
        help="the work root the target copy must live inside",
    )
    parser.add_argument(
        "--production-database",
        action="append",
        default=[],
        help="a production database path this target is checked against; repeatable",
    )
    parser.add_argument(
        "--expected-schema",
        type=int,
        default=None,
        help="the schema version the copy must be at, read read-only",
    )
    args = parser.parse_args()

    database, target_receipt = _database(
        args.database,
        allowed_root=args.allowed_root,
        production_paths=tuple(args.production_database),
        expected_schema=args.expected_schema,
    )

    if args.list:
        rows = list_recoverable(database, limit=args.limit)
        print(
            json.dumps(
                {
                    "database_target": target_receipt,
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
        settings.model_copy(update={"database_path": database.path})
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
                    "database_target": target_receipt,
                    "status": "REVIEW_FAILED",
                    "code": getattr(error, "code", type(error).__name__),
                }
            )
        )
        return 4
    print(
        json.dumps(
            {
                "database_target": target_receipt,
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
