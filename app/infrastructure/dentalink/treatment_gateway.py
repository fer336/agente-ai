from app.application.errors.error_types import (
    DENTALINK_AUTH_ERROR,
    DENTALINK_INVALID_RESPONSE,
    DENTALINK_TIMEOUT,
)
from app.domain.entities.treatment import Treatment
from app.infrastructure.dentalink.client import DentalinkClient
from app.infrastructure.dentalink.exceptions import (
    DentalinkAPIError,
    DentalinkAuthError,
    DentalinkTimeoutError,
)
from app.infrastructure.dentalink.schemas import as_list, treatment_from_tratamiento
from app.infrastructure.observability.tool_tracing import traced_call

_PROVIDER = "dentalink"


def _http_status_of(exc: Exception) -> str | None:
    if isinstance(exc, DentalinkAPIError):
        return str(exc.status_code)
    if isinstance(exc, DentalinkTimeoutError):
        return "timeout"
    if isinstance(exc, DentalinkAuthError):
        return "auth_error"
    return None


def _error_type_of(exc: Exception) -> str:
    if isinstance(exc, DentalinkTimeoutError):
        return DENTALINK_TIMEOUT
    if isinstance(exc, DentalinkAuthError):
        return DENTALINK_AUTH_ERROR
    return DENTALINK_INVALID_RESPONSE


class DentalinkTreatmentGateway:
    """`DentalinkClient`-based real implementation of the `TreatmentGateway` port.

    UNVERIFIED endpoint path — `GET /v1/pacientes/{id}/tratamientos` follows
    the same patient-scoped-relationship convention confirmed live for
    `/v1/pacientes/{id}/citas` (`get_patient_appointments`) and
    `/v1/pacientes/{id}/convenios` (`get_patient_agreements`), but this
    specific sub-path was not itself hit against the live account —
    `GET /v1/tratamientos` (the unscoped list) was confirmed instead.
    Confirm before production use.
    """

    def __init__(self, client: DentalinkClient) -> None:
        self._client = client

    async def get_patient_treatments(self, patient_id: str) -> list[Treatment]:
        return await traced_call(
            tool_name="GetPatientTreatmentsTool",
            provider=_PROVIDER,
            operation="get_patient_treatments",
            request_summary=f"patient_id={patient_id}",
            call=lambda: self._get_patient_treatments(patient_id),
            response_summary=lambda treatments: f"{len(treatments)} treatments",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def _get_patient_treatments(self, patient_id: str) -> list[Treatment]:
        raw_tratamientos = await self._client.get(f"/v1/pacientes/{patient_id}/tratamientos")
        return [treatment_from_tratamiento(raw) for raw in as_list(raw_tratamientos)]
