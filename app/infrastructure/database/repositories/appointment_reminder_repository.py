from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.appointment_reminder import AppointmentReminder
from app.infrastructure.database.models.appointment_reminder import AppointmentReminderModel


class SqlAlchemyAppointmentReminderRepository:
    """PostgreSQL persistence with compare-and-swap delivery transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, reminder: AppointmentReminder) -> bool:
        """Refresh only retryable rows, preserving active delivery claims."""
        statement = insert(AppointmentReminderModel).values(
            id=reminder.id,
            appointment_id=reminder.appointment_id,
            patient_id=reminder.patient_id,
            kind=reminder.kind,
            status="pending",
            due_at=reminder.due_at,
            attempts=0,
            claimed_at=None,
            recipient_phone=reminder.recipient_phone,
            external_message_id=None,
            last_error=None,
            sent_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=(
                AppointmentReminderModel.appointment_id,
                AppointmentReminderModel.kind,
            ),
            set_={
                "patient_id": statement.excluded.patient_id,
                "status": "pending",
                "due_at": statement.excluded.due_at,
                "claimed_at": None,
                "recipient_phone": statement.excluded.recipient_phone,
                "external_message_id": None,
                "last_error": None,
                "sent_at": None,
            },
            where=AppointmentReminderModel.status.in_(("pending", "failed")),
        )
        result = await self._session.execute(statement)
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1

    async def list_due(self, now: datetime, limit: int) -> list[AppointmentReminder]:
        result = await self._session.execute(
            select(AppointmentReminderModel)
            .where(
                AppointmentReminderModel.status == "pending",
                AppointmentReminderModel.due_at <= now,
            )
            .order_by(AppointmentReminderModel.due_at)
            .limit(limit)
        )
        return [_to_entity(model) for model in result.scalars()]

    async def claim(self, reminder_id: str, claimed_at: datetime) -> bool:
        result = await self._session.execute(
            update(AppointmentReminderModel)
            .where(
                AppointmentReminderModel.id == reminder_id,
                AppointmentReminderModel.status == "pending",
            )
            .values(
                status="processing",
                claimed_at=claimed_at,
                attempts=AppointmentReminderModel.attempts + 1,
            )
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1

    async def release_or_fail(
        self,
        reminder_id: str,
        *,
        claimed_at: datetime,
        error: str,
        retry_at: datetime | None,
    ) -> bool:
        values: dict[str, object] = {
            "status": "pending" if retry_at is not None else "failed",
            "claimed_at": None,
            "last_error": error,
        }
        if retry_at is not None:
            values["due_at"] = retry_at
        result = await self._session.execute(
            update(AppointmentReminderModel)
            .where(
                AppointmentReminderModel.id == reminder_id,
                AppointmentReminderModel.status == "processing",
                AppointmentReminderModel.claimed_at == claimed_at,
            )
            .values(**values)
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1

    async def mark_sent(
        self,
        reminder_id: str,
        *,
        claimed_at: datetime,
        external_message_id: str,
        sent_at: datetime,
    ) -> bool:
        result = await self._session.execute(
            update(AppointmentReminderModel)
            .where(
                AppointmentReminderModel.id == reminder_id,
                AppointmentReminderModel.status == "processing",
                AppointmentReminderModel.claimed_at == claimed_at,
            )
            .values(
                status="sent",
                claimed_at=None,
                external_message_id=external_message_id,
                last_error=None,
                sent_at=sent_at,
            )
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1

    async def has_sent_review_request_since(self, patient_id: str, cutoff: datetime) -> bool:
        statement = select(
            exists().where(
                AppointmentReminderModel.patient_id == patient_id,
                AppointmentReminderModel.kind == "review_request",
                AppointmentReminderModel.status == "sent",
                AppointmentReminderModel.sent_at >= cutoff,
            )
        )
        result = await self._session.execute(statement)
        return bool(result.scalar())


def _to_entity(model: AppointmentReminderModel) -> AppointmentReminder:
    return AppointmentReminder(
        id=model.id,
        appointment_id=model.appointment_id,
        patient_id=model.patient_id,
        kind=cast(Any, model.kind),
        status=cast(Any, model.status),
        due_at=model.due_at,
        recipient_phone=model.recipient_phone,
        attempts=model.attempts,
        claimed_at=model.claimed_at,
        external_message_id=model.external_message_id,
        last_error=model.last_error,
        created_at=model.created_at,
        updated_at=model.updated_at,
        sent_at=model.sent_at,
    )
