"""Pure, behavior-preserving helpers for the create-appointment selection
path.

This is PR 1 of the appointment-decision-subgraph migration: a no-behavior-
change extraction of the selection helpers, payload resolution, pagination,
and slot list/button builders that `app.agent.nodes.appointment` already
implements. Everything here has no side effects and does not import from
`app.agent.nodes.appointment` -- `appointment.py` depends on this module,
never the other way around, so the typed create-selection subgraph added in
PR 2 can share this same behavior-pinned implementation.
"""

import re
from typing import cast

from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.interactive_button import InteractiveButton

#: Mirrors `app.agent.nodes.appointment.SELECT_SLOT_PAYLOAD_PREFIX`. Owned
#: here now — `appointment.py` imports this constant instead of redefining
#: it, so the two can never drift apart.
SELECT_SLOT_PAYLOAD_PREFIX = "SELECT_SLOT:"

#: Mirror the legacy stage strings this module's mapping and helpers need.
#: Kept as separate literals (not imported from `appointment.py`) so this
#: module never depends on the legacy appointment module — see the module
#: docstring. `appointment.py` keeps its own definitions of these same
#: values for its many other stage-dispatch branches; both are asserted
#: equal by `tests/unit/agent/nodes/test_appointment_selection.py`.
STAGE_AWAITING_SPECIALTY_SELECTION = "awaiting_specialty_selection"
STAGE_AWAITING_PROFESSIONAL_SELECTION = "awaiting_professional_selection"
STAGE_AWAITING_SLOT_SELECTION = "awaiting_slot_selection"
STAGE_AWAITING_NO_SLOTS_CHOICE = "awaiting_no_slots_choice"
STAGE_AWAITING_NO_AVAILABILITY_CHOICE = "awaiting_no_availability_choice"

#: Legacy stage -> internal decision-subgraph entry node (PR 2). Only the
#: first-slice migrated stages are mapped; no-availability/no-slot
#: follow-up stages stay legacy-owned by construction — they're simply
#: absent from this mapping, never mapped to `None`.
LEGACY_STAGE_TO_DECISION_NODE: dict[str, str] = {
    STAGE_AWAITING_SPECIALTY_SELECTION: "choose_specialty",
    STAGE_AWAITING_PROFESSIONAL_SELECTION: "choose_professional",
    STAGE_AWAITING_SLOT_SELECTION: "choose_slot",
}


def decision_entry_node_for_stage(stage: str | None) -> str | None:
    """Looks up the internal decision-subgraph entry node for a legacy
    stage, or `None` when the stage isn't part of the first migrated slice
    (including no stage, no-availability, and no-slots)."""
    if stage is None:
        return None
    return LEGACY_STAGE_TO_DECISION_NODE.get(stage)


# --- Payload resolution helpers --------------------------------------------

#: A patient answering a numbered list types "2", "2." or "opción 2" —
#: never more than three digits, since no catalog here is that long.
_NUMBERED_CHOICE_PATTERN = re.compile(r"\b(\d{1,3})\b")


def resolve_numbered_choice(text: str, option_count: int) -> int | None:
    """Maps a patient's 1-based reply to a 0-based index into the list they
    were just shown, or `None` when it isn't a number in range."""
    match = _NUMBERED_CHOICE_PATTERN.search(text)
    if match is None:
        return None
    index = int(match.group(1)) - 1
    return index if 0 <= index < option_count else None


def resolve_by_name(text: str, names: list[str]) -> int | None:
    """Falls back to matching a catalog name found inside the message —
    a patient who types "quiero ortodoncia" instead of "1" still gets
    through."""
    lowered = text.casefold()
    for index, name in enumerate(names):
        if name.casefold() in lowered:
            return index
    return None


def resolve_choice(text: str, names: list[str]) -> int | None:
    """Number first (what the list explicitly asked for), name second."""
    by_number = resolve_numbered_choice(text, len(names))
    if by_number is not None:
        return by_number
    return resolve_by_name(text, names)


def numbered_list(names: list[str]) -> str:
    return "\n".join(f"{position}. {name}" for position, name in enumerate(names, start=1))


def resolve_list_choice(
    *,
    button_payload: str | None,
    user_message: str,
    payload_prefix: str,
    option_ids: list[str],
    option_names: list[str],
) -> int | None:
    """Resolves a patient's selection from a paginated list.

    A row tap (`payload_prefix + id`) resolves deterministically against
    the ids currently on screen. A tap whose id isn't among them (a stale
    row from an older list message) is rejected outright — it never falls
    through to number/name matching. Only the absence of a button payload
    falls back to matching the free-text message by number, then by name.
    """
    button_index = (
        next(
            (
                index
                for index, option_id in enumerate(option_ids)
                if button_payload == f"{payload_prefix}{option_id}"
            ),
            None,
        )
        if button_payload is not None
        else None
    )
    if button_index is not None:
        return button_index
    if button_payload is not None:
        return None
    return resolve_choice(user_message, option_names)


# --- Pagination helpers -----------------------------------------------------


def current_page(collected_data: dict[str, object], key: str) -> int:
    """Reads a 0-based page counter from `collected_data`, defaulting to 0
    for both a missing key and an explicit `None`."""
    return cast(int, collected_data.get(key, 0) or 0)


def next_page(collected_data: dict[str, object], key: str) -> int:
    return current_page(collected_data, key) + 1


# --- Slot list/button builders ----------------------------------------------


def format_slot_option(slot: AppointmentSlot, professional_names: dict[str, str]) -> str:
    professional_name = professional_names.get(slot.professional_id, "Profesional")
    return f"- {professional_name}: {slot.time_range.start.strftime('%A %d/%m %H:%M hs')}"


def slot_button(slot: AppointmentSlot) -> InteractiveButton:
    return InteractiveButton(
        id=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        title=slot.time_range.start.strftime("%d/%m %H:%M"),
    )


def slot_payload_id(button_payload: str | None) -> str | None:
    """Extracts the slot id from a `SELECT_SLOT:<id>` payload, or `None`
    when the payload is absent or carries a different prefix."""
    if button_payload is None or not button_payload.startswith(SELECT_SLOT_PAYLOAD_PREFIX):
        return None
    return button_payload[len(SELECT_SLOT_PAYLOAD_PREFIX) :]


def slot_by_id(slots: list[AppointmentSlot], slot_id: str) -> AppointmentSlot | None:
    """Finds a slot by id within the currently checkpointed availability
    window, or `None` when it's outside it (a stale selection)."""
    return next((slot for slot in slots if slot.id == slot_id), None)
