import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from app.application.audio.transcribe_audio import TranscribeAudioUseCase, TranscriptionRepositories
from app.domain.entities.media_processing_job import MediaProcessingJob
from app.domain.entities.message import Message
from app.domain.repositories.media_gateway import MediaLocation
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from app.infrastructure.media.exceptions import MediaDownloadError
from app.infrastructure.media.fake_media_downloader import FakeMediaDownloader
from app.infrastructure.transcription.exceptions import TranscriptionAPIError
from app.infrastructure.transcription.fake_transcription_gateway import FakeTranscriptionGateway
from app.infrastructure.ycloud.fake_media_gateway import FakeYCloudMediaGateway
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.audio_samples import TINY_VALID_OGG_BYTES
from tests.fixtures.gateways import (
    make_agent_invoker,
    make_conversation_repository,
    make_ingest_message_use_case,
    make_media_processing_job_repository,
)
from tests.fixtures.seed_objects import make_conversation

_CONVERSATION_ID = "ycloud-+5491122334455"
_ALLOWED_MIME_TYPES = frozenset({"audio/ogg", "audio/mpeg", "audio/mp4", "audio/aac"})


def _audio_message(
    message_id: str = "msg-audio-1", conversation_id: str = _CONVERSATION_ID
) -> Message:
    return Message(
        id=message_id,
        conversation_id=ConversationId(conversation_id),
        external_message_id=ExternalMessageId(f"wamid.{message_id}"),
        direction="inbound",
        text="",
        created_at=datetime(2026, 8, 30, 9, 0, tzinfo=UTC),
        message_type="audio",
        media_id="media-1",
        media_mime_type="audio/ogg",
        media_status="pending",
        transcription_status="pending",
    )


def _job(
    job_id: str = "job-1", message_id: str = "msg-audio-1", status: str = "pending"
) -> MediaProcessingJob:
    return MediaProcessingJob(
        id=job_id,
        message_id=message_id,
        status=status,
        media_id="media-1",
        media_mime_type="audio/ogg",
        attempts=0,
    )


class _TrackingDownloader:
    """Wraps a `MediaDownloader`, recording every produced temp-file path so
    a test can assert it was deleted once `execute()` returns.
    """

    def __init__(self, inner: FakeMediaDownloader) -> None:
        self._inner = inner
        self.produced_paths: list[str] = []

    async def download(self, url: str, *, max_size_bytes: int):
        result = await self._inner.download(url, max_size_bytes=max_size_bytes)
        self.produced_paths.append(result.path)
        return result


class _SlowTranscriptionGateway:
    """A `TranscriptionGateway` that never returns within any test timeout,
    so `asyncio.wait_for`'s own timeout always wins.
    """

    async def transcribe(self, audio_path: str, mime_type: str) -> str:
        await asyncio.sleep(10)
        return "too late"


def _build_use_case(
    *,
    job_repository: object | None = None,
    message_repository: object | None = None,
    media_gateway: object | None = None,
    media_downloader: object | None = None,
    transcription_gateway: object | None = None,
    messaging_gateway: FakeYCloudMessagingGateway | None = None,
    ingest_message_use_case: object | None = None,
    conversation_repository: object | None = None,
    agent_invoker: object | None = None,
    max_duration_seconds: int = 180,
    allowed_mime_types: frozenset[str] = _ALLOWED_MIME_TYPES,
) -> tuple[TranscribeAudioUseCase, object, object, FakeYCloudMessagingGateway, object]:
    job_repository = (
        job_repository if job_repository is not None else make_media_processing_job_repository()
    )
    message_repository = (
        message_repository if message_repository is not None else FakeMessageRepository()
    )
    media_gateway = (
        media_gateway
        if media_gateway is not None
        else FakeYCloudMediaGateway(
            {
                "media-1": MediaLocation(
                    url="https://cdn.ycloud.com/media/1", mime_type="audio/ogg", sha256=None
                )
            }
        )
    )
    media_downloader = (
        media_downloader
        if media_downloader is not None
        else FakeMediaDownloader(content=TINY_VALID_OGG_BYTES)
    )
    transcription_gateway = (
        transcription_gateway
        if transcription_gateway is not None
        else FakeTranscriptionGateway(transcript="hola quiero un turno")
    )
    messaging_gateway = (
        messaging_gateway if messaging_gateway is not None else FakeYCloudMessagingGateway()
    )

    if ingest_message_use_case is None:
        conversation_repository = (
            conversation_repository
            if conversation_repository is not None
            else make_conversation_repository()
        )
        ingest_message_use_case = make_ingest_message_use_case(
            conversation_repository=conversation_repository,
            agent_invoker=agent_invoker,
            debounce_seconds=0.05,
        )

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[TranscriptionRepositories]:
        yield TranscriptionRepositories(
            media_processing_jobs=job_repository, messages=message_repository
        )

    use_case = TranscribeAudioUseCase(
        repositories_provider=repositories_provider,
        media_gateway=media_gateway,
        media_downloader=media_downloader,
        transcription_gateway=transcription_gateway,
        messaging_gateway=messaging_gateway,
        ingest_message_use_case=ingest_message_use_case,
        allowed_mime_types=allowed_mime_types,
        max_size_bytes=16_000_000,
        max_duration_seconds=max_duration_seconds,
        transcription_timeout_seconds=5,
        provider_name="groq",
        model_name="whisper-large-v3-turbo",
    )
    return use_case, job_repository, message_repository, messaging_gateway, ingest_message_use_case


