"""API routes for managing internal projects."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Deployment, Project
from schemas import ProjectCreate, ProjectResponse

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("/", response_model=ProjectResponse)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    """Create a new internal project."""
    project = Project(name=data.name)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all internal projects ordered by creation date."""
    result = await db.execute(select(Project).order_by(Project.created_at))
    return result.scalars().all()


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a project and unassign its deployments (deployments are kept)."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    dep_result = await db.execute(
        select(Deployment).where(Deployment.project_id == project_id)
    )
    for dep in dep_result.scalars().all():
        dep.project_id = None

    name = project.name
    await db.delete(project)
    await db.commit()
    return {"message": f"Deleted project '{name}'"}
