"""Async SQLAlchemy engine, session factory, and database initialization."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """Declarative base for all ORM models."""


async def get_db():
    """Yield a database session for use as a FastAPI dependency."""
    async with session_factory() as session:
        yield session


async def init_db():
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
