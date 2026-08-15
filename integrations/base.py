"""Abstract base class and shared result type for platform API clients."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class DeployResult:
    """Normalized deployment result returned by all platform clients."""

    platform_deployment_id: str
    url: Optional[str]
    status: str
    project_name: str = ""


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
