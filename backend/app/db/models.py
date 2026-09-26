"""Database models.

The schema is intentionally shaped so Stripe can become the authoritative source
of paid subscription state later without a redesign:

* `subscription_provider` / `subscription_external_id` / `subscription_status`
  / `subscription_current_period_end` are a local *mirror* of the billing
  provider's state. A future Stripe webhook writes them, and the backend then
  treats Stripe as authoritative rather than trusting the mirror.
* The entitlement columns (`preview_limit_seconds`, `has_full_preview`,
  `can_export`) and the usage columns (`monthly_processing_allowance_seconds`,
  `processing_used_seconds`, usage period bounds) are the read model the API
  serves, seeded from `app/plans.py`.

Column types are deliberately portable (no JSONB/ARRAY/UUID server defaults) so
the same Alembic revisions run on PostgreSQL in production and on SQLite for
local verification.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..plans import SUBSCRIPTION_NONE
from .base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- Identity ---
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- Plan ---
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="free")

    # --- Mirrored subscription state (authoritative source is Stripe later) ---
    subscription_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SUBSCRIPTION_NONE
    )
    subscription_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subscription_external_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    subscription_current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Usage ---
    monthly_processing_allowance_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    processing_used_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_period_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    usage_period_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- Entitlements (read model served to the frontend) ---
    # None means an unrestricted preview.
    preview_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_full_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_export: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_users_plan_status", "plan", "subscription_status"),)


class Session(Base):
    """An opaque bearer session.

    Only the SHA-256 hash of the token is stored, so a database leak does not
    expose usable credentials. Revoking a row invalidates the token immediately.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")

    __table_args__ = (UniqueConstraint("token_hash", name="uq_sessions_token_hash"),)
