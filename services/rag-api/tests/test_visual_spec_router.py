from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.visual.compiler import compile_visual_spec
from app.visual.planner import MockVisualPlannerProvider, load_runtime_prompt
from app.visual.spec import Renderer, VisualSpec, validate_source_grounding
from app.visual.workflows import WorkflowRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "visual_router_cases_v1.json"


def test_production_registry_uses_frozen_flux_and_wan_workflows() -> None:
    registry = WorkflowRegistry.load()
    assert (
        registry.select(Renderer.COMFY_IMAGE, "aliyun_eas").workflow_id
        == "coursejesus-flux2-klein-image-v1"
    )
    assert (
        registry.select(Renderer.COMFY_VIDEO, "aliyun_eas").workflow_id
        == "coursejesus-wan22-ti2v-5b-video-v1"
    )


def test_wan_compilation_uses_native_24fps_and_bounded_single_gpu_geometry() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="VIDEO",
            renderer="COMFY_VIDEO",
            duration_seconds=3,
            motion_is_essential=True,
            semantic_precision="ILLUSTRATIVE",
            diagram=None,
        )
    )
    compiled = compile_visual_spec(spec)
    assert (compiled.frames, compiled.width, compiled.height) == (73, 512, 288)
    assert compiled.cfg == 5


def valid_spec(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "visual_spec_version": "1.0",
        "should_generate": True,
        "pedagogical_reason": "A diagram makes the relationship easier to inspect.",
        "visual_goal": "Show the supported relationship.",
        "visual_type": "DIAGRAM",
        "renderer": "SVG",
        "importance": "MEDIUM",
        "timing": "ON_DEMAND",
        "source_grounding": [
            {
                "source_id": "source-1",
                "source_version": "v1",
                "locator": "p.1",
                "supported_claim": "A relates to B.",
            }
        ],
        "must_include": ["A", "B"],
        "must_not_include": [],
        "exact_labels": ["A", "B"],
        "equations": [],
        "code_elements": [],
        "reference_assets": [],
        "style": {"tone": "CLEAN_TECHNICAL"},
        "duration_seconds": None,
        "aspect_ratio": "16:9",
        "cost_tier": "LOW",
        "confidence": 0.9,
        "fallback_renderer": "NONE",
        "cache_policy": "REUSE",
        "language": "en",
        "motion_is_essential": False,
        "semantic_precision": "EXACT",
        "diagram": {
            "layout": "LEFT_RIGHT",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b", "label": "relates"}],
        },
        "animation_steps": [],
    }
    value.update(changes)
    return value


def test_visual_spec_is_strict_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        VisualSpec.model_validate({**valid_spec(), "workflow_json": {}})


def test_visual_spec_rejects_oversized_prompt_fragments() -> None:
    with pytest.raises(ValidationError):
        VisualSpec.model_validate(valid_spec(must_include=["x" * 801]))


@pytest.mark.parametrize(
    "changes",
    [
        {"should_generate": False},
        {"visual_type": "VIDEO", "renderer": "COMFY_VIDEO", "motion_is_essential": False},
        {"renderer": "COMFY_IMAGE", "semantic_precision": "EXACT"},
        {
            "diagram": {
                "layout": "AUTO",
                "nodes": [{"id": "a", "label": "A"}],
                "edges": [{"from": "a", "to": "missing"}],
            }
        },
        {
            "diagram": {
                "layout": "AUTO",
                "nodes": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}],
                "edges": [],
            }
        },
        {
            "visual_type": "ANIMATION",
            "renderer": "MANIM",
            "animation_steps": [
                {"order": 2, "label": "second", "highlight_ids": []},
                {"order": 1, "label": "first", "highlight_ids": []},
            ],
        },
    ],
)
def test_visual_spec_rejects_semantically_invalid_payloads(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        VisualSpec.model_validate(valid_spec(**changes))


def test_source_grounding_must_be_resolved_by_server() -> None:
    spec = VisualSpec.model_validate(valid_spec())
    validate_source_grounding(spec, {("source-1", "v1")})
    with pytest.raises(ValueError, match="not present"):
        validate_source_grounding(spec, {("other", "v1")})


def test_unverified_reference_asset_is_rejected() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(reference_assets=[{"asset_id": "private-asset", "purpose": "style"}])
    )
    with pytest.raises(ValueError, match="reference asset"):
        validate_source_grounding(spec, {("source-1", "v1")})


def test_runtime_prompt_is_loaded_from_versioned_file_with_hash() -> None:
    loaded = load_runtime_prompt()
    assert loaded.version == "visual-router-planner-v2"
    assert len(loaded.sha256) == 64
    assert "VisualSpec version 1.0" in loaded.text


