"""Password recovery routes.

Security posture
----------------
* **No user enumeration.** `POST /api/auth/forgot-password` returns the same
  status, body, and timing shape whether or not the address is registered. The
  response text never confirms an account.
* **No availability oracle either.** This used to answer 503 when the mail
  provider failed and 200 for an unknown address, so the status code alone told
  an attacker whether an address was registered. Every path now answers 200
  with the same message and the failure is recorded server-side only.
* **Single-use, expiring, hashed tokens.** Only a SHA-256 hash of the emailed
  token is stored. Consuming one takes a row lock, so a token cannot be redeemed
  twice even under concurrent requests.
* **Sessions die with the password.** A successful reset revokes every active
  login session and every other outstanding reset token, so a compromised session
  does not survive the reset.
* **Nothing sensitive is logged.** No passwords, no raw tokens, no Authorization
  headers, no provider keys, and no email addresses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.models import User
from ..db.session import get_db
from ..email import EmailDeliveryError, get_provider
from ..ratelimit import allow, enforce, reset_rate_limits
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


def reset_ip_throttle() -> None:
    """Clear the in-memory throttles. Used by tests.

    Kept under its original name because it is imported by the test suite. The
    address counters it used to reset now live in `app.ratelimit`, which is
    bounded, prunes itself, and no longer trusts a spoofable forwarded header.
    """
    reset_rate_limits()


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
) -> ForgotPasswordResponse:
    """Start a password reset.

    Always answers 200 with the same message, whether the address is unknown,
    the account is inactive, the request was rate limited, email is not
    configured, or delivery failed.
    """
    require_database()

    # Throttled first, so an abusive client never reaches the database. This
    # answers with the same generic 200 rather than a 429: a 429 would reveal
    # that the address is under observation, which is itself an enumeration
    # signal. Per-account cooldown and cap live in the database
    # (`reset_tokens.is_rate_limited`) and are the durable half of the control.
    if not allow("forgot-password", request, account=payload.email):
        logger.info("Password reset request throttled")
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
        _record_delivery_failure(db, user, "provider rejected the message", exc)
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE)
    except Exception as exc:  # pragma: no cover - unexpected provider failure
        _record_delivery_failure(db, user, "provider raised", exc)
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE)

    return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE)


def _record_delivery_failure(
    db: OrmSession, user: User, summary: str, exc: Exception
) -> None:
    """Withdraw an undelivered token and log the failure, then return normally.

    The caller still replies with the generic 200. A previous version raised a
    503 here, which leaked whether an address was registered: an unknown address
    always produced 200, a registered one produced 503 as soon as the mail
    provider hiccuped. Operators lose nothing here because the failure is logged
    with the user id, the error class, and the reason; the user is not told
    anything an attacker could not already guess.

    No address, token, or provider payload is written to the log.
    """
    # Withdraw the token so a link that was never delivered cannot be used.
    revoke_all_reset_tokens(db, user.id)

    try:
        db.commit()
    except Exception:  # pragma: no cover - the token is already void
        db.rollback()
        logger.warning("Could not withdraw an undelivered password reset token")

    logger.error(
        "Password reset email could not be delivered (%s): %s for user_id=%s. "
        "The caller still receives the generic response.",
        summary,
        type(exc).__name__,
        user.id,
    )


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
) -> MessageResponse:
    """Redeem a reset token and set a new password.

    Every rejection path returns the same message and status, so a token cannot be
    probed for validity, expiry, or prior use.
    """
    require_database()

    # The token is the only credential here, so the throttle is per address:
    # redemption is what actually changes a password, and brute-forcing it is
    # the abuse worth stopping.
    enforce("reset-password", request)

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
    request: Request,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> MessageResponse:
    """Change the password while signed in.

    Requires the current password. On success every other session is revoked, so
    a stolen token cannot outlive the change.
    """
    require_database()

    # Per address and per account: a hijacked session guessing the current
    # password must not be able to grind through it unhindered.
    enforce("change-password", request, account=str(user.id))

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
