from __future__ import annotations

import base64
import html
import json

from pydantic import BaseModel, ConfigDict, Field

from app.visual.media import wan_frames
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
    start_image_png_b64: str = Field(default="", max_length=4_000_000)
    end_image_png_b64: str = Field(default="", max_length=4_000_000)


def _bullet_lines(values: list[str]) -> str:
    return "\n".join(f"- {value.strip()}" for value in values if value.strip())


def _and_list(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else ""
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _compact_text(value: str, limit: int) -> str:
    """Normalize a renderer clause without letting one field dominate the prompt."""

    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip(" ,;:-") + "…"


def _compact_values(values: list[str], *, count: int, item_limit: int) -> list[str]:
    compacted: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _compact_text(value, item_limit)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        compacted.append(normalized)
        if len(compacted) == count:
            break
    return compacted


_STAGED_SEQUENCE_MARKERS = (
    "分段呈现",
    "分段展示",
    "分阶段",
    "先分别",
    "先展示",
    "再展示",
    "随后展示",
    "segmented presentation",
    "staged presentation",
    "then show",
    "then display",
    "first show",
)

_HDD_START_FRAME_MARKERS = (
    ("mechanical hard-disk drive body", "机械硬盘", "硬盘主体"),
    ("circular platter", "圆形盘片", "盘片"),
    ("actuator arm", "执行器臂"),
    ("read/write head", "read write head", "读写头", "读写磁头"),
)

_HDD_VIDEO_PROMPT = (
    "Single-shot 2D technical animation of one mechanical hard-disk cutaway. "
    "Locked overhead camera; the case, background and object identities stay fixed. "
    "The orange-marked black read/write head at the tip of the tan actuator arm must make "
    "a large unmistakable radial sweep: start on the outer track, move inward across at "
    "least half the platter radius toward the inner track and spindle, then return outward. "
    "do not leave it frozen; the arm pivots visibly and never detaches. Meanwhile the "
    "circular platter turns continuously around the fixed spindle, shown by its red radial "
    "stripe. Preserve the same drive, platter, spindle, arm, head and case in every frame. "
    "Smooth stable lighting, cool neutral technical illustration, no readable text."
)

_HDD_VIDEO_NEGATIVE_PROMPT = (
    "camera movement, zoom, pan, scene cut, montage, object morphing, extra or missing parts, "
    "frozen actuator arm, stationary read/write head, people, text, labels, watermark, sparks, "
    "damage, SSD, exact speed, seek time, data "
    "locations, manufacturing details, overexposure, white wash, black frame, flicker, "
    "color shift, blur"
)


def _contains_staged_sequence(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in _STAGED_SEQUENCE_MARKERS)


def _requires_hdd_start_frame(spec: VisualSpec) -> bool:
    required = " ".join(spec.must_include).casefold()
    return all(
        any(marker in required for marker in aliases)
        for aliases in _HDD_START_FRAME_MARKERS
    )


def _without_staged_sequence(value: str) -> str:
    """Remove delivery directions that would ask a single-shot video to become a montage."""

    normalized = " ".join(value.split())
    lowered = normalized.casefold()
    cut_at = min(
        (
            index
            for marker in _STAGED_SEQUENCE_MARKERS
            if (index := lowered.find(marker)) >= 0
        ),
        default=-1,
    )
    if cut_at < 0:
        return normalized
    prefix = normalized[:cut_at]
    boundary = max(prefix.rfind(mark) for mark in ("，", ",", "；", ";", "。", "."))
    if boundary >= 0:
        prefix = prefix[:boundary]
    return prefix.strip(" ,，;；.。")


def asset_alt_text(spec: VisualSpec) -> str:
    """Return a user-facing description that matches the renderer contract."""

    if spec.renderer is not Renderer.COMFY_VIDEO:
        return spec.visual_goal.strip()
    summary = _without_staged_sequence(spec.visual_goal)
    if not summary:
        labels = [step.label.strip() for step in spec.animation_steps if step.label.strip()]
        summary = "；".join(labels) or "Single continuous teaching animation."
    return _compact_text(summary, 320)


def _video_generative_prompt(spec: VisualSpec, exact: list[str]) -> str:
    """Compile a short, single-shot video contract for the pinned Wan workflow.

    Course grounding is retained in the validated VisualSpec and source receipts. It is
    not copied wholesale into the generative prompt: Wan needs one observable scene and
    one continuous action, while long audit text and staged prose make the renderer drift.
    """

    exact_set = set(exact)
    required = _compact_values(
        [
            value
            for value in spec.must_include
            if value not in exact_set and not _contains_staged_sequence(value)
        ],
        count=5,
        item_limit=120,
    )
    forbidden = _compact_values(spec.must_not_include, count=6, item_limit=90)
    stage_labels = [
        _compact_text(step.label, 140)
        for step in spec.animation_steps
        if step.label.strip()
    ]
    initial_state = (
        stage_labels[0]
        if stage_labels
        else (
            "All required teaching objects are already visible in one fixed view."
        )
    )
    final_state = (
        stage_labels[-1]
        if len(stage_labels) >= 2
        else (
            f"Preserve {_and_list(required)} at the end while the teaching relationship "
            "is established."
            if required
            else "Keep every object visible and preserve the same physical scene."
        )
    )
    main_action = _compact_text(_without_staged_sequence(spec.visual_goal), 320)
    if not main_action or main_action.casefold() in {
        "show the supported concept.",
        "show the supported relationship.",
    }:
        main_action = (
            stage_labels[1]
            if len(stage_labels) >= 2
            else "Show one slow, continuous, physically plausible change."
        )
    elif not any(
        cue in main_action.casefold()
        for cue in (
            "rotate",
            "rotating",
            "move",
            "moving",
            "sweep",
            "flow",
            "bud",
            "fuse",
            "change",
            "旋转",
            "移动",
            "运动",
            "变化",
        )
    ) and len(stage_labels) >= 2:
        main_action = stage_labels[1]
    view = _compact_text(
        " ".join(value for value in (spec.style.camera, spec.style.composition) if value),
        240,
    )
    background = _compact_text(
        " ".join(
            value for value in (spec.style.background, spec.style.color_guidance) if value
        ),
        140,
    )
    learning_objective = _compact_text(spec.pedagogical_reason, 160)

    return "\n\n".join(
        [
            (
                "Create one short educational video as a single continuous shot. "
                "Use one fixed camera and one physical scene. Fill the frame with the "
                "teaching subject and preserve the same object identities throughout."
            ),
            f"Main action:\n{main_action}",
            (
                "Motion contract:\n"
                f"Initial state:\n{initial_state}\n"
                f"Final state:\n{final_state}"
            ),
            "Fixed objects:\n" + (_bullet_lines(required) or "- required teaching objects"),
            (
                "Camera and continuity:\n"
                f"{view or 'locked medium-wide teaching view'}. One unbroken shot; no camera cuts, "
                "no montage, no scene changes, no additional teaching actions, "
                "no object morphing or "
                "unexplained disappearance."
            ),
            (
                f"Lighting and background:\n"
                f"{background or 'even neutral lighting with a clean background'}"
            ),
            "Forbidden elements:\n" + (_bullet_lines(forbidden) or "- unsupported facts"),
            f"Learning objective:\n{learning_objective}",
        ]
    )


def _generative_prompt(spec: VisualSpec, exact: list[str]) -> str:
    """Build a teaching prompt from the existing grounded VisualSpec fields."""

    if spec.renderer is Renderer.COMFY_VIDEO:
        return _video_generative_prompt(spec, exact)

    exact_set = set(exact)
    required = list(dict.fromkeys(value for value in spec.must_include if value not in exact_set))
    relationships = list(
        dict.fromkeys(
            source.supported_claim
            for source in spec.source_grounding
            if source.supported_claim and source.supported_claim not in exact_set
        )
    )
    view = " ".join(value for value in (spec.style.camera, spec.style.composition) if value)
    background = " ".join(
        value for value in (spec.style.background, spec.style.color_guidance) if value
    )
    if spec.renderer is Renderer.COMFY_VIDEO:
        subject_kind = "educational video"
    elif spec.style.tone == "REALISTIC":
        subject_kind = "clean educational product photograph"
    else:
        subject_kind = "textbook scientific illustration"
    photographic = spec.renderer is Renderer.COMFY_IMAGE and spec.style.tone == "REALISTIC"
    generation_contract = (
        "Generation contract:\n"
        f"Create one large, edge-to-edge {subject_kind}. "
        "This is an unannotated product photograph. Fill the frame with "
        "only the physical teaching subject. Show only visible objects, surfaces, materials, "
        "positions and proportions. This must remain a photograph, not an infographic, diagram "
        "or annotated explainer. Do not render any letters, words, numbers, labels, legends, "
        "captions, callouts, arrows, leader lines, annotation circles, overlay cards, watermark "
        "or pseudo-text; gibberish typography or graphic overlays are a failed result."
        if photographic
        else "Generation contract:\n"
        f"Create one large, edge-to-edge {subject_kind}. Fill the frame with "
        "the teaching subject. Use only visible objects, surfaces, positions, proportions, "
        "colors and unlabeled motion/relationship arrows. Do not render any letters, words, "
        "numbers, labels, legends, captions, callouts, watermark or pseudo-text; gibberish "
        "typography is a failed result."
    )
    sections = [
        generation_contract,
        f"Subject:\n{spec.visual_goal.strip()}",
        "Required elements:\n"
        + (_bullet_lines(required) or "- Keep only the course-grounded subject."),
        (
            "Visible physical arrangement and course facts:\n"
            if photographic
            else "Spatial relationships and course facts:\n"
        )
        + (_bullet_lines(relationships) or "- Preserve the relationships stated by the subject."),
        f"View and composition:\n{view or 'one clear, unobstructed teaching view'}",
        "Lighting and background:\n"
        f"{background or 'even, neutral lighting with a clean observable background'}",
        "Forbidden elements:\n" + (_bullet_lines(spec.must_not_include) or "- unsupported facts"),
        f"Educational purpose:\n{spec.pedagogical_reason.strip()}",
    ]
    if spec.renderer is Renderer.COMFY_VIDEO:
        stage_labels = [step.label.strip() for step in spec.animation_steps if step.label.strip()]
        fixed = [value for value in required if value]
        if len(stage_labels) >= 2:
            initial_state = stage_labels[0]
            main_action = " Then ".join(stage_labels[1:-1]) or stage_labels[1]
            final_state = stage_labels[-1]
        elif len(stage_labels) == 1:
            initial_state = stage_labels[0]
            main_action = spec.visual_goal.strip()
            final_state = (
                f"Preserve {_and_list(fixed)} at the end while the course relationship "
                "is established."
                if fixed
                else "Preserve the same object identities and course relationship at the end."
            )
        else:
            initial_state = (
                "Begin with the required objects already visible and separated in the frame: "
                f"{', '.join(fixed)}."
                if fixed
                else "Begin with every required teaching object already visible in one frame."
            )
            main_action = spec.visual_goal.strip()
            final_state = (
                f"Preserve {_and_list(fixed)} at the end while the course relationship "
                "is established."
                if fixed
                else "Preserve the same object identities and course relationship at the end."
            )
        camera = " ".join(value for value in (spec.style.camera, spec.style.composition) if value)
        sections.append(
            "Video teaching contract:\n"
            f"Initial state:\n{initial_state}\n\n"
            f"Main action:\n{main_action}\n\n"
            f"Final state:\n{final_state}\n\n"
            "Fixed objects:\n"
            f"{_bullet_lines(fixed) or '- Preserve the required teaching objects throughout.'}\n\n"
            "Camera and continuity:\n"
            f"{camera or 'fixed teaching view'}. Use a locked fixed camera in a single continuous "
            "shot. Preserve object identity, scale, relative position and background continuity "
            "from first frame to last frame.\n\n"
            "Forbidden motion:\n"
            "- no montage\n"
            "- no camera cuts\n"
            "- no scene changes\n"
            "- no additional teaching actions\n"
            "- no object morphing or unexplained disappearance\n\n"
            f"Learning objective:\n{spec.pedagogical_reason.strip()}"
        )
    return "\n\n".join(sections)


def _svg(spec: VisualSpec) -> str:
    diagram = spec.diagram
    if diagram is not None and diagram.hdd_kinematics is not None:
        from app.visual.hdd_motion import render

        return render(spec.language)
    if diagram is not None and diagram.kmeans is not None:
        from app.visual.kmeans import render

        return render(diagram.kmeans, spec.language)
    if diagram is not None and diagram.phospholipid_bilayer is not None:
        from app.visual.membrane import render

        return render(spec.language)
    if diagram is not None and diagram.dbscan is not None:
        from app.visual.dbscan import render

        return render(spec.language)
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
        hdd_video = spec.renderer is Renderer.COMFY_VIDEO and _requires_hdd_start_frame(spec)
        positive = _HDD_VIDEO_PROMPT if hdd_video else _generative_prompt(spec, exact)
        start_image_png_b64 = ""
        end_image_png_b64 = ""
        if hdd_video:
            from app.visual.hdd_motion import render_start_frame_png

            start_image_png_b64 = base64.b64encode(
                render_start_frame_png(width=1280, height=704)
            ).decode("ascii")
        return CompiledVisual(
            renderer=spec.renderer,
            positive_prompt=positive,
            # The pinned FLUX workflow zeroes its negative conditioning, so keeping
            # must-not-include facts only in the positive prompt is truthful.
            negative_prompt=(
                _HDD_VIDEO_NEGATIVE_PROMPT
                if hdd_video
                else (
                    ", ".join(spec.must_not_include)
                    if spec.renderer is Renderer.COMFY_VIDEO
                    else ""
                )
            ),
            duration_seconds=spec.duration_seconds,
            frames=wan_frames(spec.duration_seconds)
            if spec.renderer is Renderer.COMFY_VIDEO and spec.duration_seconds
            else None,
            width=1280 if spec.renderer is Renderer.COMFY_VIDEO else 1024,
            height=704 if spec.renderer is Renderer.COMFY_VIDEO else 576,
            cfg=4.0 if hdd_video else (5 if spec.renderer is Renderer.COMFY_VIDEO else 1),
            steps=40 if hdd_video else (20 if spec.renderer is Renderer.COMFY_VIDEO else 4),
            seed=int.from_bytes(spec.model_dump_json().encode()[:4].ljust(4, b"0"), "big"),
            overlays=[Overlay(text=value) for value in exact],
            start_image_png_b64=start_image_png_b64,
            end_image_png_b64=end_image_png_b64,
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
        width=(
            720
            if spec.diagram and spec.diagram.phospholipid_bilayer
            else 720
            if spec.diagram and spec.diagram.hdd_kinematics
            else 360
            if spec.diagram and spec.diagram.dbscan
            else 340
            if spec.diagram and spec.diagram.kmeans
            else 1024
        ),
        height=(
            720
            if spec.diagram and spec.diagram.phospholipid_bilayer
            else 720
            if spec.diagram and spec.diagram.hdd_kinematics
            else 640
            if spec.diagram and spec.diagram.dbscan
            else 510
            if spec.diagram and spec.diagram.kmeans
            else 576
        ),
        deterministic_source=source,
        overlays=[Overlay(text=value) for value in exact],
    )
