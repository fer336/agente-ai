"""Raw-JSON <-> domain-entity mapping for Dentalink responses (PRD.md §27).

Dentalink's documented inconsistencies (PRD.md §27.6) are isolated here,
never leaked past this module into `app/domain` or `app/application`:

- `/v5/agendas` uses `id_profesional`, while creating a cita uses
  `id_dentista` — the same underlying professional id, different field name
  depending on the endpoint. Every reader below accepts both.
- The professionals endpoint mixes `dentista`/`profesional` terminology
  across API doc versions.

UNVERIFIED against live Dentalink responses — no live credentials exist in
this environment (see this change's report). PRD.md §27.1/§27.2 document
the endpoint paths and the *filter* field names with certainty; the exact
JSON *response* shape below is a best-effort mapping built from those same
field names (the most conservative assumption available), not a confirmed
schema. Confirm every field name against real Dentalink payloads before
production use.
"""

from collections.abc import Collection
from datetime import datetime, timedelta, tzinfo

from app.domain.entities.agreement import Agreement
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty
from app.domain.entities.treatment import Treatment
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.dentalink.exceptions import DentalinkInvalidResponseError

#: This clinic's Dentalink account is Argentine (confirmed against a live
#: account 2026-09-04 — see `patient_gateway.py`'s own module docstring for
#: the matching DNI-vs-RUT confirmation), not Chilean despite Dentalink
#: itself being a Chilean platform. A `celular`/`telefono` value with no
#: explicit country code (confirmed real shape, e.g. "1162436577" — area
#: code + subscriber number, no leading 0/15) is assumed local Argentine and
#: prefixed with "549" (country code "54" + the "9" mobile-number marker
#: Argentine E.164/WhatsApp numbers require) so it becomes a valid E.164
#: `PhoneNumber`. A value that already starts with "+" or already carries
#: the "54" prefix is left as-is — this does NOT insert a missing "9"
#: marker into an already-54-prefixed number lacking one, since that shape
#: was not observed in the confirmed live payloads.
_ARGENTINA_COUNTRY_CODE = "54"
_ARGENTINA_MOBILE_PREFIX = "549"


def professional_from_dentista(raw: dict[str, object]) -> Professional:
    """Confirmed against a live Dentalink account (2026-09-04): `/v1/dentistas`
    splits the name into `nombre`/`apellidos`, same as `/v1/pacientes` — see
    `patient_from_paciente`'s identical concatenation below.
    """
    professional_id = raw.get("id_dentista", raw.get("id_profesional", raw.get("id")))
    if professional_id is None:
        raise DentalinkInvalidResponseError("dentista record is missing an id")
    nombre = str(raw.get("nombre", "")).strip()
    apellidos = str(raw.get("apellidos", "")).strip()
    return Professional(
        id=str(professional_id),
        full_name=f"{nombre} {apellidos}".strip(),
        specialty_id=_optional_str(raw.get("id_especialidad")),
    )


def slot_from_agenda(
    raw: dict[str, object], *, default_duration_minutes: int, timezone: tzinfo
) -> AppointmentSlot:
    professional_id = raw.get("id_profesional", raw.get("id_dentista"))
    if professional_id is None:
        raise DentalinkInvalidResponseError("agenda slot is missing id_profesional/id_dentista")
    if "fecha" not in raw or "hora_inicio" not in raw:
        raise DentalinkInvalidResponseError("agenda slot is missing fecha/hora_inicio")

    start = _parse_datetime(str(raw["fecha"]), str(raw["hora_inicio"]), timezone)
    duration_minutes = int(str(raw.get("duracion", default_duration_minutes)))
    end = start + timedelta(minutes=duration_minutes)

    slot_id = raw.get("id", f"{professional_id}-{start.isoformat()}")
    return AppointmentSlot(
        id=str(slot_id),
        professional_id=str(professional_id),
        specialty_id=_optional_str(raw.get("id_especialidad")) or "",
        time_range=DateTimeRange(start, end),
    )


def appointment_from_cita(
    raw: dict[str, object], *, cancelled_state_ids: Collection[str] | None, timezone: tzinfo
) -> Appointment:
    if "id" not in raw:
        raise DentalinkInvalidResponseError("cita record is missing id")

    professional_id = raw.get("id_dentista", raw.get("id_profesional", ""))
    duration_minutes = int(str(raw.get("duracion", 30)))
    start = _parse_datetime(
        str(raw.get("fecha", "")), str(raw.get("hora_inicio", "00:00")), timezone
    )
    slot = AppointmentSlot(
        id=str(raw.get("id_sesion", raw["id"])),
        professional_id=str(professional_id),
        specialty_id=_optional_str(raw.get("id_especialidad")) or "",
        time_range=DateTimeRange(start, start + timedelta(minutes=duration_minutes)),
    )
    id_estado = _optional_str(raw.get("id_estado"))
    # Every `anulacion == 1` state counts here, not just the one this
    # account is allowed to PUT (`resolve_cancellation_state_id`, used only
    # to cancel via our own API call) — a cita anulada through some other
    # channel (Dentalink's own portal/WhatsApp integration, seen live using
    # states we can never write ourselves) must still show as cancelled.
    is_cancelled = (
        cancelled_state_ids is not None
        and id_estado is not None
        and id_estado in cancelled_state_ids
    )
    status = "cancelled" if is_cancelled else "confirmed"
    return Appointment(
        id=AppointmentId(str(raw["id"])),
        patient_id=str(raw.get("id_paciente", "")),
        slot=slot,
        status=status,
    )


