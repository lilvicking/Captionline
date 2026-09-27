"""Administrative support console API.

For owner administration, customer support, and goodwill processing credit. Every
route depends on `require_admin`, which reads the durable `users.is_admin` column.
That column is only ever written from the `ADMIN_EMAILS` allow-list at startup,
so there is no client-controlled route to it, and no way for a signed-in user to
promote themselves.

Deliberately absent, because they turn routine support into account takeover:

* reading a customer's password hash, session token, or reset token
* setting a customer's password
* impersonating a customer or logging in as one
* spoofing a Stripe plan to grant processing time

The one lever this console has for usage is the bonus processing credit, which is
recorded in `admin_audit_log` and never touches a plan, a subscription, or Stripe.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession

from ..db.models import (
    ACTION_CREDIT_GRANTED,
    ACTION_CREDIT_REMOVED,
    AdminAuditEntry,
    User,
)
from ..db.session import get_db
from ..plans import get_plan
from ..security.deps import require_admin
from ..usage import build_usage_snapshot, ensure_current_usage_period, utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

#: Cap on a single credit adjustment, in seconds (24 hours of processing). A guard
#: against a fat-fingered value going unnoticed.
MAX_ADJUSTMENT_SECONDS = 86_400

#: Cap on search results, so a broad query cannot pull the customer table.
SEARCH_LIMIT = 25

#: Cap on the customer picker. Captionline's customer base is small, so a plain
#: list is fine, but the cap keeps the response bounded and `truncated` tells the
#: console to fall back to search once the list is no longer complete.
CUSTOMER_OPTION_LIMIT = 500

REASON_REQUIRED = "A reason is required for every adjustment."
REASON_TOO_LONG = "Please keep the reason under 280 characters."
NO_SUCH_USER = "No account matches that search."
CREDIT_WOULD_GO_NEGATIVE = "That adjustment would take the credit below zero."
ADJUSTMENT_TOO_LARGE = "That adjustment is larger than the maximum allowed."
NOT_A_USER = "That account does not exist."


# --- Request bodies ---------------------------------------------------------


class CreditAdjustmentRequest(BaseModel):
    """Grant or remove support credit.

    A negative `minutes` corrects a previous grant. The balance is never allowed
    to go below zero, and the reason is mandatory so every action is attributable.
    """

    model_config = {"extra": "forbid"}

    minutes: float = Field(description="Positive to grant, negative to remove.")
    reason: str = Field(min_length=3, max_length=280)


class AuditEntryResponse(BaseModel):
    id: int
    action: str
    amount_seconds: int
    reason: str
    created_at: datetime
    admin_user_id: int
    admin_email: str


class UserSummaryResponse(BaseModel):
    """Enough to identify an account in a search result, and nothing more."""

    id: int
    email: str
    plan: str
    subscription_status: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    bonus_processing_seconds: int


class UserDetailResponse(BaseModel):
    """Support view of one account.

    This is the *complete* field list. It contains no password hash, no session or
    reset tokens, and no payment data: the response is assembled here, field by
    field, so no accidental pass-through of the model can leak one.
    """

    id: int
    email: str
    plan: str
    plan_label: str
    subscription_status: str
    is_paid_plan: bool
    is_active: bool
    is_admin: bool
    created_at: datetime
    updated_at: datetime

    monthly_processing_allowance_seconds: int
    processing_used_seconds: int
    processing_reserved_seconds: int
    bonus_processing_seconds: int
    processing_remaining_seconds: int

    usage_period_started_at: datetime
    usage_period_ends_at: datetime
    usage_resets_monthly: bool
    billed_annually: bool

    has_full_preview: bool
    can_export: bool

    processing_allowance_minutes: float
    processing_used_minutes: float
    processing_remaining_minutes: float

    terms_accepted_at: datetime | None
    privacy_acknowledged_at: datetime | None


class AdminSummaryResponse(BaseModel):
    total_users: int
    free_users: int
    paid_users: int
    users_with_credit: int
    total_bonus_seconds: int


class CustomerOption(BaseModel):
    """The minimum needed to populate a picker.

    Deliberately only an id and an email. No plan, usage, entitlement, or billing
    data: those belong in the detail endpoint, which is fetched once a customer has
    actually been chosen.
    """

    id: int
    email: str


class CustomerOptionsResponse(BaseModel):
    options: list[CustomerOption]
    #: True when the cap was reached, so the UI can point at search instead.
    truncated: bool
    limit: int


# --- Helpers ----------------------------------------------------------------


def _require_user(db: OrmSession, user_id: int) -> User:
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(status_code=404, detail=NOT_A_USER)

    return user


def _detail_for(db: OrmSession, user: User) -> UserDetailResponse:
    snapshot = build_usage_snapshot(db, user)
    plan = get_plan(user.plan)

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        plan=user.plan,
        plan_label=plan.label,
        subscription_status=user.subscription_status,
        is_paid_plan=plan.paid,
        is_active=user.is_active,
        is_admin=bool(user.is_admin),
        created_at=user.created_at,
        updated_at=user.updated_at,
        monthly_processing_allowance_seconds=snapshot.monthly_processing_allowance_seconds,
        processing_used_seconds=snapshot.processing_used_seconds,
        processing_reserved_seconds=snapshot.processing_reserved_seconds,
        bonus_processing_seconds=snapshot.bonus_processing_seconds,
        processing_remaining_seconds=snapshot.processing_remaining_seconds,
        usage_period_started_at=snapshot.usage_period_started_at,
        usage_period_ends_at=snapshot.usage_period_ends_at,
        usage_resets_monthly=snapshot.usage_resets_monthly,
        billed_annually=snapshot.billed_annually,
        has_full_preview=snapshot.has_full_preview,
        can_export=snapshot.can_export,
        processing_allowance_minutes=snapshot.processing_allowance_minutes,
        processing_used_minutes=snapshot.processing_used_minutes,
        processing_remaining_minutes=snapshot.processing_remaining_minutes,
        terms_accepted_at=user.terms_accepted_at,
        privacy_acknowledged_at=user.privacy_acknowledged_at,
    )


# --- Routes -----------------------------------------------------------------


@router.get("/summary", response_model=AdminSummaryResponse)
def admin_summary(
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
) -> AdminSummaryResponse:
    """A few counts to orient an administrator."""
    del admin
    total = db.scalar(select(func.count()).select_from(User)) or 0
    free = db.scalar(
        select(func.count()).select_from(User).where(User.plan == "free")
    ) or 0
    with_credit = db.scalar(
        select(func.count()).select_from(User).where(User.bonus_processing_seconds > 0)
    ) or 0
    total_bonus = (
        db.scalar(select(func.coalesce(func.sum(User.bonus_processing_seconds), 0)))
        or 0
    )

    return AdminSummaryResponse(
        total_users=total,
        free_users=free,
        paid_users=total - free,
        users_with_credit=with_credit,
        total_bonus_seconds=int(total_bonus),
    )


@router.get("/customer-options", response_model=CustomerOptionsResponse)
def customer_options(
    response: Response,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
) -> CustomerOptionsResponse:
    """Every account's id and email, for the console's customer picker.

    Admin-only, because it enumerates addresses. The search endpoint cannot serve
    this: it requires a query term, matches loosely, and is capped for a different
    purpose.

    Two limits keep this safe as the customer base grows. The list is capped, and
    when the cap is reached `truncated` is true so the UI can fall back to search
    rather than pretending the list is complete.
    """
    del admin

    # Ordering is case-insensitive so the list reads alphabetically the way the
    # admin expects. Emails are unique in the schema, so no de-duplication is
    # needed, and deleted accounts no longer exist as rows at all.
    rows = db.execute(
        select(User.id, User.email)
        .order_by(func.lower(User.email).asc(), User.id.asc())
        .limit(CUSTOMER_OPTION_LIMIT + 1)
    ).all()

    truncated = len(rows) > CUSTOMER_OPTION_LIMIT
    options = [
        CustomerOption(id=user_id, email=email)
        for user_id, email in rows[:CUSTOMER_OPTION_LIMIT]
    ]

    # Customer addresses must never sit in a shared cache.
    response.headers["Cache-Control"] = "no-store"

    return CustomerOptionsResponse(
        options=options, truncated=truncated, limit=CUSTOMER_OPTION_LIMIT
    )


@router.get("/users", response_model=list[UserSummaryResponse])
def search_users(
    q: str = Query(min_length=1, max_length=320),
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
) -> list[UserSummaryResponse]:
    """Find accounts by email, or by numeric id.

    The query runs server side and is capped, so the console never downloads the
    customer table to filter it in the browser.
    """
    del admin
    term = q.strip().lower()

    if not term:
        raise HTTPException(status_code=400, detail="Enter an email address or account id.")

    conditions = [func.lower(User.email).like(f"%{term}%")]

    if term.isdigit():
        conditions.append(User.id == int(term))

    rows = db.scalars(
        select(User).where(or_(*conditions)).order_by(User.id).limit(SEARCH_LIMIT)
    ).all()

    return [
        UserSummaryResponse(
            id=user.id,
            email=user.email,
            plan=user.plan,
            subscription_status=user.subscription_status,
            is_active=bool(user.is_active),
            is_admin=bool(user.is_admin),
            created_at=user.created_at,
            bonus_processing_seconds=max(int(user.bonus_processing_seconds or 0), 0),
        )
        for user in rows
    ]


@router.get("/users/{user_id}", response_model=UserDetailResponse)
def user_detail(
    user_id: int,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
) -> UserDetailResponse:
    """Support detail for one account."""
    del admin
    user = _require_user(db, user_id)
    # Roll the period so an administrator sees current, not last month's, usage.
    if ensure_current_usage_period(user):
        db.commit()
    db.refresh(user)

    return _detail_for(db, user)


@router.post("/users/{user_id}/credits", response_model=UserDetailResponse)
def adjust_credit(
    user_id: int,
    payload: CreditAdjustmentRequest,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
) -> UserDetailResponse:
    """Grant or remove support processing credit, and record why.

    A separate audit row is written for every adjustment rather than rewriting a
    balance, so the history stays truthful. The balance is never allowed to go
    below zero.

    An administrator may adjust their own account, so the owner can grant
    themselves credit for testing, QA, or demonstrations. That is an intentional
    exception to the usual support flow, and it is only reachable by an
    authenticated administrator: `require_admin` still guards this route, so a
    normal user adjusting either themselves or anyone else is still refused. The
    adjustment is still reasoned, confirmed, and audited, and for a self-adjustment
    the audit row simply has the same id in both columns.
    """
    reason = payload.reason.strip()

    if len(reason) < 3:
        raise HTTPException(status_code=422, detail=REASON_REQUIRED)

    seconds = int(round(payload.minutes * 60))

    if seconds == 0:
        raise HTTPException(status_code=422, detail="Enter a non-zero number of minutes.")

    if abs(seconds) > MAX_ADJUSTMENT_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=f"Adjustments are limited to {MAX_ADJUSTMENT_SECONDS // 3600} hours at a time.",
        )

    target = _require_user(db, user_id)

    current = max(int(target.bonus_processing_seconds or 0), 0)

    if seconds < 0 and abs(seconds) > current:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{CREDIT_WOULD_GO_NEGATIVE} "
                f"Available credit is {current // 60} minutes."
            ),
        )

    target.bonus_processing_seconds = current + seconds
    target.updated_at = utcnow()

    db.add(
        AdminAuditEntry(
            admin_user_id=admin.id,
            target_user_id=target.id,
            action=ACTION_CREDIT_GRANTED if seconds > 0 else ACTION_CREDIT_REMOVED,
            amount_seconds=seconds,
            reason=reason,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    db.refresh(target)

    logger.info(
        "Admin %s adjusted credit for user_id=%s by %ss (%s)",
        admin.id,
        target.id,
        seconds,
        reason,
    )

    return _detail_for(db, target)


@router.get("/users/{user_id}/audit", response_model=list[AuditEntryResponse])
def user_audit(
    user_id: int,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
) -> list[AuditEntryResponse]:
    """Recent administrative actions against one account, newest first."""
    del admin
    _require_user(db, user_id)

    rows = db.scalars(
        select(AdminAuditEntry)
        .where(AdminAuditEntry.target_user_id == user_id)
        .order_by(AdminAuditEntry.created_at.desc(), AdminAuditEntry.id.desc())
        .limit(50)
    ).all()

    admins = {
        row.admin_user_id: row.admin_user.email
        for row in rows
        if row.admin_user is not None
    }

    return [
        AuditEntryResponse(
            id=row.id,
            action=row.action,
            amount_seconds=row.amount_seconds,
            reason=row.reason,
            created_at=row.created_at,
            admin_user_id=row.admin_user_id,
            admin_email=admins.get(row.admin_user_id, "unknown"),
        )
        for row in rows
    ]


__all__ = ["router", "sync_admin_emails"]


def sync_admin_emails(db: OrmSession) -> int:
    """Apply the ADMIN_EMAILS allow-list to the accounts table.

    Called once at startup. When the variable is empty nothing happens at all, so
    an unconfigured deployment can never expose the console. When it is set the
    list is authoritative: listed accounts gain administrator access and every
    other account loses it, which makes revocation a matter of editing one
    variable and redeploying.

    Returns the number of accounts whose administrator flag changed.
    """
    from ..config import get_settings

    allowed = get_settings().admin_email_set

    if not allowed:
        logger.info("ADMIN_EMAILS is not configured; no administrators are managed.")
        return 0

    changed = 0

    for user in db.scalars(select(User)).all():
        normalised = (user.email or "").strip().lower()
        should_be_admin = normalised in allowed

        if bool(user.is_admin) != should_be_admin:
            user.is_admin = should_be_admin
            changed += 1

    if changed:
        db.commit()
        logger.info("Applied ADMIN_EMAILS: %s administrator flag(s) changed.", changed)
    else:
        logger.info("ADMIN_EMAILS already matches the stored administrator flags.")

    return changed
