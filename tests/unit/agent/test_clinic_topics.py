import pytest

from app.agent.clinic_topics import (
    CLINIC_TOPICS,
    SPECIAL_INSURANCE_NAMES,
    SPECIAL_INSURANCE_TEXT,
    ClinicTopic,
    match_clinic_topic,
    match_special_insurance,
    special_insurance_message,
    topic_by_id,
)
from app.agent.handoff_offer import normalize_text
from app.domain.value_objects.menu_payloads import (
    FAQ_TOPIC_ALINEADORES_PAYLOAD,
    FAQ_TOPIC_BLANQUEAMIENTO_PAYLOAD,
    FAQ_TOPIC_BRACKETS_PAYLOAD,
    FAQ_TOPIC_CONSULTA_PAYLOAD,
    FAQ_TOPIC_LIMPIEZA_PAYLOAD,
    FAQ_TOPIC_PAYLOAD_PREFIX,
)

_EXPECTED_IDS = (
    "blanqueamiento",
    "consulta_particular",
    "limpieza_particular",
    "brackets_obra_social",
    "alineadores",
)


def test_the_five_frequent_topics_are_defined_in_order():
    assert tuple(topic.id for topic in CLINIC_TOPICS) == _EXPECTED_IDS
    assert all(isinstance(topic, ClinicTopic) for topic in CLINIC_TOPICS)


def test_titles_fit_a_whatsapp_list_row():
    assert [topic.title for topic in CLINIC_TOPICS] == [
        "Blanqueamiento dental",
        "Consulta particular",
        "Limpieza particular",
        "Brackets por obra social",
        "Alineadores",
    ]
    assert all(len(topic.title) <= 24 for topic in CLINIC_TOPICS)


def test_keywords_are_accent_folded_lowercase():
    for topic in CLINIC_TOPICS:
        assert topic.keywords
        assert all(keyword == normalize_text(keyword) for keyword in topic.keywords)


def test_topic_payloads_follow_the_prefix_and_the_domain_constants():
    assert [topic.payload for topic in CLINIC_TOPICS] == [
        FAQ_TOPIC_BLANQUEAMIENTO_PAYLOAD,
        FAQ_TOPIC_CONSULTA_PAYLOAD,
        FAQ_TOPIC_LIMPIEZA_PAYLOAD,
        FAQ_TOPIC_BRACKETS_PAYLOAD,
        FAQ_TOPIC_ALINEADORES_PAYLOAD,
    ]
    assert all(topic.payload.startswith(FAQ_TOPIC_PAYLOAD_PREFIX) for topic in CLINIC_TOPICS)


def test_blanqueamiento_text_carries_the_clinic_figures():
    text = topic_by_id("blanqueamiento").text  # type: ignore[union-attr]
    assert "$450.000" in text
    assert "$360.000" in text
    assert "20%" in text
    assert "45 minutos" in text


def test_consulta_particular_text_carries_the_price():
    text = topic_by_id("consulta_particular").text  # type: ignore[union-attr]
    assert "$60.000" in text


def test_limpieza_and_brackets_texts_invent_no_figures():
    for topic_id in ("limpieza_particular", "brackets_obra_social"):
        text = topic_by_id(topic_id).text  # type: ignore[union-attr]
        assert "$" not in text
        assert "administración" in text


def test_alineadores_text_lists_the_three_usd_options():
    text = topic_by_id("alineadores").text  # type: ignore[union-attr]
    for figure in ("USD 2.500", "USD 1.000", "USD 600", "USD 1.100", "USD 300"):
        assert figure in text
    assert "Smilesecret" in text


def test_topic_by_id_returns_none_for_an_unknown_id():
    assert topic_by_id("nope") is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Hola, cuánto sale el blanqueamiento?", "blanqueamiento"),
        ("BLANQUEAMIENTO", "blanqueamiento"),
        ("quiero info de la consulta particular", "consulta_particular"),
        ("Hacen limpieza?", "limpieza_particular"),
        ("tienen brackets con obra social?", "brackets_obra_social"),
        ("precio de los alineadores", "alineadores"),
        ("me interesa smilesecret", "alineadores"),
    ],
)
def test_match_clinic_topic_finds_the_topic(message, expected):
    topic = match_clinic_topic(message)

    assert topic is not None
    assert topic.id == expected


@pytest.mark.parametrize("message", ["quiero un turno", "OSDE", "hola", "", "Juan Pérez 12345678"])
def test_match_clinic_topic_returns_none_otherwise(message):
    assert match_clinic_topic(message) is None


def test_special_insurance_names_are_the_three_clinic_cases():
    assert SPECIAL_INSURANCE_NAMES == ("osde", "medife", "william hope")


@pytest.mark.parametrize(
    ("message", "display"),
    [
        ("tengo OSDE", "OSDE"),
        ("atienden Medifé?", "Medifé"),
        ("soy de medife", "Medifé"),
        ("William Hope", "William Hope"),
    ],
)
def test_match_special_insurance_returns_the_display_name(message, display):
    assert match_special_insurance(message) == display


def test_match_special_insurance_ignores_other_text():
    assert match_special_insurance("tengo Swiss Medical") is None
    assert match_special_insurance("posdelta") is None


def test_special_insurance_message_formats_the_name_into_the_template():
    assert "{name}" in SPECIAL_INSURANCE_TEXT
    text = special_insurance_message("Medifé")
    assert text.startswith("Si tenés Medifé, lo que te podemos ofrecer")
    assert "Esto lo cubre Medifé." in text
    assert "{name}" not in text


@pytest.mark.parametrize(
    ("message", "topic_id"),
    [
        ("cuánto sale el blanqueo", "blanqueamiento"),
        ("hacen blanqueo dental?", "blanqueamiento"),
        ("cuánto sale invisalign", "alineadores"),
        ("tienen ortodoncia invisible", "alineadores"),
        ("cuánto cuesta una consulta particular", "consulta_particular"),
        ("cuánto sale la consulta sin obra social", "consulta_particular"),
        ("cuánto cuesta la consulta", "consulta_particular"),
        ("hacen ortodoncia con obra social", "brackets_obra_social"),
        ("ponen frenos con obra social", "brackets_obra_social"),
        ("limpiezas dentales cuánto salen", "limpieza_particular"),
    ],
)
def test_common_free_text_phrasings_reach_their_topic(message, topic_id):
    topic = match_clinic_topic(message)

    assert topic is not None
    assert topic.id == topic_id


@pytest.mark.parametrize(
    "message",
    ["tengo una consulta", "quiero hacer una consulta sobre un turno", "hola buen día"],
)
def test_a_generic_word_alone_is_not_a_topic(message):
    assert match_clinic_topic(message) is None
