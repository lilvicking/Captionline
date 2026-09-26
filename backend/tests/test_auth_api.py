"""API tests for registration, login, sessions, and entitlement.

These exercise the real Alembic migration and the real SQLAlchemy models.
"""

from __future__ import annotations

from sqlalchemy import select, text

from app.db.models import Session as SessionModel
from app.db.models import User
from app.db.session import get_engine
from app.plans import FREE_PLAN
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
    assert body["user"]["plan"] == "free"
    assert body["user"]["subscription_status"] == "none"
    assert body["user"]["is_active"] is True


def test_register_seeds_free_plan_entitlements(client, db_session):
    register(client)

    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()

    assert user.monthly_processing_allowance_seconds == FREE_PLAN.monthly_processing_seconds == 600
    assert user.preview_limit_seconds == FREE_PLAN.preview_limit_seconds == 30
    assert user.has_full_preview is False
    assert user.can_export is False
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


def test_duplicate_email_different_password_still_rejected(client):
    register(client)
    duplicate = register(client, password="another-password-999")

    assert duplicate.status_code == 409


def test_short_password_is_rejected(client):
    response = register(client, password="short")

    assert response.status_code == 422


def test_invalid_email_is_rejected(client):
    response = register(client, email="not-an-email")

    assert response.status_code == 422


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

    response = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_login_unknown_email_returns_same_error_as_wrong_password(client):
    register(client)

    wrong_password = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": "wrong-password"}
    )
    unknown_email = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    # Identical responses avoid leaking which emails are registered.
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_login_issues_a_distinct_token_each_time(client):
    register(client)
    first = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    second = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert first.json()["access_token"] != second.json()["access_token"]


# --- Token handling ---


def test_token_is_stored_hashed_not_plaintext(client, db_session):
    token = register(client).json()["access_token"]

    stored = db_session.execute(select(SessionModel.token_hash)).scalar_one()

    assert stored != token
    assert len(stored) == 64  # sha256 hex


def test_me_requires_a_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_rejects_a_garbage_token(client):
    response = client.get("/api/auth/me", headers=auth_header("not-a-real-token"))

    assert response.status_code == 401


def test_me_rejects_a_non_bearer_scheme(client):
    token = register(client).json()["access_token"]
    response = client.get("/api/auth/me", headers={"Authorization": f"Basic {token}"})

    assert response.status_code == 401


def test_me_returns_the_authenticated_user(client):
    token = register(client).json()["access_token"]

    response = client.get("/api/auth/me", headers=auth_header(token))

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL
    assert response.json()["plan"] == "free"


# --- Logout / invalidation ---


def test_logout_invalidates_the_session(client):
    token = register(client).json()["access_token"]
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200

    assert client.post("/api/auth/logout", headers=auth_header(token)).status_code == 204

    after = client.get("/api/auth/me", headers=auth_header(token))
    assert after.status_code == 401


def test_logout_only_invalidates_the_presented_token(client):
    first = register(client).json()["access_token"]
    second = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).json()["access_token"]

    client.post("/api/auth/logout", headers=auth_header(first))

    assert client.get("/api/auth/me", headers=auth_header(first)).status_code == 401
    assert client.get("/api/auth/me", headers=auth_header(second)).status_code == 200


# --- Entitlement ---


def test_entitlement_requires_authentication(client):
    assert client.get("/api/account/entitlement").status_code == 401


def test_entitlement_returns_free_plan_values(client):
    token = register(client).json()["access_token"]

    response = client.get("/api/account/entitlement", headers=auth_header(token))

    assert response.status_code == 200
    body = response.json()

    assert body["plan"] == "free"
    assert body["plan_label"] == "Free"
    assert body["subscription_status"] == "none"
    assert body["monthly_processing_allowance_seconds"] == 600
    assert body["processing_used_seconds"] == 0
    assert body["processing_remaining_seconds"] == 600
    assert body["preview_limit_seconds"] == 30
    assert body["has_full_preview"] is False
    assert body["can_export"] is False
    assert body["processing_allowance_minutes"] == 10.0
    assert body["processing_remaining_minutes"] == 10.0


def test_entitlement_reflects_recorded_usage(client, db_session):
    token = register(client).json()["access_token"]

    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()
    user.processing_used_seconds = 192
    db_session.commit()

    body = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert body["processing_used_seconds"] == 192
    assert body["processing_remaining_seconds"] == 408
    assert body["processing_used_minutes"] == 3.2
    assert body["processing_remaining_minutes"] == 6.8


def test_entitlement_ignores_client_supplied_values(client):
    """Entitlement must come from the database, not the request."""
    token = register(client).json()["access_token"]

    response = client.get(
        "/api/account/entitlement",
        headers=auth_header(token),
        params={"plan": "enterprise", "has_full_preview": "true", "can_export": "true"},
    )

    body = response.json()
    assert body["plan"] == "free"
    assert body["has_full_preview"] is False
    assert body["can_export"] is False


# --- Health ---


def test_health_reports_database_without_leaking_credentials(client):
    response = client.get("/api/health")
    body = response.json()

    assert response.status_code == 200
    assert body["database"]["configured"] is True
    assert body["database"]["reachable"] is True
    assert body["database"]["status"] == "ok"

    # No connection string, credentials, or driver details may be exposed.
    assert set(body["database"]) == {"configured", "reachable", "status"}
    serialised = response.text
    assert "sqlite" not in serialised.lower()
    assert "://" not in serialised
    assert "password" not in serialised.lower()


# --- Transcription must stay unauthenticated in Phase 3A ---


def test_transcribe_does_not_require_auth(client):
    """Phase 3A must not gate transcription behind login."""
    no_file = client.post("/api/transcribe")
    assert no_file.status_code == 422  # missing file, not 401


# --- Behaviour with no database configured ---


def test_account_routes_return_503_when_no_database(monkeypatch):
    """A missing DATABASE_URL must be a clean 503, not an unhandled error.

    The database dependency resolves before the route body, so this guards
    against a bare RuntimeError escaping as a 500.
    """
    from fastapi.testclient import TestClient

    import app.main as main_module
    import app.security.deps as deps_module
    from app.db import session as session_module
    from app.main import app

    # These modules import `is_configured` / `get_session_factory` by name, so
    # each reference has to be patched where it is actually used.
    monkeypatch.setattr(main_module, "is_configured", lambda: False)
    monkeypatch.setattr(deps_module, "is_configured", lambda: False)
    monkeypatch.setattr(session_module, "get_session_factory", lambda: None)

    with TestClient(app, raise_server_exceptions=False) as no_db_client:
        health = no_db_client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["database"] == {
            "configured": False,
            "reachable": False,
            "status": "not_configured",
        }

        for method, path, payload in [
            ("post", "/api/auth/register", {"email": "a@b.com", "password": "password123"}),
            ("post", "/api/auth/login", {"email": "a@b.com", "password": "password123"}),
            ("get", "/api/auth/me", None),
            ("get", "/api/account/entitlement", None),
        ]:
            if method == "post":
                response = no_db_client.post(path, json=payload)
            else:
                response = no_db_client.get(path)

            assert response.status_code == 503, f"{path} returned {response.status_code}"
            assert "no database is configured" in response.json()["detail"]
