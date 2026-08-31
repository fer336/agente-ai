import httpx

from app.application.errors.error_types import LINEAR_ERROR
from app.infrastructure.observability.tool_tracing import traced_call

_PROVIDER = "linear"

#: Linear's `IssuePriority` enum is an int (0=No priority, 1=Urgent,
#: 2=High, 3=Medium, 4=Low) — our `IncidentGateway.create_issue(priority=...)`
#: takes PRD.md §48's plain-string priorities ("urgent"/"high"/"medium"/
#: "low"); anything unrecognized falls back to "no priority" rather than
#: guessing.
_PRIORITY_BY_NAME = {"urgent": 1, "high": 2, "medium": 3, "low": 4}

_CREATE_ISSUE_MUTATION = """
mutation IssueCreate($teamId: String!, $title: String!, $description: String!, $priority: Int!) {
  issueCreate(
    input: {teamId: $teamId, title: $title, description: $description, priority: $priority}
  ) {
    success
    issue { identifier }
  }
}
"""

_ADD_COMMENT_MUTATION = """
mutation CommentCreate($issueId: String!, $body: String!) {
  commentCreate(input: {issueId: $issueId, body: $body}) {
    success
  }
}
"""


class LinearIncidentGateway:
    """`httpx`-based `IncidentGateway` adapter for Linear's GraphQL API
    (PRD.md §48).

    UNVERIFIED against a live Linear workspace (no live API key in this
    environment — see this change's report, same honesty convention as
    `GroqTranscriptionGateway`/`TelegramAlertNotifier`). Endpoint shape
    follows Linear's publicly documented GraphQL API (`POST
    {base_url}/graphql`, header `Authorization: {api_key}` — Linear's own
    convention is the raw key, not a `Bearer` prefix). Confirm against real
    Linear docs/credentials before production use.

    `close_issue` is INCOMPLETE by design: Linear closes an issue by
    setting `IssueUpdateInput.stateId` to a workflow state id, which is
    per-team and not resolvable without an extra query this gateway does
    not perform. Since PRD.md §51 says automatic closing is optional and
    `ErrorService`/the recovery worker never call this method, it is left
    as a documented placeholder rather than a half-verified guess — raises
    `NotImplementedError` until a real workspace's state ids are known.
    """

    def __init__(self, base_url: str, api_key: str, team_id: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._team_id = team_id
        self._timeout_seconds = timeout_seconds

    async def create_issue(self, *, title: str, description: str, priority: str) -> str:
        variables = {
            "teamId": self._team_id,
            "title": title,
            "description": description,
            "priority": _PRIORITY_BY_NAME.get(priority.lower(), 0),
        }

        async def _call() -> str:
            data = await self._graphql(_CREATE_ISSUE_MUTATION, variables)
            issue_create = data["issueCreate"]
            assert isinstance(issue_create, dict)
            issue = issue_create["issue"]
            assert isinstance(issue, dict)
            return str(issue["identifier"])

        return await traced_call(
            tool_name="LinearCreateIssueTool",
            provider=_PROVIDER,
            operation="create_issue",
            request_summary=f"title_len={len(title)} priority={priority}",
            call=_call,
            response_summary=lambda issue_id: f"issue_id={issue_id}",
            error_type_of=lambda _exc: LINEAR_ERROR,
        )

    async def add_comment(self, issue_id: str, text: str) -> None:
        async def _call() -> None:
            await self._graphql(_ADD_COMMENT_MUTATION, {"issueId": issue_id, "body": text})

        await traced_call(
            tool_name="LinearAddCommentTool",
            provider=_PROVIDER,
            operation="add_comment",
            request_summary=f"issue_id={issue_id} text_len={len(text)}",
            call=_call,
            error_type_of=lambda _exc: LINEAR_ERROR,
        )

    async def close_issue(self, issue_id: str) -> None:
        raise NotImplementedError(
            "LinearIncidentGateway.close_issue is a documented placeholder — see this "
            "class's docstring. Never called automatically (PRD.md §51)."
        )

    async def _graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        headers = {"Authorization": self._api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/graphql",
                    headers=headers,
                    json={"query": query, "variables": variables},
                )
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Linear request timed out after {self._timeout_seconds}s") from exc

        if response.is_error:
            raise RuntimeError(f"Linear rejected the request ({response.status_code})")

        payload = response.json()
        if "errors" in payload:
            raise RuntimeError(f"Linear returned GraphQL errors: {payload['errors']}")
        data = payload["data"]
        return dict(data) if isinstance(data, dict) else {}
