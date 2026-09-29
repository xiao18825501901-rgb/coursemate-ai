"""Derive a scoped hybrid-strict-v1 qualification from a labelled held-out set.

This is the module that decides whether the two strong reviewers may publish at
all, so it is deliberately conservative and fully reported:

* every row's label provenance is recorded and the provenance vocabulary is
  closed: a row is either a ``POSITIVE_CONTROL`` (a server-authored item whose
  deterministic gates all passed and into which no defect was injected) or an
  ``INJECTED_DEFECT`` (a recorded byte-level mutation that must break a named
  case).  There is no "model said so" label and no claim of human gold;
* a case is only included in the qualification when it has *both* positives and
  negatives, so a case can never be qualified on one-sided evidence;
* the metric that matters for release is the **release** decision -- an item is
  released only when both reviewers PASS every required case -- so the reported
  false-accept is measured on that conjunction, not on a single verdict;
* a zero false-accept count is reported with its exact one-sided 95% binomial
  upper bound and the independent sample count, never as "zero risk";
* the qualification carries the exact method identity (model alias, provider,
  both prompt revisions, schema revision, policy revision) and the observed
  served model facts, because a hosted alias cannot be pinned.

The label is ``SCOPED_QUALITY_ACCEPTED``.  It is explicitly *not*
``PROVEN_IDENTICAL_TO_JEV``: no paired same-sample comparison against a healthy
historical reviewer exists, so non-inferiority is not established.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from app.learning.deepseek_reviewer import StrongReviewOutcome
from app.learning.hybrid_evaluation_set import (
    NEGATIVE_LABEL,
    POSITIVE_LABEL,
    EvaluationRow,
    dataset_digest,
)
from app.learning.hybrid_quality import QUALIFICATION_TTL_DAYS
from app.learning.hybrid_review import POLICY_REVISION, combine_case_verdicts


def zero_false_accept_upper_bound(n_independent_negatives: int, alpha: float = 0.05) -> float:
    """Exact one-sided binomial upper bound for a zero-false-accept observation.

    Applies only to independent trials from a fixed procedure with
    representative sampling.  Related variants of one item (a translated copy, a
    number swap, two mutations of the same stem) are **not** independent trials,
    so the caller must pass the independent family count, not the row count.
    """
    if n_independent_negatives < 1:
        raise ValueError("a positive independent-negative count is required")
    return -math.expm1(math.log(alpha) / n_independent_negatives)


@dataclass
class CaseTally:
    """Per-case counts for one (case, language, domain) scope."""

    positives: int = 0
    negatives: int = 0
    true_accept: int = 0        # positive rows released
    false_reject: int = 0       # positive rows refused
    positive_abstain: int = 0
    false_accept: int = 0       # negative rows released
    true_reject: int = 0        # negative rows refused
    negative_abstain: int = 0

    def as_dict(self) -> dict[str, Any]:
        denominator = self.positives + self.negatives
        classified = denominator - self.positive_abstain - self.negative_abstain
        return {
            "positives": self.positives,
            "negatives": self.negatives,
            "true_accept": self.true_accept,
            "false_reject": self.false_reject,
            "positive_abstain": self.positive_abstain,
            "false_accept": self.false_accept,
            "true_reject": self.true_reject,
            "negative_abstain": self.negative_abstain,
            "denominator": denominator,
            "classified": classified,
            "coverage": (classified / denominator) if denominator else None,
            "release_precision": (
                self.true_accept / (self.true_accept + self.false_accept)
                if (self.true_accept + self.false_accept)
                else None
            ),
            "release_recall": (
                self.true_accept / self.positives if self.positives else None
            ),
            "false_accept_rate": (
                self.false_accept / self.negatives if self.negatives else None
            ),
        }


@dataclass
class RowOutcome:
    """The recorded decision for one evaluation row."""

    row_id: str
    family_id: str
    label: str
    language: str
    domain: str
    question_type: str
    released: bool
    case_outcomes: dict[str, str]
    target_case: str | None
    defect: str | None
    provenance: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "family_id": self.family_id,
            "label": self.label,
            "language": self.language,
            "domain": self.domain,
            "question_type": self.question_type,
            "released": self.released,
            "case_outcomes": dict(self.case_outcomes),
            "target_case": self.target_case,
            "defect": self.defect,
            "provenance": self.provenance,
            "reasons": list(self.reasons),
        }


def evaluate_row(
    row: EvaluationRow,
    *,
    first: StrongReviewOutcome,
    second: StrongReviewOutcome,
) -> RowOutcome:
    """Apply the publication rule to one row and record the outcome."""
    by_role = {first.role: first.case_verdicts(), second.role: second.case_verdicts()}
    combined, reasons = combine_case_verdicts(
        required_cases=row.inputs.required_cases, by_role=by_role
    )
    for outcome in (first, second):
        if not outcome.verification.complete:
            reasons.append(f"HYBRID_REVIEW_REFERENCES_UNVERIFIED:{outcome.role}")
        for reason in outcome.substantiation_reasons():
            reasons.append(f"{reason}:{outcome.role}")
    released = not reasons and all(v == "PASS" for v in combined.values())
    return RowOutcome(
        row_id=row.row_id,
        family_id=row.family_id,
        label=row.label,
        language=row.inputs.language,
        domain=row.inputs.domain,
        question_type=row.inputs.question_type,
        released=released,
        case_outcomes=combined,
        target_case=row.target_case,
        defect=row.defect,
        provenance=row.provenance,
        reasons=list(dict.fromkeys(reasons)),
    )


def summarise(outcomes: list[RowOutcome]) -> dict[str, Any]:
    """Aggregate release metrics overall and per (case, language, domain) scope.

    Two families of numbers are reported and they answer different questions:

    ``release_*``
        Row-level.  A row is released only when **both** reviewers pass **every**
        required case, which is the actual publication rule.  This is the number
        that a false-accept / false-reject claim must be based on.
    ``scopes``
        Per-case, attributed correctly.  A negative row only contributes to the
        tally of the case its injected defect targets: when a row's defect is an
        under-specified stem, a `PASS` on `answer_agreement` is not a false
        accept, it is the correct answer to a case that was not broken.  Counting
        it as one would inflate every case's error rate with other cases' rows.
    """
    overall = CaseTally()
    scopes: dict[tuple[str, str, str], CaseTally] = {}
    independent_negative_families: set[str] = set()
    release_false_accept = 0
    release_true_reject = 0
    release_true_accept = 0
    release_false_reject = 0
    release_abstain = 0
    for outcome in outcomes:
        is_negative = outcome.label == NEGATIVE_LABEL
        if is_negative:
            independent_negative_families.add(outcome.family_id)
        # Row-level release decision.
        if outcome.released:
            if is_negative:
                release_false_accept += 1
            else:
                release_true_accept += 1
        elif any(verdict == "UNCERTAIN" for verdict in outcome.case_outcomes.values()):
            release_abstain += 1
        elif is_negative:
            release_true_reject += 1
        else:
            release_false_reject += 1
        for case, verdict in outcome.case_outcomes.items():
            # A negative row is evidence about exactly one case: the one its
            # defect targets.
            if is_negative and outcome.target_case != case:
                continue
            key = (case, outcome.language, outcome.domain)
            tally = scopes.setdefault(key, CaseTally())
            for target in (overall, tally):
                if is_negative:
                    target.negatives += 1
                else:
                    target.positives += 1
            case_released = verdict == "PASS"
            if is_negative:
                if case_released:
                    overall.false_accept += 1
                    tally.false_accept += 1
                elif verdict == "UNCERTAIN":
                    overall.negative_abstain += 1
                    tally.negative_abstain += 1
                else:
                    overall.true_reject += 1
                    tally.true_reject += 1
            else:
                if case_released:
                    overall.true_accept += 1
                    tally.true_accept += 1
                elif verdict == "UNCERTAIN":
                    overall.positive_abstain += 1
                    tally.positive_abstain += 1
                else:
                    overall.false_reject += 1
                    tally.false_reject += 1
    independent = len(independent_negative_families)
    negative_rows = sum(1 for outcome in outcomes if outcome.label == NEGATIVE_LABEL)
    positive_rows = sum(1 for outcome in outcomes if outcome.label == POSITIVE_LABEL)
    return {
        "overall": overall.as_dict(),
        "release": {
            "positive_rows": positive_rows,
            "negative_rows": negative_rows,
            "true_accept": release_true_accept,
            "false_reject": release_false_reject,
            "false_accept": release_false_accept,
            "true_reject": release_true_reject,
            "abstain": release_abstain,
            "release_precision": (
                release_true_accept / (release_true_accept + release_false_accept)
                if (release_true_accept + release_false_accept)
                else None
            ),
            "release_recall": (
                release_true_accept / positive_rows if positive_rows else None
            ),
            "false_release_rate": (
                release_false_accept / negative_rows if negative_rows else None
            ),
            "coverage": (
                (positive_rows + negative_rows - release_abstain)
                / (positive_rows + negative_rows)
                if (positive_rows + negative_rows)
                else None
            ),
        },
        "scopes": {
            f"{case}|{language}|{domain}": tally.as_dict()
            for (case, language, domain), tally in sorted(scopes.items())
        },
        "independent_negative_families": independent,
        "negative_rows": negative_rows,
        "positive_rows": positive_rows,
        "zero_false_accept_upper_bound_95": (
            zero_false_accept_upper_bound(independent)
            if independent and release_false_accept == 0
            else None
        ),
        "zero_false_accept_bound_applicable": release_false_accept == 0,
        "zero_false_accept_bound_note": (
            "The one-sided bound is only defined for a zero-false-accept "
            "observation; it is reported as null when any item was wrongly "
            "released, because a bound on an event that did occur is not a "
            "risk statement."
        ),
    }


def qualify(
    outcomes: list[RowOutcome],
    *,
    method_identity: str,
    observed_model_facts: dict[str, Any],
    min_positives_per_case: int,
    min_negatives_per_case: int,
    min_independent_negatives: int,
    min_release_recall: float,
) -> dict[str, Any]:
    """Turn measurements into a scoped qualification decision.

    A case is only admitted to the qualification when it has at least
    ``min_positives_per_case`` positives and ``min_negatives_per_case``
    negatives, when *no* item anywhere was wrongly released, and when the
    procedure actually releases a usable share of the sound items.

    Two of those conditions exist because this round measured what happens
    without them:

    * **the negative floor.**  A run with 30 rows and 18 negatives recorded a
      passing qualification; the same procedure on 67 rows and 40 negatives
      recorded three false accepts.  A clean small sample is not evidence of a
      clean procedure, so the floors are deliberately high and the
      independent-negative count is checked globally, not only per case.
    * **the recall floor.**  A procedure can reach zero false accepts by
      refusing almost everything.  The first enumeration-based run did exactly
      that -- 0 false accepts out of 41 negatives while rejecting 13 of 24 sound
      controls -- and "everything is blocked, therefore nothing bad was
      released" is explicitly not an acceptable quality baseline.  A method has
      to be both safe and usable.

    ``min_release_recall`` is a *coverage* floor (does the procedure publish
    usable work at all), not an invented accuracy score; see the versioned
    profile note in the decision record.  Cases below any floor are reported as
    unmeasured and are therefore absent from the qualification's case set, which
    leaves them fail-closed at publication.
    """
    summary = summarise(outcomes)
    scopes = summary["scopes"]
    admitted_cases: set[str] = set()
    admitted_languages: set[str] = set()
    admitted_domains: set[str] = set()
    per_case_evidence: dict[str, dict[str, Any]] = {}
    for key, tally in scopes.items():
        case, language, domain = key.split("|", 2)
        entry = per_case_evidence.setdefault(
            case, {"positives": 0, "negatives": 0, "false_accept": 0, "scopes": []}
        )
        entry["positives"] += tally["positives"]
        entry["negatives"] += tally["negatives"]
        entry["false_accept"] += tally["false_accept"]
        entry["scopes"].append({"language": language, "domain": domain, **tally})
    independent_negatives = summary["independent_negative_families"]
    sample_sufficient = independent_negatives >= min_independent_negatives
    recall = summary["release"]["release_recall"]
    coverage_sufficient = recall is not None and recall >= min_release_recall
    for case, entry in per_case_evidence.items():
        if (
            entry["positives"] >= min_positives_per_case
            and entry["negatives"] >= min_negatives_per_case
            and entry["false_accept"] == 0
            and summary["release"]["false_accept"] == 0
            and sample_sufficient
            and coverage_sufficient
        ):
            admitted_cases.add(case)
            for scope in entry["scopes"]:
                admitted_languages.add(scope["language"])
                admitted_domains.add(scope["domain"])
    return {
        "policy_revision": POLICY_REVISION,
        "method_identity": method_identity,
        "status": (
            "SCOPED_QUALITY_ACCEPTED" if admitted_cases else "DRAFT"
        ),
        "reviewer_label": "SCOPED_QUALITY_ACCEPTED",
        "cases": sorted(admitted_cases),
        "languages": sorted(admitted_languages),
        "domains": sorted(admitted_domains),
        "unmeasured_cases": sorted(set(per_case_evidence) - admitted_cases),
        "sample_sufficient": sample_sufficient,
        "min_independent_negatives": min_independent_negatives,
        "coverage_sufficient": coverage_sufficient,
        "min_release_recall": min_release_recall,
        "release_recall": recall,
        "per_case_evidence": per_case_evidence,
        "summary": summary,
        "observed_model_facts": observed_model_facts,
        "notes": [
            "POSITIVE_CONTROL rows are server-authored items with all deterministic "
            "hard gates PASS and no injected defect; they are controls, not human gold.",
            "INJECTED_DEFECT rows carry a recorded byte-level mutation that must break "
            "a named case, so their label is decidable by construction.",
            "A mutation that cannot actually be applied produces no row; the gap is "
            "recorded in mutation_coverage rather than filled with a fake defect.",
            "The release decision is the conjunction of both reviewers PASSing every "
            "required case; false-accept is measured on that conjunction.",
            "A hosted model alias cannot be pinned; the served revision is recorded as "
            "an observation and must be re-sampled periodically.",
            "A clean small sample is not evidence of a clean procedure: the same "
            "runner recorded a pass at 18 negatives and three false accepts at 40. "
            "The floors therefore apply to the independent-negative count as well.",
            "Zero false accepts is not sufficient on its own: a procedure that "
            "refuses most sound items also releases nothing bad, and an "
            "everything-blocked baseline is not an acceptable quality standard. "
            "The release-recall floor is what distinguishes safe from merely closed.",
            "No paired same-sample comparison against a healthy historical reviewer "
            "exists, so quality non-inferiority is NOT established by this record.",
        ],
    }


def qualification_artifact(
    *,
    rows: list[EvaluationRow],
    outcomes: list[RowOutcome],
    decision: dict[str, Any],
    reviewer_identity: dict[str, Any],
    created_at: datetime | None = None,
    ttl_days: int = QUALIFICATION_TTL_DAYS,
) -> dict[str, Any]:
    created = created_at or datetime.now(UTC)
    return {
        "schema": "coursejesus.hybrid-qualification-run.v1",
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "expires_at": (created + timedelta(days=ttl_days)).isoformat().replace("+00:00", "Z"),
        "policy_revision": POLICY_REVISION,
        "dataset": {
            "digest": dataset_digest(rows),
            "rows": len(rows),
            "manifest": [row.manifest_entry() for row in rows],
        },
        "reviewer": reviewer_identity,
        "decision": decision,
        "row_outcomes": [outcome.as_dict() for outcome in outcomes],
    }


def write_artifact(path: str, artifact: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(artifact, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
