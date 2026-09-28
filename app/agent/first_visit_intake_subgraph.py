"""Deterministic first-visit intake flow, isolated from appointment selection.

The appointment node adapts its conversational state into this graph.  The
subgraph never persists data: it only exposes ``ready_to_persist`` after the
patient has explicitly confirmed a complete review.
"""

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.domain.value_objects.interactive_button import InteractiveButton

FIRST_VISIT_CONFIRM_PAYLOAD = "FIRST_VISIT_CONFIRM"
FIRST_VISIT_EXISTING_PATIENT_PAYLOAD = "FIRST_VISIT_EXISTING_PATIENT"
FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD = "FIRST_VISIT_REVIEW_CONFIRM"
FIRST_VISIT_REVIEW_MODIFY_PAYLOAD = "FIRST_VISIT_REVIEW_MODIFY"
FIRST_VISIT_REVIEW_CANCEL_PAYLOAD = "FIRST_VISIT_REVIEW_CANCEL"
MENU_MAIN_PAYLOAD = "MENU_MAIN"
MENU_ADMIN_PAYLOAD = "MENU_ADMIN"

_FIELDS = ("full_name", "dni", "phone", "coverage")
_FIELD_PROMPTS = {
    "full_name": "Por favor, indicame tu nombre y apellido completos.",
    "dni": "Ahora necesito tu DNI, solo números.",
    "phone": "Indicame tu número de teléfono con código de área.",
    "coverage": "Indicame tu obra social y plan, por ejemplo: OSDE 210.",
}


class FirstVisitIntakeState(TypedDict, total=False):
    """Narrow state exchanged with the appointment-node adapter."""

    user_message: str
    button_payload: str | None
    stage: Literal["offer", "collect", "review", "choose_field", "cancelled"]
    details: dict[str, str]
    editing_field: str | None
    response_text: str
    response_buttons: list[InteractiveButton] | None
    next_action: Literal["none", "specialties", "persist", "main_menu", "handoff"]
    ready_to_persist: bool


def _buttons(*buttons: tuple[str, str]) -> list[InteractiveButton]:
    return [InteractiveButton(id=identifier, title=title) for identifier, title in buttons]


def _missing_field(details: dict[str, str]) -> str | None:
    for field in _FIELDS:
        if not details.get(field, "").strip():
            return field
    return None


def _valid(field: str, value: str) -> bool:
    if field == "full_name":
        return len(value.split()) >= 2
    if field == "dni":
        return value.isdigit() and len(value) in (7, 8)
    if field == "phone":
        digits = "".join(character for character in value if character.isdigit())
        return len(digits) >= 10
    return bool(value.strip())


def _review(details: dict[str, str]) -> str:
    return (
        "Por favor, confirmá tus datos:\n\n"
        f"Nombre y apellido: {details['full_name']}\n"
        f"DNI: {details['dni']}\n"
        f"Teléfono: {details['phone']}\n"
        f"Obra social y plan: {details['coverage']}"
    )


def _normalise_field_choice(text: str) -> str | None:
    normalized = text.strip().casefold()
    choices = {
        "nombre": "full_name",
        "nombre y apellido": "full_name",
        "dni": "dni",
        "teléfono": "phone",
        "telefono": "phone",
        "obra social": "coverage",
        "obra social y plan": "coverage",
        "plan": "coverage",
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
        details = dict(state.get("details", {}))

        if stage == "offer":
            if payload == FIRST_VISIT_EXISTING_PATIENT_PAYLOAD:
                return {"next_action": "specialties", "ready_to_persist": False}
            if payload != FIRST_VISIT_CONFIRM_PAYLOAD:
                return {
                    "stage": "offer",
                    "response_text": (
                        "Hola, soy el asistente de Smiling Pilar. Antes de ayudarte con tu turno, "
                        "¿es tu primera vez en la clínica?"
                    ),
                    "response_buttons": _buttons(
                        (FIRST_VISIT_CONFIRM_PAYLOAD, "Sí, primera vez"),
                        (FIRST_VISIT_EXISTING_PATIENT_PAYLOAD, "No, ya soy paciente"),
                    ),
                    "next_action": "none",
                    "ready_to_persist": False,
                }
            return {
                "stage": "collect",
                "response_text": _FIELD_PROMPTS["full_name"],
                "response_buttons": None,
                "details": details,
                "next_action": "none",
                "ready_to_persist": False,
            }

        if stage == "cancelled":
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

        if stage == "choose_field":
            field = _normalise_field_choice(state.get("user_message", ""))
            if field is None:
                return {
                    "stage": "choose_field",
                    "response_text": (
                        "Indicame qué querés modificar: nombre y apellido, DNI, teléfono, "
                        "u obra social y plan."
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
            return {
                "stage": "review",
                "response_text": _review(details),
                "response_buttons": _buttons(
                    (FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD, "✅ Confirmar"),
                    (FIRST_VISIT_REVIEW_MODIFY_PAYLOAD, "✏️ Modificar"),
                    (FIRST_VISIT_REVIEW_CANCEL_PAYLOAD, "❌ Cancelar"),
                ),
                "next_action": "none",
                "ready_to_persist": False,
            }

        field = state.get("editing_field") or _missing_field(details)
        assert field is not None
        value = state.get("user_message", "").strip()
        if not _valid(field, value):
            return {
                "stage": "collect",
                "editing_field": field,
                "details": details,
                "response_text": _FIELD_PROMPTS[field],
                "response_buttons": None,
                "next_action": "none",
                "ready_to_persist": False,
            }
        details[field] = value
        missing = _missing_field(details)
        if missing is not None:
            return {
                "stage": "collect",
                "editing_field": None,
                "details": details,
                "response_text": _FIELD_PROMPTS[missing],
                "response_buttons": None,
                "next_action": "none",
                "ready_to_persist": False,
            }
        return {
            "stage": "review",
            "editing_field": None,
            "details": details,
            "response_text": _review(details),
            "response_buttons": _buttons(
                (FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD, "✅ Confirmar"),
                (FIRST_VISIT_REVIEW_MODIFY_PAYLOAD, "✏️ Modificar"),
                (FIRST_VISIT_REVIEW_CANCEL_PAYLOAD, "❌ Cancelar"),
            ),
            "next_action": "none",
            "ready_to_persist": False,
        }

    graph = StateGraph(FirstVisitIntakeState)
    graph.add_node("advance", advance)
    graph.add_edge(START, "advance")
    graph.add_edge("advance", END)
    return graph.compile()
