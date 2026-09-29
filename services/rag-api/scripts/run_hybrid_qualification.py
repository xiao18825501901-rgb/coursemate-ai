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
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.db_target import DatabaseTargetError, target_from_environment  # noqa: E402
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
from app.learning.hybrid_quality import review_domain, review_language  # noqa: E402
from app.learning.hybrid_review import (  # noqa: E402
    case_set_for_blueprint,
)
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
        answer_form = "WORKED_STEPS"
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
            {
                "evidence_id": f.evidence_id,
                "content": f.content,
                # The locator travels with the span so the server can resolve a
                # cited id back to a frozen, addressable place in the source.
                "locator": f.locator,
            }
            for f in evidence.fragments
        ),
        deterministic={"AUTHOR_COMPLETED": "PASS", "BLIND_COMPLETED": "PASS"},
    )


def diagnose_item(  # noqa: PLR0913 - one record per item, reported verbatim
    *, family: str, inputs: ReviewerInputs, candidate, blueprint=None
) -> dict[str, object]:
    """Describe one item's *shape* without recording any of its text.

    Whether a defect can be injected is a property of the item, not of the
    reviewers, so a run that cannot build negatives for a case is a corpus
    problem.  This record is what makes that visible: it reports the structural
    facts (lengths, counts, which mutations applied) and never the stem itself,
    because the stems are private course material.
    """
    from app.learning.hybrid_evaluation_set import _MUTATIONS

    text = inputs.question_text
    sentences = [part for part in re.split(r"(?<=[.!?;])\s+", text) if part.strip()]
    clauses = [part for part in re.split(r",\s*", text) if part.strip()]
    applied: dict[str, bool] = {}
    for case in inputs.required_cases:
        name, mutate = _MUTATIONS[case]
        applied[name] = mutate(inputs) is not None
    record = {
        "family": family,
        "question_type": inputs.question_type,
        "required_cases": list(inputs.required_cases),
        "stem_chars": len(text),
        "digit_groups": len(re.findall(r"\d+(?:[.,]\d+)?", text)),
        "sentences": len(sentences),
        "clauses": len(clauses),
        "has_condition_marker": any(
            marker in text.lower()
            for marker in (
                " given that ",
                " assuming ",
                " such that ",
                " in the case that ",
                " where ",
            )
        ),
        "evidence_spans": len(inputs.evidence),
        "evidence_chars": sum(len(fragment["content"]) for fragment in inputs.evidence),
        "options": len(inputs.options),
        "mutations_applied": applied,
        "author_answer_kind": type(inputs.solution_a.get("candidate_answer")).__name__,
    }
    record.update(_contract_diagnosis(candidate, blueprint, inputs))
    return record


def _certificate_for(candidate, blueprint, evidence, inputs: ReviewerInputs):
    """The completeness certificate for an authored item, or None.

    None means "no positive evidence that this item is answerable", which the
    ambiguity case treats as an abstention -- never as an approval.
    """
    from app.learning.task_spec import certify_completeness, render_public_projection

    if not getattr(candidate, "task_contract", None):
        return None
    spec = candidate.task_spec(blueprint)
    if spec is None:
        return None
    try:
        projection = render_public_projection(spec)
    except Exception:  # noqa: BLE001 - an unrenderable contract is no evidence
        return None
    return certify_completeness(
        spec,
        projection=projection,
        available_span_ids=evidence.evidence_ids,
        reviewable_language=inputs.language,
    )


def _contract_diagnosis(candidate, blueprint, inputs: ReviewerInputs) -> dict[str, object]:
    """Whether the item carries a usable student-visible task contract.

    This is the fact a qualification run is most likely to be blocked by now: an
    item without a contract, or whose contract names a profile the server has not
    registered, has no positive completeness evidence and therefore cannot be
    approved however well the reviewers behave.  Reporting it here means a
    diagnosis-only run answers that question without paying for a single review
    call.
    """
    from app.learning.task_spec import certify_completeness, render_public_projection

    if not getattr(candidate, "task_contract", None):
        return {
            "task_contract": False,
            "profile": None,
            "certificate_status": "NO_CONTRACT",
            "certificate_failing_checks": [],
        }
    draft = candidate.task_contract
    base = {
        "task_contract": True,
        "profile": draft.profile_id,
        "profile_version": draft.profile_version,
        "declared_conventions": sorted(item.key for item in draft.conventions),
        "fact_roles": sorted({item.role for item in draft.facts}),
        "answer_equivalence": draft.answer_equivalence,
        "task_boundary_chars": len(draft.task_boundary),
    }
    if blueprint is None:
        base["certificate_status"] = "NO_BLUEPRINT"
        base["certificate_failing_checks"] = []
        return base
    spec = candidate.task_spec(blueprint)
    projection = render_public_projection(spec)
    certificate = certify_completeness(
        spec,
        projection=projection,
        available_span_ids=[fragment["evidence_id"] for fragment in inputs.evidence],
        reviewable_language=inputs.language,
    )
    base.update(
        {
            "certificate_status": certificate.status,
            "certificate_failing_checks": [
                check.name for check in certificate.checks if check.status == "FAIL"
            ],
            "projection_chars": len(projection.text),
            "projection_digest": projection.text_digest,
            "certifies": certificate.certifies,
        }
    )
    return base


