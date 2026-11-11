from __future__ import annotations

import html


def render(language: str) -> str:
    """Render the grounded platter/actuator teaching motion without generative text."""

    chinese = language.lower().startswith("zh")
    title = "机械硬盘：盘片旋转与执行器臂径向移动" if chinese else (
        "Hard-disk drive kinematics"
    )
    subtitle = "盘片持续旋转；执行器臂做有界径向扫动" if chinese else (
        "Platter rotation and bounded radial actuator sweep"
    )
    platter_label = "Continuous platter rotation" if not chinese else "盘片持续旋转"
    sweep_label = "Bounded radial sweep" if not chinese else "有界径向扫动"
    actuator_label = "Actuator arm" if not chinese else "执行器臂"
    head_label = "Read/write head" if not chinese else "读写磁头"
    spindle_label = "Fixed spindle" if not chinese else "固定主轴"
    fixed_label = "Drive body remains fixed" if not chinese else "硬盘本体保持固定"
    phase_labels = (
        [
            "1  硬盘本体与主轴固定",
            "2  盘片围绕主轴持续旋转",
            "3  执行器臂径向移动，磁头改变半径",
        ]
        if chinese
        else [
            "1  Drive body and spindle fixed",
            "2  Platter rotates continuously",
            "3  Arm sweeps radially; head changes radius",
        ]
    )

    def label(x: int, y: int, value: str, size: int = 18, anchor: str = "start") -> str:
        return (
            f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="sans-serif" '
            f'font-size="{size}" fill="#213547">{html.escape(value)}</text>'
        )

    tracks = "".join(
        f'<circle cx="285" cy="330" r="{radius}" fill="none" '
        'stroke="#879ca8" stroke-width="2" opacity="0.58"/>'
        for radius in (52, 88, 124, 158)
    )
    phase_text = "".join(
        label(54, 570 + index * 34, value, 21)
        for index, value in enumerate(phase_labels)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="720" '
        'viewBox="0 0 720 720" role="img" '
        f'aria-label="{html.escape(title)}" data-renderer="hdd-kinematics">'
        "<defs>"
        '<marker id="sweepArrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#a55416"/>'
        "</marker>"
        "</defs>"
        '<rect width="720" height="720" fill="#fbfcfd"/>'
        f'<text x="360" y="36" text-anchor="middle" font-family="sans-serif" '
        f'font-size="29" font-weight="700" fill="#172b3d">{html.escape(title)}</text>'
        f'<text x="360" y="66" text-anchor="middle" font-family="sans-serif" '
        f'font-size="20" fill="#526875">{html.escape(subtitle)}</text>'
        '<rect x="42" y="92" width="518" height="422" rx="30" fill="#eef2f3" '
        'stroke="#526875" stroke-width="8"/>'
        '<path d="M72 135H510" stroke="#b7c4ca" stroke-width="3"/>'
        '<g aria-label="rotating platter">'
        '<circle cx="285" cy="330" r="180" fill="#c8d6dc" stroke="#435967" stroke-width="7"/>'
        + tracks
        + '<g>'
        '<animateTransform attributeName="transform" type="rotate" '
        'values="0 285 330;360 285 330" dur="3s" repeatCount="indefinite"/>'
        '<path d="M285 210V158" stroke="#b54f2f" stroke-width="14" stroke-linecap="round"/>'
        '<circle cx="285" cy="175" r="10" fill="#b54f2f"/>'
        '<path d="M285 330L392 278" stroke="#7d94a0" stroke-width="5"/>'
        "</g>"
        "</g>"
        '<circle cx="285" cy="330" r="28" fill="#5c7480" stroke="#263d49" stroke-width="6"/>'
        '<circle cx="285" cy="330" r="9" fill="#edf4f6"/>'
        '<g aria-label="bounded actuator arm sweep">'
        '<animateTransform attributeName="transform" type="rotate" '
        'values="8 505 430;-14 505 430;8 505 430" dur="3s" '
        'repeatCount="indefinite" calcMode="spline" keyTimes="0;0.5;1" '
        'keySplines="0.4 0 0.6 1;0.4 0 0.6 1"/>'
        '<path d="M505 430L485 397L348 322L332 350Z" fill="#f2c889" '
        'stroke="#6e4a20" stroke-width="5"/>'
        '<circle cx="505" cy="430" r="34" fill="#8e6c44" stroke="#3e352b" stroke-width="7"/>'
        '<rect x="323" y="323" width="23" height="34" rx="7" fill="#293b46" '
        'stroke="#111c23" stroke-width="4" transform="rotate(-26 334 340)"/>'
        "</g>"
        '<path d="M330 274Q410 238 478 304" fill="none" stroke="#a55416" '
        'stroke-width="5" stroke-dasharray="9 7" marker-end="url(#sweepArrow)"/>'
        '<line x1="438" y1="351" x2="548" y2="351" stroke="#788c97" stroke-width="2"/>'
        f'{label(556, 357, actuator_label, 20)}'
        '<line x1="342" y1="335" x2="548" y2="301" stroke="#788c97" stroke-width="2"/>'
        f'{label(556, 299, head_label, 20)}'
        '<line x1="207" y1="275" x2="160" y2="176" stroke="#788c97" stroke-width="2"/>'
        f'{label(64, 164, platter_label, 22)}'
        '<line x1="285" y1="330" x2="215" y2="463" stroke="#788c97" stroke-width="2"/>'
        f'{label(214, 477, spindle_label, 21)}'
        '<line x1="274" y1="112" x2="205" y2="112" stroke="#788c97" stroke-width="2"/>'
        f'{label(64, 120, fixed_label, 22)}'
        '<path d="M330 500H620" stroke="#d4dde1" stroke-width="2"/>'
        f'{label(54, 532, sweep_label, 25)}'
        + phase_text
        + "</svg>"
    )
