from app.visual.compiler import compile_visual_spec
from app.visual.planner import GroundedPolicyVisualPlannerProvider

ANSWER = r"""
Worked example (constructed teaching example, not original course data).
| A | (1, 1) |
| B | (2, 1) |
| C | (4, 3) |
| D | (5, 4) |
K = 2
c_1^{(0)} = (1, 1)
c_2^{(0)} = (5, 4)
"""


def plan(answer=ANSWER):
    return GroundedPolicyVisualPlannerProvider().plan(
        question="请用中文教我 K-means Clustering",
        answer=answer,
        evidence=[],
        action="diagram",
        language="zh-CN",
    )


def test_delivered_kmeans_example_has_computed_centroids_and_sse():
    spec = plan()
    svg = compile_visual_spec(spec).deterministic_source
    assert "SSE = 1.5" in svg
    assert "(1.5, 1)" in svg
    assert "(4.5, 3.5)" in svg
    assert "main concept" not in svg
    assert "例" in svg
    assert spec.diagram.kmeans.points[0].x == 1


def test_missing_course_structure_is_text_only_not_successful_placeholder():
    spec = plan("")
    assert not spec.should_generate
    assert spec.renderer == "NONE"


def test_no_coordinates_are_invented_from_a_title():
    spec = plan("K-means uses centroids.")
    assert not spec.should_generate


def test_unrelated_unknown_topic_does_not_get_default_box():
    spec = GroundedPolicyVisualPlannerProvider().plan(
        question="Explain an unspecified topic",
        answer="",
        evidence=[],
        action="auto",
        language="en",
    )
    assert not spec.should_generate


def test_existing_spec_without_extension_preserves_serialized_identity():
    from app.visual.spec import Diagram

    raw = {"layout": "AUTO", "nodes": [], "edges": []}
    assert Diagram.model_validate(raw).model_dump() == raw


def test_empty_cluster_declines_without_inventing_a_center():
    assert not plan(ANSWER.replace("c_2^{(0)} = (5, 4)", "c_2^{(0)} = (999, 999)")).should_generate


def test_duplicate_labels_decline_instead_of_merging_points():
    assert not plan(ANSWER.replace("| B |", "| A |")).should_generate


def test_independent_exercise_is_not_added_to_worked_example():
    spec = plan(ANSWER + "\nIndependent exercise:\n| P | (100, 100) |")
    assert len(spec.diagram.kmeans.points) == 4


def test_other_cluster_counts_are_not_silently_replaced_by_two():
    assert not plan(ANSWER.replace("K = 2", "K = 3")).should_generate
