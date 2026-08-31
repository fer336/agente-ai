import pytest

from app.domain.repositories.transcription_gateway import TranscriptionGateway
from app.infrastructure.transcription.fake_transcription_gateway import FakeTranscriptionGateway


def test_fake_satisfies_transcription_gateway_protocol():
    assert isinstance(FakeTranscriptionGateway(), TranscriptionGateway)


@pytest.mark.asyncio
async def test_returns_configured_transcript():
    gateway = FakeTranscriptionGateway(transcript="hola quiero un turno")

    result = await gateway.transcribe("/tmp/audio.ogg", "audio/ogg")

    assert result == "hola quiero un turno"


@pytest.mark.asyncio
async def test_records_calls():
    gateway = FakeTranscriptionGateway(transcript="hola")

    await gateway.transcribe("/tmp/audio.ogg", "audio/ogg")

    assert gateway.calls == [("/tmp/audio.ogg", "audio/ogg")]


@pytest.mark.asyncio
async def test_raises_configured_exception():
    gateway = FakeTranscriptionGateway(raises=TimeoutError("timed out"))

    with pytest.raises(TimeoutError):
        await gateway.transcribe("/tmp/audio.ogg", "audio/ogg")
