from __future__ import annotations

import html
import textwrap


def render(language: str) -> str:
    """Render a source-grounded phospholipid bilayer without generative typography."""

    chinese = language.lower().startswith("zh")
    title = "流动镶嵌模型：疏水尾部朝向膜内侧" if chinese else (
        "Fluid mosaic model: hydrophobic tails face inward"
    )
    water = "水环境" if chinese else "Aqueous environment"
    heads = "磷脂头部面向水" if chinese else "Phospholipid heads face water"
    tail_lines = (
        ["疏水尾部彼此相对，避开水"]
        if chinese
        else ["Hydrophobic tails face each other,", "away from water"]
    )
    caption_lines = (
        ["疏水尾部无法与水形成氢键，", "因此在水环境中彼此相对并朝向膜内侧。"]
        if chinese
        else textwrap.wrap(
            "Hydrophobic tails cannot hydrogen-bond with water, so they face inward "
            "and toward each other.",
            width=52,
        )
    )

    phospholipids: list[str] = []
    left = 88.0
    spacing = 81.0
    for index in range(8):
        x = left + index * spacing
        phospholipids.append(
            f'<g class="phospholipid" transform="translate({x:.1f} 0)">'
            '<circle cx="0" cy="254" r="17" fill="#70a9e8" stroke="#1d5a96" stroke-width="3"/>'
            '<path d="M -7 269 C -21 286 -16 307 -22 324" fill="none" '
            'stroke="#e28443" stroke-width="7" stroke-linecap="round"/>'
            '<path d="M 7 269 C 21 286 16 307 22 324" fill="none" '
            'stroke="#e28443" stroke-width="7" stroke-linecap="round"/>'
            '<circle cx="0" cy="432" r="17" fill="#70a9e8" stroke="#1d5a96" stroke-width="3"/>'
            '<path d="M -7 417 C -21 400 -16 379 -22 362" fill="none" '
            'stroke="#e28443" stroke-width="7" stroke-linecap="round"/>'
            '<path d="M 7 417 C 21 400 16 379 22 362" fill="none" '
            'stroke="#e28443" stroke-width="7" stroke-linecap="round"/>'
            "</g>"
        )

    water_molecules: list[str] = []
    for row_y in (146, 526):
        for index in range(6):
            x = 120 + index * 100
            water_molecules.append(
                f'<g class="water-molecule" transform="translate({x} {row_y})">'
                '<circle cx="0" cy="0" r="6" fill="#3ca7c7"/>'
                '<circle cx="-12" cy="7" r="4" fill="#b9e7f2"/>'
                '<circle cx="12" cy="7" r="4" fill="#b9e7f2"/>'
                "</g>"
            )

    def text_lines(
        lines: list[str],
        *,
        x: int,
        y: int,
        font_size: int,
        fill: str,
        line_height: int,
        anchor: str = "start",
        weight: int | None = None,
        extra: str = "",
    ) -> str:
        weight_attr = f' font-weight="{weight}"' if weight is not None else ""
        anchor_attr = f' text-anchor="{anchor}"' if anchor != "start" else ""
        return "".join(
            (
                f'<text x="{x}" y="{y + index * line_height}" font-family="sans-serif" '
                f'font-size="{font_size}"{weight_attr}{anchor_attr}{extra}>'
                f"{html.escape(line)}</text>"
            )
            for index, line in enumerate(lines)
        )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="720" '
        'viewBox="0 0 720 720" role="img" '
        'aria-label="Flow mosaic model phospholipid bilayer teaching diagram" '
        'data-renderer="phospholipid-bilayer">'
        "<defs>"
        '<linearGradient id="water" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#eefaff"/>'
        '<stop offset="1" stop-color="#dff4fb"/>'
        "</linearGradient>"
        '<marker id="inward" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#6c3d1d"/>'
        "</marker>"
        "</defs>"
        '<rect width="720" height="720" fill="#ffffff"/>'
        '<rect x="28" y="92" width="664" height="486" rx="24" fill="url(#water)"/>'
        f'<text x="360" y="52" text-anchor="middle" font-family="sans-serif" '
        f'font-size="34" font-weight="700" fill="#18314f">{html.escape(title)}</text>'
        f'<text x="52" y="126" font-family="sans-serif" font-size="24" '
        f'font-weight="700" fill="#246d84">{html.escape(water)}</text>'
        f'<text x="668" y="566" text-anchor="end" font-family="sans-serif" font-size="24" '
        f'font-weight="700" fill="#246d84">{html.escape(water)}</text>'
        '<rect x="48" y="332" width="624" height="22" rx="11" fill="#fff3df"/>'
        + "".join(water_molecules)
        + "".join(phospholipids)
        + '<line x1="52" y1="254" x2="52" y2="324" stroke="#6c3d1d" '
        'stroke-width="3" marker-end="url(#inward)"/>'
        '<line x1="668" y1="432" x2="668" y2="362" stroke="#6c3d1d" '
        'stroke-width="3" marker-end="url(#inward)"/>'
        + text_lines(
            [heads],
            x=52,
            y=196,
            font_size=25 if chinese else 21,
            fill="#1d5a96",
            line_height=28,
            extra=(
                ' paint-order="stroke" stroke="#eefaff" stroke-width="5" '
                'stroke-linejoin="round"'
            ),
        )
        + text_lines(
            tail_lines,
            x=668,
            y=186,
            font_size=25 if chinese else 21,
            fill="#6c3d1d",
            line_height=27,
            anchor="end",
            weight=700,
            extra=(
                ' paint-order="stroke" stroke="#fff8ea" stroke-width="6" '
                'stroke-linejoin="round"'
            ),
        )
        + text_lines(
            caption_lines,
            x=360,
            y=614,
            font_size=28 if chinese else 24,
            fill="#33475b",
            line_height=34,
            anchor="middle",
        )
        + "</svg>"
    )
