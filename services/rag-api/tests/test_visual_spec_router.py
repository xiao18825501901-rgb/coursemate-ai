from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from app.visual.api import _exact_asset_labels
from app.visual.compiler import compile_visual_spec
from app.visual.planner import MockVisualPlannerProvider, load_runtime_prompt
from app.visual.spec import Renderer, VisualSpec, VisualType, validate_source_grounding
from app.visual.validators import validate_output
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


def test_exact_labels_are_projected_for_the_caption_but_not_sent_to_generation() -> None:
    labels = ["主板", "CPU 插座／散热器区域", "不要从本图推断电气兼容性"]
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="IMAGE",
            renderer="COMFY_IMAGE",
            exact_labels=labels,
            semantic_precision="BOUNDED",
            diagram=None,
        )
    )

    compiled = compile_visual_spec(spec)
    projected = _exact_asset_labels(
        {"visual_spec_json": spec.model_dump_json(by_alias=True)}
    )

    assert projected == labels
    assert all(label not in compiled.positive_prompt for label in labels)


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
    assert loaded.version == "visual-router-planner-v4"
    assert len(loaded.sha256) == 64
    assert "VisualSpec version 1.0" in loaded.text


def test_all_40_router_route_families_match_the_contract() -> None:
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 40
    planner = MockVisualPlannerProvider()
    for case in cases:
        visual_type, renderer, _ = planner._decision(case["question"])
        assert (visual_type != "NONE") is case["should_visualize"], case["id"]
        assert visual_type == case["expected_visual_type"], case["id"]
        assert renderer == case["expected_renderer_family"], case["id"]
        if case["should_not_use_video"]:
            assert renderer != Renderer.COMFY_VIDEO.value, case["id"]
        if case["exactness_required"]:
            assert renderer not in {Renderer.COMFY_IMAGE.value, Renderer.COMFY_VIDEO.value}, (
                case["id"]
            )


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


def test_natural_image_extracts_a_visual_fact_instead_of_a_leading_heading() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question="Explain gravitational lensing as a conceptual natural scene.",
        answer=(
            "一、章节定位与知识链\n"
            "A massive foreground galaxy bends light from a distant source into luminous arcs."
        ),
        evidence=[
            {
                "source_id": "gravity-source",
                "source_version": "v1",
                "locator": "section 2",
                "supported_claim": "CourseJesus_Gravity_Notes.md",
            }
        ],
        action="visual",
        language="en",
    )
    compiled = compile_visual_spec(spec)
    rendered = compiled.positive_prompt

    assert spec.renderer is Renderer.COMFY_IMAGE
    assert any("bends light" in claim for claim in spec.must_include)
    assert "章节定位" not in rendered
    assert "CourseJesus_Gravity_Notes.md" not in rendered
    assert spec.pedagogical_reason != "A visual is useful."


def test_natural_video_preserves_a_grounded_evidence_fact_and_rejects_labels() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question="Explain how two gears transfer motion in a short animation.",
        answer="Unit 2\nCourseJesus_Gear_Notes.docx",
        evidence=[
            {
                "source_id": "gear-source",
                "source_version": "v1",
                "locator": "Unit 2",
                "supported_claim": (
                    "When two gears mesh, their touching teeth move in opposite directions."
                ),
            }
        ],
        action="animate",
        language="en",
    )
    compiled = compile_visual_spec(spec)
    rendered = compiled.positive_prompt

    assert spec.renderer is Renderer.COMFY_VIDEO
    assert any("opposite directions" in claim for claim in spec.must_include)
    assert "Unit 2" not in rendered
    assert "CourseJesus_Gear_Notes.docx" not in rendered
    assert spec.pedagogical_reason != "A visual is useful."


