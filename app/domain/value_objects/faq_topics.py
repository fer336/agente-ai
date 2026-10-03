"""Ids of the clinic's frequent topics, as the LLM provider needs them.

The answers live in `app.agent.clinic_topics` (a unit test keeps both id lists equal); the
infrastructure layer only needs the ids to document and validate the understand JSON.
"""

#: One line per topic id, in the order of the topic list the patient sees.
FAQ_TOPIC_DESCRIPTIONS: dict[str, str] = {
    "blanqueamiento": "blanqueamiento dental, aclarar los dientes, precio y cómo funciona",
    "consulta_particular": "consulta particular (sin obra social), su precio y si atienden "
    "pacientes particulares",
    "limpieza_particular": "limpieza dental particular",
    "brackets_obra_social": "brackets / ortodoncia por obra social",
    "alineadores": "alineadores invisibles (Smilesecret, Invisalign)",
}
FAQ_TOPIC_IDS: tuple[str, ...] = tuple(FAQ_TOPIC_DESCRIPTIONS)


def valid_faq_topic_id(value: object) -> str | None:
    """The id when `value` is a string naming a known frequent topic, else None."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped in FAQ_TOPIC_IDS else None
