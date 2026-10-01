from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.cm_update.auth import current_user
from app.course_access import require_course_access
from app.errors import ApiError
from app.visual.service import FrozenVisualInput, VisualQuotaExceeded, VisualService
from app.visual.store import IdempotencyConflict, VisualStateConflict

User = Annotated[dict, Depends(current_user)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateVisualRequest(StrictRequest):
    request_id: str = Field(min_length=8, max_length=200)
    pair_id: str = Field(min_length=1, max_length=200)
    action: Literal["auto", "diagram", "visual", "animate"]


class RetryVisualRequest(StrictRequest):
    request_id: str = Field(min_length=8, max_length=200)


def _authorize_course(request: Request, course_id: str, user_id: str):
    host = request.app.state.visual_host_app
    try:
        return require_course_access(
            host.state.database,
            course_id,
            owner_user_id=user_id,
            is_admin=user_id in host.state.settings.admin_user_id_set,
        )
    except ApiError as error:
        raise HTTPException(error.status_code, "课程不存在或无权访问") from None


def _owned_message(ui_db, *, user_id: str, course_id: str, pair_id: str, message_id: str):
    pair = ui_db.one(
        "SELECT * FROM cmui_pairs WHERE id=? AND owner=? AND course=?",
        (pair_id, user_id, course_id),
    )
    if not pair:
        raise HTTPException(404, "学习会话不存在")
    message = ui_db.one(
        "SELECT m.*,m.rowid AS message_rowid,c.course,c.owner,c.lane "
        "FROM cmui_messages m JOIN cmui_conversations c ON c.id=m.conversation "
        "WHERE m.id=? AND c.owner=? AND c.course=? AND "
        "(c.id=? OR c.id=?)",
        (
            message_id,
            user_id,
            course_id,
            pair.get("teach_conversation"),
            pair.get("problem_conversation"),
        ),
    )
    if not message or message["role"] != "assistant":
        raise HTTPException(404, "可视化所对应的回答不存在")
    question = ui_db.one(
        "SELECT text FROM cmui_messages WHERE conversation=? AND role='user' "
        "AND rowid<? ORDER BY rowid DESC LIMIT 1",
        (message["conversation"], message["message_rowid"]),
    )
    return pair, message, (question["text"] if question else "Visualise this answer")


def _evidence(message: dict) -> tuple[dict[str, str], ...]:
    try:
        citations = json.loads(message.get("citations") or "[]")
    except (TypeError, json.JSONDecodeError):
        citations = []
    values: list[dict[str, str]] = []
    for index, item in enumerate(citations[:16]):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("document_id") or item.get("id") or f"citation-{index + 1}")
        version = str(
            item.get("document_version_id")
            or item.get("source_version")
            or item.get("sha256")
            or "ui-citation-v1"
        )
        values.append(
            {
                "source_id": source_id,
                "source_version": version,
                "locator": str(item.get("page") or item.get("locator") or "citation"),
                "supported_claim": str(
                    item.get("claim") or item.get("name") or "Cited course evidence."
                ),
            }
        )
    return tuple(values)


