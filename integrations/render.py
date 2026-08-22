"""Render REST API client."""

import logging
from typing import Optional

import httpx

from integrations.base import (
    BasePlatformClient, DeployResult, build_result, normalize_status, safe_delete,
)

logger = logging.getLogger(__name__)

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

    # Default versions for native-runtime web services.
    # Docker services don't need envSpecificDetails; all others do.
    # Fallback build commands used when the user leaves the field blank.
    _RUNTIME_BUILD_DEFAULTS: dict[str, str] = {
        "python":  "pip install -r requirements.txt",
        "node":    "npm install",
        "go":      "go build ./...",
        "ruby":    "bundle install",
        "elixir":  "mix deps.get && mix compile",
        "rust":    "cargo build --release",
    }

    @staticmethod
    def _build_service_payload(
        project_name: str, owner_id: str, repo_url: str, opts: dict
    ) -> dict:
        """Return the JSON payload for a Render service creation request."""
        if opts.get("deployment_type") == "backend":
            runtime = opts.get("render_runtime") or "docker"
            build_cmd = (
                opts.get("build_command")
                or RenderClient._RUNTIME_BUILD_DEFAULTS.get(runtime, "")
            )
            # buildCommand and startCommand live inside envSpecificDetails for
            # native-runtime web services (Render API v1 schema requirement).
            env_specific: dict = {
                "buildCommand": build_cmd,
                "startCommand": opts.get("start_command") or "",
            }
            return {
                "type": "web_service",
                "name": project_name,
                "ownerId": owner_id,
                "repo": repo_url,
                "branch": "main",
                "serviceDetails": {
                    "env": runtime,
                    "plan": "free",
                    "region": "oregon",
                    "envSpecificDetails": env_specific,
                },
            }
        return {
            "type": "static_site",
            "name": project_name,
            "ownerId": owner_id,
            "repo": repo_url,
            "branch": "main",
            "buildCommand": None,
            "serviceDetails": {"publishPath": "."},
        }

    async def _fetch_url_after_create(
        self, client: httpx.AsyncClient, service_id: str, initial_url: Optional[str]
    ) -> Optional[str]:
        """Fetch the public URL for a newly created service if not yet assigned."""
        if initial_url or not service_id:
            return initial_url
        get_resp = await client.get(
            f"{RENDER_API}/services/{service_id}", headers=self._headers
        )
        if get_resp.status_code == 200:
            d = get_resp.json()
            return self._extract_url(d.get("service", d))
        return None

    async def create_deployment(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        project_name: str,
        repo_url: Optional[str] = None,
        deployment_type: Optional[str] = None,
        start_command: Optional[str] = None,
        render_runtime: Optional[str] = None,
        build_command: Optional[str] = None,
    ) -> DeployResult:
        """Create a Render service (static site or web service). Requires a GitHub repo URL."""
        if not repo_url:
            return DeployResult(
                platform_deployment_id="pending",
                url=None,
                status="requires_repo",
                project_name=project_name,
            )

        opts = {
            "deployment_type": deployment_type,
            "start_command": start_command,
            "render_runtime": render_runtime,
            "build_command": build_command,
        }
        async with httpx.AsyncClient() as client:
            owner_id = await self._fetch_owner_id(client)
            payload = self._build_service_payload(project_name, owner_id, repo_url, opts)
            logger.info("Render create-service payload: %s", payload)
            resp = await client.post(
                f"{RENDER_API}/services", headers=self._headers, json=payload
            )
            if not resp.is_success:
                svc = payload.get("serviceDetails", {})
                raise ValueError(
                    f"Render API {resp.status_code}: {resp.text} "
                    f"[svc.buildCommand={svc.get('buildCommand')!r}, "
                    f"svc.env={svc.get('env')!r}, "
                    f"top.buildCommand={payload.get('buildCommand')!r}]"
                )
            service = resp.json().get("service", {})
            service_id = service.get("id", "")
            url = await self._fetch_url_after_create(
                client, service_id, self._extract_url(service)
            )

            if service_id:
                return build_result(
                    platform_deployment_id=service_id,
                    url=url,
                    project_name=project_name,
                )
            return DeployResult(
                platform_deployment_id="unknown",
                url=url,
                status="failed",
                project_name=project_name,
            )

    async def list_deployments(self) -> list[DeployResult]:
        """Return all Render static site services as DeployResult entries."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API}/services",
                headers=self._headers,
                params={"limit": 100},
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
            svc_type = service.get("type", "")
            deployment_type = (
                "static" if svc_type == "static_site"
                else "backend" if svc_type == "web_service"
                else None
            )
            results.append(
                DeployResult(
                    platform_deployment_id=service_id,
                    url=self._extract_url(service),
                    status=status,
                    project_name=service.get("name", ""),
                    repo_url=service.get("repo") or None,
                    deployment_type=deployment_type,
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
                params={"name": project_name, "limit": 100},
            )
            if resp.status_code != 200:
                return None
            for item in resp.json():
                service = item.get("service", {})
                if service.get("name") == project_name:
                    return self._extract_url(service)
        return None

    async def get_project_repo_url(self, project_name: str) -> Optional[str]:
        """Return the connected GitHub repo URL for a Render service by name.

        Returns the URL string if a repo is connected, "" if the service exists
        but has no repo, or None on API error.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API}/services",
                headers=self._headers,
                params={"name": project_name, "limit": 100},
            )
            if resp.status_code != 200:
                return None
            for item in resp.json():
                service = item.get("service", {})
                if service.get("name") == project_name:
                    repo = service.get("repo", "")
                    return repo if repo else ""
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
        return build_result(
            platform_deployment_id=platform_deployment_id,
            url=None,
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
        self, platform_deployment_id: str, project_name: str  # pylint: disable=unused-argument
    ) -> dict:
        """Return the current build command and response headers for a Render service."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API}/services/{platform_deployment_id}",
                headers=self._headers,
            )
            if resp.status_code != 200:
                return {"build_command": "", "headers": []}
            data = resp.json()
            # Some Render endpoints wrap in {"service": {...}}, others return directly
            service = data.get("service", data)
            details = service.get("serviceDetails", {})
            return {
                "build_command": details.get("buildCommand", "") or "",
                "headers": details.get("headers", []),
            }

    async def update_build_command(
        self,
        platform_deployment_id: str,
        project_name: str,  # pylint: disable=unused-argument
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
                {"path": "/*", "name": "Access-Control-Allow-Methods",  # pylint: disable=line-too-long
                 "value": "GET, HEAD, OPTIONS"},
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
        """Fetch the current build status for a Render service.

        Checks the latest deploy's status rather than service-level suspension so
        that build failures are surfaced (a suspended service is only checked when
        no deploys exist yet).
        """
        async with httpx.AsyncClient() as client:
            deploys_resp = await client.get(
                f"{RENDER_API}/services/{deployment_id}/deploys",
                headers=self._headers,
                params={"limit": 1},
            )
            if deploys_resp.status_code == 200:
                deploys = deploys_resp.json()
                if isinstance(deploys, list) and deploys:
                    deploy = deploys[0].get("deploy", deploys[0])
                    return normalize_status(deploy.get("status", "unknown"))

            # Fallback: service-level check (e.g. suspended with no deploys yet)
            svc_resp = await client.get(
                f"{RENDER_API}/services/{deployment_id}",
                headers=self._headers,
            )
            if svc_resp.status_code == 404:
                return "not_found"
            svc_resp.raise_for_status()
            data = svc_resp.json()
            service = data.get("service", data)
            return "suspended" if service.get("suspended") == "suspended" else "ready"

    @staticmethod
    def _extract_log_lines(entries: list) -> list[str]:
        """Extract message strings from Render log entry list."""
        result = []
        for e in entries:
            log_obj = e.get("log", e)
            msg = log_obj.get("message", log_obj.get("text", ""))
            if msg:
                result.append(msg)
        return result

    async def get_deployment_logs(
        self, platform_deployment_id: str, project_name: str
    ) -> list[str]:
        """Fetch build log lines for a Render static site service.

        Static sites have no runtime process so the generic /logs endpoint
        returns nothing.  We first try the deploy-specific log endpoint which
        captures build output, then fall back to the time-scoped generic endpoint.
        """
        async with httpx.AsyncClient() as client:
            # Get the latest deploy ID and time window
            deploys_resp = await client.get(
                f"{RENDER_API}/services/{platform_deployment_id}/deploys",
                headers=self._headers,
                params={"limit": 1},
            )
            deploy_id = None
            start_time = None
            if deploys_resp.status_code == 200:
                deploys = deploys_resp.json()
                if isinstance(deploys, list) and deploys:
                    deploy = deploys[0].get("deploy", deploys[0])
                    deploy_id = deploy.get("id")
                    start_time = deploy.get("createdAt")

            # Primary: deploy-specific log endpoint (build output for static sites)
            if deploy_id:
                log_resp = await client.get(
                    f"{RENDER_API}/services/{platform_deployment_id}/deploys/{deploy_id}/log",
                    headers=self._headers,
                )
                if log_resp.status_code == 200:
                    try:
                        entries = log_resp.json()
                        if isinstance(entries, list):
                            lines = self._extract_log_lines(entries)
                            if lines:
                                return lines
                    except Exception:  # pylint: disable=broad-exception-caught  # nosec B110
                        pass
                    text = log_resp.text.strip()
                    if text:
                        return [l for l in text.splitlines() if l.strip()]

            # Fallback: generic logs scoped to deploy start time (no end cutoff)
            params: dict = {"limit": 100, "direction": "forward"}
            if start_time:
                params["startTime"] = start_time

            logs_resp = await client.get(
                f"{RENDER_API}/services/{platform_deployment_id}/logs",
                headers=self._headers,
                params=params,
            )
            if logs_resp.status_code != 200:
                return []
            entries = logs_resp.json()
            if not isinstance(entries, list):
                return []
            return self._extract_log_lines(entries)

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
        if domain.lower().endswith(".onrender.com"):
            raise ValueError(
                ".onrender.com domains are platform-managed and cannot be added as custom domains"
            )
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_API}/services/{platform_deployment_id}/custom-domains",
                headers=self._headers,
                json={"name": domain},
            )
            if resp.status_code >= 400:
                raise ValueError(
                    f"Render rejected domain '{domain}': {resp.status_code} — {resp.text}"
                )

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
