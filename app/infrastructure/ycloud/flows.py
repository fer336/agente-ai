import json

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
            "alt-text": "Smiling Pilar",
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


def build_patient_intake_flow_json(header_image_base64: str | None = None) -> str:
    """One Flow for both returning and new patients.

    A single terminal screen asks "are you a patient?" first. Name and DNI
    are always shown; Mail and Obra Social appear (Flow JSON `If`) only for
    "no" — new patients, who need full registration. The completion payload
    carries every field; `email`/`obra_social` simply come back empty when
    the `If` branch was never rendered. The backend branches on
    `es_paciente` (see the appointment node).
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
            "type": "TextInput",
            "name": "obra_social",
            "label": "Obra Social / Cobertura",
            "input-type": "text",
            "required": False,
        },
    ]
    screen = {
        "id": PATIENT_INTAKE_FLOW_SCREEN_ID,
        "title": "Tus datos",
        "terminal": True,
        "layout": {
            "type": "Form",
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
                        },
                    },
                },
            ],
        },
    }
    return json.dumps({"version": _FLOW_JSON_VERSION, "screens": [screen]})
