"""Netlify REST API client."""

from typing import Optional

import httpx

from integrations.base import (
    BasePlatformClient, DeployResult, build_result, normalize_status, safe_delete,
)

NETLIFY_API = "https://api.netlify.com/api/v1"


class NetlifyClient(BasePlatformClient):
    """Async client for the Netlify REST API."""

    def __init__(self, token: str):
        """Initialise with a Netlify personal access token."""
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def create_deployment(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        project_name: str,
        repo_url: Optional[str] = None,
        deployment_type: Optional[str] = None,  # pylint: disable=unused-argument
        start_command: Optional[str] = None,  # pylint: disable=unused-argument
        render_runtime: Optional[str] = None,  # pylint: disable=unused-argument
        build_command: Optional[str] = None,  # pylint: disable=unused-argument
    ) -> DeployResult:
        """Create a Netlify site, optionally connected to a GitHub repo."""
        site_payload: dict = {"name": project_name}

        if repo_url:
            parts = repo_url.rstrip("/").split("/")
            owner, repo = parts[-2], parts[-1].removesuffix(".git")
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
            if resp.status_code == 422:
                errors = resp.json().get("errors", {})
                if "subdomain" in errors:
                    raise ValueError(
                        f"Project name '{project_name}' is already taken on Netlify"
                        " — choose a different name"
                    )
                raise ValueError(f"Netlify rejected the request: {resp.text}")
            resp.raise_for_status()
            data = resp.json()

            url = data.get("ssl_url") or data.get("url")
            if repo_url:
                return build_result(
                    platform_deployment_id=data["id"],
                    url=url,
                    project_name=project_name,
                )
            return DeployResult(
                platform_deployment_id=data["id"],
                url=url,
                status=normalize_status(data.get("state", "unknown")),
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
            # published_deploy.state reflects the actual build outcome (e.g. "error");
            # site-level state stays "current" even after a failed build.
            raw_state = (
                (site.get("published_deploy") or {}).get("state")
                or site.get("state", "unknown")
            )
            results.append(
                DeployResult(
                    platform_deployment_id=site["id"],
                    url=url,
                    status=normalize_status(raw_state),
                    project_name=site.get("name", ""),
                    deployment_type="static",
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

        return build_result(
            platform_deployment_id=platform_deployment_id,
            url=data.get("ssl_url") or data.get("url"),
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
        return build_result(
            platform_deployment_id=platform_deployment_id,
            url=None,
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
        """Fetch the build status by checking the latest deploy (not site-level state).

        Site state stays "current" even after a failed build; the deploy-level
        state reflects the actual build outcome (e.g. "error", "building").
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{NETLIFY_API}/sites/{deployment_id}/deploys",
                headers=self._headers,
                params={"per_page": 1},
            )
            if resp.status_code == 404:
                return "not_found"
            resp.raise_for_status()
            deploys = resp.json()
            if not deploys:
                return "ready"
            return normalize_status(deploys[0].get("state", "unknown"))

    async def get_deployment_logs(
        self, platform_deployment_id: str, project_name: str
    ) -> list[str]:
        """Fetch build log lines for the latest Netlify deploy of a site.

        Netlify's static log for a completed build lives at a pre-signed S3 URL
        stored in deploy.links.logfile.  The /deploys/{id}/log REST endpoint
        only streams during an active build and returns [] for finished ones.
        """
        async with httpx.AsyncClient() as client:
            deploys_resp = await client.get(
                f"{NETLIFY_API}/sites/{platform_deployment_id}/deploys",
                headers=self._headers,
                params={"per_page": 1},
            )
            if deploys_resp.status_code != 200 or not deploys_resp.json():
                return []
            deploy = deploys_resp.json()[0]
            deploy_id = deploy.get("id")
            if not deploy_id:
                return []

            # Primary: pre-signed logfile URL embedded in the deploy object
            log_url = (deploy.get("links") or {}).get("logfile")
            if log_url:
                log_resp = await client.get(log_url)
                if log_resp.status_code == 200 and log_resp.text.strip():
                    return [line for line in log_resp.text.splitlines() if line.strip()]

            # Fallback: streaming log endpoint (only populated during active builds)
            log_resp = await client.get(
                f"{NETLIFY_API}/deploys/{deploy_id}/log",
                headers=self._headers,
            )
            if log_resp.status_code != 200:
                error_msg = deploy.get("error_message")
                return [error_msg] if error_msg else []
            try:
                entries = log_resp.json()
                if isinstance(entries, list):
                    return [e["m"] for e in entries if isinstance(e, dict) and e.get("m")]
            except Exception:  # pylint: disable=broad-except  # nosec B110
                pass
            return [line for line in log_resp.text.splitlines() if line.strip()]

    async def get_project_url(self, project_name: str) -> Optional[str]:
        """Netlify does not expose a project-name URL lookup — always None."""
        _ = project_name
        return None

    async def get_project_repo_url(self, project_name: str) -> Optional[str]:
        """Return the connected GitHub repo URL for a Netlify site by name.

        Returns the URL string if a repo is connected, "" if the site exists
        but has no repo (so the caller can clear a stale cached URL), or None
        on API error (caller should not change the stored value).
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{NETLIFY_API}/sites",
                headers=self._headers,
                params={"name": project_name},
            )
            if resp.status_code != 200:
                return None
            for site in resp.json():
                if site.get("name") == project_name:
                    repo = site.get("repo") or {}
                    repo_name = repo.get("repo", "")  # "owner/repo" format
                    return f"https://github.com/{repo_name}" if repo_name else ""
        return None

    async def _get_site_env(self, client: httpx.AsyncClient, site_id: str) -> dict:
        """Return the current build_settings.env dict for a Netlify site."""
        resp = await client.get(f"{NETLIFY_API}/sites/{site_id}", headers=self._headers)
        if resp.status_code != 200:
            return {}
        return resp.json().get("build_settings", {}).get("env") or {}

    async def list_env_vars(
        self, platform_deployment_id: str, project_name: str
    ) -> list[dict]:
        """Return env vars stored in build_settings.env for a Netlify site."""
        async with httpx.AsyncClient() as client:
            env = await self._get_site_env(client, platform_deployment_id)
            return [{"key": k, "value": v} for k, v in env.items()]

    async def set_env_vars(
        self, platform_deployment_id: str, project_name: str, env_vars: list[dict]
    ) -> None:
        """Merge env vars into build_settings.env and PATCH the Netlify site."""
        async with httpx.AsyncClient() as client:
            existing = await self._get_site_env(client, platform_deployment_id)
            for ev in env_vars:
                existing[ev["key"]] = ev["value"]
            resp = await client.patch(
                f"{NETLIFY_API}/sites/{platform_deployment_id}",
                headers=self._headers,
                json={"build_settings": {"env": existing}},
            )
            if resp.status_code not in (200, 201, 204):
                resp.raise_for_status()

    async def delete_env_var(
        self, platform_deployment_id: str, project_name: str, key: str
    ) -> None:
        """Remove an env var from build_settings.env and PATCH the Netlify site."""
        async with httpx.AsyncClient() as client:
            existing = await self._get_site_env(client, platform_deployment_id)
            existing.pop(key, None)
            resp = await client.patch(
                f"{NETLIFY_API}/sites/{platform_deployment_id}",
                headers=self._headers,
                json={"build_settings": {"env": existing}},
            )
            if resp.status_code not in (200, 201, 204):
                resp.raise_for_status()

    async def list_domains(
        self, platform_deployment_id: str, project_name: str
    ) -> list[str]:
        """Return the custom domain for a Netlify site (at most one)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{NETLIFY_API}/sites/{platform_deployment_id}",
                headers=self._headers,
            )
            if resp.status_code != 200:
                return []
            domain = resp.json().get("custom_domain")
            return [domain] if domain else []

    async def add_domain(
        self, platform_deployment_id: str, project_name: str, domain: str
    ) -> None:
        """Set the custom domain on a Netlify site."""
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{NETLIFY_API}/sites/{platform_deployment_id}",
                headers=self._headers,
                json={"custom_domain": domain},
            )
            resp.raise_for_status()

    async def remove_domain(
        self, platform_deployment_id: str, project_name: str, domain: str
    ) -> None:
        """Remove the custom domain from a Netlify site."""
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{NETLIFY_API}/sites/{platform_deployment_id}/domain",
                headers=self._headers,
            )
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()
