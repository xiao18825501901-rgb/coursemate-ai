"""The owner's small-sample live read, exercised against a simulated school.

The live run differs from these tests only in the transport, which is the point of putting the
logic in a module: the ordering (identity, courses, files, download, destroy), the receipt's shape
and the guarantee that no credential appears anywhere are all covered here, so a live run is not
the first time the code path executes.
"""

from __future__ import annotations

import json
import pathlib

import httpx
import pytest

from app.canvas.adapter import CanvasReadAdapter
from app.canvas.owner_smoke import run_smoke
from app.canvas.registry import InstitutionConnectionRegistry
from app.canvas.transient_credential import (
    DESTROYED,
    REASON_READS_COMPLETE,
    TransientCanvasCredentialStore,
)

CITYU = "https://canvas.cityu.edu.hk"
TOKEN = "1~ownerSmokeTestTokenValue0000000000000000000000"
PAYLOAD = b"# Shading\n\nDiffuse and specular reflection.\n"

COURSE = {
    "id": 560,
    "name": "Problem Solve & Programming",
    "course_code": "CS2312",
    "workflow_state": "available",
    "enrollments": [{"type": "student", "role": "StudentEnrollment", "enrollment_state": "active"}],
}
FILE_ENTRY = {
    "id": 7,
    "display_name": "shading.md",
    "size": len(PAYLOAD),
    "updated_at": "2026-09-01T00:00:00Z",
    "url": f"{CITYU}/download/560/7",
}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/v1/users/self/profile":
        return httpx.Response(200, json={"id": 4242, "name": "Owner Account"})
    if path == "/api/v1/courses":
        completed = dict(request.url.params).get("enrollment_state") == "completed"
        return httpx.Response(200, json=[] if completed else [COURSE])
    if path == "/api/v1/courses/560/files":
        return httpx.Response(200, json=[FILE_ENTRY])
    if path == "/api/v1/courses/560/files/7":
        return httpx.Response(200, json=FILE_ENTRY)
    if path == "/download/560/7":
        return httpx.Response(200, content=PAYLOAD)
    return httpx.Response(404, json={"errors": [{"message": "not found"}]})


def build(tmp_path: pathlib.Path) -> tuple[TransientCanvasCredentialStore, str, CanvasReadAdapter]:
    store = TransientCanvasCredentialStore()
    credential = store.open_task(
        subject="owner",
        connection_id="owner-conn",
        institution_key="cityu",
        institution_origin=CITYU,
        token=TOKEN,
    )
    transport = httpx.MockTransport(handler)
    adapter = CanvasReadAdapter(
        connection_id="owner-conn",
        origin=CITYU,
        token_provider=store.provider(credential.credential_ref),
        registry=InstitutionConnectionRegistry(),
        client=httpx.Client(base_url=CITYU, transport=transport, follow_redirects=False),
        download_client=httpx.Client(transport=transport, follow_redirects=False),
    )
    return store, credential.credential_ref, adapter


def test_a_small_sample_is_read_hashed_and_the_credential_is_destroyed(tmp_path) -> None:
    store, ref, adapter = build(tmp_path)

    receipt = run_smoke(
        adapter=adapter,
        store=store,
        credential_ref=ref,
        sink_dir=tmp_path / "sink",
    )

    assert receipt.ok is True, receipt.as_dict()
    assert receipt.canvas_user_id == "4242"
    assert receipt.canvas_name == "Owner Account"
    assert receipt.readable_courses == 1
    assert receipt.course_id == "560"
    assert receipt.listed_files == 1
    assert receipt.files[0].display_name == "shading.md"
    assert receipt.files[0].received_bytes == len(PAYLOAD)
    assert receipt.files[0].sha256
    assert receipt.credential_state == DESTROYED
    assert receipt.destroy_reason == REASON_READS_COMPLETE
    assert receipt.zeroed_bytes == len(TOKEN)
    assert receipt.read_calls >= 4, "identity, courses, file list, file detail and bytes are reads"
    # The measurement leaves nothing behind, and the credential cannot be used again.
    assert list((tmp_path / "sink").glob("*")) == []
    assert store.provider(ref)() is None
    assert TOKEN not in json.dumps(receipt.as_dict())


def test_a_named_course_that_is_not_readable_is_refused_rather_than_substituted(tmp_path) -> None:
    store, ref, adapter = build(tmp_path)

    receipt = run_smoke(
        adapter=adapter,
        store=store,
        credential_ref=ref,
        sink_dir=tmp_path / "sink",
        course_id="999",
    )

    assert receipt.ok is False
    assert receipt.errors and "999" in receipt.errors[0]
    assert receipt.files == []
    # A refusal still destroys the credential: a failed run must not leave one held.
    assert receipt.credential_state == DESTROYED


def test_a_file_above_the_cap_is_reported_without_being_downloaded(tmp_path) -> None:
    store, ref, adapter = build(tmp_path)

    receipt = run_smoke(
        adapter=adapter,
        store=store,
        credential_ref=ref,
        sink_dir=tmp_path / "sink",
        max_bytes=4,
    )

    assert receipt.files[0].skipped_reason
    assert receipt.files[0].sha256 == ""
    assert receipt.ok is False, "no bytes were read, so this run proves nothing and must not pass"
    assert receipt.credential_state == DESTROYED


def test_a_school_that_refuses_the_token_ends_the_run_with_a_receipt(tmp_path) -> None:
    store = TransientCanvasCredentialStore()
    credential = store.open_task(
        subject="owner",
        connection_id="owner-conn",
        institution_key="cityu",
        institution_origin=CITYU,
        token=TOKEN,
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"errors": []}))
    adapter = CanvasReadAdapter(
        connection_id="owner-conn",
        origin=CITYU,
        token_provider=store.provider(credential.credential_ref),
        registry=InstitutionConnectionRegistry(),
        client=httpx.Client(base_url=CITYU, transport=transport, follow_redirects=False),
        download_client=httpx.Client(transport=transport, follow_redirects=False),
    )

    receipt = run_smoke(
        adapter=adapter,
        store=store,
        credential_ref=credential.credential_ref,
        sink_dir=tmp_path / "sink",
    )

    assert receipt.ok is False
    assert receipt.errors and "expired_token" in receipt.errors[0].lower()
    assert receipt.credential_state == DESTROYED
    assert receipt.zeroed_bytes == len(TOKEN)


@pytest.mark.parametrize("token", ["", "   ", "short"])
def test_the_cli_refuses_a_token_that_cannot_be_one(tmp_path, token: str) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "canvas_owner_smoke_test",
        pathlib.Path(__file__).resolve().parents[3] / "scripts" / "canvas_owner_smoke_test.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    token_file = tmp_path / "pat.txt"
    token_file.write_text(token, encoding="utf-8")
    code = module.main(["--institution", "cityu", "--token-file", str(token_file)])
    assert code == 2


def test_the_cli_refuses_an_unknown_school(tmp_path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "canvas_owner_smoke_test",
        pathlib.Path(__file__).resolve().parents[3] / "scripts" / "canvas_owner_smoke_test.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    token_file = tmp_path / "pat.txt"
    token_file.write_text(TOKEN, encoding="utf-8")
    code = module.main(["--institution", "not-a-school", "--token-file", str(token_file)])
    assert code == 2
