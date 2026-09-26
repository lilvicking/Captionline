"""Auth and account request/response models.

These are the account API contract, separate from the transcription models in
`app/schemas.py`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: int
    email: str
    plan: str
    subscription_status: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Issued on register and login."""

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse


class EntitlementResponse(BaseModel):
    """Server-computed plan, usage, and access state.

    The client never sends these values; they are always derived from the
    authenticated user record so entitlement cannot be spoofed from the browser.
    """

    plan: str
    plan_label: str
    subscription_status: str

    monthly_processing_allowance_seconds: int
    processing_used_seconds: int
    processing_remaining_seconds: int

    usage_period_started_at: datetime
    usage_period_ends_at: datetime

    preview_limit_seconds: int | None
    has_full_preview: bool
    can_export: bool

    # Display-only conveniences derived from the seconds above.
    processing_allowance_minutes: float
    processing_used_minutes: float
    processing_remaining_minutes: float
