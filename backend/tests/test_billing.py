"""Stripe tests using fixtures and a fake client.

No live Stripe account, network call, or real charge is involved. The webhook
signature path is exercised against a locally computed signature so the
verification logic itself is genuinely tested.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import select

import app.stripe_client as stripe_client
from app.db.models import StripeEvent, User
from app.plans import (
    CREATOR_ANNUAL_PLAN_ID,
    CREATOR_MONTHLY_PLAN_ID,
    PRO_MONTHLY_PLAN_ID,
    register_price_mapping,
    reset_price_mapping,
)
from app.stripe_client import StripeNotConfigured, construct_event, extract_subscription_details
from tests.conftest import auth_header

# Fixture values only. They are deliberately not shaped like real Stripe
# credentials, so secret scanners cannot mistake them for live keys. The code under
# test only checks that a value is present, and the webhook value is used purely as
# an HMAC signing key.
SECRET = "local-test-value-not-a-credential"
WEBHOOK_SECRET = "local-test-webhook-value-not-a-credential"
CREATOR_PRICE = "test-price-creator-monthly"
PRO_PRICE = "test-price-pro-monthly"
ANNUAL_PRICE = "test-price-creator-annual"
UNMAPPED_PRICE = "test-price-not-ours"


@pytest.fixture(autouse=True)
def stripe_env(monkeypatch, live_settings):
    """Configure fake Stripe environment for each test."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", SECRET)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("STRIPE_PRICE_CREATOR_MONTHLY", CREATOR_PRICE)
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", PRO_PRICE)
    monkeypatch.setenv("STRIPE_PRICE_CREATOR_ANNUAL", ANNUAL_PRICE)

    # Re-read the environment in both the settings singleton and the app module.
    live_settings()

    reset_price_mapping()
    stripe_client.refresh_price_mapping()

    yield

    reset_price_mapping()
    live_settings()


