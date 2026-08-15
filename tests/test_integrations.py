# pylint: disable=missing-module-docstring,missing-function-docstring,line-too-long
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
    patch_return=None,
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
    if patch_return is not None:
        mock.patch = AsyncMock(return_value=patch_return)
    return mock


# ---------------------------------------------------------------------------
# Vercel
# ---------------------------------------------------------------------------

def _project_info_resp(domain="my-site.vercel.app"):
    """Mock a GET /v9/projects response with the given project-level alias domain."""
    return _mock_response({"alias": [{"domain": domain}]})


def _project_info_resp_no_alias(deploy_url: str, production_alias: str):
    """Mock project info where alias[] is empty but latestDeployments has aliases.

    Simulates the case where Vercel auto-assigns an alias like
    ``test-indol-one-73.vercel.app`` because the plain name was taken;
    the project-level alias list is empty, but the deployment alias array
    contains both the production alias and the deployment-specific URL.
    """
    return _mock_response({
        "alias": [],
        "latestDeployments": [
            {"url": deploy_url, "alias": [production_alias, deploy_url]}
        ],
    })


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
        get_return=_project_info_resp("my-site.vercel.app"),
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment("my-site")

    assert result.platform_deployment_id == "dpl_xyz"
    assert result.url == "https://my-site.vercel.app"
    assert result.status == "initializing"
    mock_client.put.assert_called_once()


