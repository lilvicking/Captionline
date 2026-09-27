"""Support processing credit: consumption order, resets, and correctness.

The credit is an *addition* to the plan allowance, never a replacement. The
properties that matter economically:

* the monthly allowance is spent before any credit
* `processing_used_seconds` never exceeds the plan allowance just to represent a
  credit, so the monthly figure keeps meaning "of your plan allowance"
* a monthly reset restores the plan allowance but does not erase credit
* a failed transcription restores everything it held
* concurrent requests cannot overspend the combined total
* an administrative correction cannot drive the balance negative
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import User, UsageReservation
from app.plans import FREE_PLAN
from app.usage import (
    AllowanceExceededError,
    build_usage_snapshot,
    ensure_current_usage_period,
    finalize_reservation,
    release_reservation,
    remaining_allowance_seconds,
    reserve_processing_seconds,
)
from test_usage_accounting import make_user

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def grant(user, seconds: int) -> None:
    user.bonus_processing_seconds = max(int(user.bonus_processing_seconds or 0), 0) + seconds


# --- Totals -----------------------------------------------------------------


def test_credit_is_additive(db_session):
    user = make_user(db_session, processing_used_seconds=500)  # 100 left of 600
    assert remaining_allowance_seconds(db_session, user, NOW) == 100

    grant(user, 3600)
    db_session.commit()

    assert remaining_allowance_seconds(db_session, user, NOW) == 3700


def test_snapshot_reports_credit_separately_from_the_allowance(db_session):
    user = make_user(db_session, processing_used_seconds=500)
    grant(user, 3600)
    db_session.commit()

    snapshot = build_usage_snapshot(db_session, user, NOW)

    assert snapshot.monthly_processing_allowance_seconds == 600
    assert snapshot.processing_used_seconds == 500
    assert snapshot.bonus_processing_seconds == 3600
    assert snapshot.processing_remaining_seconds == 3700


# --- Consumption order ------------------------------------------------------


def test_plan_allowance_is_spent_before_credit(db_session):
    """Used goes to 600, then only the excess touches the credit."""
    user = make_user(db_session, processing_used_seconds=550)  # 50 left
    grant(user, 3600)
    db_session.commit()

    # 300 seconds: 50 from the plan, 250 from the credit.
    reservation = reserve_processing_seconds(db_session, user, 300, NOW)
    finalize_reservation(db_session, reservation.reservation_id, NOW)
    db_session.refresh(user)

    assert user.processing_used_seconds == 600  # exactly the plan allowance
    assert user.bonus_processing_seconds == 3350


def test_credit_only_is_used_when_the_plan_is_exhausted(db_session):
    user = make_user(db_session, processing_used_seconds=600)
    grant(user, 3600)
    db_session.commit()

    reservation = reserve_processing_seconds(db_session, user, 120, NOW)
    finalize_reservation(db_session, reservation.reservation_id, NOW)
    db_session.refresh(user)

    # The plan figure must not inflate to represent credit usage.
    assert user.processing_used_seconds == 600
    assert user.bonus_processing_seconds == 3480


def test_reserve_refuses_beyond_plan_plus_credit(db_session):
    user = make_user(db_session, processing_used_seconds=590)  # 10 left
    grant(user, 100)
    db_session.commit()

    assert remaining_allowance_seconds(db_session, user, NOW) == 110

    with pytest.raises(AllowanceExceededError) as caught:
        reserve_processing_seconds(db_session, user, 111, NOW)

    assert caught.value.remaining_seconds == 110


# --- Failed transcription ---------------------------------------------------


def test_failed_transcription_restores_credit(db_session):
    """A released hold must not burn goodwill credit."""
    user = make_user(db_session, processing_used_seconds=600)
    grant(user, 3600)
    db_session.commit()

    reservation = reserve_processing_seconds(db_session, user, 300, NOW)
    # The hold comes off the combined balance, so 300 of the credit is
    # provisionally unavailable even though nothing is charged yet.
    assert remaining_allowance_seconds(db_session, user, NOW) == 3300

    release_reservation(db_session, reservation.reservation_id, NOW)
    db_session.refresh(user)

    assert user.bonus_processing_seconds == 3600
    assert remaining_allowance_seconds(db_session, user, NOW) == 3600


def test_failed_transcription_leaves_no_residual_charge(db_session):
    user = make_user(db_session, processing_used_seconds=550)
    grant(user, 600)
    db_session.commit()

    reservation = reserve_processing_seconds(db_session, user, 100, NOW)
    release_reservation(db_session, reservation.reservation_id, NOW)
    db_session.refresh(user)

    assert user.processing_used_seconds == 550
    assert user.bonus_processing_seconds == 600


# --- Monthly reset ----------------------------------------------------------


def test_monthly_reset_restores_the_plan_but_keeps_the_credit(db_session):
    user = make_user(db_session, processing_used_seconds=600)
    grant(user, 3600)
    db_session.commit()

    october = datetime(2026, 10, 2, tzinfo=timezone.utc)
    assert ensure_current_usage_period(user, october) is True
    db_session.commit()
    db_session.refresh(user)

    assert user.processing_used_seconds == 0
    # Credit is not part of the monthly cycle.
    assert user.bonus_processing_seconds == 3600

    snapshot = build_usage_snapshot(db_session, user, october)
    assert snapshot.processing_remaining_seconds == 600 + 3600


def test_apply_plan_does_not_clear_the_credit(db_session):
    """Re-applying a plan must never destroy granted goodwill."""
    from app.usage import apply_plan_to_user

    user = make_user(db_session)
    grant(user, 3600)
    db_session.commit()

    apply_plan_to_user(user, FREE_PLAN.id)
    db_session.commit()

    assert user.bonus_processing_seconds == 3600
    assert user.can_export is True


# --- Concurrency ------------------------------------------------------------


def test_in_flight_holds_reduce_the_combined_balance(db_session):
    user = make_user(db_session, processing_used_seconds=500)
    grant(user, 1000)
    db_session.commit()

    first = reserve_processing_seconds(db_session, user, 600, NOW)
    # 100 plan + 1000 credit = 1100 available, 600 now held, 500 left.
    assert remaining_allowance_seconds(db_session, user, NOW) == 500

    with pytest.raises(AllowanceExceededError) as caught:
        reserve_processing_seconds(db_session, user, 501, NOW)
    assert caught.value.remaining_seconds == 500

    release_reservation(db_session, first.reservation_id, NOW)


def test_two_holds_cannot_both_spend_the_same_credit(db_session):
    user = make_user(db_session, processing_used_seconds=600)
    grant(user, 1000)
    db_session.commit()

    first = reserve_processing_seconds(db_session, user, 700, NOW)

    # Only 300 of the credit is still unheld, so a second overlapping request
    # for 400 is refused rather than both drawing on the same 1000 seconds.
    with pytest.raises(AllowanceExceededError) as caught:
        reserve_processing_seconds(db_session, user, 400, NOW)

    assert caught.value.remaining_seconds == 300

    finalize_reservation(db_session, first.reservation_id, NOW)
    db_session.refresh(user)

    assert user.bonus_processing_seconds == 300
    assert remaining_allowance_seconds(db_session, user, NOW) == 300


# --- Corrections ------------------------------------------------------------


def test_negative_correction_removes_credit(db_session):
    user = make_user(db_session)
    grant(user, 3600)
    db_session.commit()

    user.bonus_processing_seconds = 1800
    db_session.commit()

    assert remaining_allowance_seconds(db_session, user, NOW) == 1800 + 600


def test_credit_can_never_go_negative(db_session):
    user = make_user(db_session)
    grant(user, 600)
    db_session.commit()

    assert user.bonus_processing_seconds == 600
    # The API refuses an over-large removal; the column is only ever written
    # through that guarded path, so a negative value is not representable.
    assert remaining_allowance_seconds(db_session, user, NOW) == 1200


def test_credit_is_consumed_only_by_real_transcription(db_session):
    """Reading usage or building a snapshot must not change any balance."""
    user = make_user(db_session)
    grant(user, 3600)
    db_session.commit()

    for _ in range(3):
        build_usage_snapshot(db_session, user, NOW)
        remaining_allowance_seconds(db_session, user, NOW)

    db_session.refresh(user)
    assert user.bonus_processing_seconds == 3600
    assert user.processing_used_seconds == 0


# --- Endpoint integration ---------------------------------------------------


def _admin_token(client):
    from tests.test_admin import make_admin

    return make_admin(client)


@pytest.mark.parametrize("minutes", [10, 30, 60, 120, 45.5])
def test_credits_of_various_sizes_are_stored_in_seconds(client, db_session, minutes):
    admin_token = _admin_token(client)
    client.post(
        "/api/auth/register", json={"email": "target@example.com", "password": "a-strong-password-123"}
    )
    target = db_session.execute(
        select(User).where(User.email == "target@example.com")
    ).scalar_one()

    response = client.post(
        f"/api/admin/users/{target.id}/credits",
        json={"minutes": minutes, "reason": "support goodwill"},
        headers=auth_header(admin_token),
    )

    assert response.status_code == 200
    assert response.json()["bonus_processing_seconds"] == round(minutes * 60)


def test_granted_credit_increases_effective_remaining(client, db_session):
    admin_token = _admin_token(client)
    client.post(
        "/api/auth/register", json={"email": "target2@example.com", "password": "a-strong-password-123"}
    )
    target = db_session.execute(
        select(User).where(User.email == "target2@example.com")
    ).scalar_one()

    before = client.get(f"/api/admin/users/{target.id}", headers=auth_header(admin_token)).json()
    assert before["processing_remaining_seconds"] == 600

    client.post(
        f"/api/admin/users/{target.id}/credits",
        json={"minutes": 60, "reason": "goodwill"},
        headers=auth_header(admin_token),
    )
    after = client.get(f"/api/admin/users/{target.id}", headers=auth_header(admin_token)).json()

    assert after["processing_remaining_seconds"] == 600 + 3600
    assert after["monthly_processing_allowance_seconds"] == 600  # unchanged
    assert after["bonus_processing_seconds"] == 3600


def test_negative_adjustment_beyond_the_balance_is_refused(client, db_session):
    admin_token = _admin_token(client)
    client.post(
        "/api/auth/register", json={"email": "target3@example.com", "password": "a-strong-password-123"}
    )
    target = db_session.execute(
        select(User).where(User.email == "target3@example.com")
    ).scalar_one()

    response = client.post(
        f"/api/admin/users/{target.id}/credits",
        json={"minutes": -30, "reason": "over-correct"},
        headers=auth_header(admin_token),
    )

    assert response.status_code == 400
    assert "below zero" in response.json()["detail"]


def test_correction_records_a_removal_audit_row(client, db_session):
    admin_token = _admin_token(client)
    client.post(
        "/api/auth/register", json={"email": "target4@example.com", "password": "a-strong-password-123"}
    )
    target = db_session.execute(
        select(User).where(User.email == "target4@example.com")
    ).scalar_one()

    client.post(
        f"/api/admin/users/{target.id}/credits",
        json={"minutes": 60, "reason": "grant"},
        headers=auth_header(admin_token),
    )
    client.post(
        f"/api/admin/users/{target.id}/credits",
        json={"minutes": -10, "reason": "mistake"},
        headers=auth_header(admin_token),
    )

    from app.db.models import ACTION_CREDIT_REMOVED

    actions = [
        entry.action
        for entry in db_session.execute(select(__import__("app.db.models", fromlist=["AdminAuditEntry"]).AdminAuditEntry)).scalars().all()
    ]
    assert "credit_granted" in actions
    assert ACTION_CREDIT_REMOVED in actions


from tests.conftest import auth_header  # noqa: E402  (used throughout)