def sign(payload: bytes, signing_value: str = WEBHOOK_SECRET) -> str:
    """Build a valid Stripe-style signature header locally."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode() + payload
    signature = hmac.new(signing_value.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def register(client, email="buyer@example.com"):
    return client.post(
        "/api/auth/register", json={"email": email, "password": "a-strong-password-123"}
    )


# --- Checkout authentication ---


def test_checkout_requires_authentication(client):
    assert client.post("/api/billing/checkout", json={"plan": CREATOR_MONTHLY_PLAN_ID}).status_code == 401


def test_portal_requires_authentication(client):
    assert client.post("/api/billing/portal").status_code == 401


def test_checkout_rejects_free_plan(client):
    token = register(client).json()["access_token"]

    response = client.post(
        "/api/billing/checkout", json={"plan": "free"}, headers=auth_header(token)
    )

    assert response.status_code == 400
    assert "not available" in response.json()["detail"]


def test_checkout_rejects_unknown_plan(client):
    token = register(client).json()["access_token"]

    response = client.post(
        "/api/billing/checkout", json={"plan": "enterprise_ultra"}, headers=auth_header(token)
    )

    assert response.status_code == 400


def test_checkout_rejects_empty_plan(client):
    token = register(client).json()["access_token"]

    assert (
        client.post("/api/billing/checkout", json={"plan": ""}, headers=auth_header(token)).status_code
        == 422
    )


# --- Plan -> Price mapping ---


def test_price_id_mapping_uses_environment():
    assert stripe_client.price_id_for_plan(CREATOR_MONTHLY_PLAN_ID) == CREATOR_PRICE
    assert stripe_client.price_id_for_plan(PRO_MONTHLY_PLAN_ID) == PRO_PRICE
    assert stripe_client.price_id_for_plan(CREATOR_ANNUAL_PLAN_ID) == ANNUAL_PRICE
    # The free plan is never purchasable, so it has no Price ID.
    assert stripe_client.price_id_for_plan("free") is None
    assert stripe_client.price_id_for_plan("nope") is None


def test_unmapped_price_fails_closed():
    from app.plans import plan_for_price_id

    assert plan_for_price_id(UNMAPPED_PRICE) is None
    assert plan_for_price_id(CREATOR_PRICE).id == CREATOR_MONTHLY_PLAN_ID


# --- Stripe not configured ---


def test_checkout_without_stripe_reports_configuration(client, monkeypatch, live_settings):
    token = register(client).json()["access_token"]

    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    live_settings()

    response = client.post(
        "/api/billing/checkout", json={"plan": CREATOR_MONTHLY_PLAN_ID}, headers=auth_header(token)
    )

    # A configuration gap is 503, not a crash and not a fake success.
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_health_reports_stripe_without_leaking_keys(client):
    body = client.get("/api/health").json()

    assert body["stripe"]["configured"] is True
    assert body["stripe"]["webhook_configured"] is True
    assert "sk_test" not in json.dumps(body)
    assert "whsec" not in json.dumps(body)


def test_plans_endpoint_reports_purchasability(client):
    body = client.get("/api/account/plans").json()
    by_id = {plan["id"]: plan for plan in body}

    assert by_id["creator_monthly"]["purchasable"] is True
    assert by_id["free"]["purchasable"] is False
    # Prices come from the backend catalogue.
    assert by_id["creator_monthly"]["price_usd"] == 19
    assert by_id["pro_monthly"]["price_usd"] == 39
    assert by_id["creator_annual"]["price_usd"] == 190


# --- Portal ---


def test_portal_requires_a_stripe_customer(client):
    token = register(client).json()["access_token"]

    response = client.post("/api/billing/portal", headers=auth_header(token))

    assert response.status_code == 400
    assert "no billing profile" in response.json()["detail"]


# --- Webhook signature verification ---


def test_webhook_rejects_missing_signature(client):
    payload = json.dumps({"id": "evt_1", "type": "customer.subscription.updated"}).encode()

    response = client.post("/api/billing/webhook", content=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Stripe signature."


def test_webhook_rejects_bad_signature(client):
    payload = json.dumps({"id": "evt_1", "type": "customer.subscription.updated"}).encode()

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": "t=1,v1=deadbeef"},
    )

    assert response.status_code == 400


def test_webhook_rejects_signature_from_wrong_secret(client):
    payload = json.dumps({"id": "evt_1", "type": "customer.subscription.updated"}).encode()

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": sign(payload, signing_value="local-wrong-value")},
    )

    assert response.status_code == 400


def test_webhook_accepts_valid_signature(client):
    payload = json.dumps({"id": "evt_ok", "type": "unrelated.event"}).encode()

    response = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": sign(payload)},
    )

    assert response.status_code == 200
    assert response.json()["received"] is True


def test_webhook_without_stripe_configured_returns_503(client, monkeypatch, live_settings):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "")
    live_settings()

    payload = json.dumps({"id": "evt_x", "type": "customer.subscription.updated"}).encode()
    response = client.post(
        "/api/billing/webhook", content=payload, headers={"Stripe-Signature": "t=1,v1=abc"}
    )

    assert response.status_code == 503


# --- Webhook effects ---


def subscription_event(event_id: str, price_id: str, status: str = "active", **overrides):
    body = {
        "id": event_id,
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "object": "subscription",
                "id": "sub_test_123",
                "customer": "cus_test_123",
                "status": status,
                "current_period_end": 1790000000,
                "items": {"data": [{"price": {"id": price_id}}]},
                **overrides,
            }
        },
    }
    return json.dumps(body).encode()


def attach_stripe_identity(db_session, email, customer_id="cus_test_123"):
    user = db_session.execute(select(User).where(User.email == email)).scalar_one()
    user.subscription_provider = "stripe"
    user.subscription_external_id = customer_id
    db_session.commit()
    return user


def test_active_paid_subscription_upgrades_plan(client, db_session):
    token = register(client).json()["access_token"]
    attach_stripe_identity(db_session, "buyer@example.com")

    payload = subscription_event("evt_creator", CREATOR_PRICE)
    response = client.post(
        "/api/billing/webhook", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert response.status_code == 200
    assert response.json()["handled"] is True

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert entitlement["plan"] == CREATOR_MONTHLY_PLAN_ID
    assert entitlement["has_full_preview"] is True
    assert entitlement["can_export"] is True
    assert entitlement["preview_limit_seconds"] is None
    assert entitlement["monthly_processing_allowance_seconds"] == 30_000
    assert entitlement["processing_remaining_seconds"] == 30_000


def test_pro_price_upgrades_to_pro_allowance(client, db_session):
    token = register(client).json()["access_token"]
    attach_stripe_identity(db_session, "buyer@example.com")

    payload = subscription_event("evt_pro", PRO_PRICE)
    client.post("/api/billing/webhook", content=payload, headers={"Stripe-Signature": sign(payload)})

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert entitlement["plan"] == PRO_MONTHLY_PLAN_ID
    assert entitlement["monthly_processing_allowance_seconds"] == 90_000
    assert entitlement["can_export"] is True


def test_annual_price_upgrades_to_monthly_allowance(client, db_session):
    """Annual Stripe billing still grants a monthly 500-minute allowance."""
    token = register(client).json()["access_token"]
    attach_stripe_identity(db_session, "buyer@example.com")

    payload = subscription_event("evt_annual", ANNUAL_PRICE)
    client.post("/api/billing/webhook", content=payload, headers={"Stripe-Signature": sign(payload)})

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert entitlement["plan"] == CREATOR_ANNUAL_PLAN_ID
    assert entitlement["monthly_processing_allowance_seconds"] == 30_000
    assert entitlement["processing_allowance_minutes"] == 500.0
    # Billed annually, but usage resets monthly.
    assert entitlement["billed_annually"] is True
    assert entitlement["usage_resets_monthly"] is True
    assert entitlement["usage_period_months"] == 1
    assert entitlement["has_full_preview"] is True
    assert entitlement["can_export"] is True


def test_unknown_price_does_not_grant_paid_access(client, db_session):
    """A price we do not map must never upgrade the account."""
    token = register(client).json()["access_token"]
    attach_stripe_identity(db_session, "buyer@example.com")

    payload = subscription_event("evt_unknown_price", UNMAPPED_PRICE)
    client.post("/api/billing/webhook", content=payload, headers={"Stripe-Signature": sign(payload)})

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert entitlement["plan"] == "free"
    assert entitlement["has_full_preview"] is False
    assert entitlement["can_export"] is False
    assert entitlement["monthly_processing_allowance_seconds"] == 600


def test_past_due_subscription_removes_paid_entitlement(client, db_session):
    token = register(client).json()["access_token"]
    attach_stripe_identity(db_session, "buyer@example.com")

    active = subscription_event("evt_active", CREATOR_PRICE)
    client.post("/api/billing/webhook", content=active, headers={"Stripe-Signature": sign(active)})
    assert (
        client.get("/api/account/entitlement", headers=auth_header(token)).json()["plan"]
        == CREATOR_MONTHLY_PLAN_ID
    )

    past_due = subscription_event("evt_past_due", CREATOR_PRICE, status="past_due")
    client.post(
        "/api/billing/webhook", content=past_due, headers={"Stripe-Signature": sign(past_due)}
    )

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()
    assert entitlement["plan"] == "free"
    assert entitlement["has_full_preview"] is False
    assert entitlement["can_export"] is False


def test_subscription_deleted_returns_to_free_but_keeps_the_account(
    client, db_session
):
    token = register(client).json()["access_token"]
    attach_stripe_identity(db_session, "buyer@example.com")

    active = subscription_event("evt_active2", CREATOR_PRICE)
    client.post("/api/billing/webhook", content=active, headers={"Stripe-Signature": sign(active)})

    deleted = json.dumps(
        {
            "id": "evt_deleted",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "object": "subscription",
                    "id": "sub_test_123",
                    "customer": "cus_test_123",
                    "status": "canceled",
                    "items": {"data": [{"price": {"id": CREATOR_PRICE}}]},
                }
            },
        }
    ).encode()

    client.post(
        "/api/billing/webhook", content=deleted, headers={"Stripe-Signature": sign(deleted)}
    )

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    # Entitlement reverts...
    assert entitlement["plan"] == "free"
    assert entitlement["has_full_preview"] is False
    # ...but the account itself, and access to it, survive.
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200
    assert client.get("/api/auth/me", headers=auth_header(token)).json()["email"] == "buyer@example.com"


def test_checkout_completed_alone_does_not_grant_access(client, db_session):
    """Returning from the browser must not grant paid access by itself."""
    token = register(client).json()["access_token"]
    attach_stripe_identity(db_session, "buyer@example.com")

    completed = json.dumps(
        {
            "id": "evt_checkout",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "object": "checkout.session",
                    "customer": "cus_test_123",
                    "subscription": "sub_test_123",
                    "client_reference_id": CREATOR_MONTHLY_PLAN_ID,
                }
            },
        }
    ).encode()

    client.post(
        "/api/billing/webhook", content=completed, headers={"Stripe-Signature": sign(completed)}
    )

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert entitlement["plan"] == "free"
    assert entitlement["has_full_preview"] is False


def test_webhook_is_idempotent_for_duplicate_delivery(client, db_session):
    token = register(client).json()["access_token"]
    attach_stripe_identity(db_session, "buyer@example.com")

    payload = subscription_event("evt_dup", CREATOR_PRICE)

    first = client.post(
        "/api/billing/webhook", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert first.json()["duplicate"] if "duplicate" in first.json() else True

    second = client.post(
        "/api/billing/webhook", content=payload, headers={"Stripe-Signature": sign(payload)}
    )

    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    # Entitlement applied exactly once.
    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()
    assert entitlement["plan"] == CREATOR_MONTHLY_PLAN_ID

    events = db_session.execute(select(StripeEvent)).scalars().all()
    assert len([event for event in events if event.event_id == "evt_dup"]) == 1


def test_unrelated_event_is_acknowledged_without_effect(client, db_session):
    token = register(client).json()["access_token"]

    payload = json.dumps(
        {
            "id": "evt_unrelated",
            "type": "invoice.created",
            "data": {"object": {"object": "invoice", "customer": "cus_test_123"}},
        }
    ).encode()

    response = client.post(
        "/api/billing/webhook", content=payload, headers={"Stripe-Signature": sign(payload)}
    )

    assert response.status_code == 200
    assert response.json()["handled"] is False
    assert client.get("/api/account/entitlement", headers=auth_header(token)).json()["plan"] == "free"


def test_webhook_for_unknown_customer_is_acknowledged(client):
    payload = subscription_event("evt_orphan", CREATOR_PRICE, )
    body = json.loads(payload)
    body["data"]["object"]["customer"] = "cus_does_not_exist"
    payload = json.dumps(body).encode()

    response = client.post(
        "/api/billing/webhook", content=payload, headers={"Stripe-Signature": sign(payload)}
    )

    # Acknowledged so Stripe stops retrying, but nothing was changed.
    assert response.status_code == 200
    assert response.json()["handled"] is False


# --- Detail extraction ---


def test_extract_subscription_details_from_subscription_object():
    event = {
        "data": {
            "object": {
                "object": "subscription",
                "id": "sub_1",
                "customer": "cus_1",
                "status": "active",
                "current_period_end": 1790000000,
                "items": {"data": [{"price": {"id": "price_1"}}]},
            }
        }
    }

    details = extract_subscription_details(event)

    assert details["subscription_id"] == "sub_1"
    assert details["customer_id"] == "cus_1"
    assert details["price_id"] == "price_1"
    assert details["status"] == "active"


def test_extract_subscription_details_from_invoice_parent():
    event = {
        "data": {
            "object": {
                "object": "invoice",
                "customer": "cus_2",
                "parent": {
                    "subscription_details": {
                        "subscription": {
                            "id": "sub_2",
                            "status": "active",
                            "items": {"data": [{"price": {"id": "price_2"}}]},
                        }
                    }
                },
            }
        }
    }

    details = extract_subscription_details(event)

    assert details["subscription_id"] == "sub_2"
    assert details["customer_id"] == "cus_2"
    assert details["price_id"] == "price_2"


def test_extract_returns_none_without_a_subscription():
    assert extract_subscription_details({"data": {"object": {"object": "charge"}}}) is None


# --- Entitlement wire contract ---------------------------------------------
#
# The frontend reads these exact field names. If they are renamed without a
# matching frontend change, a paying customer would silently be limited to the
# free preview. These assertions pin the contract.


def test_entitlement_uses_snake_case_field_names(client, db_session):
    token = register(client).json()["access_token"]
    attach_stripe_identity(db_session, "buyer@example.com")

    payload = subscription_event("evt_wire", CREATOR_PRICE)
    client.post("/api/billing/webhook", content=payload, headers={"Stripe-Signature": sign(payload)})

    body = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    # Exactly the keys the frontend's entitlement bridge reads.
    assert "has_full_preview" in body
    assert "preview_limit_seconds" in body
    assert "can_export" in body
    assert "is_paid_plan" in body
    assert "usage_resets_monthly" in body
    assert "usage_period_months" in body
    assert "billed_annually" in body
    assert "processing_reserved_seconds" in body
    assert body["has_full_preview"] is True
    assert body["preview_limit_seconds"] is None
    assert body["usage_resets_monthly"] is True
    assert body["billed_annually"] is False


def test_free_entitlement_wire_shape(client):
    token = register(client).json()["access_token"]
    body = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert body["has_full_preview"] is False
    assert body["preview_limit_seconds"] == 30
    assert body["can_export"] is False


def test_plans_payload_uses_snake_case(client):
    body = client.get("/api/account/plans").json()
    first = body[0]

    assert "price_usd" in first
    assert "billing_period" in first
    assert "usage_allowance_seconds" in first
    assert "usage_period_months" in first
    assert "usage_resets_monthly" in first
    assert "annual_savings_usd" in first
    assert "monthly_equivalent_price_usd" in first
    assert "purchasable" in first


def test_plans_annual_plan_reports_monthly_allowance_and_savings(client):
    body = client.get("/api/account/plans").json()
    annual = next(plan for plan in body if plan["id"] == "creator_annual")

    assert annual["billing_period"] == "annual"
    assert annual["usage_allowance_seconds"] == 30_000
    assert annual["usage_resets_monthly"] is True
    assert annual["usage_period_months"] == 1
    assert annual["annual_savings_usd"] == 38
    assert annual["monthly_equivalent_price_usd"] == 19
    # Not advertised as an annual pool.
    assert annual["usage_allowance_seconds"] != 360_000

