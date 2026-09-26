"""Usage period and entitlement calculation.

Seconds are the unit of record everywhere so rounding never loses time. Minute
values are derived only at the API/display boundary.

Nothing here is enforced against transcription yet: Phase 3A proves the
account/usage state is correct first. `record_processing_seconds` exists so the
eventual enforcement path is already defined, but it is not wired into
`/api/transcribe`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db.models import User
from .plans import get_plan


def _as_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC.

    SQLite round-trips `DateTime(timezone=True)` as naive values, so this keeps
    period comparisons valid on both SQLite and PostgreSQL.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def monthly_period_start(reference: datetime) -> datetime:
    """First instant of the calendar month containing `reference` (UTC)."""
    reference = _as_utc(reference)
    return reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_month(start: datetime, months: int) -> datetime:
    """Advance a month boundary, clamping to the last valid day when needed."""
    start = _as_utc(start)
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1

    # Find the last day of the target month so 31 Jan + 1 month lands in Feb.
    next_month_start = datetime(year + (month // 12), (month % 12) + 1, 1, tzinfo=timezone.utc)
    last_day = (next_month_start - timedelta(days=1)).day

    return start.replace(year=year, month=month, day=min(start.day, last_day))


def ensure_current_usage_period(user: User, now: datetime | None = None) -> bool:
    """Roll the usage period forward if it has elapsed.

    Returns True when a rollover happened, so callers can decide whether to
    commit. Safe to call on every entitlement read.
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    ends_at = _as_utc(user.usage_period_ends_at)

    if now < ends_at:
        return False

    period_start = monthly_period_start(now)
    user.usage_period_started_at = period_start
    user.usage_period_ends_at = add_month(period_start, 1)
    user.processing_used_seconds = 0

    return True


def apply_plan_to_user(user: User, plan_id: str | None = None) -> None:
    """Seed a user's plan, usage, and entitlement columns from the plan catalogue.

    Called on registration and whenever entitlements are refreshed from the
    authoritative source. This keeps every literal in `app/plans.py` rather than
    scattered through the codebase.
    """
    plan = get_plan(plan_id if plan_id is not None else user.plan)

    user.plan = plan.id
    user.monthly_processing_allowance_seconds = plan.monthly_processing_seconds
    user.preview_limit_seconds = plan.preview_limit_seconds
    user.has_full_preview = plan.has_full_preview
    user.can_export = plan.can_export

    if not user.subscription_status:
        user.subscription_status = plan.subscription_status


def seconds_to_minutes(seconds: int | float | None) -> float:
    """Convert seconds to minutes rounded to one decimal, for display only."""
    if not seconds:
        return 0.0
    return round(float(seconds) / 60.0, 1)


@dataclass(frozen=True)
class UsageSnapshot:
    """Everything the frontend needs to render plan and usage state."""

    plan: str
    plan_label: str
    subscription_status: str

    monthly_processing_allowance_seconds: int
    processing_used_seconds: int
    processing_remaining_seconds: int

    usage_period_started_at: datetime
    usage_period_ends_at: datetime

    preview_limit_seconds: int | None
    has_full_preview: bool
    can_export: bool

    # Display conveniences, derived from the authoritative seconds above.
    processing_allowance_minutes: float
    processing_used_minutes: float
    processing_remaining_minutes: float


def build_usage_snapshot(user: User, now: datetime | None = None) -> UsageSnapshot:
    """Compute the read model for a user.

    Reads the mirrored columns; never accepts values from the client.
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    plan = get_plan(user.plan)

    allowance = int(user.monthly_processing_allowance_seconds or 0)
    used = int(user.processing_used_seconds or 0)
    # Clamp so a negative allowance can never report negative remaining time.
    remaining = max(allowance - used, 0)

    return UsageSnapshot(
        plan=user.plan,
        plan_label=plan.label,
        subscription_status=user.subscription_status,
        monthly_processing_allowance_seconds=allowance,
        processing_used_seconds=used,
        processing_remaining_seconds=remaining,
        usage_period_started_at=_as_utc(user.usage_period_started_at),
        usage_period_ends_at=_as_utc(user.usage_period_ends_at),
        preview_limit_seconds=user.preview_limit_seconds,
        has_full_preview=bool(user.has_full_preview),
        can_export=bool(user.can_export),
        processing_allowance_minutes=seconds_to_minutes(allowance),
        processing_used_minutes=seconds_to_minutes(used),
        processing_remaining_minutes=seconds_to_minutes(remaining),
    )


def record_processing_seconds(user: User, seconds: int) -> int:
    """Add processed time to the current usage period.

    Not called by /api/transcribe in Phase 3A. It defines the future enforcement
    path so that wiring it later is a one-line change plus an allowance check.
    """
    if seconds <= 0:
        return int(user.processing_used_seconds or 0)

    user.processing_used_seconds = int(user.processing_used_seconds or 0) + int(seconds)
    return user.processing_used_seconds
