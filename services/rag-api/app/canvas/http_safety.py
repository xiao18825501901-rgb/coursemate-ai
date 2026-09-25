"""Origin, URL and network-target rules for the Canvas read-only adapter.

The requirements these encode come from the CourseJesus pack §10: an origin may only be a
standard HTTPS origin (no userinfo, no unusual port, no control characters); a Canvas token
travels only in the `Authorization` header; and every redirect and DNS answer must be
checked so a student-supplied URL cannot make the server read its own internal network.

They are deliberately a separate module from the adapter: the adapter talks HTTP, this
module decides what HTTP is allowed to touch, and the rules can be tested without a socket.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
ALLOWED_SCHEME = "https"
DEFAULT_HTTPS_PORT = 443


class UnsafeUrlError(ValueError):
    """A URL, origin or resolved address that the adapter must refuse to use."""


def normalize_origin(value: str) -> str:
    """Return `https://host[:port]` for a URL/origin, or raise `UnsafeUrlError`.

    Rejects anything that is not plain HTTPS, carries credentials, uses a non-standard
    port, or contains control characters — each of which has been used to smuggle a
    request somewhere other than the intended Canvas instance.
    """
    if not isinstance(value, str) or not value.strip():
        raise UnsafeUrlError("origin is empty")
    if CONTROL_CHARACTERS.search(value):
        raise UnsafeUrlError("origin contains control characters")
    parts = urlsplit(value.strip())
    if parts.scheme != ALLOWED_SCHEME:
        raise UnsafeUrlError(f"origin must use {ALLOWED_SCHEME}, got {parts.scheme!r}")
    if parts.username or parts.password:
        raise UnsafeUrlError("origin must not carry userinfo")
    if not parts.hostname:
        raise UnsafeUrlError("origin has no host")
    if parts.hostname.endswith("."):
        raise UnsafeUrlError("origin host must not end with a dot")
    try:
        port = parts.port
    except ValueError as error:  # non-numeric or out-of-range port
        raise UnsafeUrlError(f"origin port is invalid: {error}") from error
    if port not in (None, DEFAULT_HTTPS_PORT):
        raise UnsafeUrlError(f"origin port must be {DEFAULT_HTTPS_PORT} or absent, got {port}")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise UnsafeUrlError("origin must not carry a path, query or fragment")
    return f"{ALLOWED_SCHEME}://{parts.hostname.lower()}"


def normalize_canvas_page_origin(value: str) -> str:
    """Reduce an ordinary Canvas page URL to its HTTPS origin.

    Students copy the address currently visible in the browser, not a hand-edited API root.
    Paths, queries and fragments are therefore intentionally discarded. The security-bearing
    parts are not: non-HTTPS schemes, userinfo, unusual ports, localhost and non-public IP
    literals are refused before the registry is consulted.
    """

    if not isinstance(value, str) or not value.strip():
        raise UnsafeUrlError("Canvas address is empty")
    entered = value.strip()
    if CONTROL_CHARACTERS.search(entered):
        raise UnsafeUrlError("Canvas address contains control characters")
    if "://" not in entered:
        entered = f"https://{entered}"
    parts = urlsplit(entered)
    if parts.scheme.lower() != ALLOWED_SCHEME:
        raise UnsafeUrlError(f"Canvas address must use {ALLOWED_SCHEME}")
    if parts.username or parts.password:
        raise UnsafeUrlError("Canvas address must not carry userinfo")
    host = (parts.hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith("."):
        raise UnsafeUrlError("Canvas address has an invalid host")
    try:
        port = parts.port
    except ValueError as error:
        raise UnsafeUrlError(f"Canvas address port is invalid: {error}") from error
    if port not in (None, DEFAULT_HTTPS_PORT):
        raise UnsafeUrlError("Canvas address must use the standard HTTPS port")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not is_public_address(str(literal)):
        raise UnsafeUrlError("Canvas address must not target a private or reserved network")
    return f"{ALLOWED_SCHEME}://{host}"


def validate_api_url(
    url: str,
    *,
    allowed_origin: str,
    allowed_patterns: tuple[re.Pattern[str], ...],
) -> str:
    """Validate one Canvas API URL against an institution origin and endpoint allow-list.

    Returns the URL to request. The allow-list is what stops the adapter from becoming a
    general-purpose proxy: only the endpoints the product actually needs are reachable, and
    they are matched **exactly** — a course-scoped prefix would have allowed
    `/api/v1/courses/:id/assignments` and `/submissions` through as well, which the
    adapter's own tests caught.
    """
    if CONTROL_CHARACTERS.search(url):
        raise UnsafeUrlError("url contains control characters")
    parts = urlsplit(url)
    if parts.scheme != ALLOWED_SCHEME:
        raise UnsafeUrlError(f"url must use {ALLOWED_SCHEME}, got {parts.scheme!r}")
    if parts.username or parts.password:
        raise UnsafeUrlError("url must not carry userinfo")
    if normalize_origin(f"{parts.scheme}://{parts.netloc}") != allowed_origin:
        raise UnsafeUrlError(f"url must stay on {allowed_origin}")
    if not any(pattern.match(parts.path) for pattern in allowed_patterns):
        raise UnsafeUrlError(f"path {parts.path!r} is not an allowed Canvas endpoint")
    return url


# Address ranges that must never be reachable from a user-influenced URL. The metadata
# address is covered by link-local, but it is listed by name so the reason is obvious.
FORBIDDEN_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local, includes 169.254.169.254
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("240.0.0.0/4"),  # reserved
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("fe80::/10"),  # link-local
    ipaddress.ip_network("ff00::/8"),  # multicast
)


def is_public_address(address: str) -> bool:
    """False for loopback, private, link-local, metadata, multicast or reserved ranges."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.is_loopback or parsed.is_private or parsed.is_link_local:
        return False
    if parsed.is_multicast or parsed.is_reserved or parsed.is_unspecified:
        return False
    if parsed.version == 4 and parsed.is_global is False:  # pragma: no cover - defensive
        return False
    return not any(parsed in network for network in FORBIDDEN_NETWORKS)


