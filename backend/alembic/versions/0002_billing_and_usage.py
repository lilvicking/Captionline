"""Stripe subscription mirroring and transactional usage accounting.

Revision ID: 0002_billing_and_usage
Revises: 0001_initial_accounts
Create Date: 2026-09-26

Adds:
  * users.subscription_price_id  - the Stripe Price ID behind the current plan
  * usage_reservations           - two-phase allowance holds (reserve/finalize/release)
  * stripe_events                - processed event ids for idempotent webhooks

0001 is already deployed, so this is a new revision rather than an edit.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_billing_and_usage"
down_revision: Union[str, None] = "0001_initial_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("subscription_price_id", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_users_subscription_price_id", "users", ["subscription_price_id"], unique=False
    )

    op.create_table(
        "usage_reservations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reserved_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_usage_reservations_user_status",
        "usage_reservations",
        ["user_id", "status"],
        unique=False,
    )

    op.create_table(
        "stripe_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stripe_events_event_id"), "stripe_events", ["event_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_stripe_events_event_id"), table_name="stripe_events")
    op.drop_table("stripe_events")

    op.drop_index("ix_usage_reservations_user_status", table_name="usage_reservations")
    op.drop_table("usage_reservations")

    op.drop_index("ix_users_subscription_price_id", table_name="users")
    op.drop_column("users", "subscription_price_id")
