import asyncio
import logging
import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from mutagen import File as MutagenFile

from app.application.messages.ingest_message import IngestMessageUseCase
from app.domain.entities.media_processing_job import COMPLETED as JOB_COMPLETED
from app.domain.entities.media_processing_job import DOWNLOADING as JOB_DOWNLOADING
from app.domain.entities.media_processing_job import FAILED as JOB_FAILED
from app.domain.entities.media_processing_job import PENDING as JOB_PENDING
from app.domain.entities.media_processing_job import REJECTED as JOB_REJECTED
from app.domain.entities.message import MEDIA_COMPLETED, MEDIA_FAILED, MEDIA_REJECTED, Message
from app.domain.repositories.gateways import MessagingGateway
from app.domain.repositories.media_downloader import DownloadedMedia, MediaDownloader
from app.domain.repositories.media_gateway import MediaGateway
from app.domain.repositories.media_processing_job_repository import MediaProcessingJobRepository
from app.domain.repositories.message_repository import MessageRepository
from app.domain.repositories.transcription_gateway import TranscriptionGateway
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.media.exceptions import MediaDownloadError
from app.infrastructure.transcription.exceptions import TranscriptionError

logger = logging.getLogger(__name__)

_FALLBACK_EMPTY_TRANSCRIPT = (
    "No pude entender el audio. ¿Podés escribir tu consulta o enviar un nuevo audio?"
)
_FALLBACK_TRANSCRIPTION_FAILED = (
    "No pude procesar tu audio en este momento. ¿Podés escribir tu consulta o "
    "enviar un nuevo audio?"
)
_FALLBACK_REJECTED = (
    "No pude procesar ese audio (formato, tamaño o duración no soportados). "
    "¿Podés escribir tu consulta?"
)


@dataclass(frozen=True)
class TranscriptionRepositories:
    """Bundles the two repositories one `TranscribeAudioUseCase.execute()` call needs."""

    media_processing_jobs: MediaProcessingJobRepository
    messages: MessageRepository


RepositoriesProvider = Callable[[], AbstractAsyncContextManager[TranscriptionRepositories]]