def resolve_public_host(
    host: str, *, resolver: Callable[..., Sequence[tuple[Any, ...]]] = socket.getaddrinfo
) -> list[str]:
    """Resolve `host`, refusing the host when any answer is non-public.

    Every answer is checked, not just the first: a name that resolves to one public and
    one private address must be refused outright rather than raced.
    """
    try:
        infos = resolver(host, None)
    except OSError as error:
        raise UnsafeUrlError(f"cannot resolve {host}: {error}") from error
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise UnsafeUrlError(f"{host} resolved to no address")
    blocked = [address for address in addresses if not is_public_address(address)]
    if blocked:
        raise UnsafeUrlError(f"{host} resolves to non-public address(es) {blocked}")
    return addresses


def validate_download_target(
    url: str,
    *,
    allowed_hosts: tuple[str, ...],
    resolver: Callable[..., Sequence[tuple[Any, ...]]] | None = None,
) -> str:
    """Validate one download URL (initial or a redirect hop) and return it.

    Applied to every hop because a signed URL legitimately redirects to a CDN, and the
    second hop is where a crafted first hop would try to send the request somewhere else.
    """
    if CONTROL_CHARACTERS.search(url):
        raise UnsafeUrlError("download url contains control characters")
    parts = urlsplit(url)
    if parts.scheme != ALLOWED_SCHEME:
        raise UnsafeUrlError(f"download url must use {ALLOWED_SCHEME}, got {parts.scheme!r}")
    if parts.username or parts.password:
        raise UnsafeUrlError("download url must not carry userinfo")
    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeUrlError("download url has no host")
    try:
        port = parts.port
    except ValueError as error:
        raise UnsafeUrlError(f"download url port is invalid: {error}") from error
    if port not in (None, DEFAULT_HTTPS_PORT):
        raise UnsafeUrlError(f"download url port must be {DEFAULT_HTTPS_PORT} or absent")
    if allowed_hosts and host not in allowed_hosts:
        raise UnsafeUrlError(f"download host {host!r} is not allowed")
    if resolver is not None:
        resolve_public_host(host, resolver=resolver)
    else:
        resolve_public_host(host)
    return url
