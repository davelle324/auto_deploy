"""API routes for managing platform API tokens."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Platform, PlatformToken
from schemas import TokenCreate, TokenResponse
from security import encrypt_token

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


@router.post("/", response_model=TokenResponse)
async def upsert_token(data: TokenCreate, db: AsyncSession = Depends(get_db)):
    """Store or update the API token for a platform (encrypted at rest)."""
    result = await db.execute(
        select(PlatformToken).where(PlatformToken.platform == data.platform)
    )
    existing = result.scalar_one_or_none()
    encrypted = encrypt_token(data.token)

    if existing:
        existing.encrypted_token = encrypted
        await db.commit()
        await db.refresh(existing)
        return TokenResponse(
            platform=existing.platform, configured=True, created_at=existing.created_at
        )

    new_token = PlatformToken(platform=data.platform, encrypted_token=encrypted)
    db.add(new_token)
    await db.commit()
    await db.refresh(new_token)
    return TokenResponse(
        platform=new_token.platform, configured=True, created_at=new_token.created_at
    )


@router.get("/", response_model=list[TokenResponse])
async def list_tokens(db: AsyncSession = Depends(get_db)):
    """Return configured/unconfigured status for every platform."""
    result = await db.execute(select(PlatformToken))
    existing = {t.platform: t for t in result.scalars().all()}
    return [
        TokenResponse(
            platform=p,
            configured=p in existing,
            created_at=existing[p].created_at if p in existing else None,
        )
        for p in Platform
    ]


@router.delete("/{platform}")
async def delete_token(platform: Platform, db: AsyncSession = Depends(get_db)):
    """Remove the stored token for the given platform."""
    result = await db.execute(
        select(PlatformToken).where(PlatformToken.platform == platform)
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    await db.delete(token)
    await db.commit()
    return {"message": f"Token for {platform.value} deleted"}
