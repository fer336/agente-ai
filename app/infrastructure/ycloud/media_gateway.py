from app.domain.repositories.media_gateway import MediaLocation
from app.infrastructure.ycloud.client import YCloudClient


class YCloudMediaGateway:
    """`YCloudClient`-based real implementation of the `MediaGateway` port
    (PRD.md §24.1).

    UNVERIFIED against a live YCloud account (no live credentials in this
    environment — see this change's report). Response field names
    (`url`/`mime_type`/`sha256`) follow Meta's WhatsApp Cloud API's
    documented media-metadata response shape, which YCloud's own docs were
    not available to confirm — the highest-uncertainty part of this module,
    same caveat as `webhook_parser.py`'s interactive-button mapping. Not
    wired into DI yet (still `FakeYCloudMediaGateway` by default, matching
    every other gateway's fake-by-default swap-point convention).
    """

    def __init__(self, client: YCloudClient) -> None:
        self._client = client

    async def get_media_location(self, media_id: str) -> MediaLocation:
        data = await self._client.get_media(media_id)
        return MediaLocation(
            url=str(data["url"]),
            mime_type=str(data.get("mime_type", "")),
            sha256=str(data["sha256"]) if data.get("sha256") else None,
        )
