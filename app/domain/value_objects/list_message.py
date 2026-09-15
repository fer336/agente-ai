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


#: WhatsApp's real, live-confirmed cap on a list message's own button
#: label (the tappable "Elegí una opción"-style control that opens the
#: list) — DISTINCT from `ListRow.title`'s 24-char cap above. Confirmed
#: live: WhatsApp rejected an outbound list ("Elegí una especialidad", 22
#: chars) with `[131009] Button label is too long. Max length is 20` —
#: YCloud still answered our send call with 200 OK, so this went
#: completely unnoticed (no error anywhere in our own logs) until someone
#: checked YCloud's own delivery log. Validated here, at construction, so
#: a future overlong label fails loudly in a test instead of silently
#: dropping every message that uses it in production.
_BUTTON_LABEL_MAX_CHARS = 20


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

    def __post_init__(self) -> None:
        if len(self.button_label) > _BUTTON_LABEL_MAX_CHARS:
            raise ValueError(
                f"ListMessage.button_label exceeds WhatsApp's "
                f"{_BUTTON_LABEL_MAX_CHARS}-char cap ({len(self.button_label)} chars): "
                f"{self.button_label!r}"
            )
