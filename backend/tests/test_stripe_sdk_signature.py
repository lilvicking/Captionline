"""Regression test for the Stripe SDK call signature.

The production failure was:

    TypeError: SessionService.create() got an unexpected keyword argument 'mode'

caused by calling ``client.checkout.sessions.create(**params)``. The typed params
object is a single positional argument, because the real signature is
``create(params, options)``.

These tests drive the **real installed Stripe library** with a stubbed transport,
so the SDK performs its genuine argument validation. No network request is made and
no live charge can occur.
"""

from __future__ import annotations

import json

import pytest
import stripe

import app.stripe_client as stripe_client
from app.plans import reset_price_mapping
from app.stripe_client import build_checkout_session, build_portal_session
from tests.conftest import auth_header


class RecordingTransport:
    """Stub HTTP client. Records requests and returns a canned Stripe response.

    Implements the small surface the SDK actually uses, so real request building and
    parameter validation still run.
    """

    name = "recording-transport"

    def __init__(self, response: dict):
        self._response = response
        self.calls: list[dict] = []

    def request_with_retries(
        self, method, url, headers, post_data=None, max_network_retries=0, **kwargs
    ):
        # The SDK passes extra internals such as `_usage`; accept and ignore them
        # so this stub matches the real client interface.
        if post_data is None:
            body = None
        elif isinstance(post_data, (bytes, bytearray)):
            body = post_data.decode("utf-8", "replace")
        else:
            body = str(post_data)

        self.calls.append({"method": method, "url": url, "body": body})
        return json.dumps(self._response), 200, {}


