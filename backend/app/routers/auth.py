"""Account registration, login, and session routes."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.models import Session as SessionModel
from ..db.models import User
from ..db.session import get_db
from ..ratelimit import enforce
from ..usage import add_months, apply_plan_to_user, period_start_for
from ..security.deps import (
    INVALID_CREDENTIALS,
    get_current_user,
    require_database,
    revoke_current_session,
)
from ..security.passwords import (
    PasswordTooShortError,
    hash_password,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from ..security.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from ..security.tokens import generate_token, hash_token
from ..terms import PRIVACY_VERSION, TERMS_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_TAKEN = "An account with that email already exists."

#: A real Argon2id hash of a value nobody can present, computed once at import.
#:
#: Argon2id at 64 MiB costs tens of milliseconds by design. Verifying only when
#: the account exists therefore made a login for an unknown address return
#: roughly a hundred times faster than a login for a known one, which is a
#: usable account-enumeration oracle on its own, whatever the response body
#: says. Paying the same cost on both paths removes the difference. The hash is
#: not a secret: it is a well-formed hash of a value that is not a password, so
#: a real candidate can never match it.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _issue_session(db: OrmSession, user: User) -> tuple[str, datetime]:
    """Create a session row and return the plaintext token plus its expiry."""
    settings = get_settings()
    token = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)

    db.add(
        SessionModel(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=expires_at,
        )
    )

    return token, expires_at


def _token_response(user: User, token: str, expires_at: datetime) -> TokenResponse:
    return TokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
) -> TokenResponse:
    """Create an account on the free plan and issue a session."""
    require_database()

    settings = get_settings()
    email = _normalize_email(payload.email)

    # Throttled per address and per account before any hashing or database work.
    enforce("register", request, account=email)

    try:
        validate_password_strength(payload.password, settings.min_password_length)
    except PasswordTooShortError as exc:
        # Numeric status avoids coupling to a renamed Starlette enum.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if db.scalar(select(User).where(User.email == email)) is not None:
        # A distinguishable response, because duplicate-email handling is an
        # explicit requirement.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EMAIL_TAKEN)

    now = datetime.now(timezone.utc)
    period_start = period_start_for(now, "free")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        created_at=now,
        updated_at=now,
        usage_period_started_at=period_start,
        usage_period_ends_at=add_months(period_start, 1),
    )

    # Record the consent the client reported, and nothing more. The version comes
    # from `app/terms.py` and never from the request, so a client cannot claim
    # acceptance of a version that is not the one on display.
    #
    # Absent consent leaves the columns NULL and is not an error. Blocking
    # registration on it, or gating login on it, would retroactively lock out
    # every account created before these columns existed: nobody agreed to text
    # that did not exist when they signed up. The frontend presents the
    # agreement; the backend only remembers what was asserted.
    if payload.accepted_terms:
        user.terms_accepted_at = now
        user.terms_version = TERMS_VERSION

    if payload.acknowledged_privacy:
        user.privacy_acknowledged_at = now
        user.privacy_version = PRIVACY_VERSION

    # Seeds plan, allowance, preview, and export columns from app/plans.py.
    apply_plan_to_user(user)

    db.add(user)
    db.commit()
    db.refresh(user)

    token, expires_at = _issue_session(db, user)
    db.commit()

    logger.info("Registered account on the %s plan", user.plan)
    return _token_response(user, token, expires_at)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
) -> TokenResponse:
    """Exchange email and password for a session token."""
    require_database()

    email = _normalize_email(payload.email)

    # Throttled per address and per account, so neither password spraying from
    # one host nor one account sprayed from many hosts gets a free run at
    # Argon2id.
    enforce("login", request, account=email)

    user = db.scalar(select(User).where(User.email == email))

    # A missing account and a wrong password must be indistinguishable to the
    # caller, so the same message and status are used for both, and Argon2 runs
    # on both paths so the two cannot be told apart by how long they take.
    password_ok = verify_password(
        payload.password, user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    )

    if user is None or not password_ok or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS
        )

    # Opportunistically upgrade hashes when Argon2 parameters change.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    token, expires_at = _issue_session(db, user)
    db.commit()

    return _token_response(user, token, expires_at)


@router.get("/me", response_model=UserResponse)
def read_me(user: User = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated account."""
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: OrmSession = Depends(get_db)) -> None:
    """Revoke the presented session so its token stops working immediately."""
    revoke_current_session(request, db)
