from __future__ import annotations

import html
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class _Point:
    label: str
    x: float
    y: float
    neighbors: int
    kind: str


def _classify_points() -> tuple[list[_Point], float, int]:
    eps = 160.0
    min_pts = 4
    raw = [
        ("A", 250.0, 250.0),
        ("B", 350.0, 250.0),
        ("C", 300.0, 350.0),
        ("D", 180.0, 250.0),
        ("E", 420.0, 250.0),
        ("F", 620.0, 480.0),
    ]
    counts = [
        sum(math.dist((x, y), (other_x, other_y)) <= eps for _, other_x, other_y in raw)
        for _, x, y in raw
    ]
    core_indexes = {index for index, count in enumerate(counts) if count >= min_pts}
    points: list[_Point] = []
    for index, ((label, x, y), count) in enumerate(zip(raw, counts, strict=True)):
        is_core = index in core_indexes
        near_core = any(
            math.dist((x, y), (raw[core_index][1], raw[core_index][2])) <= eps
            for core_index in core_indexes
        )
        kind = "core" if is_core else ("border" if near_core else "noise")
        points.append(_Point(label, x, y, count, kind))
    return points, eps, min_pts


def _point_style(kind: str) -> tuple[str, str, str]:
    if kind == "core":
        return "#7c3aed", "#4c1d95", "9"
    if kind == "border":
        return "#f59e0b", "#b45309", "7"
    return "#ef4444", "#991b1b", "8"


