"""Shared builders for tests that drive the appointment node end to end."""

from datetime import UTC, datetime, timedelta

from app.agent.nodes.appointment import create_appointment_node
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_agreement_gateway,
    make_conversation_repository,
    make_dentalink_gateway,
    make_patient_gateway,
    make_proposal_repositories_provider,
    make_specialty_gateway,
)
from tests.fixtures.seed_objects import (
    make_conversation,
    make_patient,
    make_professional,
    make_specialty,
)


def future_slot(
    id_: str = "slot-1", days: int = 1, professional_id: str = "prof-1"
) -> AppointmentSlot:
    now = datetime.now(UTC)
    start = now + timedelta(days=days)
    return AppointmentSlot(
        id=id_,
        professional_id=professional_id,
        specialty_id="cleaning",
        time_range=DateTimeRange(start, start + timedelta(hours=1)),
    )


async def make_node_and_conversation(
    available_slots=None,
    patients=None,
    conversation_repository=None,
    proposal_repositories_provider=None,
    professionals=None,
    conversation_id="conv-1",
    llm_provider=None,
    specialties=None,
    agreements=None,
    patient_gateway=None,
    agreement_gateway=None,
    verification_flow_id="",
    registration_flow_id="",
):
    conversation_repository = conversation_repository or make_conversation_repository()
    await conversation_repository.save(make_conversation(id_=conversation_id, mode="agent"))
    appointment_gateway = make_dentalink_gateway(
        available_slots=available_slots if available_slots is not None else [future_slot()],
        professionals=professionals
        if professionals is not None
        else [make_professional(id_="prof-1", specialty_id="cleaning")],
    )
    node = create_appointment_node(
        appointment_gateway=appointment_gateway,
        patient_gateway=patient_gateway
        or make_patient_gateway(
            patients=patients
            if patients is not None
            else [make_patient(id_="pat-1", full_name="Juan Perez", dni="30123456")]
        ),
        proposal_repositories_provider=(
            proposal_repositories_provider or make_proposal_repositories_provider()
        ),
        conversation_repository=conversation_repository,
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        llm_provider=llm_provider or FakeLLMProvider(),
        specialty_gateway=make_specialty_gateway(
            specialties=specialties
            if specialties is not None
            else [make_specialty(id_="cleaning", name="Ortodoncia")]
        ),
        agreement_gateway=agreement_gateway or make_agreement_gateway(agreements=agreements),
        verification_flow_id=verification_flow_id,
        registration_flow_id=registration_flow_id,
    )
    return node, conversation_repository, appointment_gateway
