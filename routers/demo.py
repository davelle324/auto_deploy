"""Demo API routes — return realistic fake data without touching real APIs or the database."""

import copy
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/demo/api", tags=["demo"])

# ── Seed data (never mutated) ─────────────────────────────────────────────────

_D1 = "2026-08-19T10:30:00Z"
_D2 = "2026-08-18T14:20:00Z"
_D3 = "2026-08-17T08:45:00Z"

_SEED_DEPLOYMENTS = [
    {
        "id": 1,
        "platform": "vercel",
        "project_name": "my-portfolio",
        "platform_deployment_id": "dpl_abc123xyz789",
        "url": "https://my-portfolio.vercel.app",
        "status": "ready",
        "repo_url": "https://github.com/demo-user/my-portfolio",
        "project_id": 1,
        "deployment_type": "static",
        "notes": None,
        "last_deployed_at": _D1,
        "created_at": "2026-08-01T09:00:00Z",
    },
    {
        "id": 2,
        "platform": "netlify",
        "project_name": "blog-site",
        "platform_deployment_id": "601f191e-abc1-2345-6789-abcdef012345",
        "url": "https://blog-site.netlify.app",
        "status": "ready",
        "repo_url": "https://github.com/demo-user/blog-site",
        "project_id": 1,
        "deployment_type": "static",
        "notes": "Personal blog — Hugo static site",
        "last_deployed_at": _D2,
        "created_at": "2026-07-15T11:00:00Z",
    },
    {
        "id": 3,
        "platform": "render",
        "project_name": "api-backend",
        "platform_deployment_id": "srv-ctu0fj5umphs73eevqpg",
        "url": "https://api-backend.onrender.com",
        "status": "live",
        "repo_url": "https://github.com/demo-user/api-backend",
        "project_id": None,
        "deployment_type": "backend",
        "notes": None,
        "last_deployed_at": _D3,
        "created_at": "2026-07-20T13:30:00Z",
    },
]

_SEED_PROJECTS = [
    {"id": 1, "name": "Personal Website", "created_at": "2026-07-01T08:00:00Z"},
    {"id": 2, "name": "Side Projects", "created_at": "2026-07-10T12:00:00Z"},
]

_SEED_ENV_VARS: dict[int, list[dict]] = {
    1: [{"key": "NEXT_PUBLIC_API_URL", "value": "https://api.example.com"}],
    2: [{"key": "HUGO_VERSION", "value": "0.118.2"}],
    3: [{"key": "PORT", "value": "8080"}, {"key": "NODE_ENV", "value": "production"}],
}

_SEED_DOMAINS: dict[int, list[str]] = {1: [], 2: [], 3: []}

# ── Mutable working state (reset by _reset_demo_state in tests) ───────────────

_DEPLOYMENTS: list[dict] = copy.deepcopy(_SEED_DEPLOYMENTS)
_PROJECTS: list[dict] = copy.deepcopy(_SEED_PROJECTS)
_ENV_VARS: dict[int, list[dict]] = copy.deepcopy(_SEED_ENV_VARS)
_DOMAINS: dict[int, list[str]] = copy.deepcopy(_SEED_DOMAINS)


def _reset_demo_state() -> None:
    """Restore all mutable state to seed values. Called by tests before each test."""
    _DEPLOYMENTS[:] = copy.deepcopy(_SEED_DEPLOYMENTS)
    _PROJECTS[:] = copy.deepcopy(_SEED_PROJECTS)
    _ENV_VARS.clear()
    _ENV_VARS.update(copy.deepcopy(_SEED_ENV_VARS))
    _DOMAINS.clear()
    _DOMAINS.update(copy.deepcopy(_SEED_DOMAINS))


# ── Request bodies ────────────────────────────────────────────────────────────

class _DeployRequest(BaseModel):
    """Body for demo deployment creation."""

    platform: str = "vercel"
    project_name: str = "demo-project"
    repo_url: Optional[str] = None
    deployment_type: Optional[str] = None


