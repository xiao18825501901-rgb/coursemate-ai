from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.storage.factory import storage_backend_from_settings


@pytest.mark.parametrize("public_endpoint", ["https://oss-cn-hangzhou.aliyuncs.com", ""])
def test_public_upload_signer_keeps_internal_data_client(monkeypatch, public_endpoint):
    import alibabacloud_oss_v2 as oss

    from app.storage import factory

    clients = []

    class Client:
        def __init__(self, config):
            self.config = config
            clients.append(self)

        def presign(self, request, **kwargs):
            return SimpleNamespace(
                url=f"{self.config.endpoint}/{request.bucket}/{request.key}",
                signed_headers={"content-type": request.content_type},
                expiration=datetime.now(UTC),
            )

    monkeypatch.setattr(oss, "Client", Client)
    monkeypatch.setattr(factory, "AlibabaCloudCredentialAdapter", lambda: object())
    settings = Settings(
        _env_file=None,
        v3_enabled=True,
        storage_backend="aliyun_oss",
        oss_region="cn-hangzhou",
        oss_bucket="private-course-bucket",
        oss_endpoint="https://oss-cn-hangzhou-internal.aliyuncs.com",
        oss_public_endpoint=public_endpoint,
        oss_object_prefix="coursejesus/production",
    )
    backend = storage_backend_from_settings(settings)
    url, headers, _ = backend.presign_quarantine_put(
        "quarantine/owner/upload.pdf", size=1, sha256="a" * 64,
        content_type="application/pdf", ttl_seconds=600,
    )
    assert url.startswith((public_endpoint or settings.oss_endpoint) + "/")
    assert url.endswith("/coursejesus/production/quarantine/owner/upload.pdf")
    assert backend.client.config.endpoint == settings.oss_endpoint
    assert headers == {"content-type": "application/pdf"}
    assert len(clients) == (2 if public_endpoint else 1)
    if public_endpoint:
        assert clients[0].config.credentials_provider is clients[1].config.credentials_provider
