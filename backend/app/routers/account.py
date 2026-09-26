"""Account and entitlement routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as OrmSession

from ..db.models import User
from ..db.session import get_db
from ..security.deps import get_current_user
from ..security.schemas import EntitlementResponse
from ..usage import build_usage_snapshot

router = APIRouter(prefix="/api/account", tags=["account"])


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
    snapshot = build_usage_snapshot(user)

    return EntitlementResponse(
        plan=snapshot.plan,
        plan_label=snapshot.plan_label,
        subscription_status=snapshot.subscription_status,
        monthly_processing_allowance_seconds=snapshot.monthly_processing_allowance_seconds,
        processing_used_seconds=snapshot.processing_used_seconds,
        processing_remaining_seconds=snapshot.processing_remaining_seconds,
        usage_period_started_at=snapshot.usage_period_started_at,
        usage_period_ends_at=snapshot.usage_period_ends_at,
        preview_limit_seconds=snapshot.preview_limit_seconds,
        has_full_preview=snapshot.has_full_preview,
        can_export=snapshot.can_export,
        processing_allowance_minutes=snapshot.processing_allowance_minutes,
        processing_used_minutes=snapshot.processing_used_minutes,
        processing_remaining_minutes=snapshot.processing_remaining_minutes,
    )
