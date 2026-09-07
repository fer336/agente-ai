from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ListRow:
    """One selectable row in a WhatsApp list message.

    `id` is what comes back in the tap (WhatsApp's `list_reply.id`) — same
    role as an `InteractiveButton.id`. Meta's own limits: `title` up to 24
    chars, `description` (optional) up to 72.
    """

    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ListMessage:
    """A WhatsApp interactive list message — used instead of buttons when
    there are more than 3 options but still few enough to fit Meta's
    10-row cap (beyond that, this codebase falls back to a numbered text
    list, e.g. the specialty catalog).
    """

    button_label: str
    rows: list[ListRow]
    section_title: str | None = None
