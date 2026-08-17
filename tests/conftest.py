"""Pytest configuration and shared fixtures for async FastAPI tests."""

# pylint: disable=wrong-import-position,wrong-import-order,redefined-outer-name

import os

# Must be set before any app module imports so config/database use these values.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-32x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ["APP_PASSWORD"] = ""  # always disable auth in tests

import database  # noqa: E402 — import after env vars
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402

_TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TEST_SESSION_FACTORY = async_sessionmaker(_TEST_ENGINE, expire_on_commit=False)

# Patch the database module so init_db() and get_db use the test engine.
database.engine = _TEST_ENGINE
database.session_factory = _TEST_SESSION_FACTORY


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create all tables before each test and drop them after."""
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db():
    """Yield a test database session."""
    async with _TEST_SESSION_FACTORY() as session:
        yield session


@pytest_asyncio.fixture
async def client(db):
    """Yield an async test client with the DB dependency overridden."""
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