def _project(service: VisualService, job: dict[str, object], *, user_id: str) -> dict[str, object]:
    assets = service.store.assets_for_job(str(job["id"]), user_id=user_id)
    return {
        "id": job["id"],
        "parent_job_id": job["parent_job_id"],
        "request_id": job["request_id"],
        "course_id": job["course_id"],
        "pair_id": job["pair_id"],
        "message_id": job["message_id"],
        "action": job["action"],
        "status": job["status"],
        "renderer": job["renderer"],
        "cache_hit": bool(job["cache_hit"]),
        "retry_count": job["retry_count"],
        "fallback_available": service.fallback_available(job),
        "error_code": job["error_code"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "assets": [
            {
                "id": asset["id"],
                "type": asset["type"],
                "mime_type": asset["mime_type"],
                "width": asset["width"],
                "height": asset["height"],
                "duration_seconds": asset["duration_seconds"],
                "alt_text": asset["alt_text"],
                "semantic_validation": asset["semantic_validation"],
                "content_url": f"/visual-assets/{asset['id']}/content",
            }
            for asset in assets
        ],
    }


def visual_router(service: VisualService) -> APIRouter:
    router = APIRouter(prefix="/api/ui/v1")

    @router.post("/courses/{course_id}/messages/{message_id}/visuals", status_code=202)
    def create_visual(
        course_id: str,
        message_id: str,
        data: CreateVisualRequest,
        user: User,
        request: Request,
    ):
        course = _authorize_course(request, course_id, user["id"])
        pair, message, question = _owned_message(
            request.app.state.db,
            user_id=user["id"],
            course_id=course_id,
            pair_id=data.pair_id,
            message_id=message_id,
        )
        scope_key = (
            f"private:{user['id']}"
            if course["visibility"] != "public"
            else f"course:{course_id}:public"
        )
        try:
            job, _ = service.create_job(
                FrozenVisualInput(
                    request_id=data.request_id,
                    user_id=user["id"],
                    course_id=course_id,
                    pair_id=data.pair_id,
                    message_id=message_id,
                    node_id=pair.get("bound_node"),
                    action=data.action,
                    question=question,
                    answer=message["text"],
                    evidence=_evidence(message),
                    scope_key=scope_key,
                    language=user.get("language") or "zh-CN",
                )
            )
        except IdempotencyConflict:
            raise HTTPException(409, "请求编号已用于不同的可视化") from None
        except VisualQuotaExceeded as error:
            raise HTTPException(429, "当前可视化额度或并发已满，请稍后再试") from error
        except RuntimeError as error:
            if str(error) in {"AUTO_VISUAL_DISABLED", "VISUAL_ENGINE_DISABLED"}:
                raise HTTPException(409, "当前未启用自动可视化") from None
            raise
        return _project(service, job, user_id=user["id"])

    @router.get("/visual-jobs/{job_id}")
    def get_visual_job(job_id: str, user: User, request: Request):
        job = service.store.get(job_id, user_id=user["id"])
        if job is None:
            raise HTTPException(404, "可视化任务不存在")
        _authorize_course(request, str(job["course_id"]), user["id"])
        return _project(service, job, user_id=user["id"])

    @router.post("/visual-jobs/{job_id}/cancel")
    def cancel_visual(job_id: str, user: User, request: Request):
        job = service.store.get(job_id, user_id=user["id"])
        if job is None:
            raise HTTPException(404, "可视化任务不存在")
        _authorize_course(request, str(job["course_id"]), user["id"])
        return _project(
            service,
            service.cancel_job(job_id, user["id"]),
            user_id=user["id"],
        )

    @router.post("/visual-jobs/{job_id}/retry", status_code=202)
    def retry_visual(
        job_id: str,
        data: RetryVisualRequest,
        user: User,
        request: Request,
    ):
        job = service.store.get(job_id, user_id=user["id"])
        if job is None:
            raise HTTPException(404, "可视化任务不存在")
        _authorize_course(request, str(job["course_id"]), user["id"])
        try:
            retry, _ = service.retry_job(job_id, user["id"], request_id=data.request_id)
        except (VisualStateConflict, VisualQuotaExceeded) as error:
            raise HTTPException(409, "该可视化任务当前不能重试") from error
        return _project(service, retry, user_id=user["id"])

    @router.post("/visual-jobs/{job_id}/fallback", status_code=202)
    def fallback_visual(
        job_id: str,
        data: RetryVisualRequest,
        user: User,
        request: Request,
    ):
        job = service.store.get(job_id, user_id=user["id"])
        if job is None:
            raise HTTPException(404, "可视化任务不存在")
        _authorize_course(request, str(job["course_id"]), user["id"])
        try:
            fallback, _ = service.fallback_job(job_id, user["id"], request_id=data.request_id)
        except (VisualStateConflict, VisualQuotaExceeded) as error:
            raise HTTPException(409, "该可视化任务没有可用的确定性图解") from error
        return _project(service, fallback, user_id=user["id"])

    @router.get("/courses/{course_id}/messages/{message_id}/visuals")
    def message_visuals(course_id: str, message_id: str, user: User, request: Request):
        _authorize_course(request, course_id, user["id"])
        return {
            "items": [
                _project(service, job, user_id=user["id"])
                for job in service.store.list_for_message(user["id"], course_id, message_id)
            ]
        }

    @router.get("/courses/{course_id}/pairs/{pair_id}/visuals")
    def pair_visuals(course_id: str, pair_id: str, user: User, request: Request):
        _authorize_course(request, course_id, user["id"])
        pair = request.app.state.db.one(
            "SELECT id FROM cmui_pairs WHERE id=? AND owner=? AND course=?",
            (pair_id, user["id"], course_id),
        )
        if not pair:
            raise HTTPException(404, "学习会话不存在")
        return {
            "items": [
                _project(service, job, user_id=user["id"])
                for job in service.store.list_for_pair(user["id"], course_id, pair_id)
            ]
        }

    @router.get("/visual-assets/{asset_id}/content")
    def visual_content(asset_id: str, user: User, request: Request):
        asset = service.store.get_asset(asset_id, user_id=user["id"])
        if asset is None:
            raise HTTPException(404, "视觉资源不存在")
        _authorize_course(request, str(asset["course_id"]), user["id"])
        size = int(str(asset["size_bytes"]))
        content = service.storage.read_range(
            str(asset["storage_key"]), start=0, end=max(0, size - 1)
        )
        if len(content) != size:
            raise HTTPException(503, "视觉资源暂时不可读取")
        return Response(
            content,
            media_type=str(asset["mime_type"]),
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f'inline; filename="{asset_id}"',
                "ETag": f'"{asset["sha256"]}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router


def install_visual_routes(ui_app, host_app, service: VisualService) -> None:
    """Prepend routes so an existing root StaticFiles mount cannot shadow them."""

    ui_app.state.visual_host_app = host_app
    ui_app.state.visual_engine_enabled = True
    router = visual_router(service)
    ui_app.router.routes[:0] = list(router.routes)
