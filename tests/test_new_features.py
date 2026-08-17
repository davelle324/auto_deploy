# pylint: disable=missing-module-docstring,missing-function-docstring,invalid-name,redefined-outer-name,line-too-long,unused-argument,unused-import,import-outside-toplevel
import json
from unittest.mock import AsyncMock, patch

import pytest

from integrations.base import DeployResult


@pytest.fixture
def mock_result():
    return DeployResult(
        platform_deployment_id="dpl_abc",
        url="https://test.vercel.app",
        status="ready",
        project_name="test-proj",
    )


async def _seed_deployment(client, platform="vercel"):
    await client.post("/api/tokens/", json={"platform": platform, "token": "tok"})
    with patch("routers.deployments.VercelClient" if platform == "vercel"
               else f"routers.deployments.{'NetlifyClient' if platform == 'netlify' else 'RenderClient'}") as MC:
        MC.return_value.create_deployment = AsyncMock(return_value=DeployResult(
            platform_deployment_id="dpl_abc", url="https://x.vercel.app",
            status="ready", project_name="test-proj",
        ))
        resp = await client.post(
            "/api/deployments/",
            json={"platform": platform, "project_name": "test-proj"},
        )
    return resp.json()["id"]


# ---- Untrack (local-only delete) ----

@pytest.mark.asyncio
async def test_untrack_removes_locally(client):
    dep_id = await _seed_deployment(client)
    resp = await client.delete(f"/api/deployments/{dep_id}/untrack")
    assert resp.status_code == 200
    assert "untouched" in resp.json()["message"]
    list_resp = await client.get("/api/deployments/")
    assert all(d["id"] != dep_id for d in list_resp.json())


@pytest.mark.asyncio
async def test_untrack_not_found(client):
    resp = await client.delete("/api/deployments/9999/untrack")
    assert resp.status_code == 404


# ---- Logs ----

