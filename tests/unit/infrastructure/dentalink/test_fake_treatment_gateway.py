import pytest

from app.domain.entities.treatment import Treatment
from app.domain.repositories.gateways import TreatmentGateway
from app.infrastructure.dentalink.fake_treatment_gateway import FakeTreatmentGateway


def _treatment(id_: str = "t-1", patient_id: str = "pat-1") -> Treatment:
    return Treatment(
        id=id_,
        patient_id=patient_id,
        name="Plan",
        is_finished=False,
        total=100.0,
        paid=50.0,
        debt=50.0,
    )


@pytest.mark.asyncio
async def test_get_patient_treatments_returns_preset_treatments():
    gateway = FakeTreatmentGateway({"pat-1": [_treatment()]})

    treatments = await gateway.get_patient_treatments("pat-1")

    assert len(treatments) == 1
    assert treatments[0].id == "t-1"


@pytest.mark.asyncio
async def test_get_patient_treatments_returns_empty_for_unknown_patient():
    gateway = FakeTreatmentGateway()

    assert await gateway.get_patient_treatments("unknown") == []


def test_fake_treatment_gateway_satisfies_treatment_gateway_protocol():
    assert isinstance(FakeTreatmentGateway(), TreatmentGateway)
