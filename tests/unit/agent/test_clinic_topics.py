import pytest

from app.agent.clinic_topics import (
    CLINIC_TOPICS,
    SPECIAL_INSURANCE_NAMES,
    SPECIAL_INSURANCE_TEXT,
    ClinicTopic,
    match_clinic_topic,
    match_special_insurance,
    special_insurance_message,
    special_insurance_text_is_valid,
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
        assert all(
            keyword == normalize_text(keyword)
            for keyword in (*topic.keywords, *topic.weak_keywords)
        )


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
    assert "45 minutos" in text


def test_blanqueamiento_text_does_not_advertise_a_promo():
    text = topic_by_id("blanqueamiento").text  # type: ignore[union-attr]
    assert "$360.000" not in text
    assert "20%" not in text


def test_consulta_particular_text_carries_the_price():
    text = topic_by_id("consulta_particular").text  # type: ignore[union-attr]
    assert "$60.000" in text


def test_topics_without_a_confirmed_price_state_no_figures():
    for topic_id in ("limpieza_particular", "brackets_obra_social", "alineadores"):
        text = topic_by_id(topic_id).text  # type: ignore[union-attr]
        assert "$" not in text
        assert "USD" not in text
        assert "administración" in text


def test_alineadores_caption_has_no_prices_and_fits_a_whatsapp_caption():
    text = topic_by_id("alineadores").text  # type: ignore[union-attr]
    assert not any(char.isdigit() for char in text)
    assert len(text) <= 1024


def test_alineadores_text_names_the_brand_without_prices():
    text = topic_by_id("alineadores").text  # type: ignore[union-attr]
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


@pytest.mark.parametrize(
    ("message", "topic_id"),
    [
        ("¿Cuánto me sale aclararme los dientes?", "blanqueamiento"),
        ("cuanto sale aclarar los dientes", "blanqueamiento"),
        ("me quiero aclarar los dientes, cuánto cuesta?", "blanqueamiento"),
        ("aclarame los dientes, cuanto sale", "blanqueamiento"),
        ("quiero tener dientes blancos", "blanqueamiento"),
        ("quiero los dientes más blancos", "blanqueamiento"),
        ("me quiero blanquearme los dientes", "blanqueamiento"),
        ("¿Atienden pacientes particulares?", "consulta_particular"),
        ("atienden particulares?", "consulta_particular"),
        ("atienden pacientes particulares", "consulta_particular"),
        ("¿atienden particular?", "consulta_particular"),
        ("atienden sin obra social?", "consulta_particular"),
        ("me atienden sin obra social", "consulta_particular"),
        ("pacientes particulares tienen turnos?", "consulta_particular"),
        # An explicit topic keeps priority over the broader consulta particular phrasings.
        ("limpieza particular", "limpieza_particular"),
        ("limpieza sin obra social", "limpieza_particular"),
        ("brackets sin obra social", "brackets_obra_social"),
        ("ortodoncia con obra social", "brackets_obra_social"),
        ("alineadores para pacientes particulares", "alineadores"),
        ("blanqueamiento sin obra social", "blanqueamiento"),
    ],
)
def test_audit_phrasings_reach_their_topic(message, topic_id):
    topic = match_clinic_topic(message)

    assert topic is not None
    assert topic.id == topic_id


@pytest.mark.parametrize(
    "message",
    [
        "tengo osde",
        "atienden osde?",
        "atienden medife?",
        "tengo obra social",
        "consulta",
        "quiero hacer una consulta",
        "podés aclararme una duda?",
        "aclarame el horario por favor",
        "necesito aclarar un tema del turno",
        "tengo dientes chuecos",
        "atienden los sábados?",
    ],
)
def test_the_new_phrasings_do_not_steal_other_messages(message):
    assert match_clinic_topic(message) is None


_GOOD_SPECIAL_TEXTS = [
    special_insurance_message("OSDE"),
    "Con OSDE podés sacar una primera consulta, donde un profesional te hace un diagnóstico "
    "integral y personalizado. OSDE la cubre, y si necesitás algún tratamiento más te derivan "
    "al especialista que corresponda.",
    "¡Claro! Con Medifé te esperamos para una primera visita: un profesional te va a hacer un "
    "diagnóstico personalizado e integral, que está cubierto por Medifé. Si hace falta otro "
    "tratamiento, te derivamos con el especialista indicado.",
    "William Hope cubre tu primer turno con nosotros: es una primera cita con diagnóstico "
    "integral y personalizado de un profesional. Después, si necesitás algo más, te derivan al "
    "especialista.",
]


@pytest.mark.parametrize("text", _GOOD_SPECIAL_TEXTS)
def test_special_insurance_text_is_valid_accepts_faithful_paraphrases(text):
    name = next(n for n in ("OSDE", "Medifé", "William Hope") if n in text)
    assert special_insurance_text_is_valid(text, name) is True


_VALID = _GOOD_SPECIAL_TEXTS[1]


@pytest.mark.parametrize(
    ("text", "name"),
    [
        (_VALID.replace("OSDE", "Galeno"), "OSDE"),  # name missing
        (_VALID.replace("primera consulta", "consulta"), "OSDE"),  # no first visit
        (_VALID.replace("integral y personalizado", "completo"), "OSDE"),  # no diagnosis kind
        (_VALID.replace("diagnóstico", "estudio"), "OSDE"),  # no diagnosis
        (_VALID.replace("un profesional", "alguien"), "OSDE"),  # no professional
        (_VALID.replace("la cubre", "la tiene"), "OSDE"),  # no coverage
        (
            _VALID.replace("te derivan al especialista que corresponda", "te avisamos"),
            "OSDE",
        ),  # no referral
        (_VALID + " Cubre el 100%.", "OSDE"),  # percent sign
        (_VALID + " Cuesta $5.000.", "OSDE"),  # currency sign
        (_VALID + " Tenés 2 turnos.", "OSDE"),  # digit
        (_VALID + " Sin copago.", "OSDE"),
        (_VALID + " Con reintegro.", "OSDE"),
        (_VALID + " Tiene descuento.", "OSDE"),
        (_VALID + " Es gratis.", "OSDE"),
        (_VALID + " Va sin cargo.", "OSDE"),
        (_VALID + " Queda bonificada.", "OSDE"),
        (_VALID + " Pagás una cuota.", "OSDE"),
        (_VALID + " Pagás el porcentaje restante.", "OSDE"),
    ],
)
def test_special_insurance_text_is_valid_rejects_missing_facts_and_invented_figures(text, name):
    assert special_insurance_text_is_valid(text, name) is False


def test_alineadores_caption_tells_what_to_do_when_the_image_is_not_visible():
    # The prices live only in the image: if WhatsApp cannot show it, the patient must still
    # have a way to get them (without the text ever stating a figure).
    text = topic_by_id("alineadores").text  # type: ignore[union-attr]
    assert "no ves la imagen" in text.lower()
    assert "administración" in text
    assert "$" not in text
