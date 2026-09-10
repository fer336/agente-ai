"""Pure pagination + emoji-prefix helpers for WhatsApp interactive lists.

Meta caps a list message at 10 rows (`ListRow`'s own docstring), with row
titles up to 24 characters. Catalog screens with more items than that are
split into pages of 9 real rows plus a `LIST_MORE` "Ver más" row; when the
remaining items fit, the final page (and any list short enough to fit whole)
ends with a `LIST_BACK` "Volver atrás" row instead, which pops the patient
back to the previous screen (the navigation stack lives in
`collected_data["nav_stack"]`, maintained by the appointment/specialties
nodes).

Pure domain logic — no I/O, no framework imports — so the node layer just
converts entities to `ListRow`s here and ships the result through
`AgentState["response_list"]`.
"""

from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty
from app.domain.value_objects.list_message import ListMessage, ListRow
from app.domain.value_objects.menu_payloads import (
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    PROFESSIONAL_PAYLOAD_PREFIX,
    SPECIALTY_PAYLOAD_PREFIX,
)

#: Meta's hard cap on rows per interactive list.
MAX_ROWS = 10
#: Real item rows per page (one slot always reserved for Ver más/Volver atrás).
PAGE_SIZE = MAX_ROWS - 1
#: Meta's row-title cap, in characters (not code points).
TITLE_MAX_CHARS = 24

#: Row titles for the two navigation rows.
MORE_TITLE = "Ver más"
BACK_TITLE = "Volver atrás"

_SPECIALTY_EMOJIS: tuple[tuple[str, str], ...] = (
    ("odontopediatr", "👶"),
    ("ortodoncia infantil", "😁"),
    ("ortodoncia", "🦷"),
    ("estética", "✨"),
    ("estetica", "✨"),
    ("endodoncia", "🔧"),
    ("bruxismo", "🌙"),
    ("rehabilitaci", "🛠"),
    ("rehabilitac", "🛠"),
    ("implant", "🦷"),
    ("cirug", "🫁"),
    ("limpieza", "🪥"),
    (" blanqueamiento", "😁"),
    ("blanqueamiento", "😁"),
    ("periencia", "🪥"),
    ("general", "🦷"),
)

#: Male-name markers checked before the female ones ("dor." would otherwise
#: match inside "candor", hence the leading space); a bare first name falls
#: back to a small female-name list, then defaults to the man emoji.
_FEMALE_MARKERS = ("dra.", "dra ")
_FEMALE_NAMES = ("camila", "laura", "maría", "maria", "sofía", "sofia", "lucía", "lucia")


def truncate_title(title: str, limit: int = TITLE_MAX_CHARS) -> str:
    """Clamps a row title to Meta's 24-character cap.

    Python's `len` already counts in code points (what WhatsApp's limit is
    actually enforced against), so a plain slice is safe even for ZWJ emoji
    like 👨‍⚕️ — the sequence counts as 3 characters, and cutting it mid-way
    would just render a bare silhouette, never crash.
    """
    if len(title) <= limit:
        return title
    return title[: limit - 1] + "…"


def specialty_emoji(name: str) -> str:
    """Picks an identifying emoji prefix for a specialty name."""
    lowered = name.lower()
    for marker, emoji in _SPECIALTY_EMOJIS:
        if marker in lowered:
            return emoji
    return "🦷"


def professional_emoji(full_name: str) -> str:
    """Picks 👨‍⚕️/👩‍⚕️ for a professional by their name."""
    lowered = full_name.lower()
    if any(marker in lowered for marker in _FEMALE_MARKERS):
        return "👩‍⚕️"
    first = lowered.split()[0] if lowered.split() else ""
    if any(first.startswith(name) for name in _FEMALE_NAMES):
        return "👩‍⚕️"
    return "👨‍⚕️"


def paginate_rows(
    rows: list[ListRow], page: int, include_back: bool
) -> list[ListRow]:
    """One page of rows for a paginated list screen.

    - `rows` are the real item rows for the WHOLE catalog (not a slice).
    - `page` is 0-based; pages hold `PAGE_SIZE` real rows each.
    - With more pages remaining, a `LIST_MORE` row is appended (9 real rows
      + "Ver más" = Meta's 10-row cap).
    - On the last page (or a single-page list), `include_back=True` appends
      a `LIST_BACK` row so the patient can pop back a screen.
    """
    start = page * PAGE_SIZE
    fit_limit = PAGE_SIZE if include_back else MAX_ROWS
    if page == 0 and len(rows) <= fit_limit:
        # The whole catalog fits in one list — no paging at all, not even
        # a "Ver más" row. When a back row is requested, reserve one slot
        # for it so the WhatsApp list never exceeds Meta's 10-row cap.
        if include_back:
            return [*rows, ListRow(id=LIST_BACK_PAYLOAD, title=BACK_TITLE)]
        return list(rows)
    page_rows = list(rows[start : start + PAGE_SIZE])
    has_more = start + PAGE_SIZE < len(rows)
    if has_more:
        page_rows.append(ListRow(id=LIST_MORE_PAYLOAD, title=MORE_TITLE))
    elif include_back:
        page_rows.append(ListRow(id=LIST_BACK_PAYLOAD, title=BACK_TITLE))
    return page_rows


def specialty_rows(
    specialties: list[Specialty], page: int = 0, include_back: bool = False
) -> list[ListRow]:
    """Builds the paginated rows for the specialty catalog screen."""
    rows = [
        ListRow(
            id=f"{SPECIALTY_PAYLOAD_PREFIX}{specialty.id}",
            title=truncate_title(f"{specialty_emoji(specialty.name)} {specialty.name}"),
        )
        for specialty in specialties
    ]
    return paginate_rows(rows, page, include_back)


def professional_rows(
    professionals: list[Professional], page: int = 0, include_back: bool = False
) -> list[ListRow]:
    """Builds the paginated rows for a specialty's professionals screen."""
    rows = [
        ListRow(
            id=f"{PROFESSIONAL_PAYLOAD_PREFIX}{professional.id}",
            title=truncate_title(
                f"{professional_emoji(professional.full_name)} {professional.full_name}"
            ),
        )
        for professional in professionals
    ]
    return paginate_rows(rows, page, include_back)


def specialties_list_message(
    specialties: list[Specialty], page: int = 0, include_back: bool = False
) -> ListMessage:
    """The paginated specialty-catalog list message."""
    return ListMessage(
        button_label="Elegí una especialidad",
        rows=specialty_rows(specialties, page, include_back),
        section_title="Especialidades",
    )


def professionals_list_message(
    professionals: list[Professional], page: int = 0, include_back: bool = False
) -> ListMessage:
    """The paginated professionals-of-a-specialty list message."""
    return ListMessage(
        button_label="Elegí un profesional",
        rows=professional_rows(professionals, page, include_back),
        section_title="Profesionales",
    )
