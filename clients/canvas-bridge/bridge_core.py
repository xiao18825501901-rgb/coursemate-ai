from __future__ import annotations

import base64
import json
import platform
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from app.canvas.adapter import CanvasReadAdapter
from app.canvas.registry import InstitutionConnectionRegistry


TICKET_PREFIX = "coursejesus-canvas-bridge:v1:"
TICKET_KIND = "coursejesus.canvas-bridge-ticket"
TRUSTED_API_ORIGINS = frozenset({"https://rag.coursejesus.com", "https://rag.qqttai.com"})
TRUSTED_CANVAS_ORIGINS = {
    "cityu": "https://canvas.cityu.edu.hk",
    "cityu-dg": "https://cityu-dg.instructure.com",
}
TERMINAL = frozenset({"COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED", "EXPIRED"})


class BridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConnectionTicket:
    api_origin: str
    session_id: str
    code: str
    institution_key: str
    institution_origin: str
    expires_at: str


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise BridgeError("连接信息中的服务地址无效。")
    if parsed.port not in (None, 443) or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise BridgeError("连接信息中的服务地址不是受支持的 HTTPS Origin。")
    return f"https://{parsed.hostname.lower()}"


def decode_ticket(value: str) -> ConnectionTicket:
    raw = value.strip()
    if not raw.startswith(TICKET_PREFIX):
        raise BridgeError("连接信息格式不正确，请从 CourseJesus 网页重新复制完整内容。")
    encoded = raw[len(TICKET_PREFIX):]
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BridgeError("连接信息无法解析，请从网页重新生成。") from error
    if not isinstance(payload, dict) or payload.get("kind") != TICKET_KIND or payload.get("version") != 1:
        raise BridgeError("连接信息版本不受支持，请下载网页提供的最新工具。")
    api_origin = _origin(str(payload.get("apiOrigin") or ""))
    if api_origin not in TRUSTED_API_ORIGINS:
        raise BridgeError("连接信息不是来自受信任的 CourseJesus API。")
    institution_key = str(payload.get("institutionKey") or "")
    institution_origin = _origin(str(payload.get("institutionOrigin") or ""))
    if TRUSTED_CANVAS_ORIGINS.get(institution_key) != institution_origin:
        raise BridgeError("连接信息中的学校与受信任 Canvas 地址不匹配。")
    session_id = str(payload.get("sessionId") or "")
    code = str(payload.get("code") or "")
    if not re.fullmatch(r"cls_[0-9a-f]{32}", session_id) or len(code) < 24:
        raise BridgeError("连接信息缺少有效的会话标识或一次性代码。")
    expires_at = str(payload.get("expiresAt") or "")
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise BridgeError("连接信息缺少有效的到期时间，请在网页重新生成。") from error
    if expires.tzinfo is None or expires.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise BridgeError("连接信息已经过期，请在网页重新生成。")
    return ConnectionTicket(
        api_origin=api_origin,
        session_id=session_id,
        code=code,
        institution_key=institution_key,
        institution_origin=institution_origin,
        expires_at=expires_at,
    )


def decode_connection(
    value: str,
    *,
    legacy_api_origin: str = "",
    legacy_institution_key: str = "",
) -> ConnectionTicket:
    """Decode a v1 ticket, or an old bare code only with explicit known targets."""
    raw = value.strip()
    if raw.startswith(TICKET_PREFIX):
        return decode_ticket(raw)
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,200}", raw):
        raise BridgeError("连接信息格式不正确，请从 CourseJesus 网页复制完整内容。")
    api_origin = _origin(legacy_api_origin)
    if api_origin not in TRUSTED_API_ORIGINS:
        raise BridgeError("旧连接码必须明确选择受信任的 CourseJesus 服务地址。")
    institution_origin = TRUSTED_CANVAS_ORIGINS.get(legacy_institution_key, "")
    if not institution_origin:
        raise BridgeError("旧连接码必须明确选择学校 Canvas。")
    return ConnectionTicket(
        api_origin=api_origin,
        session_id="",
        code=raw,
        institution_key=legacy_institution_key,
        institution_origin=institution_origin,
        expires_at="",
    )


