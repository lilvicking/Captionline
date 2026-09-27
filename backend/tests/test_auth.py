"""Account authentication and session tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import Session as SessionModel
from app.db.models import User
from app.plans import FREE_PLAN, FREE_PLAN_ID
from app.security.sessions import purge_expired_sessions
from tests.conftest import auth_header

EMAIL = "creator@example.com"
PASSWORD = "a-strong-password-123"


def register(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/auth/register", json={"email": email, "password": password})


# --- Registration ---


def test_register_creates_free_plan_account(client):
    response = register(client)

    assert response.status_code == 201
    body = response.json()

    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == EMAIL
    assert body["user"]["plan"] == FREE_PLAN_ID
    assert body["user"]["subscription_status"] == "none"
    assert body["user"]["is_active"] is True


def test_register_seeds_free_plan_entitlements(client, db_session):
    register(client)

    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()

    assert user.monthly_processing_allowance_seconds == FREE_PLAN.usage_allowance_seconds == 600
    # Free carries the same capabilities as every paid plan; only its monthly
    # processing allowance is smaller.
    assert user.preview_limit_seconds is None
    assert user.has_full_preview is True
    assert user.can_export is True
    assert user.processing_used_seconds == 0
    assert user.usage_period_ends_at > user.usage_period_started_at


def test_register_normalizes_email_case(client):
    register(client, email="MixedCase@Example.COM")

    response = client.post(
        "/api/auth/login", json={"email": "mixedcase@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200


def test_duplicate_email_is_rejected_with_409(client):
    assert register(client).status_code == 201

    duplicate = register(client)

    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_duplicate_email_with_different_password_still_rejected(client):
    register(client)

    assert register(client, password="another-password-999").status_code == 409


def test_short_password_is_rejected(client):
    assert register(client, password="short").status_code == 422


def test_invalid_email_is_rejected(client):
    assert register(client, email="not-an-email").status_code == 422


def test_plaintext_password_is_never_stored(client, db_session):
    register(client)

    stored = db_session.execute(
        select(User.password_hash).where(User.email == EMAIL)
    ).scalar_one()

    assert PASSWORD not in stored
    assert stored.startswith("$argon2id$")


# --- Login ---


def test_login_succeeds_with_correct_password(client):
    register(client)

    response = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_rejects_wrong_password(client):
    register(client)

    response = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong-password"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_login_unknown_email_is_indistinguishable_from_wrong_password(client):
    """Must not reveal whether an address is registered."""
    register(client)

    wrong_password = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": "wrong-password"}
    )
    unknown_email = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_login_issues_a_distinct_token_each_time(client):
    register(client)

    first = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    second = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert first.json()["access_token"] != second.json()["access_token"]


# --- Tokens and sessions ---


def test_token_is_stored_hashed_not_plaintext(client, db_session):
    token = register(client).json()["access_token"]

    stored = db_session.execute(select(SessionModel.token_hash)).scalar_one()

    assert stored != token
    assert len(stored) == 64  # sha256 hex


def test_me_requires_a_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_rejects_garbage_token(client):
    assert client.get("/api/auth/me", headers=auth_header("not-a-real-token")).status_code == 401


def test_me_rejects_non_bearer_scheme(client):
    token = register(client).json()["access_token"]

    response = client.get("/api/auth/me", headers={"Authorization": f"Basic {token}"})

    assert response.status_code == 401


def test_me_returns_the_authenticated_user(client):
    token = register(client).json()["access_token"]

    response = client.get("/api/auth/me", headers=auth_header(token))

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


def test_expired_session_is_rejected(client, db_session):
    token = register(client).json()["access_token"]

    session_row = db_session.execute(select(SessionModel)).scalar_one()
    session_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401


def test_revoked_session_is_rejected(client, db_session):
    token = register(client).json()["access_token"]

    session_row = db_session.execute(select(SessionModel)).scalar_one()
    session_row.revoked_at = datetime.now(timezone.utc)
    db_session.commit()

    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401


def test_inactive_account_is_rejected(client, db_session):
    token = register(client).json()["access_token"]

    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()
    user.is_active = False
    db_session.commit()

    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401


# --- Logout ---


def test_logout_invalidates_the_session(client):
    token = register(client).json()["access_token"]
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200

    assert client.post("/api/auth/logout", headers=auth_header(token)).status_code == 204
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401


def test_logout_only_invalidates_the_presented_token(client):
    first = register(client).json()["access_token"]
    second = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()[
        "access_token"
    ]

    client.post("/api/auth/logout", headers=auth_header(first))

    assert client.get("/api/auth/me", headers=auth_header(first)).status_code == 401
    assert client.get("/api/auth/me", headers=auth_header(second)).status_code == 200


def test_logging_in_again_after_logout_works(client):
    token = register(client).json()["access_token"]
    client.post("/api/auth/logout", headers=auth_header(token))

    again = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert again.status_code == 200
    assert client.get("/api/auth/me", headers=auth_header(again.json()["access_token"])).status_code == 200


# --- Session housekeeping ---


def test_purge_removes_long_expired_sessions(client, db_session):
    register(client)

    session_row = db_session.execute(select(SessionModel)).scalar_one()
    session_row.expires_at = datetime.now(timezone.utc) - timedelta(days=30)
    db_session.commit()

    assert purge_expired_sessions(db_session, older_than_days=7) == 1
    assert db_session.execute(select(SessionModel)).scalars().all() == []


def test_purge_keeps_recently_expired_sessions(client, db_session):
    """A just-expired session is kept so it reports 'expired' rather than unknown."""
    register(client)

    session_row = db_session.execute(select(SessionModel)).scalar_one()
    session_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()

    assert purge_expired_sessions(db_session, older_than_days=7) == 0
    assert len(db_session.execute(select(SessionModel)).scalars().all()) == 1


# --- Entitlement ---


def test_entitlement_requires_authentication(client):
    assert client.get("/api/account/entitlement").status_code == 401


def test_entitlement_returns_free_plan_values(client):
    token = register(client).json()["access_token"]

    body = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert body["plan"] == FREE_PLAN_ID
    assert body["plan_label"] == "Free"
    assert body["subscription_status"] == "none"
    assert body["is_paid_plan"] is False
    assert body["monthly_processing_allowance_seconds"] == 600
    assert body["processing_used_seconds"] == 0
    assert body["processing_remaining_seconds"] == 600
    # Free gets the full finished preview and the export entitlement.
    assert body["preview_limit_seconds"] is None
    assert body["has_full_preview"] is True
    assert body["can_export"] is True
    assert body["processing_allowance_minutes"] == 10.0


def test_entitlement_ignores_client_supplied_values(client):
    """Entitlement is derived from the account, never from the request.

    The spoofed fields are the ones a client would try to escalate. Since every
    plan now has the same capabilities, the escalation that matters is the
    monthly processing allowance.
    """
    token = register(client).json()["access_token"]

    body = client.get(
        "/api/account/entitlement",
        headers=auth_header(token),
        params={
            "plan": "pro_monthly",
            "has_full_preview": "true",
            "can_export": "true",
            "monthly_processing_allowance_seconds": "90000",
            "is_paid_plan": "true",
        },
    ).json()

    assert body["plan"] == "free"
    assert body["is_paid_plan"] is False
    assert body["monthly_processing_allowance_seconds"] == 600
    assert body["processing_remaining_seconds"] == 600


# --- Health ---


def test_health_reports_database_without_leaking_credentials(client):
    import json as json_module

    response = client.get("/api/health")
    body = response.json()

    assert response.status_code == 200
    assert body["database"] == {"configured": True, "reachable": True, "status": "ok"}

    assert set(body["database"]) == {"configured", "reachable", "status"}
    serialised = response.text
    assert "sqlite" not in serialised.lower()
    assert "://" not in serialised
    assert "password" not in serialised.lower()
    assert json_module.dumps(body["stripe"])


# --- No database configured ---


def test_account_routes_return_503_when_no_database(monkeypatch):
    """A missing DATABASE_URL must be a clean 503, not an unhandled error."""
    from fastapi.testclient import TestClient

    import app.main as main_module
    import app.security.deps as deps_module
    from app.db import session as session_module
    from app.main import app

    monkeypatch.setattr(main_module, "is_configured", lambda: False)
    monkeypatch.setattr(deps_module, "is_configured", lambda: False)
    monkeypatch.setattr(session_module, "get_session_factory", lambda: None)

    with TestClient(app, raise_server_exceptions=False) as no_db_client:
        health = no_db_client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["database"]["status"] == "not_configured"

        for method, path, payload in [
            ("post", "/api/auth/register", {"email": "a@b.com", "password": "password123"}),
            ("post", "/api/auth/login", {"email": "a@b.com", "password": "password123"}),
            ("get", "/api/auth/me", None),
            ("get", "/api/account/entitlement", None),
            ("post", "/api/billing/checkout", {"plan": "creator_monthly"}),
        ]:
            response = (
                no_db_client.post(path, json=payload)
                if method == "post"
                else no_db_client.get(path)
            )
            assert response.status_code == 503, f"{path} returned {response.status_code}"
