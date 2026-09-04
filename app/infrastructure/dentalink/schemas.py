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

from datetime import datetime, timedelta

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


def slot_from_agenda(raw: dict[str, object], *, default_duration_minutes: int) -> AppointmentSlot:
    professional_id = raw.get("id_profesional", raw.get("id_dentista"))
    if professional_id is None:
        raise DentalinkInvalidResponseError("agenda slot is missing id_profesional/id_dentista")
    if "fecha" not in raw or "hora_inicio" not in raw:
        raise DentalinkInvalidResponseError("agenda slot is missing fecha/hora_inicio")

    start = _parse_datetime(str(raw["fecha"]), str(raw["hora_inicio"]))
    duration_minutes = int(str(raw.get("duracion", default_duration_minutes)))
    end = start + timedelta(minutes=duration_minutes)

    slot_id = raw.get("id", f"{professional_id}-{start.isoformat()}")
    return AppointmentSlot(
        id=str(slot_id),
        professional_id=str(professional_id),
        specialty_id=_optional_str(raw.get("id_especialidad")) or "",
        time_range=DateTimeRange(start, end),
    )


def appointment_from_cita(raw: dict[str, object], *, cancelled_state_id: str | None) -> Appointment:
    if "id" not in raw:
        raise DentalinkInvalidResponseError("cita record is missing id")

    professional_id = raw.get("id_dentista", raw.get("id_profesional", ""))
    duration_minutes = int(str(raw.get("duracion", 30)))
    start = _parse_datetime(str(raw.get("fecha", "")), str(raw.get("hora_inicio", "00:00")))
    slot = AppointmentSlot(
        id=str(raw.get("id_sesion", raw["id"])),
        professional_id=str(professional_id),
        specialty_id=_optional_str(raw.get("id_especialidad")) or "",
        time_range=DateTimeRange(start, start + timedelta(minutes=duration_minutes)),
    )
    id_estado = _optional_str(raw.get("id_estado"))
    is_cancelled = cancelled_state_id is not None and id_estado == cancelled_state_id
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
        raise DentalinkInvalidResponseError(
            f"paciente {patient_id} record has no celular/telefono"
        )
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
        raise DentalinkInvalidResponseError(
            f"unparseable phone number: {raw_value!r}"
        ) from exc


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


def resolve_cancellation_state_id(estados: list[dict[str, object]]) -> str | None:
    """Finds the anulación/cancelación state id among `GET /v1/citas/estados` (PRD.md §27.5).

    Never hardcoded — PRD.md explicitly forbids it. Confirmed against a live
    Dentalink account (2026-09-04): each estado carries a real `anulacion`
    flag (`1` for a cancellation state, `0` otherwise), used here as the
    primary signal. Falls back to the old name-based match
    (case/accent-insensitive substring against "anula"/"cancela") only for
    an estado that omits the flag entirely — defensive, in case another
    account's API version doesn't send it.
    """
    for estado in estados:
        if "anulacion" in estado:
            is_cancellation = estado.get("anulacion") == 1
        else:
            name = str(estado.get("nombre", "")).casefold()
            is_cancellation = "anula" in name or "cancela" in name
        if is_cancellation:
            state_id = estado.get("id")
            if state_id is not None:
                return str(state_id)
    return None


def _parse_datetime(fecha: str, hora: str) -> datetime:
    hora_normalized = hora if len(hora) > 5 else f"{hora}:00"
    try:
        return datetime.fromisoformat(f"{fecha}T{hora_normalized}")
    except ValueError as exc:
        raise DentalinkInvalidResponseError(
            f"could not parse Dentalink fecha/hora as a datetime: {fecha!r} {hora!r}"
        ) from exc


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


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
