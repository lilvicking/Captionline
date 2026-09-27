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


# --- Free export entitlement (the condition behind the editor paywall) -------
#
# The editor decides between "Export video" and the paywall purely on
# `can_export`, so this is the property that must hold for Free. The migration
# test below covers accounts that already existed before the rule changed.


def test_free_account_receives_can_export_true(client):
    token = client.post(
        "/api/auth/register", json={"email": "free-export@example.com", "password": "a-strong-password-123"}
    ).json()["access_token"]

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert entitlement["plan"] == "free"
    assert entitlement["can_export"] is True


def test_a_free_account_row_stale_from_before_the_rule_change_is_corrected(client, db_session):
    """An existing Free account must not keep the old paywall entitlement.

    Reproduces the production report: the account row still holds
    `can_export = false` because entitlements are copied at registration, so the
    editor shows the paywall for a capability every plan now has.
    """
    from sqlalchemy import text

    token = client.post(
        "/api/auth/register", json={"email": "stale@example.com", "password": "a-strong-password-123"}
    ).json()["access_token"]

    # Put the row back the way an old account would look.
    db_session.execute(
        text("UPDATE users SET can_export = 0, has_full_preview = 0, preview_limit_seconds = 30 WHERE email = :e"),
        {"e": "stale@example.com"},
    )
    db_session.commit()

    stale = client.get("/api/account/entitlement", headers=auth_header(token)).json()
    assert stale["can_export"] is False  # the paywall condition, reproduced

    # The corrective migration is what repairs this in production.
    from app.usage import resync_entitlements

    resync_entitlements(db_session)

    repaired = client.get("/api/account/entitlement", headers=auth_header(token)).json()
    assert repaired["can_export"] is True
    assert repaired["has_full_preview"] is True
    assert repaired["preview_limit_seconds"] is None


def test_migration_matches_catalogue():
    """The migration carries literal values, so they must not drift.

    A migration cannot import application code that may change shape later, so
    0006 keeps its own copy of the plan entitlements. This asserts the copy still
    matches `app/plans.py`, which is what makes the resync correct.
    """
    import importlib.util
    import pathlib

    from app.plans import PLANS

    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0006_admin_credits.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0006", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from_migration = {
        plan_id: values
        for plan_id, values in module.PLAN_ENTITLEMENTS.items()
    }
    from_catalogue = {
        plan_id: (
            plan.usage_allowance_seconds,
            plan.has_full_preview,
            plan.can_export,
        )
        for plan_id, plan in PLANS.items()
    }

    assert from_migration == from_catalogue


def test_migration_revision_id_fits_the_alembic_version_column():
    """Guards the deployment failure caused by an over-length revision id."""
    import importlib.util
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0006_admin_credits.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0006_len", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # alembic_version.version_num is VARCHAR(32) on the production database.
    assert len(module.revision) <= 32
    assert module.down_revision == "0005_rate_limit_buckets"