@pytest.mark.asyncio
async def test_missing_job_returns_without_error():
    use_case, *_ = _build_use_case()

    await use_case.execute("missing-job")


@pytest.mark.asyncio
async def test_already_claimed_job_is_skipped():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job(status="downloading"))
    use_case, _, message_repository, messaging_gateway, _ = _build_use_case(
        job_repository=job_repository
    )

    await use_case.execute("job-1")

    assert messaging_gateway.sent_messages == []
    assert await message_repository.get_by_id("msg-audio-1") is None


@pytest.mark.asyncio
async def test_unsupported_mime_type_is_rejected_without_network_calls():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    media_gateway = FakeYCloudMediaGateway()
    media_downloader = FakeMediaDownloader()
    use_case, _, _, messaging_gateway, _ = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        media_gateway=media_gateway,
        media_downloader=media_downloader,
        allowed_mime_types=frozenset({"audio/mp4"}),
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "rejected"
    message = await message_repository.get_by_id("msg-audio-1")
    assert message is not None
    assert message.media_status == "rejected"
    assert message.transcription_status == "rejected"
    assert media_gateway.calls == []
    assert media_downloader.calls == []
    assert len(messaging_gateway.sent_messages) == 1


@pytest.mark.asyncio
async def test_successful_transcription_completes_job_and_updates_message():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2 = _build_use_case(
        job_repository=job_repository, message_repository=message_repository
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "completed"
    assert job.completed_at is not None
    message = await message_repository.get_by_id("msg-audio-1")
    assert message is not None
    assert message.text == "hola quiero un turno"
    assert message.transcription == "hola quiero un turno"
    assert message.transcription_status == "completed"
    assert message.transcription_provider == "groq"
    assert message.transcription_model == "whisper-large-v3-turbo"


@pytest.mark.asyncio
async def test_successful_transcription_forwards_to_agent_invoker():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_=_CONVERSATION_ID, mode="agent"))
    agent_invoker = make_agent_invoker()
    use_case, *_2 = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        conversation_repository=conversation_repository,
        agent_invoker=agent_invoker,
    )

    await use_case.execute("job-1")
    await asyncio.sleep(0.15)

    assert len(agent_invoker.calls) == 1
    conversation_id, message_ids, user_message, button_payload = agent_invoker.calls[0]
    assert conversation_id == ConversationId(_CONVERSATION_ID)
    assert message_ids == ["msg-audio-1"]
    assert user_message == "hola quiero un turno"
    assert button_payload is None


@pytest.mark.asyncio
async def test_empty_transcript_sends_fallback_and_does_not_forward_to_agent():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    agent_invoker = make_agent_invoker()
    use_case, *_2, messaging_gateway, _ = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        transcription_gateway=FakeTranscriptionGateway(transcript="   "),
        agent_invoker=agent_invoker,
    )

    await use_case.execute("job-1")
    await asyncio.sleep(0.1)

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "completed"
    assert agent_invoker.calls == []
    assert len(messaging_gateway.sent_messages) == 1


@pytest.mark.asyncio
async def test_transcription_timeout_fails_job_and_sends_fallback():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2, messaging_gateway, _ = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        transcription_gateway=_SlowTranscriptionGateway(),
    )
    use_case._transcription_timeout_seconds = 0.05  # type: ignore[attr-defined]

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "failed"
    assert job.last_error == "timeout"
    message = await message_repository.get_by_id("msg-audio-1")
    assert message is not None
    assert message.transcription_status == "failed"
    assert message.transcription_error == "timeout"
    assert len(messaging_gateway.sent_messages) == 1


@pytest.mark.asyncio
async def test_transcription_provider_error_fails_job_and_sends_fallback():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2, messaging_gateway, _ = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        transcription_gateway=FakeTranscriptionGateway(raises=TranscriptionAPIError(500, "boom")),
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "failed"
    assert len(messaging_gateway.sent_messages) == 1


