"""Account, entitlement, and public plan catalogue routes.

Also carries account deletion, because it is the same surface: the caller is
already authenticated by `get_current_user` and the outcome is only ever about
this account. The legal-text endpoints live here too, in a second unprefixed
router, so `/api/legal/versions` can be public while the rest of this module
stays behind the `/api/account` prefix.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as OrmSession

from ..db.models import User
from ..db.session import get_db
from ..plans import ACTIVE_SUBSCRIPTION_STATUSES, PLANS, PURCHASABLE_PLAN_IDS
from ..ratelimit import enforce
from ..security.deps import get_current_user, get_optional_user
from ..security.passwords import verify_password
from ..security.reset_tokens import revoke_all_reset_tokens, revoke_all_sessions
from ..security.schemas import (
    AccountDeletionRequest,
    AccountDeletionResponse,
    EntitlementResponse,
    LegalVersionsResponse,
    PlanResponse,
)
from ..stripe_client import is_billing_configured_for
from ..terms import (
    GOVERNING_LAW_PLACEHOLDER,
    PRIVACY_EFFECTIVE_DATE,
    PRIVACY_VERSION,
    SUPPORT_EMAIL,
    TERMS_EFFECTIVE_DATE,
    TERMS_VERSION,
)
from ..usage import build_usage_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account", tags=["account"])

#: A second router with no prefix, so the legal endpoints are not forced behind
#: `/api/account`. Registered in `app.main` next to `router`.
legal_router = APIRouter(tags=["legal"])

# --- Account deletion -------------------------------------------------------

#: The exact word a user must type. Compared literally, so a near miss is
#: refused rather than guessed at: this action cannot be undone.
DELETION_CONFIRMATION = "DELETE"

DELETION_MESSAGE = "Your account has been deleted."
DELETION_CONFIRMATION_REQUIRED = (
    'To delete your account, type "DELETE" in the confirmation field.'
)
DELETION_PASSWORD_INCORRECT = "Your current password is incorrect."
DELETION_FAILED = (
    "We could not delete your account. Nothing has been changed. Please try again."
)

#: A live subscription must be cancelled by the customer first. The wording names
#: the action rather than just refusing, because a bare "cannot delete" leaves a
#: paying customer with no way forward.
DELETION_BLOCKED_BY_SUBSCRIPTION = (
    "Your account still has an active subscription, so it cannot be deleted yet. "
    "Cancel or manage your subscription in the billing portal first; once the "
    "subscription is cancelled you can delete your account."
)

#: Said once, and only in the success case. It is not part of `message` and not
#: in `DELETION_BLOCKED_BY_SUBSCRIPTION`: at that point nothing has been deleted,
#: so the retention point would be noise.
DELETION_RETAINED_BY_STRIPE_NOTE = (
    "Your account and its data on Captionline have been deleted. Stripe keeps its "
    "own financial records independently; deleting your account here does not "
    "erase them."
)


@router.post("/delete", response_model=AccountDeletionResponse)
def delete_account(
    payload: AccountDeletionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> AccountDeletionResponse:
    """Delete the authenticated account and everything it owns.

    POST rather than DELETE, deliberately. Several proxies, CDNs, and HTTP
    clients drop or mishandle a body on a DELETE, so a `DELETE` with a
    confirmation payload is a request that arrives empty in production. `POST`
    is unambiguous, and it is idempotent enough: a repeat call fails
    authentication, because the session died with the account.

    ## Why a live subscription blocks deletion instead of being cancelled

    Deleting the local row while Stripe keeps billing is the worst possible
    outcome: the customer is charged for a service they no longer have, their
    invoices point at an account that no longer exists, and the entitlement
    webhook has nowhere to land. This endpoint therefore **blocks** and asks the
    customer to cancel through the Customer Portal themselves.

    It does not call a Stripe cancel or modify API, and that is a deliberate
    decision for this phase rather than an omission. Cancellation is
    already portal-based in this architecture: `POST /api/billing/portal` is how
    a customer manages billing, and a server-side cancel would be a second,
    divergent path to the same state that nobody has specified, tested, or
    reasoned about. Worse, a server-side cancel called from a deletion request
    can fail after the local transaction has already committed, and the two
    systems cannot be rolled back together. Blocking keeps every one of those
    outcomes impossible, and it also puts the customer in control of a financial
    decision that is theirs. Webhook delivery, not this endpoint, remains the
    single place that decides whether a subscription is active.

    ## What deletion covers

    The local account row, its sessions, its outstanding password-reset tokens,
    and its usage reservations, in one transaction, all through the ORM cascades
    declared in `db/models.py`. Uploads are already transient (every transcription
    removes its work directory), so there is no media store to clear.

    **Stripe is outside this.** Stripe independently retains its own financial
    records, and they are not erased by this action. A card processor holds those
    records under its own obligations regardless of what a web application asks
    of it; pretending otherwise would be a false promise to the customer, so the
    deletion confirmation says so explicitly.

    Every rejection path is a fixed message that never echoes the submitted
    password or confirmation, and nothing sensitive is logged: the user id and
    the outcome are all that are recorded.
    """
    # Throttled per address and per account, on its own bucket. Deletion used to
    # share `change-password`; it has its own now so a user who has burned the
    # password-change budget (for example by mistyping five new passwords) can
    # still close their account, and so a flood of delete attempts cannot spend
    # another control's budget to get there.
    enforce("delete-account", request, account=str(user.id))

    # Confirmation first: it costs nothing, and refusing a malformed request
    # before spending Argon2id is strictly better for both sides.
    if payload.confirmation.strip() != DELETION_CONFIRMATION:
        logger.info("Account deletion refused for user_id=%s (bad confirmation)", user.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DELETION_CONFIRMATION_REQUIRED,
        )

    if not verify_password(payload.current_password, user.password_hash):
        # A 401 rather than a 403: the credential presented for this action is
        # wrong. The message names only the field, never the stored value.
        logger.info("Account deletion refused for user_id=%s (bad password)", user.id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=DELETION_PASSWORD_INCORRECT
        )

    # A mirrored active status with no provider reference is not a live
    # subscription, it is a half-applied webhook, and the customer must not be
    # locked out of deleting their account by one.
    if (
        user.subscription_status in ACTIVE_SUBSCRIPTION_STATUSES
        and user.subscription_external_id
    ):
        logger.info(
            "Account deletion refused for user_id=%s (active subscription)", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DELETION_BLOCKED_BY_SUBSCRIPTION,
        )

    now = datetime.now(timezone.utc)
    user_id = user.id

    # Revoke first, then delete, in one transaction. The revocations are
    # redundant once the rows are gone, and that redundancy is the point: if the
    # delete is rolled back, the session is still revoked, so a failed deletion
    # attempt cannot leave a live session behind on an account the user believes
    # they have closed. A pending reset link must not outlive the account either.
    #
    # Everything that touches the database is inside the `try`, so a failure at
    # any step is rolled back whole and reported as the same generic 500.
    try:
        revoked_sessions = revoke_all_sessions(db, user.id, now)
        revoked_tokens = revoke_all_reset_tokens(db, user.id, now)

        db.delete(user)
        db.commit()
    except Exception as exc:
        db.rollback()
        # The message is deliberately generic: SQLAlchemy errors carry table and
        # column names, and a constraint message is a free map of the schema.
        logger.exception("Account deletion failed for user_id=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=DELETION_FAILED
        ) from exc

    # Only the id and the counts. Never the password, the confirmation, the
    # email, or any token.
    logger.info(
        "Account deleted for user_id=%s (revoked %d session(s), %d reset token(s))",
        user_id,
        revoked_sessions,
        revoked_tokens,
    )

    return AccountDeletionResponse(
        message=DELETION_MESSAGE, stripe_data_note=DELETION_RETAINED_BY_STRIPE_NOTE
    )


# --- Legal text -------------------------------------------------------------


@legal_router.get("/api/legal/versions", response_model=LegalVersionsResponse)
def legal_versions() -> LegalVersionsResponse:
    """Report the Terms and Privacy versions currently in force.

    Public, so the signup page can render them for a visitor who has no account
    yet, and served from `app/terms.py` so the frontend never hardcodes a
    version string that could disagree with the one the backend records.
    """
    return LegalVersionsResponse(
        terms_version=TERMS_VERSION,
        terms_effective_date=TERMS_EFFECTIVE_DATE,
        privacy_version=PRIVACY_VERSION,
        privacy_effective_date=PRIVACY_EFFECTIVE_DATE,
        support_email=SUPPORT_EMAIL,
        support_email_configured=bool(SUPPORT_EMAIL),
        governing_law=GOVERNING_LAW_PLACEHOLDER,
    )


def _to_entitlement(snapshot, user) -> EntitlementResponse:
    return EntitlementResponse(
        plan=snapshot.plan,
        plan_label=snapshot.plan_label,
        subscription_status=snapshot.subscription_status,
        is_paid_plan=snapshot.is_paid_plan,
        is_admin=bool(user.is_admin),
        monthly_processing_allowance_seconds=snapshot.monthly_processing_allowance_seconds,
        processing_used_seconds=snapshot.processing_used_seconds,
        processing_reserved_seconds=snapshot.processing_reserved_seconds,
        bonus_processing_seconds=snapshot.bonus_processing_seconds,
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
    return _to_entitlement(build_usage_snapshot(db, user), user)


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