def test_natural_visual_does_not_generate_from_document_labels_alone() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question="Explain gravitational lensing as a conceptual natural scene.",
        answer="一、章节定位与知识链\nCourseJesus_Gravity_Notes.md",
        evidence=[
            {
                "source_id": "gravity-source",
                "source_version": "v1",
                "locator": "section 2",
                "supported_claim": "CourseJesus_Gravity_Notes.md",
            }
        ],
        action="visual",
        language="en",
    )

    assert spec.renderer is Renderer.NONE
    assert spec.should_generate is False
    assert spec.must_include == []


def test_phospholipid_structure_uses_deterministic_teaching_diagram() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question="为什么流动镶嵌模型中的疏水尾部朝向膜的内侧？",
        answer=(
            "因为疏水尾部无法与水形成氢键，所以在水环境中会彼此相对、朝向膜内侧。 [S2][S3][S6]"
        ),
        evidence=[
            {
                "source_id": "source-1",
                "source_version": "ui-citation-v1",
                "locator": "96",
                "supported_claim": "Biology2e-OP.pdf",
            }
        ],
        action="visual",
        language="zh-CN",
    )
    compiled = compile_visual_spec(spec)

    assert spec.visual_type is VisualType.DIAGRAM
    assert spec.renderer is Renderer.SVG
    assert spec.semantic_precision == "EXACT"
    assert spec.diagram is not None
    assert spec.diagram.phospholipid_bilayer is not None
    assert compiled.positive_prompt == ""
    assert 'data-renderer="phospholipid-bilayer"' in compiled.deterministic_source
    assert "疏水尾部朝向膜内侧" in compiled.deterministic_source
    assert "main concept" not in compiled.deterministic_source
    assert 'viewBox="0 0 720 720"' in compiled.deterministic_source
    assert 'font-size="34"' in compiled.deterministic_source
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


def test_visual_action_does_not_force_an_unsafe_comfy_image() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question="请用图片解释一个没有受支持视觉结构的概念。",
        answer="课程文字给出了一个定义。",
        evidence=[],
        action="visual",
        language="zh-CN",
    )

    assert spec.visual_type is VisualType.NONE
    assert spec.renderer is Renderer.NONE
    assert spec.should_generate is False


def test_endomembrane_protein_transport_routes_to_grounded_generative_video() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question=(
            "请用中文讲解内质网、高尔基体和细胞膜之间的蛋白质运输，"
            "重点展示运输囊泡从粗面内质网出芽、与高尔基体融合、"
            "再通过囊泡到达细胞膜并成为膜蛋白的过程。"
            "结合 OpenStax Biology 2e。动画展示。"
        ),
        answer="分泌蛋白从粗面内质网进入高尔基体，再由囊泡运到细胞膜。",
        evidence=[
            {
                "source_id": "openstax-biology-2e",
                "source_version": "2018",
                "locator": "p.133",
                "supported_claim": (
                    "A transport vesicle buds from the rough endoplasmic reticulum, "
                    "fuses with the Golgi apparatus, and carries membrane proteins "
                    "to the plasma membrane."
                ),
            }
        ],
        action="animate",
        language="zh-CN",
    )
    compiled = compile_visual_spec(spec)

    assert spec.visual_type is VisualType.VIDEO
    assert spec.renderer is Renderer.COMFY_VIDEO
    assert spec.motion_is_essential is True
    assert spec.duration_seconds == 3
    assert [step.label for step in spec.animation_steps] == [
        "A transport vesicle starts attached to the rough endoplasmic reticulum.",
        (
            "One transport vesicle buds from the rough endoplasmic reticulum and moves "
            "toward the Golgi apparatus."
        ),
        (
            "The vesicle fuses with the Golgi apparatus, then a membrane-protein vesicle "
            "reaches the plasma membrane."
        ),
    ]
    assert "rough endoplasmic reticulum" in compiled.positive_prompt
    assert "Golgi apparatus" in compiled.positive_prompt
    assert "plasma membrane" in compiled.positive_prompt
    assert "two meshed gears" not in compiled.positive_prompt


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
    assert "Do not render any letters" in prompt
    assert "pseudo-text" in prompt


