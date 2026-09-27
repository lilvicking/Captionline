"""Account deletion and legal consent tests.

Deletion is irreversible, so the emphasis is on what must *not* happen: an
unauthenticated caller, a wrong password, a missing confirmation, or an account
with a live subscription must all leave the account and its data completely
untouched. Consent is tested in the opposite direction, to prove the backend only
records what it is told and never locks anybody out for the absence of it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.db.models import RESERVATION_RESERVED, PasswordResetToken
from app.db.models import Session as SessionModel
from app.db.models import UsageReservation, User
from app.routers.account import (
    DELETION_BLOCKED_BY_SUBSCRIPTION,
    DELETION_CONFIRMATION,
    DELETION_CONFIRMATION_REQUIRED,
    DELETION_FAILED,
    DELETION_MESSAGE,
    DELETION_PASSWORD_INCORRECT,
)
from app.security.tokens import hash_token
from app.terms import (
    GOVERNING_LAW_PLACEHOLDER,
    PRIVACY_EFFECTIVE_DATE,
    PRIVACY_VERSION,
    SUPPORT_EMAIL,
    TERMS_EFFECTIVE_DATE,
    TERMS_VERSION,
)
from tests.conftest import auth_header

EMAIL = "delete-me@example.com"
OTHER_EMAIL = "someone-else@example.com"
PASSWORD = "a-strong-password-123"
DELETE_PATH = "/api/account/delete"


def register(client, email=EMAIL, password=PASSWORD, **extra):
    return client.post(
        "/api/auth/register", json={"email": email, "password": password, **extra}
    )


def login(client, email=EMAIL, password=PASSWORD) -> str:
    """A signed-in session token, as the browser would hold it."""
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def delete(client, token, *, password=PASSWORD, confirmation=DELETION_CONFIRMATION):
    body = {"current_password": password, "confirmation": confirmation}
    return client.post(DELETE_PATH, json=body, headers=auth_header(token))


def counts(db_session) -> tuple[int, int, int, int]:
    """Row counts for accounts and everything an account owns."""
    return (
        db_session.execute(select(func.count()).select_from(User)).scalar_one(),
        db_session.execute(select(func.count()).select_from(SessionModel)).scalar_one(),
        db_session.execute(
            select(func.count()).select_from(PasswordResetToken)
        ).scalar_one(),
        db_session.execute(
            select(func.count()).select_from(UsageReservation)
        ).scalar_one(),
    )


def give_owned_rows(db_session, email=EMAIL) -> None:
    """Give the account a second session, a live reset token, and a reservation."""
    user = db_session.execute(select(User).where(User.email == email)).scalar_one()
    now = datetime.now(timezone.utc)

    db_session.add(
        SessionModel(
            user_id=user.id,
            token_hash=hash_token("second-session-token"),
            expires_at=now + timedelta(days=1),
        )
    )
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token("outstanding-reset-token"),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    db_session.add(
        UsageReservation(
            user_id=user.id,
            reserved_seconds=42,
            status=RESERVATION_RESERVED,
            created_at=now,
        )
    )
    db_session.commit()


def set_subscription(db_session, status_value: str, external_id: str | None) -> None:
    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()
    user.subscription_status = status_value
    user.subscription_external_id = external_id
    user.subscription_provider = "stripe" if external_id else None
    db_session.commit()


# --- 1. Authentication ------------------------------------------------------


def test_delete_requires_authentication(client):
    response = client.post(
        DELETE_PATH, json={"current_password": PASSWORD, "confirmation": "DELETE"}
    )

    assert response.status_code == 401


def test_delete_rejects_a_revoked_session(client, db_session):
    token = register(client).json()["access_token"]
    client.post("/api/auth/logout", headers=auth_header(token))

    assert delete(client, token).status_code == 401
    assert counts(db_session)[0] == 1


def test_delete_rejects_a_garbage_token(client):
    register(client)

    response = client.post(
        DELETE_PATH,
        json={"current_password": PASSWORD, "confirmation": "DELETE"},
        headers=auth_header("not-a-real-token"),
    )

    assert response.status_code == 401


# --- 2. Password and confirmation -------------------------------------------


def test_delete_rejects_wrong_current_password(client, db_session):
    token = register(client).json()["access_token"]

    response = delete(client, token, password="not-the-password")

    assert response.status_code == 401
    assert response.json()["detail"] == DELETION_PASSWORD_INCORRECT
    # Nothing was touched, and the session still works.
    assert counts(db_session)[0] == 1
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200


def test_delete_rejects_wrong_confirmation(client, db_session):
    token = register(client).json()["access_token"]

    response = delete(client, token, confirmation="delete")

    assert response.status_code == 400
    assert response.json()["detail"] == DELETION_CONFIRMATION_REQUIRED
    assert counts(db_session)[0] == 1


def test_delete_rejects_missing_confirmation(client, db_session):
    """A missing confirmation is refused with the endpoint's own explanation.

    Not a 422: the field defaults to an empty string precisely so the caller is
    told what to type instead of receiving a schema error about a body shape.
    """
    token = register(client).json()["access_token"]

    response = client.post(
        DELETE_PATH, json={"current_password": PASSWORD}, headers=auth_header(token)
    )

    assert response.status_code == 400
    assert response.json()["detail"] == DELETION_CONFIRMATION_REQUIRED
    assert counts(db_session)[0] == 1


def test_a_valid_session_alone_cannot_destroy_an_account(client, db_session):
    """A hijacked or replayed token is not sufficient without the password."""
    token = register(client).json()["access_token"]

    assert delete(client, token, password="guess-the-password").status_code == 401
    assert counts(db_session)[0] == 1


def test_confirmation_is_checked_before_the_password_is_hashed(client):
    """Order matters only for cost: a bad confirmation skips Argon2id entirely."""
    token = register(client).json()["access_token"]

    response = delete(client, token, password="also-wrong", confirmation="nope")

    assert response.status_code == 400
    assert response.json()["detail"] == DELETION_CONFIRMATION_REQUIRED


# --- 3. The billing rule ----------------------------------------------------


@pytest.mark.parametrize("status_value", ["active", "trialing"])
def test_active_subscription_blocks_deletion(client, db_session, status_value):
    token = register(client).json()["access_token"]
    set_subscription(db_session, status_value, "cus_1234567890")

    response = delete(client, token)

    assert response.status_code == 409
    assert response.json()["detail"] == DELETION_BLOCKED_BY_SUBSCRIPTION
    # The account survives intact and the caller is still signed in.
    assert counts(db_session) == (1, 1, 0, 0)
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200


def test_blocked_deletion_makes_no_stripe_call(client, db_session, monkeypatch):
    """Blocking is the whole mechanism: no Stripe cancel or modify is attempted.

    The architecture is portal-based cancellation, so a server-side cancel would
    be a second, unspecified path to the same state, and one that can fail after
    the local transaction has committed with no way to roll the two back
    together. Every function the Stripe client exposes is replaced with one that
    fails the test, so a future attempt to call into Stripe here is caught.
    """
    import inspect

    from app import stripe_client

    def explode(name):
        def _boom(*args, **kwargs):
            raise AssertionError(f"deletion must not call Stripe: {name}")

        return _boom

    replaced = []
    for name in dir(stripe_client):
        attribute = getattr(stripe_client, name)
        if inspect.isfunction(attribute) and attribute.__module__ == stripe_client.__name__:
            monkeypatch.setattr(stripe_client, name, explode(name))
            replaced.append(name)

    assert replaced, "expected stripe_client to expose module-level functions"

    token = register(client).json()["access_token"]
    set_subscription(db_session, "active", "cus_1234567890")

    assert delete(client, token).status_code == 409


def test_no_provider_reference_does_not_block_deletion(client, db_session):
    """An active status with no Stripe id is a half-applied webhook.

    It is not a live subscription, and a customer must not be locked out of
    deleting their account because one webhook landed incomplete.
    """
    token = register(client).json()["access_token"]
    set_subscription(db_session, "active", None)

    assert delete(client, token).status_code == 200
    assert counts(db_session)[0] == 0


@pytest.mark.parametrize(
    "status_value", ["canceled", "past_due", "unpaid", "incomplete", "none"]
)
def test_inactive_subscription_does_not_block_deletion(client, db_session, status_value):
    token = register(client).json()["access_token"]
    set_subscription(db_session, status_value, "cus_1234567890")

    assert delete(client, token).status_code == 200
    assert counts(db_session)[0] == 0


# --- 4. Successful deletion -------------------------------------------------


def test_successful_deletion_removes_the_account_and_everything_it_owns(
    client, db_session
):
    token = register(client).json()["access_token"]
    give_owned_rows(db_session)

    assert counts(db_session) == (1, 2, 1, 1)

    response = delete(client, token)

    assert response.status_code == 200
    assert response.json()["message"] == DELETION_MESSAGE
    # A machine-readable flag for a client that keys off a field, not prose.
    assert response.json()["deleted"] is True
    # The customer is told that Stripe keeps its own financial records.
    assert "Stripe" in response.json()["stripe_data_note"]

    # The account and every row it owned are gone. The reservation is the one
    # that depends on the ORM cascade rather than on database enforcement.
    assert counts(db_session) == (0, 0, 0, 0)


def test_deletion_leaves_other_accounts_alone(client, db_session):
    other = register(client, email=OTHER_EMAIL).json()["access_token"]
    token = register(client).json()["access_token"]
    give_owned_rows(db_session, email=EMAIL)

    assert delete(client, token).status_code == 200

    assert (
        db_session.execute(
            select(func.count()).select_from(User).where(User.email == OTHER_EMAIL)
        ).scalar_one()
        == 1
    )
    assert client.get("/api/auth/me", headers=auth_header(other)).status_code == 200


def test_the_deleted_users_session_no_longer_authenticates(client):
    token = register(client).json()["access_token"]
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200

    assert delete(client, token).status_code == 200

    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401
    assert (
        client.get("/api/account/entitlement", headers=auth_header(token)).status_code
        == 401
    )


def test_the_password_no_longer_works_after_deletion(client):
    register(client)
    assert delete(client, login(client)).status_code == 200

    response = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 401


def test_registering_again_with_the_same_email_succeeds_after_deletion(
    client, db_session
):
    register(client)
    assert delete(client, login(client)).status_code == 200

    # The unique index is genuinely freed, not merely hidden.
    assert counts(db_session)[0] == 0

    again = register(client)

    assert again.status_code == 201
    assert again.json()["user"]["email"] == EMAIL
    assert counts(db_session)[0] == 1


# --- 5. Nothing sensitive is echoed or logged --------------------------------


def test_response_never_contains_a_submitted_password_or_confirmation(client):
    token = register(client).json()["access_token"]

    # Every outcome, refusals included, must be free of submitted values.
    for password, confirmation in [
        (PASSWORD, DELETION_CONFIRMATION),
        ("wrong-password-value", DELETION_CONFIRMATION),
        (PASSWORD, "SOMETHING-ELSE"),
    ]:
        response = client.post(
            DELETE_PATH,
            json={"current_password": password, "confirmation": confirmation},
            headers=auth_header(token),
        )
        assert password not in response.text
        assert confirmation not in response.text


def test_refusals_never_echo_the_submitted_values(client):
    token = register(client).json()["access_token"]

    wrong_password = delete(client, token, password="my-guess-is-secret-value")
    wrong_confirmation = delete(client, token, confirmation="MY-SECRET-TYPING")

    for response in (wrong_password, wrong_confirmation):
        assert "my-guess-is-secret-value" not in response.text
        assert "MY-SECRET-TYPING" not in response.text
        assert PASSWORD not in response.text


def test_deletion_logging_never_contains_credentials(client, monkeypatch):
    """Only the user id and the outcome are recorded.

    The module logger is replaced rather than captured with `caplog`: Alembic's
    `fileConfig` runs during the test session's migration and disables the
    existing `app.*` loggers, so records never reach the caplog handler.
    """
    from app.routers import account as account_router

    class Recorder:
        def __init__(self):
            self.records: list[str] = []

        def _capture(self, level, message, *args):
            self.records.append(f"{level} {message % args if args else message}")

        def info(self, message, *args):
            self._capture("info", message, *args)

        def warning(self, message, *args):
            self._capture("warning", message, *args)

        def error(self, message, *args):
            self._capture("error", message, *args)

        def exception(self, message, *args):
            self._capture("exception", message, *args)

    recorder = Recorder()
    monkeypatch.setattr(account_router, "logger", recorder)

    token = register(client).json()["access_token"]
    # The refusal path first: after a successful deletion the session is gone, so
    # a second request would never reach the password check.
    delete(client, token, password="a-different-secret")
    delete(client, token)

    joined = "\n".join(recorder.records)

    assert PASSWORD not in joined
    assert "a-different-secret" not in joined
    assert EMAIL not in joined
    # The user id and the outcome are all that are recorded.
    assert "Account deleted for user_id=" in joined
    assert "bad password" in joined


# --- 6. A commit failure is contained ----------------------------------------


def test_commit_failure_rolls_back_and_returns_a_generic_500(
    client, db_session, monkeypatch
):
    """A database failure must not leave a half-deleted account.

    The detail returned is fixed text: SQLAlchemy and driver errors carry table
    and column names, and echoing one is a free map of the schema.
    """
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    token = register(client).json()["access_token"]
    give_owned_rows(db_session)

    class CommitFailsOnce:
        """Let the authentication commit through, then fail the deletion commit."""

        def __init__(self, inner):
            self._inner = inner
            self.commits = 0

        def commit(self):
            self.commits += 1
            if self.commits > 1:
                raise RuntimeError("no such column: secret_thing")
            self._inner.commit()

        def rollback(self):
            self._inner.rollback()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def failing_db():
        yield CommitFailsOnce(db_session)

    app.dependency_overrides[get_db] = failing_db
    try:
        with TestClient(app, raise_server_exceptions=False) as broken:
            response = broken.post(
                DELETE_PATH,
                json={"current_password": PASSWORD, "confirmation": "DELETE"},
                headers=auth_header(token),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json()["detail"] == DELETION_FAILED
    assert "no such column" not in response.text
    assert "secret_thing" not in response.text
    # Rolled back: the account and everything it owns are still there.
    assert counts(db_session) == (1, 2, 1, 1)


# --- 7. Consent capture ------------------------------------------------------


def test_consent_is_stamped_with_the_current_versions(client, db_session):
    response = register(client, accepted_terms=True, acknowledged_privacy=True)

    assert response.status_code == 201
    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()

    assert user.terms_version == TERMS_VERSION
    assert user.privacy_version == PRIVACY_VERSION
    assert user.terms_accepted_at is not None
    assert user.privacy_acknowledged_at is not None
    # The versions reported publicly are the versions recorded.
    assert client.get("/api/legal/versions").json()["terms_version"] == user.terms_version


def test_absent_consent_leaves_the_columns_null(client, db_session):
    register(client)

    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()

    assert user.terms_version is None
    assert user.terms_accepted_at is None
    assert user.privacy_version is None
    assert user.privacy_acknowledged_at is None


def test_explicit_false_consent_leaves_the_columns_null(client, db_session):
    register(client, accepted_terms=False, acknowledged_privacy=False)

    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()

    assert user.terms_version is None
    assert user.privacy_version is None


def test_partial_consent_records_only_what_was_given(client, db_session):
    register(client, accepted_terms=True, acknowledged_privacy=False)

    user = db_session.execute(select(User).where(User.email == EMAIL)).scalar_one()

    assert user.terms_version == TERMS_VERSION
    assert user.terms_accepted_at is not None
    assert user.privacy_version is None
    assert user.privacy_acknowledged_at is None


def test_a_client_cannot_claim_a_version_of_its_choosing(client, db_session):
    """The version comes from app/terms.py, never from the request body."""
    response = client.post(
        "/api/auth/register",
        json={
            "email": "liar@example.com",
            "password": PASSWORD,
            "accepted_terms": True,
            "terms_version": "1999-01-01",
            "acknowledged_privacy": True,
            "privacy_version": "1999-01-01",
        },
    )

    assert response.status_code == 201
    user = db_session.execute(
        select(User).where(User.email == "liar@example.com")
    ).scalar_one()

    assert user.terms_version == TERMS_VERSION
    assert user.privacy_version == PRIVACY_VERSION


def test_registering_without_consent_is_not_blocked_and_login_still_works(client):
    register(client, accepted_terms=False, acknowledged_privacy=False)

    token = login(client)

    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200
    assert (
        client.get("/api/account/entitlement", headers=auth_header(token)).status_code
        == 200
    )


def test_a_user_with_null_consent_can_still_delete_their_account(client, db_session):
    """Consent is recorded, never enforced, on every path."""
    register(client)

    assert delete(client, login(client)).status_code == 200
    assert counts(db_session)[0] == 0


# --- 8. The public legal versions endpoint -----------------------------------


def test_legal_versions_is_public(client):
    response = client.get("/api/legal/versions")

    assert response.status_code == 200
    body = response.json()

    assert body["terms_version"] == TERMS_VERSION
    assert body["terms_effective_date"] == TERMS_EFFECTIVE_DATE
    assert body["privacy_version"] == PRIVACY_VERSION
    assert body["privacy_effective_date"] == PRIVACY_EFFECTIVE_DATE
    assert body["support_email"] == SUPPORT_EMAIL
    assert body["support_email_configured"] is bool(SUPPORT_EMAIL)
    assert body["governing_law"] == GOVERNING_LAW_PLACEHOLDER


def test_legal_versions_never_claims_an_unverified_support_mailbox(client):
    """No inbound mailbox has been verified, so none may be implied."""
    body = client.get("/api/legal/versions").json()

    if not body["support_email_configured"]:
        assert body["support_email"] is None
    # The governing-law placeholder is visibly a placeholder in the product, not
    # only in the repository.
    assert "to be confirmed" in body["governing_law"]


def test_legal_versions_ignores_a_bogus_token(client):
    """A signed-out visitor must still get the versions, and a bad token must
    not turn the public endpoint into an error.
    """
    assert client.get("/api/legal/versions").status_code == 200
    assert (
        client.get(
            "/api/legal/versions", headers=auth_header("nonsense-token")
        ).status_code
        == 200
    )


def test_support_email_is_read_from_the_environment(monkeypatch):
    from app.terms import resolve_support_email, support_email_configured

    monkeypatch.setenv("SUPPORT_EMAIL", "  hello@example.com  ")
    assert resolve_support_email() == "hello@example.com"

    # Blank and whitespace-only are both treated as unset, not as an address.
    monkeypatch.setenv("SUPPORT_EMAIL", "   ")
    assert resolve_support_email() is None

    monkeypatch.delenv("SUPPORT_EMAIL", raising=False)
    assert resolve_support_email() is None
    assert support_email_configured() is False


def test_governing_law_is_a_placeholder_not_a_claim():
    """It must not name a country, a state, or a company entity."""
    lowered = GOVERNING_LAW_PLACEHOLDER.lower()

    assert "to be confirmed" in lowered
    for invented in ("england", "scotland", "ireland", "delaware", "ltd", "inc"):
        assert invented not in lowered


def test_versions_are_iso_dates_that_fit_their_columns():
    """A future bump to an overlong or non-ISO value must fail here, not in prod.

    The columns are `String(32)`, and the frontend renders the dates with
    `new Date(...)`, so anything unparseable would surface as a blank or an
    "Invalid Date" on a legal page.
    """
    for value in (TERMS_VERSION, TERMS_EFFECTIVE_DATE, PRIVACY_VERSION, PRIVACY_EFFECTIVE_DATE):
        assert len(value) <= 32
        assert datetime.strptime(value, "%Y-%m-%d")

    # An effective date can lag the version it belongs to, but it cannot be in
    # the future relative to the version.
    assert TERMS_EFFECTIVE_DATE <= TERMS_VERSION
    assert PRIVACY_EFFECTIVE_DATE <= PRIVACY_VERSION


# --- 9. The ORM cascade is what deletes reservations -------------------------


def test_usage_reservations_cascade_even_with_foreign_keys_disabled(
    client, db_session
):
    """SQLite does not enforce ON DELETE CASCADE unless asked, so the ORM must.

    Without the `UsageReservation.user` relationship the reservation row would
    survive as an orphan pointing at a user that no longer exists.
    """
    from app.db.session import get_engine

    engine = get_engine()
    with engine.begin() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar()
    assert foreign_keys in (0, None), "expected SQLite FK enforcement to be off"

    token = register(client).json()["access_token"]
    give_owned_rows(db_session)

    assert delete(client, token).status_code == 200
    assert (
        db_session.execute(select(func.count()).select_from(UsageReservation)).scalar_one()
        == 0
    )


# --- 10. Rate limiting -------------------------------------------------------


def test_deletion_is_throttled(client, live_settings, monkeypatch):
    """The endpoint has its own bucket, so a grind is stopped."""
    from app.ratelimit import reset_rate_limits

    token = register(client).json()["access_token"]
    monkeypatch.setenv("RATE_LIMIT_DELETE_ACCOUNT", "2")
    monkeypatch.setenv("RATE_LIMIT_DELETE_ACCOUNT_WINDOW_SECONDS", "900")
    live_settings()
    reset_rate_limits()

    statuses = [delete(client, token, password="wrong").status_code for _ in range(4)]

    assert 429 in statuses
    # Every request was refused, so the account is untouched.
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200


def test_repeated_failed_deletions_in_one_session_are_all_answered(client):
    token = register(client).json()["access_token"]

    for _ in range(4):
        assert delete(client, token, password="wrong").status_code == 401