@pytest.mark.asyncio
async def test_get_logs_returns_lines(client):
    dep_id = await _seed_deployment(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.get_deployment_logs = AsyncMock(return_value=["Line 1", "Line 2"])
        resp = await client.get(f"/api/deployments/{dep_id}/logs")
    assert resp.status_code == 200
    assert resp.json()["lines"] == ["Line 1", "Line 2"]


@pytest.mark.asyncio
async def test_get_logs_pending_returns_empty(client):
    await client.post("/api/tokens/", json={"platform": "vercel", "token": "tok"})
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.create_deployment = AsyncMock(return_value=DeployResult(
            platform_deployment_id="pending", url=None, status="pending", project_name="pp",
        ))
        create = await client.post("/api/deployments/", json={"platform": "vercel", "project_name": "pp"})
    dep_id = create.json()["id"]
    resp = await client.get(f"/api/deployments/{dep_id}/logs")
    assert resp.status_code == 200
    assert resp.json()["lines"] == []


@pytest.mark.asyncio
async def test_get_logs_not_found(client):
    resp = await client.get("/api/deployments/9999/logs")
    assert resp.status_code == 404


# ---- History ----

@pytest.mark.asyncio
async def test_history_recorded_on_create(client):
    dep_id = await _seed_deployment(client)
    resp = await client.get(f"/api/deployments/{dep_id}/history")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["deployment_id"] == dep_id
    assert events[0]["status"] == "ready"


@pytest.mark.asyncio
async def test_history_recorded_on_redeploy(client):
    dep_id = await _seed_deployment(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.redeploy = AsyncMock(return_value=DeployResult(
            platform_deployment_id="dpl_new", url=None, status="initializing", project_name="test-proj",
        ))
        await client.post(f"/api/deployments/{dep_id}/redeploy")
    resp = await client.get(f"/api/deployments/{dep_id}/history")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_history_not_found(client):
    resp = await client.get("/api/deployments/9999/history")
    assert resp.status_code == 404


# ---- Env vars ----

@pytest.mark.asyncio
async def test_list_env_vars(client):
    dep_id = await _seed_deployment(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.list_env_vars = AsyncMock(return_value=[{"key": "FOO", "value": "bar"}])
        resp = await client.get(f"/api/deployments/{dep_id}/env")
    assert resp.status_code == 200
    assert resp.json()["env_vars"] == [{"key": "FOO", "value": "bar"}]


@pytest.mark.asyncio
async def test_set_env_vars(client):
    dep_id = await _seed_deployment(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.set_env_vars = AsyncMock(return_value=None)
        resp = await client.put(
            f"/api/deployments/{dep_id}/env",
            json={"env_vars": [{"key": "FOO", "value": "bar"}]},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_env_var(client):
    dep_id = await _seed_deployment(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.delete_env_var = AsyncMock(return_value=None)
        resp = await client.delete(f"/api/deployments/{dep_id}/env/FOO")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_env_vars_no_token(client):
    await client.post("/api/tokens/", json={"platform": "vercel", "token": "tok"})
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.create_deployment = AsyncMock(return_value=DeployResult(
            platform_deployment_id="dpl_abc", url=None, status="ready", project_name="p2",
        ))
        create = await client.post("/api/deployments/", json={"platform": "vercel", "project_name": "p2"})
    dep_id = create.json()["id"]
    await client.delete("/api/tokens/vercel")
    resp = await client.get(f"/api/deployments/{dep_id}/env")
    assert resp.status_code == 400


# ---- Domains ----

@pytest.mark.asyncio
async def test_list_domains(client):
    dep_id = await _seed_deployment(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.list_domains = AsyncMock(return_value=["example.com"])
        resp = await client.get(f"/api/deployments/{dep_id}/domains")
    assert resp.status_code == 200
    assert resp.json()["domains"] == ["example.com"]


@pytest.mark.asyncio
async def test_add_domain(client):
    dep_id = await _seed_deployment(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.add_domain = AsyncMock(return_value=None)
        resp = await client.post(
            f"/api/deployments/{dep_id}/domains",
            json={"domain": "example.com"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_remove_domain(client):
    dep_id = await _seed_deployment(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.remove_domain = AsyncMock(return_value=None)
        resp = await client.delete(f"/api/deployments/{dep_id}/domains/example.com")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_domains_no_token(client):
    await client.post("/api/tokens/", json={"platform": "vercel", "token": "tok"})
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.create_deployment = AsyncMock(return_value=DeployResult(
            platform_deployment_id="dpl_abc", url=None, status="ready", project_name="p3",
        ))
        create = await client.post("/api/deployments/", json={"platform": "vercel", "project_name": "p3"})
    dep_id = create.json()["id"]
    await client.delete("/api/tokens/vercel")
    resp = await client.get(f"/api/deployments/{dep_id}/domains")
    assert resp.status_code == 400


# ---- Webhooks ----

@pytest.mark.asyncio
async def test_vercel_webhook_updates_status(client):
    dep_id = await _seed_deployment(client)
    payload = {
        "type": "deployment.ready",
        "deployment": {"id": "dpl_abc"},
    }
    resp = await client.post("/api/webhook/vercel", json=payload)
    assert resp.status_code == 200
    assert resp.json()["received"] is True
    dep = await client.get(f"/api/deployments/{dep_id}")
    assert dep.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_netlify_webhook_updates_status(client):
    await client.post("/api/tokens/", json={"platform": "netlify", "token": "tok"})
    with patch("routers.deployments.NetlifyClient") as MC:
        MC.return_value.create_deployment = AsyncMock(return_value=DeployResult(
            platform_deployment_id="site_abc", url=None, status="ready", project_name="nl-proj",
        ))
        create = await client.post(
            "/api/deployments/", json={"platform": "netlify", "project_name": "nl-proj"}
        )
    dep_id = create.json()["id"]

    payload = {"event": "deploy_building", "site_id": "site_abc", "id": "deploy_123"}
    resp = await client.post("/api/webhook/netlify", json=payload)
    assert resp.status_code == 200
    dep = await client.get(f"/api/deployments/{dep_id}")
    assert dep.json()["status"] == "building"


@pytest.mark.asyncio
async def test_render_webhook_updates_status(client):
    await client.post("/api/tokens/", json={"platform": "render", "token": "tok"})
    with patch("routers.deployments.RenderClient") as MC:
        MC.return_value.create_deployment = AsyncMock(return_value=DeployResult(
            platform_deployment_id="svc_abc", url=None, status="deploying", project_name="rn-proj",
        ))
        create = await client.post(
            "/api/deployments/", json={"platform": "render", "project_name": "rn-proj"}
        )
    dep_id = create.json()["id"]

    payload = {"service": {"id": "svc_abc"}, "deploy": {"id": "dep_1", "status": "live"}}
    resp = await client.post("/api/webhook/render", json=payload)
    assert resp.status_code == 200
    dep = await client.get(f"/api/deployments/{dep_id}")
    assert dep.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_webhook_unknown_deployment_ignored(client):
    payload = {"type": "deployment.ready", "deployment": {"id": "unknown_id_xyz"}}
    resp = await client.post("/api/webhook/vercel", json=payload)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_invalid_json(client):
    resp = await client.post(
        "/api/webhook/vercel",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


# ---- Base client defaults ----

@pytest.mark.asyncio
async def test_base_client_log_default():
    from integrations.base import BasePlatformClient
    class _Stub(BasePlatformClient):
        async def create_deployment(self, *a, **kw): ...
        async def list_deployments(self): ...
        async def delete_deployment(self, *a, **kw): ...
        async def connect_repo(self, *a, **kw): ...
        async def get_deployment_status(self, *a): ...
    stub = _Stub()
    assert await stub.get_deployment_logs("x", "y") == []


@pytest.mark.asyncio
async def test_base_client_env_var_default():
    from integrations.base import BasePlatformClient
    class _Stub(BasePlatformClient):
        async def create_deployment(self, *a, **kw): ...
        async def list_deployments(self): ...
        async def delete_deployment(self, *a, **kw): ...
        async def connect_repo(self, *a, **kw): ...
        async def get_deployment_status(self, *a): ...
    stub = _Stub()
    assert await stub.list_env_vars("x", "y") == []
    with pytest.raises(ValueError):
        await stub.set_env_vars("x", "y", [])
    with pytest.raises(ValueError):
        await stub.delete_env_var("x", "y", "K")


@pytest.mark.asyncio
async def test_base_client_domain_default():
    from integrations.base import BasePlatformClient
    class _Stub(BasePlatformClient):
        async def create_deployment(self, *a, **kw): ...
        async def list_deployments(self): ...
        async def delete_deployment(self, *a, **kw): ...
        async def connect_repo(self, *a, **kw): ...
        async def get_deployment_status(self, *a): ...
    stub = _Stub()
    assert await stub.list_domains("x", "y") == []
    with pytest.raises(ValueError):
        await stub.add_domain("x", "y", "z")
    with pytest.raises(ValueError):
        await stub.remove_domain("x", "y", "z")