@pytest.mark.asyncio
async def test_vercel_create_deployment_uses_alias_url():
    """URL should come from the project alias, not the deployment URL."""
    project_resp = _mock_response({"id": "proj_abc", "name": "my-site"})
    deploy_resp = _mock_response({"id": "dpl_xyz", "url": "my-site-abc123.vercel.app", "readyState": "READY"})
    upload_resp = _mock_response({}, status_code=200)

    mock_client = _make_async_client(
        post_side_effect=[project_resp, deploy_resp],
        put_return=upload_resp,
        # Alias differs from the deployment hash URL — this is the real test
        get_return=_project_info_resp("my-site-teamslug.vercel.app"),
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment("my-site")

    assert result.url == "https://my-site-teamslug.vercel.app"


@pytest.mark.asyncio
async def test_vercel_create_deployment_no_repo_file_already_uploaded():
    """A 409 from the file upload (already exists) should not raise."""
    project_resp = _mock_response({"id": "proj_abc", "name": "my-site"})
    deploy_resp = _mock_response({"id": "dpl_xyz", "url": "my-site.vercel.app", "readyState": "READY"})
    upload_resp = _mock_response({}, status_code=409)

    mock_client = _make_async_client(
        post_side_effect=[project_resp, deploy_resp],
        put_return=upload_resp,
        get_return=_project_info_resp(),
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

    mock_client = _make_async_client(
        post_side_effect=[project_resp, deploy_resp],
        get_return=_project_info_resp(),
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment(
            "my-site", repo_url="https://github.com/octocat/hello"
        )

    assert result.status == "ready"
    # Project creation POST must include gitRepository to enable auto-deploy on push
    project_body = mock_client.post.call_args_list[0].kwargs["json"]
    assert project_body["gitRepository"]["repo"] == "octocat/hello"
    assert project_body["gitRepository"]["type"] == "github"
    # Deployment POST must still carry gitSource for the initial build
    deploy_body = mock_client.post.call_args_list[1].kwargs["json"]
    assert "gitSource" in deploy_body


@pytest.mark.asyncio
async def test_vercel_create_deployment_url_from_project_creation_alias():
    """URL is taken from the project creation response when Vercel includes the alias there.

    This avoids the fallback guess (name.vercel.app) for projects where Vercel
    assigns a hash alias at creation time (e.g. test-indol-one-73.vercel.app).
    """
    project_resp = _mock_response({
        "id": "proj_abc",
        "name": "test",
        "alias": [{"domain": "test-indol-one-73.vercel.app"}],
    })
    deploy_resp = _mock_response({"id": "dpl_xyz", "url": "test-git-abc.vercel.app", "readyState": "INITIALIZING"})
    upload_resp = _mock_response({}, status_code=200)

    mock_client = _make_async_client(
        post_side_effect=[project_resp, deploy_resp],
        put_return=upload_resp,
        get_return=_project_info_resp("wrong-should-not-be-called.vercel.app"),
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment("test")

    assert result.url == "https://test-indol-one-73.vercel.app"
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_vercel_create_deployment_url_from_deployment_alias():
    """URL falls back to deployment response alias when project creation has none."""
    project_resp = _mock_response({"id": "proj_abc", "name": "test"})
    deploy_resp = _mock_response({
        "id": "dpl_xyz",
        "url": "test-git-abc.vercel.app",
        "alias": ["test-indol-one-73.vercel.app", "test-git-abc.vercel.app"],
        "readyState": "INITIALIZING",
    })
    upload_resp = _mock_response({}, status_code=200)

    mock_client = _make_async_client(
        post_side_effect=[project_resp, deploy_resp],
        put_return=upload_resp,
        get_return=_project_info_resp("wrong-should-not-be-called.vercel.app"),
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment("test")

    assert result.url == "https://test-indol-one-73.vercel.app"
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_vercel_create_deployment_url_none_when_alias_not_yet_assigned():
    """URL is None when deployment is still INITIALIZING and no alias is available."""
    project_resp = _mock_response({"id": "proj_abc", "name": "test"})
    deploy_resp = _mock_response({"id": "dpl_xyz", "url": "test-abc.vercel.app", "readyState": "INITIALIZING"})
    upload_resp = _mock_response({}, status_code=200)

    mock_client = _make_async_client(
        post_side_effect=[project_resp, deploy_resp],
        put_return=upload_resp,
        # _fetch_project_url returns None — alias not assigned yet
        get_return=_mock_response({"alias": [], "latestDeployments": []}),
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment("test")

    assert result.url is None  # sync button will fill this in once deployment reaches READY


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
    mock_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_vercel_github_app_not_installed_falls_back_to_plain_project():
    """When gitRepository causes 400 at project creation, retry without it.

    The fallback project (no auto-deploys) is created successfully, then the
    gitSource deployment fails with incorrect_git_source_info → PartialDeployError.
    This ensures the project is still saved to the DB even when the GitHub App
    isn't installed.
    """
    github_app_error = _mock_response(
        {"error": {"code": "bad_request", "action": "Install GitHub App",
                   "message": "install the GitHub integration first"}},
        status_code=400,
    )
    plain_project_resp = _mock_response({"id": "proj_abc", "name": "my-site"})
    deploy_error_resp = _mock_response(
        {"error": {"code": "incorrect_git_source_info", "message": "repo not found"}},
        status_code=400,
    )

    mock_client = _make_async_client(
        post_side_effect=[github_app_error, plain_project_resp, deploy_error_resp],
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(PartialDeployError) as exc_info:
            await VercelClient("fake-token").create_deployment(
                "my-site", repo_url="https://github.com/owner/private-repo"
            )

    assert "Vercel GitHub App" in str(exc_info.value)
    assert exc_info.value.partial_result.status == "deployment_failed"
    assert mock_client.post.call_count == 3
    # Fallback second POST must NOT include gitRepository
    second_call_body = mock_client.post.call_args_list[1].kwargs["json"]
    assert "gitRepository" not in second_call_body


@pytest.mark.asyncio
async def test_vercel_connect_repo_link_error_raises_value_error():
    """GitHub App error from the PATCH in connect_repo raises ValueError (→ 400)."""
    link_error_resp = _mock_response(
        {"error": {"code": "incorrect_git_source_info"}},
        status_code=400,
    )
    mock_client = _make_async_client(
        post_side_effect=[],
        patch_return=link_error_resp,
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="Vercel GitHub App"):
            await VercelClient("fake-token").connect_repo(
                "proj_abc", "my-site", "https://github.com/owner/private-repo"
            )


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
                "alias": [{"domain": "my-site.vercel.app"}],
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
    assert results[0].repo_url is None


@pytest.mark.asyncio
async def test_vercel_list_deployments_includes_repo_url():
    """Projects linked to a GitHub repo should have repo_url populated on import."""
    list_resp = _mock_response({
        "projects": [
            {
                "id": "proj_abc",
                "name": "my-site",
                "alias": [{"domain": "my-site.vercel.app"}],
                "link": {"type": "github", "org": "octocat", "repo": "hello"},
                "latestDeployments": [
                    {"id": "dpl_xyz", "readyState": "READY"}
                ],
            }
        ]
    })
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        results = await VercelClient("fake-token").list_deployments()

    assert results[0].repo_url == "https://github.com/octocat/hello"


@pytest.mark.asyncio
async def test_vercel_list_deployments_uses_alias_not_constructed_url():
    """Import should use the project alias domain, not construct {name}.vercel.app."""
    list_resp = _mock_response({
        "projects": [
            {
                "id": "proj_abc",
                "name": "my-site",
                "alias": [{"domain": "my-site-teamslug.vercel.app"}],
                "latestDeployments": [{"id": "dpl_xyz", "readyState": "READY"}],
            }
        ]
    })
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        results = await VercelClient("fake-token").list_deployments()

    assert results[0].url == "https://my-site-teamslug.vercel.app"


@pytest.mark.asyncio
async def test_vercel_list_deployments_uses_deployment_alias_when_project_alias_empty():
    """When project alias[] is empty, the URL comes from latestDeployments[0].alias."""
    list_resp = _mock_response({
        "projects": [
            {
                "id": "proj_abc",
                "name": "test",
                "alias": [],
                "latestDeployments": [
                    {
                        "id": "dpl_xyz",
                        "url": "test-git-abc123.vercel.app",
                        "alias": ["test-indol-one-73.vercel.app", "test-git-abc123.vercel.app"],
                        "readyState": "READY",
                    }
                ],
            }
        ]
    })
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        results = await VercelClient("fake-token").list_deployments()

    assert results[0].url == "https://test-indol-one-73.vercel.app"


@pytest.mark.asyncio
async def test_vercel_list_deployments_skips_git_branch_alias():
    """Git-branch alias (-git-) must be skipped; stable production domain returned instead."""
    list_resp = _mock_response({
        "projects": [
            {
                "id": "proj_abc",
                "name": "test",
                "alias": [
                    {"domain": "test-git-main.vercel.app"},  # git-branch — skip
                    {"domain": "test.vercel.app"},            # production — use this
                ],
                "latestDeployments": [{"id": "dpl_xyz", "readyState": "READY"}],
            }
        ]
    })
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        results = await VercelClient("fake-token").list_deployments()

    assert results[0].url == "https://test.vercel.app"


@pytest.mark.asyncio
async def test_vercel_create_deployment_uses_deployment_alias_when_project_alias_empty():
    """URL from _fetch_project_url falls back to latestDeployments alias when alias[] empty."""
    project_resp = _mock_response({"id": "proj_abc", "name": "test"})
    deploy_resp = _mock_response({"id": "dpl_xyz", "url": "test-git-abc.vercel.app", "readyState": "READY"})
    upload_resp = _mock_response({}, status_code=200)

    mock_client = _make_async_client(
        post_side_effect=[project_resp, deploy_resp],
        put_return=upload_resp,
        get_return=_project_info_resp_no_alias("test-git-abc.vercel.app", "test-indol-one-73.vercel.app"),
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").create_deployment("test")

    assert result.url == "https://test-indol-one-73.vercel.app"


@pytest.mark.asyncio
async def test_vercel_get_project_url_uses_deployment_alias_when_project_alias_empty():
    """get_project_url falls back to latestDeployments alias when project alias[] is empty."""
    project_resp = _project_info_resp_no_alias("test-git-abc.vercel.app", "test-indol-one-73.vercel.app")
    mock_client = _make_async_client(get_return=project_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        url = await VercelClient("fake-token").get_project_url("test")

    assert url == "https://test-indol-one-73.vercel.app"


@pytest.mark.asyncio
async def test_vercel_list_deployments_repo_from_meta_fallback():
    """When link is absent, repo_url comes from latestDeployments[0].meta commit fields."""
    list_resp = _mock_response({
        "projects": [
            {
                "id": "proj_abc",
                "name": "my-site",
                "alias": [{"domain": "my-site.vercel.app"}],
                "latestDeployments": [
                    {
                        "id": "dpl_xyz",
                        "url": "my-site.vercel.app",
                        "readyState": "READY",
                        "meta": {
                            "githubCommitOrg": "octocat",
                            "githubCommitRepo": "hello",
                        },
                    }
                ],
            }
        ]
    })
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        results = await VercelClient("fake-token").list_deployments()

    assert results[0].repo_url == "https://github.com/octocat/hello"


@pytest.mark.asyncio
async def test_vercel_list_deployments_repo_combined_format():
    """link.repo in 'org/repo' format without a separate org field is parsed correctly."""
    list_resp = _mock_response({
        "projects": [
            {
                "id": "proj_abc",
                "name": "my-site",
                "alias": [{"domain": "my-site.vercel.app"}],
                "link": {"type": "github", "repo": "octocat/hello"},
                "latestDeployments": [{"id": "dpl_xyz", "readyState": "READY"}],
            }
        ]
    })
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        results = await VercelClient("fake-token").list_deployments()

    assert results[0].repo_url == "https://github.com/octocat/hello"


@pytest.mark.asyncio
async def test_vercel_get_project_repo_url():
    project_resp = _mock_response({
        "link": {"type": "github", "org": "octocat", "repo": "hello"},
    })
    mock_client = _make_async_client(get_return=project_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        url = await VercelClient("fake-token").get_project_repo_url("my-site")

    assert url == "https://github.com/octocat/hello"


@pytest.mark.asyncio
async def test_vercel_get_project_repo_url_meta_fallback():
    """get_project_repo_url falls back to deployment meta when link is absent."""
    project_resp = _mock_response({
        "latestDeployments": [
            {"meta": {"githubCommitOrg": "octocat", "githubCommitRepo": "hello"}}
        ],
    })
    mock_client = _make_async_client(get_return=project_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        url = await VercelClient("fake-token").get_project_repo_url("my-site")

    assert url == "https://github.com/octocat/hello"


@pytest.mark.asyncio
async def test_vercel_delete_deployment():
    delete_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete_return=delete_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        await VercelClient("fake-token").delete_deployment("dpl_xyz", "my-site")

    mock_client.delete.assert_called_once()
    assert "my-site" in mock_client.delete.call_args.args[0]


@pytest.mark.asyncio
async def test_vercel_redeploy():
    deploy_resp = _mock_response({"id": "dpl_new", "url": "my-site-new.vercel.app", "readyState": "INITIALIZING"})
    mock_client = _make_async_client(
        post_side_effect=[deploy_resp],
        get_return=_project_info_resp("my-site.vercel.app"),
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").redeploy(
            "dpl_old", "my-site", "https://github.com/owner/repo"
        )

    assert result.platform_deployment_id == "dpl_new"
    assert result.status == "initializing"
    deploy_body = mock_client.post.call_args.kwargs["json"]
    assert deploy_body["gitSource"]["org"] == "owner"
    assert deploy_body["gitSource"]["repo"] == "repo"


@pytest.mark.asyncio
async def test_vercel_redeploy_no_repo_raises():
    with pytest.raises(ValueError, match="repo URL is required"):
        await VercelClient("fake-token").redeploy("dpl_old", "my-site", repo_url=None)


@pytest.mark.asyncio
async def test_vercel_connect_repo():
    deploy_resp = _mock_response({
        "id": "dpl_new123",
        "url": "my-site-git-abc.vercel.app",
        "readyState": "INITIALIZING",
    })
    link_resp = _mock_response({}, status_code=200)
    mock_client = _make_async_client(
        post_side_effect=[deploy_resp],
        get_return=_project_info_resp("my-site.vercel.app"),
        patch_return=link_resp,
    )

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        result = await VercelClient("fake-token").connect_repo(
            "proj_abc", "my-site", "https://github.com/owner/repo"
        )

    assert result.platform_deployment_id == "dpl_new123"
    assert result.url == "https://my-site.vercel.app"
    assert result.status == "initializing"
    # PATCH must be called to link the repo for auto-deploys
    mock_client.patch.assert_called_once()
    patch_body = mock_client.patch.call_args.kwargs["json"]
    assert patch_body["gitRepository"]["repo"] == "owner/repo"
    assert patch_body["gitRepository"]["type"] == "github"


@pytest.mark.asyncio
async def test_vercel_get_project_url():
    project_resp = _mock_response({"alias": [{"domain": "my-site-team.vercel.app"}]})
    mock_client = _make_async_client(get_return=project_resp)

    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        url = await VercelClient("fake-token").get_project_url("my-site")

    assert url == "https://my-site-team.vercel.app"


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
async def test_netlify_connect_repo():
    site_resp = _mock_response({
        "id": "site_abc",
        "ssl_url": "https://my-site.netlify.app",
        "state": "building",
    })
    mock_client = _make_async_client()
    mock_client.put = AsyncMock(return_value=site_resp)

    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        result = await NetlifyClient("fake-token").connect_repo(
            "site_abc", "my-site", "https://github.com/owner/repo"
        )

    assert result.platform_deployment_id == "site_abc"
    assert result.url == "https://my-site.netlify.app"
    assert result.status == "building"
    body = mock_client.put.call_args.kwargs["json"]
    assert body["repo"]["repo"] == "owner/repo"


@pytest.mark.asyncio
async def test_netlify_delete_deployment():
    delete_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete_return=delete_resp)

    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        await NetlifyClient("fake-token").delete_deployment("site_abc", "my-site")

    mock_client.delete.assert_called_once()
    assert "site_abc" in mock_client.delete.call_args.args[0]


@pytest.mark.asyncio
async def test_netlify_redeploy():
    build_resp = _mock_response({"id": "build_abc", "done": False})
    mock_client = _make_async_client(post_side_effect=[build_resp])

    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        result = await NetlifyClient("fake-token").redeploy("site_abc", "my-site")

    assert result.status == "building"
    assert result.platform_deployment_id == "site_abc"
    assert "site_abc" in mock_client.post.call_args.args[0]


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
    owners_resp = _mock_response([{"owner": {"id": "usr_abc123"}, "cursor": "x"}])
    service_resp = _mock_response({
        "service": {"id": "srv_render789", "serviceDetails": {"url": "my-site.onrender.com"}}
    })
    mock_client = _make_async_client(
        post_side_effect=[service_resp],
        get_return=owners_resp,
    )

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        result = await RenderClient("fake-token").create_deployment(
            "my-site", repo_url="https://github.com/owner/repo"
        )

    assert result.platform_deployment_id == "srv_render789"
    assert result.url == "https://my-site.onrender.com"
    assert result.status == "deploying"
    body = mock_client.post.call_args.kwargs["json"]
    assert body["ownerId"] == "usr_abc123"
    # publishPath must be inside serviceDetails (top-level staticPublishPath is ignored by Render)
    assert body.get("serviceDetails", {}).get("publishPath") == "."
    # buildCommand should be null, not empty string
    assert body.get("buildCommand") is None


@pytest.mark.asyncio
async def test_render_create_deployment_fetches_url_when_absent_in_creation_response():
    """When the creation response has no URL, a follow-up GET fetches it."""
    owners_resp = _mock_response([{"owner": {"id": "usr_abc123"}, "cursor": "x"}])
    # Creation response: service exists but URL not yet assigned
    service_resp = _mock_response({
        "service": {"id": "srv_render789", "serviceDetails": {}}
    })
    # Follow-up GET returns the real URL once Render assigns it
    fetch_resp = _mock_response({
        "service": {"id": "srv_render789", "serviceDetails": {"url": "my-site-abc.onrender.com"}}
    })
    mock_client = _make_async_client(
        post_side_effect=[service_resp],
        get_return=fetch_resp,
    )
    # owners call goes through get_return too — make get return different things
    # Use side_effect for get: first call (owners) then second call (service fetch)
    mock_client.get = AsyncMock(side_effect=[owners_resp, fetch_resp])

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        result = await RenderClient("fake-token").create_deployment(
            "my-site", repo_url="https://github.com/owner/repo"
        )

    assert result.url == "https://my-site-abc.onrender.com"


@pytest.mark.asyncio
async def test_render_get_project_url():
    """get_project_url finds the service by name and returns its public URL."""
    list_resp = _mock_response([
        {
            "service": {
                "id": "srv_abc",
                "name": "my-service",
                "suspended": "not_suspended",
                "serviceDetails": {"url": "my-service-x.onrender.com"},
            }
        }
    ])
    mock_client = _make_async_client(get_return=list_resp)

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        url = await RenderClient("fake-token").get_project_url("my-service")

    assert url == "https://my-service-x.onrender.com"


@pytest.mark.asyncio
async def test_render_get_deployment_status_ready():
    status_resp = _mock_response({"service": {"id": "srv_abc", "suspended": "not_suspended"}})
    mock_client = _make_async_client(get_return=status_resp)

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        status = await RenderClient("fake-token").get_deployment_status("srv_abc")

    assert status == "ready"


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
    assert results[0].status == "ready"
    assert results[0].url == "https://my-service.onrender.com"


@pytest.mark.asyncio
async def test_render_connect_repo_raises():
    with pytest.raises(ValueError, match="Render does not support"):
        await RenderClient("fake-token").connect_repo("srv_abc", "my-service", "https://github.com/o/r")


@pytest.mark.asyncio
async def test_render_redeploy():
    deploy_resp = _mock_response({"id": "dep_xyz", "status": "created"})
    mock_client = _make_async_client(post_side_effect=[deploy_resp])

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        result = await RenderClient("fake-token").redeploy("srv_abc", "my-service")

    assert result.status == "deploying"
    assert result.platform_deployment_id == "srv_abc"
    assert "srv_abc" in mock_client.post.call_args.args[0]


@pytest.mark.asyncio
async def test_render_delete_deployment():
    delete_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete_return=delete_resp)

    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        await RenderClient("fake-token").delete_deployment("srv_abc", "my-service")

    mock_client.delete.assert_called_once()
    assert "srv_abc" in mock_client.delete.call_args.args[0]
