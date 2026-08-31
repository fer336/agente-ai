import hashlib
import ipaddress
import os
import socket
import tempfile
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import cast
from urllib.parse import urlparse

import httpx

from app.domain.repositories.media_downloader import DownloadedMedia
from app.infrastructure.media.exceptions import MediaDownloadError

#: PRD.md §74.7: "No se seguirán redirecciones hacia hosts no autorizados" —
#: a redirect IS allowed, but only when its target passes the same
#: host-allowlist + SSRF check as the original URL, and only up to this many
#: hops (guards against a redirect loop).
_MAX_REDIRECTS = 2

_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class SecureMediaDownloader:
    """`httpx`-based `MediaDownloader` with SSRF protections (PRD.md §74.7).

    Enforces, in order: HTTPS-only, host allowlist, DNS-resolved-address
    blocklist (private/loopback/link-local/multicast/reserved/unspecified —
    covers the cloud-metadata address `169.254.169.254` via link-local), a
    manually-validated redirect chain (never `httpx`'s own
    `follow_redirects`), and a byte cap enforced WHILE streaming (aborts
    mid-download rather than only checking `Content-Length`, which a
    malicious/misconfigured server can lie about or omit).

    KNOWN LIMITATION (documented, not hidden): the host/address check below
    resolves DNS once, separately from the actual connection `httpx` makes
    moments later — a classic TOCTOU/DNS-rebinding window exists between
    the two. Closing it fully requires a custom transport that pins the
    validated IP for the actual socket connection, which this change does
    not build (see this PR's report). Acceptable for an MVP-level guard
    against the overwhelmingly common cases (hardcoded metadata/private-
    network URLs, disallowed hosts) — not a hardened defense against an
    adversary who controls DNS for an allowlisted host.
    """

    def __init__(self, allowed_hosts: frozenset[str], timeout_seconds: float) -> None:
        self._allowed_hosts = allowed_hosts
        self._timeout_seconds = timeout_seconds

    async def download(self, url: str, *, max_size_bytes: int) -> DownloadedMedia:
        current_url = url
        for _ in range(_MAX_REDIRECTS + 1):
            self._validate_url(current_url)
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout_seconds, follow_redirects=False
                ) as client:
                    async with client.stream("GET", current_url) as response:
                        if response.status_code in _REDIRECT_STATUS_CODES:
                            location = response.headers.get("location")
                            if not location:
                                raise MediaDownloadError(
                                    "http_error", "redirect response missing Location header"
                                )
                            current_url = location
                            continue
                        if response.is_error:
                            raise MediaDownloadError(
                                "http_error", f"media download returned {response.status_code}"
                            )
                        return await self._stream_to_temp_file(response, max_size_bytes)
            except httpx.TimeoutException as exc:
                raise MediaDownloadError("timeout", "media download timed out") from exc

        raise MediaDownloadError(
            "redirect_blocked", f"exceeded {_MAX_REDIRECTS} redirects downloading media"
        )

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise MediaDownloadError("ssrf_blocked", f"disallowed scheme {parsed.scheme!r}")

        host = parsed.hostname
        if host is None or host not in self._allowed_hosts:
            raise MediaDownloadError("ssrf_blocked", f"host {host!r} is not in the allowlist")

        try:
            resolved = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise MediaDownloadError("ssrf_blocked", f"could not resolve host {host!r}") from exc

        for _family, _type, _proto, _canonname, sockaddr in resolved:
            address = ipaddress.ip_address(sockaddr[0])
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            ):
                raise MediaDownloadError(
                    "ssrf_blocked",
                    f"host {host!r} resolves to a disallowed address {address}",
                )

    async def _stream_to_temp_file(
        self, response: httpx.Response, max_size_bytes: int
    ) -> DownloadedMedia:
        fd, path = tempfile.mkstemp(prefix="media-download-")
        os.chmod(path, 0o600)
        hasher = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(fd, "wb") as temp_file:
                # `httpx.Response.aiter_bytes()` is typed as the narrower
                # `AsyncIterator[bytes]`, but is actually always an async
                # generator at runtime — `aclosing` needs the wider
                # `AsyncGenerator` type to type-check its own `aclose()` call.
                byte_stream = cast("AsyncGenerator[bytes, None]", response.aiter_bytes())
                async with aclosing(byte_stream) as stream:
                    async for chunk in stream:
                        size += len(chunk)
                        if size > max_size_bytes:
                            raise MediaDownloadError(
                                "size_exceeded",
                                f"media download exceeded {max_size_bytes} bytes",
                            )
                        hasher.update(chunk)
                        temp_file.write(chunk)
        except Exception:
            os.unlink(path)
            raise

        return DownloadedMedia(
            path=path,
            size_bytes=size,
            sha256=hasher.hexdigest(),
            content_type=response.headers.get("content-type"),
        )
