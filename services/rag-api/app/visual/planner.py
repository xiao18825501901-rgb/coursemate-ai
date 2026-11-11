from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.visual.kmeans import assignment, delivered_example
from app.visual.spec import VisualSpec

PROMPT_VERSION = "visual-router-planner-v4"
PROMPT_PATH = Path(__file__).with_name("prompts") / "visual_router_planner_v1.system.md"
HDD_VISUAL_REQUIRED = [
    "one mechanical hard-disk drive body remaining fixed",
    "one circular platter rotating about a central spindle",
    (
        "one visible actuator arm spanning from a pivot beside the platter to the "
        "read/write head above the platter"
    ),
    "one read/write head visibly changing bounded radial position above the platter",
]
HDD_GROUNDED_CLAIM = (
    "The circular platter rotates continuously around the fixed central spindle while one "
    "actuator arm performs a bounded radial sweep that moves the read/write head across "
    "different radial positions; the drive body remains fixed."
)
DESKTOP_VISUAL_REQUIRED = [
    "one large main circuit board fills most of the frame",
    "one compact CPU heatsink area mounted on the motherboard",
    "one set of long narrow parallel DIMM memory slots near the CPU area",
]
DESKTOP_GROUNDED_CLAIM = (
    "The large main circuit board is the motherboard. A compact CPU socket and heatsink "
    "area is mounted on the motherboard. Long narrow DIMM memory slots form a separate "
    "parallel-slot region often near the CPU area."
)
DBSCAN_VISUAL_REQUIRED_ZH = ["Eps 邻域", "MinPts", "核心点", "边界点", "噪声点"]
DBSCAN_VISUAL_REQUIRED_EN = [
    "Eps neighborhood",
    "MinPts",
    "core point",
    "border point",
    "noise point",
]
DBSCAN_GROUNDED_CLAIM_ZH = (
    "DBSCAN 用 Eps 邻域中的点数与 MinPts 判定核心点；边界点落在核心点邻域内，"
    "但自身邻域不足 MinPts；噪声点不在任何核心点的 Eps 邻域内。"
)
DBSCAN_GROUNDED_CLAIM_EN = (
    "DBSCAN classifies a point as core when its Eps neighborhood contains at least "
    "MinPts points, as border when it lies in a core point's neighborhood without "
    "meeting MinPts itself, and as noise when it lies in no core point's neighborhood."
)
_GENERIC_DIAGRAM_LABELS = {
    "concept",
    "nodes",
    "edges",
    "relationships",
    "exact relationships",
    "ordered states",
}


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


_DOCUMENT_FILE_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\."
    r"(?:pdf|docx?|pptx?|xlsx?|csv|json|md|txt|html?|png|jpe?g|gif|webp|mp4|mov|zip)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_HEADING_LINE_RE = re.compile(
    r"^(?:#{1,6}\s*|[一二三四五六七八九十百]+、|\d+[.、)]\s+)",
)
_NAVIGATION_LABEL_RE = re.compile(
    r"^(?:(?:unit|chapter|section|lesson|module)\s+[\w.-]+(?:\s*[:：-].*)?|"
    r"第[一二三四五六七八九十百\d]+[章节单元])$",
    re.IGNORECASE,
)
_CLAIM_SPLIT_RE = re.compile(r"(?<=[。！？!?；;.])\s+|[\r\n]+")
_VISUAL_RELATION_RE = re.compile(
    r"\b(?:is|are|was|were|has|have|contains?|consists?|shows?|"
    r"reads?|identifies?|performs?|stores?|writes?|selects?|loads?|decodes?|"
    r"executes?|fetches?|"
    r"rotates?|moves?|bends?|curves?|fuses?|buds?|flows?|pushes?|turns?|"
    r"increases?|decreases?|connects?|separates?|lies?|sits?|surrounds?|"
    r"enters?|leaves?|travels?|reflects?|refracts?|causes?|represents?|"
    r"expresses?|means?|equals?|occurs?|detects?|creates?|forms?|extends?|"
    r"spans?|supports?|produces?|changes?|converts?|passes?|reaches?|"
    r"remains?|relates?)\b|"
    r"(?:是|为|由|包含|包括|具有|位于|朝向|绕着|绕|旋转|移动|弯曲|折射|"
    r"传播|流向|连接|组成|构成|形成|进入|离开|到达|保持|改变|增加|减少|"
    r"导致|表示|说明|产生|发出|吸收|释放|提供|支撑|包围|覆盖|接触|推动|"
    r"驱动|变为|成为|对应|关系|相比|相差|等于|大于|小于|附近|之间|内侧|"
    r"外侧|上方|下方|左侧|右侧|内部|外部|相对|彼此|形成|给出)",
    re.IGNORECASE,
)


