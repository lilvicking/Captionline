"""Account registration, login, and session routes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.models import Session as SessionModel
from ..db.models import User
from ..db.session import get_db
from ..usage import add_month, apply_plan_to_user, monthly_period_start
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_TAKEN = "An account with that email already exists."


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
def register(payload: RegisterRequest, db: OrmSession = Depends(get_db)) -> TokenResponse:
    """Create an account on the free plan and issue a session."""
    require_database()

    settings = get_settings()
    email = _normalize_email(payload.email)

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
    period_start = monthly_period_start(now)

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        created_at=now,
        updated_at=now,
        usage_period_started_at=period_start,
        usage_period_ends_at=add_month(period_start, 1),
    )

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
def login(payload: LoginRequest, db: OrmSession = Depends(get_db)) -> TokenResponse:
    """Exchange email and password for a session token."""
    require_database()

    email = _normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))

    # A missing account and a wrong password must be indistinguishable to the
    # caller, so the same message and status are used for both.
    stored_hash = user.password_hash if user is not None else ""
    password_ok = verify_password(payload.password, stored_hash) if stored_hash else False

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
