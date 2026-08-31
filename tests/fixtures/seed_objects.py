"""Shared seed-object builders for domain objects commonly needed in tests.

Plain factory functions (not `@pytest.fixture`s) — fakes and domain objects
have no setup/teardown lifecycle, so a callable constructor is sufficient and
matches the call shape of the inline helpers these replace.
"""

from datetime import UTC, datetime, timedelta

from app.domain.entities.agent_run import RUNNING, AgentRun
from app.domain.entities.agreement import Agreement
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.contact import Contact
from app.domain.entities.conversation import Conversation
from app.domain.entities.error_record import SEVERITY_INFO, SOURCE_APPLICATION, ErrorRecord
from app.domain.entities.incident import INCIDENT_OPEN, Incident
from app.domain.entities.message import Message
from app.domain.entities.node_execution import COMPLETED as NODE_EXECUTION_COMPLETED
from app.domain.entities.node_execution import NodeExecution
from app.domain.entities.outbox_event import OutboxEvent
from app.domain.entities.patient import Patient
from app.domain.entities.pending_action import PendingAction
from app.domain.entities.professional import Professional
from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.entities.tool_execution import COMPLETED as TOOL_EXECUTION_COMPLETED
from app.domain.entities.tool_execution import ToolExecution
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.confirmation_token import ConfirmationToken
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.idempotency_key import IdempotencyKey
from app.domain.value_objects.phone_number import PhoneNumber


def make_slot(
    id_: str = "slot-1",
    professional_id: str = "prof-1",
    specialty_id: str = "cleaning",
    start: datetime = datetime(2026, 8, 1, 10, 0),
    end: datetime = datetime(2026, 8, 1, 10, 30),
) -> AppointmentSlot:
    return AppointmentSlot(
        id=id_,
        professional_id=professional_id,
        specialty_id=specialty_id,
        time_range=DateTimeRange(start, end),
    )


def make_professional(
    id_: str = "prof-1",
    full_name: str = "Dra. Laura Pérez",
    specialty_id: str | None = "cleaning",
) -> Professional:
    return Professional(id=id_, full_name=full_name, specialty_id=specialty_id)


def make_agreement(id_: str = "agr-1", name: str = "OSDE") -> Agreement:
    return Agreement(id=id_, name=name)


def make_patient(
    id_: str = "pat-1",
    full_name: str = "Jane Doe",
    phone: str = "+5491122334455",
    dni: str | None = None,
) -> Patient:
    return Patient(id=id_, full_name=full_name, phone=PhoneNumber(phone), dni=dni)


def make_appointment(
    id_: str = "appt-1",
    patient_id: str = "pat-1",
    slot: AppointmentSlot | None = None,
    status: str = "confirmed",
) -> Appointment:
    return Appointment(
        id=AppointmentId(id_),
        patient_id=patient_id,
        slot=slot if slot is not None else make_slot(),
        status=status,
    )


def make_conversation_id(value: str = "conv-1") -> ConversationId:
    return ConversationId(value)


def make_contact(
    id_: str = "contact-1",
    phone: str = "+5491122334455",
    patient_id: str | None = None,
) -> Contact:
    return Contact(id=id_, phone=PhoneNumber(phone), patient_id=patient_id)


def make_conversation(
    id_: str = "ycloud-+5491122334455",
    contact_id: str = "contact-1",
    mode: str = "agent",
    created_at: datetime | None = None,
    input_state: str = "FREE_INPUT",
) -> Conversation:
    return Conversation(
        id=ConversationId(id_),
        contact_id=contact_id,
        mode=mode,
        created_at=created_at if created_at is not None else datetime.now(UTC),
        input_state=input_state,
    )


