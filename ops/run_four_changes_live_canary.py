#!/usr/bin/env python3
"""Run one bounded, synthetic live-Qwen check through the shipped UI routes.

It creates a new throwaway RAG/UI database, uses the exact production UI code,
and refuses to run without the explicit opt-in and a total ceiling at or below
the Owner-approved USD 2.00 release budget.  It writes token/route metadata but
never model text, private course material, credentials, or session tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any


def fail(message: str) -> None:
    raise RuntimeError(message)


def terminal(client: Any, api: str, run_id: str, headers: dict[str, str]) -> dict[str, Any]:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        response = client.get(f"{api}/runs/{run_id}", headers=headers)
        response.raise_for_status()
        value = response.json()
        if value["status"] in {"completed", "failed", "cancelled"}:
            return value
        time.sleep(0.25)
    fail(f"Run {run_id} did not finish within the bounded canary timeout.")


def numeric_usage(run: dict[str, Any]) -> dict[str, int]:
    result = {"input_tokens": 0, "output_tokens": 0, "usage_events": 0}
    for item in run.get("usage", []):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        result["usage_events"] += 1
        result["input_tokens"] += int(value.get("input_tokens", value.get("prompt_tokens", 0)) or 0)
        result["output_tokens"] += int(value.get("output_tokens", value.get("completion_tokens", 0)) or 0)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-live-usd", type=Decimal, required=True)
    parser.add_argument("--allow-billable", action="store_true")
    args = parser.parse_args()

    if not args.allow_billable:
        fail("Pass --allow-billable only after an approved release model budget.")
    if args.max_live_usd <= 0 or args.max_live_usd > Decimal("2.00"):
        fail("The synthetic live canary cap must be positive and no greater than USD 2.00.")
    source = args.source.resolve()
    if not (source / "services" / "rag-api").is_dir():
        fail("--source must be the immutable CourseMate release root.")
    output = args.output.resolve()
    if output.exists():
        fail("Refusing to overwrite an existing canary output directory.")
    if not os.environ.get("V3_MODEL_API_KEY") or not os.environ.get("V3_MODEL_BASE_URL"):
        fail("The protected Qwen credential/base URL is unavailable.")

    # Keep all generated state outside the immutable application release and the
    # production data roots. The test source has no uploaded files or retrieval
    # evidence, therefore the model receives only the synthetic course fields.
    output.mkdir(mode=0o700, parents=True)
    rag_database = output / "rag.sqlite3"
    ui_data = output / "ui"
    os.environ.update(
        {
            "CMUI_ENV": "development",
            "CMUI_PROVIDER_MODE": "qwen",
            "CMUI_ALLOW_BILLABLE": "true",
            "CMUI_QWEN_BASE_URL": os.environ["V3_MODEL_BASE_URL"],
            "CMUI_QWEN_API_KEY": os.environ["V3_MODEL_API_KEY"],
            "CMUI_COVERAGE_REVIEWER": "none",
            "CMUI_DATA_DIR": str(ui_data),
            "CMUI_OPERATION_USD_BASELINE": "0.20",
            "CMUI_OPERATION_INPUT_USD_PER_MILLION": "2",
            "CMUI_OPERATION_OUTPUT_USD_PER_MILLION": "6",
            "CMUI_IMAGE_MAX_PIXELS": "2621440",
            "CMUI_CAMPUS_QUALIFICATION_POLICY": "registered_active",
        }
    )

    import sys

    sys.path.insert(0, str(source / "services" / "rag-api"))
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from pydantic import SecretStr  # noqa: PLC0415
    from app.config import Settings  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415

    class SyntheticEmbedding:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0] for _ in texts]

    settings = Settings(
        _env_file=None,
        database_path=rag_database,
        upload_dir=output / "uploads",
        admin_user_ids="release-canary-user",
        app_env="test",
        auth_test_user_id="release-canary-user",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        v3_model="qwen3.8-max",
        v3_model_api_key=SecretStr(os.environ["V3_MODEL_API_KEY"]),
        v3_model_base_url=os.environ["V3_MODEL_BASE_URL"],
        ui_web_dir=output / "no-static-build",
        web_origin="http://127.0.0.1:8199",
    )
    application = create_app(settings=settings, embedding_provider=SyntheticEmbedding())
    api = "/ui-extension/api/ui/v1"
    headers = {"Authorization": "Bearer test-session-token"}
    report: dict[str, Any] = {
        "artifact_version": "four-changes-live-ui-canary-v1",
        "status": "RUNNING",
        "environment": "isolated synthetic RAG/UI databases; exact immutable release source",
        "application_release": source.name,
        "provider": "qwen3.8-max",
        "authorized_max_live_usd": str(args.max_live_usd),
        "model_calls_authorized": 5,
        "operations": [],
    }

    try:
        with TestClient(application) as client:
            course = client.post(
                "/api/courses",
                headers=headers,
                json={"id": "cs3481", "name": "Synthetic DBSCAN Release Canary", "description": "No private materials."},
            )
            course.raise_for_status()

            def conversation(lane: str) -> str:
                response = client.post(f"{api}/conversations", headers=headers, json={"course": "cs3481", "lane": lane})
                response.raise_for_status()
                return response.json()["id"]

            def operation(label: str, lane: str, text: str, mode: str, strength: str) -> dict[str, Any]:
                conv = conversation(lane)
                start = client.post(
                    f"{api}/conversations/{conv}/runs",
                    headers=headers,
                    json={
                        "text": text,
                        "request_id": f"release-live-{label}-001",
                        "teaching_mode": mode,
                        "reasoning_strength": strength,
                    },
                )
                start.raise_for_status()
                initial = start.json()
                run = terminal(client, api, initial["id"], headers)
                record = {
                    "label": label,
                    "lane": lane,
                    "requested_mode": mode,
                    "effective_mode": run["teaching_mode"],
                    "strength": run["reasoning_strength"],
                    "initial_application_budget_usd": initial.get("application_budget_usd"),
                    "status": run["status"],
                    "public_generated_prompt_present": "generated_prompt" in run,
                    "response_text_chars": len(str(run.get("partial_text", ""))),
                    "usage": numeric_usage(run),
                }
                if run["status"] != "completed":
                    fail(f"{label} completed with terminal state {run['status']}.")
                report["operations"].append(record)
                return {"run": run, "record": record}

            normal = operation("normal-medium", "teach", "请用中文简要说明 DBSCAN 的核心点定义。", "normal", "medium")
            thinking = operation("thinking-medium", "teach", "请用中文解释 DBSCAN 如何从核心点扩张聚类，保留英文术语。", "thinking", "medium")
            high = operation("problem-high", "problem", "请给出一个 DBSCAN 参数判断小题的四步标准解答。", "normal", "high")
            maximum = operation("normal-max", "teach", "一句话说明 DBSCAN 的 eps 是什么。", "normal", "max")

            ui_db = application.state.ui_extension_app.state.db
            with ui_db.connect() as connection:
                planned = connection.execute("SELECT generated_prompt FROM cmui_runs WHERE id=?", (thinking["run"]["id"],)).fetchone()[0]
                high_cap = connection.execute("SELECT application_budget_usd FROM cmui_runs WHERE id=?", (high["run"]["id"],)).fetchone()[0]
                max_cap = connection.execute("SELECT application_budget_usd FROM cmui_runs WHERE id=?", (maximum["run"]["id"],)).fetchone()[0]
                bridge_rows = connection.execute("SELECT count(*) FROM cmui_bridges").fetchone()[0]
            if not isinstance(planned, str) or not planned.strip():
                fail("Thinking canary did not persist its stage-one prompt.")
            if high_cap != "0.40" or max_cap is not None:
                fail("Reasoning-strength caps were not persisted as high=0.40 and max=null.")
            report["thinking_prompt_saved_chars"] = len(planned)
            report["high_application_cap"] = high_cap
            report["max_application_cap"] = max_cap
            report["new_bridge_rows"] = bridge_rows
            report["status"] = "LIVE_QWEN_CALLS_COMPLETED"
    except Exception as error:
        report["status"] = "FAILED_OR_UNKNOWN_COST"
        report["failure_class"] = type(error).__name__
        report["failure"] = str(error)[:240]
        raise
    finally:
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("FOUR_CHANGES_LIVE_CANARY=ok operations=4 authorized_provider_calls=5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
