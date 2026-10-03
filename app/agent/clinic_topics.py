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
#: `collected_data` key: the option ("1", "2" or "3") the patient chose on a topic's option
#: buttons. Set by the router, kept through the booking, shown in the confirmation message
#: and dropped when the booking ends or the flow resets. Never sent to Dentalink.
ALIGNER_OPTION_KEY = "aligner_option"
#: `collected_data` key: the id of the frequent topic the patient chose to book from. Carried
#: exactly like `ALIGNER_OPTION_KEY` until the booking is confirmed, where it becomes the
#: appointment comment (see `booking_comment`). Dropped when the booking ends or the flow
#: resets.
BOOKING_TOPIC_KEY = "booking_topic"


@dataclass(frozen=True)
class ClinicTopic:
    id: str
    #: WhatsApp list row title (24 characters at most).
    title: str
    #: Accent-folded lowercase words/phrases (see `normalize_text`) that name the topic.
    keywords: tuple[str, ...]
    text: str
    #: Broader phrases that only name the topic when no topic matched a regular keyword, so
    #: "brackets sin obra social" stays brackets and "limpieza sin obra social" stays limpieza.
    weak_keywords: tuple[str, ...] = ()
    #: Dentalink specialty a booking of this topic goes to, skipping the specialty list. The
    #: clinic books every frequent topic on "General".
    book_specialty: str | None = None
    #: File under `app/static/public/` sent with the answer (needs a configured image URL).
    image_filename: str | None = None
    #: Option buttons (`Opción n`) that replace the usual Agendar / Menú / Administración
    #: trio, since WhatsApp allows 3 reply buttons. Each starts the booking.
    options: tuple[str, ...] = ()
    #: Name administration reads in the Dentalink appointment comment.
    comment_label: str | None = None

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

# The prices are in the image (`alineadores-opciones.jpg`), never in the text.
_ALINEADORES_TEXT = (
    "😁 *Alineadores Smilesecret*\n\n"
    "Estas son las opciones de pago. Elegí la que más te convenga y seguimos con tu "
    "turno.\n\n"
    'Si no ves la imagen o preferís otra cosa, escribí "administración" (o "menú") y te '
    "ayudamos."
)

CLINIC_TOPICS: tuple[ClinicTopic, ...] = (
    ClinicTopic(
        id="blanqueamiento",
        title="Blanqueamiento dental",
        keywords=(
            "blanqueamiento",
            "blanquear",
            "blanqueo",
            "blanquearme",
            # "aclarar"/"aclarame" alone are everyday verbs ("aclarame una duda"): only the
            # teeth-lightening phrasings name the topic.
            "aclarar los dientes",
            "aclararme los dientes",
            "aclarame los dientes",
            "aclarar dientes",
            "aclararme dientes",
            "dientes blancos",
            "dientes mas blancos",
        ),
        text=_BLANQUEAMIENTO_TEXT,
        book_specialty="General",
        comment_label="Blanqueamiento",
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
        weak_keywords=(
            "pacientes particulares",
            "atienden particulares",
            "atienden pacientes particulares",
            "atienden particular",
            "sin obra social",
        ),
        text=_CONSULTA_PARTICULAR_TEXT,
        comment_label="Consulta Particular",
        book_specialty="General",
    ),
    ClinicTopic(
        id="limpieza_particular",
        title="Limpieza particular",
        keywords=("limpieza", "profilaxis"),
        text=_LIMPIEZA_PARTICULAR_TEXT,
        book_specialty="General",
        comment_label="Limpieza Particular",
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
        book_specialty="General",
        comment_label="Brackets por obra social",
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
        book_specialty="General",
        comment_label="Alineadores",
        image_filename="alineadores-opciones.jpg",
        options=("1", "2", "3"),
    ),
)


def topic_by_id(topic_id: object) -> ClinicTopic | None:
    return next((topic for topic in CLINIC_TOPICS if topic.id == topic_id), None)


def booking_comment(topic_id: str | None, option: str | None = None) -> str | None:
    """The appointment comment for a booking that started from a frequent topic.

    `Consulta frecuente: <label>`, plus ` - Opción <n>` for a topic with options (the
    alineadores). None when the topic is unknown, so the booking carries no comment."""
    topic = topic_by_id(topic_id)
    if topic is None or topic.comment_label is None:
        return None
    text = f"Consulta frecuente: {topic.comment_label}"
    if option is not None and option in topic.options:
        text += f" - Opción {option}"
    return text


def _mentions(normalized_text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}", normalized_text) is not None


def match_clinic_topic(text: str) -> ClinicTopic | None:
    """The first topic whose keyword the text names (accent- and case-insensitive).

    Weak keywords are only consulted when no topic matched a regular one."""
    normalized = normalize_text(text)
    for topic in CLINIC_TOPICS:
        if any(_mentions(normalized, keyword) for keyword in topic.keywords):
            return topic
    for topic in CLINIC_TOPICS:
        if any(_mentions(normalized, keyword) for keyword in topic.weak_keywords):
            return topic
    return None


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


_FIRST_VISIT_TERMS = ("primera visita", "primera consulta", "primer turno", "primera cita")
_COVERAGE_TERMS = ("cubre", "cubierta", "cubierto", "cobertura", "incluida")
_REFERRAL_TERMS = ("derivan", "derivar", "derivacion", "especialista")
#: Words that would state a figure or condition the clinic never confirmed (PRD §20).
_FORBIDDEN_TERMS = (
    "copago",
    "porcentaje",
    "reintegro",
    "descuento",
    "gratis",
    "sin cargo",
    "bonificad",
    "cuota",
)
_FORBIDDEN_CHARACTERS = re.compile(r"[%$\d]")


def special_insurance_text_is_valid(text: str, name: str) -> bool:
    """Deterministic fact check for an LLM-written special-insurance answer.

    The answer must keep the clinic's four facts (first visit, integral/personalized
    diagnosis by a professional, covered by the insurance, referral to a specialist) and
    must never state a percentage, copay, price or condition.
    """
    if _FORBIDDEN_CHARACTERS.search(text):
        return False
    normalized = normalize_text(text)
    if any(_mentions(normalized, term) for term in _FORBIDDEN_TERMS):
        return False
    folded_name = normalize_text(name)
    has_diagnosis = _mentions(normalized, "diagnostico") and (
        _mentions(normalized, "integral") or _mentions(normalized, "personalizado")
    )
    return (
        _mentions(normalized, folded_name)
        and any(_mentions(normalized, term) for term in _FIRST_VISIT_TERMS)
        and has_diagnosis
        and _mentions(normalized, "profesional")
        and any(_mentions(normalized, term) for term in _COVERAGE_TERMS)
        and any(_mentions(normalized, term) for term in _REFERRAL_TERMS)
    )
