"""CLI: derive the hybrid-strict-v1 qualification from a held-out evaluation set.

Run with the pinned production runtime so the protected DeepSeek credential and
the configured highest-quality model role are the ones actually measured:

    python scripts/run_hybrid_qualification.py \
        --database /path/rag.sqlite3 \
        --workspace <workspace-id> --node <node-id> \
        --per-type 4 --out /path/hybrid-qualification.json [--record]

``--record`` writes the resulting qualification row into ``hybrid_qualifications``
for the database given by ``--database``; without it the run is measurement only
and no deployment state changes.

Every provider call is metered in the artifact (input/output tokens, latency) and
there is no retry anywhere in this path: a failed call fails the row, it is not
silently re-asked.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.learning.blind_solve import run_blind_solve  # noqa: E402
from app.learning.deepseek_reviewer import (  # noqa: E402
    DeepSeekStrongReviewer,
    ReviewerInputs,
    StrongReviewError,
)
from app.learning.hybrid_evaluation_set import build_rows  # noqa: E402
from app.learning.hybrid_qualification import (  # noqa: E402
    evaluate_row,
    qualification_artifact,
    qualify,
    write_artifact,
)
from app.learning.hybrid_review import (  # noqa: E402
    CASE_AGREEMENT,
    CASE_AMBIGUITY,
    CASE_DISTRACTORS,
    CASE_RULE,
    case_set_for_blueprint,
)
from app.learning.hybrid_quality import review_domain, review_language  # noqa: E402
from app.learning.orchestrator import LearningOrchestrator  # noqa: E402
from app.learning.provider import LearningProvider  # noqa: E402
from app.learning.question_author import (  # noqa: E402
    QUESTION_AUTHOR_PROMPT_VERSION,
    RULE_VIOLATION_POLICY_VERSION,
    author_question,
)
from app.learning.question_blueprint import (  # noqa: E402
    QuestionBlueprint,
    resolve_objective,
)
from app.learning.question_evidence import (  # noqa: E402
    EvidencePackAccess,
    build_evidence_pack,
)

ITEM_KINDS = ("NUMERIC", "MCQ_SINGLE", "RULE_EXPLANATION")


def _blueprint(
    *,
    objective,
    evidence,
    course_id: str,
    node_id: str,
    spec_hash: str,
    kind: str,
    index: int,
) -> QuestionBlueprint:
    if kind == "MCQ_SINGLE":
        question_type = "MCQ_SINGLE"
        answer_form = "SINGLE_CHOICE"
        policy = "question-generation-policy-v1"
        misconceptions = ["off_by_one", "wrong_definition"]
        criteria = [objective.acceptance, "the selected option is the only correct one"]
    elif kind == "RULE_EXPLANATION":
        question_type = "EXPLANATION"
        answer_form = "FREE_TEXT"
        policy = RULE_VIOLATION_POLICY_VERSION
        misconceptions = []
        criteria = [objective.acceptance, "the cited rule is applied correctly"]
    else:
        question_type = "NUMERIC"
        answer_form = "NUMERIC_VALUE"
        policy = "question-generation-policy-v1"
        misconceptions = []
        criteria = [objective.acceptance, "the numeric result is exact"]
    return QuestionBlueprint(
        blueprint_id=f"qual-{kind.lower()}-{index}",
        course_id=course_id,
        node_id=node_id,
        spec_version=1,
        spec_content_hash=spec_hash,
        objective_id=objective.item_id,
        objective_text=objective.objective,
        source_scope=evidence.source_scope(),
        bloom_target="APPLY",
        target_difficulty=3,
        difficulty_features=["STEPS"],
        question_type=question_type,
        expected_answer_form=answer_form,
        marks=20,
        scoring_criteria=criteria,
        misconception_targets=misconceptions,
        question_family_id=f"qual-family-{kind.lower()}-{index}",
        prompt_versions={"question_author": QUESTION_AUTHOR_PROMPT_VERSION},
        generation_policy_version=policy,
    )


def _reviewer_inputs(candidate, blueprint, evidence, blind) -> ReviewerInputs:
    solution = candidate.private_solution.model_dump(mode="json")
    try:
        blind_payload = json.loads(blind.output)
    except (TypeError, ValueError):
        blind_payload = {"raw": blind.output}
    return ReviewerInputs(
        question_revision=candidate.question_revision,
        blueprint_hash=blueprint.identity(),
        evidence_pack_hash=evidence.identity(),
        course_id=blueprint.course_id,
        node_id=blueprint.node_id,
        spec_version=blueprint.spec_version,
        objective_id=blueprint.objective_id,
        language=review_language(blueprint, evidence),
        domain=review_domain(evidence),
        required_cases=case_set_for_blueprint(
            question_type=blueprint.question_type,
            rule_policy=(
                blueprint.generation_policy_version == RULE_VIOLATION_POLICY_VERSION
            ),
        ),
        question_text=candidate.public_question.question_text,
        question_type=blueprint.question_type,
        options=tuple(candidate.public_question.options),
        solution_a={
            "candidate_answer": solution.get("candidate_answer"),
            "correct_option_index": solution.get("correct_option_index"),
            "distractor_rationales": solution.get("distractor_rationales"),
            "rule_violation_analysis": solution.get("rule_violation_analysis"),
            "solution_steps": solution.get("solution_steps"),
            "source_refs": solution.get("source_refs"),
        },
        solution_b=blind_payload,
        rubric=tuple(blueprint.scoring_criteria),
        evidence=tuple(
            {"evidence_id": f.evidence_id, "content": f.content}
            for f in evidence.fragments
        ),
        deterministic={"AUTHOR_COMPLETED": "PASS", "BLIND_COMPLETED": "PASS"},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--private-course", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--per-type", type=int, default=4)
    parser.add_argument("--max-output-tokens", type=int, default=4000)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--qualification-id", default="hybrid-qual-live-v1")
    parser.add_argument("--min-positives", type=int, default=3)
    parser.add_argument("--min-negatives", type=int, default=3)
    args = parser.parse_args()

    settings = Settings()
    database = Database(settings)
    with database.connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE id=?", (args.workspace,)
        ).fetchone()
    if workspace is None:
        print(json.dumps({"status": "FAILED", "error": "workspace not found"}))
        return 2
    access = EvidencePackAccess(
        owner_user_id=str(workspace["owner_user_id"]),
        course_id=str(workspace["course_id"]),
        private_course_id=str(workspace["private_course_id"]),
    )
    with database.connect() as connection:
        objective = resolve_objective(connection, node_id=args.node)
    evidence = build_evidence_pack(database, objective=objective, access=access)

    provider = LearningProvider(settings)
    base: list[tuple[str, ReviewerInputs]] = []
    author_failures: list[dict[str, str]] = []
    for kind in ITEM_KINDS:
        for index in range(args.per_type):
            blueprint = _blueprint(
                objective=objective,
                evidence=evidence,
                course_id=str(workspace["course_id"]),
                node_id=args.node,
                spec_hash=objective.spec_content_hash,
                kind=kind,
                index=index,
            )
            try:
                candidate = author_question(provider, blueprint=blueprint, evidence=evidence)
                blind = run_blind_solve(provider, candidate=candidate, evidence=evidence)
            except Exception as error:  # noqa: BLE001 - each item is independent
                author_failures.append(
                    {"kind": kind, "index": str(index), "error": type(error).__name__}
                )
                continue
            base.append(
                (
                    f"{kind.lower()}-{index}",
                    _reviewer_inputs(candidate, blueprint, evidence, blind),
                )
            )

    rows = build_rows(base)
    reviewer = DeepSeekStrongReviewer(
        provider,
        model_alias=settings.v3_model,
        max_output_tokens=args.max_output_tokens,
    )
    outcomes = []
    row_failures: list[dict[str, str]] = []
    for position, row in enumerate(rows, start=1):
        try:
            first, second = reviewer.review(row.inputs)
        except StrongReviewError as error:
            row_failures.append(
                {"row_id": row.row_id, "code": error.code, "step": str(position)}
            )
            continue
        outcome = evaluate_row(row, first=first, second=second)
        outcomes.append(outcome)
        print(
            json.dumps(
                {
                    "progress": f"{position}/{len(rows)}",
                    "row_id": outcome.row_id,
                    "label": outcome.label,
                    "released": outcome.released,
                    "cases": outcome.case_outcomes,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    decision = qualify(
        outcomes,
        method_identity=reviewer.method_identity,
        observed_model_facts={
            "model_alias": settings.v3_model,
            "provider": "DEEPSEEK_API" if settings.v3_model == "deepseek-flash" else "OTHER",
            "protocol": "responses",
            "endpoint_host": (settings.v3_model_base_url or "").split("/")[2]
            if settings.v3_model_base_url and "//" in settings.v3_model_base_url
            else None,
            "api_surface_has_application_usd_cap": False,
        },
        min_positives_per_case=args.min_positives,
        min_negatives_per_case=args.min_negatives,
    )
    artifact = qualification_artifact(
        rows=rows,
        outcomes=outcomes,
        decision=decision,
        reviewer_identity={
            "model_alias": reviewer.model_alias,
            "provider_label": reviewer.provider_label,
            "protocol": reviewer.protocol,
            "evidence_prompt_version": reviewer.evidence_prompt_version,
            "adversarial_prompt_version": reviewer.adversarial_prompt_version,
            "schema_version": reviewer.schema_version,
            "method_identity": reviewer.method_identity,
        },
    )
    artifact["author_failures"] = author_failures
    artifact["row_failures"] = row_failures
    write_artifact(args.out, artifact)

    recorded = None
    if args.record and decision["status"] == "SCOPED_QUALITY_ACCEPTED":
        from app.learning.hybrid_quality import HybridQualificationStore

        store = HybridQualificationStore(database)
        record = store.record(
            qualification_id=args.qualification_id,
            policy_revision=decision["policy_revision"],
            method_identity=decision["method_identity"],
            status=decision["status"],
            reviewer_label=decision["reviewer_label"],
            languages=decision["languages"],
            domains=decision["domains"],
            cases=decision["cases"],
            roles=["evidence_audit", "adversarial_audit"],
            sample_counts={
                "positive_rows": artifact["decision"]["summary"]["positive_rows"],
                "negative_rows": artifact["decision"]["summary"]["negative_rows"],
                "independent_negative_families": artifact["decision"]["summary"][
                    "independent_negative_families"
                ],
            },
            metrics=artifact["decision"]["summary"],
            evidence_manifest_digest=artifact["dataset"]["digest"],
            observed_model_facts=decision["observed_model_facts"],
            expires_at=artifact["expires_at"],
        )
        recorded = record.id

    print(
        json.dumps(
            {
                "status": decision["status"],
                "cases": decision["cases"],
                "languages": decision["languages"],
                "domains": decision["domains"],
                "unmeasured_cases": decision["unmeasured_cases"],
                "summary": decision["summary"],
                "recorded_qualification_id": recorded,
                "artifact": args.out,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
