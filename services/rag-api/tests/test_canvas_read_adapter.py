"""The Canvas adapter must be read-only, isolated per connection, and un-exploitable as a proxy.

Task B3/B4 of the CourseJesus pack: only the student's own profile, own student courses
(`active` **and** `completed`), the selected courses' file metadata, and downloads derived
from verified metadata — with "no generic `/read_api?path=...`, no dynamic endpoint
discovery, no model tool that can operate Canvas", learning APIs `GET`-only, and no Canvas
token on a redirect or on the CDN download.

These tests drive a mock transport, so they assert the *client's* behaviour (what it
requests, with what headers, to which target) rather than a live Canvas instance. That is
the whole point: the security properties are properties of this code.
"""

from __future__ import annotations

import ipaddress
import json
import pathlib

import httpx
import pytest

from app.canvas import (
    CanvasReadAdapter,
    CanvasReadError,
    InstitutionConnectionRegistry,
    UnknownInstitutionError,
    default_institutions,
    is_public_address,
    normalize_origin,
    parse_next_link,
    validate_download_target,
)
from app.canvas.adapter import FORBIDDEN, INVALID_RESPONSE
from app.canvas.http_safety import normalize_canvas_page_origin

CITYU = "https://canvas.cityu.edu.hk"
CITYU_DG = "https://cityu-dg.instructure.com"


def registry() -> InstitutionConnectionRegistry:
    return InstitutionConnectionRegistry()


def public_resolver(host, *_args, **_kwargs):
    """A resolver stub that must not touch DNS.

    An IP literal resolves to itself, so the private/metadata tests still exercise the
    real `is_public_address` rule instead of being masked by a stub that answers
    "public" for everything; a hostname resolves to a public address.
    """
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return [(2, 1, 6, "", ("93.184.216.34", 0))]
    return [(2, 1, 6, "", (host, 0))]


def adapter(
    handler,
    *,
    origin: str = CITYU,
    token: str | None = "token-1",
    registry_override: InstitutionConnectionRegistry | None = None,
    **kwargs,
) -> CanvasReadAdapter:
    client = httpx.Client(
        base_url=normalize_origin(origin),
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    download_client = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )
    options: dict = {"resolver": public_resolver}
    options.update(kwargs)
    return CanvasReadAdapter(
        connection_id="conn-1",
        origin=origin,
        token_provider=lambda: token,
        registry=registry_override or registry(),
        client=client,
        download_client=download_client,
        **options,
    )


COURSES_ACTIVE = [
    {
        "id": 560,
        "name": "Problem Solve & Programming",
        "course_code": "CS2312",
        "workflow_state": "available",
        "term": {"name": "Semester B 2025_26"},
        "enrollments": [
            {"type": "student", "role": "StudentEnrollment", "enrollment_state": "active"}
        ],
    },
    {
        "id": 999,
        "name": "A course where I am a teacher",
        "course_code": "CS9999",
        "workflow_state": "available",
        "enrollments": [
            {"type": "teacher", "role": "TeacherEnrollment", "enrollment_state": "active"}
        ],
    },
]
COURSES_COMPLETED = [
    {
        "id": 240,
        "name": "Funda. of Internet App. Dev.",
        "course_code": "CS2204",
        "workflow_state": "completed",
        "term": {"name": "Semester A 2024_25"},
        "enrollments": [
            {"type": "student", "role": "StudentEnrollment", "enrollment_state": "completed"}
        ],
    }
]


def canvas_handler(request: httpx.Request) -> httpx.Response:
    """A stand-in Canvas: two course states, one file page, one profile."""
    path = request.url.path
    query = dict(request.url.params)
    if path == "/api/v1/users/self/profile":
        return httpx.Response(200, json={"id": 42, "name": "Student One"})
    if path == "/api/v1/courses":
        completed = query.get("enrollment_state") == "completed"
        items = COURSES_COMPLETED if completed else COURSES_ACTIVE
        return httpx.Response(200, json=items, headers={"Link": ""})
    if path == "/api/v1/courses/560/files":
        if query.get("page") == "2":
            return httpx.Response(
                200,
            json=[{"id": 2, "display_name": "b.pdf", "size": 2, "url": "https://files.example/b"}],
            )
        return httpx.Response(
            200,
            json=[{"id": 1, "display_name": "a.pdf", "size": 1, "url": "https://files.example/a"}],
            headers={"Link": f'<{CITYU}/api/v1/courses/560/files?page=2>; rel="next"'},
        )
    if path == "/download/a.pdf":
        return httpx.Response(200, content=b"hello", headers={"content-type": "application/pdf"})
    return httpx.Response(404, json={"errors": [{"message": "not found"}]})


