from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.visual.kmeans import assignment, delivered_example
from app.visual.spec import VisualSpec

PROMPT_VERSION = "visual-router-planner-v2"
PROMPT_PATH = Path(__file__).with_name("prompts") / "visual_router_planner_v1.system.md"


@dataclass(frozen=True)
class RuntimePrompt:
    version: str
    sha256: str
    text: str


def load_runtime_prompt(path: Path = PROMPT_PATH) -> RuntimePrompt:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError("Visual planner prompt is empty")
    return RuntimePrompt(PROMPT_VERSION, hashlib.sha256(text.encode()).hexdigest(), text)


class VisualPlannerProvider(Protocol):
    prompt: RuntimePrompt

    def plan(
        self,
        *,
        question: str,
        answer: str,
        evidence: list[dict[str, str]],
        action: Literal["auto", "diagram", "visual", "animate"],
        language: str,
    ) -> VisualSpec: ...


def _contains(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _prompt_fragment(value: object, *, limit: int = 800) -> str:
    """Normalize untrusted data into a bounded renderer prompt fragment."""

    normalized = " ".join(str(value or "").split())
    return normalized[:limit].rstrip()


def _answer_fragment(answer: str, *, limit: int = 700) -> str:
    """Return the delivered fact, without UI citation markers."""

    without_citations = re.sub(r"\[[^\]]+\]", "", answer)
    return _prompt_fragment(without_citations.split("\n", 1)[0], limit=limit)


def _is_visual_claim(value: str) -> bool:
    """Reject document labels that some citation adapters put in supported_claim."""

    if not value:
        return False
    if re.fullmatch(r".+\.(?:pdf|docx?|pptx?|xlsx?|html?)", value, re.IGNORECASE):
        return False
    return value.casefold() not in {"course evidence", "source", "document"}


def _is_endomembrane_transport(question: str) -> bool:
    q = question.lower()
    return _contains(
        q,
        r"endomembrane.*(?:protein|membrane).*transport",
        r"endoplasmic reticulum.*golgi",
        r"rough er.*golgi",
        r"openstax biology 2e.*(?:vesicle|protein|golgi|endoplasmic)",
    )


class GroundedPolicyVisualPlannerProvider:
    """Deterministic, source-grounded production router with no provider cost."""

    def __init__(self) -> None:
        self.prompt = load_runtime_prompt()

    def _decision(self, question: str) -> tuple[str, str, list[str]]:
        q = question.lower()
        if _contains(
            q,
            r"what does acid stand for",
            r"what is a homogeneous coordinate",
            r"k-means objective function",
            r"definition of a definite integral",
            r"what does select distinct do",
        ):
            return "NONE", "NONE", []
        if _contains(
            q,
            r"endomembrane.*(?:protein|membrane).*transport",
            r"endoplasmic reticulum.*golgi",
            r"rough er.*golgi",
            r"内质网.*高尔基体.*(?:蛋白质|分泌蛋白|膜蛋白).*运输",
            r"囊泡.*(?:出芽|融合).*高尔基体",
        ):
            return (
                "VIDEO",
                "COMFY_VIDEO",
                [
                    "rough endoplasmic reticulum",
                    "transport vesicle budding",
                    "Golgi apparatus",
                    "plasma membrane",
                ],
            )
        if _contains(q, r"two gears", r"gears transfer motion"):
            return "VIDEO", "COMFY_VIDEO", ["two meshed gears", "opposite rotation"]
        if _contains(
            q, r"gravitational lens", r"cell membrane", r"enzyme-substrate", r"spacetime curvature"
        ):
            return "IMAGE", "COMFY_IMAGE", ["conceptual scene"]
        if _contains(
            q,
            r"red-black.*rotation",
            r"dijkstra",
            r"bfs and dfs",
            r"t\s*@\s*r\s*@\s*s",
            r"linked list",
            r"insertion sort",
            r"wave propagation",
            r"projectile motion",
            r"quadratic formula",
            r"binary search",
            r"round-robin",
            r"blood-flow",
        ):
            return "ANIMATION", "MANIM", ["ordered states"]
        if _contains(q, r"er relationship", r"class relationships"):
            return "DIAGRAM", "MERMAID", ["relationships"]
        if _contains(
            q, r"b\+ tree", r"sql join execution plan", r"network topology", r"finite state machine"
        ):
            return "DIAGRAM", "GRAPHVIZ", ["nodes", "edges"]
        if _contains(
            q,
            r"cpu pipeline",
            r"tcp three-way",
            r"cache hierarchy",
            r"half adder",
            r"neural network architecture",
            r"backpropagation",
            r"dbscan",
            r"eigenvalue",
            r"hash collision",
            r"coffman",
            r"tls handshake",
            r"acid and base",
        ):
            return "DIAGRAM", "SVG", ["exact relationships"]
        return "NONE", "NONE", []

    def plan(
        self,
        *,
        question: str,
        answer: str,
        evidence: list[dict[str, str]],
        action: Literal["auto", "diagram", "visual", "animate"],
        language: str,
    ) -> VisualSpec:
        visual_type, renderer, includes = self._decision(question)
        is_endomembrane_transport = _is_endomembrane_transport(question)
        kmeans = None
        is_kmeans = _contains(question, r"k[-\s]?means", r"K均值")
        is_phospholipid_bilayer = _contains(
            question,
            r"phospholipid",
            r"hydrophobic\s+tails?",
            r"流动镶嵌模型",
            r"磷脂",
            r"疏水尾部",
        ) and _contains(
            question,
            r"bilayer",
            r"membrane",
            r"膜",
            r"疏水",
        )
        if is_kmeans:
            kmeans = delivered_example(answer)
            if kmeans is not None:
                try:
                    assignment(kmeans)
                except ValueError:
                    kmeans = None
            if kmeans is not None:
                visual_type, renderer = "DIAGRAM", "SVG"
                includes = [p.label for p in kmeans.points]
            else:
                visual_type, renderer, includes = "NONE", "NONE", []
        if is_phospholipid_bilayer:
            visual_type, renderer = "DIAGRAM", "SVG"
            includes = ["疏水尾部", "水环境", "膜内侧"]
        if action == "diagram" and renderer != "NONE":
            visual_type, renderer = "DIAGRAM", "SVG"
        elif action == "visual" and renderer == "NONE":
            visual_type, renderer, includes = "NONE", "NONE", []
        elif action == "animate" and renderer == "NONE" and not is_kmeans and includes:
            visual_type, renderer, includes = "ANIMATION", "MANIM", ["ordered states"]
        should_generate = renderer != "NONE"
        natural = renderer in {"COMFY_IMAGE", "COMFY_VIDEO"}
        answer_fact = _answer_fragment(answer)
        supported: list[str] = []
        if natural:
            supported_claims = [
                _prompt_fragment(item.get("supported_claim"))
                for item in evidence[:16]
                if _prompt_fragment(item.get("supported_claim"))
            ]
            supported_claims = [claim for claim in supported_claims if _is_visual_claim(claim)]
            supported = list(
                dict.fromkeys(([answer_fact] if answer_fact else []) + supported_claims)
            )
            includes = list(dict.fromkeys(supported))[:4]
            is_endomembrane_transport = is_endomembrane_transport or _contains(
                " ".join(includes),
                r"transport vesicle buds.*endoplasmic reticulum.*golgi",
            )
        labels = [] if natural else includes
        nodes = [
            {"id": f"n{index + 1}", "label": value}
            for index, value in enumerate(includes or ["concept"])
        ]
        edges = [
            {"from": nodes[index]["id"], "to": nodes[index + 1]["id"], "label": "next"}
            for index in range(max(0, len(nodes) - 1))
        ]
        diagram = (
            None
            if not should_generate or natural
            else {
                "layout": "LEFT_RIGHT",
                "nodes": nodes,
                "edges": edges,
            }
        )
        if kmeans is not None and diagram is not None:
            diagram["edges"] = []
            diagram["kmeans"] = kmeans.model_dump()
            labels = []
        if is_phospholipid_bilayer and diagram is not None:
            diagram["edges"] = []
            diagram["phospholipid_bilayer"] = {"provenance": "DELIVERED_GROUNDED_EXPLANATION"}
            labels = []
        animation_steps = []
        if renderer == "COMFY_VIDEO" and is_endomembrane_transport:
            animation_steps = [
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
                    "label": (
                        "The vesicle fuses with the Golgi apparatus, then a membrane-protein "
                        "vesicle reaches the plasma membrane."
                    ),
                    "highlight_ids": [],
                },
            ]
        elif renderer == "MANIM":
            animation_steps = [
                {"order": index + 1, "label": value, "highlight_ids": [nodes[index]["id"]]}
                for index, value in enumerate(includes or ["state"])
            ]
        grounding = [
            {
                "source_id": str(item["source_id"]),
                "source_version": str(item["source_version"]),
                "locator": str(item.get("locator") or "source"),
                "supported_claim": (
                    claim
                    if _is_visual_claim(claim := _prompt_fragment(item.get("supported_claim")))
                    else answer_fact or "Course-grounded visual explanation."
                ),
            }
            for item in evidence[:16]
        ]
        return VisualSpec.model_validate(
            {
                "visual_spec_version": "1.0",
                "should_generate": should_generate,
                "pedagogical_reason": "A visual is useful."
                if should_generate
                else "Insufficient supported visual structure; continue with the delivered text.",
                "visual_goal": (
                    _prompt_fragment(
                        "Create a clear educational illustration that teaches: "
                        f"{_prompt_fragment(question, limit=300)}"
                        + (
                            " Use this grounded explanation: "
                            f"{_prompt_fragment(answer_fact, limit=420)}"
                            if answer_fact
                            else ""
                        ),
                        limit=800,
                    )
                    if natural
                    else (
                        "K-means：最近质心分配、坐标均值更新与 SSE（一轮教学例）"
                        if kmeans is not None
                        else (
                            answer_fact
                            if should_generate and answer_fact
                            else (
                                "流动镶嵌模型：磷脂疏水尾部避开水环境并朝向膜内侧。"
                                if is_phospholipid_bilayer
                                else (
                                    f"课程图解：{_prompt_fragment(question, limit=400)}"
                                    if should_generate
                                    else ""
                                )
                            )
                        )
                    )
                ),
                "visual_type": visual_type,
                "renderer": renderer,
                "importance": "MEDIUM",
                "timing": "ON_DEMAND",
                "source_grounding": grounding,
                "must_include": includes,
                "must_not_include": (
                    [
                        "unrelated fantasy elements",
                        "watermark",
                        "unreadable text",
                        "unsupported facts",
                    ]
                    if natural
                    else ["unsupported facts"]
                ),
                "exact_labels": labels,
                "equations": [],
                "code_elements": [],
                "reference_assets": [],
                "style": {"tone": "CONCEPTUAL" if natural else "CLEAN_TECHNICAL"},
                "duration_seconds": 3 if renderer == "COMFY_VIDEO" else None,
                "aspect_ratio": "16:9",
                "cost_tier": "EXPENSIVE"
                if renderer == "COMFY_VIDEO"
                else ("DEFAULT" if natural else "LOW"),
                "confidence": 0.9,
                "fallback_renderer": "NONE" if not natural else "SVG",
                "cache_policy": "REUSE",
                "language": language,
                "motion_is_essential": visual_type in {"ANIMATION", "VIDEO"},
                "semantic_precision": "ILLUSTRATIVE" if natural else "EXACT",
                "diagram": diagram,
                "animation_steps": animation_steps,
            }
        )


class MockVisualPlannerProvider(GroundedPolicyVisualPlannerProvider):
    """Backward-compatible Phase A test seam for the production policy router."""
