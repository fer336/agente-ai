from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId

#: PRD.md §33's documented `messages.media_status` enum (audio pipeline,
#: PRD.md §24.1). `None` (the dataclass default) means "not a media message".
MEDIA_PENDING = "pending"
MEDIA_DOWNLOADING = "downloading"
MEDIA_TRANSCRIBING = "transcribing"
MEDIA_COMPLETED = "completed"
MEDIA_FAILED = "failed"
MEDIA_REJECTED = "rejected"

#: Conversational-memory module's LLM-facing role labels (no PRD.md section
#: number — this session's own brief). `Message.role` is `None` for rows
#: written before this module existed; `MemoryService`'s own `_message_role`
#: falls back to `direction` in that case.
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


@dataclass
class Message:
    """Minimal message shell, sized to type gateway Protocol signatures.

    The `media_*`/`transcription_*` fields (PRD.md §33) are only populated
    for `message_type="audio"` — a `"text"` message (the default) leaves all
    of them at their `None` default. `text` starts empty for an inbound
    audio message and is filled in with the transcript once
    `TranscribeAudioUseCase` completes (PRD.md §24.1's "Normalizar texto"
    step), at which point it is fed through the exact same
    debounce/lock/agent-invocation path a typed message already uses — see
    `IngestMessageUseCase.resume_after_transcription`.
    """

    id: str
    conversation_id: ConversationId
    external_message_id: ExternalMessageId
    direction: str
    text: str
    created_at: datetime
    message_type: str = "text"
    media_id: str | None = None
    media_mime_type: str | None = None
    media_sha256: str | None = None
    media_status: str | None = None
    inbound_received_at: datetime | None = None
    transcription: str | None = None
    transcription_status: str | None = None
    transcription_provider: str | None = None
    transcription_model: str | None = None
    transcription_duration_ms: int | None = None
    transcription_error: str | None = None
    role: str | None = None
