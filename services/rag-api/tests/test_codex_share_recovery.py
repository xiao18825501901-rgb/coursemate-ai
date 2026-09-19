"""Crash/retry and multi-worker evidence for integrated frozen snapshot joins."""

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.errors import ApiError
from app.main import create_app
from app.services.ingestion import IngestionService
from test_codex_sharing import UI, auth, client, private_course
from test_current_change_features import (
    FakeAuthVerifier,
    FakeEmbeddingProvider,
    make_settings,
)


def test_failed_send_resumes_frozen_manifest_with_same_request(client,monkeypatch):
    from app.ui_extension.domain import V3DomainAdapter
    course=private_course(client)
    for index in range(2):
        assert client.post(f'{UI}/courses/{course}/files',headers=auth('token-a'),
            files={'file':(f'original-{index}.txt',f'Frozen source {index}'.encode(),'text/plain')}).status_code==201
    original=V3DomainAdapter._snapshot_export
    calls=0
    def interrupted(self,subject,payload):
        nonlocal calls
        calls+=1
        if calls==2: raise ApiError(503,'SYNTHETIC_COPY_INTERRUPTION','Synthetic interruption')
        return original(self,subject,payload)
    monkeypatch.setattr(V3DomainAdapter,'_snapshot_export',interrupted)
    data={'course':course,'recipients':['user-b'],'history_scope':'none','request_id':'resume-frozen-send'}
    assert client.post(f'{UI}/shares',headers=auth('token-a'),json=data).status_code==503
    db=client.app.state.ui_extension_app.state.db
    first=db.one('SELECT * FROM cmui_shares WHERE request_id=?',(data['request_id'],))
    assert first['status']=='failed'
    assert not db.all('SELECT * FROM cmui_share_recipients WHERE share=?',(first['id'],))
    client.post(f'{UI}/courses/{course}/files',headers=auth('token-a'),
        files={'file':('late.txt',b'MUST_NOT_JOIN_ORIGINAL_MANIFEST','text/plain')})
    retried=client.post(f'{UI}/shares',headers=auth('token-a'),json=data)
    assert retried.status_code==201,retried.text
    assert retried.json()['id']==first['id']
    joined=client.post(f"{UI}/shares/{first['id']}/join",headers=auth('token-b'))
    assert joined.status_code==200,joined.text
    files=client.get(f"{UI}/courses/{joined.json()['joined_course_id']}/files",headers=auth('token-b')).json()
    assert {f['name'] for f in files}=={'original-0.txt','original-1.txt'}