def render(language: str) -> str:
    chinese = language.lower().startswith("zh")
    points, eps, min_pts = _classify_points()
    core_points = [point for point in points if point.kind == "core"]
    border_points = [point for point in points if point.kind == "border"]
    noise_points = [point for point in points if point.kind == "noise"]
    title = (
        "DBSCAN：由 Eps 邻域和 MinPts 判定三类点"
        if chinese
        else "DBSCAN: classify points with Eps neighborhoods and MinPts"
    )
    subtitle = (
        "示意点集；邻域计数包含点自身"
        if chinese
        else "Illustrative point set; neighborhood counts include the point itself"
    )
    core_text = "核心点" if chinese else "Core point"
    border_text = "边界点" if chinese else "Border point"
    noise_text = "噪声点" if chinese else "Noise point"
    criteria_title = "判定关系" if chinese else "Decision rules"
    cluster_text = "同一密度连通簇" if chinese else "One density-connected cluster"
    core_rule = "邻域点数 ≥ MinPts，可扩展簇" if chinese else (
        "neighborhood ≥ MinPts; can expand"
    )
    border_rule = "邻域 < MinPts，但在核心点邻域内" if chinese else (
        "< MinPts, but inside a core neighborhood"
    )
    noise_rule = "不在任何核心点的 Eps 邻域内" if chinese else (
        "outside every core point neighborhood"
    )
    eps_title = "Eps 邻域" if chinese else "Eps neighborhood"
    eps_rule = "虚线圆半径 = Eps；计数包含点自身" if chinese else (
        "dashed radius = Eps; count includes self"
    )
    border_note = "边界点只归入簇，不能再向外扩展" if chinese else (
        "border points join a cluster but cannot expand it"
    )

    circles = "".join(
        (
            f'<circle cx="{point.x:.0f}" cy="{point.y:.0f}" r="{eps:.0f}" '
            'fill="#7c3aed" fill-opacity="0.055" stroke="#8b5cf6" '
            'stroke-width="2" stroke-dasharray="8 7"/>'
        )
        for point in core_points
    )
    marks: list[str] = []
    for point in points:
        fill, stroke, radius = _point_style(point.kind)
        marks.append(
            f'<g data-point="{html.escape(point.label)}" data-kind="{point.kind}" '
            f'data-neighbors="{point.neighbors}">'
            f'<circle cx="{point.x:.0f}" cy="{point.y:.0f}" r="{radius}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
            f'<text x="{point.x + 14:.0f}" y="{point.y - 13:.0f}" '
            'font-family="Arial, sans-serif" font-size="17" font-weight="700" '
            f'fill="{stroke}">{point.label} · {point.neighbors}</text></g>'
        )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="576" '
        'viewBox="0 0 1024 576" role="img" '
        'aria-label="DBSCAN core, border and noise points classified by Eps and MinPts" '
        'data-renderer="dbscan-density" '
        f'data-eps="{eps:.0f}" data-min-pts="{min_pts}" '
        f'data-core-points="{len(core_points)}" '
        f'data-border-points="{len(border_points)}" '
        f'data-noise-points="{len(noise_points)}">'
        '<rect width="1024" height="576" fill="#f8fafc"/>'
        f'<text x="512" y="34" text-anchor="middle" font-family="Arial, sans-serif" '
        f'font-size="25" font-weight="700" fill="#172033">{html.escape(title)}</text>'
        f'<text x="512" y="57" text-anchor="middle" font-family="Arial, sans-serif" '
        f'font-size="14" fill="#52637a">{html.escape(subtitle)}</text>'
        '<rect x="24" y="78" width="650" height="470" rx="18" fill="#ffffff" '
        'stroke="#d7deea"/>'
        f"{circles}"
        '<ellipse cx="300" cy="300" rx="215" ry="190" fill="none" stroke="#94a3b8" '
        'stroke-width="2" stroke-dasharray="3 8"/>'
        f'<text x="300" y="118" text-anchor="middle" font-family="Arial, sans-serif" '
        f'font-size="15" font-weight="600" fill="#52637a">{html.escape(cluster_text)}</text>'
        f'{"".join(marks)}'
        '<rect x="694" y="78" width="306" height="470" rx="18" fill="#ffffff" '
        'stroke="#d7deea"/>'
        f'<text x="714" y="113" font-family="Arial, sans-serif" font-size="21" '
        f'font-weight="700" fill="#172033">{html.escape(criteria_title)}</text>'
        '<circle cx="725" cy="155" r="9" fill="#7c3aed"/>'
        f'<text x="746" y="160" font-family="Arial, sans-serif" font-size="17" '
        f'font-weight="700" fill="#4c1d95">{html.escape(core_text)}</text>'
        f'<text x="714" y="188" font-family="Arial, sans-serif" font-size="14" '
        f'fill="#3b4658">{html.escape(core_rule)}</text>'
        '<circle cx="725" cy="231" r="8" fill="#f59e0b"/>'
        f'<text x="746" y="236" font-family="Arial, sans-serif" font-size="17" '
        f'font-weight="700" fill="#b45309">{html.escape(border_text)}</text>'
        f'<text x="714" y="264" font-family="Arial, sans-serif" font-size="14" '
        f'fill="#3b4658">{html.escape(border_rule)}</text>'
        '<circle cx="725" cy="307" r="8" fill="#ef4444"/>'
        f'<text x="746" y="312" font-family="Arial, sans-serif" font-size="17" '
        f'font-weight="700" fill="#991b1b">{html.escape(noise_text)}</text>'
        f'<text x="714" y="340" font-family="Arial, sans-serif" font-size="14" '
        f'fill="#3b4658">{html.escape(noise_rule)}</text>'
        '<line x1="714" y1="366" x2="980" y2="366" stroke="#e2e8f0"/>'
        f'<text x="714" y="398" font-family="Arial, sans-serif" font-size="16" '
        f'font-weight="700" fill="#172033">{html.escape(eps_title)}</text>'
        f'<text x="714" y="425" font-family="Arial, sans-serif" font-size="14" '
        f'fill="#52637a">{html.escape(eps_rule)}</text>'
        f'<text x="714" y="458" font-family="Arial, sans-serif" font-size="16" '
        f'font-weight="700" fill="#172033">MinPts = {min_pts}</text>'
        f'<text x="714" y="485" font-family="Arial, sans-serif" font-size="14" '
        f'fill="#52637a">{html.escape(border_note)}</text>'
        "</svg>"
    )
