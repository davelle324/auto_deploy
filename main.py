"""FastAPI application entry point."""

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import settings
from database import init_db
from routers import demo, deployments, domains, env_vars, projects, tokens, webhooks


@asynccontextmanager
async def lifespan(_app: FastAPI):  # pragma: no cover
    """Initialize the database on startup."""
    await init_db()
    yield


class AuthMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """Redirect unauthenticated requests to /login when APP_PASSWORD is set."""

    async def dispatch(self, request: Request, call_next):
        if not settings.app_password:
            return await call_next(request)
        path = request.url.path
        if path.startswith("/login") or path.startswith("/static") or path.startswith("/demo"):
            return await call_next(request)
        if not request.session.get("authenticated"):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return RedirectResponse("/demo")
        return await call_next(request)


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware, secret_key=settings.secret_key, https_only=False, max_age=3600
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["Content-Type"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(demo.router)
app.include_router(tokens.router)
app.include_router(deployments.router)
app.include_router(projects.router)
app.include_router(env_vars.router)
app.include_router(domains.router)
app.include_router(webhooks.router)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the login page; redirect home if already authenticated."""
    if not settings.app_password or request.session.get("authenticated"):
        return RedirectResponse("/")
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    """Check password and set session cookie."""
    if hmac.compare_digest(password, settings.app_password):
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": "Incorrect password"}, status_code=401
    )


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


@app.get("/logout")
async def logout(request: Request):
    """Clear the session and redirect to the demo."""
    request.session.clear()
    return RedirectResponse("/demo")


@app.get("/demo", response_class=HTMLResponse)
async def demo_dashboard(request: Request):
    """Render the demo deployments dashboard with fake data."""
    return templates.TemplateResponse(request, "index.html", {"demo": True})


@app.get("/demo/deploy", response_class=HTMLResponse)
async def demo_deploy_page(request: Request):
    """Render the demo new deployment form."""
    return templates.TemplateResponse(request, "deploy.html", {"demo": True})


@app.get("/demo/settings", response_class=HTMLResponse)
async def demo_settings_page(request: Request):
    """Render the demo platform token settings page."""
    return templates.TemplateResponse(request, "settings.html", {"demo": True})
