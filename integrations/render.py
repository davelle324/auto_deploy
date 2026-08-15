"""Render REST API client."""

from typing import Optional

import httpx

from integrations.base import BasePlatformClient, DeployResult, safe_delete

RENDER_API = "https://api.render.com/v1"


class RenderClient(BasePlatformClient):
    """Async client for the Render REST API."""

    def __init__(self, token: str):
        """Initialise with a Render API key."""
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def create_deployment(
        self, project_name: str, repo_url: Optional[str] = None
    ) -> DeployResult:
        """Create a Render static site service. Requires a GitHub repo URL."""
        if not repo_url:
            return DeployResult(
                platform_deployment_id="pending",
                url=None,
                status="requires_repo",
                project_name=project_name,
            )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_API}/services",
                headers=self._headers,
                json={
                    "type": "static_site",
                    "name": project_name,
                    "repo": repo_url,
                    "branch": "main",
                    "buildCommand": "",
                    "staticPublishPath": ".",
                    "serviceDetails": {"pullRequestPreviewsEnabled": "no"},
                },
            )
            resp.raise_for_status()
            data = resp.json()

            service = data.get("service", {})
            service_id = service.get("id", "")
            raw_url = service.get("serviceDetails", {}).get("url")
            url: Optional[str] = (
                f"https://{raw_url}"
                if raw_url and not raw_url.startswith("https://")
                else raw_url
            )

            return DeployResult(
                platform_deployment_id=service_id or "unknown",
                url=url,
                status="deploying" if service_id else "failed",
                project_name=project_name,
            )

    async def list_deployments(self) -> list[DeployResult]:
        """Return all Render static site services as DeployResult entries."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API}/services",
                headers=self._headers,
                params={"type": "static_site", "limit": 100},
            )
            resp.raise_for_status()
            services = resp.json()

        results = []
        for item in services:
            service = item.get("service", {})
            service_id = service.get("id")
            if not service_id:
                continue
            raw_url = service.get("serviceDetails", {}).get("url")
            url: Optional[str] = (
                f"https://{raw_url}"
                if raw_url and not raw_url.startswith("https://")
                else raw_url
            )
            suspended = service.get("suspended", "not_suspended")
            status = "suspended" if suspended == "suspended" else "active"
            results.append(
                DeployResult(
                    platform_deployment_id=service_id,
                    url=url,
                    status=status,
                    project_name=service.get("name", ""),
                )
            )
        return results

    async def connect_repo(
        self, platform_deployment_id: str, project_name: str, repo_url: str
    ) -> DeployResult:
        """Render services are always repo-backed; a repo cannot be added after creation."""
        raise ValueError(
            "Render does not support connecting a repo after a service is created. "
            "Delete this deployment and create a new one with a repo URL."
        )

    async def delete_deployment(
        self, platform_deployment_id: str, project_name: str
    ) -> None:
        """Delete a Render service by its service ID."""
        async with httpx.AsyncClient() as client:
            await safe_delete(
                client, f"{RENDER_API}/services/{platform_deployment_id}", self._headers
            )

    async def get_deployment_status(self, deployment_id: str) -> str:
        """Fetch the current status for a Render service."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API}/services/{deployment_id}",
                headers=self._headers,
            )
            if resp.status_code == 404:
                return "not_found"
            resp.raise_for_status()
            service = resp.json().get("service", {})
            suspended = service.get("suspended", "not_suspended")
            return "suspended" if suspended == "suspended" else "active"
