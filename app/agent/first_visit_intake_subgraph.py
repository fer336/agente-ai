"""Deterministic first-visit intake flow, isolated from appointment selection.

The appointment node adapts its conversational state into this graph.  The
subgraph never persists data and never calls the LLM: the adapter extracts
whatever the patient wrote (see ``first_visit_intake_extraction``) and hands it
in as ``extracted_details``; the graph validates and merges it, decides which
fields are still missing and exposes ``ready_to_persist`` only after the
patient has explicitly confirmed a complete review.

Every "ask" turn returns ``ask_fields`` (the missing fields, in fixed order)
plus a static ``response_text`` the adapter can use verbatim as the fallback
when its LLM-built wording is unavailable.
"""

import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.domain.value_objects.interactive_button import InteractiveButton

#: Legacy "No, ya soy paciente" tap.  The first-visit question is now answered
#: as free text, but a stale button from an older message (and programmatic
#: callers that skip the intake) still resolve to the existing-patient path.
FIRST_VISIT_EXISTING_PATIENT_PAYLOAD = "FIRST_VISIT_EXISTING_PATIENT"
FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD = "FIRST_VISIT_REVIEW_CONFIRM"
FIRST_VISIT_REVIEW_MODIFY_PAYLOAD = "FIRST_VISIT_REVIEW_MODIFY"
FIRST_VISIT_REVIEW_CANCEL_PAYLOAD = "FIRST_VISIT_REVIEW_CANCEL"
MENU_MAIN_PAYLOAD = "MENU_MAIN"
MENU_ADMIN_PAYLOAD = "MENU_ADMIN"

#: Fixed collection (and listing) order.
INTAKE_FIELDS = ("full_name", "dni", "email", "obra_social", "plan")
INTAKE_FIELD_LABELS = {
    "full_name": "Nombre completo",
    "dni": "DNI",
    "email": "Correo electrónico",
    "obra_social": "Obra social",
    "plan": "Plan",
}
_FIELD_PROMPTS = {
    "full_name": "Por favor, indicame tu nombre y apellido completos.",
    "dni": "Indicame tu DNI, solo números.",
    "email": "Indicame tu correo electrónico.",
    "obra_social": "Indicame tu obra social.",
    "plan": "Indicame tu plan.",
}
_EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")

#: Static intros, also the fallback wording when the LLM-built one fails.
FIRST_ASK_INTRO = "¿Es tu primera vez en la clínica? Para dejarte registrado necesito estos datos:"
RETRY_ASK_INTRO = "Gracias. Todavía me faltan estos datos:"


class FirstVisitIntakeState(TypedDict, total=False):
    """Narrow state exchanged with the appointment-node adapter."""

    user_message: str
    button_payload: str | None
    stage: Literal["offer", "collect", "review", "choose_field", "cancelled"]
    details: dict[str, str]
    #: Fields the adapter extracted from this turn's free-text reply.
    extracted_details: dict[str, str]
    #: The first-visit yes/no, when the reply stated it.
    first_visit_answer: Literal["new", "existing"] | None
    editing_field: str | None
    response_text: str
    response_buttons: list[InteractiveButton] | None
    #: Missing fields listed by this turn's ask, in fixed order; unset otherwise.
    ask_fields: list[str] | None
    ask_kind: Literal["first", "retry"] | None
    next_action: Literal["none", "specialties", "persist", "main_menu", "handoff"]
    ready_to_persist: bool


def format_field_bullets(fields: list[str]) -> str:
    """Render the fields as "- " bullets, one per line, in the given order."""
    return "\n".join(f"- {INTAKE_FIELD_LABELS[field]}" for field in fields)


def _buttons(*buttons: tuple[str, str]) -> list[InteractiveButton]:
    return [InteractiveButton(id=identifier, title=title) for identifier, title in buttons]


def _normalise(field: str, value: str) -> str:
    value = value.strip()
    if field == "dni":
        return re.sub(r"[.\s]", "", value)
    return value


def _valid(field: str, value: str) -> bool:
    if field == "full_name":
        return len(value.split()) >= 2
    if field == "dni":
        return value.isdigit() and len(value) in (7, 8)
    if field == "email":
        return _EMAIL_PATTERN.fullmatch(value) is not None
    return bool(value.strip())


def _clean_details(details: dict[str, str]) -> dict[str, str]:
    """Keep only known, valid, normalised values."""
    cleaned: dict[str, str] = {}
    for field in INTAKE_FIELDS:
        value = _normalise(field, str(details.get(field, "")))
        if value and _valid(field, value):
            cleaned[field] = value
    return cleaned


def missing_intake_fields(details: dict[str, str]) -> list[str]:
    """Fields with no value yet, in the fixed intake order."""
    return [field for field in INTAKE_FIELDS if not details.get(field, "").strip()]


def _ask(
    details: dict[str, str],
    missing: list[str],
    kind: Literal["first", "retry"],
    *,
    editing_field: str | None = None,
) -> dict[str, object]:
    intro = FIRST_ASK_INTRO if kind == "first" else RETRY_ASK_INTRO
    return {
        "stage": "collect",
        "editing_field": editing_field,
        "details": details,
        "ask_fields": missing,
        "ask_kind": kind,
        "response_text": f"{intro}\n\n{format_field_bullets(missing)}",
        "response_buttons": None,
        "next_action": "none",
        "ready_to_persist": False,
    }


