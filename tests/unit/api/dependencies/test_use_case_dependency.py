from app.api.dependencies.use_cases import (
    get_ingest_message_use_case,
    get_transcribe_audio_use_case,
)
from app.application.audio.transcribe_audio import TranscribeAudioUseCase
from app.application.messages.ingest_message import IngestMessageUseCase


def test_get_ingest_message_use_case_returns_an_ingest_message_use_case():
    use_case = get_ingest_message_use_case()

    assert isinstance(use_case, IngestMessageUseCase)


def test_get_ingest_message_use_case_returns_the_same_cached_instance_across_calls():
    first = get_ingest_message_use_case()
    second = get_ingest_message_use_case()

    assert first is second


def test_get_ingest_message_use_case_wires_a_workflow_session_repositories_provider():
    # T5 (review-2358088d31f27658, R3-expire-all-flag-ignored-without-
    # repositories-provider): `IngestMessageUseCase`'s new-conversation
    # rotation (`ingest_message.py`) passes `expire_all_pending_generations=
    # True` to `RotateWorkflowSessionUseCase`, but that flag is silently
    # ignored unless a `workflow_session_repositories_provider` was wired in
    # — without one, `RotateWorkflowSessionUseCase.__init__` falls back to a
    # bare `ConversationRepository` (`repositories.conversations`), which
    # skips ALL pending-action expiry, not only the "every generation" case.
    # This proves the real FastAPI dependency wires the provider so
    # production never silently falls into that narrower fallback.
    use_case = get_ingest_message_use_case()

    assert use_case._workflow_session_repositories_provider is not None


def test_get_transcribe_audio_use_case_returns_a_transcribe_audio_use_case():
    use_case = get_transcribe_audio_use_case()

    assert isinstance(use_case, TranscribeAudioUseCase)


def test_get_transcribe_audio_use_case_returns_the_same_cached_instance_across_calls():
    first = get_transcribe_audio_use_case()
    second = get_transcribe_audio_use_case()

    assert first is second
