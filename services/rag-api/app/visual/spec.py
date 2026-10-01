from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
FactText = Annotated[str, Field(min_length=1, max_length=800)]
CodeText = Annotated[str, Field(min_length=1, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisualType(StrEnum):
    NONE = "NONE"
    DIAGRAM = "DIAGRAM"
    ANIMATION = "ANIMATION"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


class Renderer(StrEnum):
    NONE = "NONE"
    DETERMINISTIC_DIAGRAM = "DETERMINISTIC_DIAGRAM"
    SVG = "SVG"
    MERMAID = "MERMAID"
    GRAPHVIZ = "GRAPHVIZ"
    MANIM = "MANIM"
    COMFY_IMAGE = "COMFY_IMAGE"
    COMFY_VIDEO = "COMFY_VIDEO"


class SourceGrounding(StrictModel):
    source_id: str = Field(min_length=1, max_length=200)
    source_version: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=500)
    supported_claim: str = Field(min_length=1, max_length=800)


class ReferenceAsset(StrictModel):
    asset_id: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=300)


class VisualStyle(StrictModel):
    tone: Literal["TEXTBOOK", "CLEAN_TECHNICAL", "CONCEPTUAL", "REALISTIC", "MINIMAL"]
    background: str = Field(default="", max_length=200)
    composition: str = Field(default="", max_length=500)
    camera: str = Field(default="", max_length=300)
    color_guidance: str = Field(default="", max_length=300)


class DiagramNode(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    label: ShortText
    kind: str = Field(default="concept", max_length=80)
    group: str | None = Field(default=None, max_length=80)


class DiagramEdge(StrictModel):
    from_id: str = Field(alias="from", serialization_alias="from", pattern=r"^[A-Za-z0-9_-]{1,80}$")
    to: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    label: str | None = Field(default=None, max_length=200)
    kind: str = Field(default="relationship", max_length=80)


class Diagram(StrictModel):
    layout: Literal["AUTO", "LEFT_RIGHT", "TOP_DOWN", "RADIAL", "TIMELINE", "COORDINATE"]
    nodes: list[DiagramNode] = Field(max_length=60)
    edges: list[DiagramEdge] = Field(max_length=120)


class AnimationStep(StrictModel):
    order: int = Field(ge=1, le=100)
    label: str = Field(min_length=1, max_length=300)
    highlight_ids: list[str] = Field(max_length=30)

    @model_validator(mode="after")
    def validate_highlights(self) -> AnimationStep:
        for value in self.highlight_ids:
            if (
                not value
                or len(value) > 80
                or not value.replace("_", "").replace("-", "").isalnum()
            ):
                raise ValueError("animation highlight IDs must be opaque safe identifiers")
        return self


class VisualSpec(StrictModel):
    visual_spec_version: Literal["1.0"]
    should_generate: bool
    pedagogical_reason: str = Field(min_length=1, max_length=1200)
    visual_goal: str = Field(max_length=1200)
    visual_type: VisualType
    renderer: Renderer
    importance: Literal["LOW", "MEDIUM", "HIGH"]
    timing: Literal["INLINE", "ON_DEMAND"]
    source_grounding: list[SourceGrounding] = Field(max_length=16)
    must_include: list[FactText] = Field(max_length=32)
    must_not_include: list[FactText] = Field(max_length=32)
    exact_labels: list[ShortText] = Field(max_length=40)
    equations: list[CodeText] = Field(max_length=20)
    code_elements: list[CodeText] = Field(max_length=20)
    reference_assets: list[ReferenceAsset] = Field(max_length=8)
    style: VisualStyle
    duration_seconds: float | None = Field(ge=0.5, le=15)
    aspect_ratio: Literal["16:9", "4:3", "1:1", "9:16"]
    cost_tier: Literal["FREE", "LOW", "DEFAULT", "EXPENSIVE"]
    confidence: float = Field(ge=0, le=1)
    fallback_renderer: Literal[
        "NONE", "DETERMINISTIC_DIAGRAM", "SVG", "MERMAID", "GRAPHVIZ", "MANIM"
    ]
    cache_policy: Literal["REUSE", "REGENERATE", "NO_CACHE"]
    language: str = Field(min_length=2, max_length=20)
    motion_is_essential: bool
    semantic_precision: Literal["EXACT", "BOUNDED", "ILLUSTRATIVE"]
    diagram: Diagram | None
    animation_steps: list[AnimationStep] = Field(max_length=40)

    @model_validator(mode="after")
    def semantic_contract(self) -> VisualSpec:
        if not self.should_generate:
            if self.visual_type is not VisualType.NONE or self.renderer is not Renderer.NONE:
                raise ValueError("non-generated specs must use NONE type and renderer")
        elif self.visual_type is VisualType.NONE or self.renderer is Renderer.NONE:
            raise ValueError("generated specs require a concrete type and renderer")
        if self.visual_type is VisualType.VIDEO and not self.motion_is_essential:
            raise ValueError("video requires essential motion")
        if self.renderer is Renderer.COMFY_VIDEO and (
            self.visual_type is not VisualType.VIDEO or self.duration_seconds is None
        ):
            raise ValueError("COMFY_VIDEO requires a bounded video duration")
        if (
            self.renderer in {Renderer.COMFY_IMAGE, Renderer.COMFY_VIDEO}
            and self.semantic_precision == "EXACT"
        ):
            raise ValueError("generative renderers cannot own exact semantics")
        if (
            self.renderer
            in {
                Renderer.DETERMINISTIC_DIAGRAM,
                Renderer.SVG,
                Renderer.MERMAID,
                Renderer.GRAPHVIZ,
            }
            and self.semantic_precision == "ILLUSTRATIVE"
        ):
            raise ValueError("deterministic diagrams require exact or bounded semantics")
        if self.diagram is not None:
            ids = [node.id for node in self.diagram.nodes]
            if len(ids) != len(set(ids)):
                raise ValueError("diagram node IDs must be unique")
            known = set(ids)
            for edge in self.diagram.edges:
                if edge.from_id not in known or edge.to not in known:
                    raise ValueError("diagram edges must reference existing nodes")
        orders = [step.order for step in self.animation_steps]
        if len(orders) != len(set(orders)) or orders != sorted(orders):
            raise ValueError("animation step order must be unique and increasing")
        if self.diagram is not None:
            known = {node.id for node in self.diagram.nodes}
            if any(set(step.highlight_ids) - known for step in self.animation_steps):
                raise ValueError("animation highlights must reference diagram nodes")
        return self


def validate_source_grounding(
    spec: VisualSpec,
    allowed: set[tuple[str, str]],
    allowed_reference_assets: set[str] | None = None,
) -> None:
    for source in spec.source_grounding:
        if (source.source_id, source.source_version) not in allowed:
            raise ValueError("VisualSpec source grounding is not present in the frozen evidence")
    permitted_assets = allowed_reference_assets or set()
    if any(asset.asset_id not in permitted_assets for asset in spec.reference_assets):
        raise ValueError("VisualSpec reference asset is not present in the authorized frozen input")
