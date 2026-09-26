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
