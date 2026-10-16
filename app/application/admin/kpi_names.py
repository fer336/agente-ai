import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300.0
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_FAILURE_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class KpiNames:
    """Plain id -> display name maps. Empty when the catalog could not be loaded."""

    professionals: dict[str, str] = field(default_factory=dict)
    specialties: dict[str, str] = field(default_factory=dict)


class _CachedNames:
    """One catalog, cached in-process. Failures are logged and never raised.

    Concurrent callers share ONE in-flight fetch (no lock is held while awaiting the
    network). A failed fetch is cached negatively for `failure_ttl_seconds`: callers get
    the last good value (or `{}` if there never was one) without calling the source again.
    """

    def __init__(
        self,
        label: str,
        fetch: Callable[[], Awaitable[dict[str, str]]],
        ttl_seconds: float,
        timeout_seconds: float,
        failure_ttl_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        self._label = label
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._failure_ttl = failure_ttl_seconds
        self._clock = clock
        self._value: dict[str, str] = {}
        self._loaded_at: float | None = None
        self._failed_at: float | None = None
        self._inflight: asyncio.Task[None] | None = None

    async def get(self) -> dict[str, str]:
        now = self._clock()
        if self._loaded_at is not None and now - self._loaded_at < self._ttl:
            return self._value
        if self._failed_at is not None and now - self._failed_at < self._failure_ttl:
            return self._value
        if self._inflight is None:
            self._inflight = asyncio.create_task(self._refresh())
        # Shielded so one cancelled caller does not cancel the fetch the others share.
        await asyncio.shield(self._inflight)
        return self._value

    async def _refresh(self) -> None:
        try:
            self._value = await asyncio.wait_for(self._fetch(), timeout=self._timeout)
            self._loaded_at = self._clock()
            self._failed_at = None
        except Exception as error:
            self._failed_at = self._clock()
            logger.warning("KPI %s names unavailable, using ids as labels: %r", self._label, error)
        finally:
            self._inflight = None


class KpiNameCatalog:
    """Best-effort id -> name lookup for the KPI endpoint (professionals, specialties).

    Sources are injected callables (the Dentalink gateways' `list_*` methods), so this
    class knows nothing about Dentalink. It never raises: the endpoint must still answer
    with ids as labels when Dentalink is down, slow, or not configured.
    """

    def __init__(
        self,
        professionals: Callable[[], Awaitable[list[Professional]]],
        specialties: Callable[[], Awaitable[list[Specialty]]],
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        failure_ttl_seconds: float = DEFAULT_FAILURE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        async def fetch_professionals() -> dict[str, str]:
            return {p.id: p.full_name for p in await professionals()}

        async def fetch_specialties() -> dict[str, str]:
            return {s.id: s.name for s in await specialties()}

        self._professionals = _CachedNames(
            "professional",
            fetch_professionals,
            ttl_seconds,
            timeout_seconds,
            failure_ttl_seconds,
            clock,
        )
        self._specialties = _CachedNames(
            "specialty", fetch_specialties, ttl_seconds, timeout_seconds, failure_ttl_seconds, clock
        )

    async def load(self) -> KpiNames:
        professionals, specialties = await asyncio.gather(
            self._professionals.get(), self._specialties.get()
        )
        return KpiNames(professionals=professionals, specialties=specialties)
