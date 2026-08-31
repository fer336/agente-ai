from datetime import datetime

from app.domain.entities.incident import INCIDENT_RECOVERED
from app.domain.repositories.alert_notifier import AlertNotifier
from app.domain.repositories.incident_gateway import IncidentGateway
from app.domain.repositories.incident_repository import IncidentRepository


async def check_incident_recovery(
    incident_repository: IncidentRepository,
    telegram_notifier: AlertNotifier,
    linear_gateway: IncidentGateway,
    quiet_window_seconds: int,
    now: datetime,
) -> int:
    """PRD.md §51's incident-recovery sweep — one poll tick: any open
    incident whose `last_seen` is older than `quiet_window_seconds` before
    `now` is marked recovered.

    DELIBERATELY NOT a running process/scheduler (no ARQ/cron loop, no
    `asyncio.sleep`-based poll loop) — this mirrors the exact same gap
    already accepted for `ScheduledAction` follow-up/expiry processing and
    for `app.workers.audio_tasks.process_pending_audio_jobs` elsewhere in
    this codebase. This function is the complete, tested, swap-point-ready
    processing step; wiring it into an actual worker/cron entrypoint is a
    later, broader "at least one worker process" concern, out of scope
    here.

    A Telegram/Linear delivery failure for one incident never aborts the
    sweep — the incident is still marked recovered in the repository even
    if the recovery notification itself fails, matching `ErrorService.
    notify_telegram`/`sync_linear`'s own "never let an alert channel outage
    corrupt otherwise-correct state" posture. Returns how many incidents
    were recovered.
    """
    open_incidents = await incident_repository.list_open()
    recovered_count = 0
    for incident in open_incidents:
        elapsed = (now - incident.last_seen).total_seconds()
        if elapsed < quiet_window_seconds:
            continue

        incident.status = INCIDENT_RECOVERED
        incident.resolved_at = now
        await incident_repository.update(incident)
        recovered_count += 1

        duration_minutes = int((incident.resolved_at - incident.first_seen).total_seconds() // 60)
        text = (
            f"✅ Recuperado — {incident.source}\n\n"
            f"Error: {incident.error_type}\n"
            f"Duración: {duration_minutes} minutos\n"
            f"Conversaciones afectadas: {incident.affected_conversations}"
        )
        try:
            await telegram_notifier.notify(text)
        except Exception:  # noqa: BLE001 - a Telegram outage must never break the sweep
            pass

        if incident.linear_issue_id is not None:
            try:
                await linear_gateway.add_comment(
                    incident.linear_issue_id, f"Recovered — duration {duration_minutes}m"
                )
            except Exception:  # noqa: BLE001 - a Linear outage must never break the sweep
                pass

    return recovered_count
