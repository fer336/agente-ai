from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.db import get_committing_db_session
from app.api.dependencies.gateways import get_linear_gateway, get_telegram_notifier
from app.application.errors.error_service import ErrorService
from app.config.settings import Settings, get_settings
from app.domain.repositories.sent_message_repository import SentMessageRepository
from app.infrastructure.database.repositories.error_repository import SqlAlchemyErrorRepository
from app.infrastructure.database.repositories.incident_repository import (
    SqlAlchemyIncidentRepository,
)
from app.infrastructure.database.repositories.sent_message_repository import (
    SqlAlchemySentMessageRepository,
)


def get_committing_error_service(
    session: AsyncSession = Depends(get_committing_db_session),
    settings: Settings = Depends(get_settings),
) -> ErrorService:
    """FastAPI dependency providing an `ErrorService` bound to a COMMITTING
    session — for routes (the YCloud webhook's delivery-failure branch)
    that must persist an `ErrorRecord`/`Incident` past the request, same
    rationale as
    `app.api.dependencies.repositories.get_committing_conversation_repository`.

    Every other `ErrorService` construction in this codebase happens
    per-turn inside `LangGraphAgentInvoker.handle()`, sharing that turn's
    own session/commit via `trace_repositories_provider` — this is the
    first standalone route-level `ErrorService` outside that flow.

    Deliberately lives in its own module rather than
    `app.api.dependencies.repositories` (which needs `session` deps but
    never imports from `gateways.py`) or `app.api.dependencies.gateways`
    (which has no `session`-scoped dependencies): `gateways.py` already
    imports from `repositories.py`, so this needing both would create an
    import cycle either way it was placed there.
    """
    return ErrorService(
        error_repository=SqlAlchemyErrorRepository(session),
        incident_repository=SqlAlchemyIncidentRepository(session),
        telegram_notifier=get_telegram_notifier(),
        linear_gateway=get_linear_gateway(),
        alert_threshold_count=settings.alert_timeout_threshold_count,
        alert_window_seconds=settings.alert_timeout_threshold_window_seconds,
        incident_threshold_count=settings.incident_threshold_count,
        incident_threshold_window_seconds=settings.incident_threshold_window_seconds,
        telegram_alert_cooldown_seconds=settings.telegram_alert_cooldown_seconds,
    )


def get_committing_sent_message_repository(
    session: AsyncSession = Depends(get_committing_db_session),
) -> SentMessageRepository:
    """FastAPI dependency providing `SentMessageRepository` bound to the
    SAME committing session `get_committing_error_service` uses — FastAPI
    caches `Depends(get_committing_db_session)` per request, so a route
    depending on both shares one session/transaction.
    """
    return SqlAlchemySentMessageRepository(session)
