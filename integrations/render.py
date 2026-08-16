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

    async def get_build_config(
        self, platform_deployment_id: str, project_name: str
    ) -> dict:
        """Return the current build command and response headers for a Render service."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API}/services/{platform_deployment_id}",
                headers=self._headers,
            )
            if resp.status_code != 200:
                return {"build_command": "", "headers": []}
            service = resp.json().get("service", {})
            details = service.get("serviceDetails", {})
            return {
                "build_command": details.get("buildCommand", "") or "",
                "headers": details.get("headers", []),
            }

    async def update_build_command(
        self,
        platform_deployment_id: str,
        project_name: str,
        build_command: str,
        apply_cors: bool = True,
    ) -> None:
        """PATCH the Render service to set build command and optionally CORS headers.

        Render ignores render.yaml for API-created services; settings must be
        applied explicitly via PATCH.  apply_cors=True adds permissive CORS
        response headers so the site is reachable from other origins (e.g.
        testing from a Vercel-hosted page).
        """
        service_details: dict = {
            "buildCommand": build_command,
            "headers": [
                {"path": "/*", "name": "Access-Control-Allow-Origin", "value": "*"},
                {"path": "/*", "name": "Access-Control-Allow-Methods", "value": "GET, HEAD, OPTIONS"},
                {"path": "/*", "name": "Access-Control-Allow-Headers", "value": "*"},
            ] if apply_cors else [],
        }
        payload = {"serviceDetails": service_details}
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{RENDER_API}/services/{platform_deployment_id}",
                headers=self._headers,
                json=payload,
            )
            if resp.status_code not in (200, 201):
                resp.raise_for_status()

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

    async def get_deployment_logs(
        self, platform_deployment_id: str, project_name: str
    ) -> list[str]:
        """Fetch recent log lines for a Render service."""
        async with httpx.AsyncClient() as client:
            logs_resp = await client.get(
                f"{RENDER_API}/services/{platform_deployment_id}/logs",
                headers=self._headers,
                params={"limit": 100, "direction": "backward"},
            )
            if logs_resp.status_code != 200:
                return []
            entries = logs_resp.json()
            if not isinstance(entries, list):
                return []
            result = []
            for e in entries:
                # Render wraps each entry: {"cursor": "...", "log": {"message": "..."}}
                log_obj = e.get("log", e)
                msg = log_obj.get("message", log_obj.get("text", ""))
                if msg:
                    result.append(msg)
            return result

    async def list_env_vars(
        self, platform_deployment_id: str, project_name: str
    ) -> list[dict]:
        """Return env vars for a Render service as [{key, value}] dicts."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API}/services/{platform_deployment_id}/env-vars",
                headers=self._headers,
            )
            if resp.status_code != 200:
                return []
            result = []
            for e in resp.json():
                # Render wraps each item: {"cursor": "...", "envVar": {"key": ..., "value": ...}}
                env_obj = e.get("envVar", e)
                key = env_obj.get("key", "")
                if key:
                    result.append({"key": key, "value": env_obj.get("value", "")})
            return result

    async def set_env_vars(
        self, platform_deployment_id: str, project_name: str, env_vars: list[dict]
    ) -> None:
        """Overwrite all env vars on a Render service."""
        async with httpx.AsyncClient() as client:
            existing = await self.list_env_vars(platform_deployment_id, project_name)
            merged = {e["key"]: e["value"] for e in existing}
            for ev in env_vars:
                merged[ev["key"]] = ev["value"]
            resp = await client.put(
                f"{RENDER_API}/services/{platform_deployment_id}/env-vars",
                headers=self._headers,
                json=[{"key": k, "value": v} for k, v in merged.items()],
            )
            if resp.status_code not in (200, 201):
                resp.raise_for_status()

    async def delete_env_var(
        self, platform_deployment_id: str, project_name: str, key: str
    ) -> None:
        """Remove an env var from a Render service by re-PUTting without it."""
        existing = await self.list_env_vars(platform_deployment_id, project_name)
        remaining = [e for e in existing if e["key"] != key]
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{RENDER_API}/services/{platform_deployment_id}/env-vars",
                headers=self._headers,
                json=remaining,
            )
            if resp.status_code not in (200, 201):
                resp.raise_for_status()

    async def list_domains(
        self, platform_deployment_id: str, project_name: str
    ) -> list[str]:
        """Return custom domains for a Render service."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API}/services/{platform_deployment_id}/custom-domains",
                headers=self._headers,
            )
            if resp.status_code != 200:
                return []
            return [
                d.get("customDomain", {}).get("name", d.get("name", ""))
                for d in resp.json()
                if isinstance(d, dict)
            ]

    async def add_domain(
        self, platform_deployment_id: str, project_name: str, domain: str
    ) -> None:
        """Add a custom domain to a Render service."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_API}/services/{platform_deployment_id}/custom-domains",
                headers=self._headers,
                json={"name": domain},
            )
            resp.raise_for_status()

    async def remove_domain(
        self, platform_deployment_id: str, project_name: str, domain: str
    ) -> None:
        """Remove a custom domain from a Render service."""
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{RENDER_API}/services/{platform_deployment_id}/custom-domains/{domain}",
                headers=self._headers,
            )
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()
