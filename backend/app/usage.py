"""Usage periods, allowance accounting, and entitlement calculation.

Seconds are the unit of record everywhere, so rounding never loses time. Minute
values are derived only at the API/display boundary.

## Concurrency

Two simultaneous transcription requests must not be able to spend the same
remaining allowance. `reserve_processing_seconds` performs the check and the hold
inside one transaction that first takes a row-level lock on the account
(`SELECT ... FOR UPDATE`, which PostgreSQL provides). The second request blocks
until the first commits, then re-reads the new total and is rejected if the
allowance is genuinely exhausted. See `reserve_processing_seconds` for details.

## Charging

Nothing is charged for an upload that merely starts. Allowance is *reserved*
before WhisperX runs, then `finalize_reservation` converts the hold into real
usage on success, or `release_reservation` discards it on failure. A request that
crashes leaves a `reserved` row that `release_stale_reservations` reclaims after
a TTL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from .db.models import (
    RESERVATION_FINALIZED,
    RESERVATION_RELEASED,
    RESERVATION_RESERVED,
    UsageReservation,
    User,
)
from .plans import get_plan

#: Sentinels and limits
MIN_RESERVED_SECONDS = 1


def _as_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC.

    SQLite round-trips `DateTime(timezone=True)` as naive values, so this keeps
    period comparisons valid on both SQLite and PostgreSQL.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def period_start_for(reference: datetime, plan_id: str | None) -> datetime:
    """Start of the usage period containing `reference` (UTC).

    Every plan resets monthly, including `creator_annual`: annual billing changes
    when the customer is charged, not when the allowance refreshes. The period
    length still comes from the plan (`usage_period_months`) so a future
    non-monthly allowance does not need another code change.
    """
    reference = _as_utc(reference)
    return reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(start: datetime, months: int) -> datetime:
    """Advance a period boundary by whole months, clamping to the last valid day."""
    start = _as_utc(start)
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1

    next_month_start = datetime(year + (month // 12), (month % 12) + 1, 1, tzinfo=timezone.utc)
    last_day = (next_month_start - timedelta(days=1)).day

    return start.replace(year=year, month=month, day=min(start.day, last_day))


def ensure_current_usage_period(user: User, now: datetime | None = None) -> bool:
    """Roll the usage period forward if it has elapsed.

    Returns True when a rollover happened. The period length comes from
    `plan.usage_period_months`, which is 1 for every current plan. An annually
    billed customer therefore still resets monthly, and unused allowance is
    discarded rather than accumulated.
    """
    now = _as_utc(now or utcnow())
    plan = get_plan(user.plan)

    if now < _as_utc(user.usage_period_ends_at):
        return False

    period_start = period_start_for(now, user.plan)
    user.usage_period_started_at = period_start
    user.usage_period_ends_at = add_months(period_start, plan.usage_period_months)
    user.processing_used_seconds = 0

    return True


def apply_plan_to_user(user: User, plan_id: str | None = None) -> None:
    """Seed a user's plan, usage, and entitlement columns from the catalogue."""
    plan = get_plan(plan_id if plan_id is not None else user.plan)

    user.plan = plan.id
    user.monthly_processing_allowance_seconds = plan.usage_allowance_seconds
    user.preview_limit_seconds = plan.preview_limit_seconds
    user.has_full_preview = plan.has_full_preview
    user.can_export = plan.can_export

    if not user.subscription_status:
        from .plans import SUBSCRIPTION_NONE

        user.subscription_status = SUBSCRIPTION_NONE


def seconds_to_minutes(seconds: int | float | None) -> float:
    """Convert seconds to minutes rounded to one decimal, for display only."""
    if not seconds:
        return 0.0
    return round(float(seconds) / 60.0, 1)


def format_minutes(seconds: int | float | None) -> str:
    """Human-friendly minute string that keeps large values readable."""
    if not seconds:
        return "0 minutes"

    minutes = float(seconds) / 60.0
    if minutes >= 100:
        return f"{int(round(minutes)):,} minutes"
    if minutes >= 10:
        return f"{int(round(minutes)):,} minutes"

    return f"{round(minutes, 1)} minutes"


# --------------------------------------------------------------------------- #
# Reservations                                                               #
# --------------------------------------------------------------------------- #


