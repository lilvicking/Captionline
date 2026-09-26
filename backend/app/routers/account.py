"""Account, entitlement, and public plan catalogue routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as OrmSession

from ..db.models import User
from ..db.session import get_db
from ..plans import PLANS, PURCHASABLE_PLAN_IDS
from ..security.deps import get_current_user, get_optional_user
from ..security.schemas import EntitlementResponse, PlanResponse
from ..stripe_client import is_billing_configured_for
from ..usage import build_usage_snapshot

router = APIRouter(prefix="/api/account", tags=["account"])


def _to_entitlement(snapshot) -> EntitlementResponse:
    return EntitlementResponse(
        plan=snapshot.plan,
        plan_label=snapshot.plan_label,
        subscription_status=snapshot.subscription_status,
        is_paid_plan=snapshot.is_paid_plan,
        monthly_processing_allowance_seconds=snapshot.monthly_processing_allowance_seconds,
        processing_used_seconds=snapshot.processing_used_seconds,
        processing_reserved_seconds=snapshot.processing_reserved_seconds,
        processing_remaining_seconds=snapshot.processing_remaining_seconds,
        usage_period_started_at=snapshot.usage_period_started_at,
        usage_period_ends_at=snapshot.usage_period_ends_at,
        usage_period_months=snapshot.usage_period_months,
        usage_resets_monthly=snapshot.usage_resets_monthly,
        billed_annually=snapshot.billed_annually,
        preview_limit_seconds=snapshot.preview_limit_seconds,
        has_full_preview=snapshot.has_full_preview,
        can_export=snapshot.can_export,
        processing_allowance_minutes=snapshot.processing_allowance_minutes,
        processing_used_minutes=snapshot.processing_used_minutes,
        processing_remaining_minutes=snapshot.processing_remaining_minutes,
    )


@router.get("/entitlement", response_model=EntitlementResponse)
def entitlement(
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> EntitlementResponse:
    """Server-computed plan, usage, and access state for the current account.

    Every value is derived from the authenticated user's database record. The
    client cannot influence it, which is the point: the frontend must never be
    the authority on what an account is entitled to.
    """
    return _to_entitlement(build_usage_snapshot(db, user))


@router.get("/plans", response_model=list[PlanResponse])
def plans(
    user: User | None = Depends(get_optional_user),
) -> list[PlanResponse]:
    """The authoritative plan catalogue, for rendering the pricing table.

    Public so the pricing page renders while signed out. Prices come from the
    backend catalogue, so the frontend never hardcodes them. `purchasable` reports
    whether Stripe is configured for that plan, letting the UI show a clear
    message instead of a dead button.
    """
    current_plan = user.plan if user is not None else None

    return [
        PlanResponse(
            id=plan.id,
            label=plan.label,
            price_usd=plan.price_usd,
            billing_period=plan.billing_period,
            monthly_equivalent_price_usd=plan.monthly_equivalent_price_usd,
            annual_savings_usd=plan.annual_savings_usd,
            usage_allowance_seconds=plan.usage_allowance_seconds,
            usage_period_months=plan.usage_period_months,
            usage_resets_monthly=plan.usage_resets_monthly,
            preview_limit_seconds=plan.preview_limit_seconds,
            has_full_preview=plan.has_full_preview,
            can_export=plan.can_export,
            tagline=plan.tagline,
            is_current=(plan.id == current_plan),
            purchasable=(
                plan.id in PURCHASABLE_PLAN_IDS and is_billing_configured_for(plan.id)
            ),
        )
        for plan in PLANS.values()
    ]