@pytest.mark.asyncio
async def test_download_ssrf_blocked_rejects_the_job():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2, messaging_gateway, _ = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        media_downloader=FakeMediaDownloader(raises=MediaDownloadError("ssrf_blocked", "blocked")),
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "rejected"
    assert len(messaging_gateway.sent_messages) == 1


@pytest.mark.asyncio
async def test_media_location_lookup_failure_fails_the_job():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2, messaging_gateway, _ = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        # No locations configured -> `get_media_location("media-1")` raises
        # a plain `KeyError`, exercising the generic-exception branch around
        # the media gateway call (not a `MediaDownloadError`).
        media_gateway=FakeYCloudMediaGateway(),
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "failed"
    assert len(messaging_gateway.sent_messages) == 1


@pytest.mark.asyncio
async def test_unparseable_audio_rejects_the_job_for_undetermined_duration():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2, messaging_gateway, _ = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        # `mutagen.File()` returns `None` (no exception) for bytes it can't
        # recognize as any known audio container.
        media_downloader=FakeMediaDownloader(content=b"not-a-real-audio-file-at-all"),
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "rejected"
    assert job.last_error == "could not determine audio duration"
    assert len(messaging_gateway.sent_messages) == 1


@pytest.mark.asyncio
async def test_duration_probe_exception_rejects_the_job(monkeypatch: pytest.MonkeyPatch):
    import app.application.audio.transcribe_audio as transcribe_audio_module

    def _raising_mutagen_file(path: str):
        raise OSError("cannot read file")

    monkeypatch.setattr(transcribe_audio_module, "MutagenFile", _raising_mutagen_file)
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2, messaging_gateway, _ = _build_use_case(
        job_repository=job_repository, message_repository=message_repository
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "rejected"
    assert job.last_error == "could not determine audio duration"
    assert len(messaging_gateway.sent_messages) == 1


class _FailingMessagingGateway(FakeYCloudMessagingGateway):
    """A `MessagingGateway` whose `send_text_message` always raises, so a
    fallback-reply attempt (`TranscribeAudioUseCase._send_fallback`) never
    crashes the worker even when YCloud itself is unreachable.
    """

    async def send_text_message(self, to, text: str) -> str:  # type: ignore[override]
        raise RuntimeError("ycloud unreachable")


@pytest.mark.asyncio
async def test_fallback_reply_failure_does_not_raise():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2 = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        messaging_gateway=_FailingMessagingGateway(),
        transcription_gateway=FakeTranscriptionGateway(raises=TranscriptionAPIError(500, "boom")),
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "failed"


@pytest.mark.asyncio
async def test_download_timeout_fails_the_job():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2 = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        media_downloader=FakeMediaDownloader(raises=MediaDownloadError("timeout", "timed out")),
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "failed"


@pytest.mark.asyncio
async def test_audio_exceeding_max_duration_is_rejected():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    use_case, *_2 = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        max_duration_seconds=0,  # even the 0.1s tiny fixture exceeds this
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "rejected"
    message = await message_repository.get_by_id("msg-audio-1")
    assert message is not None
    assert message.media_status == "rejected"


@pytest.mark.asyncio
async def test_hash_mismatch_is_rejected():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    media_gateway = FakeYCloudMediaGateway(
        {
            "media-1": MediaLocation(
                url="https://cdn.ycloud.com/media/1",
                mime_type="audio/ogg",
                sha256="does-not-match",
            )
        }
    )
    use_case, *_2 = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        media_gateway=media_gateway,
    )

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "rejected"


@pytest.mark.asyncio
async def test_downloaded_temp_file_is_always_deleted_on_success():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    downloader = _TrackingDownloader(FakeMediaDownloader(content=TINY_VALID_OGG_BYTES))
    use_case, *_2 = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        media_downloader=downloader,
    )

    await use_case.execute("job-1")

    assert downloader.produced_paths
    assert not os.path.exists(downloader.produced_paths[0])


@pytest.mark.asyncio
async def test_downloaded_temp_file_is_deleted_even_when_rejected():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job())
    message_repository = FakeMessageRepository()
    await message_repository.save(_audio_message())
    downloader = _TrackingDownloader(FakeMediaDownloader(content=TINY_VALID_OGG_BYTES))
    use_case, *_2 = _build_use_case(
        job_repository=job_repository,
        message_repository=message_repository,
        media_downloader=downloader,
        max_duration_seconds=0,
    )

    await use_case.execute("job-1")

    assert downloader.produced_paths
    assert not os.path.exists(downloader.produced_paths[0])


@pytest.mark.asyncio
async def test_message_not_found_marks_job_failed():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job(message_id="does-not-exist"))
    use_case, *_2 = _build_use_case(job_repository=job_repository)

    await use_case.execute("job-1")

    job = await job_repository.get_by_id("job-1")
    assert job is not None
    assert job.status == "failed"
