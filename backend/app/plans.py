"""Captionline plan catalog.

Single source of truth for pricing, allowances, and entitlements. Nothing in the
backend should hardcode a number that also appears here, and the frontend never
supplies plan information: it renders what the backend reports.

## Billing cadence is not usage cadence

`billing_period` is the Stripe billing cadence: how often the customer is charged.
`usage_period_months` is how often the processing allowance resets. These are
deliberately independent.

`creator_annual` is the case that matters: the customer is charged $190 **once a
year** by Stripe, but their 500-minute allowance still **resets every month**, the
same as Creator Monthly. Buying a year does not buy twelve months up front, and
unused minutes do not roll over into the next month.
"""

from __future__ import annotations

from dataclasses import dataclass

FREE_PLAN_ID = "free"
CREATOR_MONTHLY_PLAN_ID = "creator_monthly"
PRO_MONTHLY_PLAN_ID = "pro_monthly"
CREATOR_ANNUAL_PLAN_ID = "creator_annual"

# Subscription status values mirrored on the user row.
SUBSCRIPTION_NONE = "none"
SUBSCRIPTION_ACTIVE = "active"
SUBSCRIPTION_TRIALING = "trialing"
SUBSCRIPTION_PAST_DUE = "past_due"
SUBSCRIPTION_CANCELED = "canceled"
SUBSCRIPTION_INCOMPLETE = "incomplete"
SUBSCRIPTION_UNPAID = "unpaid"

#: Statuses that grant paid access. Anything else is treated as not paid.
ACTIVE_SUBSCRIPTION_STATUSES = frozenset(
    {SUBSCRIPTION_ACTIVE, SUBSCRIPTION_TRIALING}
)

#: Stripe billing cadences.
BILLING_MONTHLY = "monthly"
BILLING_ANNUAL = "annual"

#: Name of the environment variable that holds the Stripe Price ID per plan.
# The values themselves are never stored in this repository.
STRIPE_PRICE_ENV_VARS: dict[str, str] = {
    CREATOR_MONTHLY_PLAN_ID: "STRIPE_PRICE_CREATOR_MONTHLY",
    PRO_MONTHLY_PLAN_ID: "STRIPE_PRICE_PRO_MONTHLY",
    CREATOR_ANNUAL_PLAN_ID: "STRIPE_PRICE_CREATOR_ANNUAL",
}


@dataclass(frozen=True)
class PlanDefinition:
    """Immutable commercial definition of a plan."""

    id: str
    label: str

    # --- Pricing / billing (when the customer is charged) ---
    price_usd: int
    billing_period: str  # BILLING_MONTHLY or BILLING_ANNUAL
    #: What the same plan would cost per month on monthly billing. Used to show
    #: the saving on annual plans. Equal to `price_usd` for monthly plans.
    monthly_equivalent_price_usd: int
    #: Saving per year versus monthly billing. 0 when there is no saving.
    annual_savings_usd: int

    # --- Usage (when the allowance resets) ---
    #: Processing allowance granted per usage period, in seconds.
    usage_allowance_seconds: int
    #: Length of a usage period in months. Every plan resets monthly, including
    #: the annually billed one.
    usage_period_months: int

    # --- Entitlements ---
    preview_limit_seconds: int | None
    has_full_preview: bool
    can_export: bool
    paid: bool
    tagline: str
    sort_order: int

    @property
    def is_annual_billing(self) -> bool:
        """True when Stripe charges annually. Unrelated to usage reset."""
        return self.billing_period == BILLING_ANNUAL

    @property
    def usage_resets_monthly(self) -> bool:
        return self.usage_period_months == 1

    @property
    def usage_allowance_minutes(self) -> float:
        return self.usage_allowance_seconds / 60.0


FREE_PLAN = PlanDefinition(
    id=FREE_PLAN_ID,
    label="Free",
    price_usd=0,
    billing_period=BILLING_MONTHLY,
    monthly_equivalent_price_usd=0,
    annual_savings_usd=0,
    usage_allowance_seconds=600,  # 10 minutes per month
    usage_period_months=1,
    preview_limit_seconds=30,
    has_full_preview=False,
    can_export=False,
    paid=False,
    tagline="10 processing minutes a month, 30-second finished preview",
    sort_order=0,
)

