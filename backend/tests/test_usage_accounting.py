"""Tests for allowance accounting, reservations, and usage periods.

These use the real database and the real Alembic migrations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import UsageReservation, User
from app.plans import (
    CREATOR_ANNUAL,
    CREATOR_ANNUAL_PLAN_ID,
    CREATOR_MONTHLY,
    CREATOR_MONTHLY_PLAN_ID,
    FREE_PLAN,
    FREE_PLAN_ID,
    PRO_MONTHLY,
    PRO_MONTHLY_PLAN_ID,
)
from app.usage import (
    AllowanceExceededError,
    add_months,
    apply_plan_to_user,
    build_usage_snapshot,
    ensure_current_usage_period,
    finalize_reservation,
    format_minutes,
    period_start_for,
    release_reservation,
    release_stale_reservations,
    remaining_allowance_seconds,
    reserve_processing_seconds,
    seconds_to_minutes,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def make_user(db_session, email="usage@example.com", plan_id=FREE_PLAN_ID, **overrides):
    from app.plans import get_plan

    plan = get_plan(plan_id)
    start = period_start_for(NOW, plan_id)
    defaults = dict(
        email=email,
        password_hash="x",
        plan=plan_id,
        subscription_status="none",
        monthly_processing_allowance_seconds=plan.usage_allowance_seconds,
        processing_used_seconds=0,
        usage_period_started_at=start,
        usage_period_ends_at=add_months(start, plan.usage_period_months),
        preview_limit_seconds=plan.preview_limit_seconds,
        has_full_preview=plan.has_full_preview,
        can_export=plan.can_export,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)

    user = User(**defaults)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# --- Allowances per plan ---


@pytest.mark.parametrize(
    "plan_id,expected_allowance,expected_minutes",
    [
        (FREE_PLAN_ID, 600, 10.0),
        (CREATOR_MONTHLY_PLAN_ID, 30_000, 500.0),
        (PRO_MONTHLY_PLAN_ID, 90_000, 1_500.0),
        # Creator Annual is billed yearly but resets monthly, so it gets the same
        # 500 minutes as Creator Monthly, NOT a 6,000 minute annual pool.
        (CREATOR_ANNUAL_PLAN_ID, 30_000, 500.0),
    ],
)
def test_allowance_seconds_per_plan(
    db_session, plan_id, expected_allowance, expected_minutes
):
    user = make_user(db_session, f"{plan_id}@example.com", plan_id)

    snapshot = build_usage_snapshot(db_session, user, NOW)

    assert snapshot.monthly_processing_allowance_seconds == expected_allowance
    assert snapshot.processing_allowance_minutes == expected_minutes
    assert snapshot.processing_remaining_seconds == expected_allowance
    # Every plan reports a monthly usage reset.
    assert snapshot.usage_resets_monthly is True
    assert snapshot.usage_period_months == 1


# --- Reservation lifecycle ---


def test_reserve_then_finalize_charges_duration(db_session):
    user = make_user(db_session)

    reservation = reserve_processing_seconds(db_session, user, 90, NOW)
    assert reservation.reservation_id > 0
    assert reservation.remaining_seconds == 510

    # Before finalising, the hold is not yet real usage.
    db_session.refresh(user)
    assert user.processing_used_seconds == 0
    assert remaining_allowance_seconds(db_session, user, NOW) == 510

    finalize_reservation(db_session, reservation.reservation_id, NOW)

    db_session.refresh(user)
    assert user.processing_used_seconds == 90
    assert remaining_allowance_seconds(db_session, user, NOW) == 510


def test_reserve_then_release_charges_nothing(db_session):
    """A failed transcription must never be billed."""
    user = make_user(db_session)

    reservation = reserve_processing_seconds(db_session, user, 90, NOW)
    release_reservation(db_session, reservation.reservation_id, NOW)

    db_session.refresh(user)
    assert user.processing_used_seconds == 0
    assert remaining_allowance_seconds(db_session, user, NOW) == 600


def test_rejected_request_never_reserves(db_session):
    user = make_user(db_session)

    with pytest.raises(AllowanceExceededError):
        reserve_processing_seconds(db_session, user, 601, NOW)

    db_session.refresh(user)
    assert user.processing_used_seconds == 0
    assert db_session.query(UsageReservation).count() == 0


def test_insufficient_allowance_reports_remaining_and_required(db_session):
    user = make_user(db_session, processing_used_seconds=558)

    with pytest.raises(AllowanceExceededError) as caught:
        reserve_processing_seconds(db_session, user, 90, NOW)

    error = caught.value
    assert error.remaining_seconds == 42
    assert error.required_seconds == 90
    assert "42 seconds" in error.detail
    assert "90 seconds" in error.detail


def test_exact_allowance_is_allowed(db_session):
    user = make_user(db_session)

    reservation = reserve_processing_seconds(db_session, user, 600, NOW)
    assert reservation.remaining_seconds == 0

    with pytest.raises(AllowanceExceededError):
        reserve_processing_seconds(db_session, user, 1, NOW)


def test_zero_and_negative_reservations_are_free(db_session):
    user = make_user(db_session)

    zero = reserve_processing_seconds(db_session, user, 0, NOW)
    negative = reserve_processing_seconds(db_session, user, -50, NOW)

    assert zero.reservation_id == 0
    assert negative.reservation_id == 0
    db_session.refresh(user)
    assert user.processing_used_seconds == 0


def test_finalize_is_idempotent(db_session):
    """Double-finalising must not double-charge."""
    user = make_user(db_session)

    reservation = reserve_processing_seconds(db_session, user, 90, NOW)
    assert finalize_reservation(db_session, reservation.reservation_id, NOW) == 90
    assert finalize_reservation(db_session, reservation.reservation_id, NOW) == 0

    db_session.refresh(user)
    assert user.processing_used_seconds == 90


def test_release_after_finalize_does_nothing(db_session):
    user = make_user(db_session)

    reservation = reserve_processing_seconds(db_session, user, 90, NOW)
    finalize_reservation(db_session, reservation.reservation_id, NOW)
    release_reservation(db_session, reservation.reservation_id, NOW)

    db_session.refresh(user)
    assert user.processing_used_seconds == 90


# --- Concurrency protection ---


def test_two_reservations_cannot_spend_the_same_remaining_allowance(db_session):
    """The second concurrent hold must see the first one's hold.

    The allowance check and the hold happen in one transaction under a row lock,
    so a second request cannot both be told there is room for 400s when only
    400s exist in total.
    """
    user = make_user(db_session, processing_used_seconds=200)  # 400 remaining

    first = reserve_processing_seconds(db_session, user, 400, NOW)
    assert first.remaining_seconds == 0

    # A second request for any further time must be refused, because the first
    # hold is still unresolved.
    with pytest.raises(AllowanceExceededError) as caught:
        reserve_processing_seconds(db_session, user, 1, NOW)

    assert caught.value.remaining_seconds == 0

    db_session.refresh(user)
    assert user.processing_used_seconds == 200  # only real usage counted


def test_two_partial_reservations_share_the_allowance(db_session):
    user = make_user(db_session, processing_used_seconds=100)  # 500 remaining

    first = reserve_processing_seconds(db_session, user, 300, NOW)
    assert first.remaining_seconds == 200

    second = reserve_processing_seconds(db_session, user, 200, NOW)
    assert second.remaining_seconds == 0

    with pytest.raises(AllowanceExceededError):
        reserve_processing_seconds(db_session, user, 1, NOW)

    # Finalising both consumes exactly the remaining allowance, never more.
    finalize_reservation(db_session, first.reservation_id, NOW)
    finalize_reservation(db_session, second.reservation_id, NOW)

    db_session.refresh(user)
    assert user.processing_used_seconds == 600
    assert remaining_allowance_seconds(db_session, user, NOW) == 0


def test_allowance_never_goes_negative(db_session):
    user = make_user(db_session, processing_used_seconds=599)

    reservation = reserve_processing_seconds(db_session, user, 1, NOW)
    finalize_reservation(db_session, reservation.reservation_id, NOW)

    db_session.refresh(user)
    assert user.processing_used_seconds == 600
    assert remaining_allowance_seconds(db_session, user, NOW) == 0
    assert build_usage_snapshot(db_session, user, NOW).processing_remaining_seconds == 0


def test_corrupt_used_value_is_clamped_at_finalize(db_session):
    """A hand-edited value must not push usage past the allowance or below zero."""
    user = make_user(db_session, processing_used_seconds=590)  # 10 remaining

    reservation = reserve_processing_seconds(db_session, user, 5, NOW)

    # Simulate usage drifting up between reserve and finalize.
    user.processing_used_seconds = 598
    db_session.commit()

    finalize_reservation(db_session, reservation.reservation_id, NOW)

    db_session.refresh(user)
    # 598 + 5 = 603, which would exceed the 600 allowance.
    assert user.processing_used_seconds == 600
    assert user.processing_used_seconds <= 600
    assert remaining_allowance_seconds(db_session, user, NOW) == 0


def test_negative_used_value_is_clamped(db_session):
    """A corrupted negative counter must not produce a negative charge."""
    user = make_user(db_session, processing_used_seconds=-50)

    snapshot = build_usage_snapshot(db_session, user, NOW)

    assert snapshot.processing_used_seconds == -50  # reported as stored
    # Remaining is still bounded and never negative.
    assert snapshot.processing_remaining_seconds == 650
    assert snapshot.processing_remaining_seconds >= 0


# --- Stale reservation recovery ---


def test_stale_reservations_are_released(db_session):
    """A crashed request must not consume allowance forever."""
    user = make_user(db_session)

    reservation = reserve_processing_seconds(db_session, user, 300, NOW)
    assert remaining_allowance_seconds(db_session, user, NOW) == 300

    stale_time = NOW + timedelta(seconds=7200 + 60)
    released = release_stale_reservations(db_session, 7200, stale_time)
    assert released == 1

    assert remaining_allowance_seconds(db_session, user, stale_time) == 600
    db_session.refresh(user)
    assert user.processing_used_seconds == 0


def test_fresh_reservations_are_not_released(db_session):
    user = make_user(db_session)
    reserve_processing_seconds(db_session, user, 300, NOW)

    assert release_stale_reservations(db_session, 7200, NOW + timedelta(seconds=60)) == 0
    assert remaining_allowance_seconds(db_session, user, NOW) == 300


def test_stale_release_is_disabled_when_ttl_is_zero(db_session):
    user = make_user(db_session)
    reserve_processing_seconds(db_session, user, 300, NOW)

    assert release_stale_reservations(db_session, 0, NOW + timedelta(days=1)) == 0


# --- Usage periods ---


def test_period_starts_on_first_of_month_for_every_plan():
    """Annual billing must not move the usage boundary to January."""
    for plan_id in (FREE_PLAN_ID, CREATOR_MONTHLY_PLAN_ID, PRO_MONTHLY_PLAN_ID, CREATOR_ANNUAL_PLAN_ID):
        start = period_start_for(NOW, plan_id)
        assert start == datetime(2026, 9, 1, tzinfo=timezone.utc), plan_id


def test_monthly_plan_advances_one_month(db_session):
    user = make_user(db_session)
    assert ensure_current_usage_period(user, datetime(2026, 9, 15, tzinfo=timezone.utc)) is False
    assert ensure_current_usage_period(user, datetime(2026, 10, 2, tzinfo=timezone.utc)) is True
    assert user.usage_period_started_at == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert user.usage_period_ends_at == datetime(2026, 11, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Creator Annual: billed annually, allowance resets monthly                  #
# --------------------------------------------------------------------------- #


def test_creator_annual_receives_thirty_thousand_seconds(db_session):
    """1. Creator Annual receives 30,000 seconds, not a 12-month pool."""
    user = make_user(db_session, "annual@example.com", CREATOR_ANNUAL_PLAN_ID)

    snapshot = build_usage_snapshot(db_session, user, NOW)

    assert snapshot.monthly_processing_allowance_seconds == 30_000
    assert snapshot.processing_allowance_minutes == 500.0
    assert snapshot.processing_remaining_seconds == 30_000


def test_creator_annual_usage_survives_within_the_same_month(db_session):
    """2. Usage survives inside the same calendar month."""
    user = make_user(db_session, "annual@example.com", CREATOR_ANNUAL_PLAN_ID)
    user.processing_used_seconds = 12_345
    db_session.commit()

    later_in_month = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)
    assert ensure_current_usage_period(user, later_in_month) is False

    db_session.refresh(user)
    assert user.processing_used_seconds == 12_345
    assert build_usage_snapshot(db_session, user, later_in_month).processing_remaining_seconds == 17_655


def test_creator_annual_usage_resets_at_the_next_month(db_session):
    """3. Usage resets at the next monthly boundary."""
    user = make_user(db_session, "annual@example.com", CREATOR_ANNUAL_PLAN_ID)
    user.processing_used_seconds = 29_999
    db_session.commit()

    october = datetime(2026, 10, 1, 0, 1, tzinfo=timezone.utc)
    assert ensure_current_usage_period(user, october) is True

    assert user.processing_used_seconds == 0
    assert user.usage_period_started_at == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert user.usage_period_ends_at == datetime(2026, 11, 1, tzinfo=timezone.utc)

    snapshot = build_usage_snapshot(db_session, user, october)
    assert snapshot.processing_remaining_seconds == 30_000
    assert snapshot.processing_allowance_minutes == 500.0


def test_creator_annual_billing_status_is_independent_of_monthly_reset(db_session):
    """4. Annual Stripe billing and monthly usage reset are separate."""
    user = make_user(
        db_session,
        "annual@example.com",
        CREATOR_ANNUAL_PLAN_ID,
        subscription_status="active",
    )
    user.processing_used_seconds = 30_000  # exhausted this month
    db_session.commit()

    snapshot = build_usage_snapshot(db_session, user, NOW)

    # Billed annually...
    assert snapshot.billed_annually is True
    assert snapshot.subscription_status == "active"
    # ...but usage still resets every month.
    assert snapshot.usage_resets_monthly is True
    assert snapshot.usage_period_months == 1

    # Crossing a month boundary clears usage without touching the subscription.
    october = datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc)
    assert ensure_current_usage_period(user, october) is True

    # Usage is cleared...
    assert user.processing_used_seconds == 0
    # ...while the annual subscription is untouched by the usage rollover.
    assert user.subscription_status == "active"
    assert build_usage_snapshot(db_session, user, october).billed_annually is True
    assert build_usage_snapshot(db_session, user, october).processing_remaining_seconds == 30_000


def test_creator_annual_unused_minutes_do_not_roll_over(db_session):
    """5. Unused allowance is discarded, never accumulated."""
    user = make_user(db_session, "annual@example.com", CREATOR_ANNUAL_PLAN_ID)
    user.processing_used_seconds = 60  # 29940s unused
    db_session.commit()

    october = datetime(2026, 10, 1, 0, 1, tzinfo=timezone.utc)
    assert ensure_current_usage_period(user, october) is True

    snapshot = build_usage_snapshot(db_session, user, october)

    # A fresh month, back to exactly one allowance. Not 30,000 + 29,940.
    assert user.processing_used_seconds == 0
    assert snapshot.processing_remaining_seconds == 30_000
    assert snapshot.monthly_processing_allowance_seconds == 30_000


def test_creator_annual_keeps_paid_entitlements_after_usage_reset(db_session):
    """6. A usage reset never downgrades paid access."""
    user = make_user(
        db_session,
        "annual@example.com",
        CREATOR_ANNUAL_PLAN_ID,
        subscription_status="active",
    )
    user.processing_used_seconds = 30_000
    db_session.commit()

    october = datetime(2026, 10, 1, 0, 1, tzinfo=timezone.utc)
    assert ensure_current_usage_period(user, october) is True

    snapshot = build_usage_snapshot(db_session, user, october)

    assert snapshot.plan == CREATOR_ANNUAL_PLAN_ID
    assert snapshot.has_full_preview is True
    assert snapshot.can_export is True
    assert snapshot.preview_limit_seconds is None
    assert snapshot.is_paid_plan is True
    assert snapshot.processing_allowance_minutes == 500.0


def test_creator_annual_and_creator_monthly_have_identical_allowances(db_session):
    monthly = make_user(db_session, "cm@example.com", CREATOR_MONTHLY_PLAN_ID)
    annual = make_user(db_session, "ca@example.com", CREATOR_ANNUAL_PLAN_ID)

    monthly_snapshot = build_usage_snapshot(db_session, monthly, NOW)
    annual_snapshot = build_usage_snapshot(db_session, annual, NOW)

    assert monthly_snapshot.monthly_processing_allowance_seconds == annual_snapshot.monthly_processing_allowance_seconds
    assert monthly_snapshot.usage_period_ends_at == annual_snapshot.usage_period_ends_at
    # Only the billing cadence differs.
    assert annual_snapshot.billed_annually is True
    assert monthly_snapshot.billed_annually is False


def test_rollover_resets_usage_for_monthly(db_session):
    user = make_user(db_session, processing_used_seconds=500)
    assert ensure_current_usage_period(user, datetime(2026, 10, 5, tzinfo=timezone.utc)) is True
    assert user.processing_used_seconds == 0


def test_add_months_clamps_short_month():
    assert add_months(datetime(2026, 1, 31, tzinfo=timezone.utc), 1) == datetime(
        2026, 2, 28, tzinfo=timezone.utc
    )


def test_add_months_crosses_year():
    assert add_months(datetime(2026, 12, 15, tzinfo=timezone.utc), 1) == datetime(
        2027, 1, 15, tzinfo=timezone.utc
    )


def test_naive_datetimes_are_treated_as_utc(db_session):
    user = make_user(db_session)
    assert ensure_current_usage_period(user, datetime(2026, 9, 20)) is False
    assert ensure_current_usage_period(user, datetime(2026, 10, 20)) is True


# --- Snapshot ---


def test_snapshot_reports_free_plan(db_session):
    user = make_user(db_session, processing_used_seconds=192)
    snapshot = build_usage_snapshot(db_session, user, NOW)

    assert snapshot.plan == "free"
    assert snapshot.processing_used_seconds == 192
    assert snapshot.processing_remaining_seconds == 408
    assert snapshot.processing_used_minutes == 3.2
    # Free previews the finished video in full, like every other plan.
    assert snapshot.preview_limit_seconds is None
    assert snapshot.has_full_preview is True
    assert snapshot.can_export is True
    assert snapshot.is_paid_plan is False
    assert snapshot.usage_resets_monthly is True
    assert snapshot.billed_annually is False


def test_paid_snapshot_reports_full_preview_and_export(db_session):
    user = make_user(db_session, "creator@example.com", CREATOR_MONTHLY_PLAN_ID)
    snapshot = build_usage_snapshot(db_session, user, NOW)

    assert snapshot.plan == "creator_monthly"
    assert snapshot.plan_label == "Creator"
    assert snapshot.preview_limit_seconds is None
    assert snapshot.has_full_preview is True
    assert snapshot.can_export is True
    assert snapshot.is_paid_plan is True


def test_snapshot_includes_reserved_seconds(db_session):
    user = make_user(db_session)
    reserve_processing_seconds(db_session, user, 120, NOW)

    snapshot = build_usage_snapshot(db_session, user, NOW)

    assert snapshot.processing_reserved_seconds == 120
    assert snapshot.processing_used_seconds == 0
    assert snapshot.processing_remaining_seconds == 480


def test_apply_plan_seeds_entitlements(db_session):
    user = make_user(db_session, plan_id=CREATOR_ANNUAL_PLAN_ID, subscription_status="")
    apply_plan_to_user(user)

    assert user.plan == CREATOR_ANNUAL_PLAN_ID
    # 500 minutes per month, even though billing is annual.
    assert user.monthly_processing_allowance_seconds == 30_000
    assert user.preview_limit_seconds is None
    assert user.has_full_preview is True
    assert user.can_export is True


def test_apply_plan_falls_back_to_free_for_unknown(db_session):
    """An unknown plan id lands on free, and never on paid capacity."""
    user = make_user(db_session, plan_id="enterprise_unknown")
    apply_plan_to_user(user, "enterprise_unknown")

    assert user.plan == "free"
    # Capabilities match free, which every plan has.
    assert user.can_export is True
    assert user.has_full_preview is True
    assert user.preview_limit_seconds is None
    # Capacity is the free allowance, not an unknown plan's.
    assert user.monthly_processing_allowance_seconds == 600


def test_seconds_and_minutes_formatting():
    assert seconds_to_minutes(192) == 3.2
    assert seconds_to_minutes(0) == 0.0
    assert seconds_to_minutes(None) == 0.0

    assert format_minutes(90) == "1.5 minutes"
    assert format_minutes(600) == "10 minutes"
    assert format_minutes(30_000) == "500 minutes"
    assert format_minutes(360_000) == "6,000 minutes"
    assert format_minutes(0) == "0 minutes"


def test_reservations_are_attributable_to_a_user(db_session):
    user = make_user(db_session)
    reservation = reserve_processing_seconds(db_session, user, 60, NOW)

    rows = db_session.scalars(
        select(UsageReservation).where(UsageReservation.user_id == user.id)
    ).all()

    assert len(rows) == 1
    assert rows[0].id == reservation.reservation_id
    assert rows[0].reserved_seconds == 60
    assert rows[0].status == "reserved"