def patient_from_paciente(raw: dict[str, object]) -> Patient:
    """Maps a raw `/v1/pacientes` record to the domain `Patient`.

    `Patient.dni` carries Dentalink's `rut` here (see
    `DentalinkPatientGateway`'s module docstring for why the field keeps
    its existing PRD name rather than being renamed project-wide).
    """
    patient_id = raw.get("id")
    if patient_id is None:
        raise DentalinkInvalidResponseError("paciente record is missing an id")

    nombre = str(raw.get("nombre", "")).strip()
    apellidos = str(raw.get("apellidos", "")).strip()
    full_name = f"{nombre} {apellidos}".strip()

    raw_phone = raw.get("celular") or raw.get("telefono")
    if not raw_phone:
        raise DentalinkInvalidResponseError(f"paciente {patient_id} record has no celular/telefono")
    phone = _phone_from_dentalink(str(raw_phone))

    rut = raw.get("rut")
    return Patient(
        id=str(patient_id),
        full_name=full_name,
        phone=phone,
        dni=str(rut) if rut is not None else None,
    )


def _phone_from_dentalink(raw_value: str) -> PhoneNumber:
    digits = "".join(char for char in raw_value if char.isdigit())
    if not digits:
        raise DentalinkInvalidResponseError(f"unparseable phone number: {raw_value!r}")

    if raw_value.strip().startswith("+") or digits.startswith(_ARGENTINA_COUNTRY_CODE):
        candidate = f"+{digits}"
    else:
        candidate = f"+{_ARGENTINA_MOBILE_PREFIX}{digits}"

    try:
        return PhoneNumber(candidate)
    except ValueError as exc:
        raise DentalinkInvalidResponseError(f"unparseable phone number: {raw_value!r}") from exc


def agreement_from_convenio(raw: dict[str, object]) -> Agreement:
    agreement_id = raw.get("id", raw.get("id_convenio"))
    if agreement_id is None:
        raise DentalinkInvalidResponseError("convenio record is missing an id")
    return Agreement(id=str(agreement_id), name=str(raw.get("nombre", "")))


def specialty_from_especialidad(raw: dict[str, object]) -> Specialty:
    specialty_id = raw.get("id", raw.get("id_especialidad"))
    if specialty_id is None:
        raise DentalinkInvalidResponseError("especialidad record is missing an id")
    return Specialty(id=str(specialty_id), name=str(raw.get("nombre", "")))


def treatment_from_tratamiento(raw: dict[str, object]) -> Treatment:
    """Confirmed against a live Dentalink account (2026-09-04):
    `/v1/pacientes/{id}/tratamientos` returns `finalizado` as `0`/`1`
    (never a bool literal) and numeric money fields (`total`/`abonado`/
    `deuda`) as JSON numbers.
    """
    treatment_id = raw.get("id")
    patient_id = raw.get("id_paciente")
    if treatment_id is None or patient_id is None:
        raise DentalinkInvalidResponseError("tratamiento record is missing id/id_paciente")
    return Treatment(
        id=str(treatment_id),
        patient_id=str(patient_id),
        name=str(raw.get("nombre", "")),
        is_finished=raw.get("finalizado") == 1,
        total=_as_float(raw.get("total")),
        paid=_as_float(raw.get("abonado")),
        debt=_as_float(raw.get("deuda")),
    )


def _is_cancellation_estado(estado: dict[str, object]) -> bool:
    """Shared anulación/cancelación signal for both resolvers below.

    Confirmed against a live Dentalink account (2026-09-04): each estado
    carries a real `anulacion` flag (`1` for a cancellation state, `0`
    otherwise), used here as the primary signal. Falls back to the old
    name-based match (case/accent-insensitive substring against
    "anula"/"cancela") only for an estado that omits the flag entirely —
    defensive, in case another account's API version doesn't send it.
    """
    if "anulacion" in estado:
        return estado.get("anulacion") == 1
    name = str(estado.get("nombre", "")).casefold()
    return "anula" in name or "cancela" in name


