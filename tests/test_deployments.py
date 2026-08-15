# pylint: disable=missing-module-docstring,missing-function-docstring,invalid-name,redefined-outer-name,line-too-long,unused-argument
from unittest.mock import AsyncMock, patch

import pytest

from integrations.base import DeployResult, PartialDeployError


@pytest.fixture
def mock_deploy_result():
    return DeployResult(
        platform_deployment_id="dpl_abc123",
        url="https://my-project.vercel.app",
        status="ready",
        project_name="my-project",
    )


async def _setup_token(client, platform="vercel"):
    await client.post("/api/tokens/", json={"platform": platform, "token": "fake-token"})


@pytest.mark.asyncio
async def test_create_deployment(client, mock_deploy_result):
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "my-project"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] == "vercel"
    assert data["project_name"] == "my-project"
    assert data["url"] == "https://my-project.vercel.app"
    assert data["status"] == "ready"
    assert data["id"] is not None


@pytest.mark.asyncio
async def test_create_deployment_with_repo(client, mock_deploy_result):
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        resp = await client.post(
            "/api/deployments/",
            json={
                "platform": "vercel",
                "project_name": "my-project",
                "repo_url": "https://github.com/octocat/hello-world",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["repo_url"] == "https://github.com/octocat/hello-world"


@pytest.mark.asyncio
async def test_create_deployment_no_token(client):
    resp = await client.post(
        "/api/deployments/",
        json={"platform": "vercel", "project_name": "no-token-project"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_deployment_invalid_project_name(client):
    await _setup_token(client)
    resp = await client.post(
        "/api/deployments/",
        json={"platform": "vercel", "project_name": "My Project!"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_deployment_invalid_repo_url(client):
    await _setup_token(client)
    resp = await client.post(
        "/api/deployments/",
        json={
            "platform": "vercel",
            "project_name": "my-project",
            "repo_url": "https://bitbucket.org/owner/repo",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_deployments_empty(client):
    resp = await client.get("/api/deployments/")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_deployments(client, mock_deploy_result):
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "project-one"},
        )
    resp = await client.get("/api/deployments/")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_list_deployments_filter_by_platform(client):
    await _setup_token(client, "netlify")
    netlify_result = DeployResult(
        platform_deployment_id="site_xyz",
        url="https://site.netlify.app",
        status="ready",
        project_name="netlify-site",
    )
    with patch("routers.deployments.NetlifyClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=netlify_result)
        await client.post(
            "/api/deployments/",
            json={"platform": "netlify", "project_name": "netlify-site"},
        )

    resp = await client.get("/api/deployments/?platform=vercel")
    assert resp.status_code == 200
    assert resp.json() == []

    resp = await client.get("/api/deployments/?platform=netlify")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_get_deployment(client, mock_deploy_result):
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "fetch-me"},
        )
    dep_id = create_resp.json()["id"]

    resp = await client.get(f"/api/deployments/{dep_id}")
    assert resp.status_code == 200
    assert resp.json()["project_name"] == "fetch-me"


@pytest.mark.asyncio
async def test_get_deployment_not_found(client):
    resp = await client.get("/api/deployments/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_deployment_platform_error(client):
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(
            side_effect=Exception("API down")
        )
        resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "error-project"},
        )
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_partial_deploy_error_saves_to_db(client):
    """When GitHub isn't connected, the partial deployment is saved to the DB."""
    await _setup_token(client)
    partial = DeployResult(
        platform_deployment_id="proj_abc",
        url=None,
        status="deployment_failed",
        project_name="broken-project",
    )
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(
            side_effect=PartialDeployError("GitHub not connected", partial)
        )
        resp = await client.post(
            "/api/deployments/",
            json={
                "platform": "vercel",
                "project_name": "broken-project",
                "repo_url": "https://github.com/owner/repo",
            },
        )

    # Still a 502 so the form shows the error
    assert resp.status_code == 502

    # But the record was saved so it shows in the dashboard
    list_resp = await client.get("/api/deployments/")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["project_name"] == "broken-project"
    assert items[0]["status"] == "deployment_failed"


@pytest.mark.asyncio
async def test_delete_deployment_also_deletes_on_platform(client, mock_deploy_result):
    """Deleting a deployment should call the platform client's delete_deployment."""
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "to-delete"},
        )
    dep_id = create_resp.json()["id"]

    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.delete_deployment = AsyncMock(return_value=None)
        resp = await client.delete(f"/api/deployments/{dep_id}")

    assert resp.status_code == 200
    MockClient.return_value.delete_deployment.assert_called_once()

    resp = await client.get(f"/api/deployments/{dep_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_deployment_platform_failure_still_removes_local(client, mock_deploy_result):
    """Platform delete failure should be swallowed; local record still removed."""
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "to-delete"},
        )
    dep_id = create_resp.json()["id"]

    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.delete_deployment = AsyncMock(
            side_effect=Exception("network error")
        )
        resp = await client.delete(f"/api/deployments/{dep_id}")

    assert resp.status_code == 200
    resp = await client.get(f"/api/deployments/{dep_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_deployment_not_found(client):
    resp = await client.delete("/api/deployments/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_from_platform(client):
    """Import should pull remote projects and add ones not already tracked."""
    await _setup_token(client)
    remote_results = [
        DeployResult(
            platform_deployment_id="dpl_imported",
            url="https://imported-site.vercel.app",
            status="ready",
            project_name="imported-site",
        )
    ]
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.list_deployments = AsyncMock(return_value=remote_results)
        resp = await client.post("/api/deployments/import/vercel")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["project_name"] == "imported-site"
    assert data[0]["status"] == "ready"


@pytest.mark.asyncio
async def test_import_skips_existing(client, mock_deploy_result):
    """Import should not create duplicate records for projects already tracked."""
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "my-project"},
        )

    remote_results = [
        DeployResult(
            platform_deployment_id="dpl_abc123",
            url="https://my-project.vercel.app",
            status="ready",
            project_name="my-project",
        )
    ]
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.list_deployments = AsyncMock(return_value=remote_results)
        resp = await client.post("/api/deployments/import/vercel")

    assert resp.status_code == 200
    assert resp.json() == []  # Nothing new to import

    resp = await client.get("/api/deployments/")
    assert len(resp.json()) == 1  # Still only one record


@pytest.mark.asyncio
async def test_import_no_token(client):
    resp = await client.post("/api/deployments/import/vercel")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_connect_repo(client, mock_deploy_result):
    """PATCH /{id}/repo triggers a git deployment and updates the record."""
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "my-project"},
        )
    dep_id = create_resp.json()["id"]

    connected = DeployResult(
        platform_deployment_id="dpl_new",
        url="https://my-project.vercel.app",
        status="initializing",
        project_name="my-project",
    )
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.connect_repo = AsyncMock(return_value=connected)
        resp = await client.patch(
            f"/api/deployments/{dep_id}/repo",
            json={"repo_url": "https://github.com/owner/repo"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["repo_url"] == "https://github.com/owner/repo"
    assert data["url"] == "https://my-project.vercel.app"
    assert data["status"] == "initializing"


@pytest.mark.asyncio
async def test_connect_repo_platform_refuses(client, mock_deploy_result):
    """Platforms that don't support connect_repo return 400."""
    await _setup_token(client, "render")
    render_result = DeployResult(
        platform_deployment_id="srv_abc", url="https://x.onrender.com", status="active", project_name="x"
    )
    with patch("routers.deployments.RenderClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=render_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "render", "project_name": "x", "repo_url": "https://github.com/o/r"},
        )
    dep_id = create_resp.json()["id"]

    with patch("routers.deployments.RenderClient") as MockClient:
        MockClient.return_value.connect_repo = AsyncMock(
            side_effect=ValueError("Render does not support")
        )
        resp = await client.patch(
            f"/api/deployments/{dep_id}/repo",
            json={"repo_url": "https://github.com/owner/repo"},
        )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_connect_repo_not_found(client):
    resp = await client.patch(
        "/api/deployments/9999/repo",
        json={"repo_url": "https://github.com/owner/repo"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sync_deployment(client, mock_deploy_result):
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "to-sync"},
        )
    dep_id = create_resp.json()["id"]

    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.get_deployment_status = AsyncMock(return_value="ready")
        MockClient.return_value.get_project_url = AsyncMock(return_value=None)
        MockClient.return_value.get_project_repo_url = AsyncMock(return_value=None)
        resp = await client.post(f"/api/deployments/{dep_id}/sync")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_sync_deployment_not_found(client):
    resp = await client.post("/api/deployments/9999/sync")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sync_updates_url_from_platform(client, mock_deploy_result):
    """Sync should update the stored URL via get_project_url if the platform returns one."""
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "my-project"},
        )
    dep_id = create_resp.json()["id"]

    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.get_deployment_status = AsyncMock(return_value="ready")
        MockClient.return_value.get_project_url = AsyncMock(
            return_value="https://my-project-team.vercel.app"
        )
        MockClient.return_value.get_project_repo_url = AsyncMock(return_value=None)
        resp = await client.post(f"/api/deployments/{dep_id}/sync")

    assert resp.status_code == 200
    assert resp.json()["url"] == "https://my-project-team.vercel.app"


