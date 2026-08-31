from app.domain.repositories.transcription_gateway import TranscriptionGateway


class ConformingTranscriptionGateway:
    async def transcribe(self, audio_path, mime_type):
        return ""


class PartialTranscriptionGateway:
    pass


def test_conforming_class_satisfies_transcription_gateway_protocol():
    assert isinstance(ConformingTranscriptionGateway(), TranscriptionGateway)


def test_partial_class_does_not_satisfy_transcription_gateway_protocol():
    assert not isinstance(PartialTranscriptionGateway(), TranscriptionGateway)
