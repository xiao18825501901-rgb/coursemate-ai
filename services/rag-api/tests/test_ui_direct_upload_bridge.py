import hashlib

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.models import CourseCreate
from app.storage.backends import AliyunOssStorageBackend
from app.ui_extension.domain import V3DomainAdapter
from app.ui_extension.direct_upload import begin_upload, complete_upload
from test_direct_storage_upload import _Auth, _Embedding, _OssClient


def adapter_for(tmp_path):
    settings = Settings(database_path=tmp_path/'db.sqlite3', upload_dir=tmp_path/'uploads',
                        storage_cache_dir=tmp_path/'cache', storage_reserve_min_bytes=0,
                        storage_reserve_fraction=0, app_env='test', v3_enabled=True,
                        rag_provider_mode='deterministic')
    app = create_app(settings=settings, embedding_provider=_Embedding(), auth_verifier=_Auth())
    ingestion = app.state.ingestion_service
    for cid in ('course-a', 'course-b'):
        ingestion.create_course(CourseCreate(id=cid, name=cid), owner_user_id='owner-a', is_admin=False)
    adapter = V3DomainAdapter(database=app.state.database, settings=settings, ingestion=ingestion,
                              learning=None, retriever=None)
    adapter._begin_request()
    fake = _OssClient()
    ingestion.storage_backend = AliyunOssStorageBackend(bucket='test', client=fake, prefix='coursejesus')
    return adapter, fake


def test_direct_ui_upload_preserves_private_scope_and_indexes_once(tmp_path):
    adapter, fake = adapter_for(tmp_path)
    content = b'# Licensed course\n\nThis source supports search and learning.'
    body = dict(course='course-a', filename='notes.md', mediaType='text/markdown',
                byteSize=len(content), sha256=hashlib.sha256(content).hexdigest())
    grant = begin_upload(adapter, 'owner-a', body)
    fake.objects[fake.presigned_key] = content
    with pytest.raises(ApiError):
        complete_upload(adapter, 'owner-b', dict(course='course-a', upload_id=grant['uploadId']))
    with pytest.raises(ApiError):
        complete_upload(adapter, 'owner-a', dict(course='course-b', upload_id=grant['uploadId']))
    result = complete_upload(adapter, 'owner-a', dict(course='course-a', upload_id=grant['uploadId']))
    assert result['status'] == 'indexed'
    assert result['scope'] == 'private'
    repeated = complete_upload(adapter, 'owner-a', dict(course='course-a', upload_id=grant['uploadId']))
    assert repeated['id'] == result['id']
    duplicate = begin_upload(adapter, 'owner-a', body)
    assert duplicate['method'] == 'EXISTING'
    assert duplicate['file']['id'] == result['id']
    assert duplicate['file']['duplicate'] is True
    with adapter.database.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM chunks WHERE document_id=?', (result['id'],)).fetchone()[0] > 0
        assert db.execute('SELECT source_scope FROM document_versions WHERE document_id=?', (result['id'],)).fetchone()[0] == 'WORKSPACE_PRIVATE'


def test_admin_open_resource_is_shared_not_mislabeled_campus(tmp_path):
    adapter, _ = adapter_for(tmp_path)
    created = adapter.ingestion.create_course(CourseCreate(id='open-textbook', name='Open textbook'),
                                               is_admin=True, open_resource=True)
    assert created.display_type == 'shared'
    assert not created.requires_student_verification
    assert created.visibility == 'public'
    with pytest.raises(ApiError):
        adapter.ingestion.create_course(CourseCreate(id='private-fake-open', name='Private'),
                                         owner_user_id='owner-a', is_admin=False, open_resource=True)


def test_real_mounted_ui_routes_use_direct_storage_and_clerk_boundary(tmp_path):
    settings = Settings(database_path=tmp_path/'db.sqlite3', upload_dir=tmp_path/'uploads',
                        storage_cache_dir=tmp_path/'cache', storage_reserve_min_bytes=0,
                        storage_reserve_fraction=0, app_env='test', v3_enabled=True,
                        ui_extension_enabled=True, ui_web_dir=tmp_path/'no-web',
                        rag_provider_mode='deterministic')
    app = create_app(settings=settings, embedding_provider=_Embedding(), auth_verifier=_Auth())
    fake = _OssClient()
    app.state.ingestion_service.storage_backend = AliyunOssStorageBackend(bucket='test', client=fake)
    base = '/ui-extension/api/ui/v1'
    content = b'# Public source, private upload\n\nA data structure organizes data for efficient access.'
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer owner'
        course = client.post(f'{base}/courses', json={'name': 'Source course'}).json()
        path = f"{base}/courses/{course['id']}"
        grant = client.post(f'{path}/direct-uploads', json={
            'filename': 'notes.md', 'mediaType': 'text/markdown', 'byteSize': len(content),
            'sha256': hashlib.sha256(content).hexdigest(),
        })
        assert grant.status_code == 201, grant.text
        fake.objects[fake.presigned_key] = content
        completion = f"{path}/direct-uploads/{grant.json()['uploadId']}/complete"
        client.headers['Authorization'] = 'Bearer other'
        assert client.post(completion, json={}).status_code in {403, 404}
        client.headers['Authorization'] = 'Bearer owner'
        result = client.post(completion, json={})
        assert result.status_code == 201, result.text
        assert result.json()['status'] == 'indexed'
        assert client.post(completion, json={}).json()['id'] == result.json()['id']
        original = client.get(f"{path}/files/{result.json()['id']}/content?download=true")
        assert original.status_code == 200
        assert original.content == content
