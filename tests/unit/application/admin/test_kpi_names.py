import asyncio
import logging

import pytest

from app.application.admin.kpi_names import KpiNameCatalog
from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Source:
    """Counts calls and can be switched to fail or hang."""

    def __init__(self) -> None:
        self.professional_calls = 0
        self.specialty_calls = 0
        self.fail = False
        self.hang = False
        self.professionals = [Professional(id="p1", full_name="Dra. Ana", specialty_id="s1")]
        self.specialties = [Specialty(id="s1", name="Ortodoncia")]

    async def list_professionals(self) -> list[Professional]:
        self.professional_calls += 1
        await self._maybe_misbehave()
        return list(self.professionals)

    async def list_specialties(self) -> list[Specialty]:
        self.specialty_calls += 1
        await self._maybe_misbehave()
        return list(self.specialties)

    async def _maybe_misbehave(self) -> None:
        if self.hang:
            await asyncio.sleep(3600)
        if self.fail:
            raise RuntimeError("dentalink down")


def _catalog(source: _Source, clock: _Clock, **kwargs: float) -> KpiNameCatalog:
    return KpiNameCatalog(
        professionals=source.list_professionals,
        specialties=source.list_specialties,
        clock=clock,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_load_returns_id_to_name_dicts():
    names = await _catalog(_Source(), _Clock()).load()

    assert names.professionals == {"p1": "Dra. Ana"}
    assert names.specialties == {"s1": "Ortodoncia"}


@pytest.mark.asyncio
async def test_second_load_within_ttl_is_served_from_cache():
    source, clock = _Source(), _Clock()
    catalog = _catalog(source, clock, ttl_seconds=300)

    await catalog.load()
    clock.now += 299
    await catalog.load()

    assert (source.professional_calls, source.specialty_calls) == (1, 1)


@pytest.mark.asyncio
async def test_load_refreshes_after_the_ttl():
    source, clock = _Source(), _Clock()
    catalog = _catalog(source, clock, ttl_seconds=300)
    await catalog.load()

    source.professionals = [Professional(id="p2", full_name="Dr. Luis", specialty_id=None)]
    clock.now += 301
    names = await catalog.load()

    assert (source.professional_calls, source.specialty_calls) == (2, 2)
    assert names.professionals == {"p2": "Dr. Luis"}


@pytest.mark.asyncio
async def test_failure_is_swallowed_logged_and_yields_empty_dicts(
    caplog: pytest.LogCaptureFixture,
):
    source = _Source()
    source.fail = True

    with caplog.at_level(logging.WARNING, logger="app.application.admin.kpi_names"):
        names = await _catalog(source, _Clock()).load()

    assert names.professionals == {}
    assert names.specialties == {}
    assert [r.levelno for r in caplog.records] == [logging.WARNING, logging.WARNING]


@pytest.mark.asyncio
async def test_a_failure_is_retried_once_the_negative_ttl_has_passed():
    source, clock = _Source(), _Clock()
    source.fail = True
    catalog = _catalog(source, clock)
    await catalog.load()

    source.fail = False
    clock.now += 31
    names = await catalog.load()

    assert names.professionals == {"p1": "Dra. Ana"}
    assert names.specialties == {"s1": "Ortodoncia"}


@pytest.mark.asyncio
async def test_a_failed_refresh_keeps_serving_the_last_good_names():
    source, clock = _Source(), _Clock()
    catalog = _catalog(source, clock, ttl_seconds=300)
    await catalog.load()

    source.fail = True
    clock.now += 301
    names = await catalog.load()

    assert names.professionals == {"p1": "Dra. Ana"}


@pytest.mark.asyncio
async def test_one_catalog_failing_does_not_drop_the_other():
    source = _Source()

    async def broken() -> list[Professional]:
        raise RuntimeError("boom")

    catalog = KpiNameCatalog(
        professionals=broken, specialties=source.list_specialties, clock=_Clock()
    )

    names = await catalog.load()

    assert names.professionals == {}
    assert names.specialties == {"s1": "Ortodoncia"}


@pytest.mark.asyncio
async def test_a_hanging_source_times_out_and_yields_empty_dicts():
    source = _Source()
    source.hang = True

    names = await _catalog(source, _Clock(), timeout_seconds=0.01).load()

    assert names.professionals == {}
    assert names.specialties == {}


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_in_flight_fetch():
    source, clock = _Source(), _Clock()
    gate = asyncio.Event()
    original = source.list_professionals

    async def gated() -> list[Professional]:
        await gate.wait()
        return await original()

    catalog = KpiNameCatalog(professionals=gated, specialties=source.list_specialties, clock=clock)

    callers = [asyncio.create_task(catalog.load()) for _ in range(5)]
    await asyncio.sleep(0.01)
    gate.set()
    results = await asyncio.gather(*callers)

    assert source.professional_calls == 1
    assert source.specialty_calls == 1
    assert all(r.professionals == {"p1": "Dra. Ana"} for r in results)


@pytest.mark.asyncio
async def test_concurrent_callers_during_a_hang_wait_one_timeout_not_n():
    source = _Source()
    source.hang = True
    catalog = _catalog(source, _Clock(), timeout_seconds=0.05)

    loop = asyncio.get_running_loop()
    started = loop.time()
    await asyncio.gather(*(catalog.load() for _ in range(10)))

    assert loop.time() - started < 0.2
    assert source.professional_calls == 1


@pytest.mark.asyncio
async def test_a_failure_is_cached_negatively_within_the_ttl():
    source, clock = _Source(), _Clock()
    source.fail = True
    catalog = _catalog(source, clock, failure_ttl_seconds=30)
    await catalog.load()

    source.fail = False
    clock.now += 29
    names = await catalog.load()

    assert (source.professional_calls, source.specialty_calls) == (1, 1)
    assert names.professionals == {}


@pytest.mark.asyncio
async def test_a_failed_catalog_is_refetched_after_the_negative_ttl():
    source, clock = _Source(), _Clock()
    source.fail = True
    catalog = _catalog(source, clock, failure_ttl_seconds=30)
    await catalog.load()

    source.fail = False
    clock.now += 30
    names = await catalog.load()

    assert (source.professional_calls, source.specialty_calls) == (2, 2)
    assert names.professionals == {"p1": "Dra. Ana"}


@pytest.mark.asyncio
async def test_stale_good_names_survive_a_failure_and_the_negative_window():
    source, clock = _Source(), _Clock()
    catalog = _catalog(source, clock, ttl_seconds=300, failure_ttl_seconds=30)
    await catalog.load()

    source.fail = True
    clock.now += 301
    first = await catalog.load()
    clock.now += 10
    second = await catalog.load()

    assert first.professionals == second.professionals == {"p1": "Dra. Ana"}
    assert source.professional_calls == 2  # initial + one failed refresh, none in the window


@pytest.mark.asyncio
async def test_one_catalog_failing_is_cached_without_affecting_the_other():
    source, clock = _Source(), _Clock()

    async def broken() -> list[Professional]:
        raise RuntimeError("boom")

    catalog = KpiNameCatalog(professionals=broken, specialties=source.list_specialties, clock=clock)
    await catalog.load()
    clock.now += 31
    source.specialties = [Specialty(id="s2", name="Endodoncia")]
    clock.now += 300
    names = await catalog.load()

    assert names.professionals == {}
    assert names.specialties == {"s2": "Endodoncia"}