CREATOR_MONTHLY = PlanDefinition(
    id=CREATOR_MONTHLY_PLAN_ID,
    label="Creator",
    price_usd=19,
    billing_period=BILLING_MONTHLY,
    monthly_equivalent_price_usd=19,
    annual_savings_usd=0,
    usage_allowance_seconds=30_000,  # 500 minutes per month
    usage_period_months=1,
    preview_limit_seconds=None,  # unrestricted
    has_full_preview=True,
    can_export=True,
    paid=True,
    tagline="500 processing minutes a month, full preview and export",
    sort_order=1,
)

PRO_MONTHLY = PlanDefinition(
    id=PRO_MONTHLY_PLAN_ID,
    label="Pro",
    price_usd=39,
    billing_period=BILLING_MONTHLY,
    monthly_equivalent_price_usd=39,
    annual_savings_usd=0,
    usage_allowance_seconds=90_000,  # 1,500 minutes per month
    usage_period_months=1,
    preview_limit_seconds=None,
    has_full_preview=True,
    can_export=True,
    paid=True,
    tagline="1,500 processing minutes a month, full preview and export",
    sort_order=2,
)

# Charged once a year by Stripe, but the allowance still resets every month and is
# the same 500 minutes as Creator Monthly. Unused minutes do not roll over.
CREATOR_ANNUAL = PlanDefinition(
    id=CREATOR_ANNUAL_PLAN_ID,
    label="Creator Annual",
    price_usd=190,
    billing_period=BILLING_ANNUAL,
    monthly_equivalent_price_usd=19,  # what Creator Monthly would cost monthly
    annual_savings_usd=19 * 12 - 190,  # 38
    usage_allowance_seconds=30_000,  # 500 minutes per month, not per year
    usage_period_months=1,
    preview_limit_seconds=None,
    has_full_preview=True,
    can_export=True,
    paid=True,
    tagline="500 processing minutes a month, billed annually",
    sort_order=3,
)

PLANS: dict[str, PlanDefinition] = {
    plan.id: plan
    for plan in sorted(
        (FREE_PLAN, CREATOR_MONTHLY, PRO_MONTHLY, CREATOR_ANNUAL),
        key=lambda p: p.sort_order,
    )
}

DEFAULT_PLAN = FREE_PLAN

#: Plan ids that can be purchased, in pricing-table order.
PURCHASABLE_PLAN_IDS: tuple[str, ...] = (
    CREATOR_MONTHLY_PLAN_ID,
    PRO_MONTHLY_PLAN_ID,
    CREATOR_ANNUAL_PLAN_ID,
)

#: Stripe Price ID -> internal plan id. Built at runtime from the environment so
#: no Stripe identifier is ever committed.
PRICE_ID_TO_PLAN_ID: dict[str, str] = {}


def register_price_mapping(price_id: str | None, plan_id: str) -> None:
    """Record a Stripe Price ID -> plan mapping, ignoring unset values."""
    if price_id:
        PRICE_ID_TO_PLAN_ID[price_id] = plan_id


def reset_price_mapping() -> None:
    """Clear the runtime mapping. Used by tests."""
    PRICE_ID_TO_PLAN_ID.clear()


def get_plan(plan_id: str | None) -> PlanDefinition:
    """Look up a plan, falling back to free for unknown or missing ids.

    Falling back keeps an unrecognised plan from granting broader access than the
    viewer is entitled to.
    """
    if not plan_id:
        return DEFAULT_PLAN
    return PLANS.get(plan_id, DEFAULT_PLAN)


def is_paid_plan(plan_id: str | None) -> bool:
    return get_plan(plan_id).paid


def plan_for_price_id(price_id: str | None) -> PlanDefinition | None:
    """Resolve a Stripe Price ID to a plan, or None when it is not mapped.

    An unmapped price grants nothing: the caller must fall back to Free.
    """
    if not price_id:
        return None

    plan_id = PRICE_ID_TO_PLAN_ID.get(price_id)
    if plan_id is None:
        return None

    return PLANS.get(plan_id)


def has_active_paid_subscription(subscription_status: str | None) -> bool:
    """Whether a mirrored Stripe status grants paid access.

    Stripe is the authority: a local status the backend did not learn from a
    verified webhook must not be treated as paid.
    """
    if not subscription_status:
        return False
    return subscription_status in ACTIVE_SUBSCRIPTION_STATUSES
