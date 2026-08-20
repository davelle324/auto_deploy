# pylint: disable=missing-module-docstring,missing-function-docstring
import pytest

import routers.demo as _demo_module


@pytest.fixture(autouse=True)
def _reset_state():
    _demo_module._reset_demo_state()  # pylint: disable=protected-access
    yield


# ── Tokens ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_list_tokens(client):
    resp = await client.get("/demo/api/tokens/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all(t["configured"] for t in data)


@pytest.mark.asyncio
async def test_demo_upsert_token(client):
    resp = await client.post("/demo/api/tokens/", json={"platform": "vercel", "token": "tok_x"})
    assert resp.status_code == 200
    assert resp.json()["platform"] == "vercel"
    assert resp.json()["configured"] is True


@pytest.mark.asyncio
async def test_demo_delete_token(client):
    resp = await client.delete("/demo/api/tokens/vercel")
    assert resp.status_code == 200
    assert "vercel" in resp.json()["message"]


# ── Projects ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_list_projects(client):
    resp = await client.get("/demo/api/projects/")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_demo_create_project(client):
    resp = await client.post("/demo/api/projects/", json={"name": "My Project"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "My Project"


@pytest.mark.asyncio
async def test_demo_delete_project(client):
    resp = await client.delete("/demo/api/projects/1")
    assert resp.status_code == 200
    assert "1" in resp.json()["message"]


# ── Deployments — list / create / import ─────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_list_deployments(client):
    resp = await client.get("/demo/api/deployments/")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_demo_list_deployments_filtered(client):
    resp = await client.get("/demo/api/deployments/?platform=vercel")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["platform"] == "vercel"


@pytest.mark.asyncio
async def test_demo_create_deployment(client):
    resp = await client.post(
        "/demo/api/deployments/",
        json={"platform": "netlify", "project_name": "new-site"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] == "netlify"
    assert data["project_name"] == "new-site"
    assert "netlify.app" in data["url"]
    assert data["status"] == "deploying"


@pytest.mark.asyncio
async def test_demo_create_deployment_unknown_platform_fallback_url(client):
    resp = await client.post(
        "/demo/api/deployments/",
        json={"platform": "unknown", "project_name": "my-proj"},
    )
    assert resp.status_code == 200
    assert "vercel.app" in resp.json()["url"]


@pytest.mark.asyncio
async def test_demo_import_from_platform(client):
    resp = await client.post("/demo/api/deployments/import/vercel")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Deployments — parameterised actions ──────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_redeploy(client):
    resp = await client.post("/demo/api/deployments/1/redeploy")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deploying"


@pytest.mark.asyncio
async def test_demo_get_dep_not_found(client):
    resp = await client.post("/demo/api/deployments/999/redeploy")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_demo_sync_vercel(client):
    resp = await client.post("/demo/api/deployments/1/sync")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_demo_sync_render(client):
    resp = await client.post("/demo/api/deployments/3/sync")
    assert resp.status_code == 200
    assert resp.json()["status"] == "live"


@pytest.mark.asyncio
async def test_demo_logs(client):
    resp = await client.get("/demo/api/deployments/1/logs")
    assert resp.status_code == 200
    assert len(resp.json()["lines"]) > 0


@pytest.mark.asyncio
async def test_demo_history(client):
    resp = await client.get("/demo/api/deployments/1/history")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_demo_connect_repo(client):
    resp = await client.patch(
        "/demo/api/deployments/1/repo",
        json={"repo_url": "https://github.com/user/repo"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "deploying"
    assert data["repo_url"] == "https://github.com/user/repo"


@pytest.mark.asyncio
async def test_demo_assign_project(client):
    resp = await client.patch("/demo/api/deployments/1/project", json={"project_id": 2})
    assert resp.status_code == 200
    assert resp.json()["project_id"] == 2


@pytest.mark.asyncio
async def test_demo_build_settings_get(client):
    resp = await client.get("/demo/api/deployments/3/build")
    assert resp.status_code == 200
    assert "build_command" in resp.json()


@pytest.mark.asyncio
async def test_demo_build_settings_patch(client):
    resp = await client.patch(
        "/demo/api/deployments/3/build",
        json={"build_command": "npm run build", "apply_cors": True},
    )
    assert resp.status_code == 200
    assert "message" in resp.json()


@pytest.mark.asyncio
async def test_demo_set_type(client):
    resp = await client.patch("/demo/api/deployments/1/type", json={"deployment_type": "backend"})
    assert resp.status_code == 200
    assert resp.json()["deployment_type"] == "backend"


@pytest.mark.asyncio
async def test_demo_set_notes(client):
    resp = await client.patch("/demo/api/deployments/1/notes", json={"notes": "Test note"})
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Test note"


@pytest.mark.asyncio
async def test_demo_ping(client):
    resp = await client.get("/demo/api/deployments/1/ping")
    assert resp.status_code == 200
    data = resp.json()
    assert data["up"] is True
    assert data["response_ms"] == 42


@pytest.mark.asyncio
async def test_demo_untrack(client):
    resp = await client.delete("/demo/api/deployments/1/untrack")
    assert resp.status_code == 200
    assert "tracking" in resp.json()["message"]


@pytest.mark.asyncio
async def test_demo_delete_deployment(client):
    resp = await client.delete("/demo/api/deployments/1")
    assert resp.status_code == 200
    assert "message" in resp.json()


# ── Env vars ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_list_env(client):
    resp = await client.get("/demo/api/deployments/1/env")
    assert resp.status_code == 200
    assert "env_vars" in resp.json()
    assert len(resp.json()["env_vars"]) > 0


@pytest.mark.asyncio
async def test_demo_set_env(client):
    resp = await client.put(
        "/demo/api/deployments/1/env",
        json={"env_vars": [{"key": "TEST", "value": "1"}]},
    )
    assert resp.status_code == 200
    assert "message" in resp.json()


@pytest.mark.asyncio
async def test_demo_delete_env(client):
    resp = await client.delete("/demo/api/deployments/1/env/MY_KEY")
    assert resp.status_code == 200
    assert "MY_KEY" in resp.json()["message"]


# ── Domains ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_list_domains(client):
    resp = await client.get("/demo/api/deployments/1/domains")
    assert resp.status_code == 200
    data = resp.json()
    assert "domains" in data
    assert "platform_url" in data


@pytest.mark.asyncio
async def test_demo_add_domain(client):
    resp = await client.post(
        "/demo/api/deployments/1/domains",
        json={"domain": "example.com"},
    )
    assert resp.status_code == 200
    assert "example.com" in resp.json()["message"]


@pytest.mark.asyncio
async def test_demo_remove_domain(client):
    resp = await client.delete("/demo/api/deployments/1/domains/example.com")
    assert resp.status_code == 200
    assert "example.com" in resp.json()["message"]


# ── Demo page routes ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_dashboard_page(client):
    resp = await client.get("/demo")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_demo_deploy_page(client):
    resp = await client.get("/demo/deploy")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_demo_settings_page(client):
    resp = await client.get("/demo/settings")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ── Stateful behaviour ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_create_deployment_appears_in_list(client):
    await client.post(
        "/demo/api/deployments/", json={"platform": "vercel", "project_name": "new-site"}
    )
    resp = await client.get("/demo/api/deployments/")
    assert len(resp.json()) == 4


@pytest.mark.asyncio
async def test_demo_delete_deployment_removes_from_list(client):
    await client.delete("/demo/api/deployments/1")
    resp = await client.get("/demo/api/deployments/")
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_demo_untrack_removes_from_list(client):
    await client.delete("/demo/api/deployments/1/untrack")
    resp = await client.get("/demo/api/deployments/")
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_demo_create_project_appears_in_list(client):
    await client.post("/demo/api/projects/", json={"name": "New Project"})
    resp = await client.get("/demo/api/projects/")
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_demo_delete_project_removes_from_list(client):
    await client.delete("/demo/api/projects/1")
    resp = await client.get("/demo/api/projects/")
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_demo_reset_restores_seed_data(client):
    await client.post("/demo/api/deployments/", json={"platform": "vercel", "project_name": "x"})
    assert len((await client.get("/demo/api/deployments/")).json()) == 4
    resp = await client.post("/demo/api/reset")
    assert resp.status_code == 200
    assert len((await client.get("/demo/api/deployments/")).json()) == 3