@pytest.fixture()
def stripe_env(monkeypatch, live_settings):
    """Configure Stripe environment and capture the transport the client builds."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "local-test-value-not-a-credential")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "local-test-webhook-value-not-a-credential")
    monkeypatch.setenv("STRIPE_PRICE_CREATOR_MONTHLY", "test-price-creator-monthly")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "test-price-pro-monthly")
    monkeypatch.setenv("STRIPE_PRICE_CREATOR_ANNUAL", "test-price-creator-annual")
    live_settings()

    stripe_client.refresh_price_mapping()
    yield
    reset_price_mapping()
    live_settings()


def patched_client(response: dict, monkeypatch) -> RecordingTransport:
    """Return a client whose transport is stubbed, still built by real SDK code."""
    transport = RecordingTransport(response)

    real_client = stripe.StripeClient

    def factory(api_key, **kwargs):
        kwargs["http_client"] = transport
        return real_client(api_key, **kwargs)

    monkeypatch.setattr(stripe_client.stripe, "StripeClient", factory)
    return transport


# --- The exact regression ----------------------------------------------------


def test_checkout_params_are_passed_positionally_not_as_keywords(
    stripe_env, monkeypatch
):
    """THE REGRESSION: expanding params into keywords raises TypeError.

    Against the real SDK this fails with
    "SessionService.create() got an unexpected keyword argument 'mode'" if the
    implementation reverts to create(**params).
    """
    transport = patched_client(
        {"id": "cs_test_123", "url": "https://checkout.stripe.com/session"}, monkeypatch
    )

    result = build_checkout_session(
        customer_email="user@example.com",
        plan_id="creator_monthly",
        stripe_customer_id=None,
        success_url="https://example.com/?checkout=success",
        cancel_url="https://example.com/?checkout=cancelled",
    )

    assert result["id"] == "cs_test_123"
    assert result["url"] == "https://checkout.stripe.com/session"

    # The request really was made, and carried the plan's Price.
    assert len(transport.calls) == 1
    body = transport.calls[0]["body"] or ""
    assert "mode=subscription" in body
    assert "test-price-creator-monthly" in body


def test_portal_params_are_passed_positionally_not_as_keywords(stripe_env, monkeypatch):
    """The Customer Portal had the identical bug and must stay fixed."""
    transport = patched_client(
        {"id": "bps_test_123", "url": "https://billing.stripe.com/session"}, monkeypatch
    )

    result = build_portal_session(
        customer_id="cus_test_123", return_url="https://example.com/"
    )

    assert result["url"] == "https://billing.stripe.com/session"
    assert len(transport.calls) == 1
    body = transport.calls[0]["body"] or ""
    assert "cus_test_123" in body


@pytest.mark.parametrize(
    "plan_id,expected_price",
    [
        ("creator_monthly", "test-price-creator-monthly"),
        ("pro_monthly", "test-price-pro-monthly"),
        ("creator_annual", "test-price-creator-annual"),
    ],
)
def test_every_plan_id_creates_a_session(
    stripe_env, monkeypatch, plan_id, expected_price
):
    """All three paid plans must still reach Stripe with the right Price."""
    transport = patched_client(
        {"id": "cs_test_123", "url": "https://checkout.stripe.com/session"}, monkeypatch
    )

    result = build_checkout_session(
        customer_email="user@example.com",
        plan_id=plan_id,
        stripe_customer_id=None,
        success_url="https://example.com/s",
        cancel_url="https://example.com/c",
    )

    assert result["id"] == "cs_test_123"
    body = transport.calls[0]["body"] or ""
    assert expected_price in body
    # The internal plan id is forwarded for reconciliation; the client never
    # supplies a price or amount.
    assert plan_id in body


def test_existing_customer_id_is_sent_instead_of_email(stripe_env, monkeypatch):
    transport = patched_client(
        {"id": "cs_test_123", "url": "https://checkout.stripe.com/session"}, monkeypatch
    )

    build_checkout_session(
        customer_email="user@example.com",
        plan_id="pro_monthly",
        stripe_customer_id="cus_existing",
        success_url="https://example.com/s",
        cancel_url="https://example.com/c",
    )

    body = transport.calls[0]["body"] or ""
    assert "cus_existing" in body
    assert "customer_email" not in body


# --- Signature guard ---------------------------------------------------------


def test_sdk_create_signature_is_params_and_options():
    """Documents why positional params are required.

    If a future SDK upgrade changes the signature, this fails loudly instead of
    silently breaking checkout in production again.
    """
    client = stripe.StripeClient("sk_test_dummy")
    parameters = list(
        __import__("inspect").signature(client.v1.checkout.sessions.create).parameters
    )
    assert parameters[:2] == ["params", "options"]


def test_keyword_expansion_would_fail_against_real_sdk():
    """Proves the old call shape is invalid, so the fix cannot silently regress."""
    client = stripe.StripeClient("sk_test_dummy")

    with pytest.raises(TypeError) as caught:
        client.v1.checkout.sessions.create(mode="subscription")

    assert "unexpected keyword argument 'mode'" in str(caught.value)


# --- Sanitized failure logging ----------------------------------------------
#
# Assertions target the sanitizer directly and stub the module logger, because
# the pytest logging plugin in this environment does not surface records attached
# to application loggers. The behaviour under test is the message content and the
# call itself, both of which are verifiable without depending on handler plumbing.


class RecordingLogger:
    """Stands in for the module logger and records formatted warnings."""

    def __init__(self):
        self.warnings: list[tuple] = []

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)


def test_stripe_failure_logging_records_class_and_operation(monkeypatch):
    """A future SDK failure must be diagnosable from the logs."""
    from app.routers import billing

    recorder = RecordingLogger()
    monkeypatch.setattr(billing, "logger", recorder)

    boom = TypeError("SessionService.create() got an unexpected keyword argument 'mode'")
    billing._log_stripe_failure("checkout", "creator_monthly", boom)

    record = recorder.warnings[-1]
    assert "checkout" in record
    assert "creator_monthly" in record
    assert "TypeError" in record
    assert "unexpected keyword argument" in record


def test_stripe_failure_logging_never_leaks_sensitive_detail(monkeypatch):
    """Truncation must drop anything past the first clause."""
    from app.routers import billing

    recorder = RecordingLogger()
    monkeypatch.setattr(billing, "logger", recorder)

    boom = RuntimeError(
        "Request failed for " + "sk_" + "live_realsecretvalue123. "
        "customer email " + "user" + "@example.com. "
        "Bearer " + "ey" + "JhbGciOiJIUzI1NiJ9.payloadvalue.sigvalue"
    )
    billing._log_stripe_failure("portal", "pro_monthly", boom)

    record = recorder.warnings[-1]
    assert "sk_" + "live_realsecretvalue123" not in record
    assert "ey" + "JhbGciOiJIUzI1NiJ9" not in record
    assert "user" + "@example.com" not in record
    # The diagnosable part survives.
    assert "RuntimeError" in record
    assert "Request failed" in record
    assert "pro_monthly" in record


@pytest.mark.parametrize(
    "exception,expected",
    [
        (TypeError("boom. trailing secret"), "TypeError: boom"),
        (RuntimeError("single clause"), "RuntimeError: single clause"),
        (TypeError(""), "TypeError"),
        (ValueError("first. second. third"), "ValueError: first"),
    ],
)
def test_safe_stripe_message_truncation(exception, expected):
    """The sanitizer keeps the first clause and always names the exception class."""
    from app.routers.billing import _safe_stripe_message

    assert _safe_stripe_message(exception) == expected


@pytest.mark.parametrize(
    "leaked",
    [
        # Assembled at runtime so these key-shaped values never appear as literals
        # in the repository, where secret scanners would flag them. The strings are
        # still exactly the shape the redaction patterns must match.
        "sk_" + "live_" + "51Hxxxxxxxxxxxxxxxxxxxx",
        "sk_" + "test_" + "51Hxxxxxxxxxxxxxxxxxxxx",
        "wh" + "sec_" + "abcdefghijklmnop",
        "ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sigvalue",
        "4242 4242 4242 4242",
        "4242424242424242",
        "customer" + "@example.com",
    ],
)
def test_safe_stripe_message_redacts_sensitive_values(leaked):
    """A secret inside the first clause must still be redacted.

    Stripe puts the offending value in the first sentence for errors such as
    "Invalid API Key provided: sk_live_...", so truncation alone is insufficient.
    """
    from app.routers.billing import _safe_stripe_message

    message = _safe_stripe_message(RuntimeError(f"Request failed: {leaked}. Retry later."))

    assert leaked not in message
    assert "REDACTED" in message
    # The diagnostic prefix is preserved.
    assert "RuntimeError" in message
    assert "Request failed" in message


def test_safe_stripe_message_redacts_bearer_tokens():
    from app.routers.billing import _safe_stripe_message

    token = "ey" + "JhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payloadvalue.signaturevalue"
    message = _safe_stripe_message(RuntimeError(f"Auth failed with Bearer {token}."))

    assert token not in message
    assert "REDACTED" in message


def test_safe_stripe_message_caps_length():
    """A single very long clause is still bounded."""
    from app.routers.billing import _safe_stripe_message

    result = _safe_stripe_message(RuntimeError("x" * 5000))

    assert len(result) <= 220
    assert result.startswith("RuntimeError: ")


def test_public_error_response_stays_sanitized(client, stripe_env, monkeypatch):
    """The client must never receive SDK internals."""
    token = client.post(
        "/api/auth/register",
        json={"email": "leaky@example.com", "password": "a-strong-password-123"},
    ).json()["access_token"]

    # Assembled at runtime so no key-shaped literal is stored in the repository.
    leaked = "sk_" + "live_secret_abc123"

    def explode(**_kwargs):
        raise TypeError(f"SessionService.create() failed with {leaked}")

    monkeypatch.setattr("app.routers.billing.build_checkout_session", explode)

    response = client.post(
        "/api/billing/checkout",
        json={"plan": "creator_monthly"},
        headers=auth_header(token),
    )

    assert response.status_code == 502
    body = response.text
    assert leaked not in body
    assert "TypeError" not in body
    assert "SessionService" not in body
    assert "Checkout is temporarily unavailable" in body
