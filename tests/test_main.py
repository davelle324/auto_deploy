# pylint: disable=missing-module-docstring,missing-function-docstring
import pytest


@pytest.mark.asyncio
async def test_dashboard_renders(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_deploy_page_renders(client):
    resp = await client.get("/deploy")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_settings_page_renders(client):
    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
