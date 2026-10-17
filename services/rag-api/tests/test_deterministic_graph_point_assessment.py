"""Source-bound host questions for the audited graph-degree point family."""

import hashlib

import pytest

from app.learning.assessment_point_configuration import PointQuestionSlot
from app.learning.assessment_point_question_inputs import (
    AssessmentPointQuestionInput,
    OriginalPointTarget,
    _blueprint_id,
)
from app.learning.deterministic_graph_point_assessment import (
    METHOD,
    build_graph_point_content,
)

SOURCE = (
    "Graph Theory Essentials. In an undirected graph, the degree of a vertex is "
    "the number of incident edges. The sum of all vertex degrees equals twice "
    "the number of edges."
)
HASH = hashlib.sha256(SOURCE.encode()).hexdigest()

CASES = (
    (
        "vd_degree_definition_required",
        "target-point-degree",
        "Define the degree of a vertex in an undirected graph as the number of incident edges.",
        "Learner states the definition and computes every requested degree.",
        "SHORT_TEXT",
        "definition",
    ),
    (
        "vd_handshake_identity_required",
        "target-point-handshake",
        "State and apply the identity that the sum of all vertex degrees "
        "equals twice the number of edges.",
        "Learner states the identity and verifies both sides on the supplied graph.",
        "SHORT_TEXT",
        "definition",
    ),
    (
        "vd_even_odd_degree_count",
        "target-point-odd",
        "Derive from the handshake identity that the number of odd-degree vertices is even.",
        "Learner derives the parity result and verifies it on the supplied graph.",
        "EXPLANATION",
        "analysis",
    ),
    (
        "vd_doubling_misconception",
        "target-point-double",
        "Correct the misconception that the degree sum equals the edge count "
        "rather than twice the edge count.",
        "Learner rejects the claim, gives the factor-two reason, and verifies an example.",
        "EXPLANATION",
        "analysis",
    ),
)


def point_input(case=CASES[0], *, language="en") -> AssessmentPointQuestionInput:
    item_id, point_id, objective, acceptance, question_type, task_form = case
    fragment = {
        "evidence_id": "chunk-graph",
        "document_id": "document-graph",
        "document_version_id": "document-graph-v1",
        "document_version": 1,
        "document_sha256": HASH,
        "filename": "graph.pdf",
        "source_scope": "WORKSPACE_PRIVATE",
        "ordinal": 0,
        "locator_type": "page",
        "locator_value": "1",
        "section": "Page 1",
        "content": SOURCE,
        "truncated": False,
        "source_content_sha256": HASH,
        "excerpt_sha256": HASH,
    }
    evidence = {
        "schema_version": "question-evidence-pack.v1",
        "course_id": "course-graph",
        "node_id": "node-graph",
        "spec_version": 1,
        "spec_content_hash": "a" * 64,
        "objective_id": item_id,
        "objective_text": objective,
        "acceptance": acceptance,
        "evidence_ids": ["chunk-graph"],
        "fragments": [fragment],
    }
    point = {
        "point_id": point_id,
        "canonical_key": item_id,
        "objective": objective,
        "constraints": [SOURCE],
        "scoring_evidence": [acceptance],
        "allowed_forms": [question_type],
        "sequence": 0,
        "source_refs": [{
            "source_id": "chunk-graph",
            "document_id": "document-graph",
            "document_version": "document-graph-v1",
            "locator": "page:1",
            "scope_key": "workspace:workspace-graph:owner:owner-graph",
        }],
        "validation_receipt_id": "catalog-review-graph",
        "status": "VERIFIED",
        "weight": 1,
        "weight_receipt_id": None,
    }
    payload = {
        "owner_user_id": "owner-graph",
        "workspace_id": "workspace-graph",
        "course_id": "course-graph",
        "private_course_id": "private-graph",
        "node_id": "node-graph",
        "configuration_id": "configuration-graph",
        "plan_hash": "b" * 64,
        "source_snapshot": "c" * 64,
        "spec_version": 1,
        "spec_content_hash": "a" * 64,
        "content_language": language,
        "point_slot": {
            "schema_version": "assessment-question-slot.points.v1",
            "slot_key": "slot-graph-" + item_id,
            "ordinal": 1,
            "marks": 100,
            "marks_basis_points": 10000,
            "bloom_target": "ANALYZE" if task_form == "analysis" else "UNDERSTAND",
            "target_difficulty": 3,
            "difficulty_features": ["CONCEPTS", "STEPS"],
            "empirical_difficulty": None,
            "question_type": question_type,
            "task_form": task_form,
            "expected_answer_form": "WORKED_STEPS" if task_form == "analysis" else "SHORT_ANSWER",
            "scoring_focus": acceptance,
            "misconception_target": "Surface counting instead of applying the stated conditions.",
            "primary_point_id": point_id,
            "variation_purpose": None,
            "independently_scored_parts": 1,
            "original_target_item_ids": [item_id],
            "verified_point": point,
        },
        "targets": [{
            "item_id": item_id,
            "requirement": "REQUIRED",
            "objective": objective,
            "acceptance": acceptance,
            "evidence": evidence,
        }],
    }
    payload["point_slot"] = PointQuestionSlot.model_validate(
        payload["point_slot"]
    ).model_dump(mode="json")
    payload["targets"] = [
        OriginalPointTarget.model_validate(target).model_dump(mode="json")
        for target in payload["targets"]
    ]
    return AssessmentPointQuestionInput.model_validate(
        {**payload, "blueprint_id": _blueprint_id(payload)}
    )


