"""Billing routes: Checkout, Customer Portal, and webhooks.

Paid access is only ever granted by a *verified* webhook. Creating a Checkout
session does not change entitlement, so returning from the browser cannot grant
anything on its own.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.models import StripeEvent, User
from ..db.session import get_db
from ..plans import (
    PURCHASABLE_PLAN_IDS,
    SUBSCRIPTION_CANCELED,
    get_plan,
    has_active_paid_subscription,
    plan_for_price_id,
)
from ..security.deps import get_current_user
from ..security.schemas import CheckoutResponse
from ..stripe_client import (
    StripeNotConfigured,
    build_checkout_session,
    build_portal_session,
    construct_event,
    extract_subscription_details,
)
from ..usage import apply_plan_to_user, add_months, period_start_for

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

INVALID_PLAN = "That plan is not available."
WEBHOOK_SIGNATURE_INVALID = "Invalid Stripe signature."

#: Stripe error messages can echo request data, so anything that looks like a
#: credential, a card number, or a token is redacted before it reaches the logs.
#: Truncation alone is not enough: Stripe routinely puts the offending value in
#: the first sentence (for example "Invalid API Key provided: sk_live_...").
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]+"), "[REDACTED_STRIPE_KEY]"),
    (re.compile(r"\bwhsec_[A-Za-z0-9]+"), "[REDACTED_WEBHOOK_SECRET]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+"), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "[REDACTED_JWT]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_CARD]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
)

_SAFE_MESSAGE_CHARS = 200


def _safe_stripe_message(exc: Exception) -> str:
    """Reduce an SDK exception to something safe to write to logs.

    Keeps the exception class and a short leading clause, after redacting
    anything that looks like a secret key, webhook secret, bearer token, JWT,
    card number, or email address. The public API response is unaffected.
    """
    message = str(exc).strip()

    for pattern, replacement in _REDACTIONS:
        message = pattern.sub(replacement, message)

    for separator in (". ", "\n"):
        index = message.find(separator)
        if index != -1:
            message = message[:index]

    message = message[:_SAFE_MESSAGE_CHARS]
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _log_stripe_failure(operation: str, plan_id: str | None, exc: Exception) -> None:
    """Log a Stripe SDK failure with enough detail to diagnose it.

    Deliberately logs only the operation, the internal plan id, the exception
    class, and a sanitized message. No key, token, or customer data.
    """
    logger.warning(
        "Stripe %s failed (plan=%s): %s",
        operation,
        plan_id or "n/a",
        _safe_stripe_message(exc),
    )


class CheckoutRequest(BaseModel):
    plan: str = Field(min_length=1)


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(
    payload: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> CheckoutResponse:
    """Start a Stripe Checkout session for a paid plan.

    Requires authentication. The amount comes from the server-configured Price
    ID for the requested plan; the client cannot influence it.
    """
    if payload.plan not in PURCHASABLE_PLAN_IDS:
        raise HTTPException(status_code=400, detail=INVALID_PLAN)

    settings = get_settings()
    frontend = settings.frontend_url.rstrip("/")

    try:
        result = build_checkout_session(
            customer_email=user.email,
            plan_id=payload.plan,
            stripe_customer_id=user.subscription_provider == "stripe"
            and user.subscription_external_id
            or None,
            success_url=f"{frontend}/?checkout=success&plan={payload.plan}",
            cancel_url=f"{frontend}/?checkout=cancelled&plan={payload.plan}",
        )
    except StripeNotConfigured as exc:
        # A configuration gap, not a user error. Billing UI shows this plainly.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:  # pragma: no cover - network/upstream failure
        _log_stripe_failure("checkout", payload.plan, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Checkout is temporarily unavailable. Please try again.",
        ) from exc

    return CheckoutResponse(
        session_id=result["id"],
        url=result["url"],
        plan=payload.plan,
    )


@router.post("/portal", response_model=CheckoutResponse)
def create_portal(
    user: User = Depends(get_current_user),
) -> CheckoutResponse:
    """Open the Stripe Customer Portal for an account with a Stripe customer id."""
    customer_id = user.subscription_external_id

    if not customer_id or user.subscription_provider != "stripe":
        raise HTTPException(
            status_code=400,
            detail="This account has no billing profile yet.",
        )

    settings = get_settings()
    frontend = settings.frontend_url.rstrip("/")

    try:
        result = build_portal_session(
            customer_id=customer_id, return_url=f"{frontend}/"
        )
    except StripeNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:  # pragma: no cover
        _log_stripe_failure("portal", user.plan, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The billing portal is temporarily unavailable.",
        ) from exc

    return CheckoutResponse(session_id="", url=result["url"], plan=user.plan)


# --------------------------------------------------------------------------- #
# Webhooks                                                                    #
# --------------------------------------------------------------------------- #

# Events that change entitlement.
SUBSCRIPTION_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
        "invoice.paid",
        "invoice.payment_failed",
    }
)


def _find_user(
    db: OrmSession,
    *,
    customer_id: str | None,
    subscription_id: str | None,
    client_reference_id: str | None,
) -> User | None:
    """Locate the account a Stripe event refers to.

    Never trusts an email in the payload for identity; matches only on the
    identifiers Captionline itself previously stored.
    """
    if subscription_id:
        user = db.scalar(
            select(User).where(User.subscription_external_id == subscription_id)
        )
        if user is not None:
            return user

    if customer_id:
        user = db.scalar(
            select(User).where(
                User.subscription_provider == "stripe",
                User.subscription_external_id == customer_id,
            )
        )
        if user is not None:
            return user

    return None


def _apply_subscription(
    db: OrmSession,
    user: User,
    *,
    subscription_id: str | None,
    customer_id: str | None,
    price_id: str | None,
    status_value: str | None,
    current_period_end: int | None,
    event_type: str,
) -> None:
    """Mirror verified Stripe state onto the account.

    An unmapped price id never upgrades the plan: it only updates the mirrored
    identifiers, so a misconfigured price degrades to free rather than granting
    premium access.
    """
    now = datetime.now(timezone.utc)

    if subscription_id:
        user.subscription_external_id = subscription_id
    if customer_id:
        user.subscription_external_id = customer_id

    user.subscription_provider = "stripe"
    user.subscription_status = (status_value or "incomplete").lower()

    if price_id:
        user.subscription_price_id = price_id

    if current_period_end:
        user.subscription_current_period_end = datetime.fromtimestamp(
            int(current_period_end), tz=timezone.utc
        )

    plan = plan_for_price_id(user.subscription_price_id)
    paid = has_active_paid_subscription(user.subscription_status)

    if plan is not None and paid:
        # Verified, mapped, and active: grant the paid plan.
        previous_plan = user.plan
        apply_plan_to_user(user, plan.id)

        # Starting a new subscription period resets the pool.
        if previous_plan != user.plan or _period_should_reset(user, plan.id, now):
            user.processing_used_seconds = 0
            start = period_start_for(now, user.plan)
            user.usage_period_started_at = start
            user.usage_period_ends_at = add_months(start, plan.usage_period_months)
    else:
        # Cancelled, unpaid, or an unmapped price: safely return to Free.
        # The account, its captions, and its usage history are preserved.
        apply_plan_to_user(user, "free")
        user.subscription_price_id = user.subscription_price_id

    user.updated_at = now


def _period_should_reset(user: User, plan_id: str, now: datetime) -> bool:
    plan = get_plan(plan_id)
    ends_at = user.usage_period_ends_at

    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)

    if now >= ends_at:
        return True

    # Align the period length with the plan (monthly vs annual).
    expected = add_months(user.usage_period_started_at, plan.usage_period_months)
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)

    return abs((expected - ends_at).total_seconds()) > 1


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    """Handle a Stripe webhook.

    Requires a valid signature. Idempotent: the event id is recorded and a repeat
    delivery is acknowledged without being applied twice.
    """
    payload = await request.body()

    try:
        event = construct_event(payload, stripe_signature)
    except StripeNotConfigured as exc:
        logger.warning("Webhook received but Stripe is not configured.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ValueError as exc:
        # Never echo signature or payload detail.
        raise HTTPException(status_code=400, detail=WEBHOOK_SIGNATURE_INVALID) from exc

    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")

    if not event_id:
        raise HTTPException(status_code=400, detail=WEBHOOK_SIGNATURE_INVALID)

    # Idempotency: a duplicate delivery is acknowledged and ignored.
    existing = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
    if existing is not None:
        return {"received": True, "duplicate": True}

    record = StripeEvent(event_id=event_id, event_type=event_type)
    db.add(record)

    if event_type not in SUBSCRIPTION_EVENTS:
        db.commit()
        record.processed_at = datetime.now(timezone.utc)
        db.commit()
        return {"received": True, "handled": False}

    details = extract_subscription_details(event)
    applied = False

    if details is not None:
        user = _find_user(
            db,
            customer_id=details.get("customer_id"),
            subscription_id=details.get("subscription_id"),
            client_reference_id=(event.get("data", {}).get("object", {}) or {}).get(
                "client_reference_id"
            ),
        )

        if user is not None:
            if event_type == "checkout.session.completed":
                # Adopt the customer id Stripe just created for this account.
                customer_id = details.get("customer_id")
                if customer_id:
                    user.subscription_external_id = customer_id
                    user.subscription_provider = "stripe"
                # Entitlement itself comes from subscription.* events, so that a
                # browser round trip cannot grant access on its own.
            elif event_type == "customer.subscription.deleted":
                _apply_subscription(
                    db,
                    user,
                    subscription_id=details.get("subscription_id"),
                    customer_id=details.get("customer_id"),
                    price_id=None,
                    status_value=SUBSCRIPTION_CANCELED,
                    current_period_end=details.get("current_period_end"),
                    event_type=event_type,
                )
                applied = True
            else:
                _apply_subscription(
                    db,
                    user,
                    subscription_id=details.get("subscription_id"),
                    customer_id=details.get("customer_id"),
                    price_id=details.get("price_id"),
                    status_value=details.get("status"),
                    current_period_end=details.get("current_period_end"),
                    event_type=event_type,
                )
                applied = True
        else:
            logger.info("No account matched Stripe event %s (%s)", event_id, event_type)

    record.processed_at = datetime.now(timezone.utc)
    db.commit()

    return {"received": True, "handled": applied}
