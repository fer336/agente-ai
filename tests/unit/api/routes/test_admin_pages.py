"""Smoke tests for the admin panel's static HTML pages (PRD.md §44).

These routes serve plain files with no server-side auth dependency — the
real access control is client-side (`app/static/admin/app.js`'s
`requireAuth()`, checked against `/admin/api/me`) plus, ultimately, every
data-bearing `/admin/api/*` route's own `require_role` (see
`tests/unit/api/routes/test_admin.py`). These tests only confirm the
shell pages and static assets actually serve, and that the path-collision
fix (moving the JSON API to `/admin/api/*`) left these routes free.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _get(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, follow_redirects=False)


@pytest.mark.asyncio
async def test_admin_root_redirects_to_conversations():
    response = await _get("/admin")

    assert response.status_code in (301, 307, 308)
    assert response.headers["location"] == "/admin/conversations"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/admin/login",
        "/admin/conversations",
        "/admin/conversations/conv-1",
        "/admin/errors",
        "/admin/errors/err-1",
        "/admin/agent",
        "/admin/kpis",
        "/admin/runs/run-1",
    ],
)
async def test_page_serves_html_with_no_auth_dependency(path: str):
    # No session cookie at all — the page shell itself must still load;
    # its own JS is what redirects to /admin/login on a failed auth check.
    response = await _get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
@pytest.mark.parametrize("asset", ["app.js", "style.css", "agent-diagram.js", "kpis.js"])
async def test_static_asset_serves(asset: str):
    response = await _get(f"/admin/static/{asset}")

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/admin/conversations/conv-1", "/admin/runs/run-1"])
async def test_detail_pages_drop_mermaid_and_link_to_the_diagram(path: str):
    response = await _get(path)

    assert response.status_code == 200
    assert "mermaid" not in response.text.lower()
    assert "graph-view" not in response.text
    assert "/admin/agent#run=" in response.text


@pytest.mark.asyncio
async def test_graph_view_asset_is_gone():
    response = await _get("/admin/static/graph-view.js")

    assert response.status_code == 404


_NAV_LINKS = [
    '<a href="/admin/conversations"',
    '<a href="/admin/errors"',
    '<a href="/admin/agent"',
    '<a href="/admin/kpis"',
    '<a href="/admin/llm-config"',
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/admin/conversations",
        "/admin/conversations/conv-1",
        "/admin/errors",
        "/admin/errors/err-1",
        "/admin/agent",
        "/admin/kpis",
        "/admin/llm-config",
        "/admin/runs/run-1",
    ],
)
async def test_nav_links_to_kpis_after_agent(path: str):
    response = await _get(path)

    assert response.status_code == 200
    positions = [response.text.index(link) for link in _NAV_LINKS]
    assert positions == sorted(positions)
    assert ">KPIs</a>" in response.text


@pytest.mark.asyncio
async def test_kpis_page_loads_its_script_and_states_the_scope():
    response = await _get("/admin/kpis")

    assert "/admin/static/kpis.js" in response.text
    assert "no incluye turnos cargados o cancelados directamente en Dentalink" in response.text
