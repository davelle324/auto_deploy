"""API routes for managing environment variables on platform deployments."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Deployment, PlatformToken
from routers.deployments import _build_client
from security import decrypt_token

router = APIRouter(prefix="/api/deployments", tags=["env-vars"])


class EnvVarItem(BaseModel):
    """A single environment variable key/value pair."""

    key: str
    value: str


class EnvVarSetRequest(BaseModel):
    """Request body for upserting environment variables."""

    env_vars: list[EnvVarItem]


async def _get_deployment_and_client(deployment_id: int, db: AsyncSession):
    """Shared helper: fetch deployment + build authenticated platform client."""
    result = await db.execute(select(Deployment).where(Deployment.id == deployment_id))
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    token_row = await db.execute(
        select(PlatformToken).where(PlatformToken.platform == deployment.platform)
    )
    token_record = token_row.scalar_one_or_none()
    if not token_record:
        raise HTTPException(
            status_code=400,
            detail=f"No API token configured for {deployment.platform.value}",
        )
    token = decrypt_token(token_record.encrypted_token)
    client = _build_client(deployment.platform, token)
    return deployment, client


@router.get("/{deployment_id}/env")
async def list_env_vars(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """List environment variables for a deployment."""
    deployment, client = await _get_deployment_and_client(deployment_id, db)
    try:
        env_vars = await client.list_env_vars(
            deployment.platform_deployment_id or "", deployment.project_name
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc
    return {"env_vars": env_vars}


@router.put("/{deployment_id}/env")
async def set_env_vars(
    deployment_id: int, data: EnvVarSetRequest, db: AsyncSession = Depends(get_db)
):
    """Upsert one or more environment variables on a deployment."""
    deployment, client = await _get_deployment_and_client(deployment_id, db)
    try:
        await client.set_env_vars(
            deployment.platform_deployment_id or "",
            deployment.project_name,
            [{"key": ev.key, "value": ev.value} for ev in data.env_vars],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc
    return {"message": "Environment variables updated"}


@router.delete("/{deployment_id}/env/{key}")
async def delete_env_var(
    deployment_id: int, key: str, db: AsyncSession = Depends(get_db)
):
    """Delete a single environment variable from a deployment by key."""
    deployment, client = await _get_deployment_and_client(deployment_id, db)
    try:
        await client.delete_env_var(
            deployment.platform_deployment_id or "", deployment.project_name, key
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc
    return {"message": f"Deleted env var {key!r}"}
