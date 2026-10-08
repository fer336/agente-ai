import pytest

from app.application.reminders.sent_message_text import render_reminder_text
from app.domain.repositories.gateways import TemplateMessage, TemplateQuickReplyButton


def template(params, *buttons):
    return TemplateMessage(
        "any-name",
        "es_AR",
        params,
        tuple(TemplateQuickReplyButton(index, payload) for index, payload in buttons),
    )


def test_day_before_text_names_the_appointment_and_asks_for_confirmation():
    text = render_reminder_text(
        template(
            ("Sofía", "jueves 8 de octubre", "10:30"),
            (0, "REMINDER_CONFIRM:apt-1"),
        )
    )

    assert "Sofía" in text
    assert "jueves 8 de octubre" in text
    assert "10:30" in text
    assert "Confirmar turno" in text
    assert "Reprogramar" not in text


def test_unconfirmed_same_day_text_offers_confirmation_and_rescheduling():
    text = render_reminder_text(
        template(
            ("Sofía", "jueves 8 de octubre", "10:30"),
            (0, "REMINDER_CONFIRM:apt-1"),
            (1, "REMINDER_RESCHEDULE:apt-1"),
        )
    )

    assert "todavía no confirmaste" in text
    assert "jueves 8 de octubre" in text
    assert "10:30" in text
    assert "Confirmar turno" in text
    assert "Reprogramar turno" in text


def test_location_text_mentions_the_time_and_the_location_button():
    text = render_reminder_text(template(("Sofía", "10:30"), (0, "REMINDER_LOCATION:apt-1")))

    assert "Sofía" in text
    assert "10:30" in text
    assert "ubicación" in text


def test_review_text_thanks_the_patient_by_name():
    text = render_reminder_text(template(("Sofía",), (1, "REMINDER_REVIEW_OPTOUT")))

    assert "Sofía" in text
    assert "reseña" in text


@pytest.mark.parametrize("params", [(), ("solo",)])
def test_an_unknown_shape_falls_back_to_a_generic_text(params):
    assert render_reminder_text(template(params)) == "Te enviamos un recordatorio de tu turno."
