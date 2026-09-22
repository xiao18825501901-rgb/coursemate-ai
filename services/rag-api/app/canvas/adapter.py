"""Stateless, read-only Canvas adapter.

Adapted from `hairoom/canvas-study-assistant-skill` (MIT, Copyright (c) 2026 Hairong
Zheng) at commit `f05ffae8e98d3d6860695abe11c59c52718dd277` **plus the owner's local
`canvas_study/runtime.py` patch** that widens student-course discovery to
`enrollment_state=completed` while re-applying the student-type filter. See
`UPSTREAM_NOTICE.md` for the attribution and the list of what was and was not reused.

What the upstream skill does *not* give a multi-user service, and what this module
therefore does differently:

* no global state — no `config.json`, no `CANVAS_ASSISTANT_HOME`, no module-level
  singleton client, no shared session file and no shared cache. Connection context
  (`connection_id`, `origin`, `token_provider`) is injected per instance, so two users'
  requests cannot affect each other;
* no OS keychain / Windows Credential Manager access — tokens come from an injected
  provider that reads the server-side credential store;
* learning APIs are **GET only**, enforced in the single request path, and the reachable
  endpoints are an allow-list rather than "any path";
* every request target, every pagination link and every download hop passes the rules in
  `http_safety`, and the download client never carries a Canvas `Authorization` header.

This module performs no retries: retry/backoff belongs to the job layer (see
`docs/coursejesus/CANVAS_IMPORT_JOB_CONTRACT.md`), which needs `Retry-After` and the
error category rather than a hidden retry loop.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from .http_safety import (
    UnsafeUrlError,
    validate_api_url,
    validate_download_target,
)
from .registry import InstitutionConnectionRegistry

GET = "GET"

# The endpoints this product may call, and nothing else. Each entry corresponds to a
# documented read the student's own authorisation already permits; there is no
# general-purpose pass-through and no way to discover new endpoints at runtime. They are
# matched as exact patterns, not prefixes: a prefix would have let
# `/api/v1/courses/:id/assignments`, `/submissions` and everything else under a course
# through, which is precisely the "dynamic endpoint discovery" the pack forbids.
ALLOWED_ENDPOINTS: tuple[str, ...] = (
    "/api/v1/users/self/profile",
    "/api/v1/users/self/enrollments",
    "/api/v1/courses",
    "/api/v1/courses/:course_id/files",
    "/api/v1/courses/:course_id/files/:file_id",
    "/api/v1/courses/:course_id/folders",
    "/api/v1/courses/:course_id/modules",
    "/api/v1/courses/:course_id/modules/:module_id/items",
    "/api/v1/files/:file_id",
    "/api/v1/folders/:folder_id/files",
)
ALLOWED_ENDPOINT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/v1/users/self/profile$"),
    re.compile(r"^/api/v1/users/self/enrollments$"),
    re.compile(r"^/api/v1/courses$"),
    re.compile(r"^/api/v1/courses/\d+/files$"),
    re.compile(r"^/api/v1/courses/\d+/files/\d+$"),
    re.compile(r"^/api/v1/courses/\d+/folders$"),
    re.compile(r"^/api/v1/courses/\d+/modules$"),
    re.compile(r"^/api/v1/courses/\d+/modules/\d+/items$"),
    re.compile(r"^/api/v1/files/\d+$"),
    re.compile(r"^/api/v1/folders/\d+/files$"),
)
FORBIDDEN_METHODS = ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

# Error categories the job layer records per file (CANVAS_IMPORT_JOB_CONTRACT.md §4).
EXPIRED_TOKEN = "EXPIRED_TOKEN"
FORBIDDEN = "FORBIDDEN"
NOT_FOUND = "NOT_FOUND"
RATE_LIMIT = "RATE_LIMIT"
SERVER_ERROR = "SERVER_ERROR"
NETWORK = "NETWORK"
INVALID_RESPONSE = "INVALID_RESPONSE"

STATUS_CATEGORIES = {
    401: EXPIRED_TOKEN,
    403: FORBIDDEN,
    404: NOT_FOUND,
    429: RATE_LIMIT,
}


class CanvasReadError(RuntimeError):
    """A classified read failure. `category` is stable; `detail` is for humans."""

    def __init__(self, category: str, detail: str, *, status: int | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(f"{category}: {detail}")
        self.category = category
        self.detail = detail
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        """Only rate limiting and transient network failures may be retried.

        A `403` is never retryable: the pack is explicit that a hidden or locked course
        must not be re-probed in the hope that it becomes readable.
        """
        return self.category in (RATE_LIMIT, NETWORK, SERVER_ERROR)


@dataclass(frozen=True)
class CanvasProfile:
    id: str
    name: str
    sortable_name: str = ""
    primary_email: str = ""


@dataclass(frozen=True)
class CanvasCourse:
    id: str
    name: str
    course_code: str = ""
    workflow_state: str = ""
    enrollment_states: tuple[str, ...] = ()
    term: str = ""

    @property
    def is_readable_history(self) -> bool:
        """A completed course is still readable material, not a failure (pack §9)."""
        return self.workflow_state in ("available", "completed")


@dataclass(frozen=True)
class CanvasFileEntry:
    id: str
    display_name: str
    size: int
    updated_at: str = ""
    folder_id: str = ""
    content_type: str = ""
    url_present: bool = False


@dataclass(frozen=True)
class DownloadResult:
    path: pathlib.Path
    bytes_written: int
    sha256: str
    content_type: str = ""
    hops: int = 0


@dataclass
class _Page:
    # JSON payloads: typed as Any on purpose, so the runtime `isinstance(item, dict)`
    # checks stay meaningful instead of being optimised away by the type checker.
    items: list[Any] = field(default_factory=list)
    next_url: str | None = None


def parse_next_link(link_header: str | None) -> str | None:
    """Return the `rel="next"` URL from a Canvas `Link` header, if any."""
    if not link_header:
        return None
    for part in link_header.split(","):
        segments = [segment.strip() for segment in part.split(";")]
        if not segments:
            continue
        url = segments[0].strip("<>").strip()
        if any(segment.lower() in ('rel="next"', "rel=next") for segment in segments[1:]):
            return url
    return None


class CanvasReadAdapter:
    """Read-only Canvas access for exactly one connection.

    Every instance is bound to one connection, one institution origin and one token
    provider. Nothing is cached between instances, and nothing is read from the process
    environment beyond the registry's availability check.
    """

    def __init__(
        self,
        *,
        connection_id: str,
        origin: str,
        token_provider: Callable[[], str | None],
        registry: InstitutionConnectionRegistry,
        client: httpx.Client | None = None,
        download_client: httpx.Client | None = None,
        per_page: int = 100,
        max_pages: int = 50,
        max_download_bytes: int = 512 * 1024 * 1024,
        max_redirect_hops: int = 5,
        resolver: Callable[..., Sequence[tuple[Any, ...]]] | None = None,
    ) -> None:
        if not connection_id:
            raise ValueError("connection_id is required")
        self.connection_id = connection_id
        self.institution = registry.by_origin(origin)
        self.origin = self.institution.origin
        self._token_provider = token_provider
        self.per_page = per_page
        self.max_pages = max_pages
        self.max_download_bytes = max_download_bytes
        self.max_redirect_hops = max_redirect_hops
        self._resolver = resolver
        self._client = client or httpx.Client(
            base_url=self.origin, timeout=30.0, follow_redirects=False
        )
        # Deliberately a second client with no default Authorization header: a signed
        # download URL is served by the CDN, which must never see the Canvas token.
        self._download_client = download_client or httpx.Client(
            timeout=60.0, follow_redirects=False
        )

    # ---------------------------------------------------------------- request path
    def _request(
        self, method: str, path: str, params: Sequence[tuple[str, str]] | None = None
    ) -> httpx.Response:
        """The single request path: GET only, allow-listed, token in the header only."""
        if method != GET:
            raise CanvasReadError(
                FORBIDDEN, f"{method} is not available: the Canvas surface is read-only"
            )
        url = path if path.startswith("https://") else f"{self.origin}{path}"
        try:
            validate_api_url(
                url,
                allowed_origin=self.origin,
                allowed_patterns=ALLOWED_ENDPOINT_PATTERNS,
            )
        except UnsafeUrlError as error:
            raise CanvasReadError(FORBIDDEN, f"refused url: {error}") from error
        token = self._token_provider()
        if not token:
            raise CanvasReadError(EXPIRED_TOKEN, "no usable credential for this connection")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        # `params` is passed only when it has entries: httpx rebuilds the query string from
        # it, so an empty list would silently drop the query of a followed next-link and the
        # reader would re-fetch the first page forever. The adapter's own pagination test
        # caught exactly that.
        request_params: list[tuple[str, str | int | float | bool | None]] | None = (
            list(params) if params else None
        )
        try:
            response = self._client.get(url, params=request_params, headers=headers)
        except httpx.HTTPError as error:
            raise CanvasReadError(NETWORK, f"{type(error).__name__}: {error}") from error
        if response.status_code >= 400:
            raise self._classify(response)
        return response

    @staticmethod
    def _classify(response: httpx.Response) -> CanvasReadError:
        status = response.status_code
        category = STATUS_CATEGORIES.get(status)
        if category is None:
            category = SERVER_ERROR if status >= 500 else INVALID_RESPONSE
        retry_after: float | None = None
        if category == RATE_LIMIT:
            raw = response.headers.get("Retry-After", "")
            try:
                retry_after = float(raw)
            except ValueError:
                retry_after = None
        return CanvasReadError(
            category, f"Canvas answered {status}", status=status, retry_after=retry_after
        )

    def _pages(self, path: str, params: Sequence[tuple[str, str]] | None = None) -> _Page:
        """One page, with the next link validated against the same institution origin."""
        response = self._request(GET, path, params)
        try:
            payload = response.json()
        except ValueError as error:
            raise CanvasReadError(INVALID_RESPONSE, f"Canvas returned non-JSON: {error}") from error
        if not isinstance(payload, list):
            raise CanvasReadError(INVALID_RESPONSE, "expected a list from a paged endpoint")
        next_url = parse_next_link(response.headers.get("Link"))
        if next_url:
            try:
                validate_api_url(
                    next_url,
                    allowed_origin=self.origin,
                    allowed_patterns=ALLOWED_ENDPOINT_PATTERNS,
                )
            except UnsafeUrlError as error:
                raise CanvasReadError(
                    FORBIDDEN, f"refused pagination link: {error}"
                ) from error
        return _Page(items=list(payload), next_url=next_url)

    def _iter_pages(
        self, path: str, params: Sequence[tuple[str, str]] | None = None
    ) -> Iterator[Any]:
        """Follow `rel="next"` to the end, bounded by `max_pages`."""
        url = path
        query: Sequence[tuple[str, str]] | None = list(params or ())
        pages = 0
        while url and pages < self.max_pages:
            page = self._pages(url, query)
            pages += 1
            yield from page.items
            follow: str | None = page.next_url
            url = follow or ""
            query = None  # the next link already carries the query string
        if url:
            raise CanvasReadError(
                INVALID_RESPONSE,
                f"pagination exceeded max_pages={self.max_pages}; refusing to read more",
            )

    # ------------------------------------------------------------------- read API
    def profile(self) -> CanvasProfile:
        response = self._request(GET, "/api/v1/users/self/profile")
        payload = response.json()
        if not isinstance(payload, dict):
            raise CanvasReadError(INVALID_RESPONSE, "profile was not an object")
        return CanvasProfile(
            id=str(payload.get("id", "")),
            name=str(payload.get("name", "")),
            sortable_name=str(payload.get("sortable_name", "")),
            primary_email=str(payload.get("primary_email", "")),
        )

    def student_courses(
        self, states: Sequence[str] = ("active", "completed")
    ) -> list[CanvasCourse]:
        """Courses with a real student enrollment, across the requested states.

        `enrollment_state` (active / completed) and `course.workflow_state` are separate
        facts and are both recorded: a course whose term has ended is still readable
        history, and "no current-term enrollment" must not deny a student their past.
        Results are de-duplicated by course id, keeping every state that was observed.
        """
        by_id: dict[str, dict[str, Any]] = {}
        for state in states:
            params = [
                ("enrollment_state", state),
                ("include[]", "enrollments"),
                ("include[]", "term"),
                ("per_page", str(self.per_page)),
            ]
            for item in self._iter_pages("/api/v1/courses", params):
                if not isinstance(item, dict):
                    continue
                course_id = str(item.get("id", ""))
                if not course_id:
                    continue
                enrollments = item.get("enrollments") or []
                student_states = [
                    str(enrollment.get("enrollment_state", state))
                    for enrollment in enrollments
                    if isinstance(enrollment, dict)
                    and (
                        enrollment.get("type") == "student"
                        or enrollment.get("role") == "StudentEnrollment"
                    )
                ]
                if not student_states:
                    # Not a student on this course: skip rather than borrow the token's
                    # other roles to read someone else's material.
                    continue
                entry = by_id.setdefault(course_id, {"item": item, "states": []})
                entry["states"].extend(student_states)
                entry["item"] = item
        return [self._to_course(entry["item"], entry["states"]) for entry in by_id.values()]

    @staticmethod
    def _to_course(item: dict[str, Any], states: Sequence[str]) -> CanvasCourse:
        term = item.get("term") or {}
        return CanvasCourse(
            id=str(item.get("id", "")),
            name=str(item.get("name", "")),
            course_code=str(item.get("course_code", "")),
            workflow_state=str(item.get("workflow_state", "")),
            enrollment_states=tuple(sorted(set(states))),
            term=str(term.get("name", "")) if isinstance(term, dict) else "",
        )

    def course_files(self, course_id: str) -> list[CanvasFileEntry]:
        """File metadata for one selected course, paged to the end."""
        if not course_id or not str(course_id).isdigit():
            raise CanvasReadError(INVALID_RESPONSE, f"invalid course id {course_id!r}")
        params = [("per_page", str(self.per_page))]
        entries = [
            self._to_file(item)
            for item in self._iter_pages(f"/api/v1/courses/{course_id}/files", params)
            if isinstance(item, dict)
        ]
        return [entry for entry in entries if entry.id]

    @staticmethod
    def _to_file(item: dict[str, Any]) -> CanvasFileEntry:
        return CanvasFileEntry(
            id=str(item.get("id", "")),
            display_name=str(item.get("display_name", "")),
            size=int(item.get("size") or 0),
            updated_at=str(item.get("updated_at", "")),
            folder_id=str(item.get("folder_id", "")),
            content_type=str(item.get("content-type", "")),
            url_present=bool(item.get("url")),
        )

    # ------------------------------------------------------------------- download
    def download(self, url: str, sink: pathlib.Path) -> DownloadResult:
        """Fetch a signed download URL with a client that carries no Canvas token.

        Every hop is validated (HTTPS, allowed host for this institution, public target)
        and the response is streamed to `sink` with a hard byte limit and a SHA-256 of the
        bytes actually written. Redirects are followed manually so that `Authorization`
        can never travel with them.
        """
        allowed_hosts = self.institution.download_hosts
        current = url
        hops = 0
        digest = hashlib.sha256()
        written = 0
        content_type = ""
        while True:
            try:
                validate_download_target(
                    current, allowed_hosts=allowed_hosts, resolver=self._resolver
                )
            except UnsafeUrlError as error:
                raise CanvasReadError(FORBIDDEN, f"refused download target: {error}") from error
            try:
                with self._download_client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location", "")
                        hops += 1
                        if hops > self.max_redirect_hops:
                            raise CanvasReadError(
                                FORBIDDEN, f"download exceeded {self.max_redirect_hops} redirects"
                            )
                        if not location:
                            raise CanvasReadError(INVALID_RESPONSE, "redirect without a location")
                        current = httpx.URL(current).join(location).__str__()
                        continue
                    if response.status_code >= 400:
                        raise self._classify(response)
                    content_type = response.headers.get("content-type", "")
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > self.max_download_bytes:
                        raise CanvasReadError(
                            FORBIDDEN,
                            f"declared size {declared} exceeds limit {self.max_download_bytes}",
                        )
                    sink.parent.mkdir(parents=True, exist_ok=True)
                    with sink.open("wb") as handle:
                        for chunk in response.iter_bytes(1024 * 256):
                            written += len(chunk)
                            if written > self.max_download_bytes:
                                raise CanvasReadError(
                                    FORBIDDEN,
                                    f"download exceeded {self.max_download_bytes} bytes",
                                )
                            digest.update(chunk)
                            handle.write(chunk)
                    return DownloadResult(
                        path=sink,
                        bytes_written=written,
                        sha256=digest.hexdigest(),
                        content_type=content_type,
                        hops=hops,
                    )
            except httpx.HTTPError as error:
                raise CanvasReadError(NETWORK, f"{type(error).__name__}: {error}") from error
