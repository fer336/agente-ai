import re

from app.domain.entities.message import ROLE_ASSISTANT
from app.domain.repositories.llm_provider import LLMProvider, ResponseContext
from app.infrastructure.llm.exceptions import LLMProviderError

#: A greeting at the very start of a reply ("¡Hola!", "Buenas tardes,", "Hola Fernando!").
#: The optional name is a capitalised word (or "che") that ends in punctuation, so
#: "Hola, sí atendemos" keeps its "sí" and "Buenas noticias:" is not a greeting.
_LEADING_GREETING = re.compile(
    r"^\s*[¡!]*\s*"
    r"(?:hola|holi|holis|hey"
    r"|buenas\s+(?:tardes|noches|d[ií]as)"
    r"|buen(?:os)?\s+d[ií]as?"
    r"|buenas(?=\s*(?:[,!.¡]|$)))"
    r"(?![\wáéíóúñ])"
    r"(?:\s+(?:che|(?-i:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+))(?=\s*[,!.¡]))?"
    r"[\s,!.¡:;-]*",
    re.IGNORECASE,
)


def conversation_started(recent_messages: list[dict[str, str]]) -> bool:
    """True once the assistant already spoke in this conversation.

    Only the first reply of a conversation may greet; every later one continues a
    chat that is already running.
    """
    return any(message.get("role") == ROLE_ASSISTANT for message in recent_messages)


def strip_leading_greeting(text: str) -> str:
    """Drops a greeting the text opens with; the rest is capitalised.

    A text that is nothing but a greeting is returned untouched.
    """
    match = _LEADING_GREETING.match(text)
    if match is None:
        return text
    remainder = text[match.end() :]
    if not remainder.strip():
        return text
    return remainder[0].upper() + remainder[1:]


def without_mid_conversation_greeting(text: str, recent_messages: list[dict[str, str]]) -> str:
    """Deterministic safety net behind the prompts: no greeting after the first reply."""
    if conversation_started(recent_messages):
        return strip_leading_greeting(text)
    return text


async def generate_or_fallback(
    llm_provider: LLMProvider,
    conversation_id: str,
    intent: str,
    collected_data: dict[str, object],
    static_text: str,
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
    temperature: float | None = None,
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
        text = await llm_provider.generate_response(
            ResponseContext(
                conversation_id=conversation_id,
                intent=intent,
                collected_data=collected_data,
                recent_messages=recent_messages,
                contact_memory=contact_memory,
                conversation_started=conversation_started(recent_messages),
                temperature=temperature,
            )
        )
        return without_mid_conversation_greeting(text, recent_messages)
    except LLMProviderError:
        return static_text
