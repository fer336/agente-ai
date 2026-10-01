from datetime import UTC, datetime, timedelta

import pytest

from app.api.dependencies.internal_eval import get_evaluate_chat_turn_use_case
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.dentalink.eval_seed import (
    EVAL_PATIENT_DNI,
    EVAL_PATIENT_NAME,
    build_eval_seed,
)

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_seed_patient_is_found_by_name_and_dni():
    seed = build_eval_seed(_NOW)

    patient = await seed.patients.find_patient(EVAL_PATIENT_NAME, EVAL_PATIENT_DNI)

    assert patient is not None
    assert patient.dni == EVAL_PATIENT_DNI


@pytest.mark.asyncio
async def test_seed_patient_has_two_upcoming_appointments_with_professional_and_specialty():
    seed = build_eval_seed(_NOW)
    patient = await seed.patients.find_patient(EVAL_PATIENT_NAME, EVAL_PATIENT_DNI)
    assert patient is not None

    appointments = await seed.dentalink.get_patient_appointments(patient.id)
    professionals = {p.id: p for p in await seed.dentalink.list_professionals()}
    specialties = {s.id: s for s in await seed.specialties.list_specialties()}

    assert len(appointments) == 2
    starts = [a.slot.time_range.start for a in appointments]
    assert all(start > _NOW + timedelta(days=1) for start in starts)
    assert starts == sorted(starts)
    for appointment in appointments:
        assert appointment.slot.professional_id in professionals
        assert appointment.slot.specialty_id in specialties


@pytest.mark.asyncio
async def test_seed_offers_availability_for_rescheduling():
    seed = build_eval_seed(_NOW)

    from app.domain.value_objects.date_time_range import DateTimeRange

    slots = await seed.dentalink.search_availability(
        None, None, DateTimeRange(_NOW, _NOW + timedelta(days=30))
    )

    assert len(slots) >= 2


def test_seed_patients_do_not_collide_with_the_not_found_scenario():
    # datasets/appointments.yaml expects "Juan Pérez, DNI 30111222" to be NOT found.
    assert EVAL_PATIENT_DNI != "30111222"


def test_eval_stack_is_built_on_the_seed():
    use_case = get_evaluate_chat_turn_use_case()
    invoker = use_case._agent_invoker  # type: ignore[attr-defined]

    assert invoker._patient_gateway._patients  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_seed_carries_a_few_agreements_so_osde_resolves():
    seed = build_eval_seed(_NOW)

    names = [agreement.name for agreement in await seed.agreements.list_agreements()]
    osde = await seed.agreements.find_agreement_by_name("osde")

    assert names == ["OSDE", "Swiss Medical", "Galeno"]
    assert osde is not None
    assert osde.id.startswith("eval-")


def test_eval_stack_uses_the_seeded_agreements():
    use_case = get_evaluate_chat_turn_use_case()
    invoker = use_case._agent_invoker  # type: ignore[attr-defined]

    assert invoker._agreement_gateway._agreements  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_seed_has_a_staffed_general_specialty_with_availability():
    seed = build_eval_seed(_NOW)

    specialties = {s.name: s for s in await seed.specialties.list_specialties()}
    professionals = await seed.dentalink.list_professionals()
    slots = await seed.dentalink.search_availability(
        None, None, DateTimeRange(_NOW, _NOW + timedelta(days=30))
    )

    general = specialties["General"]
    assert general.id == "eval-spec-3"
    assert any(p.specialty_id == general.id for p in professionals)
    assert any(slot.specialty_id == general.id for slot in slots)
