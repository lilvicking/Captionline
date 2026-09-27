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

    #: Legal consent, recorded but never required. Both default to False so an
    #: older client that sends only email and password keeps working, and so a
    #: signup that somehow omits them cannot be blocked. The frontend presents
    #: the agreement; the backend only remembers what the user asserted. Nothing
    #: reads these back to gate sign-in, so a user who never ticked a box is not
    #: locked out — see the note on the consent columns in `db/models.py`.
    accepted_terms: bool = False
    acknowledged_privacy: bool = False


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
    #: Whether this account may open the support console. The frontend uses it
    #: only to decide whether to offer the link; the server enforces access on
    #: every admin endpoint regardless.
    is_admin: bool = False

    monthly_processing_allowance_seconds: int
    processing_used_seconds: int
    processing_reserved_seconds: int
    #: Administrative goodwill credit, added to the plan allowance.
    bonus_processing_seconds: int = 0
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


# --- Account deletion --------------------------------------------------------


class AccountDeletionRequest(BaseModel):
    """Proof that the caller really means it, for an irreversible action.

    Two independent checks: the current password, so a borrowed or replayed
    session cannot destroy an account, and a literal typed confirmation, so a
    stray or automated request cannot either.

    `confirmation` defaults to an empty string rather than being required, so a
    caller that omits it gets the endpoint's own explicit 400 explaining what is
    missing instead of a generic schema 422. Either way the request is refused;
    the shape of the refusal is simply the one that tells the user what to do.
    """

    current_password: str = Field(min_length=1, max_length=1024)
    confirmation: str = Field(default="", max_length=64)


class AccountDeletionResponse(MessageResponse):
    """The neutral confirmation, plus what this action does *not* delete.

    `message` is exactly the neutral sentence and nothing else, so it can never
    grow wording that echoes a submitted value or hints at internal state. The
    Stripe retention point is a separate field because it is a disclosure the
    customer is entitled to, and keeping it out of `message` lets the frontend
    place it where the confirmation is actually explained.

    `deleted` is a machine-readable success flag. It is always true here: this
    response is only ever produced after the commit succeeds, and a failure
    returns a 5xx with no body of this shape. A client that keys off a field
    rather than off prose gets an unambiguous answer.
    """

    deleted: bool = True
    stripe_data_note: str


# --- Legal -------------------------------------------------------------------


class LegalVersionsResponse(BaseModel):
    """The legal text currently in force, for rendering without hardcoding.

    Public and unauthenticated: the signup page has to show the versions before
    there is an account to sign in to. The values come from `app/terms.py`, so
    the frontend can never display a version the backend is not actually
    recording.
    """

    terms_version: str
    terms_effective_date: str
    privacy_version: str
    privacy_effective_date: str

    #: None when no support mailbox is configured. The frontend must not render
    #: a mailto link to an address that is not monitored.
    support_email: str | None = None
    support_email_configured: bool = False

    #: Placeholder text until counsel has chosen a jurisdiction. Exposed so it
    #: is visible in the rendered product rather than only in this repository.
    governing_law: str