@pytest.mark.asyncio
async def test_import_includes_repo_url(client):
    """Import should preserve the repo_url from the platform when available."""
    await _setup_token(client)
    remote_results = [
        DeployResult(
            platform_deployment_id="dpl_imported",
            url="https://imported.vercel.app",
            status="ready",
            project_name="imported-site",
            repo_url="https://github.com/owner/imported-repo",
        )
    ]
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.list_deployments = AsyncMock(return_value=remote_results)
        resp = await client.post("/api/deployments/import/vercel")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["repo_url"] == "https://github.com/owner/imported-repo"


@pytest.mark.asyncio
async def test_sync_deployment_platform_error(client, mock_deploy_result):
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "sync-error"},
        )
    dep_id = create_resp.json()["id"]

    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.get_deployment_status = AsyncMock(
            side_effect=Exception("platform down")
        )
        MockClient.return_value.get_project_url = AsyncMock(return_value=None)
        MockClient.return_value.get_project_repo_url = AsyncMock(return_value=None)
        resp = await client.post(f"/api/deployments/{dep_id}/sync")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_sync_updates_repo_url_from_platform(client, mock_deploy_result):
    """Sync should backfill repo_url via get_project_repo_url when it is unset."""
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "my-project"},
        )
    dep_id = create_resp.json()["id"]
    assert create_resp.json()["repo_url"] is None

    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.get_deployment_status = AsyncMock(return_value="ready")
        MockClient.return_value.get_project_url = AsyncMock(return_value=None)
        MockClient.return_value.get_project_repo_url = AsyncMock(
            return_value="https://github.com/owner/my-repo"
        )
        resp = await client.post(f"/api/deployments/{dep_id}/sync")

    assert resp.status_code == 200
    assert resp.json()["repo_url"] == "https://github.com/owner/my-repo"


