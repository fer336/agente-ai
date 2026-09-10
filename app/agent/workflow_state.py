from typing import Literal

SelectionLevel = Literal["specialty", "professional", "slot"]

# Operational selections form a dependency chain. Moving back in the workflow
# must only invalidate values that depend on the choice being revisited; patient
# identity and unrelated conversation context intentionally never appear here.
_DROP_BY_LEVEL: dict[SelectionLevel, frozenset[str]] = {
    "specialty": frozenset(
        {
            "stage",
            "navigation_target",
            "chosen_specialty_id",
            "chosen_specialty_name",
            "specialty_options",
            "specialty_retry_count",
            "specialties_page",
            "chosen_professional_id",
            "professional_options",
            "professional_retry_count",
            "doctors_page",
            "available_slots",
            "pending_selected_slot",
            "professional_names",
        }
    ),
    "professional": frozenset(
        {
            "stage",
            "navigation_target",
            "chosen_professional_id",
            "professional_options",
            "professional_retry_count",
            "doctors_page",
            "available_slots",
            "pending_selected_slot",
            "professional_names",
        }
    ),
    "slot": frozenset(
        {
            "stage",
            "navigation_target",
            "available_slots",
            "pending_selected_slot",
        }
    ),
}


def invalidate_from(data: dict[str, object], level: SelectionLevel) -> dict[str, object]:
    """Return a copy with only ``level`` and its downstream choices removed.

    Deliberately preserves patient/identification data, the requested operation,
    the selected appointment during a reschedule, and every other independent
    value. Navigation is therefore not equivalent to resetting the workflow.
    """

    dropped = _DROP_BY_LEVEL[level]
    return {key: value for key, value in data.items() if key not in dropped}