# ------------------------------------------------------------------ registry
def test_availability_is_not_configured_until_a_real_key_exists(monkeypatch) -> None:
    for name in (
        "CANVAS_CITYU_CLIENT_ID",
        "CANVAS_CITYU_CLIENT_SECRET",
        "CANVAS_CITYU_DG_CLIENT_ID",
        "CANVAS_CITYU_DG_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    available = registry().availability()
    assert available == {"cityu": "NOT_CONFIGURED", "cityu-dg": "NOT_CONFIGURED"}
    # A secret in the environment alone is not enough; the pair defines the connection.
    monkeypatch.setenv("CANVAS_CITYU_CLIENT_ID", "123")
    assert registry().state_of("cityu") == "NOT_CONFIGURED"
    monkeypatch.setenv("CANVAS_CITYU_CLIENT_SECRET", "shh")
    monkeypatch.setenv("CANVAS_CITYU_DG_CLIENT_ID", "456")
    monkeypatch.setenv("CANVAS_CITYU_DG_CLIENT_SECRET", "shh")
    assert registry().state_of("cityu") == "AVAILABLE"
    assert registry().state_of("cityu-dg") == "AVAILABLE"


def test_two_institutions_never_share_a_credential_reference() -> None:
    institutions = default_institutions()
    refs = {institution.client_secret_ref for institution in institutions}
    assert len(refs) == len(institutions)
    assert all(institution.callback_url.endswith("/api/integrations/canvas/oauth/callback")
               for institution in institutions)


def test_an_unregistered_origin_is_refused() -> None:
    with pytest.raises(UnknownInstitutionError):
        registry().by_origin("https://canvas.example.edu")
    # A registered institution given with the wrong scheme is refused, not silently fixed.
    with pytest.raises(UnknownInstitutionError):
        registry().by_origin("http://canvas.cityu.edu.hk")


def test_adapter_cannot_be_pointed_at_another_institution() -> None:
    """A client passing another school's base_url must not reach a registered secret."""
    with pytest.raises(UnknownInstitutionError):
        CanvasReadAdapter(
            connection_id="c",
            origin="https://canvas.somewhere-else.edu",
            token_provider=lambda: "t",
            registry=registry(),
        )


# ------------------------------------------------------------------ read-only
def test_every_non_get_verb_is_refused_at_the_single_request_path() -> None:
    client = adapter(canvas_handler)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(CanvasReadError) as error:
            client._request(method, "/api/v1/courses/560/files")
        assert error.value.category == "FORBIDDEN"
        assert "read-only" in error.value.detail


def test_endpoints_outside_the_allow_list_are_refused() -> None:
    client = adapter(canvas_handler)
    for path in (
        "/api/v1/accounts",
        "/api/v1/courses/560/assignments",
        "/api/v1/courses/560/submissions",
        "/api/v1/users/1/messages",
        "/read_api?path=/api/v1/courses",
    ):
        with pytest.raises(CanvasReadError) as error:
            client._request("GET", path)
        assert error.value.category == "FORBIDDEN"
        assert "not an allowed Canvas endpoint" in error.value.detail


def test_an_absolute_url_on_another_host_is_refused() -> None:
    client = adapter(canvas_handler)
    with pytest.raises(CanvasReadError):
        client._request("GET", "https://evil.example/api/v1/courses")


def test_the_token_travels_only_in_the_authorization_header() -> None:
    """Pack §10: the token never appears in a query string, a log or a manifest."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"id": 1, "name": "n"})
        return httpx.Response(200, json=COURSES_ACTIVE)

    client = adapter(handler)
    client.profile()
    client.student_courses(states=("active",))
    assert seen, "expected at least one request"
    for request in seen:
        assert request.headers.get("authorization") == "Bearer token-1"
        assert "token-1" not in str(request.url)
        assert "access_token" not in str(request.url)
        assert "token" not in {key.lower() for key in request.url.params}


def test_no_token_means_expired_token_not_an_anonymous_request() -> None:
    client = adapter(canvas_handler, token=None)
    with pytest.raises(CanvasReadError) as error:
        client.profile()
    assert error.value.category == "EXPIRED_TOKEN"


# ------------------------------------------------------------------ discovery
def test_student_courses_include_completed_history_and_exclude_other_roles() -> None:
    client = adapter(canvas_handler)
    courses = client.student_courses()
    assert {course.id for course in courses} == {"560", "240"}
    assert "999" not in {course.id for course in courses}  # teacher enrollment, not student
    completed = next(course for course in courses if course.id == "240")
    assert completed.enrollment_states == ("completed",)
    assert completed.workflow_state == "completed"
    assert completed.is_readable_history is True
    assert completed.term == "Semester A 2024_25"


def test_pagination_follows_the_next_link_to_the_end() -> None:
    client = adapter(canvas_handler)
    files = client.course_files("560")
    assert [entry.id for entry in files] == ["1", "2"]


def test_a_cross_origin_pagination_link_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": '<https://evil.example/api/v1/courses/560/files?page=2>; rel="next"'},
        )

    client = adapter(handler)
    with pytest.raises(CanvasReadError) as error:
        client.course_files("560")
    assert error.value.category == "FORBIDDEN"
    assert "pagination link" in error.value.detail


def test_pagination_is_bounded_rather_than_endless() -> None:
    """A chain longer than the bound is refused, not read to the end.

    The mock chain is deliberately finite (50 pages): with the bound removed the adapter
    would read them all and return items instead of raising, which the assertion catches.
    An infinite chain would only hang the test, which proves nothing.
    """
    reached: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(dict(request.url.params).get("page", "1"))
        reached.append(page)
        link = (
            f'<{CITYU}/api/v1/courses/560/files?page={page + 1}>; rel="next"'
            if page < 50
            else ""
        )
        return httpx.Response(200, json=[{"id": page}], headers={"Link": link})

    client = adapter(handler, max_pages=3)
    with pytest.raises(CanvasReadError) as error:
        client.course_files("560")
    assert "max_pages" in error.value.detail
    assert reached == [1, 2, 3], f"expected the bound to stop after 3 pages, got {reached}"


def test_link_header_parsing_ignores_non_next_relations() -> None:
    assert parse_next_link('<https://x/2>; rel="next"') == "https://x/2"
    assert parse_next_link('<https://x/1>; rel="prev", <https://x/3>; rel="next"') == "https://x/3"
    assert parse_next_link('<https://x/9>; rel="last"') is None
    assert parse_next_link(None) is None


# ------------------------------------------------------------------ errors
def test_forbidden_is_classified_and_never_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"errors": [{"message": "locked"}]})

    client = adapter(handler)
    with pytest.raises(CanvasReadError) as error:
        client.course_files("560")
    assert error.value.category == "FORBIDDEN"
    assert error.value.status == 403
    assert error.value.retryable is False


def test_rate_limit_surfaces_retry_after_and_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "12"}, json={"errors": []})

    client = adapter(handler)
    with pytest.raises(CanvasReadError) as error:
        client.course_files("560")
    assert error.value.category == "RATE_LIMIT"
    assert error.value.retry_after == 12.0
    assert error.value.retryable is True


def test_expired_token_and_not_found_are_distinct() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        code = 401 if request.url.path.endswith("/profile") else 404
        return httpx.Response(code, json={"errors": []})

    client = adapter(handler)
    with pytest.raises(CanvasReadError) as unauthorized:
        client.profile()
    assert unauthorized.value.category == "EXPIRED_TOKEN"
    with pytest.raises(CanvasReadError) as missing:
        client.course_files("560")
    assert missing.value.category == "NOT_FOUND"


def test_non_json_body_is_reported_as_api_response_not_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>login</html>")

    client = adapter(handler)
    with pytest.raises(CanvasReadError) as error:
        client.course_files("560")
    assert error.value.category == "API_RESPONSE_NOT_JSON"


def test_profile_html_is_reported_as_api_response_not_json() -> None:
    client = adapter(lambda request: httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(CanvasReadError) as error:
        client.profile()
    assert error.value.category == "API_RESPONSE_NOT_JSON"
    assert "content-type" in error.value.detail.lower()


# ------------------------------------------------------------------ downloads
def download_handler(*, location: str | None = None, payload: bytes = b"hello"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/download/a.pdf" and location:
            return httpx.Response(302, headers={"location": location})
        return httpx.Response(200, content=payload, headers={"content-type": "application/pdf"})

    return handler


def test_download_streams_bytes_hashes_them_and_sends_no_canvas_token(
    tmp_path: pathlib.Path,
) -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, content=b"payload", headers={"content-type": "application/pdf"})

    client = adapter(handler)
    result = client.download(f"{CITYU}/download/a.pdf", tmp_path / "out.pdf")
    assert result.bytes_written == 7
    assert result.sha256 == "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5"
    assert (tmp_path / "out.pdf").read_bytes() == b"payload"
    assert all("authorization" not in headers for headers in seen)


def test_download_refuses_a_private_or_metadata_target(tmp_path: pathlib.Path) -> None:
    for host in ("127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.1.10", "[::1]"):
        client = adapter(canvas_handler, resolver=None)  # real resolver path is not reached
        url = f"https://{host}/download/a.pdf"
        with pytest.raises(CanvasReadError) as error:
            client.download(url, tmp_path / "blocked.pdf")
        assert error.value.category == "FORBIDDEN"
        assert "non-public" in error.value.detail


def test_download_refuses_a_redirect_to_a_private_target(tmp_path: pathlib.Path) -> None:
    client = adapter(download_handler(location="https://169.254.169.254/latest/meta-data/"))
    with pytest.raises(CanvasReadError) as error:
        client.download(f"{CITYU}/download/a.pdf", tmp_path / "out.pdf")
    assert error.value.category == "FORBIDDEN"
    assert "non-public" in error.value.detail


def test_download_refuses_plain_http_and_odd_ports(tmp_path: pathlib.Path) -> None:
    client = adapter(canvas_handler)
    for url in ("http://files.example/a.pdf", "https://files.example:8443/a.pdf"):
        with pytest.raises(CanvasReadError) as error:
            client.download(url, tmp_path / "out.pdf")
        assert error.value.category == "FORBIDDEN"


def test_download_is_bounded_by_the_byte_limit(tmp_path: pathlib.Path) -> None:
    client = adapter(download_handler(payload=b"x" * 100), max_download_bytes=10)
    with pytest.raises(CanvasReadError) as error:
        client.download(f"{CITYU}/download/a.pdf", tmp_path / "out.pdf")
    assert error.value.category == "FORBIDDEN"
    assert "declared size" in error.value.detail or "exceeded" in error.value.detail


def test_download_refuses_more_redirect_hops_than_allowed(tmp_path: pathlib.Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": f"{CITYU}/download/loop.pdf"})

    client = adapter(handler, max_redirect_hops=2)
    with pytest.raises(CanvasReadError) as error:
        client.download(f"{CITYU}/download/a.pdf", tmp_path / "out.pdf")
    assert "redirects" in error.value.detail


def test_download_host_allow_list_is_enforced_when_the_institution_defines_one() -> None:
    with pytest.raises(Exception) as error:
        validate_download_target(
            "https://cdn.elsewhere.example/a.pdf",
            allowed_hosts=("files.example",),
            resolver=public_resolver,
        )
    assert "not allowed" in str(error.value)


# ------------------------------------------------------------------ isolation
def test_two_adapters_do_not_share_tokens_or_state() -> None:
    """The property that the desktop skill's global config cannot provide."""
    tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tokens.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"id": 1, "name": "n"})

    client = httpx.Client(base_url=CITYU, transport=httpx.MockTransport(handler))
    other = httpx.Client(base_url=CITYU_DG, transport=httpx.MockTransport(handler))
    first = CanvasReadAdapter(
        connection_id="a", origin=CITYU, token_provider=lambda: "token-a",
        registry=registry(), client=client, download_client=client,
    )
    second = CanvasReadAdapter(
        connection_id="b", origin=CITYU_DG, token_provider=lambda: "token-b",
        registry=registry(), client=other, download_client=other,
    )
    first.profile()
    second.profile()
    assert tokens == ["Bearer token-a", "Bearer token-b"]
    assert first.origin != second.origin


