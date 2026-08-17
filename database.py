"""Async SQLAlchemy engine, session factory, and database initialization."""

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


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
        if "deployment_type" not in cols:
            await conn.execute(text(
                "ALTER TABLE deployments ADD COLUMN deployment_type TEXT"
            ))
        if "notes" not in cols:
            await conn.execute(text(
                "ALTER TABLE deployments ADD COLUMN notes TEXT"
            ))
        if "last_deployed_at" not in cols:
            await conn.execute(text(
                "ALTER TABLE deployments ADD COLUMN last_deployed_at DATETIME"
            ))
