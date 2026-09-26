"""Shared FastAPI dependencies for authenticated routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.models import Session as SessionModel
from ..db.models import User
from ..db.session import DATABASE_UNAVAILABLE, get_db, is_configured
from ..usage import ensure_current_usage_period
from .tokens import hash_token

CREDENTIALS_REQUIRED = "Not authenticated."
INVALID_CREDENTIALS = "Invalid email or password."


def require_database() -> None:
    """Fail clearly when account routes are used without a database."""
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DATABASE_UNAVAILABLE,
        )


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header:
        return None

    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None

    return value.strip()


def get_current_user(
    request: Request,
    db: OrmSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from a bearer token.

    Raises 401 when the token is missing, unknown, revoked, or expired.
    """
    require_database()

    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=CREDENTIALS_REQUIRED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = datetime.now(timezone.utc)

    session_row = db.scalar(
        select(SessionModel).where(SessionModel.token_hash == hash_token(token))
    )

    if session_row is None or session_row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked session.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expires_at = session_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now >= expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, session_row.user_id)

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Usage periods roll lazily on read.
    if ensure_current_usage_period(user, now):
        db.commit()

    session_row.last_used_at = now
    db.commit()

    return user


def revoke_current_session(
    request: Request,
    db: OrmSession = Depends(get_db),
) -> None:
    """Revoke the presented token. Used by POST /api/auth/logout."""
    require_database()

    token = _extract_bearer_token(request)
    if not token:
        # Logging out without a token is not an error worth failing on.
        return

    session_row = db.scalar(
        select(SessionModel).where(SessionModel.token_hash == hash_token(token))
    )

    if session_row is not None and session_row.revoked_at is None:
        session_row.revoked_at = datetime.now(timezone.utc)
        db.commit()


__all__ = [
    "CREDENTIALS_REQUIRED",
    "DATABASE_UNAVAILABLE",
    "INVALID_CREDENTIALS",
    "get_current_user",
    "get_settings",
    "require_database",
    "revoke_current_session",
]
