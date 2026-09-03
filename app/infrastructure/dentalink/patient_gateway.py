"""`DentalinkClient`-based real implementation of the `PatientGateway` port.

Endpoint paths and field names for `/v1/pacientes` (list/filter, create)
follow Dentalink's own public API reference
(https://api.dentalink.healthatom.com/docs/, confirmed 2026-09-02) — this
module is new territory PRD.md never covered (no patient *creation*
endpoint anywhere in PRD.md §27), so unlike
`DentalinkAppointmentGateway`/`DentalinkAgreementGateway` it is not a
PRD-guess translation. It is still UNVERIFIED against a live Dentalink
account (no live credentials in this environment) — confirm field names
against real responses before production use.

Naming note: this clinic is Argentine and identifies patients by DNI
(confirmed 2026-09-03), not by a Chilean RUT — the `Dni` value object
(`app.domain.value_objects.dni.Dni`) only validates that the input is a
well-formed Argentine DNI (7-8 digits, no check digit to verify). It does
*not* validate a Chilean RUT checksum, and whether Dentalink's own backend
(a Chilean platform) actually accepts an Argentine-format value in its
`rut` field is UNVERIFIED — this gateway does not pre-empt that question
locally. If Dentalink rejects the value, that surfaces as the normal typed
`DentalinkAPIError`/fail-closed path below, exactly like any other
Dentalink-side rejection. Dentalink's own field name (`rut`, in the JSON
payload and the `q` filter) is unchanged — only the local validation
changed from a RUT checksum to a DNI shape check.
"""

import json

from app.application.errors.error_types import (
    DENTALINK_AUTH_ERROR,
    DENTALINK_INVALID_RESPONSE,
    DENTALINK_TIMEOUT,
    PATIENT_ALREADY_EXISTS,
)
from app.domain.entities.patient import Patient
from app.domain.exceptions.errors import PatientAlreadyExistsError
from app.domain.value_objects.dni import Dni
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.dentalink.client import DentalinkClient
from app.infrastructure.dentalink.exceptions import (
    DentalinkAPIError,
    DentalinkAuthError,
    DentalinkTimeoutError,
)
from app.infrastructure.dentalink.schemas import as_dict, as_list, patient_from_paciente
from app.infrastructure.observability.tool_tracing import traced_call

_PROVIDER = "dentalink"

#: Allow-list of `/v1/pacientes` fields this gateway will ever filter by,
#: and of the operators it will use. Guardrail against filter/query
#: injection: a caller-controlled value (e.g. a patient's own free-text
#: name) can only ever become a JSON *value* inside the `q` filter below,
#: never a JSON *key* or operator — so it can't be used to smuggle in an
#: unintended field or operator. See `_build_q_param`.
_ALLOWED_FILTER_FIELDS = frozenset({"rut", "nombre", "email", "habilitado"})
_ALLOWED_OPERATORS = frozenset({"eq", "neq", "lk"})


def _build_q_param(filters: dict[str, tuple[str, object]]) -> dict[str, str]:
    """Builds Dentalink's `?q={"campo":{"operador":"valor"}}` filter param.

    Always constructed as a Python dict and serialized with `json.dumps` —
    never by string-interpolating a field name, operator, or value into a
    hand-built query string.
    """
    query: dict[str, dict[str, object]] = {}
    for field, (operator, value) in filters.items():
        if field not in _ALLOWED_FILTER_FIELDS:
            raise ValueError(f"Filtering /v1/pacientes by {field!r} is not allowed")
        if operator not in _ALLOWED_OPERATORS:
            raise ValueError(f"Operator {operator!r} is not allowed")
        query[field] = {operator: value}
    return {"q": json.dumps(query, separators=(",", ":"))}


