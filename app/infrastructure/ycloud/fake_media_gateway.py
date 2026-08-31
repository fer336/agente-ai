from app.domain.repositories.media_gateway import MediaLocation


class FakeYCloudMediaGateway:
    """In-memory fake implementing `MediaGateway` for local dev and tests."""

    def __init__(self, locations_by_media_id: dict[str, MediaLocation] | None = None) -> None:
        self._locations_by_media_id = dict(locations_by_media_id) if locations_by_media_id else {}
        self.calls: list[str] = []

    async def get_media_location(self, media_id: str) -> MediaLocation:
        self.calls.append(media_id)
        location = self._locations_by_media_id.get(media_id)
        if location is None:
            raise KeyError(f"No fake MediaLocation configured for media_id={media_id!r}")
        return location