class AllowanceExceededError(Exception):
    """Raised when a request would exceed the remaining allowance."""

    def __init__(
        self,
        *,
        required_seconds: int,
        remaining_seconds: int,
        allowance_seconds: int,
        used_seconds: int,
    ) -> None:
        self.required_seconds = required_seconds
        self.remaining_seconds = remaining_seconds
        self.allowance_seconds = allowance_seconds
        self.used_seconds = used_seconds
        super().__init__(
            f"Requires {required_seconds}s but only {remaining_seconds}s remain."
        )

    @property
    def detail(self) -> str:
        return (
            f"You have {self.remaining_seconds} seconds of processing remaining, "
            f"but this file needs {self.required_seconds} seconds. "
            f"Your {self.allowance_seconds}-second allowance for this period has "
            f"used {self.used_seconds} seconds."
        )


@dataclass(frozen=True)
class ReservationResult:
    reservation_id: int
    reserved_seconds: int
    remaining_seconds: int


def active_reserved_seconds(db: OrmSession, user_id: int) -> int:
    """Total seconds currently held by unresolved reservations."""
    total = db.scalar(
        select(func.coalesce(func.sum(UsageReservation.reserved_seconds), 0)).where(
            UsageReservation.user_id == user_id,
            UsageReservation.status == RESERVATION_RESERVED,
        )
    )
    return int(total or 0)


def remaining_allowance_seconds(db: OrmSession, user: User, now: datetime | None = None) -> int:
    """Seconds available right now, accounting for in-flight reservations.

    Never returns a negative value, so a balance can never go below zero.
    """
    now = now or utcnow()
    ensure_current_usage_period(user, now)

    allowance = int(user.monthly_processing_allowance_seconds or 0)
    used = int(user.processing_used_seconds or 0)
    held = active_reserved_seconds(db, user.id)

    return max(allowance - used - held, 0)


def reserve_processing_seconds(
    db: OrmSession,
    user: User,
    seconds: int,
    now: datetime | None = None,
) -> ReservationResult:
    """Hold allowance for one transcription request, or refuse.

    Concurrency: the user row is re-read with `SELECT ... FOR UPDATE`, so on
    PostgreSQL a second concurrent request for the same account blocks here until
    this transaction commits. It then re-reads the committed `used_seconds` and
    the new reservation row, so it cannot spend allowance this request already
    holds. The lock is released at commit, which happens *before* the expensive
    WhisperX work starts.

    Raises `AllowanceExceededError` when the request cannot be accommodated.
    """
    now = now or utcnow()
    required = max(int(seconds or 0), 0)

    if required < MIN_RESERVED_SECONDS:
        # Nothing to hold; the request is effectively free.
        return ReservationResult(
            reservation_id=0,
            reserved_seconds=0,
            remaining_seconds=remaining_allowance_seconds(db, user, now),
        )

    # Row-level lock for the check-and-hold. Serialises concurrent requests.
    locked_user = db.scalar(
        select(User).where(User.id == user.id).with_for_update()
    )

    if locked_user is None:
        raise AllowanceExceededError(
            required_seconds=required,
            remaining_seconds=0,
            allowance_seconds=0,
            used_seconds=0,
        )

    # Roll the period if needed before measuring.
    ensure_current_usage_period(locked_user, now)

    allowance = int(locked_user.monthly_processing_allowance_seconds or 0)
    used = int(locked_user.processing_used_seconds or 0)
    held = active_reserved_seconds(db, locked_user.id)
    remaining = max(allowance - used - held, 0)

    if required > remaining:
        db.rollback()
        raise AllowanceExceededError(
            required_seconds=required,
            remaining_seconds=remaining,
            allowance_seconds=allowance,
            used_seconds=used,
        )

    reservation = UsageReservation(
        user_id=locked_user.id,
        reserved_seconds=required,
        status=RESERVATION_RESERVED,
        created_at=now,
    )
    db.add(reservation)
    db.commit()

    # Mirror the rolled period back onto the caller's instance.
    user.usage_period_started_at = locked_user.usage_period_started_at
    user.usage_period_ends_at = locked_user.usage_period_ends_at

    return ReservationResult(
        reservation_id=reservation.id,
        reserved_seconds=required,
        remaining_seconds=max(remaining - required, 0),
    )


