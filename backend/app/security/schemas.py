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
    is_paid_plan: bool

    monthly_processing_allowance_seconds: int
    processing_used_seconds: int
    processing_reserved_seconds: int
    processing_remaining_seconds: int

    usage_period_started_at: datetime
    usage_period_ends_at: datetime
    usage_period_months: int
    usage_resets_monthly: bool
    #: True when Stripe bills annually for this plan. Independent of the
    #: monthly usage reset above.
    billed_annually: bool

    preview_limit_seconds: int | None
    has_full_preview: bool
    can_export: bool

    # Display-only conveniences derived from the seconds above.
    processing_allowance_minutes: float
    processing_used_minutes: float
    processing_remaining_minutes: float


class PlanResponse(BaseModel):
    """One entry of the authoritative plan catalogue, for the pricing table.

    Billing and usage cadence are reported separately, because for
    `creator_annual` they differ: billed annually, allowance resets monthly.
    """

    id: str
    label: str

    # --- Billing ---
    price_usd: int
    billing_period: str
    monthly_equivalent_price_usd: int
    annual_savings_usd: int

    # --- Usage ---
    usage_allowance_seconds: int
    usage_period_months: int
    usage_resets_monthly: bool

    # --- Entitlements ---
    preview_limit_seconds: int | None
    has_full_preview: bool
    can_export: bool
    tagline: str
    is_current: bool = False
    purchasable: bool = False


class CheckoutResponse(BaseModel):
    """A Stripe Checkout or Customer Portal session."""

    session_id: str = ""
    url: str
    plan: str


# --- Password reset ---------------------------------------------------------


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Deliberately identical whether or not the account exists.

    The wording is the only signal a caller gets, and it never confirms or denies
    that an address is registered.
    """

    message: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class MessageResponse(BaseModel):
    """A neutral confirmation with no account or token detail."""

    message: str
