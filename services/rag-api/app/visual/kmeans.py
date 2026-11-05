"""Bounded parser and trusted drawing of a delivered two-dimensional worked example."""

from __future__ import annotations

import html
import re

from app.visual.spec import CoordinatePoint, KMeansExample

NUMBER = r"(-?\d+(?:\.\d+)?)"


def delivered_example(answer: str) -> KMeansExample | None:
    # Only the first worked-example table, never a later independent exercise.
    if not re.search(r"\bK\s*=\s*2\b", answer):
        return None
    if not re.search(r"由我构造|不是课件原例|not original course data", answer, re.I):
        return None
    pattern = r"\|\s*([A-Za-z][A-Za-z0-9]{0,7})\s*\|\s*\(" + NUMBER + r",\s*" + NUMBER + r"\)\s*\|"
    rows = []
    previous_end = None
    for match in re.finditer(pattern, answer):
        if previous_end is not None and answer[previous_end : match.start()].strip():
            break
        rows.append(match.groups())
        previous_end = match.end()
    centers = re.findall(
        r"c_([12])\^\{\(0\)\}\s*=\s*\(" + NUMBER + r",\s*" + NUMBER + r"\)", answer
    )
    if not (2 <= len(rows) <= 12) or len(centers) < 2:
        return None
    first = centers[:2]
    if [c[0] for c in first] != ["1", "2"]:
        return None
    try:
        return KMeansExample(
            points=[CoordinatePoint(label=n, x=float(x), y=float(y)) for n, x, y in rows],
            initial_centroids=[
                CoordinatePoint(label="c" + n, x=float(x), y=float(y)) for n, x, y in first
            ],
            provenance="DELIVERED_WORKED_EXAMPLE",
        )
    except ValueError:
        return None


def assignment(example: KMeansExample) -> tuple[list[int], list[tuple[float, float]], float]:
    centers = [(c.x, c.y) for c in example.initial_centroids]
    groups = [
        min(range(2), key=lambda k: (p.x - centers[k][0]) ** 2 + (p.y - centers[k][1]) ** 2)
        for p in example.points
    ]
    if any(k not in groups for k in range(2)):
        raise ValueError("empty cluster is unsupported in this teaching view")
    members = [[p for p, g in zip(example.points, groups, strict=True) if g == k] for k in range(2)]
    updated = [
        (sum(p.x for p in cluster) / len(cluster), sum(p.y for p in cluster) / len(cluster))
        for cluster in members
    ]
    sse = sum(
        (p.x - updated[g][0]) ** 2 + (p.y - updated[g][1]) ** 2
        for p, g in zip(example.points, groups, strict=True)
    )
    return groups, updated, sse


def render(example: KMeansExample, language: str) -> str:
    groups, centers, sse = assignment(example)
    zh = language.startswith("zh")
    title = "K-means：分配与质心更新" if zh else "K-means: assign and update"
    note = (
        "已交付正文中的教学例；非课件原始数据"
        if zh
        else "Delivered worked example; not original course data"
    )
    points = (
        [(p.x, p.y) for p in example.points]
        + [(c.x, c.y) for c in example.initial_centroids]
        + centers
    )
    lo_x, hi_x = min(p[0] for p in points), max(p[0] for p in points)
    lo_y, hi_y = min(p[1] for p in points), max(p[1] for p in points)

    def xy(x: float, y: float) -> tuple[float, float]:
        scale = min(240 / max(1, hi_x - lo_x), 180 / max(1, hi_y - lo_y))
        return 40 + scale * (x - lo_x), 300 - scale * (y - lo_y)

    def text(x: float, y: float, value: str, size: int = 16) -> str:
        return f'<text x="{x}" y="{y}" font-size="{size}">{html.escape(value)}</text>'

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="340" height="510" '
        f'viewBox="0 0 340 510" role="img" aria-label="{html.escape(title)}">',
        '<rect width="340" height="510" fill="white"/>',
        '<g font-family="sans-serif" fill="#17293d">',
        text(14, 28, title, 18),
        text(14, 53, note, 14),
        text(
            14,
            83,
            "1. 最近质心分配 → 2. 按簇求均值" if zh else "1. Nearest center → 2. Cluster mean",
            16,
        ),
        '<path d="M25 110V320H310" fill="none" stroke="#536175"/>',
    ]
    colors = ["#1264a3", "#9c3d0d"]
    for p, g in zip(example.points, groups, strict=True):
        x, y = xy(p.x, p.y)
        cx, cy = xy(*centers[g])
        parts += [
            f'<path d="M{x} {y}L{cx} {cy}" stroke="{colors[g]}" stroke-dasharray="4 3"/>',
            f'<circle cx="{x}" cy="{y}" r="5" fill="{colors[g]}"/>',
            text(
                round(x - 60 if x > 170 else x - 10),
                round(y - 13),
                f"{p.label} ({p.x:g}, {p.y:g})",
                14,
            ),
        ]
    for k, (x, y) in enumerate(centers):
        px, py = xy(x, y)
        parts += [
            f'<path d="M{px - 7} {py}H{px + 7}M{px} {py - 7}V{py + 7}" '
            f'stroke="{colors[k]}" stroke-width="3"/>',
            text(14, 355 + k * 28, f"c{k + 1} = ({x:g}, {y:g})", 16),
        ]
    parts += [
        text(285, 318, "x1", 14),
        text(6, 108, "x2", 14),
        text(14, 411, f"SSE = {sse:g}", 18),
        text(
            14,
            440,
            "虚线：点到更新质心；＋：新质心" if zh else "Dashed: distance; +: updated center",
            14,
        ),
        text(
            14,
            468,
            "观察：为何各簇的质心是坐标均值？" if zh else "Why is each center the coordinate mean?",
            14,
        ),
        text(
            14,
            494,
            "本图展示一轮，不预判收敛。" if zh else "One iteration; convergence not assumed.",
            14,
        ),
        "</g></svg>",
    ]
    return "".join(parts)