def _split_full_name(full_name: str) -> tuple[str, str]:
    """Best-effort split of a single `full_name` into Dentalink's required
    separate `nombre`/`apellidos` fields (first token vs. the rest)."""
    parts = full_name.strip().split(maxsplit=1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return (parts[0], parts[0]) if parts else ("", "")


def _http_status_of(exc: Exception) -> str | None:
    if isinstance(exc, DentalinkAPIError):
        return str(exc.status_code)
    if isinstance(exc, DentalinkTimeoutError):
        return "timeout"
    if isinstance(exc, DentalinkAuthError):
        return "auth_error"
    if isinstance(exc, PatientAlreadyExistsError):
        return "409"
    return None


def _error_type_of(exc: Exception) -> str:
    if isinstance(exc, DentalinkTimeoutError):
        return DENTALINK_TIMEOUT
    if isinstance(exc, DentalinkAuthError):
        return DENTALINK_AUTH_ERROR
    if isinstance(exc, PatientAlreadyExistsError):
        return PATIENT_ALREADY_EXISTS
    return DENTALINK_INVALID_RESPONSE


class DentalinkPatientGateway:
    """Real implementation of the `PatientGateway` port (see module docstring).

    Not wired into DI yet — `app.api.dependencies.gateways.get_patient_gateway`
    still returns `FakePatientGateway` by default, matching every other
    gateway's fake-by-default swap-point convention in this codebase.
    """

    def __init__(self, client: DentalinkClient) -> None:
        self._client = client

    async def find_patient(self, full_name: str, dni: str) -> Patient | None:
        async def _call() -> Patient | None:
            try:
                validated_dni = Dni(dni)
            except ValueError:
                # A string that isn't even a well-formed DNI can never
                # match a real Dentalink record, so this is a confident
                # "not found", not an error.
                return None
            candidate = await self._find_by_rut(validated_dni)
            if candidate is None:
                return None
            if candidate.full_name.strip().casefold() != full_name.strip().casefold():
                return None
            return candidate

        return await traced_call(
            tool_name="FindPatientTool",
            provider=_PROVIDER,
            operation="find_patient",
            request_summary=f"dni_len={len(dni)}",
            call=_call,
            response_summary=lambda patient: (
                f"patient_id={patient.id}" if patient else "not_found"
            ),
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def create_patient(self, full_name: str, dni: str, phone: PhoneNumber) -> Patient:
        """Creates a patient, tied to the requesting contact's own `phone`.

        Guardrails, in order: (1) DNI shape is validated before any HTTP
        call; (2) a DNI already on file is a typed `PatientAlreadyExistsError`
        conflict, never a silent duplicate create; (3) `phone` is required —
        it must be the phone number of the contact who asked for this, never
        an arbitrary caller-supplied value, so the created record is always
        provably tied to its requester (deeper enforcement — persisting and
        checking a contact->patient link before subsequent operations — is a
        separate follow-up, see this change's report); (4) any Dentalink
        failure surfaces as a typed exception, never a false success.
        """

        async def _call() -> Patient:
            validated_dni = Dni(dni)  # raises ValueError before any HTTP call on a bad shape

            existing = await self._find_by_rut(validated_dni)
            if existing is not None:
                raise PatientAlreadyExistsError(validated_dni.value, existing.id)

            nombre, apellidos = _split_full_name(full_name)
            payload: dict[str, object] = {
                "rut": validated_dni.value,
                "nombre": nombre,
                "apellidos": apellidos,
                "celular": phone.value.lstrip("+"),
            }
            raw = await self._client.post("/v1/pacientes", json=payload)
            created = as_dict(raw)
            patient_id = created.get("id")
            if patient_id is None:
                raise DentalinkAPIError(200, "Dentalink create-patient response is missing an id")

            # Built from already-validated inputs rather than round-tripped
            # through `patient_from_paciente` — sidesteps Dentalink's create
            # response not necessarily echoing back a parseable phone.
            return Patient(
                id=str(patient_id),
                full_name=full_name.strip(),
                phone=phone,
                dni=validated_dni.value,
            )

        return await traced_call(
            tool_name="CreatePatientTool",
            provider=_PROVIDER,
            operation="create_patient",
            request_summary=f"dni_len={len(dni)}",
            call=_call,
            response_summary=lambda patient: f"patient_id={patient.id}",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def _find_by_rut(self, dni: Dni) -> Patient | None:
        params = _build_q_param({"rut": ("eq", dni.value)})
        raw = await self._client.get("/v1/pacientes", params=params)
        candidates = [patient_from_paciente(r) for r in as_list(raw)]
        return candidates[0] if candidates else None
