"""Environment-driven configuration.

Every setting is read from the environment so the same image can run locally and
on Railway without code changes. Nothing here depends on a Windows-specific path
or on local machine state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

TRUE_VALUES = {"1", "true", "yes", "on"}


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
    raw = _env_optional(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_optional(name)
    if raw is None:
        return default
    return raw.lower() in TRUE_VALUES


DEFAULT_DEV_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
)


def _parse_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


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

    # --- Server -----------------------------------------------------------
    host: str = field(default_factory=lambda: _env_str("HOST", "0.0.0.0"))
    # Railway supplies PORT. 8000 is the local default.
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    # Comma-separated list. "*" allows any origin (use for initial testing only).
    cors_origins: list[str] = field(
        default_factory=lambda: _parse_origins(_env_str("CORS_ORIGINS", DEFAULT_DEV_ORIGINS))
    )

    # --- Uploads ----------------------------------------------------------
    # Temporary storage only; the file is deleted once transcription finishes.
    max_upload_bytes: int = field(
        default_factory=lambda: _env_int("MAX_UPLOAD_MB", 500) * 1024 * 1024
    )
    temp_dir: str | None = field(default_factory=lambda: _env_optional("TEMP_DIR"))

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
    def cors_allows_any(self) -> bool:
        return "*" in self.cors_origins


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
