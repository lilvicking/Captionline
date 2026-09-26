"""Tests for plans, usage periods, and entitlement calculation.

Pure logic, no database or HTTP required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import User
from app.plans import FREE_PLAN, SUBSCRIPTION_NONE, get_plan
from app.usage import (
    add_month,
    apply_plan_to_user,
    build_usage_snapshot,
    ensure_current_usage_period,
    monthly_period_start,
    record_processing_seconds,
    seconds_to_minutes,
)


def make_user(**overrides) -> User:
    now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    defaults = dict(
        id=1,
        email="test@example.com",
        password_hash="x",
        plan="free",
        subscription_status=SUBSCRIPTION_NONE,
        monthly_processing_allowance_seconds=FREE_PLAN.monthly_processing_seconds,
        processing_used_seconds=0,
        usage_period_started_at=monthly_period_start(now),
        usage_period_ends_at=add_month(monthly_period_start(now), 1),
        preview_limit_seconds=FREE_PLAN.preview_limit_seconds,
        has_full_preview=FREE_PLAN.has_full_preview,
        can_export=FREE_PLAN.can_export,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return User(**defaults)


# --- Free plan defaults ---


def test_free_plan_is_ten_minutes_and_thirty_second_preview():
    assert FREE_PLAN.monthly_processing_seconds == 600
    assert FREE_PLAN.preview_limit_seconds == 30
    assert FREE_PLAN.has_full_preview is False
    assert FREE_PLAN.can_export is False
    assert FREE_PLAN.subscription_status == SUBSCRIPTION_NONE


def test_get_plan_falls_back_to_free_for_unknown_ids():
    # An unrecognised plan must never grant broader access than free.
    assert get_plan("enterprise-unknown").id == "free"
    assert get_plan(None).id == "free"
    assert get_plan("free").id == "free"


def test_apply_plan_seeds_all_entitlement_columns():
    user = make_user(plan="free", subscription_status="")
    apply_plan_to_user(user)

    assert user.monthly_processing_allowance_seconds == 600
    assert user.preview_limit_seconds == 30
    assert user.has_full_preview is False
    assert user.can_export is False
    assert user.subscription_status == SUBSCRIPTION_NONE


# --- Usage period maths ---


def test_monthly_period_start_is_first_of_month_utc():
    start = monthly_period_start(datetime(2026, 9, 26, 13, 45, tzinfo=timezone.utc))
    assert start == datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_add_month_clamps_to_last_valid_day():
    # 31 January plus one month must land on 28/29 February, not crash.
    jan31 = datetime(2026, 1, 31, tzinfo=timezone.utc)
    assert add_month(jan31, 1) == datetime(2026, 2, 28, tzinfo=timezone.utc)


def test_add_month_crosses_year_boundary():
    dec = datetime(2026, 12, 15, tzinfo=timezone.utc)
    assert add_month(dec, 1) == datetime(2027, 1, 15, tzinfo=timezone.utc)


def test_period_does_not_roll_over_before_it_ends():
    user = make_user(
        usage_period_started_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        usage_period_ends_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        processing_used_seconds=120,
    )

    rolled = ensure_current_usage_period(user, datetime(2026, 9, 26, tzinfo=timezone.utc))

    assert rolled is False
    assert user.processing_used_seconds == 120


def test_period_rolls_over_and_resets_usage():
    user = make_user(
        usage_period_started_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        usage_period_ends_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        processing_used_seconds=500,
    )

    rolled = ensure_current_usage_period(user, datetime(2026, 10, 5, tzinfo=timezone.utc))

    assert rolled is True
    assert user.processing_used_seconds == 0
    assert user.usage_period_started_at == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert user.usage_period_ends_at == datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_naive_datetimes_are_treated_as_utc():
    # SQLite returns naive datetimes; comparisons must still work.
    user = make_user(
        usage_period_started_at=datetime(2026, 9, 1),
        usage_period_ends_at=datetime(2026, 10, 1),
    )

    assert ensure_current_usage_period(user, datetime(2026, 9, 26)) is False
    assert ensure_current_usage_period(user, datetime(2026, 10, 2)) is True


# --- Usage snapshot ---


def test_snapshot_reports_free_plan_allowance_in_seconds_and_minutes():
    snapshot = build_usage_snapshot(make_user(processing_used_seconds=192))

    assert snapshot.plan == "free"
    assert snapshot.monthly_processing_allowance_seconds == 600
    assert snapshot.processing_used_seconds == 192
    assert snapshot.processing_remaining_seconds == 408
    assert snapshot.processing_allowance_minutes == 10.0
    assert snapshot.processing_used_minutes == 3.2
    assert snapshot.processing_remaining_minutes == 6.8
    assert snapshot.preview_limit_seconds == 30
    assert snapshot.has_full_preview is False
    assert snapshot.can_export is False


def test_snapshot_clamps_remaining_at_zero_when_over_allowance():
    snapshot = build_usage_snapshot(make_user(processing_used_seconds=9999))

    assert snapshot.processing_remaining_seconds == 0
    assert snapshot.processing_remaining_minutes == 0.0


def test_record_processing_seconds_accumulates_in_seconds():
    user = make_user(processing_used_seconds=10)

    assert record_processing_seconds(user, 15) == 25
    # Non-positive values are ignored rather than crediting time back.
    assert record_processing_seconds(user, 0) == 25
    assert record_processing_seconds(user, -5) == 25


def test_seconds_to_minutes_rounds_to_one_decimal():
    assert seconds_to_minutes(192) == 3.2
    assert seconds_to_minutes(0) == 0.0
    assert seconds_to_minutes(None) == 0.0


def test_full_preview_entitlement_is_representable():
    # A future paid plan must be expressible without changing the model.
    user = make_user(
        plan="free",
        preview_limit_seconds=None,
        has_full_preview=True,
        can_export=True,
    )
    snapshot = build_usage_snapshot(user)

    assert snapshot.preview_limit_seconds is None
    assert snapshot.has_full_preview is True
    assert snapshot.can_export is True


@pytest.mark.parametrize("used,expected_remaining", [(0, 600), (300, 300), (600, 0), (601, 0)])
def test_remaining_is_never_negative(used, expected_remaining):
    snapshot = build_usage_snapshot(make_user(processing_used_seconds=used))
    assert snapshot.processing_remaining_seconds == expected_remaining


def test_usage_period_is_one_month_long():
    user = make_user()
    snapshot = build_usage_snapshot(user)
    delta = snapshot.usage_period_ends_at - snapshot.usage_period_started_at
    assert timedelta(days=27) < delta <= timedelta(days=32)
