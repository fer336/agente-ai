class FakeLinearIncidentGateway:
    """In-memory fake implementing `IncidentGateway` for local dev and tests."""

    def __init__(self) -> None:
        self.created_issues: list[dict[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.closed_issue_ids: list[str] = []
        self._next_id = 1

    async def create_issue(self, *, title: str, description: str, priority: str) -> str:
        issue_id = f"FAKE-{self._next_id}"
        self._next_id += 1
        self.created_issues.append(
            {"issue_id": issue_id, "title": title, "description": description, "priority": priority}
        )
        return issue_id

    async def add_comment(self, issue_id: str, text: str) -> None:
        self.comments.append((issue_id, text))

    async def close_issue(self, issue_id: str) -> None:
        self.closed_issue_ids.append(issue_id)
