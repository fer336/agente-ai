import logging
import re

from app.domain.entities.agreement import Agreement
from app.domain.exceptions.errors import AgreementAlreadyLinkedError
from app.infrastructure.dentalink.client import DentalinkClient
from app.infrastructure.dentalink.exceptions import DentalinkAPIError
from app.infrastructure.dentalink.schemas import agreement_from_convenio, as_list

logger = logging.getLogger(__name__)

_ALREADY_LINKED_MESSAGE = "ya tiene el convenio"
_LINKED_AGREEMENT_ID = re.compile(r"convenio id\s+(\d+)", re.IGNORECASE)


def _is_already_linked(error: DentalinkAPIError, agreement_id: str) -> bool:
    """True when Dentalink says the patient already has this very agreement.

    Seen in production: `400 {"error": {"message": "Paciente ID 4532 ya tiene el convenio
    ID 6 asociado"}}`. The message names the agreement, which must be the requested one.
    """
    if error.status_code != 400:
        return False
    body = error.body.casefold()
    if _ALREADY_LINKED_MESSAGE not in body:
        return False
    named = _LINKED_AGREEMENT_ID.search(error.body)
    return named is None or named.group(1) == str(agreement_id)


class DentalinkAgreementGateway:
    """`DentalinkClient`-based real implementation of the `AgreementGateway` port.

    UNVERIFIED against a live Dentalink account (no live credentials in this
    environment). Not wired into DI yet — see `DentalinkAppointmentGateway`'s
    docstring for the same swap-point convention.
    """

    def __init__(self, client: DentalinkClient) -> None:
        self._client = client

    async def list_agreements(self) -> list[Agreement]:
        raw_convenios = await self._client.get("/v1/convenios")
        return [agreement_from_convenio(raw) for raw in as_list(raw_convenios)]

    async def find_agreement_by_name(self, name: str) -> Agreement | None:
        # PRD.md §18's flow is client-side matching against the full
        # convenios list — no server-side name-search endpoint is
        # documented in §27.1's table.
        normalized = name.strip().casefold()
        for agreement in await self.list_agreements():
            if agreement.name.strip().casefold() == normalized:
                return agreement
        return None

    async def get_patient_agreements(self, patient_id: str) -> list[Agreement]:
        raw_convenios = await self._client.get(f"/v1/pacientes/{patient_id}/convenios")
        return [agreement_from_convenio(raw) for raw in as_list(raw_convenios)]

    async def link_patient_agreement(self, patient_id: str, agreement_id: str) -> None:
        # The endpoint and the `id_convenio` body field are confirmed by a live Dentalink
        # response (its 400 below). A patient who already has the agreement (a DNI that
        # was already registered, or a retry after a partial failure) is not a failure,
        # but the caller decides how to tell them, so it gets a typed signal.
        try:
            await self._client.post(
                f"/v1/pacientes/{patient_id}/convenios", json={"id_convenio": agreement_id}
            )
        except DentalinkAPIError as exc:
            if not _is_already_linked(exc, agreement_id):
                raise
            logger.info(
                "dentalink.agreement_already_linked patient_id=%s agreement_id=%s",
                patient_id,
                agreement_id,
            )
            raise AgreementAlreadyLinkedError(patient_id, agreement_id) from exc
