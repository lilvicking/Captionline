"""Environment-driven configuration.

Every setting is read from the environment so the same image can run locally and
on Railway without code changes. Nothing here depends on a Windows-specific path
or on local machine state.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

#: Recognised deployment environments. Anything else is treated as development
#: by `is_production`, so a typo can never silently disable the production
#: startup assertions.
PRODUCTION_ENV = "production"


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _env_int(name: str, default: int) -> int:
    """Read an integer setting, complaining loudly when the value is nonsense.

    A bad value must not crash the service, but it must not be swallowed either:
    `MAX_UPLOAD_MB=500MB` used to fall back to the default with no trace at all,
    so a typo silently changed the upload limit.
    """
    raw = _env_optional(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "Ignoring %s=%r: expected a whole number. Falling back to %r.",
            name,
            raw,
            default,
        )
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean setting, complaining loudly when the value is nonsense.

    Unrecognised text used to be read as False, which turned a typo such as
    `HSTS_ENABLED=enabeld` into a silently disabled security control rather than
    a visible configuration mistake.
    """
    raw = _env_optional(name)
    if raw is None:
        return default
    value = raw.lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    logger.warning(
        "Ignoring %s=%r: expected a boolean (%s). Falling back to %r.",
        name,
        raw,
        "/".join(sorted(TRUE_VALUES | FALSE_VALUES)),
        default,
    )
    return default


def _env_bool_opt(name: str) -> bool | None:
    """Read a tri-state boolean: True, False, or None when unset or unreadable."""
    raw = _env_optional(name)
    if raw is None:
        return None
    value = raw.lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    logger.warning(
        "Ignoring %s=%r: expected a boolean (%s). Treating it as unset.",
        name,
        raw,
        "/".join(sorted(TRUE_VALUES | FALSE_VALUES)),
    )
    return None


DEFAULT_DEV_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
)