def make_message(
    id_: str = "msg-1",
    conversation_id: str = "ycloud-+5491122334455",
    external_message_id: str = "wamid.1",
    direction: str = "inbound",
    text: str = "hola",
    created_at: datetime | None = None,
) -> Message:
    return Message(
        id=id_,
        conversation_id=ConversationId(conversation_id),
        external_message_id=ExternalMessageId(external_message_id),
        direction=direction,
        text=text,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def make_ycloud_payload(**overrides: object) -> dict[str, object]:
    """Raw YCloud `whatsapp.inbound_message.received` webhook JSON body, valid-by-default.

    Callers override individual keys to build the filtered-out/malformed
    variants exercised by the webhook route and payload-parsing tests, e.g.
    `make_ycloud_payload(whatsappInboundMessage={"type": "audio"})`. Nested
    overrides replace the whole `whatsappInboundMessage` object — callers
    passing a partial nested override should spread the default first.
    """
    payload: dict[str, object] = {
        "type": "whatsapp.inbound_message.received",
        "whatsappInboundMessage": {
            "id": "wamid.HBgLNTQ5MTEyMjMzNDQ1FQIAERgSMkQ5",
            "from": "+5491122334455",
            "to": "+5491100000001",
            "type": "text",
            "text": {"body": "Hola, quiero agendar un turno"},
        },
    }
    payload.update(overrides)
    return payload


def make_ycloud_button_reply_payload(
    whatsapp_number: str = "+5491100000001",
    button_id: str = "MENU_APPOINTMENT",
    button_title: str = "📅 Turnos",
    external_message_id: str = "wamid.button-reply-1",
    from_phone: str = "+5491122334455",
) -> dict[str, object]:
    """Raw YCloud interactive button-reply webhook JSON body, valid-by-default."""
    return {
        "type": "whatsapp.inbound_message.received",
        "whatsappInboundMessage": {
            "id": external_message_id,
            "from": from_phone,
            "to": whatsapp_number,
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": button_id, "title": button_title},
            },
        },
    }


def make_ycloud_audio_payload(
    whatsapp_number: str = "+5491100000001",
    media_id: str = "media-1",
    mime_type: str = "audio/ogg",
    sha256: str | None = None,
    external_message_id: str = "wamid.audio-1",
    from_phone: str = "+5491122334455",
) -> dict[str, object]:
    """Raw YCloud `type="audio"` webhook JSON body, valid-by-default (PRD.md §24.1)."""
    audio: dict[str, object] = {"id": media_id, "mime_type": mime_type}
    if sha256 is not None:
        audio["sha256"] = sha256
    return {
        "type": "whatsapp.inbound_message.received",
        "whatsappInboundMessage": {
            "id": external_message_id,
            "from": from_phone,
            "to": whatsapp_number,
            "type": "audio",
            "audio": audio,
        },
    }


def make_pending_action(
    id_: str = "pa-1",
    conversation_id: str = "conv-1",
    action_type: str = "create_appointment",
    payload: dict[str, object] | None = None,
    confirmation_token: str = "token-1",
    status: str = "pending",
    expires_at: datetime | None = None,
) -> PendingAction:
    return PendingAction(
        id=id_,
        conversation_id=ConversationId(value=conversation_id),
        action_type=action_type,
        payload=payload if payload is not None else {},
        confirmation_token=ConfirmationToken(value=confirmation_token),
        status=status,
        expires_at=(
            expires_at if expires_at is not None else datetime.now(UTC) + timedelta(minutes=2)
        ),
    )


def make_scheduled_action(
    id_: str = "sa-1",
    conversation_id: str = "conv-1",
    pending_action_id: str = "pa-1",
    action_type: str = "appointment_confirmation_timeout",
    status: str = "scheduled",
    scheduled_for: datetime | None = None,
    idempotency_key: str = "idem-1",
    attempts: int = 0,
) -> ScheduledAction:
    return ScheduledAction(
        id=id_,
        conversation_id=ConversationId(value=conversation_id),
        pending_action_id=pending_action_id,
        action_type=action_type,
        status=status,
        scheduled_for=(
            scheduled_for if scheduled_for is not None else datetime.now(UTC) + timedelta(minutes=2)
        ),
        idempotency_key=IdempotencyKey(value=idempotency_key),
        attempts=attempts,
    )


def make_outbox_event(
    id_: str = "evt-1",
    event_type: str = "appointment.proposed",
    aggregate_type: str = "pending_action",
    aggregate_id: str = "pa-1",
    payload: dict[str, object] | None = None,
    status: str = "pending",
    attempts: int = 0,
) -> OutboxEvent:
    return OutboxEvent(
        id=id_,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload if payload is not None else {},
        status=status,
        attempts=attempts,
    )


