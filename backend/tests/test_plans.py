"""Tests for the plan catalogue and entitlement fallbacks.

Pure logic, no database or HTTP required.
"""

from __future__ import annotations

import pytest

from app.plans import (
    CREATOR_ANNUAL,
    CREATOR_ANNUAL_PLAN_ID,
    CREATOR_MONTHLY,
    CREATOR_MONTHLY_PLAN_ID,
    FREE_PLAN,
    FREE_PLAN_ID,
    PLANS,
    PRO_MONTHLY,
    PRO_MONTHLY_PLAN_ID,
    PURCHASABLE_PLAN_IDS,
    STRIPE_PRICE_ENV_VARS,
    get_plan,
    has_active_paid_subscription,
    is_paid_plan,
    plan_for_price_id,
    register_price_mapping,
    reset_price_mapping,
)
from app.plans import SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELED, SUBSCRIPTION_PAST_DUE


# --- Free plan ---


def test_free_plan_definition():
    assert FREE_PLAN.price_usd == 0
    assert FREE_PLAN.usage_allowance_seconds == 600
    assert FREE_PLAN.preview_limit_seconds == 30
    assert FREE_PLAN.has_full_preview is False
    assert FREE_PLAN.can_export is False
    assert FREE_PLAN.paid is False
    assert FREE_PLAN.usage_period_months == 1


# --- Paid plans ---


def test_creator_monthly_definition():
    assert CREATOR_MONTHLY.price_usd == 19
    assert CREATOR_MONTHLY.usage_allowance_seconds == 30_000
    assert CREATOR_MONTHLY.usage_allowance_seconds / 60 == 500
    assert CREATOR_MONTHLY.preview_limit_seconds is None
    assert CREATOR_MONTHLY.has_full_preview is True
    assert CREATOR_MONTHLY.can_export is True
    assert CREATOR_MONTHLY.paid is True
    assert CREATOR_MONTHLY.billing_period == "monthly"


def test_pro_monthly_definition():
    assert PRO_MONTHLY.price_usd == 39
    assert PRO_MONTHLY.usage_allowance_seconds == 90_000
    assert PRO_MONTHLY.usage_allowance_seconds / 60 == 1_500
    assert PRO_MONTHLY.has_full_preview is True
    assert PRO_MONTHLY.can_export is True


def test_creator_annual_is_billed_annually_but_resets_usage_monthly():
    """Billing cadence and usage cadence are separate concerns.

    The customer pays $190 once a year, yet gets the same 500-minute monthly
    allowance as Creator Monthly, refreshing every month.
    """
    assert CREATOR_ANNUAL.price_usd == 190
    assert CREATOR_ANNUAL.billing_period == "annual"
    assert CREATOR_ANNUAL.is_annual_billing is True

    # Usage is monthly, not a 12-month pool.
    assert CREATOR_ANNUAL.usage_allowance_seconds == 30_000
    assert CREATOR_ANNUAL.usage_allowance_seconds == CREATOR_MONTHLY.usage_allowance_seconds
    assert CREATOR_ANNUAL.usage_period_months == 1
    assert CREATOR_ANNUAL.usage_resets_monthly is True

    # Explicitly not an annual pool.
    assert CREATOR_ANNUAL.usage_allowance_seconds != 360_000
    assert CREATOR_ANNUAL.usage_allowance_minutes == 500.0


def test_creator_annual_savings():
    # $19 x 12 = $228, minus $190 = $38 saved per year.
    assert CREATOR_ANNUAL.monthly_equivalent_price_usd == CREATOR_MONTHLY.price_usd == 19
    assert CREATOR_ANNUAL.annual_savings_usd == 38
    assert CREATOR_ANNUAL.annual_savings_usd == CREATOR_MONTHLY.price_usd * 12 - CREATOR_ANNUAL.price_usd


def test_every_plan_resets_usage_monthly():
    for plan in PLANS.values():
        assert plan.usage_period_months == 1, f"{plan.id} should reset monthly"
        assert plan.usage_resets_monthly is True


