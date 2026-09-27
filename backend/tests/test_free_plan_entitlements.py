"""The clarified Free plan: full capabilities, smaller monthly allowance.

Free is no longer a degraded tier. It previews the finished video in full and
carries the finished-captioned-video export entitlement, exactly like every
paid plan. The only thing that distinguishes the plans is how much video can be
processed each month.

These tests exist so the old 30-second Free preview and the paid-only export
entitlement cannot come back by accident, and so the metering that replaced them
keeps working.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import User
from app.plans import (
    CREATOR_ANNUAL,
    CREATOR_ANNUAL_PLAN_ID,
    CREATOR_MONTHLY,
    CREATOR_MONTHLY_PLAN_ID,
    FREE_PLAN,
    FREE_PLAN_ID,
    PRO_MONTHLY,
    PRO_MONTHLY_PLAN_ID,
    get_plan,
)
from app.usage import (
    AllowanceExceededError,
    build_usage_snapshot,
    ensure_current_usage_period,
    reserve_processing_seconds,
)
from tests.conftest import auth_header
from test_usage_accounting import make_user  # noqa: F401  (reuses the fixture helper)

EMAIL = "free-user@example.com"
PASSWORD = "a-strong-password-123"


# --- Allowance per plan -----------------------------------------------------


@pytest.mark.parametrize(
    "plan_id,expected_seconds",
    [
        (FREE_PLAN_ID, 600),  # 10 minutes
        (CREATOR_MONTHLY_PLAN_ID, 30_000),  # 500 minutes
        (PRO_MONTHLY_PLAN_ID, 90_000),  # 1,500 minutes
        (CREATOR_ANNUAL_PLAN_ID, 30_000),  # 500 minutes per MONTH
    ],
)
def test_allowance_seconds_per_plan(plan_id, expected_seconds):
    assert get_plan(plan_id).usage_allowance_seconds == expected_seconds


def test_creator_annual_is_500_minutes_per_month_not_an_annual_pool():
    """The annual plan is billed annually and metered monthly."""
    assert CREATOR_ANNUAL.billing_period == "annual"
    assert CREATOR_ANNUAL.usage_period_months == 1
    assert CREATOR_ANNUAL.usage_allowance_seconds == 30_000
    # Explicitly not a 6,000-minute pool.
    assert CREATOR_ANNUAL.usage_allowance_seconds != 360_000
    # Same monthly capacity as Creator Monthly, at a lower annual price.
    assert CREATOR_ANNUAL.usage_allowance_seconds == CREATOR_MONTHLY.usage_allowance_seconds
    assert CREATOR_ANNUAL.annual_savings_usd == 79


def test_commercial_values_are_unchanged():
    assert FREE_PLAN.price_usd == 0
    assert CREATOR_MONTHLY.price_usd == 19
    assert PRO_MONTHLY.price_usd == 39
    assert CREATOR_ANNUAL.price_usd == 149


# --- Capabilities are identical across plans --------------------------------


@pytest.mark.parametrize(
    "plan_id",
    [FREE_PLAN_ID, CREATOR_MONTHLY_PLAN_ID, PRO_MONTHLY_PLAN_ID, CREATOR_ANNUAL_PLAN_ID],
)
def test_every_plan_previews_in_full(plan_id):
    plan = get_plan(plan_id)
    assert plan.preview_limit_seconds is None
    assert plan.has_full_preview is True


@pytest.mark.parametrize(
    "plan_id",
    [FREE_PLAN_ID, CREATOR_MONTHLY_PLAN_ID, PRO_MONTHLY_PLAN_ID, CREATOR_ANNUAL_PLAN_ID],
)
def test_every_plan_carries_export_entitlement(plan_id):
    assert get_plan(plan_id).can_export is True


def test_free_is_not_marked_paid_but_is_fully_capable():
    """'paid' still means "takes payment", not "has features"."""
    assert FREE_PLAN.paid is False
    assert FREE_PLAN.has_full_preview is True
    assert FREE_PLAN.can_export is True
    assert FREE_PLAN.usage_allowance_seconds == 600


# --- What the account endpoint reports ---------------------------------------


def test_free_account_reports_full_capabilities(client):
    token = client.post(
        "/api/auth/register", json={"email": EMAIL, "password": PASSWORD}
    ).json()["access_token"]

    body = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert body["plan"] == "free"
    assert body["is_paid_plan"] is False
    # Full finished preview: no limit.
    assert body["preview_limit_seconds"] is None
    assert body["has_full_preview"] is True
    # Export entitlement present.
    assert body["can_export"] is True
    # Only capacity is smaller.
    assert body["monthly_processing_allowance_seconds"] == 600
    assert body["usage_resets_monthly"] is True


def test_free_user_row_is_seeded_with_full_capabilities(client, db_session):
    client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})

    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()

    assert user.preview_limit_seconds is None
    assert user.has_full_preview is True
    assert user.can_export is True
    assert user.monthly_processing_allowance_seconds == 600


# --- Metering still works for Free ------------------------------------------


def test_free_user_can_process_within_the_allowance(client, db_session):
    """A 2-minute video fits inside the 10 free minutes."""
    client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()

    result = reserve_processing_seconds(db_session, user, 120)

    assert result.reserved_seconds == 120
    assert result.remaining_seconds == 480


def test_free_user_cannot_process_past_the_allowance(db_session):
    """Exhausting the allowance is still refused before any processing."""
    user = make_user(db_session, "metered@example.com", FREE_PLAN_ID, processing_used_seconds=480)

    with pytest.raises(AllowanceExceededError) as caught:
        reserve_processing_seconds(db_session, user, 121)

    assert caught.value.remaining_seconds == 120
    assert caught.value.required_seconds == 121
    assert "120 seconds of processing remaining" in caught.value.detail


def test_free_allowance_exhaustion_is_exact(client, db_session):
    """600 seconds is usable, 601 is not."""
    client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()

    assert reserve_processing_seconds(db_session, user, 600).remaining_seconds == 0

    with pytest.raises(AllowanceExceededError):
        reserve_processing_seconds(db_session, user, 1)


def test_free_usage_resets_monthly(db_session):
    user = make_user(
        db_session, "reset@example.com", FREE_PLAN_ID, processing_used_seconds=600
    )

    from datetime import datetime, timezone

    assert ensure_current_usage_period(user, datetime(2026, 10, 2, tzinfo=timezone.utc)) is True
    assert user.processing_used_seconds == 0
    assert build_usage_snapshot(db_session, user).processing_remaining_seconds == 600


def test_free_snapshot_never_reports_a_preview_limit(db_session):
    """Guards the specific regression this pass exists to remove."""
    user = make_user(db_session, "snap@example.com", FREE_PLAN_ID)
    snapshot = build_usage_snapshot(db_session, user)

    assert snapshot.preview_limit_seconds is None
    assert snapshot.has_full_preview is True
    assert snapshot.can_export is True


def test_paid_plans_still_beat_free_on_capacity_only(db_session):
    """The only difference between plans is monthly processing seconds."""
    free = build_usage_snapshot(
        db_session, make_user(db_session, "f@x.com", FREE_PLAN_ID)
    )
    creator = build_usage_snapshot(
        db_session, make_user(db_session, "c@x.com", CREATOR_MONTHLY_PLAN_ID)
    )
    pro = build_usage_snapshot(
        db_session, make_user(db_session, "p@x.com", PRO_MONTHLY_PLAN_ID)
    )

    assert free.monthly_processing_allowance_seconds < creator.monthly_processing_allowance_seconds
    assert creator.monthly_processing_allowance_seconds < pro.monthly_processing_allowance_seconds

    # Capabilities match exactly across all three.
    for snapshot in (free, creator, pro):
        assert snapshot.preview_limit_seconds is None
        assert snapshot.has_full_preview is True
        assert snapshot.can_export is True
        assert snapshot.usage_resets_monthly is True