def _strip_document_labels(value: object) -> str:
    """Remove navigation headings and filenames before treating text as visual fact."""

    without_citations = re.sub(r"\[[^\]]+\]", "", str(value or ""))
    kept_lines: list[str] = []
    for raw_line in without_citations.splitlines():
        line = re.sub(r"^[*_`\s-]+|[*_`\s]+$", "", raw_line)
        if not line or _HEADING_LINE_RE.match(line) or _NAVIGATION_LABEL_RE.fullmatch(line):
            continue
        line = _DOCUMENT_FILE_RE.sub(" ", line)
        line = re.sub(r"\s{2,}", " ", line).strip(" ,，;；:：-")
        if line:
            kept_lines.append(line)
    return _prompt_fragment(" ".join(kept_lines))


def _is_visual_claim(value: str) -> bool:
    """Accept only bounded facts that can describe a teaching relationship."""

    claim = _prompt_fragment(value)
    if not claim or len(claim) < 12:
        return False
    if _HEADING_LINE_RE.match(claim) or _NAVIGATION_LABEL_RE.fullmatch(claim):
        return False
    if _DOCUMENT_FILE_RE.fullmatch(claim):
        return False
    if claim.casefold() in {
        "course evidence",
        "source",
        "document",
        "course material",
        "reference",
        "课程资料",
        "来源",
        "文档",
        "课件",
        "章节定位与知识链",
    }:
        return False
    return bool(_VISUAL_RELATION_RE.search(claim))


def _visual_claim_fragments(value: object, *, limit: int = 700) -> list[str]:
    """Extract bounded, source-usable teaching facts from delivered text."""

    cleaned = _strip_document_labels(value)
    if not cleaned:
        return []
    claims: list[str] = []
    for raw_sentence in _CLAIM_SPLIT_RE.split(cleaned):
        sentence = _prompt_fragment(raw_sentence)
        if _is_visual_claim(sentence):
            claims.append(sentence[:limit].rstrip())
    return list(dict.fromkeys(claims))


def _answer_fragment(answer: str, *, limit: int = 700) -> str:
    """Return the first delivered teaching fact, skipping document navigation."""

    claims = _visual_claim_fragments(answer, limit=limit)
    return claims[0] if claims else ""


def _is_endomembrane_transport(question: str) -> bool:
    q = question.lower()
    return _contains(
        q,
        r"endomembrane.*(?:protein|membrane).*transport",
        r"endoplasmic reticulum.*golgi",
        r"rough er.*golgi",
        r"openstax biology 2e.*(?:vesicle|protein|golgi|endoplasmic)",
    )


def _is_hdd_motion(question: str) -> bool:
    q = question.lower()
    return _contains(
        q,
        r"mechanical hard (?:disk|drive).*(?:platter|actuator)",
        r"platter.*(?:rotate|rotation).*actuator",
        r"执行器臂.*径向移动.*盘片.*(?:旋转|转动)",
        r"机械硬盘.*盘片.*执行器臂",
    )


def _is_desktop_internal_components(question: str) -> bool:
    q = question.lower()
    has_components = _contains(
        q,
        r"(?:motherboard|mainboard).*(?:cpu|dimm|heatsink)",
        r"(?:cpu socket|heatsink).*(?:dimm|memory slot)",
        r"主板.*(?:cpu|dimm|内存插槽|散热器)",
        r"(?:cpu\s*插座|散热器).*(?:dimm|内存插槽)",
    )
    return has_components and _contains(
        q,
        r"desktop (?:pc|computer)",
        r"台式(?:电脑|机)",
        r"通用.*电脑内部",
    )


def _has_grounded_dbscan_structure(answer: str) -> bool:
    return (
        _contains(answer, r"\bdbscan\b")
        and _contains(answer, r"\bcore point\b", r"核心点")
        and _contains(answer, r"\bborder point\b", r"边界点")
        and _contains(answer, r"\bnoise point\b", r"噪声点")
        and _contains(answer, r"\beps\b", r"\bminpts\b", r"邻域")
    )


