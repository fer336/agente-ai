"""Static FAQ-style catalog of commonly-asked treatments (this session's own brief).

Confirmed by the clinic owner (Martin) via the account manager, over
WhatsApp — a fixed, hardcoded list, unlike `app.domain.value_objects.
welcome_menu.WELCOME_LIST`'s other rows, none of which are sourced from
Dentalink. Deliberately NOT the same concept as `app.domain.entities.
treatment.Treatment` (a *patient's own* treatment/balance history against
Dentalink, `GET /v1/pacientes/{id}/tratamientos`) — this module never
imports or touches that entity or its gateways.

Answers ONLY "what treatments/prices do you offer" — never a booking step,
never live availability. It intentionally never states a numeric price: no
real price data exists yet, and the LLM prompt (`DEFAULT_UNDERSTAND_PROMPT`)
already forbids inventing one — printing a stale/wrong hardcoded number here
would undermine that same rule from a different angle.

Plain text rather than a `ListMessage`/`ListRow` catalog (contrast
`WELCOME_LIST`, `app.domain.value_objects.paginated_list.
specialties_list_message`): none of these rows lead anywhere — no booking,
no further selection, nothing a tap should do — so Meta's 24-char row title
cap would only force a distorted name (`"Extracciones particulares"` alone
is already 25 chars) for no functional gain.
"""

#: Confirmed, final content (client conversation + explicit follow-up
#: confirmation). "Alineadores" is deliberately its own separate line item
#: per the client's own instruction — not merged into the general list.
TREATMENT_CATALOG_ITEMS: tuple[str, ...] = (
    "Blanqueamiento",
    "Limpieza particular",
    "Consulta particular",
    "Extracciones particulares",
    "Alineadores",
)

TREATMENT_CATALOG_TEXT = (
    "Estos son los tratamientos que más nos consultan:\n\n"
    + "\n".join(f"🦷 {item}" for item in TREATMENT_CATALOG_ITEMS)
    + "\n\nPara el precio exacto y actualizado de cada uno, te recomendamos "
    "consultarlo directo con administración."
)
