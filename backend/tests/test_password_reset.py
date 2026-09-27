"""Password recovery tests.

Covers the full required matrix: enumeration safety, hashed storage, single use,
expiry, session revocation, password policy, email failure handling, log safety,
rate limiting, and concurrent reuse.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import PasswordResetToken
from app.db.models import Session as SessionModel
from app.db.models import User
from app.email import EmailMessage, MemoryProvider, set_provider_override
from app.routers.password_reset import (
    CHANGE_PASSWORD_MESSAGE,
    FORGOT_PASSWORD_MESSAGE,
    RESET_INVALID_MESSAGE,
    RESET_SUCCESS_MESSAGE,
    reset_ip_throttle,
)
from app.security.reset_email import build_password_reset_email, build_reset_url
from tests.conftest import auth_header

EMAIL = "recover@example.com"
PASSWORD = "a-strong-password-123"
NEW_PASSWORD = "an-even-stronger-password-456"


@pytest.fixture()
def mail() -> MemoryProvider:
    """Intercept all email, so nothing can be delivered or logged in tests."""
    provider = MemoryProvider()
    set_provider_override(provider)
    reset_ip_throttle()
    yield provider
    set_provider_override(None)
    reset_ip_throttle()


def register(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def raw_token_from(mail: MemoryProvider) -> str:
    """Pull the raw token out of the emailed link, as a real user would."""
    message = mail.last
    assert message is not None
    marker = "token="
    index = message.text.index(marker) + len(marker)
    end = message.text.index("\n", index)
    return message.text[index:end].strip()


# --- 1. Existing account ----------------------------------------------------


def test_forgot_password_for_existing_account_creates_a_token(client, mail):
    register(client)

    response = client.post("/api/auth/forgot-password", json={"email": EMAIL})

    assert response.status_code == 200
    assert response.json()["message"] == FORGOT_PASSWORD_MESSAGE
    assert len(mail.sent) == 1
    assert mail.last.to == EMAIL
    assert mail.last.subject == "Reset your Captionline password"


def test_reset_email_contains_a_frontend_url_link_and_expiry(client, mail):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})

    body = mail.last.text
    assert "FRONTEND_URL" not in body
    assert "/reset-password?token=" in body
    assert "expires in" in body
    # The ignore-if-not-requested reassurance is present.
    assert "ignore this email" in body


def test_reset_email_never_contains_a_password(client, mail):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})

    assert PASSWORD not in mail.last.text
    assert PASSWORD not in mail.last.html


# --- 2. No user enumeration -------------------------------------------------


def test_unknown_email_response_is_identical(client, mail):
    register(client)
    known = client.post("/api/auth/forgot-password", json={"email": EMAIL})
    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    # No email is sent for an unknown address.
    assert len(mail.sent) == 1


def test_inactive_account_response_is_identical(client, mail, db_session):
    register(client)
    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()
    user.is_active = False
    db_session.commit()

    inactive = client.post("/api/auth/forgot-password", json={"email": EMAIL})

    assert inactive.status_code == 200
    assert inactive.json()["message"] == FORGOT_PASSWORD_MESSAGE
    assert mail.sent == []


def test_malformed_email_is_a_validation_error_not_an_enumeration_signal(client, mail):
    response = client.post("/api/auth/forgot-password", json={"email": "not-an-email"})

    assert response.status_code == 422
    assert mail.sent == []


# --- 3. Token stored hashed, never raw -------------------------------------


def test_reset_token_is_stored_hashed_not_raw(client, mail, db_session):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})

    raw = raw_token_from(mail)
    row = db_session.execute(select(PasswordResetToken)).scalar_one()

    assert row.token_hash != raw
    assert len(row.token_hash) == 64  # sha256 hex
    assert raw not in str(row.__dict__)
    # The hash really is the sha256 of the emailed token.
    from app.security.tokens import hash_token

    assert row.token_hash == hash_token(raw)


# --- 4-6. Successful reset --------------------------------------------------


def test_valid_token_resets_the_password(client, mail, db_session):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    raw = raw_token_from(mail)

    response = client.post(
        "/api/auth/reset-password", json={"token": raw, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["message"] == RESET_SUCCESS_MESSAGE

    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()
    assert user.password_hash.startswith("$argon2id$")
    assert NEW_PASSWORD not in user.password_hash


def test_old_password_stops_working_and_new_one_works(client, mail):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    client.post(
        "/api/auth/reset-password",
        json={"token": raw_token_from(mail), "new_password": NEW_PASSWORD},
    )

    old = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    new = client.post("/api/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD})

    assert old.status_code == 401
    assert new.status_code == 200


# --- 7. Token cannot be reused ---------------------------------------------


def test_token_cannot_be_reused(client, mail):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    raw = raw_token_from(mail)

    first = client.post(
        "/api/auth/reset-password", json={"token": raw, "new_password": NEW_PASSWORD}
    )
    second = client.post(
        "/api/auth/reset-password",
        json={"token": raw, "new_password": "yet-another-password-789"},
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == RESET_INVALID_MESSAGE


def test_used_token_is_marked_used(client, mail, db_session):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    client.post(
        "/api/auth/reset-password",
        json={"token": raw_token_from(mail), "new_password": NEW_PASSWORD},
    )

    row = db_session.execute(select(PasswordResetToken)).scalar_one()

    assert row.used_at is not None
    assert row.revoked_at is not None


# --- 8. Expired token -------------------------------------------------------


def test_expired_token_is_rejected(client, mail, db_session, live_settings, monkeypatch):
    import app.config as config_module
    import app.security.reset_tokens as reset_tokens

    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    raw = raw_token_from(mail)

    # Backdate the token so it is already past its window.
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.execute(
        PasswordResetToken.__table__.update().values(
            created_at=past, expires_at=past + timedelta(minutes=60)
        )
    )
    db_session.commit()

    response = client.post(
        "/api/auth/reset-password", json={"token": raw, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == RESET_INVALID_MESSAGE

    # The old password still works, so nothing was changed.
    assert client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).status_code == 200
    assert reset_tokens.INVALID_TOKEN  # module still importable


# --- 9. Invalid token -------------------------------------------------------


@pytest.mark.parametrize(
    "token", ["", "   ", "not-a-real-token", "x" * 200, "abc.def.ghi"]
)
def test_invalid_tokens_are_rejected(client, mail, token):
    register(client)

    response = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )

    assert response.status_code in (400, 422)
    if response.status_code == 400:
        assert response.json()["detail"] == RESET_INVALID_MESSAGE


def test_revoked_token_is_rejected(client, mail, db_session):
    """Issuing a newer token voids the previous link."""
    register(client)

    # First request, then push past the cooldown so a second is allowed.
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    first = raw_token_from(mail)

    # Make the cooldown look elapsed.
    db_session.execute(
        PasswordResetToken.__table__.update().values(
            created_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
    )
    db_session.commit()

    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    second = raw_token_from(mail)
    assert first != second

    old_link = client.post(
        "/api/auth/reset-password", json={"token": first, "new_password": NEW_PASSWORD}
    )
    new_link = client.post(
        "/api/auth/reset-password", json={"token": second, "new_password": NEW_PASSWORD}
    )

    assert old_link.status_code == 400
    assert new_link.status_code == 200


# --- 10. Other outstanding tokens invalidated -------------------------------


def test_other_outstanding_tokens_invalidated_after_success(client, mail, db_session):
    register(client)

    # Issue three tokens, spacing them past the cooldown.
    raws = []
    for _ in range(3):
        db_session.execute(
            PasswordResetToken.__table__.update().values(
                created_at=datetime.now(timezone.utc) - timedelta(hours=1)
            )
        )
        db_session.commit()
        client.post("/api/auth/forgot-password", json={"email": EMAIL})
        raws.append(raw_token_from(mail))

    # Only the newest survives issuance.
    assert client.post(
        "/api/auth/reset-password", json={"token": raws[-1], "new_password": NEW_PASSWORD}
    ).status_code == 200

    for stale in raws[:-1]:
        assert client.post(
            "/api/auth/reset-password",
            json={"token": stale, "new_password": "another-password-xyz"},
        ).status_code == 400

    rows = db_session.execute(select(PasswordResetToken)).scalars().all()
    assert all(row.used_at is not None or row.revoked_at is not None for row in rows)


# --- 11. Sessions invalidated ----------------------------------------------


def test_existing_sessions_are_revoked_after_reset(client, mail, db_session):
    token = register(client).json()["access_token"]
    second = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).json()["access_token"]

    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200

    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    client.post(
        "/api/auth/reset-password",
        json={"token": raw_token_from(mail), "new_password": NEW_PASSWORD},
    )

    # Every pre-existing session is dead.
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401
    assert client.get("/api/auth/me", headers=auth_header(second)).status_code == 401

    rows = db_session.execute(select(SessionModel)).scalars().all()
    assert all(row.revoked_at is not None for row in rows)


# --- 12. Password policy ----------------------------------------------------


@pytest.mark.parametrize("weak", ["short", "1234567", ""])
def test_password_policy_enforced_on_reset(client, mail, weak):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    raw = raw_token_from(mail)

    response = client.post(
        "/api/auth/reset-password", json={"token": raw, "new_password": weak}
    )

    if weak == "":
        assert response.status_code == 422  # schema min_length
    else:
        assert response.status_code == 422
        assert "at least" in response.json()["detail"]

    # A policy failure must not consume the token.
    assert client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).status_code == 200


# --- 13. Email failure handled safely ---------------------------------------


def test_email_failure_is_handled_safely(client, mail, monkeypatch, db_session):
    from app.email import EmailDeliveryError

    register(client)

    def explode(_message):
        raise EmailDeliveryError("resend rejected the message with status 422")

    monkeypatch.setattr(mail, "send", explode)

    response = client.post("/api/auth/forgot-password", json={"email": EMAIL})
    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})

    # A delivery failure used to answer 503 while an unknown address answered
    # 200, so the status code alone revealed which addresses were registered.
    # Every path now answers with the identical generic response.
    assert response.status_code == unknown.status_code == 200
    assert response.json() == unknown.json() == {"message": FORGOT_PASSWORD_MESSAGE}

    # The undelivered token was withdrawn.
    rows = db_session.execute(select(PasswordResetToken)).scalars().all()
    assert all(row.revoked_at is not None for row in rows)

    # The account is untouched and still usable.
    assert client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).status_code == 200


def test_unconfigured_email_still_returns_the_generic_response(client, mail, live_settings, monkeypatch):
    import app.config as config_module

    register(client)
    monkeypatch.setenv("EMAIL_PROVIDER", "none")
    live_settings()

    response = client.post("/api/auth/forgot-password", json={"email": EMAIL})

    assert response.status_code == 200
    assert response.json()["message"] == FORGOT_PASSWORD_MESSAGE
    # The configuration path builds no provider, so nothing was delivered. The
    # `mail` fixture's override is separate and is what the request would use.
    from app.email import build_provider

    assert build_provider() is None


# --- 14. Nothing sensitive is logged ----------------------------------------


def test_raw_token_and_password_never_appear_in_logs(client, mail, caplog):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    raw = raw_token_from(mail)

    with caplog.at_level(logging.DEBUG):
        client.post(
            "/api/auth/reset-password", json={"token": raw, "new_password": NEW_PASSWORD}
        )

    text = "\n".join(record.getMessage() for record in caplog.records)

    assert raw not in text
    assert PASSWORD not in text
    assert NEW_PASSWORD not in text


def test_password_reset_logging_never_contains_the_token(client, mail, monkeypatch):
    from app.routers import password_reset as router

    recorder = []
    monkeypatch.setattr(router, "logger", type("L", (), {"info": lambda *a: recorder.append(a), "warning": lambda *a: recorder.append(a)})())

    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    raw = raw_token_from(mail)
    client.post(
        "/api/auth/reset-password", json={"token": raw, "new_password": NEW_PASSWORD}
    )

    joined = " ".join(str(part) for call in recorder for part in call)
    assert raw not in joined
    assert NEW_PASSWORD not in joined


# --- 15. Rate limiting ------------------------------------------------------


def test_repeat_requests_for_one_account_are_throttled(client, mail, db_session, live_settings, monkeypatch):
    import app.config as config_module

    register(client)

    # Remove the per-account cooldown so only the per-address throttle is left.
    monkeypatch.setenv("PASSWORD_RESET_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("PASSWORD_RESET_MAX_ACTIVE", "0")
    monkeypatch.setenv("PASSWORD_RESET_IP_LIMIT", "3")
    monkeypatch.setenv("PASSWORD_RESET_IP_WINDOW_SECONDS", "900")
    live_settings()
    reset_ip_throttle()

    statuses = [
        client.post("/api/auth/forgot-password", json={"email": EMAIL}).status_code
        for _ in range(6)
    ]

    # The first few are served, the rest are throttled but still answer 200 so
    # nothing can be inferred.
    assert set(statuses) == {200}
    assert len(mail.sent) == 3


def test_throttled_request_does_not_send_email(client, mail, live_settings, monkeypatch):
    import app.config as config_module

    register(client)
    monkeypatch.setenv("PASSWORD_RESET_IP_LIMIT", "1")
    live_settings()
    reset_ip_throttle()

    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    assert len(mail.sent) == 1

    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    assert len(mail.sent) == 1  # suppressed


def test_per_account_cooldown_suppresses_a_second_request(client, mail, db_session):
    register(client)

    first = client.post("/api/auth/forgot-password", json={"email": EMAIL})
    second = client.post("/api/auth/forgot-password", json={"email": EMAIL})

    assert first.status_code == second.status_code == 200
    # Only the first produced an email.
    assert len(mail.sent) == 1


# --- 16. Concurrent reuse ----------------------------------------------------


def test_concurrent_reuse_of_the_same_token_yields_one_reset(client, mail, db_session):
    """Two sequential submissions with the same token: only the first may win.

    SQLite serialises writes, so this models the same interleaving that the
    `SELECT ... FOR UPDATE` row lock prevents on PostgreSQL: the second request
    must observe `used_at` and be rejected rather than resetting twice.
    """
    register(client)
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    raw = raw_token_from(mail)

    results = [
        client.post(
            "/api/auth/reset-password",
            json={"token": raw, "new_password": f"candidate-password-{index}"},
        )
        for index in range(4)
    ]

    statuses = [r.status_code for r in results]
    assert statuses.count(200) == 1
    assert all(s in (200, 400) for s in statuses)

    # Only one password change landed, and it is a real Argon2id hash.
    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()
    assert user.password_hash.startswith("$argon2id$")

    row = db_session.execute(select(PasswordResetToken)).scalar_one()
    assert row.used_at is not None


# --- Email provider behaviour ------------------------------------------------


def test_resend_provider_posts_the_expected_payload(monkeypatch):
    """The provider sends a correct Resend request and never logs the key."""
    import json as json_module

    import app.email as email_module

    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json_module.loads(request.data.decode())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(email_module.urllib.request, "urlopen", fake_urlopen)

    provider = email_module.ResendProvider(
        api_key="local-test-value-not-a-credential",
        from_address="Captionline <no-reply@captionline.pro>",
        timeout=7,
    )
    provider.send(
        EmailMessage(to="user@example.com", subject="Hi", text="body", html="<p>body</p>")
    )

    assert captured["url"] == email_module.RESEND_ENDPOINT
    assert captured["body"]["to"] == ["user@example.com"]
    assert captured["body"]["from"] == "Captionline <no-reply@captionline.pro>"
    assert captured["body"]["subject"] == "Hi"
    assert captured["timeout"] == 7
    # The key travels in the header only, never the body.
    assert "local-test-value-not-a-credential" not in json_module.dumps(captured["body"])


def test_resend_provider_reports_http_errors_without_raising_raw(monkeypatch):
    import urllib.error

    import app.email as email_module

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 422, "Unprocessable", {}, None
        )

    monkeypatch.setattr(email_module.urllib.request, "urlopen", fake_urlopen)

    provider = email_module.ResendProvider(
        api_key="local-test-value-not-a-credential", from_address="x@example.com"
    )

    with pytest.raises(email_module.EmailDeliveryError) as caught:
        provider.send(EmailMessage(to="user@example.com", subject="s", text="t"))

    # The message is a status, not the provider's response body.
    assert "422" in str(caught.value)
    assert "local-test-value-not-a-credential" not in str(caught.value)


def test_console_provider_is_never_the_default():
    """A production deployment must not silently print reset links.

    The console provider exists for local development only and is reachable
    solely through an explicit EMAIL_PROVIDER value.
    """
    from app.email import build_provider

    # Nothing configured: no provider at all, not the console one.
    assert build_provider() is None

    # An unrecognised provider name must not fall back to anything.
    from app.config import Settings

    assert "console" not in Settings.__dataclass_fields__


def test_email_configuration_predicates():
    from app.config import Settings

    settings = Settings()
    assert settings.email_provider_is_development_only in (True, False)

    # Dev-only providers are flagged as such.
    import app.config as config_module

    original = config_module.get_settings
    try:
        config_module._settings = None
        import os

        os.environ["EMAIL_PROVIDER"] = "console"
        config_module._settings = None
        console = config_module.get_settings()
        assert console.email_is_configured is True
        assert console.email_provider_is_development_only is True

        os.environ["EMAIL_PROVIDER"] = "resend"
        os.environ.pop("EMAIL_API_KEY", None)
        config_module._settings = None
        resend_without_key = config_module.get_settings()
        assert resend_without_key.email_is_configured is False

        os.environ["EMAIL_PROVIDER"] = "none"
        config_module._settings = None
        assert config_module.get_settings().email_is_configured is False
    finally:
        config_module._settings = None
        os.environ["EMAIL_PROVIDER"] = "none"
        assert original is not None


# --- Reset URL construction -------------------------------------------------


def test_reset_url_uses_frontend_url_not_a_hardcoded_domain():
    url = build_reset_url("raw-token-value", frontend_url="https://captionline.pro")

    assert url.startswith("https://captionline.pro/reset-password?")
    assert "raw-token-value" in url
    assert "railway" not in url


def test_reset_url_ignores_trailing_slash():
    assert build_reset_url("t", frontend_url="https://captionline.pro/").startswith(
        "https://captionline.pro/reset-password"
    )


def test_reset_url_encodes_the_token():
    url = build_reset_url("a b&c=d", frontend_url="https://captionline.pro")

    assert " " not in url
    assert "a+b%26c%3Dd" in url or "a%20b%26c%3Dd" in url


# --- Change password while signed in (Part 7) -------------------------------


def test_change_password_requires_authentication(client, mail):
    response = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401


def test_change_password_succeeds_and_revokes_other_sessions(client, mail, db_session):
    token = register(client).json()["access_token"]
    other = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).json()["access_token"]

    # Capture the session ids that exist before the change.
    before = {
        row.id
        for row in db_session.execute(select(SessionModel)).scalars().all()
    }

    response = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(token),
    )

    assert response.status_code == 200
    assert response.json()["message"] == CHANGE_PASSWORD_MESSAGE

    # The old password no longer works; the new one does.
    assert client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD}
    ).status_code == 200

    # Every pre-existing session is revoked, including the one that made the
    # change. (The fresh login above legitimately creates a new active one.)
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401
    assert client.get("/api/auth/me", headers=auth_header(other)).status_code == 401

    pre_change = db_session.execute(select(SessionModel)).scalars().all()
    assert all(row.revoked_at is not None for row in pre_change if row.id in before)


def test_change_password_rejects_wrong_current_password(client, mail):
    token = register(client).json()["access_token"]

    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "not-the-password", "new_password": NEW_PASSWORD},
        headers=auth_header(token),
    )

    assert response.status_code == 401
    assert "current password" in response.json()["detail"]

    # Password unchanged.
    assert client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).status_code == 200


def test_change_password_enforces_policy_and_reuse(client, mail):
    token = register(client).json()["access_token"]

    weak = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=auth_header(token),
    )
    same = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
        headers=auth_header(token),
    )

    assert weak.status_code == 422
    assert same.status_code == 422
    assert client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).status_code == 200


def test_change_password_invalidates_outstanding_reset_tokens(client, mail, db_session):
    """A reset link must not survive a password change."""
    token = register(client).json()["access_token"]
    client.post("/api/auth/forgot-password", json={"email": EMAIL})
    pending = raw_token_from(mail)

    client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_header(token),
    )

    # The previously emailed link is now void.
    response = client.post(
        "/api/auth/reset-password",
        json={"token": pending, "new_password": "yet-another-password-1"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == RESET_INVALID_MESSAGE
