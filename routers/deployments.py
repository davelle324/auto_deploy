"""API routes for creating and querying deployments."""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from integrations.base import PartialDeployError
from integrations.netlify import NetlifyClient
from integrations.render import RenderClient
from integrations.vercel import VercelClient
from models import Deployment, DeploymentEvent, Platform, PlatformToken, Project
from schemas import (
    AssignProjectRequest,
    BuildSettingsRequest,
    ConnectRepoRequest,
    DeploymentCreate,
    DeploymentEventResponse,
    DeploymentResponse,
    DeploymentNotesUpdate,
    DeploymentTypeUpdate,
)
from security import decrypt_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/deployments", tags=["deployments"])

_PLATFORM_TYPE_DEFAULTS = {
    Platform.VERCEL: "static",
    Platform.NETLIFY: "static",
    Platform.RENDER: "static",
}


async def _get_decrypted_token(platform: Platform, db: AsyncSession) -> str:
    """Fetch and decrypt the stored API token for the given platform."""
    result = await db.execute(
        select(PlatformToken).where(PlatformToken.platform == platform)
    )
    token_row = result.scalar_one_or_none()
    if not token_row:
        raise HTTPException(
            status_code=400, detail=f"No API token configured for {platform.value}"
        )
    return decrypt_token(token_row.encrypted_token)


def _build_client(platform: Platform, token: str):
    """Instantiate the correct platform client for the given platform."""
    clients = {
        Platform.VERCEL: VercelClient,
        Platform.NETLIFY: NetlifyClient,
        Platform.RENDER: RenderClient,
    }
    return clients[platform](token)


@router.post("/", response_model=DeploymentResponse)
async def create_deployment(data: DeploymentCreate, db: AsyncSession = Depends(get_db)):
    """Provision a new project on the chosen platform and record the deployment."""
    token = await _get_decrypted_token(data.platform, db)
    client = _build_client(data.platform, token)

    try:
        result = await client.create_deployment(data.project_name, data.repo_url)
    except PartialDeployError as exc:
        # Project was created on the platform but deployment failed (e.g. GitHub App
        # not installed).  Save the partial record so it appears in the dashboard,
        # then surface the error so the user knows what to fix.
        partial = exc.partial_result
        deployment = Deployment(
            platform=data.platform,
            project_name=data.project_name,
            platform_deployment_id=partial.platform_deployment_id,
            url=partial.url,
            status=partial.status,
            repo_url=data.repo_url,
        )
        db.add(deployment)
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Include the platform's response body when available so the caller
        # can see the actual rejection reason (e.g. name conflict, bad token).
        body = getattr(getattr(exc, "response", None), "text", None)
        detail = f"Platform API error: {exc}" + (f" — {body}" if body else "")
        raise HTTPException(status_code=502, detail=detail) from exc

    now = datetime.now(timezone.utc)
    deployment = Deployment(
        platform=data.platform,
        project_name=data.project_name,
        platform_deployment_id=result.platform_deployment_id,
        url=result.url,
        status=result.status,
        repo_url=data.repo_url,
        deployment_type=(
            data.deployment_type
            or result.deployment_type
            or _PLATFORM_TYPE_DEFAULTS.get(data.platform)
        ),
        last_deployed_at=now,
    )
    db.add(deployment)
    await db.flush()
    db.add(DeploymentEvent(
        deployment_id=deployment.id,
        platform_event_id=result.platform_deployment_id,
        status=result.status,
    ))
    await db.commit()
    await db.refresh(deployment)
    return deployment