def test_flux_image_uses_frozen_klein_sampler_without_negative_conditioning() -> None:
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


def test_wan_prompt_defines_one_continuous_teaching_action_with_fixed_objects() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="VIDEO",
            renderer="COMFY_VIDEO",
            semantic_precision="ILLUSTRATIVE",
            motion_is_essential=True,
            duration_seconds=3,
            visual_goal=(
                "A transport vesicle buds from the rough endoplasmic reticulum and moves "
                "to the Golgi apparatus."
            ),
            pedagogical_reason=(
                "The learner must observe the ordered direction of membrane-protein transport."
            ),
            must_include=[
                "rough endoplasmic reticulum",
                "one transport vesicle",
                "Golgi apparatus",
            ],
            must_not_include=["extra vesicles", "camera cuts", "watermark"],
            diagram=None,
            animation_steps=[
                {
                    "order": 1,
                    "label": (
                        "A transport vesicle starts attached to the rough endoplasmic reticulum."
                    ),
                    "highlight_ids": [],
                },
                {
                    "order": 2,
                    "label": (
                        "One transport vesicle buds from the rough endoplasmic reticulum "
                        "and moves toward the Golgi apparatus."
                    ),
                    "highlight_ids": [],
                },
                {
                    "order": 3,
                    "label": "The transport vesicle reaches and fuses with the Golgi apparatus.",
                    "highlight_ids": [],
                },
            ],
            style={
                "tone": "TEXTBOOK",
                "background": "clean microscopic cell environment",
                "composition": "membrane structures fill the frame",
                "camera": "fixed side view",
            },
        )
    )
    compiled = compile_visual_spec(spec)
    prompt = compiled.positive_prompt

    assert "Initial state:" in prompt
    assert "Main action:" in prompt
    assert "Final state:" in prompt
    assert "Fixed objects:" in prompt
    assert "Camera and continuity:" in prompt
    assert "Learning objective:" in prompt
    assert "A transport vesicle starts attached" in prompt
    assert "transport vesicle buds" in prompt
    assert "reaches and fuses with the Golgi apparatus" in prompt
    assert "fixed side view" in prompt
    assert "single continuous shot" in prompt
    assert "no montage" in prompt
    assert "no camera cuts" in prompt
    assert "no additional teaching actions" in prompt


def test_wan_prompt_is_a_compact_single_shot_renderer_contract() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="VIDEO",
            renderer="COMFY_VIDEO",
            semantic_precision="ILLUSTRATIVE",
            motion_is_essential=True,
            duration_seconds=5,
            visual_goal=(
                "One complete mechanical hard-disk drive in a fixed cutaway view. "
                "The circular platter rotates continuously around its central spindle while "
                "the actuator arm makes one bounded radial sweep above the platter. The drive "
                "body, platter count and object identities remain unchanged."
            ),
            pedagogical_reason=(
                "Let the learner distinguish angular position change from radial position change."
            ),
            must_include=[
                "one fixed mechanical hard-disk body",
                "one circular platter rotating about a central spindle",
                "one actuator arm attached to a fixed pivot",
                "one read/write head making one bounded radial sweep above the platter",
            ],
            must_not_include=[
                "SSD",
                "people",
                "scratches",
                "sparks",
                "readable technical text",
            ],
            source_grounding=[
                {
                    "source_id": f"hard-disk-source-{index}",
                    "source_version": "v1",
                    "locator": f"Unit 2 source paragraph {index}",
                    "supported_claim": (
                        "This long course-evidence sentence is kept for grounding and audit, "
                        "not copied into the renderer prompt. "
                    )
                    * 6,
                }
                for index in range(4)
            ],
            diagram=None,
            animation_steps=[
                {
                    "order": 1,
                    "label": "Show every hard-disk object in one fixed cutaway view.",
                    "highlight_ids": [],
                },
                {
                    "order": 2,
                    "label": (
                        "The platter rotates continuously while the actuator arm completes one "
                        "bounded radial sweep above the same platter."
                    ),
                    "highlight_ids": [],
                },
                {
                    "order": 3,
                    "label": "Keep the drive body and every object fixed and recognizable.",
                    "highlight_ids": [],
                },
            ],
            style={
                "tone": "CLEAN_TECHNICAL",
                "background": "plain neutral background",
                "composition": "one drive fills the frame",
                "camera": "locked overhead cutaway view",
            },
        )
    )

    prompt = compile_visual_spec(spec).positive_prompt

    assert len(prompt) <= 1800
    assert "hard-disk-source-" not in prompt
    assert "This long course-evidence sentence" not in prompt
    assert "platter rotates continuously" in prompt
    assert "one bounded radial sweep" in prompt
    assert prompt.count("rotates continuously") == 1
    assert "single continuous shot" in prompt.lower()
    assert "fixed cutaway view" in prompt.lower()


