# pylint: disable=missing-module-docstring,missing-function-docstring,line-too-long,invalid-name
from unittest.mock import AsyncMock, patch

import pytest

from integrations.base import DeployResult


async def _setup_token(client, platform="render"):
    await client.post("/api/tokens/", json={"platform": platform, "token": "fake-token"})


async def _create_render_deployment(client, name="site-a"):
    """Create a Render deployment (no repo → requires_repo, no platform call needed)."""
    await _setup_token(client)
    mock_result = DeployResult(
        platform_deployment_id="pending", url=None,
        status="requires_repo", project_name=name,
    )
    with patch("routers.deployments.RenderClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_result)
        resp = await client.post("/api/deployments/", json={"platform": "render", "project_name": name})
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_create_project(client):
    resp = await client.post("/api/projects/", json={"name": "My App"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My App"
    assert data["id"] > 0


@pytest.mark.asyncio
async def test_create_project_empty_name_rejected(client):
    resp = await client.post("/api/projects/", json={"name": "   "})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_projects(client):
    await client.post("/api/projects/", json={"name": "Alpha"})
    await client.post("/api/projects/", json={"name": "Beta"})
    resp = await client.get("/api/projects/")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "Alpha" in names and "Beta" in names


@pytest.mark.asyncio
async def test_delete_project(client):
    created = (await client.post("/api/projects/", json={"name": "Temp"})).json()
    resp = await client.delete(f"/api/projects/{created['id']}")
    assert resp.status_code == 200
    projects = (await client.get("/api/projects/")).json()
    assert not any(p["id"] == created["id"] for p in projects)


@pytest.mark.asyncio
async def test_delete_project_not_found(client):
    resp = await client.delete("/api/projects/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_project_unassigns_deployments(client):
    proj = (await client.post("/api/projects/", json={"name": "Group"})).json()
    dep = await _create_render_deployment(client, "dep-one")

    # Assign to project
    assign = await client.patch(f"/api/deployments/{dep['id']}/project", json={"project_id": proj["id"]})
    assert assign.status_code == 200
    assert assign.json()["project_id"] == proj["id"]

    # Delete project — deployment should be unassigned
    await client.delete(f"/api/projects/{proj['id']}")
    deps = (await client.get("/api/deployments/")).json()
    found = next(d for d in deps if d["id"] == dep["id"])
    assert found["project_id"] is None


@pytest.mark.asyncio
async def test_assign_deployment_to_project(client):
    dep = await _create_render_deployment(client, "site-a")
    proj = (await client.post("/api/projects/", json={"name": "Full Stack"})).json()

    resp = await client.patch(f"/api/deployments/{dep['id']}/project", json={"project_id": proj["id"]})
    assert resp.status_code == 200
    assert resp.json()["project_id"] == proj["id"]


@pytest.mark.asyncio
async def test_unassign_deployment_from_project(client):
    dep = await _create_render_deployment(client, "site-b")
    proj = (await client.post("/api/projects/", json={"name": "Another"})).json()

    await client.patch(f"/api/deployments/{dep['id']}/project", json={"project_id": proj["id"]})
    resp = await client.patch(f"/api/deployments/{dep['id']}/project", json={"project_id": None})
    assert resp.status_code == 200
    assert resp.json()["project_id"] is None


@pytest.mark.asyncio
async def test_assign_to_nonexistent_project(client):
    dep = await _create_render_deployment(client, "site-c")
    resp = await client.patch(f"/api/deployments/{dep['id']}/project", json={"project_id": 9999})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_assign_nonexistent_deployment(client):
    await client.post("/api/projects/", json={"name": "Some Project"})
    resp = await client.patch("/api/deployments/9999/project", json={"project_id": None})
    assert resp.status_code == 404
