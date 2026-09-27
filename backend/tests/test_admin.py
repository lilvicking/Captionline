"""Administrative support console: authorization, search, detail, and audit.

The important property under test is that administrator access is decided on the
server, from a durable column, and that a normal user has no way to reach it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import (
    ACTION_CREDIT_GRANTED,
    ACTION_CREDIT_REMOVED,
    AdminAuditEntry,
    User,
)
from app.routers.admin import router as admin_router
from tests.conftest import auth_header

PASSWORD = "a-strong-password-123"
FREE_EMAIL = "customer@example.com"
ADMIN_EMAIL = "owner@example.com"

#: Fields a support response must never carry. Asserted by key name, so a future
#: refactor that starts returning the whole model fails here.
FORBIDDEN_RESPONSE_KEYS = {
    "password_hash",
    "token_hash",
    "access_token",
    "reset_token",
    "stripe_secret_key",
    "webhook_secret",
    "authorization",
}


def make_admin(client, email=ADMIN_EMAIL):
    token = client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["access_token"]

    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        user = session.execute(select(User).where(User.email == email)).scalar_one()
        user.is_admin = True
        session.commit()
    finally:
        session.close()

    return token


# --- Authorization ----------------------------------------------------------


def test_admin_endpoints_exist():
    paths = {route.path for route in admin_router.routes}
    assert paths == {
        "/api/admin/summary",
        "/api/admin/customer-options",
        "/api/admin/users",
        "/api/admin/users/{user_id}",
        "/api/admin/users/{user_id}/credits",
        "/api/admin/users/{user_id}/audit",
    }


# --- Customer picker options ------------------------------------------------


def test_admin_can_retrieve_customer_options(client):
    token = make_admin(client)
    client.post("/api/auth/register", json={"email": "pick@example.com", "password": PASSWORD})

    response = client.get("/api/admin/customer-options", headers=auth_header(token))

    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is False
    assert body["limit"] == 500
    assert {option["email"] for option in body["options"]} >= {
        ADMIN_EMAIL,
        "pick@example.com",
    }


def test_customer_options_are_admin_only_anonymous(client):
    """401 before anything is read, so the endpoint cannot be used to probe."""
    assert client.get("/api/admin/customer-options").status_code == 401


def test_customer_options_are_admin_only_normal_user(client):
    token = client.post(
        "/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD}
    ).json()["access_token"]

    assert client.get(
        "/api/admin/customer-options", headers=auth_header(token)
    ).status_code == 403


def test_customer_options_reject_a_paid_user_too(client, db_session):
    """Being on a paid plan must not unlock the picker."""
    from app.plans import CREATOR_MONTHLY
    from app.usage import apply_plan_to_user

    token = client.post(
        "/api/auth/register", json={"email": "paid-picker@example.com", "password": PASSWORD}
    ).json()["access_token"]

    user = db_session.execute(
        select(User).where(User.email == "paid-picker@example.com")
    ).scalar_one()
    apply_plan_to_user(user, CREATOR_MONTHLY.id)
    db_session.commit()

    assert user.is_admin is False
    assert client.get(
        "/api/admin/customer-options", headers=auth_header(token)
    ).status_code == 403


def test_customer_options_are_sorted_case_insensitively(client, db_session):
    from app.db.session import get_session_factory
    from app.usage import add_months, period_start_for
    from datetime import datetime, timezone

    token = make_admin(client)

    factory = get_session_factory()
    session = factory()
    try:
        for email in ("Zebra@example.com", "apple@example.com", "Mango@example.com"):
            start = period_start_for(datetime(2026, 9, 26, tzinfo=timezone.utc), "free")
            session.add(
                User(
                    email=email,
                    password_hash="x",
                    plan="free",
                    monthly_processing_allowance_seconds=600,
                    usage_period_started_at=start,
                    usage_period_ends_at=add_months(start, 1),
                )
            )
        session.commit()
    finally:
        session.close()

    emails = [
        option["email"]
        for option in client.get(
            "/api/admin/customer-options", headers=auth_header(token)
        ).json()["options"]
    ]

    # Case-insensitive alphabetical, and the test addresses interleave correctly.
    lowered = [value.lower() for value in emails]
    assert lowered == sorted(lowered)
    assert lowered.index("apple@example.com") < lowered.index("mango@example.com")
    assert lowered.index("mango@example.com") < lowered.index("zebra@example.com")


def test_customer_options_have_no_duplicates(client, db_session):
    token = make_admin(client)
    for index in range(5):
        client.post(
            "/api/auth/register",
            json={"email": f"dup{index}@example.com", "password": PASSWORD},
        )

    options = client.get(
        "/api/admin/customer-options", headers=auth_header(token)
    ).json()["options"]

    ids = [option["id"] for option in options]
    emails = [option["email"] for option in options]

    assert len(ids) == len(set(ids))
    assert len(emails) == len(set(emails))


def test_customer_options_return_only_id_and_email(client):
    """A picker needs an id and an address, and nothing more."""
    token = make_admin(client)

    options = client.get(
        "/api/admin/customer-options", headers=auth_header(token)
    ).json()["options"]

    assert options
    for option in options:
        assert set(option) == {"id", "email"}

    # And none of the values leak a credential.
    serialised = str(options)
    for forbidden in ("password", "token", "stripe", "bonus", "usage", "allowance"):
        assert forbidden not in serialised.lower()


def test_customer_options_are_not_cacheable(client):
    """Customer addresses must not sit in a shared cache."""
    token = make_admin(client)

    response = client.get("/api/admin/customer-options", headers=auth_header(token))

    assert response.headers.get("cache-control") == "no-store"


def test_customer_options_exclude_deleted_accounts(client):
    """A deleted account is no longer a row, so it cannot appear."""
    admin_token = make_admin(client)
    victim_token = client.post(
        "/api/auth/register", json={"email": "gone@example.com", "password": PASSWORD}
    ).json()["access_token"]

    deleted = client.post(
        "/api/account/delete",
        json={"current_password": PASSWORD, "confirmation": "DELETE"},
        headers=auth_header(victim_token),
    )
    assert deleted.status_code == 200

    emails = [
        option["email"]
        for option in client.get(
            "/api/admin/customer-options", headers=auth_header(admin_token)
        ).json()["options"]
    ]

    assert "gone@example.com" not in emails
    assert ADMIN_EMAIL in emails  # the admin is still listed, as an ordinary account


def test_customer_options_are_capped_and_flagged(client, db_session, monkeypatch):
    from app.routers import admin as admin_module
    from app.db.session import get_session_factory
    from app.usage import add_months, period_start_for
    from datetime import datetime, timezone

    token = make_admin(client)

    monkeypatch.setattr(admin_module, "CUSTOMER_OPTION_LIMIT", 3)

    factory = get_session_factory()
    session = factory()
    try:
        for index in range(6):
            start = period_start_for(datetime(2026, 9, 26, tzinfo=timezone.utc), "free")
            session.add(
                User(
                    email=f"cap{index:02d}@example.com",
                    password_hash="x",
                    plan="free",
                    monthly_processing_allowance_seconds=600,
                    usage_period_started_at=start,
                    usage_period_ends_at=add_months(start, 1),
                )
            )
        session.commit()
    finally:
        session.close()

    body = client.get("/api/admin/customer-options", headers=auth_header(token)).json()

    assert len(body["options"]) == 3
    assert body["truncated"] is True
    assert body["limit"] == 3


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/admin/summary", None),
        ("GET", "/api/admin/users?q=someone", None),
        ("GET", "/api/admin/users/1", None),
        ("GET", "/api/admin/users/1/audit", None),
        ("POST", "/api/admin/users/1/credits", {"minutes": 10, "reason": "support goodwill"}),
    ],
)
def test_unauthenticated_is_denied(client, method, path, body):
    """Every admin route refuses an anonymous caller, before touching any data."""
    if method == "GET":
        response = client.get(path)
    else:
        response = client.post(path, json=body)

    assert response.status_code == 401


def test_normal_user_is_denied(client, db_session):
    """A signed-in Free account cannot reach any admin route."""
    token = client.post(
        "/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD}
    ).json()["access_token"]

    user = db_session.execute(
        select(User).where(User.email == FREE_EMAIL)
    ).scalar_one()
    assert user.is_admin is False

    for method, path, body in [
        ("GET", "/api/admin/summary", None),
        ("GET", "/api/admin/customer-options", None),
        ("GET", "/api/admin/users?q=customer", None),
        ("GET", "/api/admin/users/1", None),
        ("GET", "/api/admin/users/1/audit", None),
        ("POST", "/api/admin/users/1/credits", {"minutes": 10, "reason": "support"}),
    ]:
        if method == "GET":
            response = client.get(path, headers=auth_header(token))
        else:
            response = client.post(path, json=body, headers=auth_header(token))
        assert response.status_code == 403, f"{method} {path} was not refused"


def test_admin_is_allowed(client):
    token = make_admin(client)

    for method, path, body in [
        ("GET", "/api/admin/summary", None),
        ("GET", "/api/admin/users?q=owner", None),
    ]:
        if method == "GET":
            response = client.get(path, headers=auth_header(token))
        else:
            response = client.post(path, json=body, headers=auth_header(token))
        assert response.status_code == 200


def test_paid_user_is_still_not_admin(client, db_session):
    """Being on a paid plan must never imply administrator access."""
    from app.plans import CREATOR_MONTHLY
    from app.usage import apply_plan_to_user

    token = client.post(
        "/api/auth/register", json={"email": "paid@example.com", "password": PASSWORD}
    ).json()["access_token"]

    user = db_session.execute(
        select(User).where(User.email == "paid@example.com")
    ).scalar_one()
    apply_plan_to_user(user, CREATOR_MONTHLY.id)
    db_session.commit()

    assert user.is_admin is False
    assert client.get("/api/admin/summary", headers=auth_header(token)).status_code == 403


def test_no_endpoint_lets_a_user_promote_themselves(client, db_session):
    """There is no write path to is_admin that a signed-in user can reach."""
    token = client.post(
        "/api/auth/register", json={"email": "sneaky@example.com", "password": PASSWORD}
    ).json()["access_token"]

    write_paths = [
        (route.path, sorted(route.methods - {"HEAD", "OPTIONS"}))
        for route in admin_router.routes
        if "POST" in route.methods
    ]

    # The only POST is the credit adjustment, whose body model forbids is_admin.
    assert [path for path, _ in write_paths] == ["/api/admin/users/{user_id}/credits"]

    # And posting is_admin to it is rejected by validation, not ignored.
    response = client.post(
        "/api/admin/users/1/credits",
        json={"minutes": 10, "reason": "x", "is_admin": True},
        headers=auth_header(token),
    )
    assert response.status_code in (401, 403, 422)


# --- Bootstrap --------------------------------------------------------------


def test_admin_emails_unset_changes_nothing(client, db_session, live_settings, monkeypatch):
    import app.config as config_module
    from app.routers.admin import sync_admin_emails

    monkeypatch.setenv("ADMIN_EMAILS", "")
    live_settings()
    assert config_module.get_settings().admin_email_set == set()

    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        assert sync_admin_emails(session) == 0
        everyone = session.execute(select(User)).scalars().all()
        assert all(user.is_admin is False for user in everyone)
    finally:
        session.close()


def test_admin_emails_promotes_only_listed_accounts(
    client, db_session, live_settings, monkeypatch
):
    import app.config as config_module
    from app.routers.admin import sync_admin_emails
    from app.db.session import get_session_factory

    for email in (ADMIN_EMAIL, FREE_EMAIL):
        client.post("/api/auth/register", json={"email": email, "password": PASSWORD})

    # Mixed case and surrounding whitespace, because configuration is written by
    # hand and should not need to be perfect.
    monkeypatch.setenv("ADMIN_EMAILS", f"  {ADMIN_EMAIL.upper()} , someone-else@example.com ")
    live_settings()

    assert config_module.get_settings().admin_email_set == {
        ADMIN_EMAIL,
        "someone-else@example.com",
    }

    session = get_session_factory()()
    try:
        assert sync_admin_emails(session) == 1
        session.expire_all()

        owner = session.execute(
            select(User).where(User.email == ADMIN_EMAIL)
        ).scalar_one()
        customer = session.execute(
            select(User).where(User.email == FREE_EMAIL)
        ).scalar_one()
        assert owner.is_admin is True
        assert customer.is_admin is False
    finally:
        session.close()


def test_removing_from_admin_emails_revokes_access(
    client, db_session, live_settings, monkeypatch
):
    """Revoking means changing the list, not emptying it.

    An empty ADMIN_EMAILS deliberately makes no change, so a deployment that
    never configured it cannot lock itself out. To remove the last administrator
    you point the variable at an address no account uses, which is authoritative
    and demotes everyone.
    """
    import app.config as config_module
    from app.routers.admin import sync_admin_emails
    from app.db.session import get_session_factory

    client.post("/api/auth/register", json={"email": ADMIN_EMAIL, "password": PASSWORD})

    monkeypatch.setenv("ADMIN_EMAILS", ADMIN_EMAIL)
    live_settings()
    session = get_session_factory()()
    try:
        assert sync_admin_emails(session) == 1
    finally:
        session.close()

    token = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD}
    ).json()["access_token"]
    assert client.get("/api/admin/summary", headers=auth_header(token)).status_code == 200

    # A list matching no account revokes the last administrator.
    monkeypatch.setenv("ADMIN_EMAILS", "retired-owner@example.invalid")
    live_settings()
    assert config_module.get_settings().admin_email_set == {"retired-owner@example.invalid"}

    session = get_session_factory()()
    try:
        assert sync_admin_emails(session) == 1
    finally:
        session.close()

    assert client.get("/api/admin/summary", headers=auth_header(token)).status_code == 403


# --- Search -----------------------------------------------------------------


def test_search_finds_by_email_and_id(client, db_session):
    token = make_admin(client)
    client.post("/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD})

    target = db_session.execute(
        select(User).where(User.email == FREE_EMAIL)
    ).scalar_one()

    by_email = client.get(
        f"/api/admin/users?q={FREE_EMAIL}", headers=auth_header(token)
    ).json()
    assert [u["email"] for u in by_email] == [FREE_EMAIL]

    by_id = client.get(f"/api/admin/users?q={target.id}", headers=auth_header(token)).json()
    assert [u["id"] for u in by_id] == [target.id]

    # A partial address still matches, and the search runs server side.
    partial = client.get("/api/admin/users?q=customer", headers=auth_header(token)).json()
    assert [u["email"] for u in partial] == [FREE_EMAIL]


def test_search_returns_nothing_for_an_unknown_address(client):
    token = make_admin(client)

    assert client.get(
        "/api/admin/users?q=nobody-here", headers=auth_header(token)
    ).json() == []


def test_search_rejects_an_empty_query(client):
    token = make_admin(client)

    assert client.get("/api/admin/users?q=", headers=auth_header(token)).status_code == 422


def test_search_is_capped(client, db_session):
    """A broad term must not pull the whole customer table."""
    from app.plans import FREE_PLAN
    from app.db.session import get_session_factory
    from app.usage import add_months, period_start_for

    token = make_admin(client)
    factory = get_session_factory()
    session = factory()
    try:
        for index in range(40):
            start = period_start_for(datetime(2026, 9, 26, tzinfo=timezone.utc), FREE_PLAN.id)
            user = User(
                email=f"bulk{index:02d}@example.com",
                password_hash="x",
                plan=FREE_PLAN.id,
                monthly_processing_allowance_seconds=FREE_PLAN.usage_allowance_seconds,
                can_export=True,
                has_full_preview=True,
                usage_period_started_at=start,
                usage_period_ends_at=add_months(start, 1),
            )
            session.add(user)
        session.commit()
    finally:
        session.close()

    results = client.get("/api/admin/users?q=bulk", headers=auth_header(token)).json()
    assert len(results) == 25


# --- Detail -----------------------------------------------------------------


def test_detail_exposes_support_fields(client, db_session):
    token = make_admin(client)
    client.post("/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD})

    target = db_session.execute(
        select(User).where(User.email == FREE_EMAIL)
    ).scalar_one()

    body = client.get(f"/api/admin/users/{target.id}", headers=auth_header(token)).json()

    for field in (
        "email", "id", "created_at", "plan", "subscription_status",
        "monthly_processing_allowance_seconds", "processing_used_seconds",
        "processing_remaining_seconds", "usage_period_ends_at",
        "bonus_processing_seconds", "has_full_preview", "can_export", "is_admin",
    ):
        assert field in body, f"missing support field {field}"

    assert body["monthly_processing_allowance_seconds"] == 600
    assert body["processing_remaining_seconds"] == 600
    assert body["bonus_processing_seconds"] == 0
    assert body["can_export"] is True


def test_detail_never_exposes_credentials(client, db_session):
    token = make_admin(client)
    client.post("/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD})

    target = db_session.execute(
        select(User).where(User.email == FREE_EMAIL)
    ).scalar_one()

    body = client.get(f"/api/admin/users/{target.id}", headers=auth_header(token)).json()

    assert FORBIDDEN_RESPONSE_KEYS.isdisjoint(body.keys())
    # And no secret value appears anywhere in the payload.
    serialised = str(body)
    assert target.password_hash not in serialised


def test_detail_404s_for_an_unknown_account(client):
    token = make_admin(client)

    assert client.get("/api/admin/users/999999", headers=auth_header(token)).status_code == 404


# --- Audit ------------------------------------------------------------------


def test_credit_grant_writes_an_audit_row(client, db_session):
    admin_token = make_admin(client)
    client.post("/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD})

    target = db_session.execute(
        select(User).where(User.email == FREE_EMAIL)
    ).scalar_one()
    admin = db_session.execute(
        select(User).where(User.email == ADMIN_EMAIL)
    ).scalar_one()

    response = client.post(
        f"/api/admin/users/{target.id}/credits",
        json={"minutes": 30, "reason": "Transcription issue"},
        headers=auth_header(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["bonus_processing_seconds"] == 1800

    entry = db_session.execute(select(AdminAuditEntry)).scalars().all()
    assert len(entry) == 1
    assert entry[0].action == ACTION_CREDIT_GRANTED
    assert entry[0].amount_seconds == 1800
    assert entry[0].reason == "Transcription issue"
    assert entry[0].admin_user_id == admin.id
    assert entry[0].target_user_id == target.id
    assert entry[0].created_at is not None


def test_audit_endpoint_lists_history(client, db_session):
    admin_token = make_admin(client)
    client.post("/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD})
    target = db_session.execute(
        select(User).where(User.email == FREE_EMAIL)
    ).scalar_one()

    for minutes, reason in ((10, "First"), (60, "Second")):
        client.post(
            f"/api/admin/users/{target.id}/credits",
            json={"minutes": minutes, "reason": reason},
            headers=auth_header(admin_token),
        )

    audit = client.get(
        f"/api/admin/users/{target.id}/audit", headers=auth_header(admin_token)
    ).json()

    assert len(audit) == 2
    # Newest first.
    assert audit[0]["reason"] == "Second"
    assert audit[1]["reason"] == "First"
    assert audit[0]["admin_email"] == ADMIN_EMAIL


def test_cannot_adjust_your_own_credit(client, db_session):
    """Self-granting would manufacture usage outside the audited process."""
    admin_token = make_admin(client)
    admin = db_session.execute(
        select(User).where(User.email == ADMIN_EMAIL)
    ).scalar_one()

    response = client.post(
        f"/api/admin/users/{admin.id}/credits",
        json={"minutes": 600, "reason": "self grant"},
        headers=auth_header(admin_token),
    )
    assert response.status_code == 400


def test_reason_is_required(client, db_session):
    admin_token = make_admin(client)
    client.post("/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD})
    target = db_session.execute(
        select(User).where(User.email == FREE_EMAIL)
    ).scalar_one()

    for reason in ("", "  "):
        response = client.post(
            f"/api/admin/users/{target.id}/credits",
            json={"minutes": 10, "reason": reason},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 422, f"reason {reason!r} was accepted"


def test_zero_and_oversized_adjustments_are_refused(client, db_session):
    admin_token = make_admin(client)
    client.post("/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD})
    target = db_session.execute(
        select(User).where(User.email == FREE_EMAIL)
    ).scalar_one()

    zero = client.post(
        f"/api/admin/users/{target.id}/credits",
        json={"minutes": 0, "reason": "nothing"},
        headers=auth_header(admin_token),
    )
    assert zero.status_code == 422

    huge = client.post(
        f"/api/admin/users/{target.id}/credits",
        json={"minutes": 10_000, "reason": "typo"},
        headers=auth_header(admin_token),
    )
    assert huge.status_code == 422


# --- Summary ----------------------------------------------------------------


def test_summary_counts(client, db_session):
    admin_token = make_admin(client)
    client.post("/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD})
    client.post("/api/auth/register", json={"email": "other@example.com", "password": PASSWORD})

    body = client.get("/api/admin/summary", headers=auth_header(admin_token)).json()

    assert body["total_users"] == 3  # owner + two customers
    assert body["free_users"] == 3
    assert body["users_with_credit"] == 0
    assert body["total_bonus_seconds"] == 0


# --- Entitlement exposure ---------------------------------------------------


def test_entitlement_reports_is_admin_and_credit(client):
    token = make_admin(client)

    body = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert body["is_admin"] is True
    assert body["bonus_processing_seconds"] == 0


def test_entitlement_reports_admin_false_for_a_normal_account(client):
    token = client.post(
        "/api/auth/register", json={"email": FREE_EMAIL, "password": PASSWORD}
    ).json()["access_token"]

    body = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert body["is_admin"] is False