def test_wan_prompt_removes_staged_delivery_instructions() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="VIDEO",
            renderer="COMFY_VIDEO",
            semantic_precision="ILLUSTRATIVE",
            motion_is_essential=True,
            duration_seconds=5,
            visual_goal=(
                "单个硬盘盘片连续旋转，执行器臂同时做一次有边界的径向移动，"
                "硬盘主体保持固定，并通过分段呈现区分两种运动。"
            ),
            must_include=[
                "单个固定硬盘主体",
                "圆形盘片连续旋转",
                "执行器臂做一次有边界的径向移动",
                "先分别展示盘片旋转段和执行器臂移动段，再展示二者组合",
            ],
            diagram=None,
            animation_steps=[
                {
                    "order": 1,
                    "label": "同一固定场景中可见硬盘主体、盘片和执行器臂。",
                    "highlight_ids": [],
                },
                {
                    "order": 2,
                    "label": "盘片连续旋转，执行器臂同时做一次径向扫掠。",
                    "highlight_ids": [],
                },
                {
                    "order": 3,
                    "label": "所有对象保持相同身份和位置关系。",
                    "highlight_ids": [],
                },
            ],
        )
    )

    prompt = compile_visual_spec(spec).positive_prompt

    assert "连续旋转" in prompt
    assert "径向移动" in prompt
    assert "分段呈现" not in prompt
    assert "先分别展示" not in prompt
    assert "再展示" not in prompt


def test_wan_prompt_rejects_non_video_semantics_without_stage_order() -> None:
    spec = VisualSpec.model_validate(
        valid_spec(
            visual_type="VIDEO",
            renderer="COMFY_VIDEO",
            semantic_precision="ILLUSTRATIVE",
            motion_is_essential=True,
            duration_seconds=3,
            visual_goal="Show the supported relationship.",
            must_include=["A", "B"],
            exact_labels=[],
            diagram=None,
            animation_steps=[
                {
                    "order": 1,
                    "label": "Only a single state is described.",
                    "highlight_ids": [],
                }
            ],
        )
    )
    compiled = compile_visual_spec(spec)

    assert "Initial state:\nOnly a single state is described." in compiled.positive_prompt
    assert "Final state:\nPreserve A and B at the end" in compiled.positive_prompt


