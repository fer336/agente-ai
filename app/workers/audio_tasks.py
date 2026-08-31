from app.application.audio.transcribe_audio import TranscribeAudioUseCase
from app.domain.repositories.media_processing_job_repository import MediaProcessingJobRepository

#: PRD.md §68's documented default poll batch size has no dedicated env
#: var — chosen small enough that one worker tick never monopolizes the
#: transcription provider's rate limit.
_DEFAULT_BATCH_SIZE = 10


async def process_pending_audio_jobs(
    job_repository: MediaProcessingJobRepository,
    transcribe_audio_use_case: TranscribeAudioUseCase,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> int:
    """Etapa 65's "Procesar descargas y transcripciones de audio" worker
    responsibility (PRD.md §65) — one poll tick: claims up to `batch_size`
    pending `MediaProcessingJob`s and runs `TranscribeAudioUseCase` on each,
    sequentially. Returns how many jobs were attempted.

    DELIBERATELY NOT a running process/scheduler (no ARQ/cron loop, no
    `asyncio.sleep`-based poll loop) — this mirrors the exact same gap
    already accepted for `ScheduledAction` follow-up/expiry processing
    elsewhere in this codebase (PRD.md §16.1's expiry worker: entities +
    repository + use case exist, but nothing calls them on a schedule yet).
    This function is the complete, tested, swap-point-ready processing
    step; wiring it into an actual ARQ worker/cron entrypoint is Etapa 65's
    broader "at least one worker process" concern, out of scope here.

    Failures in one job never abort the batch — `TranscribeAudioUseCase`
    already turns every failure mode (timeout, provider error, rejected
    media, missing message) into a terminal job/message state internally,
    never an unhandled exception for a well-formed job. An exception here
    would only occur for a genuine infrastructure fault (e.g. the database
    itself unreachable) — letting it propagate and stop the batch is the
    correct, safe default rather than silently swallowing it.
    """
    jobs = await job_repository.list_pending(limit=batch_size)
    for job in jobs:
        await transcribe_audio_use_case.execute(job.id)
    return len(jobs)
