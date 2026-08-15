# pylint: disable=missing-module-docstring,missing-function-docstring
import pytest


@pytest.mark.asyncio
async def test_create_token(client):
    resp = await client.post(
        "/api/tokens/", json={"platform": "vercel", "token": "test-vercel-token"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] == "vercel"
    assert data["configured"] is True
    assert data["created_at"] is not None


@pytest.mark.asyncio
async def test_update_existing_token(client):
    await client.post("/api/tokens/", json={"platform": "vercel", "token": "old-token"})
    resp = await client.post(
        "/api/tokens/", json={"platform": "vercel", "token": "new-token"}
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is True


@pytest.mark.asyncio
async def test_list_tokens_shows_all_platforms(client):
    await client.post("/api/tokens/", json={"platform": "netlify", "token": "my-token"})
    resp = await client.get("/api/tokens/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3  # vercel, netlify, render
    platforms = {t["platform"] for t in data}
    assert platforms == {"vercel", "netlify", "render"}
    netlify = next(t for t in data if t["platform"] == "netlify")
    assert netlify["configured"] is True
    vercel = next(t for t in data if t["platform"] == "vercel")
    assert vercel["configured"] is False


@pytest.mark.asyncio
async def test_delete_token(client):
    await client.post("/api/tokens/", json={"platform": "render", "token": "rnd-token"})
    resp = await client.delete("/api/tokens/render")
    assert resp.status_code == 200

    list_resp = await client.get("/api/tokens/")
    render = next(t for t in list_resp.json() if t["platform"] == "render")
    assert render["configured"] is False


@pytest.mark.asyncio
async def test_delete_nonexistent_token(client):
    resp = await client.delete("/api/tokens/vercel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_token_empty_value(client):
    resp = await client.post("/api/tokens/", json={"platform": "vercel", "token": "   "})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_token_invalid_platform(client):
    resp = await client.post(
        "/api/tokens/", json={"platform": "aws", "token": "some-token"}
    )
    assert resp.status_code == 422
