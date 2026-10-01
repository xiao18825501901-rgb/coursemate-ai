from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.visual.compiler import compile_visual_spec
from app.visual.planner import MockVisualPlannerProvider, load_runtime_prompt
from app.visual.spec import Renderer, VisualSpec, validate_source_grounding

FIXTURES = Path(__file__).parent / "fixtures" / "visual_router_cases_v1.json"


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
    assert loaded.version == "visual-router-planner-v1"
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


def test_svg_compiler_renders_validated_nodes_edges_and_edge_labels() -> None:
    spec = VisualSpec.model_validate(valid_spec())
    compiled = compile_visual_spec(spec)
    assert compiled.renderer is Renderer.SVG
    assert 'id="a"' in compiled.deterministic_source
    assert 'id="b"' in compiled.deterministic_source
    assert 'data-from="a"' in compiled.deterministic_source
    assert 'data-to="b"' in compiled.deterministic_source
    assert "relates" in compiled.deterministic_source
