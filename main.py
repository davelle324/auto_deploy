"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from database import init_db
from routers import deployments, domains, env_vars, projects, tokens, webhooks


@asynccontextmanager
async def lifespan(_app: FastAPI):  # pragma: no cover
    """Initialize the database on startup."""
    await init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["Content-Type"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(tokens.router)
app.include_router(deployments.router)
app.include_router(projects.router)
app.include_router(env_vars.router)
app.include_router(domains.router)
app.include_router(webhooks.router)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the deployments dashboard."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/deploy", response_class=HTMLResponse)
async def deploy_page(request: Request):
    """Render the new deployment form."""
    return templates.TemplateResponse(request, "deploy.html")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render the platform token settings page."""
    return templates.TemplateResponse(request, "settings.html")
