"""Durable, cross-replica rate-limit counters.

Revision ID: 0005_rate_limit_buckets
Revises: 0004_account_deletion_and_consent
Create Date: 2026-09-27

Adds `rate_limit_buckets`, a single table holding one fixed window per
`"<bucket>:<scope>:<subject>"` key.

Why it exists
-------------
`app.ratelimit` keeps its counters in process memory, so the limit it enforces
is *per replica*. On a host running N replicas an attacker who reaches all of
them gets N times the documented limit, resets every counter whenever a replica
is recycled, and loses the whole budget on a deploy. That is tolerable for
transcription and billing, where the caller is authenticated, and it is not
tolerable for the three unauthenticated endpoints where password guessing,
account minting, and mail-provider flooding all start: `POST /api/auth/login`,
`POST /api/auth/register`, and `POST /api/auth/forgot-password`. Those three now
count against this table as well.

The in-process limiter is kept in front of it rather than replaced. It needs no
database round trip, so a flood is still absorbed before it can reach Postgres;
this table is the shared half of the budget, not the cheap half.

Why a fixed window with an upsert
---------------------------------
`key` is the primary key, so one request is a single
`INSERT ... ON CONFLICT (key) DO UPDATE`. PostgreSQL serialises the conflicting
writers on that row, so two replicas counting the same address cannot both read
a stale count and both slip under the limit. A read-then-write would have that
race; a `SELECT` followed by an `UPDATE` would have it too.

`window_started_at` records when the current window opened rather than when it
expires, which is what makes the window fixed instead of sliding and lets an
expired window be reset by the same statement that increments it.

Safety
------
The table is purely additive: a new table, no change to any existing table and
no data to rewrite, so it is safe to apply to the live PostgreSQL database.
Every row is transient state. Nothing else references the table, and rows older
than the longest configured bucket window are deleted by the opportunistic prune
in `app.ratelimit` (no scheduler, no background thread).

Column types are portable (no JSONB/ARRAY/UUID) so the same revision runs on
PostgreSQL in production and on SQLite for local verification and tests.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_rate_limit_buckets"
down_revision: Union[str, None] = "0004_account_deletion_and_consent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_buckets",
        # Long enough for "<bucket>:<scope>:<subject>", where the subject is
        # either a truncated client address or a truncated SHA-256 digest.
        sa.Column("key", sa.String(length=320), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("rate_limit_buckets")
