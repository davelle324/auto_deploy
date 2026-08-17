"""Pydantic request and response schemas."""

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from models import Platform

_PROJECT_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


class TokenCreate(BaseModel):
    """Request body for creating or updating a platform token."""

    platform: Platform
    token: str

    @field_validator("token")
    @classmethod
    def token_not_empty(cls, v: str) -> str:
        """Reject blank tokens."""
        v = v.strip()
        if not v:
            raise ValueError("token cannot be empty")
        return v


class TokenResponse(BaseModel):
    """Response indicating whether a platform token is configured."""

    platform: Platform
    configured: bool
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DeploymentCreate(BaseModel):
    """Request body for creating a new deployment."""

    platform: Platform
    project_name: str
    repo_url: Optional[str] = None
    deployment_type: Optional[str] = None

    @field_validator("project_name")
    @classmethod
    def validate_project_name(cls, v: str) -> str:
        """Enforce lowercase-alphanumeric-hyphen names compatible with all three platforms."""
        v = v.strip().lower()
        if not v:
            raise ValueError("project_name cannot be empty")
        if len(v) > 63:  # noqa: PLR2004
            raise ValueError("project_name must be 63 characters or fewer")
        if not _PROJECT_NAME_RE.match(v):
            raise ValueError(
                "project_name must start and end with a letter or number "
                "and contain only lowercase letters, numbers, and hyphens"
            )
        return v

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: Optional[str]) -> Optional[str]:
        """Accept only GitHub HTTPS URLs."""
        if v is None:
            return v
        v = v.strip().rstrip("/").removesuffix(".git")
        if not v.startswith("https://github.com/"):
            raise ValueError(
                "repo_url must be a GitHub HTTPS URL (https://github.com/owner/repo)"
            )
        parts = v.split("/")
        if len(parts) < 5 or not parts[-1] or not parts[-2]:  # noqa: PLR2004
            raise ValueError("repo_url must be in the format https://github.com/owner/repo")
        return v


class ConnectRepoRequest(BaseModel):
    """Request body for connecting a GitHub repo to an existing deployment."""

    repo_url: str

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        """Accept only GitHub HTTPS URLs, strip .git suffix."""
        v = v.strip().rstrip("/").removesuffix(".git")
        if not v.startswith("https://github.com/"):
            raise ValueError(
                "repo_url must be a GitHub HTTPS URL (https://github.com/owner/repo)"
            )
        parts = v.split("/")
        if len(parts) < 5 or not parts[-1] or not parts[-2]:  # noqa: PLR2004
            raise ValueError("repo_url must be in the format https://github.com/owner/repo")
        return v


class DeploymentResponse(BaseModel):
    """Response with deployment details."""

    id: int
    platform: Platform
    project_name: str
    platform_deployment_id: Optional[str] = None
    url: Optional[str] = None
    status: str
    repo_url: Optional[str] = None
    project_id: Optional[int] = None
    deployment_type: Optional[str] = None
    notes: Optional[str] = None
    last_deployed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DeploymentTypeUpdate(BaseModel):
    """Request body for setting a deployment's type."""

    deployment_type: Optional[str] = None


class DeploymentNotesUpdate(BaseModel):
    """Request body for updating deployment notes."""

    notes: Optional[str] = None


class ProjectCreate(BaseModel):
    """Request body for creating an internal project."""

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Reject blank or oversized names."""
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        if len(v) > 100:  # noqa: PLR2004
            raise ValueError("name must be 100 characters or fewer")
        return v


class ProjectResponse(BaseModel):
    """Response with project details."""

    id: int
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AssignProjectRequest(BaseModel):
    """Request body for assigning (or unassigning) a deployment to a project."""

    project_id: Optional[int] = None


class BuildSettingsRequest(BaseModel):
    """Request body for updating a Render service's build command and CORS headers."""

    build_command: str
    apply_cors: bool = True


class DeploymentEventResponse(BaseModel):
    """Response for a single deployment event record."""

    id: int
    deployment_id: int
    platform_event_id: Optional[str] = None
    status: str
    triggered_at: datetime

    model_config = {"from_attributes": True}
