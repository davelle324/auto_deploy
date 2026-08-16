"""Abstract base class and shared result type for platform API clients."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import httpx

# Maps every platform-specific status string to a common set:
#   deploying · ready · failed · suspended · unknown · not_found
_STATUS_MAP: dict[str, str] = {
    # Vercel readyState
    "initializing": "deploying",
    "building": "deploying",
    "queued": "deploying",
    "canceled": "failed",
    "error": "failed",
    # Netlify deploy state
    "new": "deploying",
    "enqueued": "deploying",
    "current": "ready",
    # Render deploy status
    "created": "deploying",
    "build_in_progress": "deploying",
    "update_in_progress": "deploying",
    "pre_deploy_in_progress": "deploying",
    "live": "ready",
    "build_failed": "failed",
    "update_failed": "failed",
    "pre_deploy_failed": "failed",
    "deactivated": "suspended",
}


def normalize_status(raw: str) -> str:
    """Return a platform-agnostic status string for any platform-specific value."""
    lowered = raw.lower()
    return _STATUS_MAP.get(lowered, lowered)


def build_result(
    platform_deployment_id: str,
    url: Optional[str],
    project_name: str,
    repo_url: Optional[str] = None,
) -> "DeployResult":
    """Return a DeployResult for any operation that triggers a build.

    Always sets status to 'deploying' so the dashboard starts polling
    regardless of what the platform API reports at creation time.
    """
    return DeployResult(
        platform_deployment_id=platform_deployment_id,
        url=url,
        status="deploying",
        project_name=project_name,
        repo_url=repo_url,
    )


@dataclass
class DeployResult:
    """Normalized deployment result returned by all platform clients."""

    platform_deployment_id: str
    url: Optional[str]
    status: str
    project_name: str = ""
    repo_url: Optional[str] = field(default=None)


async def safe_delete(client: httpx.AsyncClient, url: str, headers: dict) -> None:
    """Issue a DELETE request, ignoring 404 and treating 200/204 as success."""
    resp = await client.delete(url, headers=headers)
    if resp.status_code not in (200, 204, 404):
        resp.raise_for_status()


class PartialDeployError(Exception):
    """Raised when a project was created on the platform but deployment failed.

    The project exists on the platform (tracked via `partial_result`) but has
    no live deployment.  Callers should persist the partial result to the local
    DB so the project appears in the dashboard.
    """

    def __init__(self, message: str, partial_result: "DeployResult"):
        """Store the partial result alongside the error message."""
        super().__init__(message)
        self.partial_result = partial_result


class BasePlatformClient(ABC):
    """Common interface that every platform client must implement."""

    @abstractmethod
    async def create_deployment(
        self, project_name: str, repo_url: Optional[str] = None
    ) -> DeployResult:
        """Create a new project and trigger an initial deployment."""

    @abstractmethod
    async def list_deployments(self) -> list[DeployResult]:
        """Return all projects/sites currently on the platform."""

    @abstractmethod
    async def delete_deployment(
        self, platform_deployment_id: str, project_name: str
    ) -> None:
        """Permanently delete a project/site on the platform."""

    @abstractmethod
    async def connect_repo(
        self, platform_deployment_id: str, project_name: str, repo_url: str
    ) -> DeployResult:
        """Connect a GitHub repo to an existing project and trigger a new deployment."""

    @abstractmethod
    async def get_deployment_status(self, deployment_id: str) -> str:
        """Return the current status string for an existing deployment."""

    async def redeploy(
        self,
        platform_deployment_id: str,
        project_name: str,
        repo_url: Optional[str] = None,
    ) -> DeployResult:
        """Trigger a new deployment of the latest commit on the platform.

        The default implementation raises ValueError; platforms that support
        manual redeploy override this method.
        """
        _ = platform_deployment_id, project_name, repo_url
        raise ValueError("Manual redeploy is not supported for this platform.")

    async def get_project_url(self, project_name: str) -> Optional[str]:
        """Return the stable production URL for an existing project.

        Returns None if the platform client does not implement URL resolution.
        Subclasses override this to fetch the authoritative domain from the
        platform API rather than constructing a guessed URL.
        """
        _ = project_name
        return None

    async def get_project_repo_url(self, project_name: str) -> Optional[str]:
        """Return the connected GitHub repo URL for an existing project.

        Returns None if the platform client does not support this query.
        Subclasses override this to fetch the repo link from the platform API.
        """
        _ = project_name
        return None

    async def get_deployment_logs(
        self, platform_deployment_id: str, project_name: str
    ) -> list[str]:
        """Return recent build log lines for a deployment.

        Returns an empty list if the platform client does not support log fetching.
        """
        _ = platform_deployment_id, project_name
        return []

    async def list_env_vars(
        self, platform_deployment_id: str, project_name: str
    ) -> list[dict]:
        """Return env vars for a deployment as [{key, value}] dicts.

        Returns an empty list if the platform does not support env var management.
        """
        _ = platform_deployment_id, project_name
        return []

    async def set_env_vars(
        self, platform_deployment_id: str, project_name: str, env_vars: list[dict]
    ) -> None:
        """Upsert env vars for a deployment. Each dict must have 'key' and 'value'."""
        _ = platform_deployment_id, project_name, env_vars
        raise ValueError("Env var management is not supported for this platform.")

    async def delete_env_var(
        self, platform_deployment_id: str, project_name: str, key: str
    ) -> None:
        """Delete a single env var by key."""
        _ = platform_deployment_id, project_name, key
        raise ValueError("Env var management is not supported for this platform.")

    async def list_domains(
        self, platform_deployment_id: str, project_name: str
    ) -> list[str]:
        """Return custom domains attached to a deployment."""
        _ = platform_deployment_id, project_name
        return []

    async def add_domain(
        self, platform_deployment_id: str, project_name: str, domain: str
    ) -> None:
        """Add a custom domain to a deployment."""
        _ = platform_deployment_id, project_name, domain
        raise ValueError("Domain management is not supported for this platform.")

    async def remove_domain(
        self, platform_deployment_id: str, project_name: str, domain: str
    ) -> None:
        """Remove a custom domain from a deployment."""
        _ = platform_deployment_id, project_name, domain
        raise ValueError("Domain management is not supported for this platform.")
