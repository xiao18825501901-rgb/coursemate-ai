from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.visual.spec import VisualSpec

PROMPT_VERSION = "visual-router-planner-v1"
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


class MockVisualPlannerProvider:
    """Deterministic no-network planner used by Phase A and its 40-case gate."""

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
        return "DIAGRAM", "SVG", ["main concept"]

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
        if action == "diagram":
            visual_type, renderer = "DIAGRAM", "SVG"
        elif action == "visual" and renderer == "NONE":
            visual_type, renderer, includes = "IMAGE", "COMFY_IMAGE", ["main concept"]
        elif action == "animate" and renderer == "NONE":
            visual_type, renderer, includes = "ANIMATION", "MANIM", ["ordered states"]
        should_generate = renderer != "NONE"
        natural = renderer in {"COMFY_IMAGE", "COMFY_VIDEO"}
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
        animation_steps = []
        if renderer == "MANIM":
            animation_steps = [
                {"order": index + 1, "label": value, "highlight_ids": [nodes[index]["id"]]}
                for index, value in enumerate(includes or ["state"])
            ]
        grounding = [
            {
                "source_id": str(item["source_id"]),
                "source_version": str(item["source_version"]),
                "locator": str(item.get("locator") or "source"),
                "supported_claim": str(item.get("supported_claim") or "Course evidence."),
            }
            for item in evidence[:16]
        ]
        return VisualSpec.model_validate(
            {
                "visual_spec_version": "1.0",
                "should_generate": should_generate,
                "pedagogical_reason": "A visual is useful."
                if should_generate
                else "The answer is clearer as text.",
                "visual_goal": "Show the supported concept." if should_generate else "",
                "visual_type": visual_type,
                "renderer": renderer,
                "importance": "MEDIUM",
                "timing": "ON_DEMAND",
                "source_grounding": grounding,
                "must_include": includes,
                "must_not_include": ["unsupported facts"],
                "exact_labels": labels,
                "equations": [],
                "code_elements": [],
                "reference_assets": [],
                "style": {"tone": "CONCEPTUAL" if natural else "CLEAN_TECHNICAL"},
                "duration_seconds": 6 if renderer == "COMFY_VIDEO" else None,
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
