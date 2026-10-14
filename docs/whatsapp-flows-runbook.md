# WhatsApp Flow and template runbook (new number / new WABA)

How to recreate the patient intake Flow and the four automatic reminder templates for another
WhatsApp number. Written from what was actually built and what Meta/YCloud actually answered; items
marked **unverified** have not been confirmed against a live account.

## What belongs to the number

Everything below is created inside one WhatsApp Business Account (WABA). Flow ids and template
names are **not** shared between WABAs, so a new number needs its own Flow and its own templates.
Per-deployment settings (all live in the Swarm secret `agente_ai_backend_env`, mounted at
`/run/secrets/backend.env`; changing it means a new secret version plus a stack redeploy):

| Setting | Meaning |
| --- | --- |
| `YCLOUD_API_KEY`, `YCLOUD_WABA_ID`, `YCLOUD_WHATSAPP_NUMBER` | The YCloud account and the number |
| `YCLOUD_WEBHOOK_SECRET` | Path secret of the YCloud webhook for that number |
| `YCLOUD_PATIENT_INTAKE_FLOW_ID` | The published intake Flow of that WABA |

Open question: whether the new number gets its own backend deployment or shares this one. Flow ids
and the API key are single settings today, so one deployment serves one WABA.

## Part 1 - Patient intake Flow

### What the Flow asks

One screen (`DATOS_PACIENTE`) with the clinic logo on top:

1. "¿Sos paciente del consultorio?" (`es_paciente`: `si` / `no`).
2. Always: full name and DNI.
3. Only for `no` (first visit): email, **Obra social** (dropdown) and **Plan** (optional text).
   - The dropdown lists "Particular" first, then the enabled Dentalink convenios, built when the
     draft is created.
   - Plan is hidden when the obra social is Particular.

The agent reads the completion payload (`es_paciente`, `full_name`, `dni`, `email`, `obra_social`,
`plan`). A Particular patient is registered without a plan. If `YCLOUD_PATIENT_INTAKE_FLOW_ID` is
empty the agent falls back to the two legacy Flows.

Code: `build_patient_intake_flow_json` in `app/infrastructure/ycloud/flows.py`, consumption in
`app/agent/nodes/appointment.py`, logo in `app/assets/flow-header.png`.

### Steps

1. **Meta business must be verified.** Publishing an unverified business fails with
   `Blocked by Integrity` (code 139000, subcode 4233020). Creating drafts works regardless.
2. **Deploy a release that contains the draft route**, then log in to `/admin/login` with a user
   whose role is `ADMIN_TECHNICAL`.
3. **Create the draft** from the browser console of that logged-in tab:

   ```js
   fetch('/admin/api/flows/intake-draft', {
     method: 'POST',
     headers: { 'X-CSRF-Token': document.cookie.split('; ').find(c => c.startsWith('admin_csrf=')).split('=')[1] },
   }).then(async r => console.log(r.status, await r.text()))
   ```

   It returns `flow_id` and `preview_url`. Never paste the session or CSRF cookie anywhere.
4. **Review the preview.** Open `preview_url`. Per other providers' docs the preview shows the
   screens but is not interactive (**unverified** for YCloud), so also check the draft in the
   WhatsApp Manager Flow editor.
5. **Publish** only after reviewing: a published Flow cannot be edited, only replaced.
   Publish through the YCloud dashboard, or `POST /v2/whatsapp/flows/{id}/publish` (there is no
   publish wrapper in the codebase for an existing draft).
6. **Set `YCLOUD_PATIENT_INTAKE_FLOW_ID`** in the secret and redeploy.

### Meta rules that already bit us

- Flow names must be unique inside the WABA (`4016019`). Each draft is named
  `Datos de paciente YYYYMMDD-HHMMSS`; two requests in the same second still collide.
- The layout must be `SingleColumnLayout` > `Form`; a bare `Form` is rejected.
- Embedded image: at most 300 KB once base64-encoded (the logo is about 198 KB).
- Dropdown label at most 20 characters, option title at most 30, at most 200 options.
- `If` blocks may nest (up to 3 levels from Flow JSON 4.0; the Flow uses 6.2). How an unselected
  dropdown evaluates inside an `If` is **unverified**; the plan condition also checks `!= ''`.
- Orphan drafts from earlier attempts exist in the first account (`4672565303067581` without the
  plan field, `1004024948763559` invalid). They can be deleted in WhatsApp Manager.

## Part 2 - Automatic reminder templates

Templates are created in the provider account, not by this application: the YCloud client only
**sends** templates (`send_template`); there is no creation call (**unverified** whether YCloud's
API can create them with buttons). Create them in the YCloud dashboard or WhatsApp Manager, category
`UTILITY`, language `es_AR`, using the sample values `Sofía` / `jueves 8 de octubre` / `10:30`.
Template names must match these settings (defaults shown):

| Template | Setting | Variables | Buttons (quick replies unless noted) |
| --- | --- | --- | --- |
| `recordatorio_turno_confirmar` | `APPOINTMENT_REMINDERS_CONFIRMATION_TEMPLATE_NAME` | `{{1}}` name, `{{2}}` date, `{{3}}` time | `0` Confirmar turno |
| `recordatorio_turno_sin_confirmar` | `APPOINTMENT_REMINDERS_UNCONFIRMED_TEMPLATE_NAME` | `{{1}}` name, `{{2}}` date, `{{3}}` time | `0` Confirmar turno, `1` Reprogramar turno |
| `recordatorio_turno_ubicacion` | `APPOINTMENT_REMINDERS_LOCATION_TEMPLATE_NAME` | `{{1}}` name, `{{2}}` time | `0` Cómo llegar (quick reply; the app answers with the clinic location) |
| `solicitud_resena_google` | `APPOINTMENT_REMINDERS_REVIEW_TEMPLATE_NAME` | `{{1}}` name | `0` Opinar (URL button, static review link), `1` No recibir más (quick reply) |

Bodies of the confirm and unconfirmed templates are in
[appointment-reminders-runbook.md](appointment-reminders-runbook.md#template-definitions-metaycloud).
The other two, as seen in a delivered message (copy the review URL from the old account):

```text
recordatorio_turno_ubicacion
Hola {{1}}, te esperamos hoy a las {{2}} hs en Smiling Pilar. Si necesitás la ubicación, tocá el botón.

solicitud_resena_google
Hola {{1}}, gracias por elegirnos para tu atención en Smiling Pilar. Tu opinión nos ayuda a mejorar. ¿Nos dejás una reseña en Google?
```

Rules: a new or edited template goes through Meta review (up to about 24 hours), so create all four
and wait for approval before enabling `APPOINTMENT_REMINDERS_ENABLED`. Button payloads are supplied
by the application at send time, so the template buttons carry none. Follow the staged one-number
test in the reminders runbook before enabling for everyone.

## Checklist for a new number

- [ ] Meta business verified for the WABA
- [ ] Secret updated with that WABA's `YCLOUD_*` values; stack redeployed
- [ ] Intake draft created, previewed, published; `YCLOUD_PATIENT_INTAKE_FLOW_ID` set
- [ ] Four templates created and approved; names match the settings
- [ ] Staged reminder test on one phone before enabling reminders