def test_only_the_annual_plan_is_billed_annually():
    annual = [plan.id for plan in PLANS.values() if plan.is_annual_billing]
    assert annual == ["creator_annual"]


def test_monthly_plans_report_no_savings():
    assert CREATOR_MONTHLY.annual_savings_usd == 0
    assert PRO_MONTHLY.annual_savings_usd == 0
    assert FREE_PLAN.annual_savings_usd == 0


# --- Plan ids and lookup ---


def test_plan_ids_are_stable_and_machine_friendly():
    assert FREE_PLAN.id == FREE_PLAN_ID == "free"
    assert CREATOR_MONTHLY.id == CREATOR_MONTHLY_PLAN_ID == "creator_monthly"
    assert PRO_MONTHLY.id == PRO_MONTHLY_PLAN_ID == "pro_monthly"
    assert CREATOR_ANNUAL.id == CREATOR_ANNUAL_PLAN_ID == "creator_annual"


def test_catalogue_contains_exactly_four_plans():
    assert set(PLANS) == {"free", "creator_monthly", "pro_monthly", "creator_annual"}
    assert [plan.id for plan in PLANS.values()] == [
        "free",
        "creator_monthly",
        "pro_monthly",
        "creator_annual",
    ]


@pytest.mark.parametrize("unknown", [None, "", "enterprise", "creator", "FREE", "free_v2"])
def test_unknown_plan_fails_closed_to_free(unknown):
    resolved = get_plan(unknown)

    assert resolved.id == "free"
    assert resolved.paid is False
    assert resolved.can_export is False
    assert resolved.has_full_preview is False
    assert resolved.usage_allowance_seconds == 600


def test_is_paid_plan():
    assert is_paid_plan("creator_monthly") is True
    assert is_paid_plan("pro_monthly") is True
    assert is_paid_plan("creator_annual") is True
    assert is_paid_plan("free") is False
    assert is_paid_plan("nonexistent") is False


def test_purchasable_plans_exclude_free():
    assert FREE_PLAN_ID not in PURCHASABLE_PLAN_IDS
    assert set(PURCHASABLE_PLAN_IDS) == {
        "creator_monthly",
        "pro_monthly",
        "creator_annual",
    }


# --- Stripe price mapping ---


def test_every_purchasable_plan_has_a_price_env_var():
    for plan_id in PURCHASABLE_PLAN_IDS:
        assert plan_id in STRIPE_PRICE_ENV_VARS
        assert STRIPE_PRICE_ENV_VARS[plan_id].startswith("STRIPE_PRICE_")


def test_price_mapping_round_trip():
    reset_price_mapping()
    try:
        register_price_mapping("test-price-creator", CREATOR_MONTHLY_PLAN_ID)
        assert plan_for_price_id("test-price-creator").id == "creator_monthly"
    finally:
        reset_price_mapping()


def test_unset_price_id_is_not_registered():
    reset_price_mapping()
    register_price_mapping(None, PRO_MONTHLY_PLAN_ID)
    register_price_mapping("", PRO_MONTHLY_PLAN_ID)
    assert plan_for_price_id(None) is None
    assert plan_for_price_id("") is None
    reset_price_mapping()


def test_unknown_price_id_grants_nothing():
    """A price Stripe knows but we do not must not map to a plan."""
    reset_price_mapping()
    register_price_mapping("test-price-known", CREATOR_MONTHLY_PLAN_ID)
    try:
        assert plan_for_price_id("test-price-unknown") is None
        assert plan_for_price_id("test-price-from-another-account") is None
    finally:
        reset_price_mapping()


# --- Subscription status ---


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_active_statuses_grant_paid(status):
    assert has_active_paid_subscription(status) is True


@pytest.mark.parametrize(
    "status", ["canceled", "past_due", "unpaid", "incomplete", "none", "", None, "ACTIVE"]
)
def test_inactive_statuses_do_not_grant_paid(status):
    assert has_active_paid_subscription(status) is False


def test_status_constants():
    assert SUBSCRIPTION_ACTIVE == "active"
    assert SUBSCRIPTION_CANCELED == "canceled"
    assert SUBSCRIPTION_PAST_DUE == "past_due"

