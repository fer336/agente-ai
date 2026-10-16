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


@dataclass(frozen=True)
class KpiNames:
    """Plain id -> display name maps. Empty when the catalog could not be loaded."""

    professionals: dict[str, str] = field(default_factory=dict)
    specialties: dict[str, str] = field(default_factory=dict)


class _CachedNames:
    """One catalog, cached in-process. Failures are logged and never raised: a failed
    refresh keeps serving the last good value (or `{}` if there never was one), and is
    not cached, so the next call retries."""

    def __init__(
        self,
        label: str,
        fetch: Callable[[], Awaitable[dict[str, str]]],
        ttl_seconds: float,
        timeout_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        self._label = label
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._clock = clock
        self._value: dict[str, str] = {}
        self._loaded_at: float | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> dict[str, str]:
        async with self._lock:
            if self._loaded_at is not None and self._clock() - self._loaded_at < self._ttl:
                return self._value
            try:
                self._value = await asyncio.wait_for(self._fetch(), timeout=self._timeout)
                self._loaded_at = self._clock()
            except Exception as error:
                logger.warning(
                    "KPI %s names unavailable, using ids as labels: %r", self._label, error
                )
            return self._value


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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        async def fetch_professionals() -> dict[str, str]:
            return {p.id: p.full_name for p in await professionals()}

        async def fetch_specialties() -> dict[str, str]:
            return {s.id: s.name for s in await specialties()}

        self._professionals = _CachedNames(
            "professional", fetch_professionals, ttl_seconds, timeout_seconds, clock
        )
        self._specialties = _CachedNames(
            "specialty", fetch_specialties, ttl_seconds, timeout_seconds, clock
        )

    async def load(self) -> KpiNames:
        professionals, specialties = await asyncio.gather(
            self._professionals.get(), self._specialties.get()
        )
        return KpiNames(professionals=professionals, specialties=specialties)
