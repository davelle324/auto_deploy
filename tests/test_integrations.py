from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.base import PartialDeployError
from integrations.netlify import NetlifyClient
from integrations.render import RenderClient
from integrations.vercel import VercelClient


def _mock_response(json_data, status_code: int = 200):
    mock = MagicMock()
    mock.json.return_value = json_data
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    return mock


def _make_async_client(
    post_side_effect=None,
    put_return=None,
    get_return=None,
    delete_return=None,
):
    """Build a mock httpx.AsyncClient with configurable method responses."""
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    if post_side_effect is not None:
        mock.post = AsyncMock(side_effect=post_side_effect)
    if put_return is not None:
        mock.put = AsyncMock(return_value=put_return)
    if get_return is not None:
        mock.get = AsyncMock(return_value=get_return)
    if delete_return is not None:
        mock.delete = AsyncMock(return_value=delete_return)
    return mock


# ---------------------------------------------------------------------------
# Vercel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vercel_create_deployment_no_repo():
    project_resp = _mock_response({"id": "proj_abc", "name": "my-site"})
    deploy_resp = _mock_response({
        "id": "dpl_xyz",
        "url": "my-site.vercel.app",
        "readyState": "INITIALIZING",
    })
    upload_resp = _mock_response({}, status_code=200)

    mock_client = _make_async_client(
        post_side_effect=[project_resp, deploy_resp],
        put_return=upload_resp,
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment("my-site")

    assert result.platform_deployment_id == "dpl_xyz"
    assert result.url == "https://my-site.vercel.app"
    assert result.status == "initializing"
    mock_client.put.assert_called_once()


@pytest.mark.asyncio
async def test_vercel_create_deployment_no_repo_file_already_uploaded():
    """A 409 from the file upload (already exists) should not raise."""
    project_resp = _mock_response({"id": "proj_abc", "name": "my-site"})
    deploy_resp = _mock_response({"id": "dpl_xyz", "url": "my-site.vercel.app", "readyState": "READY"})
    upload_resp = _mock_response({}, status_code=409)

    mock_client = _make_async_client(
        post_side_effect=[project_resp, deploy_resp],
        put_return=upload_resp,
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment("my-site")

    assert result.status == "ready"


@pytest.mark.asyncio
async def test_vercel_create_deployment_with_repo():
    project_resp = _mock_response({"id": "proj_abc", "name": "my-site"})
    deploy_resp = _mock_response({
        "id": "dpl_git",
        "url": "my-site-git.vercel.app",
        "readyState": "READY",
    })

    mock_client = _make_async_client(post_side_effect=[project_resp, deploy_resp])

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment(
            "my-site", repo_url="https://github.com/octocat/hello"
        )

    assert result.status == "ready"
    body = mock_client.post.call_args_list[1].kwargs["json"]
    assert "gitSource" in body
    assert body["gitSource"]["org"] == "octocat"
    assert body["gitSource"]["repo"] == "hello"


@pytest.mark.asyncio
async def test_vercel_github_not_connected_raises_partial_deploy_error():
    """GitHub deployment failure raises PartialDeployError with project kept on Vercel."""
    project_resp = _mock_response({"id": "proj_abc", "name": "my-site"})
    github_error_resp = _mock_response(
        {"error": {"code": "incorrect_git_source_info", "message": "repo not found"}},
        status_code=400,
    )

    mock_client = _make_async_client(
        post_side_effect=[project_resp, github_error_resp],
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(PartialDeployError) as exc_info:
            await VercelClient("fake-token").create_deployment(
                "my-site", repo_url="https://github.com/owner/private-repo"
            )

    assert "Vercel GitHub App" in str(exc_info.value)
    assert exc_info.value.partial_result.status == "deployment_failed"
    assert exc_info.value.partial_result.project_name == "my-site"
    # Project should NOT be deleted — it stays on Vercel so the user can fix it
    mock_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_vercel_get_deployment_status():
    status_resp = _mock_response({"readyState": "READY"})
    mock_client = _make_async_client(get_return=status_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        status = await VercelClient("fake-token").get_deployment_status("dpl_xyz")

    assert status == "ready"


@pytest.mark.asyncio
async def test_vercel_get_deployment_status_not_found():
    not_found_resp = _mock_response({}, status_code=404)
    mock_client = _make_async_client(get_return=not_found_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        status = await VercelClient("fake-token").get_deployment_status("dpl_gone")

    assert status == "not_found"


@pytest.mark.asyncio
async def test_vercel_list_deployments():
    list_resp = _mock_response({
        "projects": [
            {
                "id": "proj_abc",
                "name": "my-site",
                "latestDeployments": [
                    {"id": "dpl_xyz", "url": "my-site.vercel.app", "readyState": "READY"}
                ],
            }
        ]
    })
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        results = await VercelClient("fake-token").list_deployments()

    assert len(results) == 1
    assert results[0].project_name == "my-site"
    assert results[0].status == "ready"
    assert results[0].url == "https://my-site.vercel.app"


@pytest.mark.asyncio
async def test_vercel_delete_deployment():
    delete_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete_return=delete_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        await VercelClient("fake-token").delete_deployment("dpl_xyz", "my-site")

    mock_client.delete.assert_called_once()
    assert "my-site" in mock_client.delete.call_args.args[0]


# ---------------------------------------------------------------------------
# Netlify
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_netlify_create_deployment():
    site_resp = _mock_response({
        "id": "site_netlify123",
        "ssl_url": "https://my-site.netlify.app",
        "url": "http://my-site.netlify.app",
        "state": "current",
    })
    mock_client = _make_async_client(post_side_effect=[site_resp])

    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        result = await NetlifyClient("fake-token").create_deployment("my-site")

    assert result.platform_deployment_id == "site_netlify123"
    assert result.url == "https://my-site.netlify.app"
    assert result.status == "current"


@pytest.mark.asyncio
async def test_netlify_create_deployment_with_repo():
    site_resp = _mock_response({"id": "site_git456", "ssl_url": "https://repo-site.netlify.app", "state": "building"})
    mock_client = _make_async_client(post_side_effect=[site_resp])

    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        result = await NetlifyClient("fake-token").create_deployment(
            "repo-site", repo_url="https://github.com/owner/repo"
        )

    body = mock_client.post.call_args.kwargs["json"]
    assert "repo" in body
    assert body["repo"]["repo"] == "owner/repo"
    assert result.status == "building"


@pytest.mark.asyncio
async def test_netlify_get_deployment_status():
    status_resp = _mock_response({"state": "current"})
    mock_client = _make_async_client(get_return=status_resp)

    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        status = await NetlifyClient("fake-token").get_deployment_status("site_abc")

    assert status == "current"


@pytest.mark.asyncio
async def test_netlify_get_deployment_status_not_found():
    not_found_resp = _mock_response({}, status_code=404)
    mock_client = _make_async_client(get_return=not_found_resp)

    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        status = await NetlifyClient("fake-token").get_deployment_status("gone")

    assert status == "not_found"


@pytest.mark.asyncio
async def test_netlify_list_deployments():
    list_resp = _mock_response([
        {"id": "site_abc", "name": "my-site", "ssl_url": "https://my-site.netlify.app", "state": "current"}
    ])
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        results = await NetlifyClient("fake-token").list_deployments()

    assert len(results) == 1
    assert results[0].project_name == "my-site"
    assert results[0].status == "current"


@pytest.mark.asyncio
async def test_netlify_delete_deployment():
    delete_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete_return=delete_resp)

    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        await NetlifyClient("fake-token").delete_deployment("site_abc", "my-site")

    mock_client.delete.assert_called_once()
    assert "site_abc" in mock_client.delete.call_args.args[0]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_render_create_deployment_no_repo():
    result = await RenderClient("fake-token").create_deployment("my-site", repo_url=None)
    assert result.status == "requires_repo"
    assert result.url is None


@pytest.mark.asyncio
async def test_render_create_deployment_with_repo():
    service_resp = _mock_response({
        "service": {"id": "srv_render789", "serviceDetails": {"url": "my-site.onrender.com"}}
    })
    mock_client = _make_async_client(post_side_effect=[service_resp])

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        result = await RenderClient("fake-token").create_deployment(
            "my-site", repo_url="https://github.com/owner/repo"
        )

    assert result.platform_deployment_id == "srv_render789"
    assert result.url == "https://my-site.onrender.com"
    assert result.status == "deploying"


@pytest.mark.asyncio
async def test_render_get_deployment_status_active():
    status_resp = _mock_response({"service": {"id": "srv_abc", "suspended": "not_suspended"}})
    mock_client = _make_async_client(get_return=status_resp)

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        status = await RenderClient("fake-token").get_deployment_status("srv_abc")

    assert status == "active"


@pytest.mark.asyncio
async def test_render_get_deployment_status_not_found():
    not_found_resp = _mock_response({}, status_code=404)
    mock_client = _make_async_client(get_return=not_found_resp)

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        status = await RenderClient("fake-token").get_deployment_status("srv_gone")

    assert status == "not_found"


@pytest.mark.asyncio
async def test_render_list_deployments():
    list_resp = _mock_response([
        {
            "service": {
                "id": "srv_abc",
                "name": "my-service",
                "suspended": "not_suspended",
                "serviceDetails": {"url": "my-service.onrender.com"},
            }
        }
    ])
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        results = await RenderClient("fake-token").list_deployments()

    assert len(results) == 1
    assert results[0].project_name == "my-service"
    assert results[0].status == "active"
    assert results[0].url == "https://my-service.onrender.com"


@pytest.mark.asyncio
async def test_render_delete_deployment():
    delete_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete_return=delete_resp)

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        await RenderClient("fake-token").delete_deployment("srv_abc", "my-service")

    mock_client.delete.assert_called_once()
    assert "srv_abc" in mock_client.delete.call_args.args[0]
