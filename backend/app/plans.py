"""Captionline plan definitions.

Single source of truth for plan limits and entitlements. Nothing in the backend
should hardcode a number that also appears here.

Stripe is not implemented. When it is, the paid tier will be added here and the
authoritative subscription state will be read from Stripe (see
`app/db/models.py` for how the mirrored columns are shaped for that).
"""

from __future__ import annotations

from dataclasses import dataclass

FREE_PLAN_ID = "free"

# Subscription status values mirrored on the user row.
SUBSCRIPTION_NONE = "none"
SUBSCRIPTION_ACTIVE = "active"
SUBSCRIPTION_CANCELED = "canceled"
SUBSCRIPTION_PAST_DUE = "past_due"


@dataclass(frozen=True)
class PlanDefinition:
    """Immutable limits for a plan."""

    id: str
    label: str
    #: Processing allowance per monthly usage period, in seconds.
    monthly_processing_seconds: int
    #: Seconds of finished-video preview. None means unrestricted.
    preview_limit_seconds: int | None
    has_full_preview: bool
    can_export: bool
    subscription_status: str


# The Captionline free plan: 10 processing minutes per month, a 30 second
# finished-video preview, and no export.
FREE_PLAN = PlanDefinition(
    id=FREE_PLAN_ID,
    label="Free",
    monthly_processing_seconds=10 * 60,
    preview_limit_seconds=30,
    has_full_preview=False,
    can_export=False,
    subscription_status=SUBSCRIPTION_NONE,
)

PLANS: dict[str, PlanDefinition] = {FREE_PLAN.id: FREE_PLAN}

DEFAULT_PLAN = FREE_PLAN


def get_plan(plan_id: str | None) -> PlanDefinition:
    """Look up a plan, falling back to free for unknown or missing ids.

    Falling back to free keeps an unrecognised plan from silently granting
    broader access than the viewer is entitled to.
    """
    if not plan_id:
        return DEFAULT_PLAN
    return PLANS.get(plan_id, DEFAULT_PLAN)
