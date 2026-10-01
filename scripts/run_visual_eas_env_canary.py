"""Run one no-retry EAS /prompt canary using process environment secrets only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "rag-api"))

from app.config import Settings
from app.visual.providers.aliyun_eas import AlibabaEASComfyProvider
from app.visual.validators import validate_output
from app.visual.workflows import REGISTRY_PATH, WorkflowRegistry


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deadline-seconds", type=float, default=900.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def _save(path: Path, report: dict[str, object]) -> None:
    temporary = path.with_name("." + path.name + ".partial")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> int:
    args = _arguments()
    endpoint = os.environ.get("COMFYUI_EAS_ENDPOINT", "")
    token = os.environ.get("COMFYUI_EAS_TOKEN", "")
    if not endpoint or not token:
        print("EAS_CANARY status=ENV_MISSING")
        return 2

    Settings(
        _env_file=None,
        v3_enabled=True,
        visual_engine_enabled=True,
        visual_provider="aliyun_eas",
        visual_eas_endpoint=endpoint,
        visual_eas_token=SecretStr(token),
    )
    registry = WorkflowRegistry.load(REGISTRY_PATH)
    workflow = registry.select_by_id("coursejesus-comfy-image-v1", "1")
    provider = AlibabaEASComfyProvider(
        endpoint=endpoint,
        token=token,
        workflow=workflow,
        timeout_seconds=min(900.0, max(10.0, args.deadline_seconds)),
        max_output_bytes=10 * 1024 * 1024,
    )
    operation = "visual-env-canary-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    prompt_id = str(uuid5(NAMESPACE_URL, operation))
    output_dir = args.output_dir or ROOT / "artifacts" / "visual-phase-b" / operation
    if output_dir.exists() and any(output_dir.iterdir()):
        print("EAS_CANARY status=OUTPUT_DIR_NOT_EMPTY")
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "visual-eas-env-canary-report.json"
    compiled: dict[str, object] = {
        "positive_prompt": (
            "clean educational illustration of a binary search tree, white background, "
            "legible nodes, no watermark"
        ),
        "negative_prompt": "watermark, unreadable text, distorted diagram",
        "seed": 2026100103,
        "width": 512,
        "height": 512,
        "steps": 20,
        "cfg": 8.0,
    }
    report: dict[str, object] = {
        "operation": operation,
        "started_at": datetime.now(UTC).isoformat(),
        "prompt_attempts": 1,
        "automatic_prompt_retries": 0,
        "workflow_sha256": workflow.workflow_sha256 or "",
        "status": "SUBMITTING",
    }
    try:
        body = {
            "prompt": provider._workflow_payload(compiled),
            "client_id": prompt_id,
            "prompt_id": prompt_id,
        }
        with httpx.Client(timeout=args.deadline_seconds, follow_redirects=False) as client:
            response = client.post(
                endpoint.rstrip("/") + "/prompt",
                headers={"Authorization": token},
                json=body,
            )
            report["submit_status_code"] = response.status_code
            if response.status_code == 401:
                prefix = hashlib.sha256(token.encode()).hexdigest()[:12]
                report.update(
                    {
                        "status": "AUTHENTICATION_FAILED",
                        "token_sha256_prefix": prefix,
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                )
                _save(report_path, report)
                print(f"EAS_CANARY status=401 token_sha256_prefix={prefix}")
                return 1
            if not 200 <= response.status_code < 300:
                report.update(
                    {
                        "status": "SUBMIT_REJECTED",
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                )
                _save(report_path, report)
                print(f"EAS_CANARY status={response.status_code}")
                return 1
            payload = response.json()
            returned_id = payload.get("prompt_id") if isinstance(payload, dict) else None
            if returned_id != prompt_id:
                report.update(
                    {
                        "status": "PROMPT_ID_MISMATCH",
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                )
                _save(report_path, report)
                print("EAS_CANARY status=PROMPT_ID_MISMATCH")
                return 1
            report.update(
                {
                    "status": "ACCEPTED",
                    "provider_job_id": prompt_id,
                    "submit_accepted_at": datetime.now(UTC).isoformat(),
                }
            )
            _save(report_path, report)
            print("EAS_CANARY status=200 accepted=true prompt_attempts=1")

            deadline = time.monotonic() + args.deadline_seconds
            polls = 0
            while time.monotonic() < deadline:
                polls += 1
                history = client.get(
                    endpoint.rstrip("/") + f"/history/{prompt_id}",
                    headers={"Authorization": token},
                )
                if history.status_code != 200:
                    report.update(
                        {
                            "status": "HISTORY_FAILED",
                            "history_status_code": history.status_code,
                            "polls": polls,
                            "completed_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    _save(report_path, report)
                    print(f"EAS_CANARY history_status={history.status_code}")
                    return 1
                history_payload = history.json()
                item = (
                    history_payload.get(prompt_id)
                    if isinstance(history_payload, dict)
                    else None
                )
                if isinstance(item, dict) and item.get("outputs"):
                    outputs = item["outputs"]
                    image = outputs[str(workflow.output_node_id)]["images"][0]
                    view = client.get(
                        endpoint.rstrip("/") + "/view",
                        headers={"Authorization": token},
                        params={
                            "filename": str(image["filename"]),
                            "subfolder": str(image.get("subfolder", "")),
                            "type": str(image.get("type", "output")),
                        },
                    )
                    if view.status_code != 200:
                        report.update(
                            {
                                "status": "VIEW_FAILED",
                                "view_status_code": view.status_code,
                                "completed_at": datetime.now(UTC).isoformat(),
                            }
                        )
                        _save(report_path, report)
                        print(f"EAS_CANARY view_status={view.status_code}")
                        return 1
                    mime_type = view.headers.get("content-type", "").split(";", 1)[0].lower()
                    width, height = validate_output(
                        view.content,
                        mime_type=mime_type,
                        width=None,
                        height=None,
                        duration_seconds=None,
                        max_bytes=10 * 1024 * 1024,
                        max_width=4096,
                        max_height=4096,
                        max_duration_seconds=60.0,
                    )
                    image_path = output_dir / "visual-eas-env-canary.png"
                    image_path.write_bytes(view.content)
                    report.update(
                        {
                            "status": "PASS",
                            "completed_at": datetime.now(UTC).isoformat(),
                            "polls": polls,
                            "mime_type": mime_type,
                            "width": width,
                            "height": height,
                            "bytes": len(view.content),
                            "sha256": hashlib.sha256(view.content).hexdigest(),
                            "artifact": image_path.name,
                        }
                    )
                    _save(report_path, report)
                    print(
                        "EAS_CANARY status=PASS "
                        f"bytes={len(view.content)} "
                        f"sha256_prefix={str(report['sha256'])[:12]} polls={polls}"
                    )
                    return 0
                time.sleep(args.poll_seconds)
            report.update(
                {
                    "status": "DEADLINE_EXCEEDED",
                    "polls": polls,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )
            _save(report_path, report)
            print("EAS_CANARY status=DEADLINE_EXCEEDED")
            return 1
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        report.update(
            {
                "status": type(error).__name__.upper(),
                "completed_at": datetime.now(UTC).isoformat(),
            }
        )
        _save(report_path, report)
        print(f"EAS_CANARY status={report['status']}")
        return 1
    finally:
        endpoint = ""
        token = ""


if __name__ == "__main__":
    raise SystemExit(main())
