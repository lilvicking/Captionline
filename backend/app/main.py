"""Captionline transcription service (FastAPI).

Deployment notes
----------------
Binds to 0.0.0.0 and reads PORT so it runs unchanged on Railway:

    uvicorn app.main:app --host 0.0.0.0 --port $PORT

All configuration comes from the environment (see `app/config.py` and
`backend/.env.example`). Uploads are written to a temporary directory and always
deleted in a `finally` block, so no persistent disk or cloud storage is required.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session as OrmSession
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import Settings, get_settings
from .db.models import User
from .db.session import get_db, is_configured
from .headers import SecurityHeadersMiddleware
from .media import MediaProbeError, billable_seconds, probe_media
from .ratelimit import enforce, reset_rate_limits
from .routers import account, auth, billing, password_reset
from .routers.account import legal_router
from .schemas import DatabaseHealth, HealthResponse, StripeHealth, TranscriptionResponse
from .security.deps import get_current_user
from .security.sessions import purge_expired_sessions
from .stripe_client import refresh_price_mapping
from .transcribe import (
    ModelUnavailableError,
    cuda_available,
    model_state,
    preload,
    transcribe_file,
)
from .usage import (
    AllowanceExceededError,
    finalize_reservation,
    release_reservation,
    release_stale_reservations,
    reserve_processing_seconds,
)

logger = logging.getLogger(__name__)

# Chunk size used when streaming an upload to disk, so large videos never sit in
# memory in full.
UPLOAD_CHUNK_BYTES = 1024 * 1024

#: Prefix of the per-request work directory, which is also what the startup sweep
#: looks for. It must stay specific: the sweep walks TEMP_DIR, which is the
#: system temp directory when TEMP_DIR is unset.
WORK_DIR_PREFIX = "captionline-"

#: A client-supplied filename is only ever echoed back or logged after this.
MAX_ECHOED_FILENAME_CHARS = 120

#: C0/C1 control characters, including NUL, newline, and CR. Stripping them
#: stops log forging and stops a terminal escape sequence reaching an operator's
#: console.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")

ALLOWED_SUFFIXES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".m4v": "video/x-m4v",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}

ALLOWED_CONTENT_TYPES = set(ALLOWED_SUFFIXES.values())


def sanitize_filename(name: str) -> str:
    """Make a client-supplied filename safe to log and to echo in an error.

    The name is fully attacker controlled, so before it reaches a log line or a
    JSON response it loses its control characters (log forging, terminal escape
    sequences), its quotes, and anything past a sane length.
    """
    cleaned = _CONTROL_CHARACTERS.sub("", name or "").replace('"', "'").strip()

    if len(cleaned) > MAX_ECHOED_FILENAME_CHARS:
        cleaned = cleaned[:MAX_ECHOED_FILENAME_CHARS] + "..."

    return cleaned or "upload"


def _safe_suffix(filename: str) -> str:
    """Choose the on-disk extension from the allow-list and nothing else.

    The client's filename never reaches the filesystem. Previously the extension
    came straight from the upload, so an arbitrary or very long extension was
    written to disk verbatim. ffprobe identifies the container by content, so
    falling back to `.bin` costs nothing.
    """
    suffix = os.path.splitext(filename)[1].lower()
    return suffix if suffix in ALLOWED_SUFFIXES else ".bin"


def sweep_stale_work_directories(base_dir: str | None, max_age_seconds: int) -> int:
    """Delete `captionline-*` work directories older than the configured age.

    Each request removes its own directory in a `finally` block, so anything
    still here belongs to a request that was killed mid-flight (an OOM, a
    deploy, a SIGKILL) and is uploaded customer media sitting on disk. It is a
    leak, not a cache. Best effort by design: every failure is swallowed so a
    locked file or a read-only volume can never stop the service from starting.
    """
    if max_age_seconds <= 0:
        return 0

    root = base_dir or tempfile.gettempdir()
    cutoff = time.time() - max_age_seconds
    removed = 0

    try:
        candidates = os.listdir(root)
    except OSError as exc:
        logger.warning("Temp sweep could not list %s: %s", root, type(exc).__name__)
        return 0

    for name in candidates:
        if not name.startswith(WORK_DIR_PREFIX):
            continue

        path = os.path.join(root, name)

        try:
            if not os.path.isdir(path):
                continue
            if os.path.getmtime(path) > cutoff:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError as exc:  # pragma: no cover - housekeeping is best effort
            logger.warning("Temp sweep skipped %s: %s", name, type(exc).__name__)

    if removed:
        logger.info("Temp sweep removed %d stale upload director%s", removed, "y" if removed == 1 else "ies")

    return removed


def assert_production_ready(resolved: Settings) -> None:
    """Refuse to serve in production with a configuration known to be unsafe.

    Each problem is a misconfiguration that would silently weaken a security
    control in a way that is invisible until it matters: a wildcard CORS origin,
    reset tokens printed to the log by the console provider, SQL bind parameters
    including password hashes in the log, or a reset link pointing at localhost.
    Failing at startup is far cheaper than discovering it during an incident.
    """
    problems = resolved.production_problems()

    if not problems:
        return

    for problem in problems:
        logger.critical("FATAL: refusing to start in production. %s", problem)

    raise RuntimeError(
        "Refusing to start with APP_ENV=production because the configuration is "
        "not safe. " + " ".join(problems)
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "Captionline transcription service %s starting (model=%s align=%s env=%s)",
        __version__,
        settings.whisperx_model,
        settings.whisperx_align_enabled,
        settings.app_env,
    )

    # Fail before binding any traffic rather than after.
    if settings.is_production:
        assert_production_ready(settings)
    elif not settings.email_is_configured:
        # Not fatal outside production, but it means password reset cannot work
        # and a customer will not be told, so say so at boot.
        logger.warning(
            "Transactional email is not configured (EMAIL_PROVIDER=%s). Password "
            "reset links cannot be sent.",
            settings.email_provider or "unset",
        )
    else:
        logger.info("Transactional email provider: %s", settings.email_provider)

    # Nothing can be over budget in a process that has just started, and this
    # keeps the counters out of whatever a previous test run left behind.
    reset_rate_limits()

    # Reclaim anything a killed request left on disk. Off the event loop and
    # best effort, so a slow or unwritable volume cannot delay startup.
    await run_in_threadpool(
        sweep_stale_work_directories,
        settings.temp_dir,
        settings.temp_sweep_max_age_seconds,
    )

    # Build the Stripe Price ID -> plan mapping from the environment.
    refresh_price_mapping()

    if settings.stripe_secret_key:
        logger.info("Stripe is configured.")
    else:
        # Not an error: transcription and accounts work without it, and the
        # pricing UI reports that checkout is unavailable.
        logger.info("Stripe is not configured; billing endpoints will report as unavailable.")

    if settings.preload_model:
        # Off the event loop: model loading can take a while.
        await run_in_threadpool(preload, settings)
    yield


app = FastAPI(
    title="Captionline Transcription Service",
    version=__version__,
    description="WhisperX-backed transcription with word-level timestamps for Captionline.",
    lifespan=lifespan,
)

settings = get_settings()

if settings.cors_allows_any:
    logger.warning("CORS_ORIGINS is '*': allowing every origin. Do not use this in production.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        # A wildcard origin can never be combined with credentials: the
        # browser would reject the response, and pairing them is a
        # misconfiguration that only works by accident. This branch is also
        # the one APP_ENV=production refuses to start in.
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

# Added last, so it wraps CORS: preflight responses are hardened too.
app.add_middleware(SecurityHeadersMiddleware, hsts_enabled=settings.hsts_enabled)

app.include_router(auth.router)
app.include_router(password_reset.router)
app.include_router(account.router)
# Unprefixed, so /api/legal/versions is reachable while signed out. Defined in
# app/routers/account.py next to the rest of the account surface.
app.include_router(legal_router)
app.include_router(billing.router)


def _database_health() -> DatabaseHealth:
    """Report database reachability without exposing any connection detail."""
    if not is_configured():
        return DatabaseHealth(configured=False, reachable=False, status="not_configured")

    from sqlalchemy import text

    from .db.session import get_session_factory

    factory = get_session_factory()

    if factory is None:
        return DatabaseHealth(configured=True, reachable=False, status="error")

    try:
        session = factory()
        try:
            session.execute(text("SELECT 1"))
        finally:
            session.close()
    except Exception as exc:
        # Log the detail, return only the coarse status.
        logger.warning("Database health check failed: %s", exc)
        return DatabaseHealth(configured=True, reachable=False, status="error")

    return DatabaseHealth(configured=True, reachable=True, status="ok")


def _looks_like_media(filename: str, content_type: str | None) -> bool:
    suffix = os.path.splitext(filename)[1].lower()
    if suffix in ALLOWED_SUFFIXES:
        return True
    if content_type and content_type.lower() in ALLOWED_CONTENT_TYPES:
        return True
    return bool(content_type and content_type.lower().startswith(("video/", "audio/")))


async def _save_upload(upload: UploadFile, destination: str, limit: int) -> int:
    """Stream an upload to disk, enforcing the size limit as we go."""
    written = 0

    with open(destination, "wb") as handle:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break

            written += len(chunk)
            if written > limit:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "File is larger than the configured limit of "
                        f"{limit // (1024 * 1024)} MB."
                    ),
                )

            handle.write(chunk)

    if written == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    return written


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness/readiness probe used by Railway and local checks.

    Reports database reachability as a coarse status only. The connection string
    is never included, and connection errors are logged server-side rather than
    returned, so credentials cannot leak through this endpoint.
    """
    state = model_state(settings)

    return HealthResponse(
        status="ok",
        version=__version__,
        whisperx_model=settings.whisperx_model,
        device=str(state["device"] or settings.whisperx_device),
        compute_type=str(state["compute_type"] or settings.whisperx_compute_type),
        batch_size=settings.whisperx_batch_size,
        model_loaded=bool(state["loaded"]),
        alignment_enabled=settings.whisperx_align_enabled,
        cuda_available=cuda_available(),
        database=_database_health(),
        stripe=StripeHealth(
            configured=settings.stripe_is_configured,
            billing_configured=settings.stripe_billing_is_configured,
            webhook_configured=bool(settings.stripe_webhook_secret),
        ),
    )


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "captionline-transcription",
        "version": __version__,
        "health": "/api/health",
        "transcribe": "/api/transcribe",
        "plans": "/api/account/plans",
    }


