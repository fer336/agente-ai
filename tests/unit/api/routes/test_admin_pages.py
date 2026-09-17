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
@pytest.mark.parametrize("asset", ["app.js", "style.css"])
async def test_static_asset_serves(asset: str):
    response = await _get(f"/admin/static/{asset}")

    assert response.status_code == 200