@pytest.mark.parametrize("case", CASES)
def test_all_four_audited_points_have_checkable_answer_and_source_steps(case):
    frozen = point_input(case)
    content = build_graph_point_content(frozen)
    assert content is not None
    assert content.method == METHOD
    assert content.point_input_hash == frozen.identity()
    assert content.question_text and content.reference_answer
    assert content.question_text != content.reference_answer
    assert [step.ordinal for step in content.solution_steps] == list(
        range(1, len(content.solution_steps) + 1)
    )
    assert all(step.source_refs == ["chunk-graph"] for step in content.solution_steps)
    assert content.proof["degree_sum"] == 8
    assert content.proof["twice_edge_count"] == 8
    assert content.proof["odd_degree_count"] == 2


def test_source_rule_or_slot_shape_change_refuses_deterministic_path():
    frozen = point_input()
    changed = frozen.model_dump(mode="json")
    changed["targets"][0]["evidence"]["fragments"][0]["content"] = (
        "A graph has vertices and edges but supplies no degree rule."
    )
    altered = changed["targets"][0]["evidence"]["fragments"][0]["content"]
    changed["targets"][0]["evidence"]["fragments"][0]["source_content_sha256"] = (
        hashlib.sha256(altered.encode()).hexdigest()
    )
    changed["targets"][0]["evidence"]["fragments"][0]["excerpt_sha256"] = (
        hashlib.sha256(altered.encode()).hexdigest()
    )
    payload = {key: value for key, value in changed.items() if key not in {
        "schema_version", "policy_version", "blueprint_id"
    }}
    changed["blueprint_id"] = _blueprint_id(payload)
    unsupported = AssessmentPointQuestionInput.model_validate(changed)
    assert build_graph_point_content(unsupported) is None

    wrong_form = point_input().model_copy(deep=True)
    wrong_form.point_slot.question_type = "EXPLANATION"
    assert build_graph_point_content(wrong_form) is None


def test_chinese_ui_language_produces_chinese_question_without_changing_source():
    frozen = point_input(language="zh-CN")
    content = build_graph_point_content(frozen)
    assert content is not None
    assert "有限无向简单图" in content.question_text
    assert content.source_snapshot == frozen.source_snapshot
