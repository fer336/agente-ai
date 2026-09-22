import re

from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.repositories.llm_provider import LLMProvider

_UNKNOWN_ANSWER = (
    "Ese dato no lo tengo confirmado. Si querés, te comunico con administración para revisarlo."
)

#: Deterministic backstop (PRD.md §75.5: "prompt-injection... debe ser
#: bloqueado por lógica de negocio, no solo confiando en el prompt"), same
#: "never trust the prompt alone" posture as `text_leaks_a_name`
#: (`appointment_selection.py`). Confirmed live: `understand()`'s free-text
#: "answer" field for intent=question was talked into acting as a
#: general-purpose assistant (a request for a recursive Python function got
#: real Python code back). A legitimate clinic answer never contains a code
#: block, a function/class definition, an import, or a SQL query — this is
#: a cheap, low-false-positive signal that the prompt-level defense already
#: failed, so the text must never reach the patient verbatim.
_OFF_TOPIC_PATTERNS = re.compile(
    r"```"
    r"|\bdef\s+\w+\s*\("
    r"|\bclass\s+\w+\s*[:(]"
    r"|\bimport\s+\w+"
    r"|\bfrom\s+\w+\s+import\b"
    r"|\bprint\s*\("
    r"|\bSELECT\b.+\bFROM\b"
    r"|<script"
    r"|#include"
    r"|\bfunction\s*\("
    r"|public\s+static\s+void",
    re.IGNORECASE | re.DOTALL,
)

_OFF_TOPIC_ANSWER = (
    "Solo puedo ayudarte con turnos, especialidades, obra social y datos de la clínica. "
    "Si necesitás otra cosa, te comunico con administración."
)


def _looks_off_topic(text: str) -> bool:
    return bool(_OFF_TOPIC_PATTERNS.search(text))


def create_question_node(llm_provider: LLMProvider) -> AgentNode:
    async def node(state: AgentState) -> dict[str, object]:
        """Deliver a genuine informational answer without forcing a menu.

        ``resolve_interaction`` currently obtains the text from ``understand`` and
        stores it as ``pending_answer``. This node intentionally does not mutate the
        operational stage, so an appointment can resume on the next turn. A later
        phase will replace generic LLM knowledge with a dedicated ClinicKnowledge
        repository; until then an absent answer fails closed instead of inventing.
        """

        collected_data = dict(state["collected_data"])
        pending_answer = collected_data.pop("pending_answer", None)
        stripped_answer = (
            pending_answer.strip() if isinstance(pending_answer, str) else None
        )
        if stripped_answer and _looks_off_topic(stripped_answer):
            text = _OFF_TOPIC_ANSWER
        elif stripped_answer:
            text = stripped_answer
        else:
            text = await generate_or_fallback(
                llm_provider,
                state["conversation_id"],
                "question_unknown_answer",
                {
                    "situacion": (
                        "El paciente hizo una pregunta, pero no tenemos una respuesta "
                        "confirmada para dársela."
                    ),
                    "instruccion": (
                        "Decile con calidez que ese dato no lo tenés confirmado y "
                        "ofrecele pasarlo con administración. Nunca inventes el dato."
                    ),
                },
                _UNKNOWN_ANSWER,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
        return {
            "response_text": text,
            "response_buttons": None,
            "requires_handoff": False,
            "collected_data": collected_data,
        }

    return node