class TranscribeAudioUseCase:
    """Etapa 9.1's audio pipeline core (PRD.md §24.1, §24.3, §74.7, §75.8):
    claims one `MediaProcessingJob`, downloads and validates the audio,
    transcribes it, and either forwards the transcript to
    `IngestMessageUseCase.resume_after_transcription` or sends a safe
    fallback reply directly.

    Called once per job — by `app.workers.audio_tasks.process_pending_audio_jobs`,
    NOT from within an HTTP request (PRD.md §24.1: "No se transcribirá
    dentro del request HTTP del webhook").

    Opens `repositories_provider()` twice, deliberately: once to claim the
    job + read the message, and once more (or more) to write the final
    result — never once around the whole method, since the download +
    transcription network calls in between can take tens of seconds and
    must not hold a database session/connection open for that long.
    """

    def __init__(
        self,
        repositories_provider: RepositoriesProvider,
        media_gateway: MediaGateway,
        media_downloader: MediaDownloader,
        transcription_gateway: TranscriptionGateway,
        messaging_gateway: MessagingGateway,
        ingest_message_use_case: IngestMessageUseCase,
        allowed_mime_types: frozenset[str],
        max_size_bytes: int,
        max_duration_seconds: int,
        transcription_timeout_seconds: float,
        provider_name: str,
        model_name: str,
    ) -> None:
        self._repositories_provider = repositories_provider
        self._media_gateway = media_gateway
        self._media_downloader = media_downloader
        self._transcription_gateway = transcription_gateway
        self._messaging_gateway = messaging_gateway
        self._ingest_message_use_case = ingest_message_use_case
        self._allowed_mime_types = allowed_mime_types
        self._max_size_bytes = max_size_bytes
        self._max_duration_seconds = max_duration_seconds
        self._transcription_timeout_seconds = transcription_timeout_seconds
        self._provider_name = provider_name
        self._model_name = model_name

    async def execute(self, job_id: str) -> None:
        async with self._repositories_provider() as repositories:
            job = await repositories.media_processing_jobs.get_by_id(job_id)
            if job is None:
                return

            claimed = await repositories.media_processing_jobs.transition_status(
                job_id, from_status=JOB_PENDING, to_status=JOB_DOWNLOADING
            )
            if not claimed:
                # Another worker already claimed this job (PRD.md §75.8:
                # "Webhook duplicado -> no repite transcripción" / "Dos
                # workers procesando el mismo mensaje").
                return

            message = await repositories.messages.get_by_id(job.message_id)

        if message is None:
            await self._finish(
                job_id, job_status=JOB_FAILED, last_error="message not found"
            )
            return

        if job.media_mime_type not in self._allowed_mime_types:
            await self._reject(job_id, message, "unsupported mime type")
            return

        try:
            location = await self._media_gateway.get_media_location(job.media_id)
        except Exception as exc:  # noqa: BLE001 - vendor gateway errors are provider-specific
            await self._fail(job_id, message, str(exc), _FALLBACK_TRANSCRIPTION_FAILED)
            return

        downloaded: DownloadedMedia | None = None
        try:
            try:
                downloaded = await self._media_downloader.download(
                    location.url, max_size_bytes=self._max_size_bytes
                )
            except MediaDownloadError as exc:
                if exc.reason in ("ssrf_blocked", "redirect_blocked", "size_exceeded"):
                    await self._reject(job_id, message, str(exc))
                else:
                    await self._fail(job_id, message, str(exc), _FALLBACK_TRANSCRIPTION_FAILED)
                return

            rejection_reason = self._validate_downloaded_media(downloaded, location.sha256)
            if rejection_reason is not None:
                await self._reject(job_id, message, rejection_reason)
                return

            try:
                transcript = await asyncio.wait_for(
                    self._transcription_gateway.transcribe(
                        downloaded.path, job.media_mime_type
                    ),
                    timeout=self._transcription_timeout_seconds,
                )
            except TimeoutError:
                await self._fail(job_id, message, "timeout", _FALLBACK_TRANSCRIPTION_FAILED)
                return
            except TranscriptionError as exc:
                await self._fail(job_id, message, str(exc), _FALLBACK_TRANSCRIPTION_FAILED)
                return
        finally:
            if downloaded is not None and os.path.exists(downloaded.path):
                os.unlink(downloaded.path)

        if not transcript.strip():
            await self._complete_with_empty_transcript(job_id, message)
            return

        await self._complete_with_transcript(job_id, message, transcript)

    def _validate_downloaded_media(
        self, downloaded: DownloadedMedia, expected_sha256: str | None
    ) -> str | None:
        if expected_sha256 is not None and downloaded.sha256 != expected_sha256:
            return "hash mismatch"

        duration_seconds = self._probe_duration_seconds(downloaded.path)
        if duration_seconds is None:
            return "could not determine audio duration"
        if duration_seconds > self._max_duration_seconds:
            return f"audio duration {duration_seconds}s exceeds limit"
        return None

    def _probe_duration_seconds(self, path: str) -> float | None:
        try:
            audio = MutagenFile(path)
        except Exception:  # noqa: BLE001 - any parse failure means "invalid audio"
            return None
        if audio is None or audio.info is None:
            return None
        return float(audio.info.length)

    async def _reject(self, job_id: str, message: Message, reason: str) -> None:
        await self._finish(
            job_id,
            job_status=JOB_REJECTED,
            last_error=reason,
            message=message,
            media_status=MEDIA_REJECTED,
            transcription_status=MEDIA_REJECTED,
            transcription_error=reason,
        )
        await self._send_fallback(message, _FALLBACK_REJECTED)

    async def _fail(
        self, job_id: str, message: Message, reason: str, fallback_text: str
    ) -> None:
        await self._finish(
            job_id,
            job_status=JOB_FAILED,
            last_error=reason,
            message=message,
            media_status=MEDIA_FAILED,
            transcription_status=MEDIA_FAILED,
            transcription_error=reason,
        )
        await self._send_fallback(message, fallback_text)

    async def _complete_with_empty_transcript(self, job_id: str, message: Message) -> None:
        await self._finish(
            job_id,
            job_status=JOB_COMPLETED,
            message=message,
            media_status=MEDIA_COMPLETED,
            transcription_status=MEDIA_COMPLETED,
            transcription="",
        )
        await self._send_fallback(message, _FALLBACK_EMPTY_TRANSCRIPT)

    async def _complete_with_transcript(
        self, job_id: str, message: Message, transcript: str
    ) -> None:
        await self._finish(
            job_id,
            job_status=JOB_COMPLETED,
            message=message,
            text=transcript,
            media_status=MEDIA_COMPLETED,
            transcription_status=MEDIA_COMPLETED,
            transcription=transcript,
            transcription_provider=self._provider_name,
            transcription_model=self._model_name,
        )
        await self._ingest_message_use_case.resume_after_transcription(
            message.conversation_id, message.id, transcript
        )

    async def _finish(
        self,
        job_id: str,
        *,
        job_status: str,
        last_error: str | None = None,
        message: Message | None = None,
        text: str | None = None,
        media_status: str | None = None,
        transcription_status: str | None = None,
        transcription: str | None = None,
        transcription_provider: str | None = None,
        transcription_model: str | None = None,
        transcription_error: str | None = None,
    ) -> None:
        async with self._repositories_provider() as repositories:
            job = await repositories.media_processing_jobs.get_by_id(job_id)
            if job is not None:
                await repositories.media_processing_jobs.save(
                    replace(
                        job,
                        status=job_status,
                        last_error=last_error,
                        completed_at=datetime.now(UTC)
                        if job_status in (JOB_COMPLETED, JOB_FAILED, JOB_REJECTED)
                        else job.completed_at,
                    )
                )

            if message is not None:
                await repositories.messages.update(
                    replace(
                        message,
                        text=text if text is not None else message.text,
                        media_status=media_status,
                        transcription_status=transcription_status,
                        transcription=transcription,
                        transcription_provider=transcription_provider,
                        transcription_model=transcription_model,
                        transcription_error=transcription_error,
                    )
                )

    async def _send_fallback(self, message: Message, text: str) -> None:
        # `ConversationId` IS `ycloud-{phone}` by construction (see
        # `IngestMessageUseCase._resolve_or_create_conversation`'s own
        # docstring for this deliberate, documented encoding convention) —
        # reversed here rather than plumbing a separate phone lookup just
        # for this fallback-reply path.
        phone = str(message.conversation_id).removeprefix("ycloud-")
        try:
            await self._messaging_gateway.send_text_message(PhoneNumber(phone), text)
        except Exception:  # noqa: BLE001 - never let a fallback-reply failure crash the worker
            logger.warning(
                "transcribe_audio.fallback_reply_failed conversation=%s",
                message.conversation_id,
                exc_info=True,
            )
