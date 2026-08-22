"""Vercel REST API client."""

import hashlib
import json
from typing import Optional

import httpx

from integrations.base import (
    BasePlatformClient, DeployResult, PartialDeployError,
    build_result, normalize_status, safe_delete,
)

VERCEL_API = "https://api.vercel.com"

# Placeholder page uploaded when no GitHub repo is provided.
_PLACEHOLDER_HTML = (
    b"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
    b"<title>Deployed</title></head><body>"
    b"<h1>Deployed via Auto Deploy</h1>"
    b"<p>Push your files to update this page.</p>"
    b"</body></html>"
)


class VercelClient(BasePlatformClient):
    """Async client for the Vercel REST API."""

    def __init__(self, token: str):
        """Initialise with a Vercel personal access token."""
        self._token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _check_github_error(body: dict) -> None:
        """Raise a readable ValueError for known GitHub-integration error codes."""
        code = body.get("error", {}).get("code", "")
        if code == "incorrect_git_source_info":
            raise ValueError(
                "Vercel can't access this GitHub repository. "
                "Install the Vercel GitHub App first: "
                "vercel.com → Settings → Integrations → GitHub. "
                "Grant it access to this repo and try again."
            )

    @staticmethod
    def _extract_repo_url(proj: dict) -> Optional[str]:
        """Extract the connected GitHub repo URL from a Vercel project API response.

        Vercel stores the git link under ``project.link`` but the field names
        vary (``org`` vs ``repoOwner``, plain name vs ``owner/repo`` format).
        Falls back to ``latestDeployments[0].meta`` commit fields, which are
        present whenever the most recent deployment came from a GitHub push.
        """
        link = proj.get("link") or {}
        if link.get("type", "").lower() == "github":
            org = link.get("org") or link.get("repoOwner", "")
            repo_name = link.get("repo") or link.get("repoName", "")
            if "/" in repo_name and not org:
                org, repo_name = repo_name.split("/", 1)
            if org and repo_name:
                return f"https://github.com/{org}/{repo_name}"
        latest = (proj.get("latestDeployments") or [{}])[0]
        meta = latest.get("meta") or {}
        gh_org = meta.get("githubCommitOrg", "")
        gh_repo = meta.get("githubCommitRepo", "")
        if gh_org and gh_repo:
            return f"https://github.com/{gh_org}/{gh_repo}"
        return None

    @staticmethod
    def _pick_production_url(proj: dict) -> Optional[str]:
        """Return the most stable public URL from a Vercel project API response.

        Skips git-branch aliases (``*-git-*``) which require authentication to visit.
        If a domain appears in ``proj["alias"]`` the project owns it, so the plain
        ``{name}.vercel.app`` alias is valid and returned when present.  Falls back to
        deployment-level aliases when the project alias list is empty or git-branch-only.
        """
        # Custom domains (non-vercel.app) always preferred
        for alias_obj in proj.get("alias", []):
            domain = alias_obj.get("domain", "")
            if domain and not domain.endswith(".vercel.app"):
                return f"https://{domain}"
        # Stable vercel.app aliases — skip only git-branch aliases
        for alias_obj in proj.get("alias", []):
            domain = alias_obj.get("domain", "")
            if domain and domain.endswith(".vercel.app") and "-git-" not in domain:
                return f"https://{domain}"
        # Deployment-level alias fallback (when project alias[] is empty or git-branch-only)
        plain_alias = f"{proj.get('name', '')}.vercel.app"
        latest = (proj.get("latestDeployments") or [{}])[0]
        deploy_url = latest.get("url", "")
        for alias in latest.get("alias", []):
            if alias not in (deploy_url, plain_alias) and "-git-" not in alias:
                return f"https://{alias}"
        return None

    async def _fetch_project_url(
        self, client: httpx.AsyncClient, project_name: str
    ) -> Optional[str]:
        """Fetch the production domain alias for a project from the Vercel API.

        Returns None when the alias hasn't been assigned yet (e.g. the initial
        deployment is still INITIALIZING).  Callers that need a guaranteed
        non-null value should use ``get_project_url`` which the sync endpoint
        calls after deployment completes.
        """
        resp = await client.get(
            f"{VERCEL_API}/v9/projects/{project_name}",
            headers=self._headers,
        )
        if resp.status_code == 200:
            return self._pick_production_url(resp.json())
        return None

    async def _upload_file(self, client: httpx.AsyncClient, content: bytes) -> str:
        """Pre-upload a file to Vercel and return its SHA1 digest.

        Vercel v13 deployments reference files by SHA rather than accepting
        inline content, so files must be uploaded before the deployment is
        created.  A 409 response means the file already exists on Vercel's
        CDN, which is fine.
        """
        sha = hashlib.sha1(content).hexdigest()  # nosec B324 — required by Vercel API
        resp = await client.put(
            f"{VERCEL_API}/v2/files",
            headers={
                "Authorization": f"Bearer {self._token}",
                "x-vercel-digest": sha,
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(content)),
            },
            content=content,
        )
        if resp.status_code not in (200, 409):
            resp.raise_for_status()
        return sha

    async def _link_github_repo(
        self,
        client: httpx.AsyncClient,
        project_name: str,
        owner: str,
        repo: str,
    ) -> None:
        """PATCH the project to link a GitHub repo and enable auto-deploy on push.

        Uses the ``gitRepository`` field (combined ``owner/repo`` format) which
        Vercel accepts on ``PATCH /v9/projects/{name}``.  This call is best-effort:
        if Vercel rejects the field for any reason other than the GitHub App not
        being installed, we skip silently rather than blocking the deployment.
        """
        resp = await client.patch(
            f"{VERCEL_API}/v9/projects/{project_name}",
            headers=self._headers,
            json={
                "gitRepository": {
                    "type": "github",
                    "repo": f"{owner}/{repo}",
                }
            },
        )
        if resp.status_code == 400:
            self._check_github_error(resp.json())
            # Unrecognised 400 (e.g. field not supported yet) — skip silently.

    async def _delete_project(self, client: httpx.AsyncClient, project_name: str) -> None:
        """Best-effort project deletion — ignores 404 (already gone)."""
        await safe_delete(client, f"{VERCEL_API}/v9/projects/{project_name}", self._headers)

    async def create_deployment(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        self,
        project_name: str,
        repo_url: Optional[str] = None,
        deployment_type: Optional[str] = None,  # pylint: disable=unused-argument
        start_command: Optional[str] = None,  # pylint: disable=unused-argument
        render_runtime: Optional[str] = None,  # pylint: disable=unused-argument
        build_command: Optional[str] = None,  # pylint: disable=unused-argument
    ) -> DeployResult:
        """Create a Vercel project and trigger an initial deployment."""
        async with httpx.AsyncClient() as client:
            if repo_url:
                *_, owner, repo = repo_url.rstrip("/").split("/")
                # Include gitRepository at creation time — Vercel installs the
                # GitHub webhook here, enabling auto-deploy on every push to main.
                project_json: dict = {
                    "name": project_name,
                    "gitRepository": {"type": "github", "repo": f"{owner}/{repo}"},
                }
                deploy_payload = {
                    "name": project_name,
                    "target": "production",
                    "gitSource": {
                        "type": "github",
                        "org": owner,
                        "repo": repo,
                        "ref": "main",
                    },
                }
            else:
                project_json = {"name": project_name}
                sha = await self._upload_file(client, _PLACEHOLDER_HTML)
                deploy_payload = {
                    "name": project_name,
                    "files": [
                        {
                            "file": "index.html",
                            "sha": sha,
                            "size": len(_PLACEHOLDER_HTML),
                        }
                    ],
                    "projectSettings": {"framework": None},
                }

            project_resp = await client.post(
                f"{VERCEL_API}/v9/projects",
                headers=self._headers,
                json=project_json,
            )
            # If gitRepository caused a 400 (GitHub App not installed / no repo
            # access), fall back to plain project creation so the deployment step
            # can still run.  That step raises PartialDeployError, which saves the
            # project to the DB as deployment_failed and shows it in the dashboard.
            if project_resp.status_code == 400 and repo_url:
                project_resp = await client.post(
                    f"{VERCEL_API}/v9/projects",
                    headers=self._headers,
                    json={"name": project_name},
                )
            project_resp.raise_for_status()

            # Alias from project creation response (set before any deployment runs).
            url: Optional[str] = self._pick_production_url(project_resp.json())

            try:
                deploy_resp = await client.post(
                    f"{VERCEL_API}/v13/deployments",
                    headers=self._headers,
                    json=deploy_payload,
                )

                if deploy_resp.status_code == 400 and repo_url:
                    self._check_github_error(deploy_resp.json())

                deploy_resp.raise_for_status()
            except ValueError as exc:
                # Project exists on Vercel but deployment failed (e.g. GitHub App
                # not installed).  Surface as PartialDeployError so the caller can
                # persist the project and show it in the dashboard.
                raise PartialDeployError(
                    str(exc),
                    DeployResult(
                        platform_deployment_id=project_resp.json()["id"],
                        url=None,
                        status="deployment_failed",
                        project_name=project_name,
                    ),
                ) from exc

            data = deploy_resp.json()

            # URL priority: project creation alias → deployment alias → project fetch
            # (None is valid — sync button fills this in once deployment reaches READY)
            if not url:
                for alias in data.get("alias", []):
                    if alias and alias != data.get("url") and "-git-" not in alias:
                        url = f"https://{alias}"
                        break
            if not url:
                url = await self._fetch_project_url(client, project_name)

            return build_result(
                platform_deployment_id=data.get("id", project_name),
                url=url,
                project_name=project_name,
            )

    async def connect_repo(
        self, platform_deployment_id: str, project_name: str, repo_url: str
    ) -> DeployResult:
        """Trigger a git-connected deployment on an existing Vercel project."""
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]

        async with httpx.AsyncClient() as client:
            await self._link_github_repo(client, project_name, owner, repo)

            deploy_resp = await client.post(
                f"{VERCEL_API}/v13/deployments",
                headers=self._headers,
                json={
                    "name": project_name,
                    "target": "production",
                    "gitSource": {
                        "type": "github",
                        "org": owner,
                        "repo": repo,
                        "ref": "main",
                    },
                },
            )

            if deploy_resp.status_code == 400:
                self._check_github_error(deploy_resp.json())

            deploy_resp.raise_for_status()
            data = deploy_resp.json()

            return build_result(
                platform_deployment_id=data.get("id", project_name),
                url=await self._fetch_project_url(client, project_name),
                project_name=project_name,
            )

    async def redeploy(
        self,
        platform_deployment_id: str,
        project_name: str,
        repo_url: Optional[str] = None,
    ) -> DeployResult:
        """Trigger a new gitSource deployment for an existing Vercel project."""
        if not repo_url:
            raise ValueError(
                "A GitHub repo URL is required to redeploy on Vercel. "
                "Connect a repo first using the 'Connect & Deploy' option."
            )
        *_, owner, repo = repo_url.rstrip("/").split("/")

        async with httpx.AsyncClient() as client:
            deploy_resp = await client.post(
                f"{VERCEL_API}/v13/deployments",
                headers=self._headers,
                json={
                    "name": project_name,
                    "target": "production",
                    "gitSource": {
                        "type": "github",
                        "org": owner,
                        "repo": repo,
                        "ref": "main",
                    },
                },
            )
            if deploy_resp.status_code == 400:
                self._check_github_error(deploy_resp.json())
            deploy_resp.raise_for_status()
            data = deploy_resp.json()
            return build_result(
                platform_deployment_id=data.get("id", platform_deployment_id),
                url=await self._fetch_project_url(client, project_name),
                project_name=project_name,
            )

    async def list_deployments(self) -> list[DeployResult]:
        """Return all Vercel projects as DeployResult entries.

        Reads each project's `alias` array for the authoritative production URL
        and `link` for the connected GitHub repo, rather than constructing URLs
        from the project name.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{VERCEL_API}/v9/projects",
                headers=self._headers,
            )
            resp.raise_for_status()
            projects = resp.json().get("projects", [])

        results = []
        for proj in projects:
            latest = (proj.get("latestDeployments") or [{}])[0]
            url = self._pick_production_url(proj) or f"https://{proj['name']}.vercel.app"
            repo_url = self._extract_repo_url(proj)

            results.append(
                DeployResult(
                    platform_deployment_id=latest.get("id") or proj["id"],
                    url=url,
                    status=normalize_status(latest.get("readyState", "unknown")),
                    project_name=proj["name"],
                    repo_url=repo_url,
                    deployment_type="static",
                )
            )
        return results

    async def get_project_url(self, project_name: str) -> Optional[str]:
        """Fetch the production alias for an existing Vercel project."""
        async with httpx.AsyncClient() as client:
            return await self._fetch_project_url(client, project_name)

    async def get_project_repo_url(self, project_name: str) -> Optional[str]:
        """Fetch the connected GitHub repo URL for an existing Vercel project.

        Returns the URL string if a repo is connected, "" if the project exists
        but has no repo (so the caller can clear a stale cached URL), or None on
        API error (caller should not change the stored value).
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{VERCEL_API}/v9/projects/{project_name}",
                headers=self._headers,
            )
            if resp.status_code == 200:
                return self._extract_repo_url(resp.json()) or ""
        return None

    async def delete_deployment(
        self, platform_deployment_id: str, project_name: str
    ) -> None:
        """Delete the Vercel project by name (removes all deployments under it)."""
        async with httpx.AsyncClient() as client:
            await self._delete_project(client, project_name)

    async def get_deployment_status(self, deployment_id: str) -> str:
        """Fetch the current readyState for a Vercel deployment."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{VERCEL_API}/v13/deployments/{deployment_id}",
                headers=self._headers,
            )
            if resp.status_code == 404:
                return "not_found"
            resp.raise_for_status()
            return normalize_status(resp.json().get("readyState", "unknown"))

    async def get_deployment_logs(
        self, platform_deployment_id: str, project_name: str
    ) -> list[str]:
        """Fetch build log lines for a Vercel deployment via the events endpoint."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{VERCEL_API}/v2/deployments/{platform_deployment_id}/events",
                headers=self._headers,
                params={"types": "command,stdout,stderr,exit"},
            )
            if resp.status_code != 200:
                return []
            lines = []
            for raw_line in resp.text.splitlines():
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                    text = event.get("payload", {}).get("text", "")
                    if text:
                        lines.append(text)
                except (json.JSONDecodeError, AttributeError):
                    lines.append(raw_line)
            return lines

    async def list_env_vars(
        self, platform_deployment_id: str, project_name: str
    ) -> list[dict]:
        """Return env vars for a Vercel project as [{key, value, id}] dicts."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{VERCEL_API}/v9/projects/{project_name}/env",
                headers=self._headers,
            )
            if resp.status_code != 200:
                return []
            return [
                {"key": e.get("key", ""), "value": e.get("value", ""), "id": e.get("id", "")}
                for e in resp.json().get("envs", [])
            ]

    async def set_env_vars(
        self, platform_deployment_id: str, project_name: str, env_vars: list[dict]
    ) -> None:
        """Upsert env vars on a Vercel project (creates each var individually)."""
        async with httpx.AsyncClient() as client:
            existing = await self.list_env_vars(platform_deployment_id, project_name)
            existing_map = {e["key"]: e["id"] for e in existing if e.get("id")}
            for ev in env_vars:
                key, value = ev["key"], ev["value"]
                if key in existing_map:
                    await client.patch(
                        f"{VERCEL_API}/v9/projects/{project_name}/env/{existing_map[key]}",
                        headers=self._headers,
                        json={"value": value},
                    )
                else:
                    await client.post(
                        f"{VERCEL_API}/v9/projects/{project_name}/env",
                        headers=self._headers,
                        json={
                            "key": key,
                            "value": value,
                            "type": "plain",
                            "target": ["production", "preview", "development"],
                        },
                    )

    async def delete_env_var(
        self, platform_deployment_id: str, project_name: str, key: str
    ) -> None:
        """Delete an env var from a Vercel project by key."""
        existing = await self.list_env_vars(platform_deployment_id, project_name)
        for ev in existing:
            if ev["key"] == key and ev.get("id"):
                async with httpx.AsyncClient() as client:
                    await client.delete(
                        f"{VERCEL_API}/v9/projects/{project_name}/env/{ev['id']}",
                        headers=self._headers,
                    )
                return

    async def list_domains(
        self, platform_deployment_id: str, project_name: str
    ) -> list[str]:
        """Return custom domains for a Vercel project."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{VERCEL_API}/v9/projects/{project_name}/domains",
                headers=self._headers,
            )
            if resp.status_code != 200:
                return []
            return [d.get("name", "") for d in resp.json().get("domains", []) if d.get("name")]

    async def add_domain(
        self, platform_deployment_id: str, project_name: str, domain: str
    ) -> None:
        """Add a custom domain to a Vercel project."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{VERCEL_API}/v9/projects/{project_name}/domains",
                headers=self._headers,
                json={"name": domain},
            )
            resp.raise_for_status()

    async def remove_domain(
        self, platform_deployment_id: str, project_name: str, domain: str
    ) -> None:
        """Remove a custom domain from a Vercel project."""
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{VERCEL_API}/v9/projects/{project_name}/domains/{domain}",
                headers=self._headers,
            )
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()
