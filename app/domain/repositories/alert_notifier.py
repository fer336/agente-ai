from typing import Protocol, runtime_checkable


@runtime_checkable
class AlertNotifier(Protocol):
    """Port to an immediate-alert channel for the technical admin (PRD.md
    §47). Takes plain, pre-formatted text — same convention as
    `MessagingGateway`'s methods — building the alert copy is
    `ErrorService`'s job, not the notifier's.
    """

    async def notify(self, text: str) -> None: ...