class _ProjectRequest(BaseModel):
    """Body for demo project creation."""

    name: str = "Demo Project"


class _TokenRequest(BaseModel):
    """Body for demo token upsert."""

    platform: str
    token: str


class _NotesRequest(BaseModel):
    """Body for updating deployment notes."""

    notes: Optional[str] = None


class _TypeRequest(BaseModel):
    """Body for updating deployment type."""

    deployment_type: Optional[str] = None


class _AssignProjectRequest(BaseModel):
    """Body for assigning a deployment to a project."""

    project_id: Optional[int] = None


class _ConnectRepoRequest(BaseModel):
    """Body for connecting a GitHub repo."""

    repo_url: str


class _AddDomainRequest(BaseModel):
    """Body for adding a custom domain."""

    domain: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_dep(deployment_id: int) -> dict:
    """Return the live deployment dict or raise 404."""
    dep = next((d for d in _DEPLOYMENTS if d["id"] == deployment_id), None)
    if not dep:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return dep


# ── Reset ─────────────────────────────────────────────────────────────────────

@router.post("/reset")
async def demo_reset() -> dict:
    """Restore all demo state to seed values."""
    _reset_demo_state()
    return {"message": "Demo reset to initial state"}


# ── Tokens ────────────────────────────────────────────────────────────────────

@router.get("/tokens/")
async def demo_list_tokens() -> list[dict]:
    """Return all three platforms as configured."""
    return [
        {"platform": p, "configured": True, "created_at": "2026-07-01T08:00:00Z"}
        for p in ("vercel", "netlify", "render")
    ]


@router.post("/tokens/")
async def demo_upsert_token(data: _TokenRequest) -> dict:
    """Fake-save a token and return success."""
    return {"platform": data.platform, "configured": True, "created_at": "2026-08-19T10:00:00Z"}


@router.delete("/tokens/{platform}")
async def demo_delete_token(platform: str) -> dict:
    """Fake-delete a token and return success."""
    return {"message": f"Token for {platform} deleted"}


# ── Projects ──────────────────────────────────────────────────────────────────

@router.get("/projects/")
async def demo_list_projects() -> list[dict]:
    """Return the demo project list."""
    return list(_PROJECTS)


@router.post("/projects/")
async def demo_create_project(data: _ProjectRequest) -> dict:
    """Add a project to demo state and return it."""
    next_id = max((p["id"] for p in _PROJECTS), default=0) + 1
    project = {"id": next_id, "name": data.name, "created_at": "2026-08-19T10:00:00Z"}
    _PROJECTS.append(project)
    return dict(project)


@router.delete("/projects/{project_id}")
async def demo_delete_project(project_id: int) -> dict:
    """Remove a project from demo state and return success."""
    project = next((p for p in _PROJECTS if p["id"] == project_id), None)
    if project:
        _PROJECTS.remove(project)
    return {"message": f"Deleted project (id={project_id})"}


# ── Deployments — list / create / import (defined before parameterised routes) ─

@router.get("/deployments/")
async def demo_list_deployments(platform: Optional[str] = None) -> list[dict]:
    """Return demo deployments, optionally filtered by platform."""
    if platform:
        return [dict(d) for d in _DEPLOYMENTS if d["platform"] == platform]
    return [dict(d) for d in _DEPLOYMENTS]