def finalize_reservation(
    db: OrmSession, reservation_id: int, now: datetime | None = None
) -> int:
    """Convert a hold into real usage. Called only after a successful transcription."""
    if not reservation_id:
        return 0

    now = now or utcnow()
    reservation = db.get(UsageReservation, reservation_id)

    if reservation is None or reservation.status != RESERVATION_RESERVED:
        # Already finalised or released: nothing to do, and never double-charged.
        return 0

    user = db.scalar(select(User).where(User.id == reservation.user_id).with_for_update())

    if user is None:
        reservation.status = RESERVATION_RELEASED
        reservation.resolved_at = now
        db.commit()
        return 0

    ensure_current_usage_period(user, now)

    allowance = int(user.monthly_processing_allowance_seconds or 0)
    used = int(user.processing_used_seconds or 0)
    # Clamp so a corrupted or manually edited value cannot go negative.
    user.processing_used_seconds = min(used + reservation.reserved_seconds, max(allowance, 0))

    reservation.status = RESERVATION_FINALIZED
    reservation.resolved_at = now
    db.commit()

    return reservation.reserved_seconds


def release_reservation(
    db: OrmSession, reservation_id: int, now: datetime | None = None
) -> int:
    """Discard a hold without charging. Called on failure, rejection, or crash recovery."""
    if not reservation_id:
        return 0

    now = now or utcnow()
    reservation = db.get(UsageReservation, reservation_id)

    if reservation is None or reservation.status != RESERVATION_RESERVED:
        return 0

    reservation.status = RESERVATION_RELEASED
    reservation.resolved_at = now
    db.commit()

    return reservation.reserved_seconds


def release_stale_reservations(
    db: OrmSession, ttl_seconds: int, now: datetime | None = None
) -> int:
    """Reclaim holds left behind by a crashed request.

    Without this, a process killed mid-transcription would hold a customer's
    allowance forever. Anything still `reserved` after the TTL is treated as
    failed and released.
    """
    if ttl_seconds <= 0:
        return 0

    now = now or utcnow()
    cutoff = now - timedelta(seconds=ttl_seconds)

    stale = db.scalars(
        select(UsageReservation).where(
            UsageReservation.status == RESERVATION_RESERVED,
            UsageReservation.created_at < cutoff,
        )
    ).all()

    for reservation in stale:
        reservation.status = RESERVATION_RELEASED
        reservation.resolved_at = now

    if stale:
        db.commit()

    return len(stale)


# --------------------------------------------------------------------------- #
# Read model                                                                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UsageSnapshot:
    """Everything the frontend needs to render plan and usage state."""

    plan: str
    plan_label: str
    subscription_status: str
    is_paid_plan: bool

    monthly_processing_allowance_seconds: int
    processing_used_seconds: int
    processing_reserved_seconds: int
    processing_remaining_seconds: int

    usage_period_started_at: datetime
    usage_period_ends_at: datetime
    usage_period_months: int
    usage_resets_monthly: bool
    #: Stripe billing cadence, deliberately separate from the usage reset above.
    billed_annually: bool

    preview_limit_seconds: int | None
    has_full_preview: bool
    can_export: bool

    # Display conveniences, derived from the authoritative seconds above.
    processing_allowance_minutes: float
    processing_used_minutes: float
    processing_remaining_minutes: float


def build_usage_snapshot(
    db: OrmSession, user: User, now: datetime | None = None
) -> UsageSnapshot:
    """Compute the read model for a user.

    Reads the mirrored columns; never accepts values from the client.
    """
    now = now or utcnow()
    plan = get_plan(user.plan)

    allowance = int(user.monthly_processing_allowance_seconds or 0)
    used = int(user.processing_used_seconds or 0)
    held = active_reserved_seconds(db, user.id)
    remaining = max(allowance - used - held, 0)

    return UsageSnapshot(
        plan=user.plan,
        plan_label=plan.label,
        subscription_status=user.subscription_status,
        is_paid_plan=plan.paid,
        monthly_processing_allowance_seconds=allowance,
        processing_used_seconds=used,
        processing_reserved_seconds=held,
        processing_remaining_seconds=remaining,
        usage_period_started_at=_as_utc(user.usage_period_started_at),
        usage_period_ends_at=_as_utc(user.usage_period_ends_at),
        usage_period_months=plan.usage_period_months,
        usage_resets_monthly=plan.usage_resets_monthly,
        billed_annually=plan.is_annual_billing,
        preview_limit_seconds=user.preview_limit_seconds,
        has_full_preview=bool(user.has_full_preview),
        can_export=bool(user.can_export),
        processing_allowance_minutes=seconds_to_minutes(allowance),
        processing_used_minutes=seconds_to_minutes(used),
        processing_remaining_minutes=seconds_to_minutes(remaining),
    )
