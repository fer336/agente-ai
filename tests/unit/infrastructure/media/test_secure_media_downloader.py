import os
import stat

import httpx
import pytest

import app.infrastructure.media.secure_media_downloader as downloader_module
from app.infrastructure.media.exceptions import MediaDownloadError
from app.infrastructure.media.secure_media_downloader import SecureMediaDownloader

_PUBLIC_IP = "93.184.216.34"  # example.com's long-standing public test IP
_PRIVATE_IP = "10.0.0.5"
_LOOPBACK_IP = "127.0.0.1"
_METADATA_IP = "169.254.169.254"


def _patch_dns(monkeypatch: pytest.MonkeyPatch, hosts_to_ips: dict[str, str]) -> None:
    def fake_getaddrinfo(host: str, port: object) -> list[tuple]:
        ip = hosts_to_ips.get(host)
        if ip is None:
            raise OSError(f"no mock DNS entry for {host}")
        return [(None, None, None, "", (ip, 0))]

    monkeypatch.setattr(downloader_module.socket, "getaddrinfo", fake_getaddrinfo)


def _patch_transport(monkeypatch: pytest.MonkeyPatch, responses: list[httpx.Response]) -> list:
    captured: list[httpx.Request] = []
    remaining = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return remaining.pop(0)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(downloader_module.httpx, "AsyncClient", patched_async_client)
    return captured


def _make_downloader(allowed_hosts: set[str]) -> SecureMediaDownloader:
    return SecureMediaDownloader(allowed_hosts=frozenset(allowed_hosts), timeout_seconds=5)


@pytest.mark.asyncio
async def test_rejects_non_https_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("http://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "ssrf_blocked"


@pytest.mark.asyncio
async def test_rejects_host_not_in_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://evil.example.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "ssrf_blocked"


@pytest.mark.asyncio
async def test_rejects_when_resolved_address_is_private(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _PRIVATE_IP})
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "ssrf_blocked"


@pytest.mark.asyncio
async def test_rejects_when_resolved_address_is_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _LOOPBACK_IP})
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "ssrf_blocked"


@pytest.mark.asyncio
async def test_rejects_when_resolved_address_is_cloud_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _METADATA_IP})
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "ssrf_blocked"


@pytest.mark.asyncio
async def test_downloads_successfully_when_host_and_address_are_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _PUBLIC_IP})
    _patch_transport(
        monkeypatch,
        [httpx.Response(200, content=b"fake-audio-bytes", headers={"content-type": "audio/ogg"})],
    )
    downloader = _make_downloader({"cdn.ycloud.com"})

    result = await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)

    assert os.path.exists(result.path)
    with open(result.path, "rb") as f:
        assert f.read() == b"fake-audio-bytes"
    assert result.size_bytes == len(b"fake-audio-bytes")
    assert result.content_type == "audio/ogg"
    # PRD.md §74.7: "El archivo temporal tendrá permisos restrictivos".
    mode = stat.S_IMODE(os.stat(result.path).st_mode)
    assert mode == 0o600


@pytest.mark.asyncio
async def test_aborts_and_deletes_temp_file_when_size_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _PUBLIC_IP})
    _patch_transport(monkeypatch, [httpx.Response(200, content=b"x" * 2_000)])
    downloader = _make_downloader({"cdn.ycloud.com"})

    created_paths: list[str] = []
    original_mkstemp = downloader_module.tempfile.mkstemp

    def tracking_mkstemp(*args: object, **kwargs: object):
        fd, path = original_mkstemp(*args, **kwargs)
        created_paths.append(path)
        return fd, path

    monkeypatch.setattr(downloader_module.tempfile, "mkstemp", tracking_mkstemp)

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)

    assert exc_info.value.reason == "size_exceeded"
    assert created_paths
    assert not os.path.exists(created_paths[0])


@pytest.mark.asyncio
async def test_follows_redirect_to_an_allowed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _PUBLIC_IP, "cdn2.ycloud.com": _PUBLIC_IP})
    _patch_transport(
        monkeypatch,
        [
            httpx.Response(302, headers={"location": "https://cdn2.ycloud.com/media/1"}),
            httpx.Response(200, content=b"redirected-bytes"),
        ],
    )
    downloader = SecureMediaDownloader(
        allowed_hosts=frozenset({"cdn.ycloud.com", "cdn2.ycloud.com"}), timeout_seconds=5
    )

    result = await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)

    with open(result.path, "rb") as f:
        assert f.read() == b"redirected-bytes"


@pytest.mark.asyncio
async def test_rejects_redirect_to_a_disallowed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _PUBLIC_IP})
    _patch_transport(
        monkeypatch,
        [httpx.Response(302, headers={"location": "https://evil.example.com/media/1"})],
    )
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "ssrf_blocked"


@pytest.mark.asyncio
async def test_raises_http_error_on_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _PUBLIC_IP})
    _patch_transport(monkeypatch, [httpx.Response(404, text="not found")])
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "http_error"


@pytest.mark.asyncio
async def test_rejects_when_dns_resolution_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # No mock DNS entry configured -> `_patch_dns`'s fake `getaddrinfo` raises
    # `OSError`, exercising the "could not resolve host" branch.
    _patch_dns(monkeypatch, {})
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "ssrf_blocked"


@pytest.mark.asyncio
async def test_rejects_redirect_missing_location_header(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _PUBLIC_IP})
    _patch_transport(monkeypatch, [httpx.Response(302)])
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "http_error"


@pytest.mark.asyncio
async def test_rejects_when_redirect_chain_exceeds_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _PUBLIC_IP})
    _patch_transport(
        monkeypatch,
        [
            httpx.Response(302, headers={"location": "https://cdn.ycloud.com/media/2"}),
            httpx.Response(302, headers={"location": "https://cdn.ycloud.com/media/3"}),
            httpx.Response(302, headers={"location": "https://cdn.ycloud.com/media/4"}),
        ],
    )
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "redirect_blocked"


@pytest.mark.asyncio
async def test_raises_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dns(monkeypatch, {"cdn.ycloud.com": _PUBLIC_IP})

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(downloader_module.httpx, "AsyncClient", patched_async_client)
    downloader = _make_downloader({"cdn.ycloud.com"})

    with pytest.raises(MediaDownloadError) as exc_info:
        await downloader.download("https://cdn.ycloud.com/media/1", max_size_bytes=1_000)
    assert exc_info.value.reason == "timeout"
