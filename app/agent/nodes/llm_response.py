from app.domain.repositories.llm_provider import LLMProvider, ResponseContext
from app.infrastructure.llm.exceptions import LLMProviderError


async def generate_or_fallback(
    llm_provider: LLMProvider,
    conversation_id: str,
    intent: str,
    collected_data: dict[str, object],
    static_text: str,
) -> str:
    """Calls `LLMProvider.generate_response`, falling back to `static_text`
    on any provider failure (timeout/auth/bad output/etc).

    Shared by every node that wants a varied, LLM-worded reply for a
    re-prompt/retry turn (PRD.md has no section for this — this session's
    own brief: a patient who gets stuck on the same step should never see
    the exact same canned sentence twice) while staying as reliable as a
    hardcoded string when the LLM itself is unavailable — the LLM only
    ever varies wording, it never gets to leave the patient without a
    reply.
    """
    try:
        return await llm_provider.generate_response(
            ResponseContext(
                conversation_id=conversation_id,
                intent=intent,
                collected_data=collected_data,
            )
        )
    except LLMProviderError:
        return static_text
