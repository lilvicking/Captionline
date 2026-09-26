"""Initial account schema for Captionline Phase 3A.

Revision ID: 0001_initial_accounts
Revises:
Create Date: 2026-09-26

Creates the `users` and `sessions` tables.

Column types are portable (no JSONB/ARRAY/UUID server defaults) so this revision
runs on PostgreSQL in production and on SQLite for local verification.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_accounts"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("subscription_status", sa.String(length=32), nullable=False),
        sa.Column("subscription_provider", sa.String(length=32), nullable=True),
        sa.Column("subscription_external_id", sa.String(length=255), nullable=True),
        sa.Column("subscription_current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("monthly_processing_allowance_seconds", sa.Integer(), nullable=False),
        sa.Column("processing_used_seconds", sa.Integer(), nullable=False),
        sa.Column("usage_period_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usage_period_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("preview_limit_seconds", sa.Integer(), nullable=True),
        sa.Column("has_full_preview", sa.Boolean(), nullable=False),
        sa.Column("can_export", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(
        "ix_users_subscription_external_id", "users", ["subscription_external_id"]
    )
    op.create_index("ix_users_plan_status", "users", ["plan", "subscription_status"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )

    op.create_index(op.f("ix_sessions_token_hash"), "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index(op.f("ix_sessions_token_hash"), table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("ix_users_plan_status", table_name="users")
    op.drop_index("ix_users_subscription_external_id", table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
