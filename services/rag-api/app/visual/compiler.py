from __future__ import annotations

import html
import json

from pydantic import BaseModel, ConfigDict, Field

from app.visual.spec import Renderer, VisualSpec


class Overlay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str
    anchor: str = "auto"


class CompiledVisual(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    renderer: Renderer
    positive_prompt: str = ""
    negative_prompt: str = ""
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=576, ge=256, le=2048)
    frames: int | None = None
    duration_seconds: float | None = None
    seed: int = 0
    steps: int = Field(default=20, ge=1, le=100)
    cfg: float = Field(default=8.0, ge=0.0, le=30.0)
    overlays: list[Overlay] = Field(default_factory=list)
    deterministic_source: str = ""


def _svg(spec: VisualSpec) -> str:
    diagram = spec.diagram
    if diagram is None:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="576"/>'
    node_width = 150
    node_height = 64
    positions: dict[str, tuple[float, float]] = {}
    count = len(diagram.nodes)
    for index, node in enumerate(diagram.nodes):
        x: float
        y: float
        if diagram.layout == "LEFT_RIGHT":
            x = 36 + (804 * index / max(1, count - 1))
            y = 250
        elif diagram.layout == "TOP_DOWN":
            x = 437
            y = 96 + (360 * index / max(1, count - 1))
        else:
            columns = min(4, max(1, count))
            row, column = divmod(index, columns)
            x = 36 + column * (900 / columns)
            y = 120 + row * 110
        positions[node.id] = (x, y)
    edges = []
    for edge in diagram.edges:
        from_x, from_y = positions[edge.from_id]
        to_x, to_y = positions[edge.to]
        x1, y1 = from_x + node_width / 2, from_y + node_height / 2
        x2, y2 = to_x + node_width / 2, to_y + node_height / 2
        edge_label = (
            f'<text x="{(x1 + x2) / 2:.0f}" y="{(y1 + y2) / 2 - 8:.0f}" '
            f'text-anchor="middle" font-family="sans-serif" font-size="14">'
            f"{html.escape(edge.label)}</text>"
            if edge.label
            else ""
        )
        edges.append(
            f'<g data-from="{html.escape(edge.from_id)}" data-to="{html.escape(edge.to)}">'
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
            'stroke="#52637a" stroke-width="2" marker-end="url(#arrow)"/>'
            f"{edge_label}</g>"
        )
    nodes = []
    for node in diagram.nodes:
        x, y = positions[node.id]
        nodes.append(
            f'<g id="{html.escape(node.id)}"><rect x="{x:.0f}" y="{y:.0f}" '
            f'width="{node_width}" height="{node_height}" rx="8" '
            'fill="#f5f7fa" stroke="#25324a"/>'
            f'<text x="{x + node_width / 2:.0f}" y="{y + node_height / 2 + 7:.0f}" '
            'text-anchor="middle" '
            f'font-family="sans-serif" font-size="20">{html.escape(node.label)}</text></g>'
        )
    labels = "".join(
        f'<text x="512" y="{40 + index * 24}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="16">{html.escape(value)}</text>'
        for index, value in enumerate(spec.exact_labels + spec.equations + spec.code_elements)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="576" '
        'viewBox="0 0 1024 576" role="img">'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#52637a"/></marker></defs>'
        f'<rect width="1024" height="576" fill="white"/>{labels}'
        f"{''.join(edges)}{''.join(nodes)}</svg>"
    )


def compile_visual_spec(spec: VisualSpec) -> CompiledVisual:
    exact = spec.exact_labels + spec.equations + spec.code_elements
    if spec.renderer in {Renderer.COMFY_IMAGE, Renderer.COMFY_VIDEO}:
        exact_set = set(exact)
        facts = [value for value in spec.must_include if value not in exact_set]
        positive = ", ".join(
            value
            for value in [spec.visual_goal, *facts, spec.style.composition, spec.style.camera]
            if value
        )
        return CompiledVisual(
            renderer=spec.renderer,
            positive_prompt=positive,
            negative_prompt=", ".join(spec.must_not_include),
            duration_seconds=spec.duration_seconds,
            frames=int(spec.duration_seconds * 8) if spec.duration_seconds else None,
            seed=int.from_bytes(spec.model_dump_json().encode()[:4].ljust(4, b"0"), "big"),
            overlays=[Overlay(text=value) for value in exact],
        )
    if spec.renderer is Renderer.NONE:
        return CompiledVisual(renderer=Renderer.NONE)
    if spec.renderer is Renderer.MANIM:
        source = json.dumps(
            {"steps": [step.model_dump() for step in spec.animation_steps], "overlays": exact},
            ensure_ascii=False,
            sort_keys=True,
        )
    elif spec.renderer in {Renderer.SVG, Renderer.DETERMINISTIC_DIAGRAM}:
        source = _svg(spec)
    else:
        source = json.dumps(
            spec.diagram.model_dump(by_alias=True) if spec.diagram else {}, sort_keys=True
        )
    return CompiledVisual(
        renderer=spec.renderer,
        deterministic_source=source,
        overlays=[Overlay(text=value) for value in exact],
    )