@router.post("/deployments/")
async def demo_create_deployment(data: _DeployRequest) -> dict:
    """Add a new deployment to demo state and return it."""
    next_id = max((d["id"] for d in _DEPLOYMENTS), default=0) + 1
    urls = {
        "vercel": f"https://{data.project_name}.vercel.app",
        "netlify": f"https://{data.project_name}.netlify.app",
        "render": f"https://{data.project_name}.onrender.com",
    }
    new_dep = {
        "id": next_id,
        "platform": data.platform,
        "project_name": data.project_name,
        "platform_deployment_id": f"dpl_demo{next_id:05d}",
        "url": urls.get(data.platform, f"https://{data.project_name}.vercel.app"),
        "status": "deploying",
        "repo_url": data.repo_url,
        "project_id": None,
        "deployment_type": data.deployment_type or "static",
        "notes": None,
        "last_deployed_at": "2026-08-19T10:30:00Z",
        "created_at": "2026-08-19T10:30:00Z",
    }
    _DEPLOYMENTS.append(new_dep)
    _ENV_VARS[next_id] = []
    _DOMAINS[next_id] = []
    return dict(new_dep)


@router.post("/deployments/import/{platform}")
async def demo_import_from_platform(platform: str) -> list:  # pylint: disable=unused-argument
    """Return an empty list — no new projects to import in demo mode."""
    return []


# ── Deployments — parameterised sub-routes ────────────────────────────────────

@router.post("/deployments/{deployment_id}/redeploy")
async def demo_redeploy(deployment_id: int) -> dict:
    """Update deployment status to deploying in demo state and return it."""
    dep = _get_dep(deployment_id)
    dep["status"] = "deploying"
    dep["last_deployed_at"] = "2026-08-19T10:30:00Z"
    return dict(dep)


@router.post("/deployments/{deployment_id}/sync")
async def demo_sync(deployment_id: int) -> dict:
    """Update deployment status to ready/live in demo state and return it."""
    dep = _get_dep(deployment_id)
    dep["status"] = "ready" if dep["platform"] in ("vercel", "netlify") else "live"
    return dict(dep)


@router.get("/deployments/{deployment_id}/logs")
async def demo_logs(deployment_id: int) -> dict:
    """Return fake build log lines."""
    _get_dep(deployment_id)
    return {
        "lines": [
            "[10:30:01] Deploying to platform...",
            "[10:30:02] Installing dependencies",
            "[10:30:04] npm install: 247 packages installed",
            "[10:30:08] Running build: npm run build",
            "[10:30:12] Build completed in 4.2s",
            "[10:30:13] Uploading artifacts",
            "[10:30:15] Deployment complete ✓",
        ]
    }


@router.get("/deployments/{deployment_id}/history")
async def demo_history(deployment_id: int) -> list[dict]:
    """Return fake deploy event history."""
    _get_dep(deployment_id)
    return [
        {
            "id": 3,
            "deployment_id": deployment_id,
            "platform_event_id": "dpl_abc123xyz789",
            "status": "ready",
            "triggered_at": "2026-08-19T10:30:15Z",
        },
        {
            "id": 2,
            "deployment_id": deployment_id,
            "platform_event_id": "dpl_abc123xyz456",
            "status": "ready",
            "triggered_at": "2026-08-18T09:15:00Z",
        },
        {
            "id": 1,
            "deployment_id": deployment_id,
            "platform_event_id": "dpl_abc123xyz123",
            "status": "ready",
            "triggered_at": "2026-08-01T09:05:00Z",
        },
    ]


@router.patch("/deployments/{deployment_id}/repo")
async def demo_connect_repo(deployment_id: int, data: _ConnectRepoRequest) -> dict:
    """Update repo_url in demo state and return the deployment with deploying status."""
    dep = _get_dep(deployment_id)
    dep["status"] = "deploying"
    dep["repo_url"] = data.repo_url
    return dict(dep)


@router.patch("/deployments/{deployment_id}/project")
async def demo_assign_project(deployment_id: int, data: _AssignProjectRequest) -> dict:
    """Update project_id in demo state and return the deployment."""
    dep = _get_dep(deployment_id)
    dep["project_id"] = data.project_id
    return dict(dep)


@router.get("/deployments/{deployment_id}/build")
async def demo_build_settings(deployment_id: int) -> dict:
    """Return fake Render build config."""
    _get_dep(deployment_id)
    return {
        "build_command": "bash build.sh",
        "headers": [{"name": "Access-Control-Allow-Origin", "value": "*"}],
    }