def test_the_adapter_exposes_no_write_or_discovery_helper() -> None:
    """A model-facing surface must not be able to reach Canvas through this class."""
    public = {name for name in dir(CanvasReadAdapter) if not name.startswith("_")}
    assert public == {
        "course_file_download_url",
        "course_files",
        "download",
        "profile",
        "student_courses",
    }


def test_a_download_url_comes_from_the_files_own_metadata_record() -> None:
    """The URL is read per file, so a listing cannot supply one for the wrong file."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v1/courses/560/files/9":
            return httpx.Response(
                200,
                json={
                    "id": 9,
                    "display_name": "notes.pdf",
                    "size": 3,
                    "url": f"{CITYU}/download/notes.pdf",
                },
            )
        return httpx.Response(404, json={})

    url = adapter(handler).course_file_download_url("560", "9")

    assert url == f"{CITYU}/download/notes.pdf"
    assert seen == ["/api/v1/courses/560/files/9"]


def test_a_file_without_a_download_url_is_forbidden_and_never_retried() -> None:
    """A locked file is reported as this way by Canvas; classifying it retryable would
    mean probing a file the school has already refused."""
    client = adapter(lambda request: httpx.Response(200, json={"id": 9, "display_name": "x"}))
    with pytest.raises(CanvasReadError) as raised:
        client.course_file_download_url("560", "9")
    assert raised.value.category == FORBIDDEN
    assert raised.value.retryable is False


def test_a_download_url_that_is_not_a_public_https_target_is_refused() -> None:
    """A metadata record is still untrusted input: it must not point the worker at a
    loopback address, the cloud metadata service, a plain-HTTP host or a strange port."""
    for target in (
        "http://canvas.cityu.edu.hk/notes.pdf",
        "https://169.254.169.254/latest/meta-data/",
        "https://127.0.0.1/notes.pdf",
        "https://canvas.cityu.edu.hk:8443/notes.pdf",
        "https://user:pass@canvas.cityu.edu.hk/notes.pdf",
    ):
        client = adapter(
            lambda request, target=target: httpx.Response(200, json={"url": target})
        )
        with pytest.raises(CanvasReadError) as raised:
            client.course_file_download_url("560", "9")
        assert raised.value.category == FORBIDDEN, target


def test_an_institution_that_declares_download_hosts_narrows_the_url_rule() -> None:
    """Once a school's file domain is known it is pinned, and nothing else is fetched.

    The default institutions declare no list yet, because guessing a school's CDN host
    would break the real download; until a live response names it, the rule stays "public
    HTTPS" and this test records the mechanism that will restrict it.
    """
    from app.canvas.registry import Institution, InstitutionConnectionRegistry

    institution = Institution(
        key="cityu",
        label="CityU",
        origin=CITYU,
        callback_url="https://rag.coursejesus.com/api/integrations/canvas/oauth/callback",
        client_id_ref="CANVAS_CITYU_CLIENT_ID",
        client_secret_ref="CANVAS_CITYU_CLIENT_SECRET",
        download_hosts=("canvas.cityu.edu.hk",),
    )
    registry = InstitutionConnectionRegistry([institution])
    client = adapter(
        lambda request: httpx.Response(200, json={"url": "https://evil.example.com/notes.pdf"}),
        registry_override=registry,
    )
    with pytest.raises(CanvasReadError) as raised:
        client.course_file_download_url("560", "9")
    assert raised.value.category == FORBIDDEN
    # And a URL on the declared host is accepted.
    allowed = adapter(
        lambda request: httpx.Response(
            200, json={"url": f"{CITYU}/download/notes.pdf"}
        ),
        registry_override=registry,
    )
    assert allowed.course_file_download_url("560", "9") == f"{CITYU}/download/notes.pdf"


def test_a_non_numeric_file_id_cannot_be_smuggled_into_the_path() -> None:
    for course_id, file_id in (("560", "9/../../users/self/profile"), ("560x", "9"), ("", "9")):
        client = adapter(lambda request: httpx.Response(200, json={"url": f"{CITYU}/x"}))
        with pytest.raises(CanvasReadError) as raised:
            client.course_file_download_url(course_id, file_id)
        assert raised.value.category == INVALID_RESPONSE


def test_file_metadata_that_is_not_an_object_is_an_invalid_response() -> None:
    for payload, content_type, expected in (
        ([{"url": f"{CITYU}/x"}], "application/json", INVALID_RESPONSE),
        ("not json at all", "text/plain", "API_RESPONSE_NOT_JSON"),
    ):
        client = adapter(
            lambda request, payload=payload, content_type=content_type: httpx.Response(
                200,
                content=payload if isinstance(payload, str) else json.dumps(payload).encode(),
                headers={"content-type": content_type},
            )
        )
        with pytest.raises(CanvasReadError) as raised:
            client.course_file_download_url("560", "9")
        assert raised.value.category == expected


# ------------------------------------------------------------------ url rules
def test_origin_normalisation_rules() -> None:
    assert normalize_origin("https://canvas.cityu.edu.hk") == CITYU
    assert normalize_origin("https://CANVAS.CityU.edu.hk/") == CITYU
    for bad in (
        "http://canvas.cityu.edu.hk",
        "https://user:pass@canvas.cityu.edu.hk",
        "https://canvas.cityu.edu.hk:8443",
        "https://canvas.cityu.edu.hk/api/v1",
        "https://canvas.cityu.edu.hk/?x=1",
        "https://canvas.cityu.edu.hk/\x00",
        "",
    ):
        with pytest.raises(ValueError):
            normalize_origin(bad)


@pytest.mark.parametrize(
    ("entered", "expected"),
    [
        ("https://cityu-dg.instructure.com/courses", CITYU_DG),
        ("cityu-dg.instructure.com/courses/487/wiki", CITYU_DG),
        ("https://canvas.cityu.edu.hk/profile/settings", CITYU),
        ("https://canvas.cityu.edu.hk/courses/123/files/456?x=1#abc", CITYU),
    ],
)
def test_canvas_page_url_normalises_to_its_safe_origin(entered: str, expected: str) -> None:
    assert normalize_canvas_page_origin(entered) == expected


@pytest.mark.parametrize(
    "entered",
    [
        "file:///etc/passwd",
        "ftp://canvas.cityu.edu.hk/courses",
        "https://user@canvas.cityu.edu.hk/courses",
        "https://localhost/courses",
        "https://127.0.0.1/courses",
        "https://169.254.169.254/latest/meta-data",
        "https://canvas.cityu.edu.hk/\x00",
    ],
)
def test_canvas_page_url_rejects_non_web_or_internal_targets(entered: str) -> None:
    with pytest.raises(ValueError):
        normalize_canvas_page_origin(entered)


def test_public_address_classification() -> None:
    assert is_public_address("93.184.216.34") is True
    assert is_public_address("2606:2800:220:1:248:1893:25c8:1946") is True
    for private in (
        "127.0.0.1", "10.0.0.5", "172.16.9.9", "192.168.0.1", "169.254.169.254",
        "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fc00::1", "fe80::1", "not-an-ip",
    ):
        assert is_public_address(private) is False, private


def test_files_endpoint_rejects_a_non_numeric_course_id() -> None:
    client = adapter(canvas_handler)
    for bad in ("", "abc", "../../etc", "560/files"):
        with pytest.raises(CanvasReadError) as error:
            client.course_files(bad)
        assert error.value.category == "INVALID_RESPONSE"


def test_course_file_metadata_is_parsed_without_urls_in_the_public_shape() -> None:
    client = adapter(canvas_handler)
    entries = client.course_files("560")
    assert entries[0].display_name == "a.pdf"
    assert entries[0].url_present is True
    # The entry type carries a boolean, never the signed URL itself: signed links do not
    # belong in manifests, logs or front-end payloads, so the field is not even available
    # to a caller that would like to serialize it.
    assert not hasattr(entries[0], "url")
    assert "url" not in {name for name in entries[0].__dataclass_fields__}