def make_agent_run(
    id_: str = "run-1",
    conversation_id: str = "conv-1",
    message_id: str = "msg-1",
    trace_id: str = "trace-1",
    prompt_version: str = "agent-system-v0.1.0",
    model: str = "gpt-4o-mini",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    status: str = RUNNING,
    current_node: str | None = None,
    error_id: str | None = None,
) -> AgentRun:
    return AgentRun(
        id=id_,
        conversation_id=ConversationId(value=conversation_id),
        message_id=message_id,
        trace_id=trace_id,
        prompt_version=prompt_version,
        model=model,
        started_at=started_at if started_at is not None else datetime.now(UTC),
        finished_at=finished_at,
        status=status,
        current_node=current_node,
        error_id=error_id,
    )


def make_node_execution(
    id_: str = "ne-1",
    agent_run_id: str = "run-1",
    node_name: str = "resolve_interaction",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    status: str = NODE_EXECUTION_COMPLETED,
    input_summary: str = "",
    output_summary: str = "",
    duration_ms: int = 10,
    error_id: str | None = None,
) -> NodeExecution:
    now = datetime.now(UTC)
    return NodeExecution(
        id=id_,
        agent_run_id=agent_run_id,
        node_name=node_name,
        started_at=started_at if started_at is not None else now,
        finished_at=finished_at if finished_at is not None else now,
        status=status,
        input_summary=input_summary,
        output_summary=output_summary,
        duration_ms=duration_ms,
        error_id=error_id,
    )


def make_tool_execution(
    id_: str = "te-1",
    agent_run_id: str = "run-1",
    node_execution_id: str | None = "ne-1",
    tool_name: str = "SearchAvailabilityTool",
    provider: str = "dentalink",
    operation: str = "search_availability",
    request_summary: str = "",
    response_summary: str | None = None,
    status: str = TOOL_EXECUTION_COMPLETED,
    http_status: str | None = "200",
    duration_ms: int = 10,
    error_id: str | None = None,
    created_at: datetime | None = None,
) -> ToolExecution:
    return ToolExecution(
        id=id_,
        agent_run_id=agent_run_id,
        node_execution_id=node_execution_id,
        tool_name=tool_name,
        provider=provider,
        operation=operation,
        request_summary=request_summary,
        response_summary=response_summary,
        status=status,
        http_status=http_status,
        duration_ms=duration_ms,
        error_id=error_id,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def make_error_record(
    id_: str = "err-1",
    trace_id: str | None = "trace-1",
    conversation_id: str | None = "conv-1",
    agent_run_id: str | None = "run-1",
    source: str = SOURCE_APPLICATION,
    error_type: str = "unexpected_exception",
    error_code: str | None = None,
    message: str = "Something went wrong",
    technical_detail: str | None = None,
    severity: str = SEVERITY_INFO,
    retryable: bool = False,
    created_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> ErrorRecord:
    return ErrorRecord(
        id=id_,
        trace_id=trace_id,
        conversation_id=ConversationId(value=conversation_id) if conversation_id else None,
        agent_run_id=agent_run_id,
        source=source,
        error_type=error_type,
        error_code=error_code,
        message=message,
        technical_detail=technical_detail,
        severity=severity,
        retryable=retryable,
        created_at=created_at if created_at is not None else datetime.now(UTC),
        resolved_at=resolved_at,
    )


def make_incident(
    id_: str = "inc-1",
    fingerprint: str = "dentalink:dentalink_timeout:search_availability",
    source: str = SOURCE_APPLICATION,
    error_type: str = "dentalink_timeout",
    operation: str | None = "search_availability",
    severity: str = "ERROR",
    occurrences: int = 1,
    affected_conversations: int = 1,
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
    status: str = INCIDENT_OPEN,
    linear_issue_id: str | None = None,
    last_notification_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> Incident:
    now = datetime.now(UTC)
    return Incident(
        id=id_,
        fingerprint=fingerprint,
        source=source,
        error_type=error_type,
        operation=operation,
        severity=severity,
        occurrences=occurrences,
        affected_conversations=affected_conversations,
        first_seen=first_seen if first_seen is not None else now,
        last_seen=last_seen if last_seen is not None else now,
        status=status,
        linear_issue_id=linear_issue_id,
        last_notification_at=last_notification_at,
        resolved_at=resolved_at,
    )