def test_hdd_motion_routes_to_a_single_fixed_camera_continuous_action() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question=(
            "请严格依据课程资料，教我区分机械硬盘中盘片的连续旋转与执行器臂有限的径向移动。"
            "用文字说明两个运动改变的是不同位置维度，并保持同一硬盘固定不动。"
            "不得声称精确转速、寻道时间、数据位置或内部制造细节，也不得出现刮擦、火花、"
            "SSD、人物或可读技术文字。"
        ),
        answer=(
            "机械硬盘中的圆形盘片绕中央主轴连续旋转，执行器臂带动读写头在盘片上方进行"
            "有限的径向移动；同一硬盘主体保持固定。"
        ),
        evidence=[
            {
                "source_id": "hard-disk-visual-source",
                "source_version": "v1",
                "locator": "Unit 2",
                "supported_claim": (
                    "The circular platters rotate around a central spindle while the actuator "
                    "arm moves the read/write head across radial positions above the platters; "
                    "the drive body remains fixed."
                ),
            }
        ],
        action="visual",
        language="zh-CN",
    )
    compiled = compile_visual_spec(spec)
    prompt = compiled.positive_prompt

    assert compiled.start_image_png_b64
    first_frame = Image.open(io.BytesIO(base64.b64decode(compiled.start_image_png_b64)))
    assert first_frame.size == (512, 288)
    assert len(first_frame.convert("RGB").getcolors(maxcolors=1_000_000) or []) > 4
    assert spec.visual_type is VisualType.VIDEO
    assert spec.renderer is Renderer.COMFY_VIDEO
    assert spec.must_include == [
        "one mechanical hard-disk drive body remaining fixed",
        "one circular platter rotating about a central spindle",
        (
            "one visible actuator arm spanning from a pivot beside the platter to the "
            "read/write head above the platter"
        ),
        "one read/write head visibly changing bounded radial position above the platter",
    ]
    assert [step.label for step in spec.animation_steps] == [
        (
            "The drive body, circular platter, central spindle, actuator arm and "
            "read/write head are visible in one fixed cutaway view."
        ),
        (
            "The platter rotates continuously around the fixed spindle while the actuator "
            "arm performs one bounded radial sweep above it."
        ),
        (
            "The same drive body and objects remain visible with only the platter angle and "
            "actuator-arm radial position changed."
        ),
    ]
    assert "fixed cutaway view" in prompt
    assert "platter rotates continuously" in prompt
    assert "one bounded radial sweep" in prompt
    assert "direct overhead cutaway view" in prompt
    assert "actuator arm is fully exposed beside the platter" in prompt
    assert "章节定位" not in prompt
    assert "- CourseJesus_PC_Hardware_Visual_Acceptance_20261009.md" not in prompt


def test_generic_desktop_components_route_to_grounded_flux_image() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question=(
            "请严格依据课程资料，教我辨认通用台式电脑内部的主板、CPU 插座/散热器区域和 "
            "DIMM 内存插槽区域。不得推断品牌、精确尺寸、精确布局或兼容性，"
            "不要出现可读型号文字。"
        ),
        answer=(
            "主板是大型主电路板；CPU 区域位于主板上并可能被散热器覆盖；"
            "DIMM 插槽是通常位于 CPU 区域附近的长而窄的内存插槽区域。"
        ),
        evidence=[
            {
                "source_id": "desktop-components-visual-source",
                "source_version": "v1",
                "locator": "Unit 1",
                "supported_claim": (
                    "A motherboard is the large main circuit board. The CPU socket area is "
                    "on the motherboard and may be covered by a heatsink. DIMM slots are long "
                    "narrow memory-slot areas often near the CPU area."
                ),
            }
        ],
        action="visual",
        language="zh-CN",
    )
    compiled = compile_visual_spec(spec)
    prompt = compiled.positive_prompt

    assert spec.visual_type is VisualType.IMAGE
    assert spec.renderer is Renderer.COMFY_IMAGE
    assert spec.must_include == [
        "one large main circuit board fills most of the frame",
        "one compact CPU heatsink area mounted on the motherboard",
        "one set of long narrow parallel DIMM memory slots near the CPU area",
    ]
    assert "large main circuit board" in prompt
    assert "compact CPU heatsink area" in prompt
    assert "long narrow parallel DIMM memory slots" in prompt
    assert "Do not render any letters" in prompt
    assert "clean educational product photograph" in prompt
    assert "brand logos or model numbers" in prompt
    assert "laptops or server racks" in prompt
    assert "no arrows, leader lines, annotation circles or overlay cards" in prompt
    assert "unannotated product photograph" in prompt
    assert "unlabeled motion/relationship arrows" not in prompt