@router.patch("/deployments/{deployment_id}/build")
async def demo_update_build_settings(deployment_id: int) -> dict:
    """Fake-apply build settings and return a success message."""
    _get_dep(deployment_id)
    return {"message": "Build settings applied — redeploy to activate"}


@router.patch("/deployments/{deployment_id}/type")
async def demo_set_type(deployment_id: int, data: _TypeRequest) -> dict:
    """Update deployment_type in demo state and return the deployment."""
    dep = _get_dep(deployment_id)
    dep["deployment_type"] = data.deployment_type
    return dict(dep)


@router.patch("/deployments/{deployment_id}/notes")
async def demo_set_notes(deployment_id: int, data: _NotesRequest) -> dict:
    """Update notes in demo state and return the deployment."""
    dep = _get_dep(deployment_id)
    dep["notes"] = data.notes
    return dict(dep)


@router.get("/deployments/{deployment_id}/ping")
async def demo_ping(deployment_id: int) -> dict:
    """Return a fake ping result indicating the site is up."""
    dep = _get_dep(deployment_id)
    if not dep.get("url"):  # pragma: no cover
        return {"up": None, "status_code": None, "response_ms": None, "reason": "no_url"}
    return {"up": True, "status_code": 200, "response_ms": 42, "reason": None}


@router.delete("/deployments/{deployment_id}/untrack")
async def demo_untrack(deployment_id: int) -> dict:
    """Remove from demo state (no platform call) and return a success message."""
    dep = _get_dep(deployment_id)
    name = dep["project_name"]
    _DEPLOYMENTS.remove(dep)
    _ENV_VARS.pop(deployment_id, None)
    _DOMAINS.pop(deployment_id, None)
    return {"message": f"Removed {name} from tracking (platform project untouched)"}


@router.delete("/deployments/{deployment_id}")
async def demo_delete_deployment(deployment_id: int) -> dict:
    """Remove from demo state and return a success message."""
    dep = _get_dep(deployment_id)
    name, platform = dep["project_name"], dep["platform"]
    _DEPLOYMENTS.remove(dep)
    _ENV_VARS.pop(deployment_id, None)
    _DOMAINS.pop(deployment_id, None)
    return {"message": f"Deleted {name} from {platform}"}


# ── Env vars ──────────────────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/env")
async def demo_list_env(deployment_id: int) -> dict:
    """Return fake environment variables for a deployment."""
    _get_dep(deployment_id)
    return {"env_vars": _ENV_VARS.get(deployment_id, [])}


@router.put("/deployments/{deployment_id}/env")
async def demo_set_env(deployment_id: int) -> dict:
    """Fake-set environment variables and return a success message."""
    _get_dep(deployment_id)
    return {"message": "Environment variables updated"}


@router.delete("/deployments/{deployment_id}/env/{key}")
async def demo_delete_env(deployment_id: int, key: str) -> dict:
    """Fake-delete an environment variable and return a success message."""
    _get_dep(deployment_id)
    return {"message": f"Deleted env var {key!r}"}


# ── Domains ───────────────────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/domains")
async def demo_list_domains(deployment_id: int) -> dict:
    """Return the platform URL and fake custom domains."""
    dep = _get_dep(deployment_id)
    return {"domains": _DOMAINS.get(deployment_id, []), "platform_url": dep.get("url", "")}


@router.post("/deployments/{deployment_id}/domains")
async def demo_add_domain(deployment_id: int, data: _AddDomainRequest) -> dict:
    """Fake-add a domain and return a success message."""
    _get_dep(deployment_id)
    return {"message": f"Domain {data.domain!r} added"}


@router.delete("/deployments/{deployment_id}/domains/{domain}")
async def demo_remove_domain(deployment_id: int, domain: str) -> dict:
    """Fake-remove a domain and return a success message."""
    _get_dep(deployment_id)
    return {"message": f"Domain {domain!r} removed"}
