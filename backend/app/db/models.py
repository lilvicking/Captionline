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

    # --- Mirrored subscription state (Stripe is the authority) ---
    # Populated only from verified Stripe webhooks. The frontend can never set
    # these, and an unmapped Stripe price leaves them untouched.
    subscription_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SUBSCRIPTION_NONE
    )
    subscription_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subscription_external_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    # The Stripe Price ID behind the current plan, so a webhook can map a
    # subscription back to a plan without re-reading the catalogue.
    subscription_price_id: Mapped[str | None] = mapped_column(
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

    # --- Support credit (administrative) ---
    # Extra processing time granted by an administrator as goodwill. It is an
    # ADDITION to the plan allowance, never a replacement for it, and it is
    # deliberately not reset by the monthly usage-period rollover: credit
    # persists until it is consumed or an administrator removes it.
    #
    # Consumption order is "plan allowance first, then credit", so the monthly
    # allowance is always spent before any goodwill credit is touched.
    bonus_processing_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # --- Entitlements (read model served to the frontend) ---
    # None means an unrestricted preview.
    preview_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_full_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_export: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- Administrative capability ---
    # Set only from the ADMIN_EMAILS allow-list at startup. There is deliberately
    # no endpoint a signed-in user can call to change this, and it is never
    # inferred from a paid plan or an email domain.
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Legal consent ---
    # Recorded, never enforced. NULL means "we did not record an agreement",
    # which is true of every account created before this existed and of anyone
    # who registered without ticking the boxes. Nothing reads these columns to
    # decide whether an account may sign in, so a NULL can never lock anybody
    # out. The version strings label which published text was shown, so the
    # text itself is never stored and can be replaced without a data migration.
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terms_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    privacy_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    privacy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

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

    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Administrative actions taken *against* this account. Cascaded with the
    # account, because the audit row is about a specific person and keeping it
    # after they delete their account would retain their data.
    #
    # `admin_audit_log` has two foreign keys onto users, so the join condition
    # has to name which one this relationship follows.
    audit_entries_as_target: Mapped[list["AdminAuditEntry"]] = relationship(
        back_populates="target_user",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="AdminAuditEntry.target_user_id",
    )

    # The `ondelete="CASCADE"` on `usage_reservations.user_id` is enforced by the
    # database, not by the ORM, and SQLite does not enforce foreign keys unless
    # a caller turns `PRAGMA foreign_keys=ON`. Without this relationship
    # `db.delete(user)` left orphaned allowance holds behind on every SQLite
    # deployment, and on any production path that ever stopped relying on the
    # database constraint. The ORM-level cascade makes deletion correct
    # regardless of what the database enforces.
    #
    # Left on the default lazy strategy rather than `selectin` (as the two
    # relationships above use): this collection is only ever needed when an
    # account is deleted, and `selectin` would add a query to every
    # authenticated request because `get_current_user` loads the user row.
    usage_reservations: Mapped[list["UsageReservation"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_users_plan_status", "plan", "subscription_status"),)


class PasswordResetToken(Base):
    """A single-use password reset token.

    The raw token is generated with `secrets`, emailed to the account owner, and
    never stored. Only its SHA-256 hash is persisted, so a database leak yields
    nothing usable — the same approach already used for session tokens.

    A token stops working when it is used (`used_at`), revoked explicitly
    (`revoked_at`, for example when a newer one is issued or the password is
    changed), or once `expires_at` passes.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # SHA-256 hex of the emailed token. Unique so lookup is an index hit and a
    # collision is impossible to insert twice.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="password_reset_tokens")

    __table_args__ = (UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),)


# Usage reservation lifecycle.
RESERVATION_RESERVED = "reserved"
RESERVATION_FINALIZED = "finalized"
RESERVATION_RELEASED = "released"


class UsageReservation(Base):
    """A short-lived hold on processing allowance.

    Accounting is two-phase so a customer is only ever charged for media that was
    actually transcribed:

      1. `reserve` checks the allowance and inserts a ``reserved`` row in the same
         transaction that holds a row lock on the user. Concurrent requests
         therefore queue behind each other and cannot both spend the same
         remaining allowance.
      2. On success the row becomes ``finalized`` and the seconds are added to
         ``users.processing_used_seconds``.
      3. On failure the row becomes ``released`` and nothing is charged.

    A request that crashes leaves a ``reserved`` row behind, which
    ``release_stale_reservations`` reclaims after a TTL so a crash cannot
    permanently consume allowance.
    """

    __tablename__ = "usage_reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reserved_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RESERVATION_RESERVED
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # See the note on `User.usage_reservations`: this pairing exists so the
    # cascade works in the ORM, not only in the database.
    user: Mapped["User"] = relationship(back_populates="usage_reservations")

    __table_args__ = (
        Index("ix_usage_reservations_user_status", "user_id", "status"),
    )


class StripeEvent(Base):
    """A processed Stripe event id, for idempotent webhook handling.

    Stripe retries webhooks until it receives a 2xx, so the same event can arrive
    more than once. Recording the event id makes handling idempotent.
    """

    __tablename__ = "stripe_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RateLimitBucket(Base):
    """One durable fixed window for a shared rate-limit counter.

    The in-process limiter in `app.ratelimit` is per replica, so on a host
    running several replicas an attacker who reaches all of them gets several
    times the intended limit. This table holds the counter that is actually
    shared, so the fleet-wide budget is the configured one. It is used only for
    the abuse-critical unauthenticated endpoints (login, register,
    forgot-password); the cheaper per-replica map stays in front of it as a
    pre-filter.

    `key` is `"<bucket>:<scope>:<subject>"` and is the primary key, so the
    increment is a single atomic upsert and two replicas cannot both slip under
    the limit. `window_started_at` is when the current window opened, which is
    what makes the window fixed rather than sliding; a window older than the
    longest configured bucket window can never be read again and is deleted by
    the opportunistic prune in `app.ratelimit`.

    The subjects stored here are the same ones the in-process limiter uses: a
    client address, or the SHA-256 of an email address (never the address
    itself). Nothing else about a caller is recorded.
    """

    __tablename__ = "rate_limit_buckets"

    key: Mapped[str] = mapped_column(String(320), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


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


# Administrative action names, kept as constants so a typo cannot silently create
# an unrecognised audit category.
ACTION_CREDIT_GRANTED = "credit_granted"
ACTION_CREDIT_REMOVED = "credit_removed"
ACTION_PRIVILEGE_CHANGED = "privilege_changed"


class AdminAuditEntry(Base):
    """One administrative action, recorded so support work is traceable.

    This is a persistent trail in PostgreSQL, not just a log line: Railway log
    retention is short and not queryable per customer.

    Deliberately does **not** record credentials, password hashes, session or
    reset tokens, or any payment data. It records who acted, on whom, what, by
    how much, and why.
    """

    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: The administrator who acted.
    admin_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The customer the action affected.
    target_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    action: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Signed change in seconds. Negative removes a previously granted credit.
    amount_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Why the action was taken. Required by the API.
    reason: Mapped[str] = mapped_column(String(280), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    admin_user: Mapped["User"] = relationship(foreign_keys=[admin_user_id])
    target_user: Mapped["User"] = relationship(
        back_populates="audit_entries_as_target", foreign_keys=[target_user_id]
    )

    __table_args__ = (Index("ix_admin_audit_target_created", "target_user_id", "created_at"),)