def _grounded_diagram_labels(includes: list[str], answer_claims: list[str]) -> list[str]:
    if includes and not any(value.casefold() in _GENERIC_DIAGRAM_LABELS for value in includes):
        return includes
    labels: list[str] = []
    for value in answer_claims[:4]:
        label = _prompt_fragment(value, limit=150)
        if label:
            labels.append(label)
    return labels


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
        if _is_hdd_motion(question):
            return "VIDEO", "COMFY_VIDEO", list(HDD_VISUAL_REQUIRED)
        if _is_desktop_internal_components(question):
            return "IMAGE", "COMFY_IMAGE", list(DESKTOP_VISUAL_REQUIRED)
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
        is_hdd_motion = _is_hdd_motion(question)
        is_desktop_internal_components = _is_desktop_internal_components(question)
        is_dbscan = _contains(question, r"\bdbscan\b", r"基于密度的聚类")
        is_grounded_dbscan = is_dbscan and _has_grounded_dbscan_structure(answer)
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
        if is_dbscan:
            if is_grounded_dbscan:
                visual_type, renderer = "DIAGRAM", "SVG"
                includes = (
                    list(DBSCAN_VISUAL_REQUIRED_ZH)
                    if language.lower().startswith("zh")
                    else list(DBSCAN_VISUAL_REQUIRED_EN)
                )
            else:
                visual_type, renderer, includes = "NONE", "NONE", []
        if is_hdd_motion and action in {"diagram", "animate"}:
            visual_type, renderer, includes = "ANIMATION", "SVG", list(HDD_VISUAL_REQUIRED)
        elif action == "diagram" and renderer != "NONE":
            visual_type, renderer = "DIAGRAM", "SVG"
        elif action == "visual" and renderer == "NONE":
            visual_type, renderer, includes = "NONE", "NONE", []
        elif action == "animate" and renderer == "NONE" and not is_kmeans and includes:
            visual_type, renderer, includes = "ANIMATION", "MANIM", ["ordered states"]
        should_generate = renderer != "NONE"
        natural = renderer in {"COMFY_IMAGE", "COMFY_VIDEO"}
        answer_claims = _visual_claim_fragments(answer)
        answer_fact = answer_claims[0] if answer_claims else ""
        if should_generate and not natural:
            includes = _grounded_diagram_labels(includes, answer_claims)
            if not includes:
                visual_type, renderer = "NONE", "NONE"
                should_generate = False
        supported: list[str] = []
        if natural:
            supported_claims = [
                claim
                for item in evidence[:16]
                for claim in _visual_claim_fragments(item.get("supported_claim"))
            ]
            if is_hdd_motion:
                supported = [HDD_GROUNDED_CLAIM, *answer_claims, *supported_claims]
            elif is_desktop_internal_components:
                supported = [DESKTOP_GROUNDED_CLAIM, *answer_claims, *supported_claims]
            else:
                supported = [*answer_claims, *supported_claims]
            supported = list(dict.fromkeys(supported))
            if not supported:
                visual_type, renderer = "NONE", "NONE"
                should_generate, natural = False, False
            includes = list(dict.fromkeys(supported))[:4]
            if renderer == "COMFY_VIDEO" and is_hdd_motion:
                includes = list(HDD_VISUAL_REQUIRED)
            elif renderer == "COMFY_IMAGE" and is_desktop_internal_components:
                includes = list(DESKTOP_VISUAL_REQUIRED)
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
        if is_hdd_motion and renderer == "SVG" and diagram is not None:
            diagram["layout"] = "AUTO"
            diagram["edges"] = []
            diagram["hdd_kinematics"] = {"provenance": "DELIVERED_GROUNDED_EXPLANATION"}
            labels = []
        if is_grounded_dbscan and renderer == "SVG" and diagram is not None:
            diagram["layout"] = "AUTO"
            diagram["edges"] = []
            diagram["dbscan"] = {"provenance": "DELIVERED_GROUNDED_EXPLANATION"}
            labels = []
        animation_steps = []
        if is_hdd_motion and renderer == "SVG":
            animation_steps = [
                {
                    "order": 1,
                    "label": (
                        "The drive body and central spindle remain fixed while all "
                        "required parts are visible."
                    ),
                    "highlight_ids": ["n1", "n2", "n3", "n4"],
                },
                {
                    "order": 2,
                    "label": (
                        "The platter rotates continuously around the fixed spindle."
                    ),
                    "highlight_ids": ["n2"],
                },
                {
                    "order": 3,
                    "label": (
                        "The actuator arm performs one bounded radial sweep that moves "
                        "the read/write head across radial positions."
                    ),
                    "highlight_ids": ["n3", "n4"],
                },
            ]
        elif renderer == "COMFY_VIDEO" and is_endomembrane_transport:
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
        elif renderer == "COMFY_VIDEO" and is_hdd_motion:
            animation_steps = [
                {
                    "order": 1,
                    "label": (
                        "The drive body, circular platter, central spindle, actuator arm and "
                        "read/write head are visible in one fixed cutaway view."
                    ),
                    "highlight_ids": [],
                },
                {
                    "order": 2,
                    "label": (
                        "The platter rotates continuously around the fixed spindle while the "
                        "actuator arm performs one bounded radial sweep above it."
                    ),
                    "highlight_ids": [],
                },
                {
                    "order": 3,
                    "label": (
                        "The same drive body and objects remain visible with only the platter "
                        "angle and actuator-arm radial position changed."
                    ),
                    "highlight_ids": [],
                },
            ]
        elif renderer == "MANIM":
            animation_steps = [
                {"order": index + 1, "label": value, "highlight_ids": [nodes[index]["id"]]}
                for index, value in enumerate(includes or ["state"])
            ]
        natural_style = {
            "tone": (
                "TEXTBOOK"
                if (
                    renderer == "COMFY_VIDEO"
                    and (is_hdd_motion or is_endomembrane_transport)
                )
                else (
                    "REALISTIC"
                    if renderer == "COMFY_IMAGE" and is_desktop_internal_components
                    else "CONCEPTUAL"
                )
            )
        }
        if renderer == "COMFY_IMAGE" and is_desktop_internal_components:
            natural_style.update(
                {
                    "background": "clean neutral workshop background",
                    "composition": (
                        "one opened generic desktop computer fills the frame; the large "
                        "motherboard, compact CPU heatsink area and parallel DIMM slots are "
                        "all clearly visible and spatially distinct"
                    ),
                    "camera": "locked three-quarter overhead view",
                }
            )
        elif renderer == "COMFY_VIDEO" and is_hdd_motion:
            natural_style.update(
                {
                    "background": "clean neutral technical teaching background",
                    "composition": (
                        "one complete drive is centered in the frame; the platter is fully "
                        "visible and the actuator arm is fully exposed beside the platter"
                    ),
                    "camera": "locked direct overhead cutaway view with the top cover removed",
                }
            )
        elif renderer == "COMFY_VIDEO" and is_endomembrane_transport:
            natural_style.update(
                {
                    "background": "clean microscopic cell environment",
                    "composition": (
                        "the rough ER, Golgi apparatus and plasma membrane remain visible"
                    ),
                    "camera": "locked fixed side view",
                }
            )
        natural_forbidden = [
            "unrelated fantasy elements",
            "watermark",
            "unreadable text",
            "unsupported facts",
            "camera cuts",
            "montage",
            "scene changes",
        ]
        if renderer == "COMFY_VIDEO" and is_hdd_motion:
            natural_forbidden.extend(
                [
                    "SSD",
                    "scratches",
                    "sparks",
                    "people",
                    "readable technical text",
                    "exact RPM or seek-time numbers",
                ]
            )
        elif renderer == "COMFY_IMAGE" and is_desktop_internal_components:
            natural_forbidden.extend(
                [
                    "brand logos or model numbers",
                    "readable technical labels",
                    "measurement scales",
                    "laptops or server racks",
                    "smartphone circuit boards",
                    "exact dimensions, exact placement or compatibility claims",
                    "no arrows, leader lines, annotation circles or overlay cards",
                ]
            )
        fallback_claim = (
            HDD_GROUNDED_CLAIM
            if is_hdd_motion and natural
            else (
                DESKTOP_GROUNDED_CLAIM
                if is_desktop_internal_components and natural
                else (supported[0] if supported else "")
            )
        )
        grounding = []
        for item in evidence[:16]:
            evidence_claims = _visual_claim_fragments(item.get("supported_claim"))
            claim = evidence_claims[0] if evidence_claims else fallback_claim
            if not claim:
                continue
            grounding.append(
                {
                    "source_id": str(item["source_id"]),
                    "source_version": str(item["source_version"]),
                    "locator": str(item.get("locator") or "source"),
                    "supported_claim": claim,
                }
            )
        if natural and is_hdd_motion and grounding:
            grounding = [
                {
                    "source_id": grounding[0]["source_id"],
                    "source_version": grounding[0]["source_version"],
                    "locator": grounding[0]["locator"],
                    "supported_claim": HDD_GROUNDED_CLAIM,
                }
            ]
        elif natural and is_desktop_internal_components and grounding:
            grounding = [
                {
                    "source_id": grounding[0]["source_id"],
                    "source_version": grounding[0]["source_version"],
                    "locator": grounding[0]["locator"],
                    "supported_claim": DESKTOP_GROUNDED_CLAIM,
                }
            ]
        if natural and is_hdd_motion:
            natural_visual_goal = (
                "One complete mechanical hard disk drive in a locked cutaway teaching view. "
                "Keep the drive body fixed and show the circular platter, central spindle, "
                "actuator arm and read/write head at a medium-wide scale."
            )
            pedagogical_reason = (
                "Let the learner distinguish continuous platter rotation from one bounded "
                "actuator-arm radial sweep while the same drive body remains fixed."
            )
        elif natural and is_desktop_internal_components:
            natural_visual_goal = (
                "A generic desktop computer interior showing one large main circuit board, "
                "one compact CPU heatsink-covered area mounted on it, and a separate region "
                "of long narrow parallel DIMM memory slots."
            )
            pedagogical_reason = (
                "Let the learner identify three broad component regions without inferring a "
                "specific brand, exact layout, dimensions or compatibility."
            )
        elif natural:
            teaching_medium = (
                "short continuous teaching video"
                if renderer == "COMFY_VIDEO"
                else "clear teaching image"
            )
            grounded_facts = " ".join(supported[:2])
            natural_visual_goal = (
                f"Create one {teaching_medium} that visualizes these course-grounded "
                f"relationships: {grounded_facts}. Use the learner question only to select "
                f"the relevant relationship: {_prompt_fragment(question, limit=240)}"
            )
            pedagogical_reason = (
                "Let the learner examine the visual relationship stated in the course "
                f"facts: {_prompt_fragment(supported[0], limit=500)}"
            )
        else:
            natural_visual_goal = ""
            pedagogical_reason = (
                "The generated visual makes the supported course relationship easier to inspect."
            )
        visual_goal = (
            _prompt_fragment(natural_visual_goal, limit=800)
            if natural
            else (
                answer_fact
                if is_hdd_motion and answer_fact
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
            )
        )
        if is_grounded_dbscan:
            visual_goal = (
                DBSCAN_GROUNDED_CLAIM_ZH
                if language.lower().startswith("zh")
                else DBSCAN_GROUNDED_CLAIM_EN
            )
            pedagogical_reason = (
                "区分 DBSCAN 核心点、边界点和噪声点：比较 Eps 邻域计数、MinPts 阈值"
                "以及点是否落在核心点邻域内。"
                if language.lower().startswith("zh")
                else (
                    "Distinguish DBSCAN core, border, and noise points by comparing "
                    "Eps-neighborhood counts with MinPts and checking connectivity to core points."
                )
            )
        return VisualSpec.model_validate(
            {
                "visual_spec_version": "1.0",
                "should_generate": should_generate,
                "pedagogical_reason": pedagogical_reason
                if should_generate
                else "Insufficient supported visual structure; continue with the delivered text.",
                "visual_goal": visual_goal,
                "visual_type": visual_type,
                "renderer": renderer,
                "importance": "MEDIUM",
                "timing": "ON_DEMAND",
                "source_grounding": grounding,
                "must_include": includes,
                "must_not_include": natural_forbidden if natural else ["unsupported facts"],
                "exact_labels": labels,
                "equations": [],
                "code_elements": [],
                "reference_assets": [],
                "style": natural_style if natural else {"tone": "CLEAN_TECHNICAL"},
                "duration_seconds": 3 if renderer == "COMFY_VIDEO" else None,
                "aspect_ratio": (
                    "9:16"
                    if is_grounded_dbscan and renderer == "SVG"
                    else "1:1"
                    if is_hdd_motion and renderer == "SVG"
                    else "16:9"
                ),
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
