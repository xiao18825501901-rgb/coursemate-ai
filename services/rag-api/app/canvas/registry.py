"""Per-institution Canvas connections.

Canvas developer keys are issued per institution, so this registry keeps one entry per
school with its own origin, credential *reference* and allowed download hosts. Two
properties matter and are enforced by the API:

* a client cannot hand the adapter another institution's `base_url` to make one school's
  secret serve another — the origin must match a registry entry exactly; and
  availability is derived from whether the credential reference actually resolves, so a
  school without a Developer Key is reported `NOT_CONFIGURED` rather than "connected".
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .http_safety import normalize_canvas_page_origin, normalize_origin

NOT_CONFIGURED = "NOT_CONFIGURED"
AVAILABLE = "AVAILABLE"


class UnknownInstitutionError(KeyError):
    """An origin or key that is not in the registry."""


@dataclass(frozen=True)
class Institution:
    """One Canvas instance and how the product may talk to it.

    Secrets are never stored here: `client_id_ref`/`client_secret_ref` are environment
    variable *names*, and the registry only asks whether they are present in order to
    report availability.
    """

    key: str
    label: str
    origin: str
    callback_url: str
    client_id_ref: str
    client_secret_ref: str
    scopes: tuple[str, ...] = ()
    download_hosts: tuple[str, ...] = ()
    notes: str = ""

    @property
    def configured(self) -> bool:
        return bool(os.environ.get(self.client_id_ref) and os.environ.get(self.client_secret_ref))

    @property
    def state(self) -> str:
        return AVAILABLE if self.configured else NOT_CONFIGURED


def default_institutions() -> tuple[Institution, ...]:
    """The two institutions the owner named, both read-only and both key-less today."""
    return (
        Institution(
            key="cityu",
            label="CityU",
            origin=normalize_origin("https://canvas.cityu.edu.hk"),
            callback_url="https://rag.coursejesus.com/api/integrations/canvas/oauth/callback",
            client_id_ref="CANVAS_CITYU_CLIENT_ID",
            client_secret_ref="CANVAS_CITYU_CLIENT_SECRET",
            notes="Developer Key must be issued by the institution's Canvas administrator.",
        ),
        Institution(
            key="cityu-dg",
            label="CityU(DG)",
            origin=normalize_origin("https://cityu-dg.instructure.com"),
            callback_url="https://rag.coursejesus.com/api/integrations/canvas/oauth/callback",
            client_id_ref="CANVAS_CITYU_DG_CLIENT_ID",
            client_secret_ref="CANVAS_CITYU_DG_CLIENT_SECRET",
            notes="Separate institution, therefore a separate key and secret.",
        ),
    )


@dataclass
class InstitutionConnectionRegistry:
    """Look-up table for institution origins, keys and availability."""

    institutions: tuple[Institution, ...] = field(default_factory=default_institutions)
    _by_key: dict[str, Institution] = field(init=False, repr=False, default_factory=dict)
    _by_origin: dict[str, Institution] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        for institution in self.institutions:
            self._by_key[institution.key] = institution
            self._by_origin[institution.origin] = institution

    def by_key(self, key: str) -> Institution:
        try:
            return self._by_key[key]
        except KeyError as error:
            raise UnknownInstitutionError(f"unknown institution {key!r}") from error

    def by_origin(self, origin: str) -> Institution:
        """Resolve a caller-supplied Canvas page URL, refusing anything not registered."""
        try:
            normalized = normalize_canvas_page_origin(origin)
        except ValueError as error:
            raise UnknownInstitutionError(str(error)) from error
        try:
            return self._by_origin[normalized]
        except KeyError as error:
            raise UnknownInstitutionError(
                f"origin {normalized!r} is not a registered institution"
            ) from error

    def state_of(self, key: str) -> str:
        return self.by_key(key).state

    def availability(self) -> dict[str, str]:
        """Public, non-secret view for the UI: which schools can be connected right now."""
        return {institution.key: institution.state for institution in self.institutions}
