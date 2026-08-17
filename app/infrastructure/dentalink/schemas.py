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
from app.domain.entities.professional import Professional
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.dentalink.exceptions import DentalinkInvalidResponseError


def professional_from_dentista(raw: dict[str, object]) -> Professional:
    professional_id = raw.get("id_dentista", raw.get("id_profesional", raw.get("id")))
    if professional_id is None:
        raise DentalinkInvalidResponseError("dentista record is missing an id")
    return Professional(
        id=str(professional_id),
        full_name=str(raw.get("nombre", "")),
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


def agreement_from_convenio(raw: dict[str, object]) -> Agreement:
    agreement_id = raw.get("id", raw.get("id_convenio"))
    if agreement_id is None:
        raise DentalinkInvalidResponseError("convenio record is missing an id")
    return Agreement(id=str(agreement_id), name=str(raw.get("nombre", "")))


def resolve_cancellation_state_id(estados: list[dict[str, object]]) -> str | None:
    """Finds the anulación/cancelación state id among `GET /v1/citas/estados` (PRD.md §27.5).

    Never hardcoded — PRD.md explicitly forbids it. Dentalink's estados
    response doesn't have a documented boolean "is this the cancellation
    state" flag, so this matches by name (case/accent-insensitive substring
    match against "anula"/"cancela") — the same best-effort, UNVERIFIED
    approach as the rest of this module.
    """
    for estado in estados:
        name = str(estado.get("nombre", "")).casefold()
        if "anula" in name or "cancela" in name:
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
