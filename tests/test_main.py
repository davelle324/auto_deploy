# pylint: disable=missing-module-docstring,missing-function-docstring
import sqlite3

import pytest

from config import settings
from database import _set_sqlite_pragma


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


# =============================================================================
# database.py — _set_sqlite_pragma event listener (lines 15-19)
# =============================================================================

def test_sqlite_pragma_event_listener():
    conn = sqlite3.connect(":memory:")
    _set_sqlite_pragma(conn, None)
    conn.close()


# =============================================================================
# main.py — AuthMiddleware (lines 32-39) and login page/submit (lines 67-78)
# =============================================================================

@pytest.mark.asyncio
async def test_login_page_redirects_when_no_password(client):
    resp = await client.get("/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].endswith("/")


@pytest.mark.asyncio
async def test_login_page_renders_when_password_set(client):
    old = settings.app_password
    settings.app_password = "testpass"
    try:
        resp = await client.get("/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
    finally:
        settings.app_password = old


@pytest.mark.asyncio
async def test_login_page_redirects_when_already_authenticated(client):
    old = settings.app_password
    settings.app_password = "testpass"
    try:
        await client.post("/login", data={"password": "testpass"})
        resp = await client.get("/login", follow_redirects=False)
        assert resp.status_code in (302, 307)
    finally:
        settings.app_password = old


@pytest.mark.asyncio
async def test_login_submit_correct_password(client):
    old = settings.app_password
    settings.app_password = "testpass"
    try:
        resp = await client.post("/login", data={"password": "testpass"}, follow_redirects=False)
        assert resp.status_code == 303
    finally:
        settings.app_password = old


@pytest.mark.asyncio
async def test_login_submit_wrong_password(client):
    old = settings.app_password
    settings.app_password = "testpass"
    try:
        resp = await client.post("/login", data={"password": "wrong"})
        assert resp.status_code == 401
    finally:
        settings.app_password = old


@pytest.mark.asyncio
async def test_auth_middleware_api_unauthenticated_returns_401(client):
    old = settings.app_password
    settings.app_password = "testpass"
    try:
        resp = await client.get("/api/deployments/")
        assert resp.status_code == 401
    finally:
        settings.app_password = old


@pytest.mark.asyncio
async def test_auth_middleware_html_unauthenticated_redirects(client):
    old = settings.app_password
    settings.app_password = "testpass"
    try:
        resp = await client.get("/", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "/demo" in resp.headers["location"]
    finally:
        settings.app_password = old


@pytest.mark.asyncio
async def test_auth_middleware_static_path_passes_through(client):
    old = settings.app_password
    settings.app_password = "testpass"
    try:
        resp = await client.get("/static/style.css")
        assert resp.status_code in (200, 404)
    finally:
        settings.app_password = old


@pytest.mark.asyncio
async def test_auth_middleware_authenticated_passes_through(client):
    old = settings.app_password
    settings.app_password = "testpass"
    try:
        await client.post("/login", data={"password": "testpass"})
        resp = await client.get("/api/deployments/")
        assert resp.status_code == 200
    finally:
        settings.app_password = old


@pytest.mark.asyncio
async def test_logout_clears_session(client):
    old = settings.app_password
    settings.app_password = "testpass"
    try:
        await client.post("/login", data={"password": "testpass"})
        assert (await client.get("/api/deployments/")).status_code == 200
        resp = await client.get("/logout", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "/demo" in resp.headers["location"]
        assert (await client.get("/api/deployments/")).status_code == 401
    finally:
        settings.app_password = old