@app.post("/api/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> TranscriptionResponse:
    """Transcribe an uploaded video or audio file for an authenticated account.

    Order of operations, which is what makes the accounting safe:

      1. authenticate (the dependency rejects anonymous callers with 401)
      2. stream the upload to a temporary directory
      3. measure the real duration server-side with ffprobe — the client never
         declares its own length
      4. reserve allowance under a row lock, or reject with 402 before WhisperX
         spends any compute
      5. transcribe and align
      6. finalize the reservation on success, release it on any failure

    The temporary directory is removed in `finally`, so the uploaded media is
    never retained, including on failure paths.
    """
    # Throttled before any disk write, probe, or reservation.
    enforce("transcribe", request, account=str(user.id))

    # The client-supplied name is used for the display name and error text only.
    # It is never used verbatim on disk or in a log line.
    filename = os.path.basename(file.filename or "upload")
    display_name = sanitize_filename(filename)
    content_type = file.content_type

    if not _looks_like_media(filename, content_type):
        await file.close()
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type for '{display_name}'. Upload a video or audio file "
                "(mp4, mov, mkv, webm, mp3, wav, m4a, flac, ogg)."
            ),
        )

    # Reclaim any hold left behind by an earlier crashed request.
    try:
        release_stale_reservations(db, settings.usage_reservation_ttl_seconds)
        purge_expired_sessions(db)
    except Exception as exc:  # pragma: no cover - housekeeping must not block work
        logger.warning("Housekeeping skipped: %s", type(exc).__name__)

    # Ephemeral by design: a fresh directory per request, always cleaned up.
    work_dir = tempfile.mkdtemp(prefix=WORK_DIR_PREFIX, dir=settings.temp_dir)
    reservation_id = 0

    try:
        # The extension comes from the allow-list, never from the client name.
        destination = os.path.join(work_dir, f"input{_safe_suffix(filename)}")

        await _save_upload(file, destination, settings.max_upload_bytes)
        await file.close()

        # --- Server-side measurement -------------------------------------
        try:
            media = await run_in_threadpool(probe_media, destination)
        except MediaProbeError as exc:
            # Reject rather than transcribe for free: an unmeasurable file cannot
            # be billed, and free unmetered transcription is worse than a refusal.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        required_seconds = billable_seconds(media.duration_seconds)

        if not media.has_audio:
            raise HTTPException(
                status_code=422,
                detail="The uploaded file has no audio track to transcribe.",
            )

        if (
            settings.max_media_duration_seconds > 0
            and required_seconds > settings.max_media_duration_seconds
        ):
            raise HTTPException(
                status_code=413,
                detail=(
                    "This file is longer than the maximum supported length of "
                    f"{settings.max_media_duration_seconds} seconds."
                ),
            )

        # --- Allowance reservation ---------------------------------------
        try:
            reservation = await run_in_threadpool(
                reserve_processing_seconds, db, user, required_seconds
            )
            reservation_id = reservation.reservation_id
        except AllowanceExceededError as exc:
            raise HTTPException(status_code=402, detail=exc.detail) from exc

        logger.info(
            "Transcribing %s: %ss required, %ss remaining after reservation",
            display_name,
            required_seconds,
            reservation.remaining_seconds,
        )

        # --- Transcription ------------------------------------------------
        try:
            result = await run_in_threadpool(transcribe_file, destination, settings)
        except Exception:
            # Never charge for work that did not succeed.
            await run_in_threadpool(release_reservation, db, reservation_id)
            reservation_id = 0
            raise

        # Charge only for a successful transcription.
        await run_in_threadpool(finalize_reservation, db, reservation_id)
        reservation_id = 0

        logger.info(
            "Transcription complete: %d segments, language=%s, aligned=%s",
            len(result.segments),
            result.language,
            result.word_aligned,
        )
        return result

    except HTTPException:
        raise
    except ModelUnavailableError as exc:
        logger.error("Transcription engine unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Transcription is temporarily unavailable. Please try again shortly.",
        ) from exc
    except RuntimeError as exc:
        # Message comes from our own decoder wrapper, not from a library.
        logger.warning("Transcription rejected the media: %s", exc)
        raise HTTPException(status_code=422, detail="The uploaded file could not be transcribed.") from exc
    except Exception as exc:  # pragma: no cover
        # The detail is deliberately generic: stack traces and internal paths
        # must never reach the client.
        logger.exception("Unexpected transcription error")
        raise HTTPException(
            status_code=500, detail="Something went wrong while transcribing this file."
        ) from exc
    finally:
        if reservation_id:
            # Safety net: if an exception escaped before the handlers above ran,
            # the hold is released so the customer is not charged.
            try:
                await run_in_threadpool(release_reservation, db, reservation_id)
            except Exception:  # pragma: no cover
                logger.warning("Could not release reservation %s", reservation_id)

        shutil.rmtree(work_dir, ignore_errors=True)
