from __future__ import annotations

import re
import struct
from xml.etree import ElementTree


class InvalidVisualOutput(ValueError):
    pass


def validate_output(
    content: bytes,
    *,
    mime_type: str,
    width: int | None,
    height: int | None,
    duration_seconds: float | None,
    max_bytes: int,
    max_width: int,
    max_height: int,
    max_duration_seconds: float,
) -> tuple[int | None, int | None]:
    if not content or len(content) > max_bytes:
        raise InvalidVisualOutput("visual output size is invalid")
    actual_width, actual_height = width, height
    if mime_type == "image/png":
        if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n":
            raise InvalidVisualOutput("PNG magic/header is invalid")
        actual_width, actual_height = struct.unpack(">II", content[16:24])
    elif mime_type == "image/svg+xml":
        stripped = content.lstrip()
        lowered = stripped.lower()
        if not stripped.startswith(b"<svg") or b"<!doctype" in lowered or b"<!entity" in lowered:
            raise InvalidVisualOutput("SVG content is invalid or unsafe")
        try:
            root = ElementTree.fromstring(stripped)
        except ElementTree.ParseError as error:
            raise InvalidVisualOutput("SVG XML is invalid") from error
        safe_tags = {
            "svg",
            "rect",
            "defs",
            "marker",
            "animatetransform",
            "path",
            "text",
            "g",
            "line",
            "circle",
            "ellipse",
            "lineargradient",
            "polygon",
            "polyline",
            "stop",
        }
        read_only_animation_attributes = {
            "attributename",
            "type",
            "values",
            "dur",
            "repeatcount",
            "calcmode",
            "keytimes",
            "keysplines",
        }
        for element in root.iter():
            tag = str(element.tag).rsplit("}", 1)[-1].lower()
            if tag not in safe_tags:
                raise InvalidVisualOutput("SVG element is outside the safe allowlist")
            if tag == "animatetransform":
                attributes = {
                    str(name).rsplit("}", 1)[-1].lower(): str(value).strip()
                    for name, value in element.attrib.items()
                }
                if any(name not in read_only_animation_attributes for name in attributes):
                    raise InvalidVisualOutput("SVG animation attributes are unsafe")
                if attributes.get("attributename", "").lower() != "transform":
                    raise InvalidVisualOutput("SVG animation target is unsafe")
                animation_type = attributes.get("type", "").lower()
                if animation_type not in {"rotate", "translate", "scale"}:
                    raise InvalidVisualOutput("SVG animation type is unsafe")
                if attributes.get("repeatcount", "").lower() != "indefinite":
                    raise InvalidVisualOutput("SVG animation repeat policy is unsafe")
                if not re.fullmatch(r"\d+(?:\.\d+)?s", attributes.get("dur", "")):
                    raise InvalidVisualOutput("SVG animation duration is unsafe")
                values = attributes.get("values", "")
                frames = [value.strip() for value in values.split(";") if value.strip()]
                expected_tokens = 2 if animation_type == "translate" else 1
                if animation_type == "rotate":
                    expected_tokens = 3
                for frame in frames:
                    tokens = [value for value in re.split(r"[\s,]+", frame) if value]
                    if len(tokens) != expected_tokens or any(
                        not re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", token)
                        for token in tokens
                    ):
                        raise InvalidVisualOutput("SVG animation values are unsafe")
                if len(frames) < 2:
                    raise InvalidVisualOutput("SVG animation values are incomplete")
                for name in ("keytimes", "keysplines"):
                    if name in attributes and not re.fullmatch(
                        r"[-+0-9.;\s]+", attributes[name]
                    ):
                        raise InvalidVisualOutput("SVG animation timing is unsafe")
            for raw_name, raw_value in element.attrib.items():
                name = str(raw_name).rsplit("}", 1)[-1].lower()
                value = str(raw_value).strip().lower()
                if name.startswith("on") or name in {"href", "style"}:
                    raise InvalidVisualOutput("SVG attribute is unsafe")
                if "javascript:" in value or "data:" in value or "file:" in value:
                    raise InvalidVisualOutput("SVG attribute contains an unsafe URL")
                if "url(" in value and "url(#" not in value:
                    raise InvalidVisualOutput("SVG attribute contains an external reference")
    else:
        raise InvalidVisualOutput("unsupported visual MIME type")
    if actual_width is not None and not 1 <= actual_width <= max_width:
        raise InvalidVisualOutput("visual width is outside policy")
    if actual_height is not None and not 1 <= actual_height <= max_height:
        raise InvalidVisualOutput("visual height is outside policy")
    if duration_seconds is not None and not 0 < duration_seconds <= max_duration_seconds:
        raise InvalidVisualOutput("visual duration is outside policy")
    return actual_width, actual_height
