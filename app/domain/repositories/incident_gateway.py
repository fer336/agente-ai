from typing import Protocol, runtime_checkable


@runtime_checkable
class IncidentGateway(Protocol):
    """Port to an incident/issue-tracking system (PRD.md §48 — Linear).

    `close_issue` is built but, per PRD.md §51 ("El cierre automático del
    issue de Linear será opcional"), `ErrorService`/the recovery worker
    never call it automatically — it exists for a future manual/`/admin`
    trigger.
    """

    async def create_issue(self, *, title: str, description: str, priority: str) -> str:
        """Creates an issue, returning its external id/key (e.g. `"CLI-42"`)."""
        ...

    async def add_comment(self, issue_id: str, text: str) -> None: ...

    async def close_issue(self, issue_id: str) -> None: ...
