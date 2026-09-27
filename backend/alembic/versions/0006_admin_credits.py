"""Administrative support console and auditable processing credit.

Revision ID: 0006_admin_credits
Revises: 0005_rate_limit_buckets
Create Date: 2026-09-27

Three things:

1. Adds `users.is_admin` and `users.bonus_processing_seconds`.
2. Adds the `admin_audit_log` table.
3. **Re-syncs every account's stored entitlement columns from the plan
   catalogue.**

Point 3 is a product fix, not an optimisation. The entitlement columns
(`has_full_preview`, `can_export`, `monthly_processing_allowance_seconds`) are a
read model copied onto the account row when it registers. When the Free plan was
corrected to carry the same capabilities as every paid plan, only *newly created*
accounts picked that up: every account created beforehand kept the old stored
values, so those customers saw a finished-video export paywall for a capability
their plan now includes. The API tests could not catch this because they always
registered a fresh account.

Re-syncing from the catalogue is the same operation registration performs, so it
is authoritative and idempotent. It is deliberately scoped with a `WHERE` guard so
rows that are already correct are left untouched, and it touches no usage,
subscription, or identity data.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_admin_credits"
down_revision: Union[str, None] = "0005_rate_limit_buckets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Mirrors `app/plans.py`. Kept literal here because a migration must not depend
#: on application code that may change shape long after it has run.
PLAN_ENTITLEMENTS: dict[str, tuple[int, bool, bool]] = {
    # plan id -> (monthly allowance seconds, has_full_preview, can_export)
    "free": (600, True, True),
    "creator_monthly": (30_000, True, True),
    "pro_monthly": (90_000, True, True),
    "creator_annual": (30_000, True, True),
}

#: Used for an account whose plan is not in the catalogue, so an unknown value
#: can never be left holding a stale capability.
FALLBACK_ENTITLEMENT = (600, True, True)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column(
            "bonus_processing_seconds", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_index("ix_users_is_admin", "users", ["is_admin"], unique=False)

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("amount_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=280), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_log_admin_user_id", "admin_audit_log", ["admin_user_id"])
    op.create_index("ix_admin_audit_log_target_user_id", "admin_audit_log", ["target_user_id"])
    op.create_index(
        "ix_admin_audit_target_created", "admin_audit_log", ["target_user_id", "created_at"]
    )

    _resync_entitlements()


def _resync_entitlements() -> None:
    """Copy catalogue entitlements onto accounts that disagree.

    Guarded per plan so only the rows that actually differ are rewritten, which
    keeps the migration cheap and makes the effect easy to reason about.

    Uses SQLAlchemy Core rather than raw SQL so the ``IN`` list is bound the way
    each dialect expects; a literal ``NOT IN :param`` is not valid on SQLite.
    """
    connection = op.get_bind()

    users = sa.table(
        "users",
        sa.column("plan", sa.String),
        sa.column("monthly_processing_allowance_seconds", sa.Integer),
        sa.column("has_full_preview", sa.Boolean),
        sa.column("can_export", sa.Boolean),
        sa.column("preview_limit_seconds", sa.Integer),
    )

    def _stale(allowance: int, full: bool, export_ok: bool):
        return sa.or_(
            users.c.monthly_processing_allowance_seconds != allowance,
            users.c.has_full_preview != full,
            users.c.can_export != export_ok,
            users.c.preview_limit_seconds.is_not(None),
        )

    for plan_id, (allowance, full_preview, can_export) in PLAN_ENTITLEMENTS.items():
        connection.execute(
            sa.update(users)
            .where(users.c.plan == plan_id, _stale(allowance, full_preview, can_export))
            .values(
                monthly_processing_allowance_seconds=allowance,
                has_full_preview=full_preview,
                can_export=can_export,
                preview_limit_seconds=None,
            )
        )

    # An account on a plan we do not recognise falls back to the same capabilities
    # every current plan has, rather than keeping a stale value.
    known = list(PLAN_ENTITLEMENTS)
    allowance, full_preview, can_export = FALLBACK_ENTITLEMENT

    connection.execute(
        sa.update(users)
        .where(
            ~users.c.plan.in_(known),
            _stale(allowance, full_preview, can_export),
        )
        .values(
            monthly_processing_allowance_seconds=allowance,
            has_full_preview=full_preview,
            can_export=can_export,
            preview_limit_seconds=None,
        )
    )


def downgrade() -> None:
    # The entitlement re-sync is not reversed. Re-applying the old, incorrect
    # capabilities on the way down would break paying customers who registered
    # while the old rules were live, and downgrading a support column should not
    # change what an account is entitled to. The two added columns and the audit
    # table are removed normally.
    op.drop_index("ix_admin_audit_target_created", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_target_user_id", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_admin_user_id", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")

    op.drop_index("ix_users_is_admin", table_name="users")
    op.drop_column("users", "bonus_processing_seconds")
    op.drop_column("users", "is_admin")