def _cancelled() -> dict[str, object]:
    return {
        "stage": "cancelled",
        "response_text": "¿Qué preferís hacer?",
        "response_buttons": _buttons(
            (MENU_MAIN_PAYLOAD, "Menú principal"),
            (MENU_ADMIN_PAYLOAD, "Administración"),
        ),
        "next_action": "none",
        "ready_to_persist": False,
    }


_REVIEW_BUTTONS = (
    (FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD, "✅ Confirmar"),
    (FIRST_VISIT_REVIEW_MODIFY_PAYLOAD, "✏️ Modificar"),
    (FIRST_VISIT_REVIEW_CANCEL_PAYLOAD, "❌ Cancelar"),
)


def _review_turn(details: dict[str, str]) -> dict[str, object]:
    return {
        "stage": "review",
        "editing_field": None,
        "details": details,
        "ask_fields": None,
        "response_text": _review(details),
        "response_buttons": _buttons(*_REVIEW_BUTTONS),
        "next_action": "none",
        "ready_to_persist": False,
    }


def _review(details: dict[str, str]) -> str:
    return (
        "Por favor, confirmá tus datos:\n\n"
        f"Nombre y apellido: {details['full_name']}\n"
        f"DNI: {details['dni']}\n"
        f"Correo electrónico: {details['email']}\n"
        f"Obra social: {details['obra_social']}\n"
        f"Plan: {details['plan']}"
    )


def _normalise_field_choice(text: str) -> str | None:
    normalized = text.strip().casefold()
    choices = {
        "nombre": "full_name",
        "nombre y apellido": "full_name",
        "nombre completo": "full_name",
        "dni": "dni",
        "correo": "email",
        "correo electrónico": "email",
        "correo electronico": "email",
        "email": "email",
        "mail": "email",
        "obra social": "obra_social",
        "plan": "plan",
    }
    return choices.get(normalized)


def build_first_visit_intake_graph() -> Any:
    """Build the pure first-visit state graph.

    Each invocation consumes one user interaction and ends.  Its persisted
    ``stage``/``details`` projection is supplied again by the parent graph on
    the next turn, which makes missing-field and correction loops deterministic.
    """

    def advance(state: FirstVisitIntakeState) -> dict[str, object]:
        stage = state.get("stage", "offer")
        payload = state.get("button_payload")
        # Legacy checkpoints (full_name/dni/phone/coverage) are migrated on
        # entry: unknown keys are dropped (so obra social and plan are asked
        # again rather than guessed from the merged coverage string) and an
        # editing field that no longer exists is cleared.
        details = _clean_details(state.get("details", {}))
        editing_field = state.get("editing_field")
        if editing_field not in INTAKE_FIELDS:
            editing_field = None

        if stage == "cancelled":
            return _cancelled()

        if stage in ("review", "choose_field"):
            # Never review, edit or persist an incomplete record.
            missing = missing_intake_fields(details)
            if missing:
                return _ask(details, missing, "retry")

        if stage == "choose_field":
            field = _normalise_field_choice(state.get("user_message", ""))
            if field is None:
                return {
                    "stage": "choose_field",
                    "response_text": (
                        "Indicame qué querés modificar: nombre y apellido, DNI, correo "
                        "electrónico, obra social o plan."
                    ),
                    "response_buttons": None,
                    "next_action": "none",
                    "ready_to_persist": False,
                }
            return {
                "stage": "collect",
                "editing_field": field,
                "details": details,
                "response_text": _FIELD_PROMPTS[field],
                "response_buttons": None,
                "next_action": "none",
                "ready_to_persist": False,
            }

        if stage == "review":
            if payload == FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD:
                return {"next_action": "persist", "ready_to_persist": True, "details": details}
            if payload == FIRST_VISIT_REVIEW_MODIFY_PAYLOAD:
                return {
                    "stage": "choose_field",
                    "response_text": "¿Qué dato querés modificar?",
                    "response_buttons": None,
                    "next_action": "none",
                    "ready_to_persist": False,
                }
            if payload == FIRST_VISIT_REVIEW_CANCEL_PAYLOAD:
                return _cancelled()
            return _review_turn(details)

        if payload == FIRST_VISIT_EXISTING_PATIENT_PAYLOAD or (
            state.get("first_visit_answer") == "existing" and not editing_field
        ):
            return {"next_action": "specialties", "ready_to_persist": False}

        if stage == "offer":
            missing = missing_intake_fields(details)
            if not missing:
                return _review_turn(details)
            return _ask(details, missing, "first")

        if editing_field:
            value = _normalise(editing_field, state.get("user_message", ""))
            if not _valid(editing_field, value):
                return _ask(details, [editing_field], "retry", editing_field=editing_field)
            details[editing_field] = value
        else:
            extracted = state.get("extracted_details", {})
            for field in INTAKE_FIELDS:
                value = _normalise(field, str(extracted.get(field, "")))
                if value and _valid(field, value):
                    details[field] = value
        missing = missing_intake_fields(details)
        if missing:
            return _ask(details, missing, "retry")
        return _review_turn(details)

    graph = StateGraph(FirstVisitIntakeState)
    graph.add_node("advance", advance)
    graph.add_edge(START, "advance")
    graph.add_edge("advance", END)
    return graph.compile()
