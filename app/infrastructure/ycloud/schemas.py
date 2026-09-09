from pydantic import BaseModel, ConfigDict, Field

# UNVERIFIED against a live YCloud account (no live credentials/sandbox in
# this change) — field names follow YCloud's publicly documented WhatsApp
# webhook event shape (`whatsapp.inbound_message.received`, see PRD §24.1),
# which itself mirrors Meta's WhatsApp Cloud API conventions. Confirm every
# field name below against a real YCloud webhook delivery before production
# use — see this PR's report for the full list of open questions.
#
# Interactive button replies (`type="interactive"`,
# `interactive.type="button_reply"`) follow the same Meta WhatsApp Cloud API
# convention: `{"interactive": {"type": "button_reply", "button_reply":
# {"id": "...", "title": "..."}}}`. This is the highest-uncertainty part of
# this module — YCloud's own docs were not available to confirm it — but it
# is the standard, long-documented shape every WhatsApp BSP built on the
# Cloud API mirrors, so it is the most defensible default absent a live
# payload to check against.


class YCloudText(BaseModel):
    body: str = ""


class YCloudButtonReply(BaseModel):
    id: str = ""
    title: str = ""


class YCloudNfmReply(BaseModel):
    """A completed WhatsApp Flow submission (`interactive.type="nfm_reply"`).

    `response_json` is a **stringified** JSON object (Meta's own
    convention, not YCloud-specific) whose keys match the `name` of each
    `TextInput` in the Flow's own JSON (see
    `app.infrastructure.ycloud.flows`) — parse it with `json.loads`, never
    assume its shape without doing so.
    """

    name: str = ""
    response_json: str = ""


class YCloudListReply(BaseModel):
    """A tapped row in an interactive list message (`interactive.type=
    "list_reply"`) — same Meta convention as `button_reply`, just with an
    extra optional `description`."""

    id: str = ""
    title: str = ""
    description: str | None = None


class YCloudInteractive(BaseModel):
    type: str = ""
    button_reply: YCloudButtonReply | None = None
    nfm_reply: YCloudNfmReply | None = None
    list_reply: YCloudListReply | None = None


class YCloudAudioMessage(BaseModel):
    """`type="audio"` payload shape (PRD.md §24.1), following the same Meta
    WhatsApp Cloud API convention every media message type uses: only an
    opaque `id` + `mime_type` are delivered in the webhook — the actual
    download URL is resolved separately via `GET /v1/media/{id}`
    (`YCloudMediaGateway`). `sha256` is optional (not every vendor/media
    type reports one).
    """

    id: str = ""
    mime_type: str = ""
    sha256: str | None = None


class YCloudInboundMessage(BaseModel):
    id: str = ""
    from_: str = Field(default="", alias="from")
    to: str = ""
    type: str = ""
    text: YCloudText | None = None
    interactive: YCloudInteractive | None = None
    audio: YCloudAudioMessage | None = None

    model_config = ConfigDict(populate_by_name=True)


class YCloudInboundEventPayload(BaseModel):
    """Raw shape of a YCloud `whatsapp.inbound_message.received` webhook event.

    Mirrors YCloud's JSON keys verbatim — the vendor-specific schema is
    confined to this module. Only `InboundMessageDTO` (built via
    `webhook_parser.to_inbound_message_dto()`) is allowed to cross into
    `app/application`.
    """

    type: str = ""
    whatsappInboundMessage: YCloudInboundMessage = YCloudInboundMessage()


class YCloudTagChangeExtra(BaseModel):
    """One entry of a `contact.attributes_changed` event's `tags.extra`
    array — documents a single ADDED/REMOVED tag action, per
    https://docs.ycloud.com/reference/contact-attributes-changed-webhook-examples.
    """

    action: str = ""
    id: str = ""
    value: str = ""


class YCloudTagsAttributeChange(BaseModel):
    oldValue: list[str] = Field(default_factory=list)
    newValue: list[str] = Field(default_factory=list)
    extra: list[YCloudTagChangeExtra] = Field(default_factory=list)


class YCloudChangedAttributes(BaseModel):
    tags: YCloudTagsAttributeChange | None = None


class YCloudContactAttributesChanged(BaseModel):
    id: str = ""
    changedAttributes: YCloudChangedAttributes = YCloudChangedAttributes()


class YCloudContactAttributesChangedEventPayload(BaseModel):
    """Raw shape of a YCloud `contact.attributes_changed` webhook event.

    UNVERIFIED against a live YCloud account (no live delivery captured in
    this change) — field names follow YCloud's publicly documented example
    at the URL above. Confirm against a real webhook delivery before
    relying on this for anything beyond the tag-driven bot/human handoff
    toggle it currently backs.
    """

    type: str = ""
    contactAttributesChanged: YCloudContactAttributesChanged = YCloudContactAttributesChanged()


class YCloudSmbEchoText(BaseModel):
    body: str = ""


class YCloudSmbEchoMessage(BaseModel):
    """The echoed message itself, nested under `whatsappMessage`.

    Field names verified against YCloud's own published example payloads
    at
    https://docs.ycloud.com/reference/whatsapp-business-app-sent-message-sync-webhook-examples
    (fetched live — not a guess): `from` is the BUSINESS number, `to` is
    the WhatsApp user (our patient) the staff member replied to — the
    reverse of `YCloudInboundMessage.from_`/`.to` on a patient-sent
    message. `text` is only present when `type == "text"`; other echoed
    message types (`image`/`video`/`audio`/`document`) are not modeled
    here since neither of this event's two effects
    (`app.application.conversations.handle_smb_message_echo`) needs their
    payload — only that the echo happened for this `to` phone.
    """

    id: str = ""
    wamid: str = ""
    status: str = ""
    from_: str = Field(default="", alias="from")
    to: str = ""
    type: str = ""
    text: YCloudSmbEchoText | None = None

    model_config = ConfigDict(populate_by_name=True)


class YCloudSmbMessageEchoEventPayload(BaseModel):
    """Raw shape of a YCloud `whatsapp.smb.message.echoes` webhook event.

    Fired for every OUTBOUND message sent by a human staff member typing
    directly in the WhatsApp Business App (or a linked companion device)
    against a Coexistence-connected number — NOT for messages our bot
    sends via the API, and NOT for inbound messages the patient sends
    (those arrive as `whatsapp.inbound_message.received`, see
    `YCloudInboundEventPayload`). This is the mechanism this change uses
    to detect a staff `/bot` command and to reset the lazy-timeout clock
    on any staff reply — see this PR's report for why the YCloud
    contact-tag mechanism (`YCloudContactAttributesChangedEventPayload`)
    was abandoned as the sole path back to `mode="agent"`.
    """

    type: str = ""
    whatsappMessage: YCloudSmbEchoMessage = YCloudSmbEchoMessage()
