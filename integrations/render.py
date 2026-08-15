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

    async def _fetch_owner_id(self, client: httpx.AsyncClient) -> str:
        """Return the first owner ID associated with this API key.

        Render requires ``ownerId`` on every service creation request.
        The ``GET /v1/owners`` endpoint returns the list of users/teams the
        current API key can act on behalf of.
        """
        resp = await client.get(f"{RENDER_API}/owners", headers=self._headers)
        resp.raise_for_status()
        owners = resp.json()
        if not owners:
            raise ValueError("No Render owners found for this API key.")
        return owners[0]["owner"]["id"]

    @staticmethod
    def _extract_url(service: dict) -> Optional[str]:
        """Return the public HTTPS URL from a Render service dict."""
        raw = service.get("serviceDetails", {}).get("url")
        if not raw:
            return None
        return raw if raw.startswith("https://") else f"https://{raw}"

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
            owner_id = await self._fetch_owner_id(client)
            resp = await client.post(
                f"{RENDER_API}/services",
                headers=self._headers,
                json={
                    "type": "static_site",
                    "name": project_name,
                    "ownerId": owner_id,
                    "repo": repo_url,
                    "branch": "main",
                    "buildCommand": None,
                    "serviceDetails": {"publishPath": "."},
                },
            )
            resp.raise_for_status()
            data = resp.json()

            service = data.get("service", {})
            service_id = service.get("id", "")
            url = self._extract_url(service)

            # URL may be null right after creation — try a follow-up GET.
            if not url and service_id:
                get_resp = await client.get(
                    f"{RENDER_API}/services/{service_id}",
                    headers=self._headers,
                )
                if get_resp.status_code == 200:
                    url = self._extract_url(get_resp.json().get("service", {}))

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
            suspended = service.get("suspended", "not_suspended")
            status = "suspended" if suspended == "suspended" else "ready"
            results.append(
                DeployResult(
                    platform_deployment_id=service_id,
                    url=self._extract_url(service),
                    status=status,
                    project_name=service.get("name", ""),
                )
            )
        return results

    async def get_project_url(self, project_name: str) -> Optional[str]:
        """Fetch the current public URL for a Render service by name.

        Called by the sync endpoint to refresh the URL after Render finishes
        its initial deployment (the URL may be null in the creation response).
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API}/services",
                headers=self._headers,
                params={"name": project_name, "type": "static_site", "limit": 100},
            )
            if resp.status_code != 200:
                return None
            for item in resp.json():
                service = item.get("service", {})
                if service.get("name") == project_name:
                    return self._extract_url(service)
        return None

    async def redeploy(
        self,
        platform_deployment_id: str,
        project_name: str,
        repo_url: Optional[str] = None,
    ) -> DeployResult:
        """Trigger a new deploy for an existing Render service."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_API}/services/{platform_deployment_id}/deploys",
                headers=self._headers,
                json={"clearCache": "do_not_clear"},
            )
            resp.raise_for_status()
        return DeployResult(
            platform_deployment_id=platform_deployment_id,
            url=None,
            status="deploying",
            project_name=project_name,
        )

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
            return "suspended" if suspended == "suspended" else "ready"