@router.patch("/{deployment_id}/repo", response_model=DeploymentResponse)
async def connect_repo(
    deployment_id: int, data: ConnectRepoRequest, db: AsyncSession = Depends(get_db)
):
    """Connect a GitHub repo to an existing deployment and trigger a new build."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    token = await _get_decrypted_token(deployment.platform, db)
    client = _build_client(deployment.platform, token)

    try:
        deploy_result = await client.connect_repo(
            deployment.platform_deployment_id, deployment.project_name, data.repo_url
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        body = getattr(getattr(exc, "response", None), "text", None)
        detail = f"Platform API error: {exc}" + (f" — {body}" if body else "")
        raise HTTPException(status_code=502, detail=detail) from exc

    deployment.platform_deployment_id = deploy_result.platform_deployment_id
    deployment.url = deploy_result.url
    deployment.status = deploy_result.status
    deployment.repo_url = data.repo_url
    await db.commit()
    await db.refresh(deployment)
    return deployment


@router.post("/{deployment_id}/redeploy", response_model=DeploymentResponse)
async def redeploy_deployment(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """Trigger a new deployment of the latest commit for an existing project."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    token = await _get_decrypted_token(deployment.platform, db)
    client = _build_client(deployment.platform, token)

    try:
        deploy_result = await client.redeploy(
            deployment.platform_deployment_id,
            deployment.project_name,
            deployment.repo_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        body = getattr(getattr(exc, "response", None), "text", None)
        detail = f"Platform API error: {exc}" + (f" — {body}" if body else "")
        raise HTTPException(status_code=502, detail=detail) from exc

    deployment.status = deploy_result.status
    deployment.last_deployed_at = datetime.now(timezone.utc)
    # Update the deployment ID if the platform issued a new one (e.g. Vercel)
    if deploy_result.platform_deployment_id:
        deployment.platform_deployment_id = deploy_result.platform_deployment_id
    if deploy_result.url:
        deployment.url = deploy_result.url
    db.add(DeploymentEvent(
        deployment_id=deployment.id,
        platform_event_id=deploy_result.platform_deployment_id,
        status=deploy_result.status,
    ))
    await db.commit()
    await db.refresh(deployment)
    return deployment


@router.post("/import/{platform}", response_model=list[DeploymentResponse])
async def import_from_platform(
    platform: Platform, db: AsyncSession = Depends(get_db)
):
    """Fetch all projects from the platform and add any not already tracked locally."""
    token = await _get_decrypted_token(platform, db)
    client = _build_client(platform, token)

    try:
        remote = await client.list_deployments()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc

    # Load existing project names for this platform to avoid duplicates.
    existing_result = await db.execute(
        select(Deployment.project_name).where(Deployment.platform == platform)
    )
    existing_names = {row[0] for row in existing_result.all()}

    added = []
    for item in remote:
        if item.project_name in existing_names:
            continue
        deployment = Deployment(
            platform=platform,
            project_name=item.project_name,
            platform_deployment_id=item.platform_deployment_id,
            url=item.url,
            status=item.status,
            repo_url=item.repo_url,
            deployment_type=item.deployment_type or _PLATFORM_TYPE_DEFAULTS.get(platform),
        )
        db.add(deployment)
        existing_names.add(item.project_name)
        added.append(deployment)

    if added:
        await db.commit()
        for dep in added:
            await db.refresh(dep)

    return added


@router.post("/{deployment_id}/sync", response_model=DeploymentResponse)
async def sync_deployment(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """Refresh the deployment status by querying the platform API."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if not deployment.platform_deployment_id or deployment.platform_deployment_id in (
        "pending",
        "unknown",
    ):
        return deployment

    token = await _get_decrypted_token(deployment.platform, db)
    client = _build_client(deployment.platform, token)

    old_status = deployment.status
    try:
        deployment.status = await client.get_deployment_status(
            deployment.platform_deployment_id
        )
        actual_url = await client.get_project_url(deployment.project_name)
        if actual_url:
            deployment.url = actual_url
        fresh_repo = await client.get_project_repo_url(deployment.project_name)
        if fresh_repo:
            deployment.repo_url = fresh_repo
        elif fresh_repo == "" and deployment.repo_url:
            deployment.repo_url = None
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc

    if deployment.status != old_status:
        db.add(DeploymentEvent(
            deployment_id=deployment.id,
            platform_event_id=deployment.platform_deployment_id,
            status=deployment.status,
        ))
    await db.commit()
    await db.refresh(deployment)
    return deployment


@router.get("/{deployment_id}/logs")
async def get_deployment_logs(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch build log lines from the platform for a deployment."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if not deployment.platform_deployment_id or deployment.platform_deployment_id in (
        "pending",
        "unknown",
    ):
        return {"lines": []}

    token = await _get_decrypted_token(deployment.platform, db)
    client = _build_client(deployment.platform, token)

    try:
        lines = await client.get_deployment_logs(
            deployment.platform_deployment_id, deployment.project_name
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc

    return {"lines": lines}


@router.get("/{deployment_id}/history", response_model=list[DeploymentEventResponse])
async def get_deployment_history(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """Return the event history for a deployment, most recent first."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Deployment not found")

    events_result = await db.execute(
        select(DeploymentEvent)
        .where(DeploymentEvent.deployment_id == deployment_id)
        .order_by(DeploymentEvent.triggered_at.desc())
    )
    return events_result.scalars().all()


@router.get("/", response_model=list[DeploymentResponse])
async def list_deployments(
    platform: Optional[Platform] = None, db: AsyncSession = Depends(get_db)
):
    """List all deployments, optionally filtered by platform."""
    stmt = select(Deployment)
    if platform:
        stmt = stmt.where(Deployment.platform == platform)
    stmt = stmt.order_by(Deployment.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """Retrieve a single deployment by its local ID."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


@router.patch("/{deployment_id}/project", response_model=DeploymentResponse)
async def assign_project(
    deployment_id: int, data: AssignProjectRequest, db: AsyncSession = Depends(get_db)
):
    """Assign or unassign a deployment to an internal project."""
    result = await db.execute(select(Deployment).where(Deployment.id == deployment_id))
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if data.project_id is not None:
        proj = await db.execute(select(Project).where(Project.id == data.project_id))
        if not proj.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Project not found")

    deployment.project_id = data.project_id
    await db.commit()
    await db.refresh(deployment)
    return deployment


@router.get("/{deployment_id}/build")
async def get_build_settings(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch the current build command and response headers for a Render static site."""
    result = await db.execute(select(Deployment).where(Deployment.id == deployment_id))
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if deployment.platform != Platform.RENDER:
        raise HTTPException(
            status_code=400,
            detail="Build settings only available for Render deployments",
        )
    token = await _get_decrypted_token(deployment.platform, db)
    client = _build_client(deployment.platform, token)
    try:
        return await client.get_build_config(
            deployment.platform_deployment_id, deployment.project_name
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.patch("/{deployment_id}/build")
async def update_build_settings(
    deployment_id: int,
    data: BuildSettingsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update build command and CORS headers on a Render static site via the Render API.

    Render ignores render.yaml for API-created services, so these settings must
    be applied explicitly.  Returns 400 for non-Render deployments.
    """
    result = await db.execute(select(Deployment).where(Deployment.id == deployment_id))
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if deployment.platform != Platform.RENDER:
        raise HTTPException(
            status_code=400,
            detail="Build settings can only be configured for Render deployments",
        )
    token = await _get_decrypted_token(deployment.platform, db)
    client = _build_client(deployment.platform, token)
    try:
        await client.update_build_command(
            deployment.platform_deployment_id,
            deployment.project_name,
            build_command=data.build_command,
            apply_cors=data.apply_cors,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"message": "Build settings applied — redeploy to activate"}


@router.patch("/{deployment_id}/type", response_model=DeploymentResponse)
async def set_deployment_type(
    deployment_id: int, data: DeploymentTypeUpdate, db: AsyncSession = Depends(get_db)
):
    """Set or clear the deployment type (static / backend)."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    deployment.deployment_type = data.deployment_type
    await db.commit()
    await db.refresh(deployment)
    return deployment


@router.patch("/{deployment_id}/notes", response_model=DeploymentResponse)
async def set_deployment_notes(
    deployment_id: int, data: DeploymentNotesUpdate, db: AsyncSession = Depends(get_db)
):
    """Update the personal notes for a deployment."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    deployment.notes = data.notes
    await db.commit()
    await db.refresh(deployment)
    return deployment


@router.get("/{deployment_id}/ping")
async def ping_deployment(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """HTTP-ping the deployment URL and return uptime status and response time."""
    result = await db.execute(select(Deployment).where(Deployment.id == deployment_id))
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if not deployment.url:
        return {"up": None, "status_code": None, "response_ms": None, "reason": "no_url"}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
            t0 = time.monotonic()
            resp = await client.get(deployment.url)
            ms = int((time.monotonic() - t0) * 1000)
        up = resp.status_code < 500
        return {"up": up, "status_code": resp.status_code, "response_ms": ms, "reason": None}
    except Exception:  # pylint: disable=broad-exception-caught
        return {"up": False, "status_code": None, "response_ms": None, "reason": "unreachable"}


@router.delete("/{deployment_id}/untrack")
async def untrack_deployment(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a deployment from local tracking without deleting it on the platform."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    name = deployment.project_name
    await db.delete(deployment)
    await db.commit()
    return {"message": f"Removed {name} from tracking (platform project untouched)"}


@router.delete("/{deployment_id}")
async def delete_deployment(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """Delete the project on the platform then remove it from the local database."""
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Attempt to delete on the platform; log and continue on failure so the
    # local record can always be cleaned up.
    if deployment.platform_deployment_id not in ("pending", "unknown", ""):
        try:
            token = await _get_decrypted_token(deployment.platform, db)
            client = _build_client(deployment.platform, token)
            await client.delete_deployment(
                deployment.platform_deployment_id, deployment.project_name
            )
        except HTTPException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Platform delete failed for %s/%s: %s",
                deployment.platform.value,
                deployment.project_name,
                exc,
            )

    await db.delete(deployment)
    await db.commit()
    return {"message": f"Deleted {deployment.project_name} from {deployment.platform.value}"}
