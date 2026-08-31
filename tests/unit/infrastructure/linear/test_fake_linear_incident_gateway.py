import pytest

from app.domain.repositories.incident_gateway import IncidentGateway
from app.infrastructure.linear.fake_linear_incident_gateway import FakeLinearIncidentGateway


def test_satisfies_incident_gateway_protocol():
    assert isinstance(FakeLinearIncidentGateway(), IncidentGateway)


@pytest.mark.asyncio
async def test_create_issue_records_and_returns_a_sequential_fake_id():
    gateway = FakeLinearIncidentGateway()

    first_id = await gateway.create_issue(title="A", description="a", priority="urgent")
    second_id = await gateway.create_issue(title="B", description="b", priority="high")

    assert first_id != second_id
    assert [issue["title"] for issue in gateway.created_issues] == ["A", "B"]


@pytest.mark.asyncio
async def test_add_comment_records_the_comment():
    gateway = FakeLinearIncidentGateway()
    issue_id = await gateway.create_issue(title="A", description="a", priority="urgent")

    await gateway.add_comment(issue_id, "still happening")

    assert gateway.comments == [(issue_id, "still happening")]


@pytest.mark.asyncio
async def test_close_issue_records_the_closed_id():
    gateway = FakeLinearIncidentGateway()

    await gateway.close_issue("FAKE-1")

    assert gateway.closed_issue_ids == ["FAKE-1"]
