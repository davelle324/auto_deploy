"""API routes for managing custom domains on platform deployments."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Deployment, PlatformToken
from routers.deployments import _build_client
from security import decrypt_token

router = APIRouter(prefix="/api/deployments", tags=["domains"])


class AddDomainRequest(BaseModel):
    """Request body for adding a custom domain."""

    domain: str


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


@router.get("/{deployment_id}/domains")
async def list_domains(deployment_id: int, db: AsyncSession = Depends(get_db)):
    """List custom domains for a deployment."""
    deployment, client = await _get_deployment_and_client(deployment_id, db)
    try:
        domains = await client.list_domains(
            deployment.platform_deployment_id or "", deployment.project_name
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc
    return {"domains": domains}


@router.post("/{deployment_id}/domains")
async def add_domain(
    deployment_id: int, data: AddDomainRequest, db: AsyncSession = Depends(get_db)
):
    """Add a custom domain to a deployment."""
    deployment, client = await _get_deployment_and_client(deployment_id, db)
    try:
        await client.add_domain(
            deployment.platform_deployment_id or "", deployment.project_name, data.domain
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc
    return {"message": f"Domain {data.domain!r} added"}


@router.delete("/{deployment_id}/domains/{domain}")
async def remove_domain(
    deployment_id: int, domain: str, db: AsyncSession = Depends(get_db)
):
    """Remove a custom domain from a deployment."""
    deployment, client = await _get_deployment_and_client(deployment_id, db)
    try:
        await client.remove_domain(
            deployment.platform_deployment_id or "", deployment.project_name, domain
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc
    return {"message": f"Domain {domain!r} removed"}