@pytest.mark.parametrize("quota", ["files", "bytes"])
def test_join_resumes_after_final_file_persisted_at_quota(client, monkeypatch, quota):
    course = private_course(client)
    contents = [f"unique quota recovery lesson {index}".encode() for index in range(3)]
    for index, content in enumerate(contents):
        uploaded = client.post(
            f"{UI}/courses/{course}/files",
            headers=auth("token-a"),
            files={"file": (f"{index}.txt", content, "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
    sent = client.post(
        f"{UI}/shares",
        headers=auth("token-a"),
        json={"course": course, "recipients": ["user-b"], "history_scope": "none",
              "request_id": f"quota-recovery-{quota}"},
    )
    assert sent.status_code == 201, sent.text
    share_id = sent.json()["id"]
    service = client.app.state.ingestion_service
    if quota == "files":
        monkeypatch.setattr(service.settings, "user_course_max_files", 3)
    else:
        monkeypatch.setattr(service.settings, "user_course_max_total_upload_bytes", sum(map(len, contents)))
    original = service.import_snapshot
    completed_imports = 0

    def interrupt_after_final_persistence(**kwargs):
        nonlocal completed_imports
        result = original(**kwargs)
        completed_imports += 1
        if completed_imports == 3:
            raise ApiError(503, "SYNTHETIC_INTERRUPT", "Interrupted after final file persistence")
        return result

    monkeypatch.setattr(service, "import_snapshot", interrupt_after_final_persistence)
    first = client.post(f"{UI}/shares/{share_id}/join", headers=auth("token-b"))
    assert first.status_code == 503, first.text
    db = client.app.state.ui_extension_app.state.db
    receipt = db.one("SELECT * FROM cmui_share_imports WHERE share=? AND recipient=?", (share_id, "user-b"))
    assert receipt["status"] == "FAILED_RETRYABLE"
    assert db.one("SELECT status FROM cmui_share_recipients WHERE share=? AND recipient=?",
                  (share_id, "user-b"))["status"] == "notified"
    before = client.get(f"{UI}/courses/{receipt['course']}/files", headers=auth("token-b"))
    assert before.status_code == 200, before.text
    original_ids = {item["id"] for item in before.json()}
    assert len(original_ids) == 3

    retried = client.post(f"{UI}/shares/{share_id}/join", headers=auth("token-b"))
    assert retried.status_code == 200, retried.text
    assert retried.json()["joined_course_id"] == receipt["course"]
    after = client.get(f"{UI}/courses/{receipt['course']}/files", headers=auth("token-b"))
    assert {item["id"] for item in after.json()} == original_ids
    assert db.one("SELECT status FROM cmui_share_imports WHERE share=? AND recipient=?",
                  (share_id, "user-b"))["status"] == "READY"


def test_concurrent_join_reuses_course_created_by_other_worker(client, tmp_path, monkeypatch):
    course = private_course(client)
    uploaded = client.post(
        f"{UI}/courses/{course}/files", headers=auth("token-a"),
        files={"file": ("one.txt", b"concurrent snapshot evidence", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    sent = client.post(
        f"{UI}/shares", headers=auth("token-a"),
        json={"course": course, "recipients": ["user-b"], "history_scope": "none",
              "request_id": "multi-worker-same-share"},
    )
    assert sent.status_code == 201, sent.text
    share_id = sent.json()["id"]
    second_app = create_app(
        settings=make_settings(tmp_path), embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    rendezvous = Barrier(2)
    original = IngestionService.create_course

    def create_after_both_workers_observe_absence(self, payload, **kwargs):
        if payload.id.startswith("share-"):
            rendezvous.wait(timeout=10)
        return original(self, payload, **kwargs)

    monkeypatch.setattr(IngestionService, "create_course", create_after_both_workers_observe_absence)
    with TestClient(second_app) as second_client, ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(worker.post, f"{UI}/shares/{share_id}/join", headers=auth("token-b"))
                   for worker in (client, second_client)]
        responses = [future.result(timeout=25) for future in futures]
    assert [response.status_code for response in responses] == [200, 200], [response.text for response in responses]
    course_ids = {response.json()["joined_course_id"] for response in responses}
    assert len(course_ids) == 1
    joined_course = course_ids.pop()
    files = client.get(f"{UI}/courses/{joined_course}/files", headers=auth("token-b"))
    assert files.status_code == 200, files.text
    assert len(files.json()) == 1
    with client.app.state.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM courses WHERE id=?", (joined_course,)).fetchone()[0] == 1


def test_share_preserves_distinct_source_files_with_identical_bytes(client):
    course = private_course(client)
    content = b"Identical bytes, distinct source filenames and source corpora."
    # The visible source list is a union of the owned course and its workspace.
    owned = client.post(
        f"/api/courses/{course}/documents", headers=auth("token-a"),
        files={"file": ("owner-copy.txt", content, "text/plain")},
    )
    assert owned.status_code == 202, owned.text
    private = client.post(
        f"{UI}/courses/{course}/files", headers=auth("token-a"),
        files={"file": ("workspace-copy.txt", content, "text/plain")},
    )
    assert private.status_code == 201, private.text
    source_files = client.get(f"{UI}/courses/{course}/files", headers=auth("token-a")).json()
    assert len(source_files) == 2
    assert len({item["sha256"] for item in source_files}) == 1
    sent = client.post(
        f"{UI}/shares", headers=auth("token-a"),
        json={"course": course, "recipients": ["user-b"], "history_scope": "none",
              "request_id": "distinct-sources-identical-bytes"},
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["files_copied"] == 2
    share_id = sent.json()["id"]
    joined = client.post(f"{UI}/shares/{share_id}/join", headers=auth("token-b"))
    assert joined.status_code == 200, joined.text
    target = joined.json()["joined_course_id"]
    copied = client.get(f"{UI}/courses/{target}/files", headers=auth("token-b"))
    assert copied.status_code == 200, copied.text
    files = copied.json()
    assert len(files) == 2, files
    assert {item["name"] for item in files} == {"owner-copy.txt", "workspace-copy.txt"}
    assert len({item["id"] for item in files}) == 2
    assert len({item["version_id"] for item in files}) == 2
    assert not {item["id"] for item in files}.intersection(item["id"] for item in source_files)
    for item in files:
        response = client.get(f"{UI}/courses/{target}/files/{item['id']}/content", headers=auth("token-b"))
        assert response.status_code == 200, response.text
        assert response.content == content
    db = client.app.state.ui_extension_app.state.db
    receipt = db.one("SELECT * FROM cmui_share_imports WHERE share=? AND recipient=?", (share_id, "user-b"))
    mapping = json.loads(receipt["mapping_json"])
    assert len({mapping[item["id"]]["document_id"] for item in source_files}) == 2
    assert receipt["status"] == "READY"
    again = client.post(f"{UI}/shares/{share_id}/join", headers=auth("token-b"))
    assert again.status_code == 200, again.text
    assert again.json()["joined_course_id"] == target
    assert len(client.get(f"{UI}/courses/{target}/files", headers=auth("token-b")).json()) == 2
