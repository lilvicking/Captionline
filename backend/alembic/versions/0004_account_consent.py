"""Account deletion support and legal consent capture.

Revision ID: 0004_account_consent
Revises: 0003_password_reset
Create Date: 2026-09-27

Adds four nullable columns to `users`:

  * terms_accepted_at / terms_version
  * privacy_acknowledged_at / privacy_version

Every column is nullable and every one has no server default, which is what
makes this safe to apply to the live PostgreSQL database:

* Existing rows are untouched. `ADD COLUMN ... NULL` rewrites nothing on
  PostgreSQL and takes a metadata-only lock.
* No existing account is locked out. Consent is recorded, never enforced at
  read time, so a user who registered before this revision keeps full access and
  the columns simply stay NULL. A `NOT NULL` column with a backfill would have
  been a different decision: it would assert that every pre-existing account
  accepted text that did not exist when they signed up.

Only the version *labels* are stored, not the legal text itself. The text lives
outside the database; what the row records is which published version the user
was shown, so an audit can answer that question later even after the text
changes again.

Column types are portable (no JSONB/ARRAY/UUID) so the same revision runs on
PostgreSQL in production and on SQLite for local verification and tests.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Alembic stores this identifier in `alembic_version.version_num`, which on the
# production PostgreSQL database is VARCHAR(32). The original identifier,
# "0004_account_deletion_and_consent", was 33 characters and failed at deploy
# time with StringDataRightTruncation, so the identifier is kept short enough to
# fit. Renaming an unapplied revision is far cheaper than widening that column.
# `tests/test_migrations.py` asserts every revision identifier fits, so the next
# person to name a long revision finds out in CI rather than in production.
revision: str = "0004_account_consent"
down_revision: Union[str, None] = "0003_password_reset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (column name, column type)
_CONSENT_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("terms_accepted_at", sa.DateTime(timezone=True)),
    ("terms_version", sa.String(length=32)),
    ("privacy_acknowledged_at", sa.DateTime(timezone=True)),
    ("privacy_version", sa.String(length=32)),
)


def upgrade() -> None:
    for name, column_type in _CONSENT_COLUMNS:
        op.add_column("users", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _column_type in reversed(_CONSENT_COLUMNS):
        op.drop_column("users", name)
