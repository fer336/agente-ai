from collections.abc import Collection
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, and_, case, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.appointment_reminder import AppointmentReminder, ReminderKind
from app.domain.value_objects.phone_number import PhoneNumber
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
            appointment_starts_at=reminder.appointment_starts_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=(
                AppointmentReminderModel.appointment_id,
                AppointmentReminderModel.kind,
            ),
            set_={
                "patient_id": statement.excluded.patient_id,
                "status": "pending",
                # A scheduled retry carries a backoff due_at. A scan must
                # not pull it forward while attempts remain outstanding.
                "due_at": case(
                    (
                        and_(
                            AppointmentReminderModel.status == "pending",
                            AppointmentReminderModel.attempts > 0,
                        ),
                        AppointmentReminderModel.due_at,
                    ),
                    else_=statement.excluded.due_at,
                ),
                "claimed_at": None,
                "recipient_phone": statement.excluded.recipient_phone,
                "external_message_id": None,
                "last_error": None,
                "sent_at": None,
                "appointment_starts_at": statement.excluded.appointment_starts_at,
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

    async def skip_pending(self, reminder_id: str, *, reason: str, skipped_at: datetime) -> bool:
        result = await self._session.execute(
            update(AppointmentReminderModel)
            .where(
                AppointmentReminderModel.id == reminder_id,
                AppointmentReminderModel.status == "pending",
            )
            .values(status="skipped", last_error=reason)
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1

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

    async def renew_claim(
        self, reminder_id: str, *, claimed_at: datetime, renewed_at: datetime
    ) -> bool:
        result = await self._session.execute(
            update(AppointmentReminderModel)
            .where(
                AppointmentReminderModel.id == reminder_id,
                AppointmentReminderModel.status == "processing",
                AppointmentReminderModel.claimed_at == claimed_at,
            )
            .values(claimed_at=renewed_at)
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1

    async def reclaim_stale_claims(self, stale_before: datetime) -> int:
        result = await self._session.execute(
            update(AppointmentReminderModel)
            .where(
                AppointmentReminderModel.status == "processing",
                AppointmentReminderModel.claimed_at < stale_before,
            )
            .values(status="pending", claimed_at=None)
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount

    async def mark_skipped(
        self,
        reminder_id: str,
        *,
        claimed_at: datetime,
        reason: str,
        skipped_at: datetime,
    ) -> bool:
        result = await self._session.execute(
            update(AppointmentReminderModel)
            .where(
                AppointmentReminderModel.id == reminder_id,
                AppointmentReminderModel.status == "processing",
                AppointmentReminderModel.claimed_at == claimed_at,
            )
            .values(status="skipped", claimed_at=None, last_error=reason)
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

    async def find_sent_for_inbound_action(
        self,
        appointment_id: str,
        recipient_phone: PhoneNumber,
        allowed_kinds: Collection[ReminderKind],
    ) -> AppointmentReminder | None:
        if not allowed_kinds:
            return None
        result = await self._session.execute(
            select(AppointmentReminderModel)
            .where(
                AppointmentReminderModel.appointment_id == appointment_id,
                AppointmentReminderModel.recipient_phone == str(recipient_phone),
                AppointmentReminderModel.kind.in_(tuple(allowed_kinds)),
                AppointmentReminderModel.status == "sent",
            )
            .limit(1)
        )
        model = result.scalars().first()
        if model is None:
            return None
        return _to_entity(model)

    async def has_sent_review_request_for_recipient(self, recipient_phone: PhoneNumber) -> bool:
        statement = select(
            exists().where(
                AppointmentReminderModel.recipient_phone == str(recipient_phone),
                AppointmentReminderModel.kind == "review_request",
                AppointmentReminderModel.status == "sent",
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
        appointment_starts_at=model.appointment_starts_at,
    )
