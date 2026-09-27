"""Stripe integration.

Every Stripe identifier and secret comes from the environment. Nothing here
invents a key, product, or price, and no value is ever logged.

The client is created lazily so the service starts and works normally when Stripe
is not configured, and so tests can inject a fake.

## Authority

Stripe is the source of truth for paid access. The browser returning from
Checkout changes nothing on its own: entitlement only changes when a *verified*
webhook is processed. An unmapped Price ID grants nothing, so a typo in the
configuration fails closed rather than granting free premium access.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from .config import get_settings
from .plans import (
    CREATOR_ANNUAL_PLAN_ID,
    CREATOR_MONTHLY_PLAN_ID,
    PRO_MONTHLY_PLAN_ID,
    register_price_mapping,
)

logger = logging.getLogger(__name__)

#: Env var name -> internal plan id.
PLAN_TO_PRICE_ENV_VAR: dict[str, str] = {
    CREATOR_MONTHLY_PLAN_ID: "stripe_price_creator_monthly",
    PRO_MONTHLY_PLAN_ID: "stripe_price_pro_monthly",
    CREATOR_ANNUAL_PLAN_ID: "stripe_price_creator_annual",
}


class StripeNotConfigured(Exception):
    """Raised when a billing action is attempted without Stripe configured."""


def get_stripe_client() -> stripe.StripeClient | None:
    """Return a configured Stripe client, or None when Stripe is not configured.

    A new client is built per call so environment changes (and tests) are picked
    up, and so the secret key never has to be held in a module global.
    """
    settings = get_settings()

    if not settings.stripe_secret_key:
        return None

    return stripe.StripeClient(settings.stripe_secret_key)


def require_stripe_client() -> stripe.StripeClient:
    client = get_stripe_client()

    if client is None:
        raise StripeNotConfigured(
            "Billing is not configured on this service yet. Please try again later."
        )

    return client


def refresh_price_mapping() -> None:
    """Rebuild the Price ID -> plan mapping from the environment.

    Called at startup and in tests. Unset prices simply are not mapped, so the
    corresponding checkout attempt reports a configuration error instead of
    granting access.
    """
    settings = get_settings()

    for plan_id, attribute in PLAN_TO_PRICE_ENV_VAR.items():
        register_price_mapping(getattr(settings, attribute, None), plan_id)


def price_id_for_plan(plan_id: str) -> str | None:
    """Resolve an internal plan id to its configured Stripe Price ID."""
    settings = get_settings()
    attribute = PLAN_TO_PRICE_ENV_VAR.get(plan_id)

    if attribute is None:
        return None

    return getattr(settings, attribute, None) or None


def is_billing_configured_for(plan_id: str) -> bool:
    return bool(price_id_for_plan(plan_id))


def build_checkout_session(
    *,
    customer_email: str,
    plan_id: str,
    stripe_customer_id: str | None,
    success_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    """Create a Stripe Checkout session for a paid plan.

    The amount is chosen by Stripe from the configured Price ID. The client only
    ever names an internal plan id, so it cannot influence what is charged.
    """
    client = require_stripe_client()
    price_id = price_id_for_plan(plan_id)

    if not price_id:
        raise StripeNotConfigured(
            "That plan is not available for purchase right now. Please try again later."
        )

    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": plan_id,
        "allow_promotion_codes": True,
    }

    if stripe_customer_id:
        params["customer"] = stripe_customer_id
    else:
        # Stripe creates the Customer from this address; the webhook then
        # records the resulting customer id on the account.
        params["customer_email"] = customer_email

    # The typed params object must be passed as ONE positional argument.
    # Expanding the dict into keywords raises
    # "TypeError: SessionService.create() got an unexpected keyword argument 'mode'",
    # because the signature is create(params, options).
    session = client.v1.checkout.sessions.create(params)

    return {
        "id": session.id,
        "url": session.url,
    }


def build_portal_session(
    *, customer_id: str, return_url: str
) -> dict[str, Any]:
    """Create a Stripe Customer Portal session for an existing subscriber."""
    client = require_stripe_client()

    # Same positional-params rule as checkout, see build_checkout_session.
    session = client.v1.billing_portal.sessions.create(
        {"customer": customer_id, "return_url": return_url}
    )

    return {"url": session.url}


def construct_event(payload: bytes, signature_header: str | None) -> dict[str, Any]:
    """Verify and decode a webhook payload.

    Raises `ValueError` when the signature is missing or does not match, which the
    caller turns into a 400. Signature verification is mandatory: an unverified
    payload must never be able to grant paid access.
    """
    settings = get_settings()

    if not settings.stripe_webhook_secret:
        raise StripeNotConfigured("Webhook handling is not configured on this service.")

    if not signature_header:
        raise ValueError("Missing Stripe signature header.")

    try:
        event = stripe.Webhook.construct_event(
            payload, signature_header, settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError as exc:
        # Raised for a bad or absent signature. Not a ValueError subclass in the
        # official library, so it has to be caught explicitly.
        raise ValueError("Invalid Stripe signature.") from exc
    except ValueError as exc:
        # Malformed payload.
        raise ValueError("Invalid Stripe payload.") from exc

    return event.to_dict()


def extract_subscription_details(event: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the fields Captionline mirrors out of a subscription-ish event.

    Handles both `customer.subscription.*` events (object at the top level) and
    invoice events, whose subscription lives at `parent.subscription_details`.
    """
    obj = event.get("data", {}).get("object", {}) or {}

    if obj.get("object") == "subscription":
        subscription = obj
        customer = subscription.get("customer")
    else:
        details = (obj.get("parent") or {}).get("subscription_details") or {}
        subscription = details.get("subscription") or {}
        customer = obj.get("customer") or (subscription or {}).get("customer")

        if isinstance(customer, dict):
            customer = customer.get("id")

    if not subscription:
        return None

    items = subscription.get("items") or {}
    data_items = items.get("data") if isinstance(items, dict) else items

    price_id = None
    if isinstance(data_items, list) and data_items:
        price = (data_items[0].get("price") or {}) if isinstance(data_items[0], dict) else {}
        if isinstance(price, dict):
            price_id = price.get("id")
    elif isinstance(data_items, dict) and data_items.get("id"):
        price = (data_items.get("price") or {}) if isinstance(data_items.get("price"), dict) else {}
        price_id = price.get("id") or data_items.get("id")

    if isinstance(customer, dict):
        customer = customer.get("id")

    return {
        "subscription_id": subscription.get("id"),
        "customer_id": customer,
        "price_id": price_id,
        "status": subscription.get("status"),
        "current_period_end": subscription.get("current_period_end"),
        "cancel_at_period_end": subscription.get("cancel_at_period_end"),
    }