def test_svg_compiler_renders_validated_nodes_edges_and_edge_labels() -> None:
    spec = VisualSpec.model_validate(valid_spec())
    compiled = compile_visual_spec(spec)
    assert compiled.renderer is Renderer.SVG
    assert 'id="a"' in compiled.deterministic_source
    assert 'id="b"' in compiled.deterministic_source
    assert 'data-from="a"' in compiled.deterministic_source
    assert 'data-to="b"' in compiled.deterministic_source
    assert "relates" in compiled.deterministic_source


def test_dbscan_uses_grounded_density_classes_instead_of_generic_placeholder() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question="请用中文解释 DBSCAN 的核心点，并说明它与边界点、噪声点的区别。",
        answer=(
            "DBSCAN 是 density-based clustering。对某个点，用半径 Eps 数它周围有多少点，"
            "计数包括点自身。\n"
            "**核心点**：Eps 邻域内点数不少于 MinPts，是 cluster 生长的起点。\n"
            "**边界点**：自身邻域少于 MinPts，但落在某个核心点的 Eps 邻域内，"
            "只能被归入 cluster，不能继续扩展。\n"
            "**噪声点**：自身邻域少于 MinPts，且不在任何核心点的 Eps 邻域内。"
        ),
        evidence=[
            {
                "source_id": "dbscan-source",
                "source_version": "v1",
                "locator": "p.25",
                "supported_claim": (
                    "DBSCAN distinguishes core points, border points and noise points "
                    "using Eps neighborhoods and MinPts."
                ),
            }
        ],
        action="visual",
        language="zh-CN",
    )
    compiled = compile_visual_spec(spec)
    svg = compiled.deterministic_source

    assert spec.diagram is not None
    assert spec.diagram.dbscan is not None
    assert spec.must_include == ["Eps 邻域", "MinPts", "核心点", "边界点", "噪声点"]
    assert spec.exact_labels == []
    assert "DBSCAN 用 Eps 邻域" in spec.visual_goal
    assert 'data-renderer="dbscan-density"' in svg
    assert 'data-core-points="3"' in svg
    assert 'data-border-points="2"' in svg
    assert 'data-noise-points="1"' in svg
    assert "核心点" in svg
    assert "边界点" in svg
    assert "噪声点" in svg
    assert spec.aspect_ratio == "9:16"
    assert 'viewBox="0 0 360 640"' in svg
    assert compiled.width == 360
    assert compiled.height == 640
    assert "exact relationships" not in svg
    assert "main concept" not in svg.lower()
    validate_output(
        svg.encode(),
        mime_type="image/svg+xml",
        width=compiled.width,
        height=compiled.height,
        duration_seconds=None,
        max_bytes=2_000_000,
        max_width=2048,
        max_height=2048,
        max_duration_seconds=15,
    )


def test_dbscan_without_grounded_point_classes_does_not_generate() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question="Explain DBSCAN.",
        answer="DBSCAN is a clustering method.",
        evidence=[],
        action="diagram",
        language="en",
    )

    assert spec.should_generate is False
    assert spec.renderer is Renderer.NONE
    assert spec.diagram is None
    assert spec.must_include == []


def test_generic_diagram_labels_are_replaced_by_delivered_teaching_facts() -> None:
    planner = MockVisualPlannerProvider()
    spec = planner.plan(
        question="Explain the CPU pipeline stages.",
        answer=(
            "Instruction fetch reads the next instruction. Decode identifies the operation. "
            "Execute performs the operation in the ALU. Writeback stores the result."
        ),
        evidence=[],
        action="diagram",
        language="en",
    )
    compiled = compile_visual_spec(spec)

    assert spec.should_generate is True
    assert "exact relationships" not in spec.must_include
    assert any("Instruction fetch" in value for value in spec.must_include)
    assert "exact relationships" not in compiled.deterministic_source
