"""Canvas integration exports without eagerly loading server-only workers.

The read-only adapter is also reused by the portable Windows bridge. Importing that adapter must
not pull the RAG ingestion/model stack into a student desktop artifact. Server-only exports retain
the same public names through module-level lazy loading.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

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
    normalize_canvas_page_origin,
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

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ALL_STATES": (".job", "ALL_STATES"),
    "TERMINAL_STATES": (".job", "TERMINAL_STATES"),
    "FileRecord": (".job", "FileRecord"),
    "ImportJob": (".job", "ImportJob"),
    "JobStateError": (".job", "JobStateError"),
    "new_job": (".job", "new_job"),
    "selection_fingerprint": (".job", "selection_fingerprint"),
    "AuthorizationState": (".oauth", "AuthorizationState"),
    "CanvasOAuthClient": (".oauth", "CanvasOAuthClient"),
    "CompletedAuthorization": (".oauth", "CompletedAuthorization"),
    "Connection": (".oauth", "Connection"),
    "CredentialStore": (".oauth", "CredentialStore"),
    "InMemoryCredentialStore": (".oauth", "InMemoryCredentialStore"),
    "InMemoryStateStore": (".oauth", "InMemoryStateStore"),
    "OAuthError": (".oauth", "OAuthError"),
    "StateStore": (".oauth", "StateStore"),
    "StoredCredential": (".oauth", "StoredCredential"),
    "TokenSet": (".oauth", "TokenSet"),
    "callback_matches_institution": (".oauth", "callback_matches_institution"),
    "scopes_for": (".oauth", "scopes_for"),
    "token_provider_for": (".oauth", "token_provider_for"),
    "CanvasJobRepository": (".store", "CanvasJobRepository"),
    "ClaimedJob": (".store", "ClaimedJob"),
    "DESTROYED": (".transient_credential", "DESTROYED"),
    "EXPIRED": (".transient_credential", "EXPIRED"),
    "LOST_ON_RESTART": (".transient_credential", "LOST_ON_RESTART"),
    "NEVER_STORED": (".transient_credential", "NEVER_STORED"),
    "PRESENT_TRANSIENTLY": (".transient_credential", "PRESENT_TRANSIENTLY"),
    "CredentialRefused": (".transient_credential", "CredentialRefused"),
    "CredentialUnavailable": (".transient_credential", "CredentialUnavailable"),
    "TaskCredential": (".transient_credential", "TaskCredential"),
    "TransientCanvasCredentialStore": (".transient_credential", "TransientCanvasCredentialStore"),
    "CanvasImportWorker": (".worker", "CanvasImportWorker"),
    "RunResult": (".worker", "RunResult"),
    "default_target_course_resolver": (".worker", "default_target_course_resolver"),
    "material_media_type": (".worker", "material_media_type"),
    "safe_upload_name": (".worker", "safe_upload_name"),
    "target_course_slug": (".worker", "target_course_slug"),
    "FileOutcome": (".worker_decisions", "FileOutcome"),
    "outcome_for_download": (".worker_decisions", "outcome_for_download"),
    "outcome_for_error": (".worker_decisions", "outcome_for_error"),
    "should_stop_job": (".worker_decisions", "should_stop_job"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    "ALLOWED_ENDPOINTS", "AVAILABLE", "AuthorizationState", "CanvasCourse",
    "CanvasFileEntry", "CanvasOAuthClient", "CanvasProfile", "CanvasReadAdapter",
    "CanvasReadError", "CompletedAuthorization", "Connection", "CredentialStore",
    "DownloadResult", "InMemoryCredentialStore", "InMemoryStateStore", "Institution",
    "InstitutionConnectionRegistry", "NOT_CONFIGURED", "OAuthError", "StateStore",
    "StoredCredential", "TokenSet", "UnknownInstitutionError", "UnsafeUrlError",
    "callback_matches_institution", "default_institutions", "is_public_address",
    "normalize_canvas_page_origin", "normalize_origin", "parse_next_link",
    "resolve_public_host", "scopes_for", "token_provider_for", "validate_api_url",
    "validate_download_target", "ALL_STATES", "TERMINAL_STATES", "FileRecord",
    "ImportJob", "JobStateError", "new_job", "selection_fingerprint",
    "CanvasJobRepository", "ClaimedJob", "FileOutcome", "outcome_for_download",
    "outcome_for_error", "should_stop_job", "CanvasImportWorker", "RunResult",
    "default_target_course_resolver", "material_media_type", "safe_upload_name",
    "target_course_slug", "DESTROYED", "EXPIRED", "LOST_ON_RESTART",
    "NEVER_STORED", "PRESENT_TRANSIENTLY", "CredentialRefused",
    "CredentialUnavailable", "TaskCredential", "TransientCanvasCredentialStore",
]
