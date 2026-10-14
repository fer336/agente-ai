import base64
import json
from collections.abc import Sequence
from pathlib import Path

#: Meta's Flow JSON schema version (developers.facebook.com/docs/whatsapp/
#: flows/reference/components) — unrelated to `flow_message_version` in
#: `YCloudClient.send_flow`'s payload, which versions the SEND action, not
#: this document.
_FLOW_JSON_VERSION = "6.2"

#: Both Flows below are single-screen and `terminal: true` — the screen
#: id doubles as the `flow_screen_id` `YCloudClient.send_flow` needs to
#: open it directly.
VERIFICATION_FLOW_SCREEN_ID = "VERIFICACION"
REGISTRATION_FLOW_SCREEN_ID = "REGISTRO"
PATIENT_INTAKE_FLOW_SCREEN_ID = "DATOS_PACIENTE"

#: Max embedded-image size YCloud/Meta documents for a Flow screen.
_MAX_IMAGE_BASE64_BYTES = 300_000

_FLOW_HEADER_IMAGE_PATH = Path(__file__).resolve().parents[2] / "assets" / "flow-header.png"

#: Meta's Dropdown limits: 200 options (no images), 30-char option titles.
_MAX_DROPDOWN_OPTIONS = 200
_MAX_DROPDOWN_TITLE_CHARS = 30

#: Dropdown option id of the private-pay choice. The backend treats it as
#: "no obra social, no plan" (see the appointment node).
PARTICULAR_OPTION_ID = "particular"
_PARTICULAR_OPTION_TITLE = "Particular"


def load_flow_header_image_base64() -> str:
    """The clinic logo (`app/assets/flow-header.png`) as raw base64, the
    form Flow JSON's `Image.src` takes. `_image_component` still guards the
    300 KB limit."""
    return base64.b64encode(_FLOW_HEADER_IMAGE_PATH.read_bytes()).decode("ascii")


def _normalized_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _dropdown_title(name: str) -> str:
    title = " ".join(name.split())
    if len(title) <= _MAX_DROPDOWN_TITLE_CHARS:
        return title
    return title[: _MAX_DROPDOWN_TITLE_CHARS - 1].rstrip() + "…"


def _obra_social_options(agreement_names: Sequence[str]) -> list[dict[str, str]]:
    """Dropdown options: our own "Particular" first (so the 200 cap can never
    drop it), then each distinct agreement. The id is the agreement name
    itself, the exact string the backend looks the agreement up by; only the
    title is truncated to Meta's limit. Empty names, duplicates (case- and
    spacing-insensitive) and any agreement already called "Particular" are
    skipped."""
    options = [{"id": PARTICULAR_OPTION_ID, "title": _PARTICULAR_OPTION_TITLE}]
    seen = {_normalized_name(_PARTICULAR_OPTION_TITLE)}
    for raw_name in agreement_names:
        name = raw_name.strip()
        key = _normalized_name(name)
        if not key or key in seen:
            continue
        if len(options) >= _MAX_DROPDOWN_OPTIONS:
            break
        seen.add(key)
        options.append({"id": name, "title": _dropdown_title(name)})
    return options


def _image_component(header_image_base64: str | None) -> list[dict[str, object]]:
    if header_image_base64 is None:
        return []
    if len(header_image_base64) > _MAX_IMAGE_BASE64_BYTES:
        # Silently dropping an oversized image would ship a broken-looking
        # Flow; the caller needs to know before it ever reaches YCloud.
        raise ValueError(
            f"Flow header image exceeds {_MAX_IMAGE_BASE64_BYTES} bytes once base64-encoded"
        )
    return [
        {
            "type": "Image",
            "src": header_image_base64,
            "width": 300,
            "height": 150,
            "scale-type": "contain",
            "alt-text": "Smiling Dental Studio",
        }
    ]


def build_verification_flow_json(header_image_base64: str | None = None) -> str:
    """First step of patient identification: just Nombre + DNI.

    Kept deliberately minimal — its only job is letting our backend check
    Dentalink for an existing record (`identify_patient`) before ever
    asking for anything else, so a returning patient never re-types data
    the clinic already has.
    """
    screen = {
        "id": VERIFICATION_FLOW_SCREEN_ID,
        "title": "Verificá tus datos",
        "terminal": True,
        "layout": {
            "type": "Form",
            "children": [
                *_image_component(header_image_base64),
                {"type": "TextHeading", "text": "Verificá tus datos"},
                {
                    "type": "TextInput",
                    "name": "full_name",
                    "label": "Nombre completo",
                    "input-type": "text",
                    "required": True,
                },
                {
                    "type": "TextInput",
                    "name": "dni",
                    "label": "DNI",
                    "input-type": "number",
                    "required": True,
                },
                {
                    "type": "Footer",
                    "label": "Enviar",
                    "on-click-action": {"name": "complete_action"},
                },
            ],
        },
    }
    return json.dumps({"version": _FLOW_JSON_VERSION, "screens": [screen]})


