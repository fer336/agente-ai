"""Fixed, clinic-authored answers for the clinic's most frequent topics.

These texts are code constants on purpose: the clinic's wording and figures must reach the
patient verbatim, never rephrased or invented by the LLM. This is the single place to edit
when a price or a promo changes.
"""

import re
from dataclasses import dataclass

from app.agent.handoff_offer import normalize_text
from app.domain.value_objects.menu_payloads import FAQ_TOPIC_PAYLOAD_PREFIX

#: One-shot `collected_data` key: the name of the Dentalink specialty a booking must go
#: straight to (see `ClinicTopic.book_specialty`). Set by the router, consumed (popped) by
#: the decision subgraph when it would otherwise show the specialty list.
PRESELECTED_SPECIALTY_KEY = "preselected_specialty_name"


@dataclass(frozen=True)
class ClinicTopic:
    id: str
    #: WhatsApp list row title (24 characters at most).
    title: str
    #: Accent-folded lowercase words/phrases (see `normalize_text`) that name the topic.
    keywords: tuple[str, ...]
    text: str
    #: Dentalink specialty a booking of this topic goes to, skipping the specialty list.
    book_specialty: str | None = None

    @property
    def payload(self) -> str:
        return f"{FAQ_TOPIC_PAYLOAD_PREFIX}{self.id}"


# Only the consulta particular and the blanqueamiento carry a price (confirmed by the clinic).
# The other topics must not state figures: administration confirms them.
_BLANQUEAMIENTO_TEXT = (
    "✨ *Blanqueamiento dental*\n\n"
    "El tratamiento se hace en 2 sesiones:\n\n"
    "1️⃣ Primera sesión: el doctor revisa que no haya caries ni sarro y autoriza el "
    "tratamiento.\n"
    "2️⃣ Segunda sesión: se realiza el blanqueamiento con luz halógena, dura "
    "aproximadamente 45 minutos.\n\n"
    "💰 Valor: $450.000\n\n"
    "Si está todo bien, se hace el mismo día."
)

_CONSULTA_PARTICULAR_TEXT = (
    "🦷 *Consulta particular*\n\n"
    "El valor de la consulta particular es de $60.000.\n\n"
    "La disponibilidad es limitada, así que te recomendamos agendar pronto."
)

_LIMPIEZA_PARTICULAR_TEXT = (
    "🪥 *Limpieza particular*\n\n"
    "La limpieza dental particular es sin obra social. El valor y la disponibilidad te los "
    "confirma administración.\n\n"
    "Si querés, te comunico con administración."
)

_BRACKETS_OBRA_SOCIAL_TEXT = (
    "😁 *Brackets por obra social*\n\n"
    "Sí, trabajamos brackets por obra social. Los detalles de cobertura te los confirma "
    "administración.\n\n"
    "Si querés, te comunico con administración."
)

_ALINEADORES_TEXT = (
    "😁 *Alineadores Smilesecret*\n\n"
    "Es un tratamiento completo para los 2 maxilares. Incluye:\n"
    "• Escaneo intraoral y seguimiento personalizado\n"
    "• Diseño digital 3D y planificación integral\n"
    "• Honorarios profesionales\n"
    "• Todos los alineadores necesarios\n"
    "• Retención final para cada maxilar\n\n"
    "Los valores y las formas de pago te los confirma administración.\n\n"
    "Si querés, te comunico con administración."
)

CLINIC_TOPICS: tuple[ClinicTopic, ...] = (
    ClinicTopic(
        id="blanqueamiento",
        title="Blanqueamiento dental",
        keywords=("blanqueamiento", "blanquear", "blanqueo"),
        text=_BLANQUEAMIENTO_TEXT,
    ),
    ClinicTopic(
        id="consulta_particular",
        title="Consulta particular",
        keywords=(
            "consulta particular",
            "consulta privada",
            "consulta sin obra social",
            "turno particular",
            "cita particular",
            "cuanto cuesta la consulta",
            "cuanto sale la consulta",
            "precio de la consulta",
            "valor de la consulta",
        ),
        text=_CONSULTA_PARTICULAR_TEXT,
        # The clinic books every consulta particular on the "General" specialty.
        book_specialty="General",
    ),
    ClinicTopic(
        id="limpieza_particular",
        title="Limpieza particular",
        keywords=("limpieza", "profilaxis"),
        text=_LIMPIEZA_PARTICULAR_TEXT,
    ),
    ClinicTopic(
        id="brackets_obra_social",
        title="Brackets por obra social",
        keywords=(
            "bracket",
            "brackets",
            "frenos",
            "ortodoncia con obra social",
            "ortodoncia por obra social",
        ),
        text=_BRACKETS_OBRA_SOCIAL_TEXT,
    ),
    ClinicTopic(
        id="alineadores",
        title="Alineadores",
        keywords=(
            "alineador",
            "alineadores",
            "smilesecret",
            "smile secret",
            "invisalign",
            "ortodoncia invisible",
        ),
        text=_ALINEADORES_TEXT,
    ),
)


def topic_by_id(topic_id: object) -> ClinicTopic | None:
    return next((topic for topic in CLINIC_TOPICS if topic.id == topic_id), None)


def _mentions(normalized_text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}", normalized_text) is not None


def match_clinic_topic(text: str) -> ClinicTopic | None:
    """The first topic whose keyword the text names (accent- and case-insensitive)."""
    normalized = normalize_text(text)
    return next(
        (
            topic
            for topic in CLINIC_TOPICS
            if any(_mentions(normalized, keyword) for keyword in topic.keywords)
        ),
        None,
    )


#: Insurances the clinic treats alike: a first visit with an integral diagnosis.
SPECIAL_INSURANCE_NAMES = ("osde", "medife", "william hope")
_SPECIAL_INSURANCE_DISPLAY_NAMES = {
    "osde": "OSDE",
    "medife": "Medifé",
    "william hope": "William Hope",
}

SPECIAL_INSURANCE_TEXT = (
    "Si tenés {name}, lo que te podemos ofrecer es que agendes una primera visita para "
    "poder tener un diagnóstico integral y personalizado por parte de un profesional. "
    "Esto lo cubre {name}. De necesitar algún tratamiento adicional te van a derivar de "
    "forma correspondiente al especialista indicado."
)


def match_special_insurance(text: str) -> str | None:
    """Display name (OSDE / Medifé / William Hope) when the text names one, else None."""
    normalized = normalize_text(text)
    for name in SPECIAL_INSURANCE_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", normalized):
            return _SPECIAL_INSURANCE_DISPLAY_NAMES[name]
    return None


def special_insurance_message(display_name: str) -> str:
    return SPECIAL_INSURANCE_TEXT.format(name=display_name)