def _parse_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _is_local_frontend(url: str) -> bool:
    """Whether a frontend URL points back at the developer's own machine."""
    lowered = url.lower()
    return "localhost" in lowered or "127.0.0.1" in lowered or "[::1]" in lowered


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings."""

    # --- WhisperX / model -------------------------------------------------
    # "small" keeps development downloads and VRAM use reasonable. Production can
    # raise this to "large-v2" purely through configuration.
    whisperx_model: str = field(default_factory=lambda: _env_str("WHISPERX_MODEL", "small"))
    # "auto" resolves to CUDA when torch reports a usable GPU, otherwise CPU.
    whisperx_device: str = field(default_factory=lambda: _env_str("WHISPERX_DEVICE", "auto"))
    # "auto" lets CTranslate2 pick float16 on CUDA and int8 on CPU.
    whisperx_compute_type: str = field(
        default_factory=lambda: _env_str("WHISPERX_COMPUTE_TYPE", "auto")
    )
    whisperx_batch_size: int = field(
        default_factory=lambda: _env_int("WHISPERX_BATCH_SIZE", 8)
    )
    # Restrict/force the transcription language. None = auto-detect.
    whisperx_language: str | None = field(
        default_factory=lambda: _env_optional("WHISPERX_LANGUAGE")
    )
    # Alignment model used for word-level timestamps.
    whisperx_align_model: str = field(
        default_factory=lambda: _env_str("WHISPERX_ALIGN_MODEL", "WAV2VEC2_ASR_BASE_960H")
    )
    # Skip word alignment (much faster, but produces no word timestamps).
    whisperx_align_enabled: bool = field(
        default_factory=lambda: _env_bool("WHISPERX_ALIGN_ENABLED", True)
    )

    # --- Deployment environment -------------------------------------------
    # "development" (default), "production", or "test". Production enables the
    # startup assertions in app.main.lifespan that refuse to serve with a
    # configuration known to be unsafe.
    app_env: str = field(default_factory=lambda: _env_str("APP_ENV", "development").lower())

    # --- Server -----------------------------------------------------------
    host: str = field(default_factory=lambda: _env_str("HOST", "0.0.0.0"))
    # Railway supplies PORT. 8000 is the local default.
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    # Comma-separated list. "*" allows any origin (use for initial testing only).
    cors_origins: list[str] = field(
        default_factory=lambda: _parse_origins(_env_str("CORS_ORIGINS", DEFAULT_DEV_ORIGINS))
    )

    # --- Transport and response hardening ---------------------------------
    # Whether a forwarded-for header may be used to derive a rate-limit bucket.
    # Off by default: the header is attacker controlled unless a proxy that
    # overwrites it is known to sit in front of the service, and trusting it
    # blindly lets one client mint unlimited buckets.
    trust_proxy_headers: bool = field(default_factory=lambda: _env_bool("TRUST_PROXY_HEADERS", False))
    # HSTS is only emitted over HTTPS unless this is explicitly turned on, so a
    # local plain-HTTP run is never pinned to HTTPS by a cached header.
    hsts_enabled: bool | None = field(default_factory=lambda: _env_bool_opt("HSTS_ENABLED"))

    # --- Abuse controls ----------------------------------------------------
    # Bounds on the in-process limiter in app.ratelimit. Each limit is applied
    # both per client address and per account, so rotating addresses does not
    # defeat a limit and one account cannot be sprayed from many hosts.
    # A limit or window of 0 disables that bucket.
    rate_limit_max_keys: int = field(default_factory=lambda: _env_int("RATE_LIMIT_MAX_KEYS", 10000))
    register_rate_limit: int = field(default_factory=lambda: _env_int("RATE_LIMIT_REGISTER", 5))
    register_rate_window_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_REGISTER_WINDOW_SECONDS", 3600)
    )
    login_rate_limit: int = field(default_factory=lambda: _env_int("RATE_LIMIT_LOGIN", 10))
    login_rate_window_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_LOGIN_WINDOW_SECONDS", 300)
    )
    transcribe_rate_limit: int = field(default_factory=lambda: _env_int("RATE_LIMIT_TRANSCRIBE", 20))
    transcribe_rate_window_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_TRANSCRIBE_WINDOW_SECONDS", 300)
    )
    checkout_rate_limit: int = field(default_factory=lambda: _env_int("RATE_LIMIT_CHECKOUT", 10))
    checkout_rate_window_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_CHECKOUT_WINDOW_SECONDS", 3600)
    )
    portal_rate_limit: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PORTAL", 10))
    portal_rate_window_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_PORTAL_WINDOW_SECONDS", 3600)
    )
    change_password_rate_limit: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_CHANGE_PASSWORD", 5)
    )
    change_password_rate_window_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_CHANGE_PASSWORD_WINDOW_SECONDS", 900)
    )
    reset_password_rate_limit: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_RESET_PASSWORD", 10)
    )
    reset_password_rate_window_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_RESET_PASSWORD_WINDOW_SECONDS", 900)
    )
    # Account deletion is irreversible and requires a password, so it gets its own
    # bucket rather than sharing one with password changes: a user who mistypes a
    # new password five times must still be able to close their account, and a
    # flood of delete attempts must not be able to borrow budget from a
    # different control to get there.
    delete_account_rate_limit: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_DELETE_ACCOUNT", 5)
    )
    delete_account_rate_window_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_DELETE_ACCOUNT_WINDOW_SECONDS", 900)
    )

    # --- Durable (cross-replica) abuse controls -----------------------------
    # The in-process limiter above is per replica: on a host running N replicas
    # an attacker who reaches all of them gets N times the limit, which is
    # exactly the wrong property for the unauthenticated login, register, and
    # forgot-password endpoints. The durable counter lives in the database and is
    # shared, so the fleet-wide budget is the configured one.
    #
    # The in-process limiter still runs first and in front of it: it needs no
    # database round trip, so a flood is absorbed before it can reach Postgres.
    # Setting this to 0/false removes the durable half and leaves the cheap
    # per-replica pre-filter, which is the documented way to turn it off.
    rate_limit_durable_enabled: bool = field(
        default_factory=lambda: _env_bool("RATE_LIMIT_DURABLE_ENABLED", True)
    )
    # How stale a durable window may be before the table is swept. Windows older
    # than the longest configured bucket window can never be read again, so they
    # are deleted. Only the *interval* is configured: the retention horizon is
    # derived from the bucket windows themselves so the two can never disagree
    # and leave a row behind forever.
    rate_limit_durable_prune_interval_seconds: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS", 300)
    )

    # --- Uploads ----------------------------------------------------------
    # Temporary storage only; the file is deleted once transcription finishes.
    max_upload_bytes: int = field(
        default_factory=lambda: _env_int("MAX_UPLOAD_MB", 500) * 1024 * 1024
    )
    temp_dir: str | None = field(default_factory=lambda: _env_optional("TEMP_DIR"))
    # Age at which a `captionline-*` work directory left behind by a crashed or
    # killed request is swept at startup. Uploaded media is meant to be
    # transient, so anything this old is a leak, not a cache.
    temp_sweep_max_age_seconds: int = field(
        default_factory=lambda: _env_int("TEMP_SWEEP_MAX_AGE_SECONDS", 86400)
    )

    # --- Diagnostics ------------------------------------------------------
    # Loads WhisperX eagerly at startup instead of on the first request.
    preload_model: bool = field(default_factory=lambda: _env_bool("PRELOAD_MODEL", False))

    # --- Database ---------------------------------------------------------
    # Provided by Railway as DATABASE_URL. Optional: without it the service
    # still runs and transcribes, and the account endpoints report that the
    # database is unavailable.
    database_url: str | None = field(default_factory=lambda: _env_optional("DATABASE_URL"))
    database_echo: bool = field(default_factory=lambda: _env_bool("DATABASE_ECHO", False))

    # --- Authentication ---------------------------------------------------
    # Lifetime of an issued bearer session, in days.
    session_ttl_days: int = field(default_factory=lambda: _env_int("SESSION_TTL_DAYS", 30))
    # Minimum accepted password length for registration.
    min_password_length: int = field(default_factory=lambda: _env_int("MIN_PASSWORD_LENGTH", 8))
    # How often expired/revoked session rows are purged opportunistically.
    session_cleanup_interval_seconds: int = field(
        default_factory=lambda: _env_int("SESSION_CLEANUP_INTERVAL_SECONDS", 900)
    )

    # --- Password reset ---------------------------------------------------
    # How long a reset link stays usable.
    password_reset_ttl_minutes: int = field(
        default_factory=lambda: _env_int("PASSWORD_RESET_TTL_MINUTES", 60)
    )
    # Per-account abuse control. A new request is only honoured once the
    # cooldown has passed, so a single address cannot flood the mail provider.
    password_reset_cooldown_seconds: int = field(
        default_factory=lambda: _env_int("PASSWORD_RESET_COOLDOWN_SECONDS", 60)
    )
    # Older outstanding tokens for an account are revoked once this many exist.
    password_reset_max_active: int = field(
        default_factory=lambda: _env_int("PASSWORD_RESET_MAX_ACTIVE", 3)
    )
    # Per-client-address throttle, applied before any database work. In-process
    # and therefore best effort: it needs no personal data and cannot grow
    # without bound, but it resets on restart and is per replica.
    password_reset_ip_limit: int = field(
        default_factory=lambda: _env_int("PASSWORD_RESET_IP_LIMIT", 5)
    )
    password_reset_ip_window_seconds: int = field(
        default_factory=lambda: _env_int("PASSWORD_RESET_IP_WINDOW_SECONDS", 900)
    )

    # --- Transactional email ----------------------------------------------
    # "resend" in production, "console" for local development, "memory" for
    # tests. Unset means no provider, and password reset reports that email is
    # unavailable without revealing whether the account exists.
    email_provider: str = field(
        default_factory=lambda: _env_str("EMAIL_PROVIDER", "none").lower()
    )
    email_api_key: str | None = field(default_factory=lambda: _env_optional("EMAIL_API_KEY"))
    email_from: str = field(
        default_factory=lambda: _env_str("EMAIL_FROM", "Captionline <no-reply@captionline.pro>")
    )
    email_timeout_seconds: int = field(
        default_factory=lambda: _env_int("EMAIL_TIMEOUT_SECONDS", 10)
    )

    # --- Stripe (Phase 3B) ------------------------------------------------
    # No value here is ever invented or committed. When these are absent the
    # billing endpoints report that Stripe is not configured and the rest of the
    # service continues to work.
    stripe_secret_key: str | None = field(
        default_factory=lambda: _env_optional("STRIPE_SECRET_KEY")
    )
    stripe_webhook_secret: str | None = field(
        default_factory=lambda: _env_optional("STRIPE_WEBHOOK_SECRET")
    )
    stripe_price_creator_monthly: str | None = field(
        default_factory=lambda: _env_optional("STRIPE_PRICE_CREATOR_MONTHLY")
    )
    stripe_price_pro_monthly: str | None = field(
        default_factory=lambda: _env_optional("STRIPE_PRICE_PRO_MONTHLY")
    )
    stripe_price_creator_annual: str | None = field(
        default_factory=lambda: _env_optional("STRIPE_PRICE_CREATOR_ANNUAL")
    )
    # Absolute origin of the deployed frontend, used for Stripe success/cancel
    # redirects. Defaults to the first local dev origin when unset.
    frontend_url: str = field(
        default_factory=lambda: _env_str("FRONTEND_URL", "http://localhost:5173")
    )

    # --- Media probing ---------------------------------------------------
    # ffprobe ships with ffmpeg and is used to measure media duration before any
    # processing, so the client never dictates how much is billed.
    ffprobe_path: str = field(default_factory=lambda: _env_str("FFPROBE_PATH", "ffprobe"))
    # Media longer than this is rejected outright (0 disables the cap).
    max_media_duration_seconds: int = field(
        default_factory=lambda: _env_int("MAX_MEDIA_DURATION_SECONDS", 0)
    )
    # A usage reservation left behind by a crashed request is released after this
    # long, so a crash cannot permanently consume a customer's allowance.
    usage_reservation_ttl_seconds: int = field(
        default_factory=lambda: _env_int("USAGE_RESERVATION_TTL_SECONDS", 7200)
    )

    @property
    def stripe_is_configured(self) -> bool:
        """Whether a Stripe secret key is present."""
        return bool(self.stripe_secret_key)

    @property
    def stripe_billing_is_configured(self) -> bool:
        """Whether Stripe can actually create checkout sessions.

        Requires both a secret key and at least one Price ID.
        """
        return bool(
            self.stripe_secret_key
            and (
                self.stripe_price_creator_monthly
                or self.stripe_price_pro_monthly
                or self.stripe_price_creator_annual
            )
        )

    @property
    def is_production(self) -> bool:
        """Whether production startup assertions apply.

        Any value other than "production" behaves as development, so a
        misspelled APP_ENV cannot turn the assertions off silently.
        """
        return self.app_env == PRODUCTION_ENV

    @property
    def cors_allows_any(self) -> bool:
        """Whether CORS_ORIGINS contains an explicit wildcard.

        This must be an equality test, not a membership test. `"*" in
        self.cors_origins` asked whether the single character appears anywhere
        in the list, so `CORS_ORIGINS=https://captionline.pro,*` reported True
        and the configured origin was thrown away in favour of allowing every
        origin.
        """
        return any(origin.strip() == "*" for origin in self.cors_origins)

    def production_problems(self) -> list[str]:
        """Configuration faults that must prevent a production deployment.

        Each entry is a complete, actionable sentence so a fatal startup log
        tells an operator exactly which variable to change. Returning a list
        rather than raising keeps the caller in charge of how loudly to fail.
        """
        problems: list[str] = []

        if self.cors_allows_any:
            problems.append(
                "CORS_ORIGINS contains '*'. List the exact frontend origins "
                "(for example https://captionline.pro) instead of a wildcard."
            )

        if self.email_provider_is_development_only:
            problems.append(
                f"EMAIL_PROVIDER={self.email_provider} is a development or test "
                "provider and would print password reset links to the log. Set "
                "EMAIL_PROVIDER=resend with a real EMAIL_API_KEY."
            )

        if self.database_echo:
            problems.append(
                "DATABASE_ECHO is enabled, so every SQL statement (including "
                "bind parameters) would be logged. Set DATABASE_ECHO=0."
            )

        frontend = (self.frontend_url or "").strip()
        if not frontend:
            problems.append("FRONTEND_URL is not set, so reset and checkout links have no origin.")
        elif not frontend.lower().startswith("https://"):
            problems.append(
                f"FRONTEND_URL={frontend!r} is not an https origin, so reset links "
                "would travel in clear text. Set an https URL."
            )
        elif _is_local_frontend(frontend):
            problems.append(
                f"FRONTEND_URL={frontend!r} points at localhost. Set the deployed "
                "frontend origin."
            )

        if self.stripe_secret_key and not frontend.lower().startswith("https://"):
            problems.append(
                "STRIPE_SECRET_KEY is set but FRONTEND_URL is not https, so Stripe "
                "success and cancel redirects would leave the user on a clear-text "
                "origin. Set an https FRONTEND_URL."
            )

        if self.email_provider == "resend" and not self.email_api_key:
            problems.append(
                "EMAIL_PROVIDER=resend but EMAIL_API_KEY is missing, so no password "
                "reset mail can be sent. Set EMAIL_API_KEY or choose another provider."
            )

        return problems

    @property
    def email_is_configured(self) -> bool:
        """Whether a usable transactional email provider is configured.

        "console" and "memory" are development/test providers. They are only ever
        active when explicitly selected through EMAIL_PROVIDER, never as a
        fallback, so a production deployment cannot silently print reset links.
        """
        provider = self.email_provider

        if provider == "resend":
            return bool(self.email_api_key)

        return provider in {"console", "memory"}

    @property
    def email_provider_is_development_only(self) -> bool:
        """True when the configured provider must never be used in production."""
        return self.email_provider in {"console", "memory"}


def resolve_device(requested: str) -> str:
    """Return the device to use, falling back to CPU when CUDA is unavailable."""
    if requested and requested != "auto":
        return requested

    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # pragma: no cover - torch import problems fall back to CPU
        pass

    return "cpu"


def resolve_compute_type(requested: str, device: str) -> str:
    """CTranslate2 needs an explicit type; pick a safe default per device."""
    if requested and requested != "auto":
        return requested

    return "float16" if device == "cuda" else "int8"


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
