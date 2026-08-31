from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MediaLocation:
    """Result of resolving a vendor media id to a downloadable location.

    `mime_type`/`sha256` come from the vendor's own media-metadata response
    (e.g. YCloud's `GET /v1/media/{id}`), independent of whatever MIME type
    the original webhook payload claimed — `TranscribeAudioUseCase` treats
    this as the authoritative value for its allowlist check. `sha256` is
    `None` when the vendor does not report one (PRD.md §24.3: "Validar hash
    cuando esté disponible" — optional, not always verifiable).
    """

    url: str
    mime_type: str
    sha256: str | None


@runtime_checkable
class MediaGateway(Protocol):
    """Port to a vendor's media-metadata API — resolves a media id to a
    short-lived, authorized download URL (PRD.md §24.1: "Descargar el
    archivo desde YCloud mediante el worker").

    Deliberately separate from `MessagingGateway` (send-only): this is a
    read-only, ordinarily short-lived credential fetch, not a message send.
    """

    async def get_media_location(self, media_id: str) -> MediaLocation: ...