class CourseJesusClient:
    def __init__(self, ticket: ConnectionTicket) -> None:
        self.ticket = ticket
        self._session_id = ticket.session_id
        self._token = ""
        self._client = httpx.Client(base_url=ticket.api_origin, timeout=120.0, follow_redirects=False)

    def close(self) -> None:
        self._token = ""
        self._client.close()

    @staticmethod
    def _body(response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json" and not content_type.endswith("+json"):
            raise BridgeError(f"CourseJesus 返回了非 JSON 响应（HTTP {response.status_code}）。")
        try:
            body = response.json()
        except ValueError as error:
            raise BridgeError("CourseJesus 返回的数据无法解析。") from error
        if not isinstance(body, dict):
            raise BridgeError("CourseJesus 返回的数据格式不正确。")
        if response.is_error:
            detail = body.get("error") if isinstance(body.get("error"), dict) else {}
            raise BridgeError(str(detail.get("message") or f"CourseJesus 请求失败（HTTP {response.status_code}）。"))
        return body

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise BridgeError("本地 Bridge 会话尚未建立。")
        return {"Authorization": f"CourseJesusBridge {self._token}"}

    def claim(self, *, canvas_user_id: str, canvas_display_name: str) -> None:
        response = self._client.post(
            "/api/integrations/canvas/local-sessions/bridge/claim",
            json={
                "code": self.ticket.code,
                "canvas_user_id": canvas_user_id,
                "canvas_display_name": canvas_display_name,
                "host_label": platform.node()[:120],
            },
        )
        body = self._body(response)
        session_id = str(body.get("sessionId") or "")
        if not re.fullmatch(r"cls_[0-9a-f]{32}", session_id):
            raise BridgeError("CourseJesus 没有返回可识别的会话。")
        if self.ticket.session_id and session_id != self.ticket.session_id:
            raise BridgeError("CourseJesus 返回的会话与网页连接信息不一致。")
        if (
            body.get("institutionKey") != self.ticket.institution_key
            or body.get("institutionOrigin") != self.ticket.institution_origin
        ):
            raise BridgeError("CourseJesus 返回的学校与本地确认目标不一致。")
        token = body.get("bridgeToken")
        if not isinstance(token, str) or len(token) < 32:
            raise BridgeError("CourseJesus 没有返回可用的本地会话凭证。")
        self._session_id = session_id
        self._token = token

    @property
    def session_id(self) -> str:
        if not self._session_id:
            raise BridgeError("本地 Bridge 会话尚未建立。")
        return self._session_id

    def discovery(self, courses: list[dict[str, Any]]) -> None:
        response = self._client.post(
            f"/api/integrations/canvas/local-sessions/bridge/{self.session_id}/discovery",
            headers=self._headers(),
            json={"courses": courses},
        )
        self._body(response)

    def selection(self) -> dict[str, Any]:
        response = self._client.get(
            f"/api/integrations/canvas/local-sessions/bridge/{self.session_id}/selection",
            headers=self._headers(),
        )
        return self._body(response)

    def upload(self, course_id: str, entry: Any, path: Path, digest: str, size: int) -> dict[str, Any]:
        with path.open("rb") as stream:
            response = self._client.post(
                f"/api/integrations/canvas/local-sessions/bridge/{self.session_id}/files",
                headers=self._headers(),
                data={
                    "canvas_course_id": course_id,
                    "canvas_file_id": entry.id,
                    "display_name": entry.display_name,
                    "declared_size": str(size),
                    "declared_sha256": digest,
                    "source_updated_at": entry.updated_at,
                },
                files={"file": (entry.display_name, stream, entry.content_type or "application/octet-stream")},
            )
        return self._body(response)

    def finish(self) -> dict[str, Any]:
        response = self._client.post(
            f"/api/integrations/canvas/local-sessions/bridge/{self.session_id}/finish",
            headers=self._headers(),
        )
        return self._body(response)


def run_bridge(
    connection_text: str,
    canvas_token: str,
    *,
    on_status: Callable[[str], None],
    cancel: Event,
    legacy_api_origin: str = "",
    legacy_institution_key: str = "",
) -> dict[str, Any]:
    ticket = decode_connection(
        connection_text,
        legacy_api_origin=legacy_api_origin,
        legacy_institution_key=legacy_institution_key,
    )
    if not canvas_token.strip():
        raise BridgeError("请输入 Canvas Token。")
    registry = InstitutionConnectionRegistry()
    api = CourseJesusClient(ticket)
    try:
        with (
            httpx.Client(base_url=ticket.institution_origin, timeout=30.0, follow_redirects=False) as canvas_http,
            httpx.Client(timeout=120.0, follow_redirects=False) as download_http,
        ):
            adapter = CanvasReadAdapter(
                connection_id=ticket.session_id or "legacy-local-bridge",
                origin=ticket.institution_origin,
                token_provider=lambda: canvas_token,
                registry=registry,
                client=canvas_http,
                download_client=download_http,
            )
            on_status("正在验证 Canvas Token 并读取学生身份…")
            profile = adapter.profile()
            courses = adapter.student_courses()
            if not profile.id:
                raise BridgeError("Canvas 没有返回可识别的学生身份。")
            if not courses:
                raise BridgeError("Canvas 没有返回当前 Token 可读取的学生课程。")
            if cancel.is_set():
                raise BridgeError("已取消。")
            api.claim(canvas_user_id=profile.id, canvas_display_name=profile.name)
            course_payload = [
                {
                    "canvas_course_id": course.id,
                    "name": course.name,
                    "course_code": course.course_code,
                    "term": course.term,
                    "enrollment_state": ",".join(course.enrollment_states),
                    "workflow_state": course.workflow_state,
                    "file_count": 0,
                    "size_bytes": 0,
                }
                for course in courses
            ]
            api.discovery(course_payload)
            on_status(f"已读取 {len(courses)} 门课程。请回到网页选择要导入的课程。")
            selected: list[str] = []
            while not cancel.is_set():
                state = api.selection()
                status = str(state.get("status") or "")
                if status in TERMINAL:
                    raise BridgeError(f"网页端会话已结束：{status}")
                selected = [str(item) for item in state.get("selectedCourseIds") or []]
                if selected:
                    break
                time.sleep(1.5)
            if cancel.is_set():
                raise BridgeError("已取消。")
            by_id = {course.id: course for course in courses}
            receipts: list[dict[str, Any]] = []
            with tempfile.TemporaryDirectory(prefix="coursejesus-canvas-") as temp_dir:
                for course_id in selected:
                    course = by_id.get(course_id)
                    if course is None:
                        raise BridgeError("网页选择了本次 Canvas 列表之外的课程。")
                    entries = adapter.course_files(course_id)
                    on_status(f"{course.name}：发现 {len(entries)} 个文件。")
                    for index, entry in enumerate(entries, start=1):
                        if cancel.is_set():
                            raise BridgeError("已取消。")
                        on_status(f"{course.name}：正在处理 {index}/{len(entries)} · {entry.display_name}")
                        url = adapter.course_file_download_url(course_id, entry.id)
                        suffix = Path(entry.display_name).suffix[:16]
                        target = Path(temp_dir) / f"{course_id}-{entry.id}{suffix}"
                        downloaded = adapter.download(url, target)
                        receipt = api.upload(
                            course_id,
                            entry,
                            target,
                            downloaded.sha256,
                            downloaded.bytes_written,
                        )
                        receipts.append(receipt)
            result = api.finish()
            on_status(f"导入结束：{result.get('status', 'UNKNOWN')}，共处理 {len(receipts)} 个文件。")
            return {"courses": len(selected), "files": len(receipts), **result}
    finally:
        api.close()
