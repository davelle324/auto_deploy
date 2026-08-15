"""ORM models for platform tokens and deployments."""

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Platform(str, enum.Enum):
    """Supported deployment platforms."""

    VERCEL = "vercel"
    NETLIFY = "netlify"
    RENDER = "render"


class PlatformToken(Base):  # pylint: disable=too-few-public-methods
    """Encrypted API token for a deployment platform."""

    __tablename__ = "platform_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform), unique=True, nullable=False)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Deployment(Base):  # pylint: disable=too-few-public-methods
    """Record of a deployment created via a platform API."""

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform), nullable=False)
    project_name: Mapped[str] = mapped_column(String(63), nullable=False)
    platform_deployment_id: Mapped[str] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    repo_url: Mapped[str] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