def _mutation_summary(diagnostics: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for record in diagnostics:
        applied = record.get("mutations_applied") or {}
        for name, ok in applied.items():  # type: ignore[union-attr]
            bucket = summary.setdefault(name, {"applicable": 0, "skipped": 0})
            bucket["applicable" if ok else "skipped"] += 1
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--private-course", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--per-type", type=int, default=8)
    # Authoring-only: report the item population's shape and which defect
    # mutations can actually be injected, without making a single review call.
    parser.add_argument("--diagnose-only", action="store_true")
    parser.add_argument("--max-output-tokens", type=int, default=4000)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--qualification-id", default="hybrid-qual-live-v1")
    parser.add_argument("--min-positives", type=int, default=3)
    # The floors are high on purpose.  A run with 18 negatives recorded a passing
    # qualification and the same procedure with 40 negatives recorded three false
    # accepts, so a thin clean sample must not be able to qualify a method.
    parser.add_argument("--min-negatives", type=int, default=8)
    parser.add_argument("--min-independent-negatives", type=int, default=16)
    # A procedure can reach zero false accepts by refusing almost everything, and
    # an everything-blocked baseline is not a quality standard.  This floor is a
    # coverage requirement, not an accuracy claim.
    parser.add_argument("--min-release-recall", type=float, default=0.5)
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
    parser.add_argument(
        "--kinds",
        default="",
        help=(
            "comma-separated subset of item kinds to build; empty means all of "
            "ITEM_KINDS.  A bounded probe costs one author and one blind call per "
            "item, so restricting the kinds is how a diagnostic stays cheap."
        ),
    )
    args = parser.parse_args()
    selected_kinds = tuple(
        part.strip().upper() for part in args.kinds.split(",") if part.strip()
    ) or ITEM_KINDS
    unknown_kinds = [kind for kind in selected_kinds if kind not in ITEM_KINDS]
    if unknown_kinds:
        print(json.dumps({"status": "FAILED", "error": f"unknown kinds {unknown_kinds}"}))
        return 7

    settings = Settings()
    # The database and upload root come from the explicit arguments, and the
    # target must survive the strict copy guard first: a run measures against a
    # restored copy and never points the process at the live file, whether or not
    # the environment agrees with the argument.
    try:
        target = target_from_environment(
            purpose="QUALIFICATION_RUN",
            explicit_path=args.database,
            allowed_root=args.allowed_root,
            production_paths=tuple(args.production_database),
            expected_schema=args.expected_schema,
        )
    except DatabaseTargetError as refusal:
        print(json.dumps(refusal.as_dict(), ensure_ascii=False))
        return 6
    database = Database(
        settings.model_copy(
            update={
                "database_path": target.path,
                "upload_dir": target.path.parent / "uploads",
            }
        )
    )
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

    provider = LearningProvider(
        settings.model_copy(update={"database_path": target.path})
    )
    base: list[tuple[str, ReviewerInputs]] = []
    # The server-issued completeness certificate per family.  Only a control row
    # receives one: an injected mutation changes the item, so a certificate that
    # described the untampered item no longer describes the mutated one.
    certificates: dict[str, object] = {}
    diagnostics: list[dict[str, object]] = []
    author_failures: list[dict[str, object]] = []
    # Complete provider responses whose parsing failed, kept so they can be
    # re-parsed offline.  Never printed; written only when the caller asked.
    raw_responses: list[dict[str, object]] = []
    for kind in selected_kinds:
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
                # The code and the provider facts are recorded, not just the
                # exception class: the first live run reported three bare
                # "AuthorGenerationError" lines and could not be attributed at all.
                failure: dict[str, object] = {
                    "kind": kind,
                    "index": str(index),
                    "error": type(error).__name__,
                    "code": getattr(error, "code", None),
                    # The refusal message names the rule that refused the item.
                    # These messages are written to be free of question text, so
                    # recording them is what makes a run attributable.
                    "message": str(error)[:300],
                }
                provider_run = getattr(error, "provider_run", None)
                if isinstance(provider_run, dict):
                    failure.update(
                        {
                            "provider_status": provider_run.get("status"),
                            "error_class": provider_run.get("error_class"),
                            "failure_layer": provider_run.get("failure_layer"),
                            "provider_response_id": provider_run.get("provider_response_id"),
                            # Which fields the response failed on, without the
                            # values: that is what makes a schema rejection
                            # attributable instead of a bare error class.
                            "schema_error_summary": provider_run.get("schema_error_summary"),
                        }
                    )
                    captured = provider_run.get("response_text")
                    if isinstance(captured, str) and captured:
                        # The complete response is persisted before anything is
                        # concluded about it, exactly as the plan requires, so a
                        # rejection can be re-parsed locally instead of being
                        # bought again.  It is private course material: the file
                        # is written beside the artifact for the caller to protect.
                        failure["raw_response_chars"] = len(captured)
                        raw_responses.append(
                            {
                                "kind": kind,
                                "index": str(index),
                                "provider_response_id": provider_run.get("provider_response_id"),
                                "response_text": captured,
                            }
                        )
                author_failures.append(failure)
                continue
            inputs = _reviewer_inputs(candidate, blueprint, evidence, blind)
            if args.diagnose_only:
                diagnostics.append(
                    diagnose_item(
                        family=f"{kind.lower()}-{index}",
                        inputs=inputs,
                        candidate=candidate,
                        blueprint=blueprint,
                    )
                )
                continue
            family = f"{kind.lower()}-{index}"
            base.append((family, inputs))
            certificate = _certificate_for(candidate, blueprint, evidence, inputs)
            if certificate is not None:
                certificates[family] = certificate
            diagnostics.append(
                diagnose_item(
                    family=f"{kind.lower()}-{index}",
                    inputs=inputs,
                    candidate=candidate,
                    blueprint=blueprint,
                )
            )

    if raw_responses:
        raw_path = Path(f"{args.out}.raw-responses.json")
        raw_path.write_text(
            json.dumps(raw_responses, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.chmod(raw_path, 0o600)

    if args.diagnose_only:
        diagnosis = {
            "schema": "coursejesus.hybrid-item-population-diagnosis.v1",
            "status": "DIAGNOSIS_ONLY",
            "node_id": args.node,
            "per_type": args.per_type,
            "items": len(diagnostics),
            "author_failures": author_failures,
            "mutation_applicability": _mutation_summary(diagnostics),
            "diagnostics": diagnostics,
        }
        write_artifact(args.out, diagnosis)
        print(
            json.dumps(
                {
                    "status": "DIAGNOSIS_ONLY",
                    "items": len(diagnostics),
                    "author_failures": author_failures,
                    "mutation_applicability": diagnosis["mutation_applicability"],
                    "artifact": args.out,
                    "diagnostics": diagnostics,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    rows = build_rows(base, certificates=certificates)
    reviewer = DeepSeekStrongReviewer(
        provider,
        model_alias=settings.v3_model,
        max_output_tokens=args.max_output_tokens,
    )
    outcomes = []
    row_failures: list[dict[str, object]] = []
    for position, row in enumerate(rows, start=1):
        try:
            first, second = reviewer.review(row.inputs)
            specification = reviewer.last_specification
        except StrongReviewError as error:
            # The layer and the field list are recorded, not just the code: a bare
            # HYBRID_SPECIFICATION_PROVIDER_FAILED says nothing about whether this
            # was an outage, our schema, or a complete response that did not parse.
            failure: dict[str, object] = {
                "row_id": row.row_id,
                "code": error.code,
                "step": str(position),
            }
            provider_run = getattr(error, "provider_run", None)
            if isinstance(provider_run, dict):
                failure.update(
                    {
                        "role": provider_run.get("role"),
                        "provider_status": provider_run.get("status"),
                        "error_class": provider_run.get("error_class"),
                        "failure_layer": provider_run.get("failure_layer"),
                        "http_status": provider_run.get("http_status"),
                        "provider_response_id": provider_run.get("provider_response_id"),
                        "schema_error_summary": provider_run.get("schema_error_summary"),
                        "response_chars": (
                            len(provider_run["response_text"])
                            if isinstance(provider_run.get("response_text"), str)
                            else None
                        ),
                    }
                )
            row_failures.append(failure)
            continue
        outcome = evaluate_row(
            row, first=first, second=second, specification=specification
        )
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
        min_independent_negatives=args.min_independent_negatives,
        min_release_recall=args.min_release_recall,
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
            "specification_prompt_version": reviewer.specification_prompt_version,
            "schema_version": reviewer.schema_version,
            "specification_schema_version": reviewer.specification_schema_version,
            "method_identity": reviewer.method_identity,
        },
    )
    artifact["author_failures"] = author_failures
    artifact["row_failures"] = row_failures
    # Which mutations could actually be applied.  A defect that cannot be
    # injected produces no row, and leaving that gap visible is the difference
    # between "measured" and "assumed".
    per_case_base: dict[str, int] = {}
    for _, inputs in base:
        for case in inputs.required_cases:
            per_case_base[case] = per_case_base.get(case, 0) + 1
    per_case_negative = {case: 0 for case in per_case_base}
    for row in rows:
        if row.label == "INJECTED_DEFECT" and row.target_case:
            per_case_negative[row.target_case] = (
                per_case_negative.get(row.target_case, 0) + 1
            )
    artifact["mutation_coverage"] = {
        case: {
            "base_items": per_case_base[case],
            "negatives_injected": per_case_negative.get(case, 0),
            "skipped_not_applicable": per_case_base[case]
            - per_case_negative.get(case, 0),
        }
        for case in sorted(per_case_base)
    }
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
