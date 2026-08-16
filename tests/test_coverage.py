# pylint: disable=missing-module-docstring,missing-function-docstring,invalid-name,redefined-outer-name,line-too-long,unused-argument,too-many-lines
"""Additional tests to reach 100% coverage on all newly-added code paths."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.base import DeployResult
from integrations.netlify import NetlifyClient
from integrations.render import RenderClient
from integrations.vercel import VercelClient


def _mock_response(json_data, status_code: int = 200, text: str = ""):
    mock = MagicMock()
    mock.json.return_value = json_data
    mock.status_code = status_code
    mock.text = text or (json.dumps(json_data) if isinstance(json_data, (dict, list)) else "")
    mock.raise_for_status = MagicMock()
    return mock


def _make_async_client(**kwargs):
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    for method, value in kwargs.items():
        setattr(mock, method, AsyncMock(return_value=value) if not isinstance(value, list) else AsyncMock(side_effect=value))
    return mock


# =============================================================================
# integrations/base.py
# =============================================================================

@pytest.mark.asyncio
async def test_safe_delete_raises_on_non_success_status():
    from integrations.base import safe_delete
    bad_resp = _mock_response({}, status_code=500)
    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(return_value=bad_resp)
    await safe_delete(mock_client, "https://example.com/del", {})
    bad_resp.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_base_redeploy_default_raises():
    from integrations.base import BasePlatformClient

    class _Stub(BasePlatformClient):
        async def create_deployment(self, *a, **kw): ...
        async def list_deployments(self): ...
        async def delete_deployment(self, *a, **kw): ...
        async def connect_repo(self, *a, **kw): ...
        async def get_deployment_status(self, *a): ...

    stub = _Stub()
    with pytest.raises(ValueError, match="not supported"):
        await stub.redeploy("id", "name")


@pytest.mark.asyncio
async def test_base_get_project_url_default_returns_none():
    from integrations.base import BasePlatformClient

    class _Stub(BasePlatformClient):
        async def create_deployment(self, *a, **kw): ...
        async def list_deployments(self): ...
        async def delete_deployment(self, *a, **kw): ...
        async def connect_repo(self, *a, **kw): ...
        async def get_deployment_status(self, *a): ...

    assert await _Stub().get_project_url("x") is None


@pytest.mark.asyncio
async def test_base_get_project_repo_url_default_returns_none():
    from integrations.base import BasePlatformClient

    class _Stub(BasePlatformClient):
        async def create_deployment(self, *a, **kw): ...
        async def list_deployments(self): ...
        async def delete_deployment(self, *a, **kw): ...
        async def connect_repo(self, *a, **kw): ...
        async def get_deployment_status(self, *a): ...

    assert await _Stub().get_project_repo_url("x") is None


# =============================================================================
# integrations/vercel.py — new methods and uncovered branches
# =============================================================================

@pytest.mark.asyncio
async def test_vercel_check_github_error_no_op_on_other_codes():
    """_check_github_error returns None (no raise) when the code is unknown."""
    VercelClient._check_github_error({"error": {"code": "some_other_error"}})


@pytest.mark.asyncio
async def test_vercel_fetch_project_url_returns_none_on_non_200():
    bad_resp = _mock_response({}, status_code=404)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        url = await VercelClient("tok").get_project_url("proj")
    assert url is None


@pytest.mark.asyncio
async def test_vercel_upload_file_raises_on_unexpected_status():
    bad_resp = _mock_response({}, status_code=500)
    bad_resp.raise_for_status.side_effect = Exception("server error")
    mock_client = _make_async_client(put=bad_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):
            await VercelClient("tok")._upload_file(mock_client, b"data")


@pytest.mark.asyncio
async def test_vercel_connect_repo_raises_on_deploy_error():
    link_resp = _mock_response({}, status_code=200)
    bad_deploy = _mock_response({}, status_code=500)
    bad_deploy.raise_for_status.side_effect = Exception("server error")
    mock_client = _make_async_client(patch=link_resp, post=[bad_deploy])
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):
            await VercelClient("tok").connect_repo("pid", "proj", "https://github.com/o/r")


@pytest.mark.asyncio
async def test_vercel_redeploy_raises_on_400_github_error():
    bad_resp = _mock_response(
        {"error": {"code": "incorrect_git_source_info"}}, status_code=400
    )
    mock_client = _make_async_client(post=[bad_resp], get=_mock_response({"alias": []}))
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="Vercel GitHub App"):
            await VercelClient("tok").redeploy("pid", "proj", "https://github.com/o/r")


@pytest.mark.asyncio
async def test_vercel_get_project_repo_url_returns_none_on_non_200():
    bad_resp = _mock_response({}, status_code=404)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        url = await VercelClient("tok").get_project_repo_url("proj")
    assert url is None


@pytest.mark.asyncio
async def test_vercel_get_deployment_logs_ndjson():
    ndjson = (
        '{"payload":{"text":"Step 1"}}\n'
        '{"payload":{"text":"Step 2"}}\n'
        '\n'
        'not-json-line\n'
    )
    log_resp = MagicMock()
    log_resp.status_code = 200
    log_resp.text = ndjson
    mock_client = _make_async_client(get=log_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        lines = await VercelClient("tok").get_deployment_logs("dpl_abc", "proj")
    assert "Step 1" in lines
    assert "Step 2" in lines


@pytest.mark.asyncio
async def test_vercel_get_deployment_logs_non_200_returns_empty():
    bad_resp = _mock_response({}, status_code=404)
    bad_resp.text = ""
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        lines = await VercelClient("tok").get_deployment_logs("dpl_abc", "proj")
    assert lines == []


@pytest.mark.asyncio
async def test_vercel_list_env_vars():
    env_resp = _mock_response({"envs": [{"key": "FOO", "value": "bar", "id": "ev1"}]})
    mock_client = _make_async_client(get=env_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        vars_ = await VercelClient("tok").list_env_vars("pid", "proj")
    assert vars_ == [{"key": "FOO", "value": "bar", "id": "ev1"}]


@pytest.mark.asyncio
async def test_vercel_list_env_vars_non_200_returns_empty():
    bad_resp = _mock_response({}, status_code=403)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        vars_ = await VercelClient("tok").list_env_vars("pid", "proj")
    assert vars_ == []


@pytest.mark.asyncio
async def test_vercel_set_env_vars_creates_new():
    empty_resp = _mock_response({"envs": []})
    create_resp = _mock_response({"id": "ev_new"})
    mock_client = _make_async_client(get=empty_resp, post=[create_resp])
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        await VercelClient("tok").set_env_vars("pid", "proj", [{"key": "NEW", "value": "v"}])
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_vercel_set_env_vars_updates_existing():
    env_resp = _mock_response({"envs": [{"key": "FOO", "value": "old", "id": "ev1"}]})
    patch_resp = _mock_response({"id": "ev1"})
    mock_client = _make_async_client(get=env_resp, patch=patch_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        await VercelClient("tok").set_env_vars("pid", "proj", [{"key": "FOO", "value": "new"}])
    mock_client.patch.assert_called_once()


@pytest.mark.asyncio
async def test_vercel_delete_env_var_by_key():
    env_resp = _mock_response({"envs": [{"key": "FOO", "value": "bar", "id": "ev1"}]})
    del_resp = _mock_response({}, status_code=200)
    mock_client = _make_async_client(get=env_resp, delete=del_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        await VercelClient("tok").delete_env_var("pid", "proj", "FOO")
    mock_client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_vercel_delete_env_var_key_not_found_is_noop():
    env_resp = _mock_response({"envs": []})
    mock_client = _make_async_client(get=env_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        await VercelClient("tok").delete_env_var("pid", "proj", "MISSING")
    mock_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_vercel_list_domains():
    dom_resp = _mock_response({"domains": [{"name": "example.com"}, {"name": ""}]})
    mock_client = _make_async_client(get=dom_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        domains = await VercelClient("tok").list_domains("pid", "proj")
    assert domains == ["example.com"]


@pytest.mark.asyncio
async def test_vercel_list_domains_non_200_returns_empty():
    bad_resp = _mock_response({}, status_code=403)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        domains = await VercelClient("tok").list_domains("pid", "proj")
    assert domains == []


@pytest.mark.asyncio
async def test_vercel_add_domain():
    ok_resp = _mock_response({"name": "example.com"})
    mock_client = _make_async_client(post=[ok_resp])
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        await VercelClient("tok").add_domain("pid", "proj", "example.com")
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_vercel_remove_domain():
    del_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete=del_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        await VercelClient("tok").remove_domain("pid", "proj", "example.com")
    mock_client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_vercel_remove_domain_non_success_raises():
    bad_resp = _mock_response({}, status_code=500)
    bad_resp.raise_for_status.side_effect = Exception("server error")
    mock_client = _make_async_client(delete=bad_resp)
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):
            await VercelClient("tok").remove_domain("pid", "proj", "example.com")


# =============================================================================
# integrations/netlify.py — new methods
# =============================================================================

@pytest.mark.asyncio
async def test_netlify_get_deployment_logs():
    deploys_resp = _mock_response([{"id": "dep_abc"}])
    log_resp = MagicMock()
    log_resp.status_code = 200
    log_resp.text = "Line A\nLine B\n"
    mock_client = _make_async_client(get=[deploys_resp, log_resp])
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        lines = await NetlifyClient("tok").get_deployment_logs("site_abc", "proj")
    assert "Line A" in lines
    assert "Line B" in lines


@pytest.mark.asyncio
async def test_netlify_get_deployment_logs_no_deploys_returns_empty():
    deploys_resp = _mock_response([], status_code=200)
    mock_client = _make_async_client(get=deploys_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        lines = await NetlifyClient("tok").get_deployment_logs("site_abc", "proj")
    assert lines == []


@pytest.mark.asyncio
async def test_netlify_get_deployment_logs_non_200_returns_empty():
    bad_resp = _mock_response({}, status_code=403)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        lines = await NetlifyClient("tok").get_deployment_logs("site_abc", "proj")
    assert lines == []


@pytest.mark.asyncio
async def test_netlify_get_deployment_logs_log_non_200_returns_empty():
    deploys_resp = _mock_response([{"id": "dep_abc"}])
    bad_log = _mock_response({}, status_code=404)
    bad_log.text = ""
    mock_client = _make_async_client(get=[deploys_resp, bad_log])
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        lines = await NetlifyClient("tok").get_deployment_logs("site_abc", "proj")
    assert lines == []


@pytest.mark.asyncio
async def test_netlify_get_deployment_logs_deploy_missing_id_returns_empty():
    deploys_resp = _mock_response([{"id": None}])
    mock_client = _make_async_client(get=deploys_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        lines = await NetlifyClient("tok").get_deployment_logs("site_abc", "proj")
    assert lines == []


@pytest.mark.asyncio
async def test_netlify_get_project_url_returns_none():
    assert await NetlifyClient("tok").get_project_url("any") is None


@pytest.mark.asyncio
async def test_netlify_list_env_vars_dict_shape():
    env_resp = _mock_response({"FOO": "bar", "BAZ": "qux"})
    mock_client = _make_async_client(get=env_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        vars_ = await NetlifyClient("tok").list_env_vars("site_abc", "proj")
    assert {"key": "FOO", "value": "bar"} in vars_


@pytest.mark.asyncio
async def test_netlify_list_env_vars_list_shape():
    env_resp = _mock_response([
        {"key": "FOO", "values": [{"value": "bar", "context": "all"}]},
        {"key": "EMPTY", "values": []},
    ])
    mock_client = _make_async_client(get=env_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        vars_ = await NetlifyClient("tok").list_env_vars("site_abc", "proj")
    assert {"key": "FOO", "value": "bar"} in vars_
    assert {"key": "EMPTY", "value": ""} in vars_


@pytest.mark.asyncio
async def test_netlify_list_env_vars_non_200_returns_empty():
    bad_resp = _mock_response({}, status_code=403)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        vars_ = await NetlifyClient("tok").list_env_vars("site_abc", "proj")
    assert vars_ == []


@pytest.mark.asyncio
async def test_netlify_list_env_vars_unexpected_shape_returns_empty():
    env_resp = _mock_response("unexpected_string")
    mock_client = _make_async_client(get=env_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        vars_ = await NetlifyClient("tok").list_env_vars("site_abc", "proj")
    assert vars_ == []


@pytest.mark.asyncio
async def test_netlify_set_env_vars():
    ok_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(patch=ok_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        await NetlifyClient("tok").set_env_vars("site_abc", "proj", [{"key": "A", "value": "1"}])
    mock_client.patch.assert_called_once()


@pytest.mark.asyncio
async def test_netlify_set_env_vars_raises_on_error():
    bad_resp = _mock_response({}, status_code=500)
    bad_resp.raise_for_status.side_effect = Exception("fail")
    mock_client = _make_async_client(patch=bad_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):
            await NetlifyClient("tok").set_env_vars("site_abc", "proj", [{"key": "A", "value": "1"}])


@pytest.mark.asyncio
async def test_netlify_delete_env_var():
    ok_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete=ok_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        await NetlifyClient("tok").delete_env_var("site_abc", "proj", "FOO")
    mock_client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_netlify_delete_env_var_raises_on_error():
    bad_resp = _mock_response({}, status_code=500)
    bad_resp.raise_for_status.side_effect = Exception("fail")
    mock_client = _make_async_client(delete=bad_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):
            await NetlifyClient("tok").delete_env_var("site_abc", "proj", "FOO")


@pytest.mark.asyncio
async def test_netlify_list_domains_with_custom_domain():
    site_resp = _mock_response({"custom_domain": "example.com"})
    mock_client = _make_async_client(get=site_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        domains = await NetlifyClient("tok").list_domains("site_abc", "proj")
    assert domains == ["example.com"]


@pytest.mark.asyncio
async def test_netlify_list_domains_no_custom_domain():
    site_resp = _mock_response({"custom_domain": None})
    mock_client = _make_async_client(get=site_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        domains = await NetlifyClient("tok").list_domains("site_abc", "proj")
    assert domains == []


@pytest.mark.asyncio
async def test_netlify_list_domains_non_200_returns_empty():
    bad_resp = _mock_response({}, status_code=404)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        domains = await NetlifyClient("tok").list_domains("site_abc", "proj")
    assert domains == []


@pytest.mark.asyncio
async def test_netlify_add_domain():
    ok_resp = _mock_response({"custom_domain": "example.com"})
    mock_client = _make_async_client(put=ok_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        await NetlifyClient("tok").add_domain("site_abc", "proj", "example.com")
    mock_client.put.assert_called_once()


@pytest.mark.asyncio
async def test_netlify_remove_domain():
    ok_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete=ok_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        await NetlifyClient("tok").remove_domain("site_abc", "proj", "example.com")
    mock_client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_netlify_remove_domain_raises_on_error():
    bad_resp = _mock_response({}, status_code=500)
    bad_resp.raise_for_status.side_effect = Exception("fail")
    mock_client = _make_async_client(delete=bad_resp)
    with patch("integrations.netlify.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):
            await NetlifyClient("tok").remove_domain("site_abc", "proj", "example.com")


# =============================================================================
# integrations/render.py — new methods and uncovered branches
# =============================================================================

@pytest.mark.asyncio
async def test_render_fetch_owner_id_empty_raises():
    empty_resp = _mock_response([])
    mock_client = _make_async_client(get=empty_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="No Render owners"):
            await RenderClient("tok").create_deployment("proj", repo_url="https://github.com/o/r")


@pytest.mark.asyncio
async def test_render_get_project_url_non_200_returns_none():
    bad_resp = _mock_response({}, status_code=403)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        url = await RenderClient("tok").get_project_url("proj")
    assert url is None


@pytest.mark.asyncio
async def test_render_get_project_url_name_not_in_results():
    list_resp = _mock_response([{"service": {"id": "s", "name": "other", "serviceDetails": {}}}])
    mock_client = _make_async_client(get=list_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        url = await RenderClient("tok").get_project_url("proj")
    assert url is None


@pytest.mark.asyncio
async def test_render_get_deployment_logs_wrapped_message():
    logs_resp = _mock_response([
        {"cursor": "c1", "log": {"message": "Build started", "level": "info"}},
        {"cursor": "c2", "log": {"message": "Done", "level": "info"}},
    ])
    mock_client = _make_async_client(get=logs_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        lines = await RenderClient("tok").get_deployment_logs("srv_abc", "proj")
    assert "Build started" in lines
    assert "Done" in lines


@pytest.mark.asyncio
async def test_render_get_deployment_logs_wrapped_text_key():
    # Fallback to "text" when "message" is absent
    logs_resp = _mock_response([{"cursor": "c1", "log": {"text": "Output line"}}])
    mock_client = _make_async_client(get=logs_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        lines = await RenderClient("tok").get_deployment_logs("srv_abc", "proj")
    assert "Output line" in lines


@pytest.mark.asyncio
async def test_render_get_deployment_logs_empty_list():
    empty_resp = _mock_response([])
    mock_client = _make_async_client(get=empty_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        lines = await RenderClient("tok").get_deployment_logs("srv_abc", "proj")
    assert lines == []


@pytest.mark.asyncio
async def test_render_get_deployment_logs_non_200():
    bad_resp = _mock_response({}, status_code=403)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        lines = await RenderClient("tok").get_deployment_logs("srv_abc", "proj")
    assert lines == []


@pytest.mark.asyncio
async def test_render_get_deployment_logs_entry_no_message():
    # Items with empty message are excluded
    logs_resp = _mock_response([
        {"cursor": "c1", "log": {"message": ""}},
        {"cursor": "c2", "log": {"message": "Real line"}},
    ])
    mock_client = _make_async_client(get=logs_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        lines = await RenderClient("tok").get_deployment_logs("srv_abc", "proj")
    assert lines == ["Real line"]


@pytest.mark.asyncio
async def test_render_get_deployment_logs_flat_fallback():
    # If items aren't wrapped, fall back to reading message/text directly
    logs_resp = _mock_response([{"message": "Flat line"}])
    mock_client = _make_async_client(get=logs_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        lines = await RenderClient("tok").get_deployment_logs("srv_abc", "proj")
    assert "Flat line" in lines


@pytest.mark.asyncio
async def test_render_list_env_vars():
    # Render API wraps each item: {"cursor": "...", "envVar": {"key": ..., "value": ...}}
    env_resp = _mock_response([
        {"cursor": "c1", "envVar": {"key": "FOO", "value": "bar"}},
        {"cursor": "c2", "envVar": {}},  # no key — should be excluded
    ])
    mock_client = _make_async_client(get=env_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        vars_ = await RenderClient("tok").list_env_vars("srv_abc", "proj")
    assert {"key": "FOO", "value": "bar"} in vars_
    assert len(vars_) == 1


@pytest.mark.asyncio
async def test_render_list_env_vars_non_200_returns_empty():
    bad_resp = _mock_response({}, status_code=403)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        vars_ = await RenderClient("tok").list_env_vars("srv_abc", "proj")
    assert vars_ == []


@pytest.mark.asyncio
async def test_render_set_env_vars_merges_and_puts():
    existing_resp = _mock_response([{"cursor": "c1", "envVar": {"key": "OLD", "value": "x"}}])
    ok_resp = _mock_response([{"cursor": "c1", "envVar": {"key": "OLD", "value": "x"}}])
    mock_client = _make_async_client(get=existing_resp, put=ok_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        await RenderClient("tok").set_env_vars("srv_abc", "proj", [{"key": "NEW", "value": "y"}])
    mock_client.put.assert_called_once()
    put_body = mock_client.put.call_args.kwargs["json"]
    keys = [e["key"] for e in put_body]
    assert "OLD" in keys
    assert "NEW" in keys


@pytest.mark.asyncio
async def test_render_set_env_vars_raises_on_error():
    existing_resp = _mock_response([])
    bad_resp = _mock_response({}, status_code=500)
    bad_resp.raise_for_status.side_effect = Exception("fail")
    mock_client = _make_async_client(get=existing_resp, put=bad_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):
            await RenderClient("tok").set_env_vars("srv_abc", "proj", [{"key": "A", "value": "1"}])


@pytest.mark.asyncio
async def test_render_delete_env_var():
    existing_resp = _mock_response([
        {"cursor": "c1", "envVar": {"key": "FOO", "value": "bar"}},
        {"cursor": "c2", "envVar": {"key": "KEEP", "value": "v"}},
    ])
    ok_resp = _mock_response([{"cursor": "c2", "envVar": {"key": "KEEP", "value": "v"}}])
    mock_client = _make_async_client(get=existing_resp, put=ok_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        await RenderClient("tok").delete_env_var("srv_abc", "proj", "FOO")
    put_body = mock_client.put.call_args.kwargs["json"]
    assert all(e["key"] != "FOO" for e in put_body)


@pytest.mark.asyncio
async def test_render_delete_env_var_raises_on_error():
    existing_resp = _mock_response([{"cursor": "c1", "envVar": {"key": "FOO", "value": "bar"}}])
    bad_resp = _mock_response({}, status_code=500)
    bad_resp.raise_for_status.side_effect = Exception("fail")
    mock_client = _make_async_client(get=existing_resp, put=bad_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):
            await RenderClient("tok").delete_env_var("srv_abc", "proj", "FOO")


@pytest.mark.asyncio
async def test_render_update_build_command_with_cors():
    ok_resp = _mock_response({}, status_code=200)
    mock_client = _make_async_client(patch=ok_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        await RenderClient("tok").update_build_command("srv_abc", "proj", "bash build.sh", apply_cors=True)
    body = mock_client.patch.call_args.kwargs["json"]
    assert "serviceDetails" in body
    assert body["serviceDetails"]["buildCommand"] == "bash build.sh"
    assert any(h["name"] == "Access-Control-Allow-Origin" for h in body["serviceDetails"]["headers"])


@pytest.mark.asyncio
async def test_render_update_build_command_without_cors():
    ok_resp = _mock_response({}, status_code=200)
    mock_client = _make_async_client(patch=ok_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        await RenderClient("tok").update_build_command("srv_abc", "proj", "make build", apply_cors=False)
    body = mock_client.patch.call_args.kwargs["json"]
    assert body["serviceDetails"]["buildCommand"] == "make build"
    assert body["serviceDetails"]["headers"] == []


@pytest.mark.asyncio
async def test_render_update_build_command_raises_on_error():
    bad_resp = _mock_response({}, status_code=422)
    bad_resp.raise_for_status.side_effect = Exception("unprocessable")
    mock_client = _make_async_client(patch=bad_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception, match="unprocessable"):
            await RenderClient("tok").update_build_command("srv_abc", "proj", "cmd")


@pytest.mark.asyncio
async def test_render_get_build_config_returns_settings():
    svc_resp = _mock_response({
        "service": {"serviceDetails": {"buildCommand": "bash build.sh", "headers": [{"path": "/*", "name": "Access-Control-Allow-Origin", "value": "*"}]}}
    }, status_code=200)
    mock_client = _make_async_client(get=svc_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        result = await RenderClient("tok").get_build_config("srv_abc", "proj")
    assert result["build_command"] == "bash build.sh"
    assert len(result["headers"]) == 1


@pytest.mark.asyncio
async def test_render_get_build_config_non_200_returns_empty():
    err_resp = _mock_response({}, status_code=404)
    mock_client = _make_async_client(get=err_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        result = await RenderClient("tok").get_build_config("srv_abc", "proj")
    assert result == {"build_command": "", "headers": []}


@pytest.mark.asyncio
async def test_get_build_settings_endpoint_returns_config(client):
    dep_id = await _seed(client, platform="render")
    with patch("routers.deployments.RenderClient") as MC:
        MC.return_value.get_build_config = AsyncMock(
            return_value={"build_command": "bash build.sh", "headers": []}
        )
        resp = await client.get(f"/api/deployments/{dep_id}/build")
    assert resp.status_code == 200
    assert resp.json()["build_command"] == "bash build.sh"


@pytest.mark.asyncio
async def test_get_build_settings_endpoint_not_found(client):
    resp = await client.get("/api/deployments/9999/build")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_build_settings_endpoint_rejects_non_render(client):
    dep_id = await _seed(client, platform="vercel")
    resp = await client.get(f"/api/deployments/{dep_id}/build")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_build_settings_endpoint_502_on_error(client):
    dep_id = await _seed(client, platform="render")
    with patch("routers.deployments.RenderClient") as MC:
        MC.return_value.get_build_config = AsyncMock(side_effect=RuntimeError("oops"))
        resp = await client.get(f"/api/deployments/{dep_id}/build")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_build_settings_endpoint_updates_render(client):
    dep_id = await _seed(client, platform="render")
    with patch("routers.deployments.RenderClient") as MC:
        MC.return_value.update_build_command = AsyncMock(return_value=None)
        resp = await client.patch(
            f"/api/deployments/{dep_id}/build",
            json={"build_command": "bash build.sh", "apply_cors": True},
        )
    assert resp.status_code == 200
    assert "redeploy" in resp.json()["message"].lower()
    MC.return_value.update_build_command.assert_called_once()


@pytest.mark.asyncio
async def test_build_settings_endpoint_rejects_non_render(client):
    dep_id = await _seed(client, platform="vercel")
    resp = await client.patch(
        f"/api/deployments/{dep_id}/build",
        json={"build_command": "bash build.sh", "apply_cors": False},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_build_settings_endpoint_not_found(client):
    resp = await client.patch(
        "/api/deployments/9999/build",
        json={"build_command": "x", "apply_cors": False},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_build_settings_endpoint_502_on_platform_error(client):
    dep_id = await _seed(client, platform="render")
    with patch("routers.deployments.RenderClient") as MC:
        MC.return_value.update_build_command = AsyncMock(side_effect=RuntimeError("bad"))
        resp = await client.patch(
            f"/api/deployments/{dep_id}/build",
            json={"build_command": "x", "apply_cors": False},
        )
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_render_list_domains():
    dom_resp = _mock_response([
        {"customDomain": {"name": "example.com"}},
        {"name": "other.com"},
    ])
    mock_client = _make_async_client(get=dom_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        domains = await RenderClient("tok").list_domains("srv_abc", "proj")
    assert "example.com" in domains
    assert "other.com" in domains


@pytest.mark.asyncio
async def test_render_list_domains_non_200_returns_empty():
    bad_resp = _mock_response({}, status_code=403)
    mock_client = _make_async_client(get=bad_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        domains = await RenderClient("tok").list_domains("srv_abc", "proj")
    assert domains == []


@pytest.mark.asyncio
async def test_render_add_domain():
    ok_resp = _mock_response({"name": "example.com"})
    mock_client = _make_async_client(post=[ok_resp])
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        await RenderClient("tok").add_domain("srv_abc", "proj", "example.com")
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_render_remove_domain():
    ok_resp = _mock_response({}, status_code=204)
    mock_client = _make_async_client(delete=ok_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        await RenderClient("tok").remove_domain("srv_abc", "proj", "example.com")
    mock_client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_render_remove_domain_raises_on_error():
    bad_resp = _mock_response({}, status_code=500)
    bad_resp.raise_for_status.side_effect = Exception("fail")
    mock_client = _make_async_client(delete=bad_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception):
            await RenderClient("tok").remove_domain("srv_abc", "proj", "example.com")


# =============================================================================
# routers/deployments.py — uncovered error paths
# =============================================================================

async def _seed(client, platform="vercel"):
    await client.post("/api/tokens/", json={"platform": platform, "token": "tok"})
    client_cls = {"vercel": "VercelClient", "netlify": "NetlifyClient", "render": "RenderClient"}[platform]
    with patch(f"routers.deployments.{client_cls}") as MC:
        MC.return_value.create_deployment = AsyncMock(return_value=DeployResult(
            platform_deployment_id="dpl_abc", url="https://x.vercel.app", status="ready", project_name="p",
        ))
        r = await client.post("/api/deployments/", json={"platform": platform, "project_name": "p"})
    return r.json()["id"]


@pytest.mark.asyncio
async def test_connect_repo_generic_exception_raises_502(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.connect_repo = AsyncMock(side_effect=RuntimeError("oops"))
        resp = await client.patch(f"/api/deployments/{dep_id}/repo", json={"repo_url": "https://github.com/o/r"})
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_redeploy_generic_exception_raises_502(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.redeploy = AsyncMock(side_effect=RuntimeError("oops"))
        resp = await client.post(f"/api/deployments/{dep_id}/redeploy")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_redeploy_url_none_does_not_overwrite(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.redeploy = AsyncMock(return_value=DeployResult(
            platform_deployment_id="", url=None, status="deploying", project_name="p",
        ))
        resp = await client.post(f"/api/deployments/{dep_id}/redeploy")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://x.vercel.app"  # original url preserved


@pytest.mark.asyncio
async def test_import_generic_exception_raises_502(client):
    await client.post("/api/tokens/", json={"platform": "vercel", "token": "tok"})
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.list_deployments = AsyncMock(side_effect=RuntimeError("fail"))
        resp = await client.post("/api/deployments/import/vercel")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_sync_unknown_id_returns_early(client):
    await client.post("/api/tokens/", json={"platform": "vercel", "token": "tok"})
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.create_deployment = AsyncMock(return_value=DeployResult(
            platform_deployment_id="unknown", url=None, status="pending", project_name="pp",
        ))
        create = await client.post("/api/deployments/", json={"platform": "vercel", "project_name": "pp"})
    dep_id = create.json()["id"]
    resp = await client.post(f"/api/deployments/{dep_id}/sync")
    assert resp.status_code == 200
    assert resp.json()["platform_deployment_id"] == "unknown"


@pytest.mark.asyncio
async def test_get_logs_platform_error_raises_502(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.get_deployment_logs = AsyncMock(side_effect=RuntimeError("fail"))
        resp = await client.get(f"/api/deployments/{dep_id}/logs")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_delete_platform_error_is_logged_and_local_record_removed(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.delete_deployment = AsyncMock(side_effect=RuntimeError("platform down"))
        resp = await client.delete(f"/api/deployments/{dep_id}")
    # Local record must be gone even if platform delete failed
    assert resp.status_code == 200
    check = await client.get(f"/api/deployments/{dep_id}")
    assert check.status_code == 404


# =============================================================================
# routers/env_vars.py — uncovered error paths
# =============================================================================

@pytest.mark.asyncio
async def test_env_vars_list_platform_502(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.list_env_vars = AsyncMock(side_effect=RuntimeError("fail"))
        resp = await client.get(f"/api/deployments/{dep_id}/env")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_env_vars_set_value_error_400(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.set_env_vars = AsyncMock(side_effect=ValueError("unsupported"))
        resp = await client.put(f"/api/deployments/{dep_id}/env", json={"env_vars": [{"key": "A", "value": "1"}]})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_env_vars_set_platform_502(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.set_env_vars = AsyncMock(side_effect=RuntimeError("fail"))
        resp = await client.put(f"/api/deployments/{dep_id}/env", json={"env_vars": [{"key": "A", "value": "1"}]})
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_env_vars_delete_value_error_400(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.delete_env_var = AsyncMock(side_effect=ValueError("unsupported"))
        resp = await client.delete(f"/api/deployments/{dep_id}/env/FOO")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_env_vars_delete_platform_502(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.delete_env_var = AsyncMock(side_effect=RuntimeError("fail"))
        resp = await client.delete(f"/api/deployments/{dep_id}/env/FOO")
    assert resp.status_code == 502


# =============================================================================
# routers/domains.py — uncovered error paths
# =============================================================================

@pytest.mark.asyncio
async def test_domains_list_platform_502(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.list_domains = AsyncMock(side_effect=RuntimeError("fail"))
        resp = await client.get(f"/api/deployments/{dep_id}/domains")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_domains_add_value_error_400(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.add_domain = AsyncMock(side_effect=ValueError("unsupported"))
        resp = await client.post(f"/api/deployments/{dep_id}/domains", json={"domain": "x.com"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_domains_add_platform_502(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.add_domain = AsyncMock(side_effect=RuntimeError("fail"))
        resp = await client.post(f"/api/deployments/{dep_id}/domains", json={"domain": "x.com"})
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_domains_remove_value_error_400(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.remove_domain = AsyncMock(side_effect=ValueError("unsupported"))
        resp = await client.delete(f"/api/deployments/{dep_id}/domains/x.com")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_domains_remove_platform_502(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.remove_domain = AsyncMock(side_effect=RuntimeError("fail"))
        resp = await client.delete(f"/api/deployments/{dep_id}/domains/x.com")
    assert resp.status_code == 502


# =============================================================================
# routers/webhooks.py — HMAC and edge case paths
# =============================================================================

def _make_sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_webhook_verify_hmac_matches():
    import routers.webhooks as wh
    body = b'{"type":"deployment.ready"}'
    sig = _make_sig(body, "secret123")
    assert wh._verify_hmac(body, sig, "secret123") is True


@pytest.mark.asyncio
async def test_webhook_verify_hmac_mismatches():
    import routers.webhooks as wh
    assert wh._verify_hmac(b"body", "badsig", "secret") is False


@pytest.mark.asyncio
async def test_webhook_verify_hmac_sha256_prefix():
    import routers.webhooks as wh
    body = b"hello"
    sig = "sha256=" + _make_sig(body, "s")
    assert wh._verify_hmac(body, sig, "s") is True


@pytest.mark.asyncio
async def test_vercel_webhook_invalid_sig_with_secret(client):
    with patch("routers.webhooks._WEBHOOK_SECRET", "my-secret"):
        resp = await client.post(
            "/api/webhook/vercel",
            json={"type": "deployment.ready", "deployment": {"id": "x"}},
            headers={"x-vercel-signature": "badsig"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_vercel_webhook_missing_sig_with_secret(client):
    with patch("routers.webhooks._WEBHOOK_SECRET", "my-secret"):
        resp = await client.post(
            "/api/webhook/vercel",
            json={"type": "deployment.ready", "deployment": {"id": "x"}},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_netlify_webhook_invalid_sig_with_secret(client):
    with patch("routers.webhooks._WEBHOOK_SECRET", "my-secret"):
        resp = await client.post(
            "/api/webhook/netlify",
            json={"event": "deploy_building", "site_id": "s", "id": "d"},
            headers={"x-webhook-signature": "badsig"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_netlify_webhook_no_site_id_is_noop(client):
    resp = await client.post("/api/webhook/netlify", json={"event": "deploy_building", "id": "d"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_render_webhook_invalid_sig_with_secret(client):
    with patch("routers.webhooks._WEBHOOK_SECRET", "my-secret"):
        resp = await client.post(
            "/api/webhook/render",
            json={"service": {"id": "s"}, "deploy": {"id": "d", "status": "live"}},
            headers={"x-render-signature": "badsig"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_render_webhook_no_service_id_is_noop(client):
    resp = await client.post(
        "/api/webhook/render",
        json={"service": {}, "deploy": {"id": "d", "status": "live"}},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_netlify_webhook_invalid_json_returns_400(client):
    resp = await client.post(
        "/api/webhook/netlify",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_render_webhook_invalid_json_returns_400(client):
    resp = await client.post(
        "/api/webhook/render",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


# =============================================================================
# Remaining targeted gaps
# =============================================================================

@pytest.mark.asyncio
async def test_env_vars_not_found_404(client):
    resp = await client.get("/api/deployments/9999/env")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_env_vars_set_not_found_404(client):
    resp = await client.put("/api/deployments/9999/env", json={"env_vars": []})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_env_vars_delete_not_found_404(client):
    resp = await client.delete("/api/deployments/9999/env/FOO")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_domains_not_found_404(client):
    resp = await client.get("/api/deployments/9999/domains")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_domains_add_not_found_404(client):
    resp = await client.post("/api/deployments/9999/domains", json={"domain": "x.com"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_domains_remove_not_found_404(client):
    resp = await client.delete("/api/deployments/9999/domains/x.com")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_re_raises_http_exception(client):
    dep_id = await _seed(client)
    from fastapi import HTTPException as FastHTTPException
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.delete_deployment = AsyncMock(
            side_effect=FastHTTPException(status_code=502, detail="upstream error")
        )
        resp = await client.delete(f"/api/deployments/{dep_id}")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_redeploy_updates_url_when_returned(client):
    dep_id = await _seed(client)
    with patch("routers.deployments.VercelClient") as MC:
        MC.return_value.redeploy = AsyncMock(return_value=DeployResult(
            platform_deployment_id="dpl_new", url="https://new.vercel.app", status="ready", project_name="p",
        ))
        resp = await client.post(f"/api/deployments/{dep_id}/redeploy")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://new.vercel.app"


@pytest.mark.asyncio
async def test_render_list_deployments_skips_no_id():
    list_resp = _mock_response([
        {"service": {}},  # no id — must be skipped
        {"service": {"id": "srv_abc", "name": "real", "suspended": "not_suspended", "serviceDetails": {}}},
    ])
    mock_client = _make_async_client(get=list_resp)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        results = await RenderClient("tok").list_deployments()
    assert len(results) == 1
    assert results[0].project_name == "real"


@pytest.mark.asyncio
async def test_render_get_deployment_logs_non_list_response():
    non_list_logs = _mock_response({"error": "not a list"})
    mock_client = _make_async_client(get=non_list_logs)
    with patch("integrations.render.httpx.AsyncClient", return_value=mock_client):
        lines = await RenderClient("tok").get_deployment_logs("srv_abc", "proj")
    assert lines == []


@pytest.mark.asyncio
async def test_vercel_pick_production_url_custom_domain():
    from integrations.vercel import VercelClient as VC
    proj = {"alias": [{"domain": "example.com"}, {"domain": "proj.vercel.app"}], "latestDeployments": []}
    url = VC._pick_production_url(proj)
    assert url == "https://example.com"


@pytest.mark.asyncio
async def test_vercel_connect_repo_400_error_raises_value_error():
    link_resp = _mock_response({}, status_code=200)
    error_resp = _mock_response(
        {"error": {"code": "incorrect_git_source_info"}}, status_code=400
    )
    mock_client = _make_async_client(patch=link_resp, post=[error_resp])
    with patch("integrations.vercel.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="Vercel GitHub App"):
            await VercelClient("tok").connect_repo("pid", "proj", "https://github.com/o/r")
