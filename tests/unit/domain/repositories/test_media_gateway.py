from app.domain.repositories.media_gateway import MediaGateway, MediaLocation


class ConformingMediaGateway:
    async def get_media_location(self, media_id):
        return MediaLocation(url="https://example.com/media/1", mime_type="audio/ogg", sha256=None)


class PartialMediaGateway:
    pass


def test_conforming_class_satisfies_media_gateway_protocol():
    assert isinstance(ConformingMediaGateway(), MediaGateway)


def test_partial_class_does_not_satisfy_media_gateway_protocol():
    assert not isinstance(PartialMediaGateway(), MediaGateway)


def test_media_location_is_frozen():
    location = MediaLocation(url="https://example.com/media/1", mime_type="audio/ogg", sha256="abc")

    assert location.url == "https://example.com/media/1"
    assert location.sha256 == "abc"
