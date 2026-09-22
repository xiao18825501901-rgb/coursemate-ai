"""Canvas integration: institution registry and the stateless read-only adapter."""

from .adapter import (
    ALLOWED_ENDPOINTS,
    CanvasCourse,
    CanvasFileEntry,
    CanvasProfile,
    CanvasReadAdapter,
    CanvasReadError,
    DownloadResult,
    parse_next_link,
)
from .http_safety import (
    UnsafeUrlError,
    is_public_address,
    normalize_origin,
    resolve_public_host,
    validate_api_url,
    validate_download_target,
)
from .registry import (
    AVAILABLE,
    NOT_CONFIGURED,
    Institution,
    InstitutionConnectionRegistry,
    UnknownInstitutionError,
    default_institutions,
)

__all__ = [
    "ALLOWED_ENDPOINTS",
    "AVAILABLE",
    "CanvasCourse",
    "CanvasFileEntry",
    "CanvasProfile",
    "CanvasReadAdapter",
    "CanvasReadError",
    "DownloadResult",
    "Institution",
    "InstitutionConnectionRegistry",
    "NOT_CONFIGURED",
    "UnknownInstitutionError",
    "UnsafeUrlError",
    "default_institutions",
    "is_public_address",
    "normalize_origin",
    "parse_next_link",
    "resolve_public_host",
    "validate_api_url",
    "validate_download_target",
]
