"""Readable Spanish equivalent of a sent reminder template.

The approved template body lives at Meta/YCloud and is not stored locally, so the
conversation history keeps this equivalent instead: only the dynamic values the
template carried (name, date, time) and the choices its buttons offered.
"""

from app.domain.repositories.gateways import TemplateMessage

_GENERIC_TEXT = "Te enviamos un recordatorio de tu turno."


def render_reminder_text(template: TemplateMessage) -> str:
    payloads = tuple(button.payload for button in template.quick_reply_buttons)
    params = template.body_parameters
    if any(payload.startswith("REMINDER_RESCHEDULE:") for payload in payloads) and len(params) == 3:
        name, date, time = params
        return (
            f"¡Hola, {name}! Vimos que todavía no confirmaste tu turno para el {date} a las "
            f"{time}. Podés confirmarlo (botón «Confirmar turno») o pedir que lo "
            "reprogramemos (botón «Reprogramar turno»)."
        )
    if any(payload.startswith("REMINDER_CONFIRM:") for payload in payloads) and len(params) == 3:
        name, date, time = params
        return (
            f"¡Hola, {name}! Somos de Smiling Pilar. Tenemos reservado tu turno para el {date} "
            f"a las {time}. ¿Contamos con vos? Tocá el botón «Confirmar turno» para confirmar "
            "tu asistencia."
        )
    if any(payload.startswith("REMINDER_LOCATION:") for payload in payloads) and len(params) == 2:
        name, time = params
        return (
            f"¡Hola, {name}! Hoy tenés turno a las {time}. Tocá el botón para ver la ubicación "
            "de la clínica."
        )
    if "REMINDER_REVIEW_OPTOUT" in payloads and len(params) == 1:
        return (
            f"¡Hola, {params[0]}! Gracias por tu visita. Te dejamos el enlace para que cuentes "
            "tu experiencia en una reseña."
        )
    return _GENERIC_TEXT
