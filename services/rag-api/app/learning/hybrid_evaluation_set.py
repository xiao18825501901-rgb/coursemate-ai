"""Build the held-out evaluation set for the hybrid-strict-v1 qualification.

The set is deliberately *not* model self-assessment and *not* claimed human
gold.  Every row records exactly how its label was obtained:

``POSITIVE_CONTROL``
    A server-authored item whose deterministic hard gates already passed.  The
    label means "no defect was injected and every deterministic check is green",
    which is a *control*, not proof of pedagogical correctness.  It is what
    false-reject is measured against.

``INJECTED_DEFECT``
    A byte-level mutation of a positive control with one specific, recorded
    defect.  The mutation and the case it must break are written down before the
    reviewers run, so the negative label is decidable by construction rather
    than by opinion.

Mutations are applied to the *reviewer input* only.  They change the frozen
question revision, because the input genuinely changed -- a review of a
different item is a different review.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any, Final

from app.learning.deepseek_reviewer import ReviewerInputs
from app.learning.hybrid_review import (
    CASE_AGREEMENT,
    CASE_AMBIGUITY,
    CASE_DISTRACTORS,
    CASE_RULE,
)

POSITIVE_LABEL: Final = "POSITIVE_CONTROL"
NEGATIVE_LABEL: Final = "INJECTED_DEFECT"


@dataclass(frozen=True)
class EvaluationRow:
    """One reviewer-input row with a decidable label and a recorded provenance."""

    row_id: str
    inputs: ReviewerInputs
    label: str
    provenance: str
    target_case: str | None  # the case the defect must break, or None for a control
    defect: str | None
    family_id: str

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "family_id": self.family_id,
            "label": self.label,
            "provenance": self.provenance,
            "target_case": self.target_case,
            "defect": self.defect,
            "language": self.inputs.language,
            "domain": self.inputs.domain,
            "required_cases": list(self.inputs.required_cases),
            "question_revision": self.inputs.question_revision,
            "question_type": self.inputs.question_type,
        }


def _revision(seed: str, mutation: str) -> str:
    return hashlib.sha256(f"{seed}\x00{mutation}".encode()).hexdigest()


_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")


def _strip_condition(text: str) -> str:
    """Remove a stated given, producing a genuinely under-specified item.

    The removal has to be unambiguous.  Deleting an arbitrary trailing phrase
    does **not** make an item under-specified -- the sentence that goes may have
    been scene-setting, and a reviewer that still answers `CLEAR` would then be
    right while the row is recorded as a missed defect.  So this mutation only
    fires when it actually takes away something the answer depends on:

    * a clause introduced by an explicit condition marker, or
    * a clause carrying a numeric given.

    When neither is present the item is left alone and
    :func:`missing_condition` reports the mutation as inapplicable, so no
    ambiguity negative is manufactured for it.
    """
    lowered = text.lower()
    for marker in (
        " given that ",
        " assuming ",
        " such that ",
        " in the case that ",
        " where ",
    ):
        index = lowered.find(marker)
        if index > 0:
            stripped = text[:index].rstrip(" ,;:") + "."
            if stripped != text:
                return stripped

    # Drop whole sentences that state numeric givens.
    sentences = [part.strip() for part in re.split(r"(?<=[.!?;])\s+", text) if part.strip()]
    kept = [part for part in sentences if not _NUMBER.search(part)]
    if kept and len(kept) < len(sentences):
        return " ".join(kept)

    # Single sentence: drop the comma-separated clauses carrying the givens.
    clauses = [part.strip() for part in re.split(r",\s*", text) if part.strip()]
    kept_clauses = [part for part in clauses if not _NUMBER.search(part)]
    if kept_clauses and len(kept_clauses) < len(clauses):
        return ", ".join(kept_clauses)

    # The givens are inline in a clause that cannot be dropped -- e.g. "Compute
    # 2 + 3 as base-ten integers."  Replacing them with an explicitly
    # unspecified quantity still removes the datum the answer depends on, which
    # is what makes the item under-specified.
    if _NUMBER.search(text):
        replaced = _NUMBER.sub("an unspecified value", text)
        if replaced != text:
            return replaced

    # Nothing the answer depends on can be removed by deletion or substitution.
    return text


def missing_condition(row_inputs: ReviewerInputs) -> ReviewerInputs | None:
    """Ambiguity must fail: a datum needed for a unique answer is now absent.

    Returns ``None`` when no explicit condition can be removed, because a
    mutation that does not actually change the item must never be recorded as a
    defect: that would silently count a positive control as a negative.
    """
    stripped = _strip_condition(row_inputs.question_text)
    if stripped == row_inputs.question_text:
        return None
    return replace(
        row_inputs,
        question_revision=_revision(row_inputs.question_revision, "missing_condition"),
        question_text=stripped,
    )


def _contradiction(value: Any) -> Any:
    """Derive a concrete, materially different result from a correct one."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return f"a different result from {value}"
    if isinstance(value, dict):
        return {key: _contradiction(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_contradiction(item) for item in value]
    return "a materially different result"


def disagreeing_solution(row_inputs: ReviewerInputs) -> ReviewerInputs | None:
    """Answer agreement must fail: the two solutions reach different results.

    The mutation has to make the *second solution itself* reach a different
    concrete result.  Replacing only a summary sentence while its steps still
    show the original answer leaves a reviewer genuinely able to report
    agreement, so the steps are rewritten too and no agreeing content remains.
    """
    solution_b = dict(row_inputs.solution_b)
    author_answer = row_inputs.solution_a.get("candidate_answer")
    if author_answer is None and not solution_b:
        return None
    contradicted = _contradiction(author_answer)
    contradiction_text = json.dumps(contradicted, ensure_ascii=False, sort_keys=True)

    changed = False
    if "conclusion" in solution_b or "steps" in solution_b:
        solution_b["conclusion"] = (
            "Working independently from the same stated material, this solution "
            f"obtains {contradiction_text}. That is a different result from the "
            "other supplied solution, so the two do not reach the same answer."
        )
        steps = solution_b.get("steps")
        if isinstance(steps, list) and steps:
            rewritten = []
            for index, step in enumerate(steps):
                if isinstance(step, dict):
                    mutated_step = dict(step)
                    if index == len(steps) - 1:
                        mutated_step["result"] = contradiction_text
                    rewritten.append(mutated_step)
                else:  # pragma: no cover - the blind contract uses objects
                    rewritten.append(step)
            solution_b["steps"] = rewritten
        solution_b.pop("answer", None)
        changed = True
    elif solution_b.get("raw"):
        solution_b["raw"] = contradiction_text
        changed = True
    if not changed:
        return None
    return replace(
        row_inputs,
        question_revision=_revision(row_inputs.question_revision, "disagree"),
        solution_b=solution_b,
    )


def duplicate_correct_option(row_inputs: ReviewerInputs) -> ReviewerInputs | None:
    """Distractor quality must fail: a distractor paraphrases the correct option."""
    options = list(row_inputs.options)
    correct = row_inputs.solution_a.get("correct_option_index")
    if not isinstance(correct, int) or not 0 <= correct < len(options):
        return None
    replacement = f"{options[correct]} (equivalently, the same statement restated)"
    changed = False
    for index in range(len(options)):
        if index != correct:
            options[index] = replacement
            changed = True
            break
    if not changed:
        return None
    return replace(
        row_inputs,
        question_revision=_revision(row_inputs.question_revision, "duplicate_option"),
        options=tuple(options),
    )


def unsupported_rule(row_inputs: ReviewerInputs) -> ReviewerInputs | None:
    """Rule quality must fail: the cited rule loses the prerequisite it needs."""
    if not row_inputs.evidence:
        return None
    solution_a = dict(row_inputs.solution_a)
    analysis = solution_a.get("rule_violation_analysis")
    if isinstance(analysis, dict):
        mutated = dict(analysis)
    else:
        mutated = {}
    mutated["rule_quote"] = (
        "A statement is a violation whenever it is different from the reference."
    )
    mutated["proposed_statement"] = (
        "The step differs from the reference, therefore it is a violation."
    )
    mutated["correction"] = "Change the step so that it matches the reference."
    solution_a["rule_violation_analysis"] = mutated
    target_id = row_inputs.evidence[0]["evidence_id"]
    evidence = tuple(
        {**fragment, "content": "Any difference from the reference is a violation."}
        if fragment["evidence_id"] == target_id
        else fragment
        for fragment in row_inputs.evidence
    )
    return replace(
        row_inputs,
        question_revision=_revision(row_inputs.question_revision, "unsupported_rule"),
        solution_a=solution_a,
        evidence=evidence,
    )


_MUTATIONS = {
    CASE_AMBIGUITY: ("MISSING_CONDITION", missing_condition),
    CASE_AGREEMENT: ("DISAGREEING_SOLUTION", disagreeing_solution),
    CASE_DISTRACTORS: ("DUPLICATE_CORRECT_OPTION", duplicate_correct_option),
    CASE_RULE: ("UNSUPPORTED_RULE", unsupported_rule),
}


def build_rows(
    base_rows: list[tuple[str, ReviewerInputs]],
    *,
    include_positives: bool = True,
) -> list[EvaluationRow]:
    """Expand base items into positive controls and injected-defect negatives.

    A case whose mutation cannot actually be applied to an item contributes no
    negative row, and the gap is left visible rather than filled with a
    mutation that does not change anything.
    """
    rows: list[EvaluationRow] = []
    for family_id, inputs in base_rows:
        if include_positives:
            rows.append(
                EvaluationRow(
                    row_id=f"{family_id}:positive",
                    inputs=inputs,
                    label=POSITIVE_LABEL,
                    provenance=(
                        "server-authored item; every deterministic hard gate PASS; "
                        "no defect injected (control, not human gold)"
                    ),
                    target_case=None,
                    defect=None,
                    family_id=family_id,
                )
            )
        for case in inputs.required_cases:
            name, mutate = _MUTATIONS[case]
            mutated = mutate(inputs)
            if mutated is None:
                continue
            rows.append(
                EvaluationRow(
                    row_id=f"{family_id}:{name}",
                    inputs=mutated,
                    label=NEGATIVE_LABEL,
                    provenance=(
                        f"deterministic byte-level mutation '{name}' applied to the "
                        f"frozen reviewer input; the {case} case must not pass"
                    ),
                    target_case=case,
                    defect=name,
                    family_id=family_id,
                )
            )
    return rows


def dataset_digest(rows: list[EvaluationRow]) -> str:
    canonical = json.dumps(
        [row.manifest_entry() for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
