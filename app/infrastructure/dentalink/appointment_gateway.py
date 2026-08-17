from datetime import timedelta

from app.application.errors.error_types import (
    APPOINTMENT_NOT_FOUND,
    DENTALINK_AUTH_ERROR,
    DENTALINK_INVALID_RESPONSE,
    DENTALINK_TIMEOUT,
)
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.entities.professional import Professional
from app.domain.exceptions.errors import AppointmentNotFoundError
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.dentalink.client import DentalinkClient, build_filter_params
from app.infrastructure.dentalink.exceptions import (
    DentalinkAPIError,
    DentalinkAuthError,
    DentalinkInvalidResponseError,
    DentalinkTimeoutError,
)
from app.infrastructure.dentalink.schemas import (
    appointment_from_cita,
    as_dict,
    as_list,
    professional_from_dentista,
    resolve_cancellation_state_id,
    slot_from_agenda,
)
from app.infrastructure.observability.tool_tracing import traced_call

_PROVIDER = "dentalink"


def _http_status_of(exc: Exception) -> str | None:
    """Maps a Dentalink exception to `tool_executions.http_status`.

    Not always a numeric code — PRD.md §41's own example uses the
    non-numeric value `timeout` — so `"timeout"`/`"auth_error"` are as
    valid here as a literal status code string. `AppointmentNotFoundError`
    is included because `reschedule_appointment`/`cancel_appointment`
    translate a Dentalink 404 into it BEFORE it would otherwise reach
    `traced_call` — losing that original status here would make a 404 look
    like an untyped failure in the trace.
    """
    if isinstance(exc, DentalinkAPIError):
        return str(exc.status_code)
    if isinstance(exc, DentalinkTimeoutError):
        return "timeout"
    if isinstance(exc, DentalinkAuthError):
        return "auth_error"
    if isinstance(exc, AppointmentNotFoundError):
        return "404"
    return None


def _error_type_of(exc: Exception) -> str:
    """Maps a Dentalink exception to PRD.md §43's `errors.error_type` catalog.

    `AppointmentNotFoundError` maps to the BUSINESS error `appointment_not_found`
    (§43.1), not an integration error — a translated 404 means the
    appointment genuinely doesn't exist, not that Dentalink itself
    misbehaved. A generic `DentalinkAPIError` (any non-timeout/auth/404
    non-2xx response) is classified as `dentalink_invalid_response` — §43.2
    has no separate "other 4xx/5xx" bucket, and an unexpected response body
    is the closest existing fit.
    """
    if isinstance(exc, DentalinkTimeoutError):
        return DENTALINK_TIMEOUT
    if isinstance(exc, DentalinkAuthError):
        return DENTALINK_AUTH_ERROR
    if isinstance(exc, AppointmentNotFoundError):
        return APPOINTMENT_NOT_FOUND
    return DENTALINK_INVALID_RESPONSE

#: Hard cap on how many per-day `/v5/agendas` calls one `search_availability`
#: call may issue. PRD.md §27.2's documented filter takes a single `fecha`,
#: not a range, so a multi-day `date_range` is served by iterating one
#: request per calendar day — this cap guards against a pathologically wide
#: `date_range` (e.g. a caller-supplied multi-year window) turning into an
#: unbounded number of HTTP calls. 60 days comfortably covers the LangGraph
#: demo node's 30-day search window.
_MAX_SEARCH_AVAILABILITY_DAYS = 60


