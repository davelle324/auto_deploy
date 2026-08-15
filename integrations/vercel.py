"""Vercel REST API client."""

import hashlib
from typing import Optional

import httpx

from integrations.base import BasePlatformClient, DeployResult, PartialDeployError, safe_delete

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
    def _stable_url(project_name: str, data: dict) -> str:
        """Return the stable project alias, falling back to the deployment URL.

        Vercel assigns {project-name}.vercel.app as the canonical alias for
        every project.  The deployment-specific URL (with a random hash) is
        less useful as it changes with every deployment.
        """
        aliases = data.get("alias") or []
        for alias in aliases:
            if alias.endswith(".vercel.app") and "-" not in alias.split(".")[0].replace(
                project_name, ""
            ):
                return f"https://{alias}"
        return f"https://{project_name}.vercel.app"

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

    async def _delete_project(self, client: httpx.AsyncClient, project_name: str) -> None:
        """Best-effort project deletion — ignores 404 (already gone)."""
        await safe_delete(client, f"{VERCEL_API}/v9/projects/{project_name}", self._headers)

    async def create_deployment(
        self, project_name: str, repo_url: Optional[str] = None
    ) -> DeployResult:
        """Create a Vercel project and trigger an initial deployment."""
        async with httpx.AsyncClient() as client:
            project_resp = await client.post(
                f"{VERCEL_API}/v9/projects",
                headers=self._headers,
                json={"name": project_name},
            )
            project_resp.raise_for_status()

            if repo_url:
                parts = repo_url.rstrip("/").split("/")
                owner, repo = parts[-2], parts[-1]
                deploy_payload = {
                    "name": project_name,
                    "gitSource": {
                        "type": "github",
                        "org": owner,
                        "repo": repo,
                        "ref": "main",
                    },
                }
            else:
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
            return DeployResult(
                platform_deployment_id=data.get("id", project_name),
                url=self._stable_url(project_name, data),
                status=data.get("readyState", "INITIALIZING").lower(),
                project_name=project_name,
            )

    async def connect_repo(
        self, platform_deployment_id: str, project_name: str, repo_url: str
    ) -> DeployResult:
        """Trigger a git-connected deployment on an existing Vercel project."""
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]

        async with httpx.AsyncClient() as client:
            deploy_resp = await client.post(
                f"{VERCEL_API}/v13/deployments",
                headers=self._headers,
                json={
                    "name": project_name,
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

            return DeployResult(
                platform_deployment_id=data.get("id", project_name),
                url=self._stable_url(project_name, data),
                status=data.get("readyState", "INITIALIZING").lower(),
                project_name=project_name,
            )

    async def list_deployments(self) -> list[DeployResult]:
        """Return all Vercel projects as DeployResult entries."""
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
            results.append(
                DeployResult(
                    platform_deployment_id=latest.get("id") or proj["id"],
                    url=f"https://{proj['name']}.vercel.app",
                    status=latest.get("readyState", "unknown").lower(),
                    project_name=proj["name"],
                )
            )
        return results

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
            return resp.json().get("readyState", "unknown").lower()