@pytest.mark.asyncio
async def test_redeploy_deployment(client, mock_deploy_result):
    """Redeploy endpoint triggers a new deployment and updates status/ID."""
    await _setup_token(client)
    redeploy_result = DeployResult(
        platform_deployment_id="dpl_new456",
        url=None,
        status="initializing",
        project_name="my-project",
    )
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "my-project"},
        )
    dep_id = create_resp.json()["id"]

    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.redeploy = AsyncMock(return_value=redeploy_result)
        resp = await client.post(f"/api/deployments/{dep_id}/redeploy")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "initializing"
    assert data["platform_deployment_id"] == "dpl_new456"


@pytest.mark.asyncio
async def test_redeploy_deployment_not_found(client):
    resp = await client.post("/api/deployments/9999/redeploy")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_redeploy_deployment_platform_error(client, mock_deploy_result):
    """A ValueError from the platform client surfaces as a 400."""
    await _setup_token(client)
    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.create_deployment = AsyncMock(return_value=mock_deploy_result)
        create_resp = await client.post(
            "/api/deployments/",
            json={"platform": "vercel", "project_name": "my-project"},
        )
    dep_id = create_resp.json()["id"]

    with patch("routers.deployments.VercelClient") as MockClient:
        MockClient.return_value.redeploy = AsyncMock(
            side_effect=ValueError("A GitHub repo URL is required to redeploy on Vercel.")
        )
        resp = await client.post(f"/api/deployments/{dep_id}/redeploy")

    assert resp.status_code == 400
    assert "repo URL" in resp.json()["detail"]
