import pytest

from app.visual.compiler import compile_visual_spec
from app.visual.planner import GroundedPolicyVisualPlannerProvider
from app.visual.validators import InvalidVisualOutput, validate_output

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


def test_phospholipid_diagram_uses_delivered_fact_as_accessible_goal():
    spec = GroundedPolicyVisualPlannerProvider().plan(
        question="请用一句中文说明“流动镶嵌模型”中疏水尾部为什么朝向膜的内侧。",
        answer="因为磷脂的疏水尾部无法与水形成氢键，所以在水环境中朝向膜内侧。[S1]",
        evidence=[],
        action="diagram",
        language="zh-CN",
    )
    assert spec.renderer == "SVG"
    assert spec.visual_goal == "因为磷脂的疏水尾部无法与水形成氢键，所以在水环境中朝向膜内侧。"
    assert "Explain the supported relationships" not in spec.visual_goal


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


@pytest.mark.parametrize("action", ["diagram", "animate"])
def test_hdd_kinematics_is_structured_deterministic_animation(action: str):
    spec = GroundedPolicyVisualPlannerProvider().plan(
        question=(
            "Explain a mechanical hard disk drive: how does the platter rotate "
            "while the actuator arm changes radial position?"
        ),
        answer=(
            "The platter rotates continuously around the fixed spindle while the "
            "actuator arm moves the read/write head across radial positions."
        ),
        evidence=[
            {
                "source_id": "course-hardware",
                "source_version": "v1",
                "locator": "section:hard-disk-drive",
                "supported_claim": (
                    "The platter rotates around the spindle while the actuator arm "
                    "moves the head radially."
                ),
            }
        ],
        action=action,
        language="en",
    )
    compiled = compile_visual_spec(spec)

    assert spec.visual_type == "ANIMATION"
    assert spec.renderer == "SVG"
    assert spec.diagram is not None
    assert spec.diagram.hdd_kinematics is not None
    assert spec.motion_is_essential is True
    assert 'data-renderer="hdd-kinematics"' in compiled.deterministic_source
    assert "<animateTransform" in compiled.deterministic_source
    assert "Continuous platter rotation" in compiled.deterministic_source
    assert "Bounded radial sweep" in compiled.deterministic_source
    assert "Actuator arm" in compiled.deterministic_source
    assert "Read/write head" in compiled.deterministic_source
    assert "main concept" not in compiled.deterministic_source.lower()
    assert (compiled.width, compiled.height) == (720, 720)
    validate_output(
        compiled.deterministic_source.encode(),
        mime_type="image/svg+xml",
        width=compiled.width,
        height=compiled.height,
        duration_seconds=None,
        max_bytes=2_000_000,
        max_width=2048,
        max_height=2048,
        max_duration_seconds=15,
    )


def test_svg_animation_cannot_rewrite_arbitrary_attributes():
    unsafe = (
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b'<animateTransform attributeName="onload" type="rotate" values="0;1" '
        b'dur="1s" repeatCount="indefinite"/>'
        b"</svg>"
    )

    with pytest.raises(InvalidVisualOutput, match="animation target"):
        validate_output(
            unsafe,
            mime_type="image/svg+xml",
            width=720,
            height=720,
            duration_seconds=None,
            max_bytes=2_000_000,
            max_width=2048,
            max_height=2048,
            max_duration_seconds=15,
        )
