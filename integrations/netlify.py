"""Netlify REST API client."""

from typing import Optional

import httpx

from integrations.base import BasePlatformClient, DeployResult, safe_delete

NETLIFY_API = "https://api.netlify.com/api/v1"


class NetlifyClient(BasePlatformClient):
    """Async client for the Netlify REST API."""

    def __init__(self, token: str):
        """Initialise with a Netlify personal access token."""
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def create_deployment(
        self, project_name: str, repo_url: Optional[str] = None
    ) -> DeployResult:
        """Create a Netlify site, optionally connected to a GitHub repo."""
        site_payload: dict = {"name": project_name}

        if repo_url:
            parts = repo_url.rstrip("/").split("/")
            owner, repo = parts[-2], parts[-1]
            site_payload["repo"] = {
                "provider": "github",
                "repo": f"{owner}/{repo}",
                "branch": "main",
                "cmd": "",
                "dir": ".",
            }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{NETLIFY_API}/sites",
                headers=self._headers,
                json=site_payload,
            )
            resp.raise_for_status()
            data = resp.json()

            url = data.get("ssl_url") or data.get("url")
            status = data.get("state", "unknown")

            return DeployResult(
                platform_deployment_id=data["id"],
                url=url,
                status=status,
                project_name=project_name,
            )

    async def list_deployments(self) -> list[DeployResult]:
        """Return all Netlify sites as DeployResult entries."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{NETLIFY_API}/sites",
                headers=self._headers,
            )
            resp.raise_for_status()
            sites = resp.json()

        results = []
        for site in sites:
            url = site.get("ssl_url") or site.get("url")
            results.append(
                DeployResult(
                    platform_deployment_id=site["id"],
                    url=url,
                    status=site.get("state", "unknown"),
                    project_name=site.get("name", ""),
                )
            )
        return results

    async def connect_repo(
        self, platform_deployment_id: str, project_name: str, repo_url: str
    ) -> DeployResult:
        """Connect a GitHub repo to an existing Netlify site and trigger a build."""
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{NETLIFY_API}/sites/{platform_deployment_id}",
                headers=self._headers,
                json={
                    "repo": {
                        "provider": "github",
                        "repo": f"{owner}/{repo}",
                        "branch": "main",
                        "cmd": "",
                        "dir": ".",
                    }
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return DeployResult(
            platform_deployment_id=platform_deployment_id,
            url=data.get("ssl_url") or data.get("url"),
            status=data.get("state", "building"),
            project_name=project_name,
        )

    async def redeploy(
        self,
        platform_deployment_id: str,
        project_name: str,
        repo_url: Optional[str] = None,
    ) -> DeployResult:
        """Trigger a new build for an existing Netlify site."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{NETLIFY_API}/sites/{platform_deployment_id}/builds",
                headers=self._headers,
            )
            resp.raise_for_status()
        return DeployResult(
            platform_deployment_id=platform_deployment_id,
            url=None,
            status="building",
            project_name=project_name,
        )

    async def delete_deployment(
        self, platform_deployment_id: str, project_name: str
    ) -> None:
        """Delete a Netlify site by its site ID."""
        async with httpx.AsyncClient() as client:
            await safe_delete(
                client, f"{NETLIFY_API}/sites/{platform_deployment_id}", self._headers
            )

    async def get_deployment_status(self, deployment_id: str) -> str:
        """Fetch the current state for a Netlify site."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{NETLIFY_API}/sites/{deployment_id}",
                headers=self._headers,
            )
            if resp.status_code == 404:
                return "not_found"
            resp.raise_for_status()
            return resp.json().get("state", "unknown")
