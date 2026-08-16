"""Inbound webhook handlers for Vercel, Netlify, and Render build events.

Each platform sends a POST to /api/webhook/{platform} when a deployment status
changes.  The handler matches the event to a local Deployment record by
platform_deployment_id and updates the status field automatically.

Signature verification (HMAC-SHA256) is performed when a WEBHOOK_SECRET is
set in the environment.  Platforms that omit the standard header are accepted
without verification so the endpoint works out-of-box without configuration,
but production deployments should always set a secret.
"""

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Deployment, DeploymentEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhook", tags=["webhooks"])

_WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


def _verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    """Return True when the HMAC-SHA256 signature matches the request body."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # Signatures may be prefixed with 'sha256=' (GitHub/Netlify style)
    sig = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, sig)


async def _handle_event(
    platform_deployment_id: str,
    status: str,
    platform_event_id: str,
    db: AsyncSession,
) -> None:
    """Locate the matching Deployment and update its status, recording an event."""
    result = await db.execute(
        select(Deployment).where(
            Deployment.platform_deployment_id == platform_deployment_id
        )
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        logger.debug("Webhook: no local deployment for id=%s", platform_deployment_id)
        return
    deployment.status = status
    db.add(DeploymentEvent(
        deployment_id=deployment.id,
        platform_event_id=platform_event_id,
        status=status,
    ))
    await db.commit()


@router.post("/vercel")
async def vercel_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive Vercel deployment status events."""
    body = await request.body()

    if _WEBHOOK_SECRET:
        sig = request.headers.get("x-vercel-signature", "")
        if not sig or not _verify_hmac(body, sig, _WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    deployment_data = payload.get("deployment") or payload.get("data", {}).get("deployment", {})
    deployment_id = deployment_data.get("id", "")
    ready_state = (payload.get("type", "") or "").lower()
    status_map = {
        "deployment.ready": "ready",
        "deployment.error": "error",
        "deployment.canceled": "canceled",
        "deployment.created": "initializing",
    }
    status = status_map.get(ready_state, payload.get("type", "unknown").lower())

    if deployment_id:
        await _handle_event(deployment_id, status, deployment_id, db)
    return {"received": True}


@router.post("/netlify")
async def netlify_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive Netlify deploy notification events."""
    body = await request.body()

    if _WEBHOOK_SECRET:
        sig = request.headers.get("x-webhook-signature", "")
        if not sig or not _verify_hmac(body, sig, _WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    site_id = payload.get("site_id", "")
    event_type = payload.get("event", "")
    status_map = {
        "deploy_building": "building",
        "deploy_created": "ready",
        "deploy_failed": "error",
        "deploy_locked": "ready",
    }
    status = status_map.get(event_type, event_type or "unknown")
    deploy_id = payload.get("id", "")

    if site_id:
        await _handle_event(site_id, status, deploy_id, db)
    return {"received": True}


@router.post("/render")
async def render_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive Render service event notifications."""
    body = await request.body()

    if _WEBHOOK_SECRET:
        sig = request.headers.get("x-render-signature", "")
        if not sig or not _verify_hmac(body, sig, _WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    service_id = (payload.get("service") or {}).get("id", "")
    deploy_id = (payload.get("deploy") or {}).get("id", "")
    deploy_status = (payload.get("deploy") or {}).get("status", "")
    status_map = {
        "live": "ready",
        "deactivated": "inactive",
        "build_failed": "error",
        "update_failed": "error",
    }
    status = status_map.get(deploy_status, deploy_status or "unknown")

    if service_id:
        await _handle_event(service_id, status, deploy_id, db)
    return {"received": True}
