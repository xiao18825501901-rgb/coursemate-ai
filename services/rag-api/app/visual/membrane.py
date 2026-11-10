from __future__ import annotations

import html


def render(language: str) -> str:
    """Render a source-grounded phospholipid bilayer without generative typography."""

    chinese = language.lower().startswith("zh")
    title = (
        "流动镶嵌模型：疏水尾部朝向膜内侧"
        if chinese
        else "Fluid mosaic model: hydrophobic tails face the membrane interior"
    )
    water = "水环境" if chinese else "Aqueous environment"
    heads = "磷脂头部面向水" if chinese else "Phospholipid heads face water"
    tails = (
        "疏水尾部彼此相对，避开水"
        if chinese
        else "Hydrophobic tails face each other, away from water"
    )
    caption = (
        "疏水尾部无法与水形成氢键，因此在水环境中彼此相对并朝向膜内侧。"
        if chinese
        else (
            "Hydrophobic tails cannot hydrogen-bond with water, so they face inward "
            "and toward each other."
        )
    )

    phospholipids: list[str] = []
    left = 142.0
    spacing = 92.5
    for index in range(8):
        x = left + index * spacing
        phospholipids.append(
            f'<g class="phospholipid" transform="translate({x:.1f} 0)">'
            '<circle cx="0" cy="215" r="18" fill="#70a9e8" stroke="#1d5a96" stroke-width="3"/>'
            '<path d="M -8 231 C -23 252 -18 276 -24 292" fill="none" '
            'stroke="#e28443" stroke-width="7" stroke-linecap="round"/>'
            '<path d="M 8 231 C 23 252 18 276 24 292" fill="none" '
            'stroke="#e28443" stroke-width="7" stroke-linecap="round"/>'
            '<circle cx="0" cy="361" r="18" fill="#70a9e8" stroke="#1d5a96" stroke-width="3"/>'
            '<path d="M -8 345 C -23 324 -18 300 -24 284" fill="none" '
            'stroke="#e28443" stroke-width="7" stroke-linecap="round"/>'
            '<path d="M 8 345 C 23 324 18 300 24 284" fill="none" '
            'stroke="#e28443" stroke-width="7" stroke-linecap="round"/>'
            "</g>"
        )

    water_molecules: list[str] = []
    for row_y in (132, 437):
        for index in range(6):
            x = 205 + index * 123
            water_molecules.append(
                f'<g class="water-molecule" transform="translate({x} {row_y})">'
                '<circle cx="0" cy="0" r="6" fill="#3ca7c7"/>'
                '<circle cx="-12" cy="7" r="4" fill="#b9e7f2"/>'
                '<circle cx="12" cy="7" r="4" fill="#b9e7f2"/>'
                "</g>"
            )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="576" '
        'viewBox="0 0 1024 576" role="img" '
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
        '<rect width="1024" height="576" fill="#ffffff"/>'
        '<rect x="48" y="84" width="928" height="408" rx="28" fill="url(#water)"/>'
        f'<text x="512" y="45" text-anchor="middle" font-family="sans-serif" '
        f'font-size="28" font-weight="700" fill="#18314f">{html.escape(title)}</text>'
        f'<text x="76" y="113" font-family="sans-serif" font-size="18" '
        f'font-weight="700" fill="#246d84">{html.escape(water)}</text>'
        f'<text x="948" y="469" text-anchor="end" font-family="sans-serif" '
        f'font-size="18" font-weight="700" fill="#246d84">{html.escape(water)}</text>'
        '<rect x="86" y="277" width="852" height="22" rx="11" fill="#fff3df"/>'
        f'<text x="948" y="185" text-anchor="end" font-family="sans-serif" '
        f'font-size="20" font-weight="700" fill="#6c3d1d" paint-order="stroke" '
        f'stroke="#fff8ea" stroke-width="6" stroke-linejoin="round">{html.escape(tails)}</text>'
        + "".join(water_molecules)
        + "".join(phospholipids)
        + '<line x1="92" y1="215" x2="92" y2="292" stroke="#6c3d1d" '
        'stroke-width="3" marker-end="url(#inward)"/>'
        '<line x1="932" y1="361" x2="932" y2="284" stroke="#6c3d1d" '
        'stroke-width="3" marker-end="url(#inward)"/>'
        f'<text x="122" y="185" font-family="sans-serif" font-size="17" '
        f'fill="#1d5a96" paint-order="stroke" stroke="#eefaff" stroke-width="5" '
        f'stroke-linejoin="round">{html.escape(heads)}</text>'
        f'<text x="512" y="531" text-anchor="middle" font-family="sans-serif" '
        f'font-size="18" fill="#33475b">{html.escape(caption)}</text>'
        "</svg>"
    )
