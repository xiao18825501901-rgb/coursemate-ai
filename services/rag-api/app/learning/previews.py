import codecs
import csv
import io
import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.errors import ApiError

TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}
OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


def capability(extension: str, artifact_id: str | None = None) -> dict[str, object]:
    if extension == ".pdf" or extension in IMAGE_MEDIA_TYPES:
        return {"kind": "INLINE_ORIGINAL", "available": True, "reason": None}
    if extension in TEXT_EXTENSIONS:
        return {"kind": "SAFE_TEXT", "available": True, "reason": None}
    if extension == ".csv":
        return {"kind": "TABLE_PREVIEW", "available": True, "reason": None}
    if extension == ".ipynb":
        return {"kind": "NOTEBOOK_PREVIEW", "available": True, "reason": None}
    if extension in OFFICE_EXTENSIONS and artifact_id:
        return {
            "kind": "DERIVED_PDF",
            "available": True,
            "reason": None,
            "artifact_id": artifact_id,
        }
    if extension in OFFICE_EXTENSIONS:
        return {
            "kind": "DOWNLOAD_ONLY",
            "available": False,
            "reason": "CONTROLLED_CONVERTER_NOT_CONFIGURED",
        }
    return {
        "kind": "DOWNLOAD_ONLY",
        "available": False,
        "reason": "FORMAT_NOT_PREVIEWABLE",
    }


def _read_limited(path: Path, limit: int) -> tuple[bytes, bool]:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    return data[:limit], len(data) > limit


def _decode_utf8(data: bytes, *, truncated: bool) -> str:
    try:
        decoder = codecs.getincrementaldecoder("utf-8")()
        return decoder.decode(data, final=not truncated)
    except UnicodeDecodeError as error:
        raise ApiError(
            422,
            "PREVIEW_INVALID_TEXT",
            "The document is not valid UTF-8 text.",
        ) from error


def safe_text_preview(path: Path, settings: Settings) -> dict[str, object]:
    data, byte_truncated = _read_limited(path, settings.v3_preview_max_bytes)
    text = _decode_utf8(data, truncated=byte_truncated)
    char_truncated = len(text) > settings.v3_preview_max_text_chars
    return {
        "kind": "SAFE_TEXT",
        "text": text[: settings.v3_preview_max_text_chars],
        "truncated": byte_truncated or char_truncated,
    }


def csv_preview(path: Path, settings: Settings) -> dict[str, object]:
    data, byte_truncated = _read_limited(path, settings.v3_preview_max_bytes)
    text = _decode_utf8(data, truncated=byte_truncated)
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        parsed: list[list[str]] = []
        truncated = byte_truncated
        for index, raw_row in enumerate(reader):
            if index > settings.v3_preview_max_csv_rows:
                truncated = True
                break
            if len(raw_row) > settings.v3_preview_max_csv_columns:
                truncated = True
            row = []
            for raw_cell in raw_row[: settings.v3_preview_max_csv_columns]:
                if len(raw_cell) > settings.v3_preview_max_cell_chars:
                    truncated = True
                row.append(raw_cell[: settings.v3_preview_max_cell_chars])
            parsed.append(row)
    except csv.Error as error:
        raise ApiError(
            422,
            "PREVIEW_INVALID_CSV",
            "The CSV document could not be parsed safely.",
        ) from error
    if not parsed:
        raise ApiError(422, "PREVIEW_EMPTY", "The document has no previewable rows.")
    return {
        "kind": "TABLE_PREVIEW",
        "columns": parsed[0],
        "rows": parsed[1:],
        "truncated": truncated,
    }


def _plain_output(output: object, limit: int) -> str | None:
    if not isinstance(output, dict):
        return None
    value: object | None = output.get("text")
    data = output.get("data")
    if value is None and isinstance(data, dict):
        value = data.get("text/plain")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        value = "".join(value)
    return value[:limit] if isinstance(value, str) and value else None


def _cell_source(cell: dict[str, Any], limit: int) -> str:
    source: object = cell.get("source", "")
    if isinstance(source, list) and all(isinstance(item, str) for item in source):
        source = "".join(source)
    return source[:limit] if isinstance(source, str) else ""


def notebook_preview(path: Path, settings: Settings) -> dict[str, object]:
    data, truncated = _read_limited(path, settings.v3_preview_max_bytes)
    if truncated:
        raise ApiError(
            413,
            "PREVIEW_TOO_LARGE",
            "The notebook is too large for a safe static preview; download the original.",
        )
    try:
        notebook = json.loads(_decode_utf8(data, truncated=False))
    except (json.JSONDecodeError, RecursionError) as error:
        raise ApiError(
            422,
            "PREVIEW_INVALID_NOTEBOOK",
            "The notebook JSON could not be parsed safely.",
        ) from error
    cells = notebook.get("cells") if isinstance(notebook, dict) else None
    if not isinstance(cells, list):
        raise ApiError(
            422,
            "PREVIEW_INVALID_NOTEBOOK",
            "The notebook does not contain a valid cell list.",
        )
    result = []
    for raw_cell in cells[: settings.v3_preview_max_notebook_cells]:
        if not isinstance(raw_cell, dict):
            raise ApiError(
                422,
                "PREVIEW_INVALID_NOTEBOOK",
                "The notebook contains an invalid cell.",
            )
        raw_outputs = raw_cell.get("outputs", [])
        outputs = (
            [
                value
                for output in raw_outputs
                if (value := _plain_output(output, settings.v3_preview_max_cell_chars))
            ]
            if isinstance(raw_outputs, list)
            else []
        )
        result.append(
            {
                "cell_type": raw_cell.get("cell_type")
                if raw_cell.get("cell_type") in {"markdown", "code", "raw"}
                else "unknown",
                "source": _cell_source(raw_cell, settings.v3_preview_max_text_chars),
                "execution_count": raw_cell.get("execution_count")
                if isinstance(raw_cell.get("execution_count"), int)
                else None,
                "outputs": outputs,
            }
        )
    return {
        "kind": "NOTEBOOK_PREVIEW",
        "executed": False,
        "cells": result,
        "truncated": len(cells) > settings.v3_preview_max_notebook_cells,
    }
