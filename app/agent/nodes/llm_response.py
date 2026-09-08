from app.domain.repositories.llm_provider import LLMProvider, ResponseContext
from app.infrastructure.llm.exceptions import LLMProviderError


async def generate_or_fallback(
    llm_provider: LLMProvider,
    conversation_id: str,
    intent: str,
    collected_data: dict[str, object],
    static_text: str,
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
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

    `recent_messages`/`contact_memory` come straight from
    `AgentState["recent_messages"]`/`AgentState["contact_memory_summary"]`
    — `LangGraphAgentInvoker.handle()` already populates both once per
    turn via `MemoryService.build_agent_context`. Every call site MUST
    forward them (never `[]`/`None` unless that's genuinely what the state
    carries): without them the model has no idea what it just said one
    message ago, and reliably re-greets/re-introduces itself on back-to-
    back replies (seen live: two consecutive LLM-generated messages both
    opened with "Hola").
    """
    try:
        return await llm_provider.generate_response(
            ResponseContext(
                conversation_id=conversation_id,
                intent=intent,
                collected_data=collected_data,
                recent_messages=recent_messages,
                contact_memory=contact_memory,
            )
        )
    except LLMProviderError:
        return static_text
