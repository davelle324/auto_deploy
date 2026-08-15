"""Async SQLAlchemy engine, session factory, and database initialization."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """Declarative base for all ORM models."""


async def get_db():  # pragma: no cover
    """Yield a database session for use as a FastAPI dependency."""
    async with session_factory() as session:
        yield session


async def init_db():  # pragma: no cover
    """Create all tables on startup, migrating existing schemas as needed."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add project_id to deployments if this DB pre-dates the projects feature.
        result = await conn.execute(text("PRAGMA table_info(deployments)"))
        cols = {row[1] for row in result.fetchall()}
        if "project_id" not in cols:
            await conn.execute(text(
                "ALTER TABLE deployments ADD COLUMN"
                " project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL"
            ))
