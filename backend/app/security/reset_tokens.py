"""Password reset token lifecycle.

Design notes
------------
* The raw token is generated with `secrets` (256 bits), emailed to the account
  owner, and **never stored**. Only its SHA-256 hash is persisted, so a database
  leak yields nothing usable. This mirrors the existing session-token approach.
* Tokens are single use. Consuming one sets `used_at` inside a transaction that
  holds a row lock, so two concurrent requests with the same token cannot both
  succeed: the second blocks, then observes `used_at` and is rejected.
* Issuing a new token revokes the account's older outstanding tokens, so an
  emailed link stops working as soon as a newer one is requested.
* `reset_password` additionally revokes every active login session, because a
  password reset is the standard response to a suspected compromise and any
  session minted with the old password must not survive it.

Nothing in this module logs a raw token.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.models import PasswordResetToken
from ..db.models import Session as SessionModel
from ..db.models import User
from .tokens import generate_token, hash_token

logger = logging.getLogger(__name__)

#: Reasons a token cannot be used. Internal only: every one of them is reported
#: to the caller with the same generic message so a token cannot be probed.
INVALID_TOKEN = "invalid"
EXPIRED_TOKEN = "expired"
USED_TOKEN = "used"
UNKNOWN_USER = "unknown_user"
INACTIVE_USER = "inactive_user"


class InvalidResetToken(Exception):
    """Raised when a presented reset token cannot be used.

    Carries an internal reason for logs and tests, but the API layer never
    reveals which one it was.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class IssuedResetToken:
    """A freshly issued token. The raw value is returned once, for emailing."""

    raw_token: str
    expires_at: datetime


def _as_utc(value: datetime) -> datetime:
    """SQLite round-trips timezone-aware columns as naive values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def active_reset_tokens(db: OrmSession, user_id: int, now: datetime | None = None) -> int:
    """Count tokens that are still usable for an account."""
    now = now or datetime.now(timezone.utc)

    rows = db.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.revoked_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    ).all()

    return len(rows)


def most_recent_reset_at(db: OrmSession, user_id: int) -> datetime | None:
    """When the newest token for this account was created, if any."""
    latest = db.scalar(
        select(PasswordResetToken.created_at)
        .where(PasswordResetToken.user_id == user_id)
        .order_by(PasswordResetToken.created_at.desc())
        .limit(1)
    )

    return _as_utc(latest) if latest is not None else None


def is_rate_limited(
    db: OrmSession,
    user_id: int,
    now: datetime | None = None,
    cooldown_seconds: int | None = None,
    max_active: int | None = None,
) -> bool:
    """Whether a new reset request for this account should be suppressed.

    Two independent guards: a cooldown between requests, and a cap on how many
    outstanding tokens may exist. Both are per account, so they need no client
    address and store no personal data.
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    cooldown = settings.password_reset_cooldown_seconds if cooldown_seconds is None else cooldown_seconds
    cap = settings.password_reset_max_active if max_active is None else max_active

    if cooldown > 0:
        created = most_recent_reset_at(db, user_id)
        if created is not None and (now - created) < timedelta(seconds=cooldown):
            return True

    if cap > 0 and active_reset_tokens(db, user_id, now) >= cap:
        return True

    return False


def revoke_all_reset_tokens(
    db: OrmSession, user_id: int, now: datetime | None = None
) -> int:
    """Revoke every outstanding token for an account. Returns the count."""
    now = now or datetime.now(timezone.utc)

    result = db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    return int(result.rowcount or 0)


def enforce_active_token_cap(
    db: OrmSession, user_id: int, max_active: int, now: datetime | None = None
) -> int:
    """Revoke the oldest outstanding tokens so at most `max_active` remain."""
    now = now or datetime.now(timezone.utc)

    outstanding = db.scalars(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.revoked_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .order_by(PasswordResetToken.created_at.asc())
    ).all()

    excess = len(outstanding) - max_active
    if excess <= 0:
        return 0

    for row in outstanding[:excess]:
        row.revoked_at = now

    return excess


def issue_reset_token(
    db: OrmSession, user: User, now: datetime | None = None
) -> IssuedResetToken:
    """Create a reset token and return the raw value exactly once.

    Revokes the account's previous outstanding tokens first, so only the newest
    emailed link works.
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=max(settings.password_reset_ttl_minutes, 1))

    revoke_all_reset_tokens(db, user.id, now)
    enforce_active_token_cap(db, user.id, settings.password_reset_max_active, now)

    raw_token = generate_token()

    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            created_at=now,
            expires_at=expires_at,
        )
    )
    db.commit()

    logger.info(
        "Issued a password reset token for user_id=%s, expires in %s minutes",
        user.id,
        settings.password_reset_ttl_minutes,
    )

    return IssuedResetToken(raw_token=raw_token, expires_at=expires_at)


def find_consumable_token(
    db: OrmSession, raw_token: str, now: datetime | None = None
) -> PasswordResetToken:
    """Resolve a raw token to a usable row, or raise `InvalidResetToken`.

    The row is re-read with `SELECT ... FOR UPDATE`, so on PostgreSQL a second
    concurrent request for the same token blocks here until this transaction
    commits. It then observes `used_at` and is rejected, which is what makes the
    token genuinely single-use.
    """
    if not raw_token or not raw_token.strip():
        raise InvalidResetToken(INVALID_TOKEN)

    now = now or datetime.now(timezone.utc)

    row = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_token(raw_token.strip()))
        .with_for_update()
    )

    if row is None:
        raise InvalidResetToken(INVALID_TOKEN)

    if row.used_at is not None:
        raise InvalidResetToken(USED_TOKEN)

    if row.revoked_at is not None:
        raise InvalidResetToken(INVALID_TOKEN)

    if now >= _as_utc(row.expires_at):
        raise InvalidResetToken(EXPIRED_TOKEN)

    return row


def apply_password_reset(
    db: OrmSession, raw_token: str, new_password_hash: str, now: datetime | None = None
) -> User:
    """Consume a reset token and set a new password.

    On success the token is marked used, every other outstanding token for the
    account is revoked, and all existing login sessions are revoked. Returns the
    affected user.
    """
    now = now or datetime.now(timezone.utc)

    row = find_consumable_token(db, raw_token, now)

    # Row lock on the account as well, so two different tokens used at the same
    # moment cannot interleave their session revocation.
    user = db.scalar(select(User).where(User.id == row.user_id).with_for_update())

    if user is None:
        db.rollback()
        raise InvalidResetToken(UNKNOWN_USER)

    if not user.is_active:
        db.rollback()
        raise InvalidResetToken(INACTIVE_USER)

    user.password_hash = new_password_hash
    user.updated_at = now

    row.used_at = now
    row.revoked_at = now

    revoke_all_reset_tokens(db, user.id, now)
    revoked_sessions = revoke_all_sessions(db, user.id, now)

    db.commit()

    # Only identifiers, never tokens or passwords.
    logger.info(
        "Password reset completed for user_id=%s; revoked %s session(s)",
        user.id,
        revoked_sessions,
    )

    return user


def revoke_all_sessions(
    db: OrmSession, user_id: int, now: datetime | None = None
) -> int:
    """Revoke every active login session for an account."""
    now = now or datetime.now(timezone.utc)

    result = db.execute(
        update(SessionModel)
        .where(SessionModel.user_id == user_id, SessionModel.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    return int(result.rowcount or 0)
