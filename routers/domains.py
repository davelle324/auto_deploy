"""API routes for managing custom domains on platform deployments."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
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

    @field_validator("domain")
    @classmethod
    def strip_protocol(cls, v: str) -> str:
        """Accept full URLs or bare hostnames; always send just the hostname."""
        v = v.strip()
        v = v.removeprefix("https://").removeprefix("http://")
        v = v.strip("/")
        if not v:
            raise ValueError("domain cannot be empty")
        return v


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
    """List domains for a deployment.

    Returns the platform-assigned URL (read-only) plus any custom domains.
    """
    deployment, client = await _get_deployment_and_client(deployment_id, db)
    try:
        domains = await client.list_domains(
            deployment.platform_deployment_id or "", deployment.project_name
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}") from exc
    platform_url = deployment.url or ""
    # Deduplicate: the platform URL is shown separately as read-only, so remove it
    # from the editable list if the platform API also returns it.
    # Strip scheme for comparison since some platforms omit https:// in their domain list.
    def _bare(url: str) -> str:
        return url.removeprefix("https://").removeprefix("http://").rstrip("/")

    platform_bare = _bare(platform_url)
    filtered = [d for d in domains if d and _bare(d) != platform_bare]
    return {"domains": filtered, "platform_url": platform_url}


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