def build_registration_flow_json(header_image_base64: str | None = None) -> str:
    """New-patient registration: everything Dentalink can actually store.

    Phone is never asked here — it's already known from the WhatsApp
    contact itself (`conversation_id`), and asking again only risks a typo
    that no longer matches who is actually messaging. "Obra Social" is
    optional (private-pay patients have none) and is resolved against the
    real convenios catalog and linked separately after creation — see
    `AgreementGateway.link_patient_agreement`.
    """
    screen = {
        "id": REGISTRATION_FLOW_SCREEN_ID,
        "title": "Completá tus datos",
        "terminal": True,
        "layout": {
            "type": "Form",
            "children": [
                *_image_component(header_image_base64),
                {"type": "TextHeading", "text": "Completá tus datos"},
                {
                    "type": "TextInput",
                    "name": "full_name",
                    "label": "Nombre completo",
                    "input-type": "text",
                    "required": True,
                },
                {
                    "type": "TextInput",
                    "name": "dni",
                    "label": "DNI",
                    "input-type": "number",
                    "required": True,
                },
                {
                    "type": "TextInput",
                    "name": "email",
                    "label": "Mail",
                    "input-type": "email",
                    "required": True,
                },
                {
                    "type": "TextInput",
                    "name": "obra_social",
                    "label": "Obra Social / Cobertura",
                    "input-type": "text",
                    "required": False,
                },
                {
                    "type": "Footer",
                    "label": "Enviar",
                    "on-click-action": {"name": "complete_action"},
                },
            ],
        },
    }
    return json.dumps({"version": _FLOW_JSON_VERSION, "screens": [screen]})


def build_patient_intake_flow_json(
    header_image_base64: str | None = None,
    agreement_names: Sequence[str] = (),
) -> str:
    """One Flow for both returning and new patients.

    A single terminal screen asks "are you a patient?" first. Name and DNI
    are always shown; Mail and Obra Social appear (Flow JSON `If`) only for
    "no" — new patients, who need full registration. Obra Social is a
    Dropdown of `agreement_names` plus "Particular"; the optional Plan field
    sits in a second, nested `If` (Meta allows up to 3 levels from Flow JSON
    4.0, we use 6.2) shown only once an insurer other than "Particular" is
    picked. The completion payload carries every field; the ones whose `If`
    branch was never rendered simply come back empty. The backend branches
    on `es_paciente` (see the appointment node).
    """
    new_patient_fields: list[dict[str, object]] = [
        {
            "type": "TextInput",
            "name": "email",
            "label": "Mail",
            "input-type": "email",
            "required": True,
        },
        {
            "type": "Dropdown",
            "name": "obra_social",
            # Meta caps Dropdown labels at 20 characters.
            "label": "Obra social",
            "required": True,
            "data-source": _obra_social_options(agreement_names),
        },
        {
            "type": "If",
            "condition": (
                f"${{form.obra_social}} != '' && ${{form.obra_social}} != '{PARTICULAR_OPTION_ID}'"
            ),
            "then": [
                {
                    "type": "TextInput",
                    "name": "plan",
                    "label": "Plan (opcional)",
                    "input-type": "text",
                    "required": False,
                },
            ],
        },
    ]
    screen = {
        "id": PATIENT_INTAKE_FLOW_SCREEN_ID,
        "title": "Tus datos",
        "terminal": True,
        "layout": {
            "type": "SingleColumnLayout",
            "children": [
                {
                    "type": "Form",
                    "name": "form",
                    "children": [
                        *_image_component(header_image_base64),
                        {"type": "TextHeading", "text": "Tus datos"},
                        {
                            "type": "RadioButtonsGroup",
                            "name": "es_paciente",
                            "label": "¿Sos paciente del consultorio?",
                            "required": True,
                            "data-source": [
                                {"id": "si", "title": "Sí, ya soy paciente"},
                                {"id": "no", "title": "No, es mi primera vez"},
                            ],
                        },
                        {
                            "type": "TextInput",
                            "name": "full_name",
                            "label": "Nombre completo",
                            "input-type": "text",
                            "required": True,
                        },
                        {
                            "type": "TextInput",
                            "name": "dni",
                            "label": "DNI",
                            "input-type": "number",
                            "required": True,
                            "helper-text": "Solo números, de 7 u 8 dígitos, sin puntos",
                        },
                        {
                            "type": "If",
                            "condition": "${form.es_paciente} == 'no'",
                            "then": new_patient_fields,
                        },
                        {
                            "type": "Footer",
                            "label": "Enviar",
                            "on-click-action": {
                                "name": "complete",
                                "payload": {
                                    "es_paciente": "${form.es_paciente}",
                                    "full_name": "${form.full_name}",
                                    "dni": "${form.dni}",
                                    "email": "${form.email}",
                                    "obra_social": "${form.obra_social}",
                                    "plan": "${form.plan}",
                                },
                            },
                        },
                    ],
                },
            ],
        },
    }
    return json.dumps({"version": _FLOW_JSON_VERSION, "screens": [screen]})
