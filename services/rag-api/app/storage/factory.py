from typing import Any

from app.config import Settings
from app.storage.backends import AliyunOssStorageBackend, LocalStorageBackend, StorageBackend


class AlibabaCloudCredentialAdapter:
    """Bridge the official default credential chain into OSS SDK V2."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from alibabacloud_credentials.client import Client

            client = Client()
        self.client = client

    def get_credentials(self):  # type: ignore[no-untyped-def]
        from alibabacloud_oss_v2.types import Credentials

        value = self.client.get_credential()
        return Credentials(
            value.access_key_id,
            value.access_key_secret,
            value.security_token,
        )


def storage_backend_from_settings(
    settings: Settings,
    *,
    oss_client: Any | None = None,
) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorageBackend(settings.upload_dir / "objects")
    if oss_client is None:
        import alibabacloud_oss_v2 as oss

        config = oss.Config(
            region=settings.oss_region,
            endpoint=settings.oss_endpoint,
            credentials_provider=AlibabaCloudCredentialAdapter(),
            disable_ssl=False,
            insecure_skip_verify=False,
            enabled_redirect=False,
        )
        oss_client = oss.Client(config)
    return AliyunOssStorageBackend(
        bucket=settings.oss_bucket,
        client=oss_client,
        prefix=settings.oss_object_prefix,
    )