def test_all_40_router_cases_match_the_contract() -> None:
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 40
    planner = MockVisualPlannerProvider()
    for case in cases:
        spec = planner.plan(
            question=case["question"],
            answer="Course-grounded answer.",
            evidence=[],
            action="auto",
            language="en",
        )
        assert spec.should_generate is case["should_visualize"], case["id"]
        assert spec.visual_type.value == case["expected_visual_type"], case["id"]
        assert spec.renderer.value == case["expected_renderer_family"], case["id"]
        if case["should_not_use_video"]:
            assert spec.renderer is not Renderer.COMFY_VIDEO, case["id"]
        if case["exactness_required"]:
            assert spec.renderer not in {Renderer.COMFY_IMAGE, Renderer.COMFY_VIDEO}, case["id"]


def test_compiler_keeps_exact_text_out_of_generative_prompt() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="IMAGE",
            renderer="COMFY_IMAGE",
            semantic_precision="BOUNDED",
            exact_labels=["SYN", "ACK"],
            equations=["x = 1"],
            diagram=None,
        )
    )
    compiled = compile_visual_spec(spec)
    assert "SYN" not in compiled.positive_prompt
    assert "x = 1" not in compiled.positive_prompt
    assert [overlay.text for overlay in compiled.overlays] == ["SYN", "ACK", "x = 1"]


def test_conceptual_image_prompt_contains_question_and_grounded_claim() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question="Explain gravitational lensing as a conceptual natural scene.",
        answer=(
            "A massive foreground object curves spacetime and bends light from a distant source."
        ),
        evidence=[
            {
                "source_id": "source-1",
                "source_version": "v1",
                "locator": "p.4",
                "supported_claim": (
                    "A massive foreground object bends light paths from a distant galaxy, "
                    "so the observer may see luminous arcs or an Einstein ring."
                ),
            }
        ],
        action="visual",
        language="en",
    )
    compiled = compile_visual_spec(spec)
    prompt = compiled.positive_prompt.lower()
    assert spec.renderer is Renderer.COMFY_IMAGE
    assert "gravitational lensing" in prompt
    assert "massive foreground object" in prompt
    assert "einstein ring" in prompt
    assert "show the supported concept" not in prompt
    assert "conceptual scene" not in prompt


def test_generative_prompt_uses_structured_course_grounded_sections() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="IMAGE",
            renderer="COMFY_IMAGE",
            semantic_precision="BOUNDED",
            visual_goal="Show a massive foreground object bending light from a distant galaxy.",
            pedagogical_reason="The learner must see why the observer detects an arc.",
            must_include=["massive foreground object", "distant galaxy"],
            must_not_include=["extra planets", "watermark"],
            exact_labels=[],
            diagram=None,
            style={
                "tone": "CONCEPTUAL",
                "background": "dark space",
                "composition": "single clear focal path",
                "camera": "distant scientific observation",
            },
        )
    )
    compiled = compile_visual_spec(spec)
    prompt = compiled.positive_prompt

    assert "Subject:" in prompt
    assert "Required elements:" in prompt
    assert "Spatial relationships and course facts:" in prompt
    assert "View and composition:" in prompt
    assert "Lighting and background:" in prompt
    assert "Forbidden elements:" in prompt
    assert "Educational purpose:" in prompt
    assert "massive foreground object" in prompt
    assert "distant galaxy" in prompt
    assert "A relates to B." in prompt
    assert "extra planets" in prompt
    assert "The learner must see why the observer detects an arc." in prompt


def test_flux_image_uses_the_frozen_klein_sampler_and_does_not_claim_negative_conditioning() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="IMAGE",
            renderer="COMFY_IMAGE",
            semantic_precision="BOUNDED",
            must_not_include=["watermark"],
            diagram=None,
        )
    )
    compiled = compile_visual_spec(spec)

    assert (compiled.steps, compiled.cfg) == (4, 1)
    assert compiled.negative_prompt == ""
    assert "watermark" in compiled.positive_prompt


def test_wan_keeps_negative_conditioning_and_steps_its_teaching_prompt() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="VIDEO",
            renderer="COMFY_VIDEO",
            semantic_precision="ILLUSTRATIVE",
            motion_is_essential=True,
            duration_seconds=3,
            must_include=["the left gear pushes the right gear"],
            must_not_include=["extra gears", "watermark"],
            diagram=None,
            style={
                "tone": "REALISTIC",
                "background": "plain workshop",
                "composition": "gears fill the frame",
                "camera": "fixed front view",
            },
        )
    )
    compiled = compile_visual_spec(spec)

    assert "watermark" in compiled.positive_prompt
    assert "the left gear pushes the right gear" in compiled.positive_prompt
    assert compiled.negative_prompt == "extra gears, watermark"
    assert (compiled.steps, compiled.cfg) == (20, 5)


def test_svg_compiler_renders_validated_nodes_edges_and_edge_labels() -> None:
    spec = VisualSpec.model_validate(valid_spec())
    compiled = compile_visual_spec(spec)
    assert compiled.renderer is Renderer.SVG
    assert 'id="a"' in compiled.deterministic_source
    assert 'id="b"' in compiled.deterministic_source
    assert 'data-from="a"' in compiled.deterministic_source
    assert 'data-to="b"' in compiled.deterministic_source
    assert "relates" in compiled.deterministic_source
