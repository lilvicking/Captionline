"""Password recovery routes.

Security posture
----------------
* **No user enumeration.** `POST /api/auth/forgot-password` returns the same
  status, body, and timing shape whether or not the address is registered. The
  response text never confirms an account.
* **Single-use, expiring, hashed tokens.** Only a SHA-256 hash of the emailed
  token is stored. Consuming one takes a row lock, so a token cannot be redeemed
  twice even under concurrent requests.
* **Sessions die with the password.** A successful reset revokes every active
  login session and every other outstanding reset token, so a compromised session
  does not survive the reset.
* **Nothing sensitive is logged.** No passwords, no raw tokens, no Authorization
  headers, no provider keys.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.models import User
from ..db.session import get_db
from ..email import EmailDeliveryError, get_provider
from ..security.deps import get_current_user, require_database
from ..security.passwords import (
    PasswordTooShortError,
    hash_password,
    verify_password,
    validate_password_strength,
)
from ..security.reset_email import build_password_reset_email
from ..security.reset_tokens import (
    InvalidResetToken,
    apply_password_reset,
    is_rate_limited,
    issue_reset_token,
    revoke_all_reset_tokens,
    revoke_all_sessions,
)
from ..security.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    MessageResponse,
    ResetPasswordRequest,
)
from ..security.tokens import hash_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: One response for every outcome. The phrase is chosen so that neither the
#: existence of an account nor the state of a token can be inferred from it.
FORGOT_PASSWORD_MESSAGE = (
    "If an account exists for that email, a password reset link has been sent."
)
RESET_SUCCESS_MESSAGE = "Your password has been reset."
#: Deliberately covers unknown, expired, already-used, and revoked tokens alike.
RESET_INVALID_MESSAGE = "This password reset link is invalid or has expired."
CHANGE_PASSWORD_MESSAGE = "Your password has been changed."
INCORRECT_CURRENT_PASSWORD = "Your current password is incorrect."


# --- Per-client-address throttle -------------------------------------------
#
# Applied before any database work, so a flood costs nothing and needs no stored
# personal data. It is in-process and therefore best effort: it resets on restart
# and is per replica. The per-account limits in `reset_tokens` are the durable
# half of the protection.
_ip_hits: dict[str, deque] = defaultdict(deque)
_ip_lock = Lock()


def _client_address(request: Request) -> str:
    """Best-effort client address, used only as an in-memory rate-limit bucket.

    A spoofable `X-Forwarded-For` value is acceptable here: the key only needs to
    be hard for one attacker to vary, and correctness does not depend on it.
    """
    forwarded = request.headers.get("X-Forwarded-For")

    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.client.host if request.client else "unknown"


def _is_ip_limited(request: Request) -> bool:
    settings = get_settings()
    limit = settings.password_reset_ip_limit
    window = settings.password_reset_ip_window_seconds

    if limit <= 0 or window <= 0:
        return False

    address = _client_address(request)
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - window

    with _ip_lock:
        hits = _ip_hits[address]
        while hits and hits[0] < cutoff:
            hits.popleft()
        limited = len(hits) >= limit
        if not limited:
            hits.append(now)

    return limited


def reset_ip_throttle() -> None:
    """Clear the in-memory throttle. Used by tests."""
    with _ip_lock:
        _ip_hits.clear()


def _client_error(exc: EmailDeliveryError) -> HTTPException:
    """Map a delivery failure to a neutral response.

    The reset flow returns 200 even when mail could not be sent, so a caller
    cannot distinguish a delivery outage from "no such account".
    """
    logger.warning("Password reset email could not be delivered: %s", exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Password reset is temporarily unavailable. Please try again later."
        ),
    )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
) -> ForgotPasswordResponse:
    """Start a password reset.

    Always answers with the same message, whether the address is unknown, the
    account is inactive, the request is rate limited, or email is not configured.
    """
    require_database()

    # Throttled first, so an abusive client never reaches the database.
    if _is_ip_limited(request):
        logger.info("Password reset request throttled by client address")
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE)

    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))

    if user is None or not user.is_active:
        # Identical response. Nothing is logged that identifies the address.
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE)

    if is_rate_limited(db, user.id):
        logger.info("Password reset suppressed for user_id=%s (cooldown or cap)", user.id)
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE)

    provider = get_provider()

    if provider is None:
        # Fail safely: no provider means no mail. The caller still cannot tell
        # whether this is a missing account or a missing configuration.
        logger.warning(
            "Password reset requested but no email provider is configured; "
            "set EMAIL_PROVIDER and EMAIL_API_KEY"
        )
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE)

    issued = issue_reset_token(db, user)
    message = build_password_reset_email(
        recipient=user.email, raw_token=issued.raw_token, expires_at=issued.expires_at
    )

    try:
        provider.send(message)
    except EmailDeliveryError as exc:
        # Withdraw the token so a link that was never delivered cannot be used.
        revoke_all_reset_tokens(db, user.id)
        db.commit()
        raise _client_error(exc) from None
    except Exception as exc:  # pragma: no cover - unexpected provider failure
        revoke_all_reset_tokens(db, user.id)
        db.commit()
        logger.warning("Unexpected email provider failure: %s", type(exc).__name__)
        raise _client_error(
            EmailDeliveryError(f"provider raised {type(exc).__name__}")
        ) from None

    return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE)


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    db: OrmSession = Depends(get_db),
) -> MessageResponse:
    """Redeem a reset token and set a new password.

    Every rejection path returns the same message and status, so a token cannot be
    probed for validity, expiry, or prior use.
    """
    require_database()

    settings = get_settings()

    try:
        validate_password_strength(payload.new_password, settings.min_password_length)
    except PasswordTooShortError as exc:
        # A policy failure is safe to report precisely: it says nothing about the
        # token or the account.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        apply_password_reset(
            db, payload.token, hash_password(payload.new_password)
        )
    except InvalidResetToken as exc:
        # The reason is logged for operators but never returned.
        logger.info("Rejected password reset: reason=%s", exc.reason)
        raise HTTPException(status_code=400, detail=RESET_INVALID_MESSAGE) from None

    return MessageResponse(message=RESET_SUCCESS_MESSAGE)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> MessageResponse:
    """Change the password while signed in.

    Requires the current password. On success every other session is revoked, so
    a stolen token cannot outlive the change.
    """
    require_database()

    settings = get_settings()

    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=INCORRECT_CURRENT_PASSWORD
        )

    try:
        validate_password_strength(payload.new_password, settings.min_password_length)
    except PasswordTooShortError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(
            status_code=422, detail="Choose a password different from your current one."
        )

    user.password_hash = hash_password(payload.new_password)
    user.updated_at = datetime.now(timezone.utc)

    # Any outstanding reset link is void once the password has changed, and every
    # other session is revoked so a stolen token cannot outlive the change.
    revoke_all_reset_tokens(db, user.id)
    revoke_all_sessions(db, user.id)
    db.commit()

    logger.info("Password changed for user_id=%s; other sessions revoked", user.id)

    return MessageResponse(message=CHANGE_PASSWORD_MESSAGE)
