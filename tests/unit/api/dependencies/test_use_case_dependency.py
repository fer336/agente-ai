from app.api.dependencies.use_cases import get_ingest_message_use_case
from app.application.messages.ingest_message import IngestMessageUseCase


def test_get_ingest_message_use_case_returns_an_ingest_message_use_case():
    use_case = get_ingest_message_use_case()

    assert isinstance(use_case, IngestMessageUseCase)


def test_get_ingest_message_use_case_returns_the_same_cached_instance_across_calls():
    first = get_ingest_message_use_case()
    second = get_ingest_message_use_case()

    assert first is second
