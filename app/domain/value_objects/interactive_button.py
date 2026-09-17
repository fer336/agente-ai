from dataclasses import dataclass

#: WhatsApp's own reply-button title constraint (YCloud error 131009:
#: "Button title length invalid. Min length: 1, Max length: 20") — seen
#: live: "🔎 Ver otros profesionales" (25 characters) shipped as a static,
#: hardcoded title and silently failed to send in production, with no
#: local/CI signal at all (nothing here calls the real WhatsApp API in
#: tests). Every button title in this codebase is a fixed literal or a
#: fixed-width formatted date — never unboundedly dynamic — so failing
#: loud at construction is strictly safer than a quiet truncation would
#: be: any violation is a genuine bug, not a case that legitimately needs
#: graceful degradation the way a real patient/specialty NAME embedded in
#: a list row (see `ListRow`/`truncate_title`) might.
_TITLE_MAX_CHARS = 20


@dataclass(frozen=True, slots=True)
class InteractiveButton:
    """A single tappable reply button in an interactive WhatsApp message."""

    id: str
    title: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.title) <= _TITLE_MAX_CHARS:
            raise ValueError(
                f"InteractiveButton title must be 1-{_TITLE_MAX_CHARS} characters "
                f"(WhatsApp's own limit) — got {len(self.title)}: {self.title!r}"
            )
