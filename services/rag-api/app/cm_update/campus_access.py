"""Single policy source for access to campus-course content.

Student-verification data remains an independent historical fact.  The current
policy opens campus courses to active authenticated accounts without rewriting
that data.  A future owner-authorized switch can require verification only for
accounts created on or after an explicit effective timestamp.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import social

OPEN_TO_REGISTERED = "open_to_registered"
NEW_USERS_REQUIRE_VERIFICATION = "new_users_require_verification"
SUPPORTED_MODES = frozenset({OPEN_TO_REGISTERED, NEW_USERS_REQUIRE_VERIFICATION})


def _timestamp(value: str | None, *, field: str) -> datetime:
    if not value:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def validate_policy(mode: str, verification_effective_at: str | None) -> None:
    if mode not in SUPPORTED_MODES:
        raise ValueError("Unsupported campus access mode")
    if mode == OPEN_TO_REGISTERED:
        if verification_effective_at:
            raise ValueError(
                "CMUI_VERIFICATION_EFFECTIVE_AT must be empty while the campus gate is disabled"
            )
        return
    _timestamp(
        verification_effective_at,
        field="CMUI_VERIFICATION_EFFECTIVE_AT",
    )


def identity_is_active(db: Any, owner: str) -> bool:
    directory = db.one(
        "SELECT active FROM cmui_directory WHERE subject=?",
        (owner,),
    )
    return directory is None or bool(directory["active"])


def _has_valid_verification(db: Any, owner: str) -> bool:
    status = social.verification_status(db, owner)
    if social.qualification_origin(status) == "real":
        return True
    # Historical registration-auto rows are not verification, but an owner may
    # later have redeemed a real code without that old provenance being
    # overwritten.  The redeemed-code row is the durable corroborating fact.
    if status.get("verified") and status.get("method") == "registered":
        return db.one(
            "SELECT 1 FROM cmui_verification_codes "
            "WHERE owner=? AND status='redeemed' LIMIT 1",
            (owner,),
        ) is not None
    return False


def can_access_campus(
    db: Any,
    owner: str,
    *,
    mode: str,
    verification_effective_at: str | None,
    is_admin: bool = False,
) -> bool:
    """Return whether one authenticated identity may access campus content.

    Callers establish authentication before invoking this function.  A known
    disabled/deleted/blocked projection always wins, including for admins.
    Missing local projections are allowed in the current open mode because the
    authenticated request path creates them; future-gate mode safely requires a
    persisted account creation timestamp.
    """

    validate_policy(mode, verification_effective_at)
    if not identity_is_active(db, owner):
        return False
    if is_admin:
        return True
    if mode == OPEN_TO_REGISTERED:
        return True

    effective_at = _timestamp(
        verification_effective_at,
        field="CMUI_VERIFICATION_EFFECTIVE_AT",
    )
    user = db.one("SELECT created_at FROM cmui_users WHERE id=?", (owner,))
    if user is None:
        return False
    created_at = _timestamp(user["created_at"], field="account.created_at")
    if created_at < effective_at:
        return True
    return _has_valid_verification(db, owner)
