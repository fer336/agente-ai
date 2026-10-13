# Chatwoot contact names from YCloud

Objective: Chatwoot contacts show the WhatsApp profile name YCloud sends in
`whatsappInboundMessage.customerProfile.name` instead of the phone number.

Scope: backend only (no n8n). Never overwrite a name staff set by hand: rename only
when the current name is empty or equals the phone/identifier.

## Tasks
- [x] T1 Parse `customerProfile.name` into `InboundMessageDTO.profile_name` (parser + schema tests)
- [x] T2 Chatwoot client `get_contact` / `update_contact`; gateway `rename_contact_if_unnamed`; fake gateway
- [x] T3 `mirror_incoming` uses the profile name (new contact) and renames phone-named contacts; ingest passes it

Route: inline (evidence already held; ~8 small files).
Checks: `uv run pytest tests/unit`, ruff, mypy on touched files.