class DentalinkAppointmentGateway:
    """`DentalinkClient`-based real implementation of the `AppointmentGateway` port.

    UNVERIFIED against a live Dentalink account (no live credentials in this
    environment). Endpoint paths and request field names follow PRD.md
    §27.1-§27.5's documented contract exactly; response field names are a
    best-effort mapping (see `schemas.py`'s module docstring). Not wired
    into DI yet (see `app.api.dependencies.gateways`, which still binds
    `FakeDentalinkGateway` by default, matching every other gateway's
    fake-by-default swap-point convention in this codebase).
    """

    def __init__(
        self,
        client: DentalinkClient,
        *,
        default_branch_id: str,
        default_chair_id: str,
        default_duration_minutes: int,
    ) -> None:
        self._client = client
        self._default_branch_id = default_branch_id
        self._default_chair_id = default_chair_id
        self._default_duration_minutes = default_duration_minutes
        self._cancellation_state_id: str | None = None
        self._cancellation_state_resolved = False

    async def search_availability(
        self,
        specialty_id: str | None,
        professional_id: str | None,
        date_range: DateTimeRange,
    ) -> list[AppointmentSlot]:
        async def _call() -> list[AppointmentSlot]:
            slots: list[AppointmentSlot] = []
            day = date_range.start.date()
            # `date_range` is a half-open [start, end) interval — if `end`
            # lands exactly at midnight, that day itself has no included
            # moments, so the last day to query is the one just before it.
            last_day = (date_range.end - timedelta(microseconds=1)).date()
            days_queried = 0
            while day <= last_day and days_queried < _MAX_SEARCH_AVAILABILITY_DAYS:
                filters: dict[str, object] = {
                    "id_sucursal": self._default_branch_id,
                    "fecha": day.isoformat(),
                    "duracion": self._default_duration_minutes,
                }
                if professional_id is not None:
                    filters["id_profesional"] = professional_id

                raw_slots = await self._client.get(
                    "/v5/agendas", params=build_filter_params(filters)
                )
                for raw_slot in as_list(raw_slots):
                    slot = slot_from_agenda(
                        raw_slot, default_duration_minutes=self._default_duration_minutes
                    )
                    if specialty_id is not None and slot.specialty_id != specialty_id:
                        continue
                    if date_range.contains(slot.time_range.start):
                        slots.append(slot)

                day += timedelta(days=1)
                days_queried += 1

            return slots

        return await traced_call(
            tool_name="SearchAvailabilityTool",
            provider=_PROVIDER,
            operation="search_availability",
            request_summary=f"specialty_id={specialty_id} professional_id={professional_id}",
            call=_call,
            response_summary=lambda slots: f"{len(slots)} slots",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def list_professionals(self, specialty_id: str | None = None) -> list[Professional]:
        async def _call() -> list[Professional]:
            raw_dentistas = await self._client.get("/v1/dentistas")
            professionals = [professional_from_dentista(raw) for raw in as_list(raw_dentistas)]
            if specialty_id is None:
                return professionals
            return [p for p in professionals if p.specialty_id == specialty_id]

        return await traced_call(
            tool_name="ListProfessionalsTool",
            provider=_PROVIDER,
            operation="list_professionals",
            request_summary=f"specialty_id={specialty_id}",
            call=_call,
            response_summary=lambda professionals: f"{len(professionals)} professionals",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def get_patient_appointments(self, patient_id: str) -> list[Appointment]:
        async def _call() -> list[Appointment]:
            cancelled_state_id = await self._resolve_cancellation_state_id()
            raw_citas = await self._client.get(f"/v1/pacientes/{patient_id}/citas")
            return [
                appointment_from_cita(raw, cancelled_state_id=cancelled_state_id)
                for raw in as_list(raw_citas)
            ]

        return await traced_call(
            tool_name="GetPatientAppointmentsTool",
            provider=_PROVIDER,
            operation="get_patient_appointments",
            request_summary=f"patient_id={patient_id}",
            call=_call,
            response_summary=lambda appointments: f"{len(appointments)} appointments",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def create_appointment(
        self,
        patient: Patient,
        slot: AppointmentSlot,
        idempotency_key: str,
    ) -> Appointment:
        # `idempotency_key` is not sent to Dentalink — it has no idempotency
        # support at this endpoint. Deduplication happens one layer up, via
        # the application's own `appointment_actions.idempotency_key`
        # unique constraint (PRD.md §17.2), before this gateway is ever
        # called a second time for the same operation.
        async def _call() -> Appointment:
            duration_minutes = int(slot.time_range.duration().total_seconds() // 60)
            payload = {
                "id_dentista": slot.professional_id,
                "id_especialidad": slot.specialty_id,
                "id_sucursal": self._default_branch_id,
                "id_sillon": self._default_chair_id,
                "id_paciente": patient.id,
                "fecha": slot.time_range.start.date().isoformat(),
                "hora_inicio": slot.time_range.start.strftime("%H:%M"),
                "duracion": duration_minutes,
            }
            raw = await self._client.post("/v1/citas/", json=payload)
            return appointment_from_cita(as_dict(raw), cancelled_state_id=None)

        return await traced_call(
            tool_name="CreateAppointmentTool",
            provider=_PROVIDER,
            operation="create_appointment",
            request_summary=(
                f"professional_id={slot.professional_id} specialty_id={slot.specialty_id}"
            ),
            call=_call,
            response_summary=lambda appointment: f"appointment_id={appointment.id}",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot: AppointmentSlot,
        idempotency_key: str,
    ) -> Appointment:
        async def _call() -> Appointment:
            # PRD.md §27.4: this endpoint calls the appointment identifier
            # `id_sesion`, not `id_cita` — isolated here, never leaked to callers.
            duration_minutes = int(new_slot.time_range.duration().total_seconds() // 60)
            payload = {
                "id_sesion": appointment_id,
                "fecha": new_slot.time_range.start.date().isoformat(),
                "hora_inicio": new_slot.time_range.start.strftime("%H:%M"),
                "duracion": duration_minutes,
            }
            try:
                raw = await self._client.post("/v1/citas/changeDate", json=payload)
            except DentalinkAPIError as exc:
                if exc.status_code == 404:
                    raise AppointmentNotFoundError(appointment_id) from exc
                raise
            return appointment_from_cita(as_dict(raw), cancelled_state_id=None)

        return await traced_call(
            tool_name="RescheduleAppointmentTool",
            provider=_PROVIDER,
            operation="reschedule_appointment",
            request_summary=f"professional_id={new_slot.professional_id}",
            call=_call,
            response_summary=lambda appointment: f"appointment_id={appointment.id}",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def cancel_appointment(self, appointment_id: str, idempotency_key: str) -> None:
        async def _call() -> None:
            cancelled_state_id = await self._resolve_cancellation_state_id()
            if cancelled_state_id is None:
                raise DentalinkInvalidResponseError(
                    "could not resolve a cancellation id_estado from GET /v1/citas/estados"
                )
            try:
                await self._client.put(
                    f"/v1/citas/{appointment_id}", json={"id_estado": cancelled_state_id}
                )
            except DentalinkAPIError as exc:
                if exc.status_code == 404:
                    raise AppointmentNotFoundError(appointment_id) from exc
                raise

        await traced_call(
            tool_name="CancelAppointmentTool",
            provider=_PROVIDER,
            operation="cancel_appointment",
            request_summary=f"appointment_id={appointment_id}",
            call=_call,
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def _resolve_cancellation_state_id(self) -> str | None:
        if not self._cancellation_state_resolved:
            raw_estados = await self._client.get("/v1/citas/estados")
            self._cancellation_state_id = resolve_cancellation_state_id(as_list(raw_estados))
            self._cancellation_state_resolved = True
        return self._cancellation_state_id