def resolve_cancellation_state_id(estados: list[dict[str, object]]) -> str | None:
    """Finds the ONE anulación state id that is safe for US to PUT (PRD.md §27.5).

    Never hardcoded — PRD.md explicitly forbids it. A candidate with
    `uso_interno == 1` is always skipped: seen live (2026-09-08) this
    account has SEVEN `anulacion == 1` states, and every one of them except
    plain "Anulado" (`uso_interno == 0`) is reserved for Dentalink's own
    automations ("Anulado por pcte. via Whatsapp", "Anulado por
    reprogramación", ...) — PUTting one of those ourselves fails with a
    400: "El estado enviado esta reservado para uso interno del software."
    Iteration order isn't guaranteed, so without this filter the first
    `anulacion == 1` match found can easily be one of the reserved ones.

    Use this ONLY for the `id_estado` we write via `cancel_appointment` —
    for "is this existing cita cancelled", use
    `resolve_cancellation_state_ids` (plural) instead, since a cita
    cancelled through another channel can carry any of the reserved ids
    this function deliberately excludes.
    """
    for estado in estados:
        if not _is_cancellation_estado(estado) or estado.get("uso_interno") == 1:
            continue
        state_id = estado.get("id")
        if state_id is not None:
            return str(state_id)
    return None


def resolve_cancellation_state_ids(estados: list[dict[str, object]]) -> frozenset[str]:
    """Finds EVERY anulación state id, for detecting an already-cancelled cita.

    Unlike `resolve_cancellation_state_id` (singular), this does NOT filter
    out `uso_interno == 1` states — a cita anulada through some other
    channel (Dentalink's own portal/WhatsApp integration) can land on any
    of them, and it must still show as cancelled to us even though we could
    never write that same id ourselves.
    """
    return frozenset(
        str(estado["id"])
        for estado in estados
        if _is_cancellation_estado(estado) and "id" in estado
    )


def _parse_datetime(fecha: str, hora: str, timezone: tzinfo) -> datetime:
    """Parses Dentalink's `fecha` + `hora_inicio` pair, in either format it sends.

    The result is stamped with the clinic's timezone. Dentalink sends bare
    wall-clock times with no offset — confirmed by its own 500 trace, which
    showed it building dates with `America/Argentina/...`. Returning them
    naive made `DateTimeRange.contains` raise `TypeError: can't compare
    offset-naive and offset-aware datetimes` against the UTC window
    `_offer_slots` builds, and would have booked appointments three hours
    off, since `create_appointment` writes `.date()` and `%H:%M` straight
    back to Dentalink. Stamping (not converting) is the point: 10:30 in the
    payload is 10:30 at the clinic, and must read back as 10:30.

    The docs' examples are ISO (`2026-08-15`), but a real account's
    `/v5/agendas` answers day-first (`07/09/2026`) — which
    `datetime.fromisoformat` rejects, and which took every booking down
    in production with `DentalinkInvalidResponseError`. Both are accepted
    here rather than picking one, since the same helper reads `/v1/citas`
    too and the two endpoints are not known to agree.

    Day-first, not month-first: Dentalink is Chilean (HealthAtom), and the
    production sample `07/09/2026` was a slot for the day after 2026-09-06
    — September 7th, which month-first would have read as a date two
    months in the past. Guessing per-value from whether a component
    exceeds 12 is NOT an option: it would silently mis-date every
    unambiguous day (`07/09` -> July 9th) while getting `13/09` right.
    """
    hora_normalized = hora if len(hora) > 5 else f"{hora}:00"
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(f"{fecha}T{hora_normalized}")
    except ValueError:
        try:
            parsed = datetime.strptime(f"{fecha} {hora_normalized}", "%d/%m/%Y %H:%M:%S")
        except ValueError as exc:
            raise DentalinkInvalidResponseError(
                f"could not parse Dentalink fecha/hora as a datetime: {fecha!r} {hora!r}"
            ) from exc
    # An offset Dentalink sent itself wins over the configured default.
    return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def full_names_match(a: str, b: str) -> bool:
    """True when both names contain the same words, in any order.

    Patients often type their name "Apellido Nombre" instead of the
    "Nombre Apellido" order Dentalink stores it in, or the reverse — seen
    live as a real cause of "no te encontramos" for someone who genuinely
    is in the system. An exact ordered-string comparison rejected that
    case even though the DNI lookup had already narrowed the candidate
    down to exactly one real patient. Comparing word sets instead of the
    raw string still requires knowing every word of the real name, just
    not the order they come in — the DNI match still does the actual
    identity gatekeeping (PRD.md §32).
    """
    return sorted(a.strip().casefold().split()) == sorted(b.strip().casefold().split())


def _as_float(value: object) -> float:
    return float(str(value)) if value is not None else 0.0


def as_list(raw: object) -> list[dict[str, object]]:
    """Unwraps a Dentalink list response, tolerating a `{"data": [...]}` envelope."""
    if isinstance(raw, dict) and "data" in raw:
        raw = raw["data"]
    if not isinstance(raw, list):
        raise DentalinkInvalidResponseError("expected a Dentalink list response")
    return raw


def as_dict(raw: object) -> dict[str, object]:
    """Unwraps a Dentalink object response, tolerating a `{"data": {...}}` envelope."""
    if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], dict):
        return raw["data"]
    if not isinstance(raw, dict):
        raise DentalinkInvalidResponseError("expected a Dentalink object response")
    return raw
