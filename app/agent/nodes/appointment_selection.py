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
from datetime import datetime
from typing import cast

from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.list_message import ListMessage, ListRow
from app.domain.value_objects.paginated_list import paginate_rows, truncate_title

#: `datetime.strftime('%A')` is locale-dependent, and this codebase never
#: sets a Spanish process locale (deliberately — `locale.setlocale` is
#: process-global and would affect every other thread/request). Seen live:
#: slot listings and confirmations rendered the weekday in English (e.g.
#: "Friday 25/09/2026") because the deployed process locale isn't Spanish.
#: `datetime.weekday()` (0=Monday) is locale-independent, so it indexes this
#: fixed table instead.
_SPANISH_WEEKDAYS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def spanish_weekday(moment: datetime) -> str:
    return _SPANISH_WEEKDAYS[moment.weekday()]


def format_slot_datetime(moment: datetime) -> str:
    """One-line 'Viernes 25/09 13:30 hs 🕐' for slot/appointment option
    listings, which never need the year (always within the current search
    window)."""
    return f"{spanish_weekday(moment)} {moment.strftime('%d/%m')} {moment.strftime('%H:%M')} hs 🕐"


def format_confirmation_datetime(moment: datetime) -> str:
    """Two-line 'Viernes 25/09/2026\\n13:30 hs 🕐' for confirmation/success
    messages, which spell out the year since they're read standalone,
    without an accompanying list of other options."""
    date_part = f"{spanish_weekday(moment)} {moment.strftime('%d/%m/%Y')}"
    time_part = f"{moment.strftime('%H:%M')} hs 🕐"
    return f"{date_part}\n{time_part}"

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
#: The post-specialty "ver próximos turnos vs elegir profesional" screen
#: (this change — most patients are new and don't know any professional by
#: name, so forcing that pick before showing a single available slot was
#: pure friction for them).
STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE = "awaiting_specialty_browse_choice"
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
    STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE: "choose_browse_mode",
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


# --- LLM-output safety net ---------------------------------------------


def text_leaks_a_name(text: str, names: list[str]) -> bool:
    """True when `text` mentions any of `names` — a defensive backstop for
    every call site whose `instruccion` tells the model not to name the
    options a List/buttons message already shows.

    Confirmed live (user-reported, screenshot): the model's own prompt
    compliance is not a guarantee — it has fabricated an entire plausible-
    sounding specialty/professional list in free text despite the explicit
    instruction not to mention one at all. Callers must discard the
    LLM-generated text and use their own static fallback when this returns
    True, so the rule holds even when a stronger prompt still doesn't.
    Case-insensitive substring match — deliberately simple and cheap, no
    LLM call of its own.
    """
    lowered = text.casefold()
    return any(name.casefold() in lowered for name in names if name)


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
    return f"- {professional_name}: {format_slot_datetime(slot.time_range.start)}"


#: A `ListRow.title` needs no professional name: every slot search that
#: produces the options shown here already passes a specific
#: `professional_id` (see `_offer_slots`/`search_availability_node`'s own
#: comments — Dentalink's `/v5/agendas` doesn't return `id_especialidad`,
#: so the professional is the one filter that's always honoured), so a row
#: only ever needs to tell two same-professional slots apart by date/time.
_SLOT_ROW_CLOCK_EMOJI = "🕐"


def slot_rows(
    slots: list[AppointmentSlot], page: int = 0, include_back: bool = False
) -> list[ListRow]:
    """Builds the paginated rows for the available-slots screen — each row
    shows the weekday name, date and time (PRD requirement: patients must
    see "Martes 17/09 14:30", not just the date, so they never have to
    tap a row to find out what day it falls on)."""
    rows = [
        ListRow(
            id=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
            title=truncate_title(
                f"{_SLOT_ROW_CLOCK_EMOJI} {spanish_weekday(slot.time_range.start)} "
                f"{slot.time_range.start.strftime('%d/%m %H:%M')}"
            ),
        )
        for slot in slots
    ]
    return paginate_rows(rows, page, include_back)


def slots_list_message(
    slots: list[AppointmentSlot], page: int = 0, include_back: bool = False
) -> ListMessage:
    """The paginated available-slots list message.

    WhatsApp caps an interactive-button message at 3 buttons — with more
    than 3 available slots, everything past the 3rd used to simply never
    render. A list supports up to Meta's real 10-row cap instead.
    """
    return ListMessage(
        button_label="Elegí horario",
        rows=slot_rows(slots, page, include_back),
        section_title="Horarios disponibles",
    )


def professional_surname(full_name: str) -> str:
    """Last whitespace-separated token of a professional's name — a
    deliberately lossy abbreviation (same "good enough for a 24-char row
    title, not a legal identifier" tradeoff `professional_emoji` already
    takes) so a slot row can fit "weekday + date + time + doctor" under
    WhatsApp's row-title cap. Falls back to the raw name if it has no
    whitespace at all (never raises)."""
    parts = full_name.split()
    return parts[-1] if parts else full_name


def slot_rows_multi_professional(
    slots: list[AppointmentSlot],
    professional_surnames: dict[str, str],
    page: int = 0,
    include_back: bool = False,
) -> list[ListRow]:
    """Sibling of `slot_rows` for a slot list aggregated across MULTIPLE
    professionals (PRD.md has no section for this — most patients are new
    and don't know any professional by name, so this is what "ver próximos
    turnos" without picking one first shows). Unlike `slot_rows`, every row
    here needs to say WHICH doctor it belongs to, since two rows can share
    the same date/time.

    A separate function rather than a new parameter on `slot_rows` — the
    single-professional path stays byte-for-byte unchanged, no behavior
    risk to its own existing callers/tests.

    Row format drops the clock emoji and abbreviates the weekday to 3
    letters to make room: "Mié 17/09 14:30 Alvarez" — 23 chars for the
    longest realistic case, 1 under `TITLE_MAX_CHARS`; `truncate_title`
    still hard-caps anything longer.
    """
    rows = [
        ListRow(
            id=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
            title=truncate_title(
                f"{spanish_weekday(slot.time_range.start)[:3]} "
                f"{slot.time_range.start.strftime('%d/%m %H:%M')} "
                f"{professional_surnames.get(slot.professional_id, 'Profesional')}"
            ),
        )
        for slot in slots
    ]
    return paginate_rows(rows, page, include_back)


def slots_list_message_multi_professional(
    slots: list[AppointmentSlot],
    professional_surnames: dict[str, str],
    page: int = 0,
    include_back: bool = False,
) -> ListMessage:
    """Sibling of `slots_list_message` for the aggregated, any-professional
    slot list — see `slot_rows_multi_professional`'s own docstring."""
    return ListMessage(
        button_label="Elegí horario",
        rows=slot_rows_multi_professional(slots, professional_surnames, page, include_back),
        section_title="Próximos turnos",
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
