# Staff /bot and /adm commands

Objective: staff can type `/bot` (bot takes over) or `/adm` (staff takes over) from the phone,
WhatsApp Web or the Chatwoot chat; the bot mode AND the Chatwoot control label change together.

Rules
- Exact text, trimmed, case-insensitive. Never mirrored/forwarded as a normal message.
- `/adm`: mode human, label `administracion`, human-reply timer starts.
- `/bot`: mode agent, fresh restart (phone path), label `agente`.
- Phone/WhatsApp Web: any other staff message also pauses (existing) and now sets `administracion`.
- Chatwoot replies also start the human-reply timer (closes the missing-timer gap).

## Tasks
- [x] T1 Parser `extract_staff_command` (+ tests)
- [x] T2 Phone/WhatsApp Web echo route: label sync for `/bot`, `/adm` and plain echoes; commands not mirrored (+ tests)
- [x] T3 Chatwoot message route: `/bot`, `/adm` consumed, not forwarded; pause stamps `last_human_reply_at` (+ tests)

Route: inline. Branch: feat/staff-bot-adm-commands (from main + echo handoff commits).
