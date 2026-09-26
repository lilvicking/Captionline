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
import shutil
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import get_settings
from .schemas import HealthResponse, TranscriptionResponse
from .transcribe import (
    ModelUnavailableError,
    cuda_available,
    model_state,
    preload,
    transcribe_file,
)

logger = logging.getLogger(__name__)

# Chunk size used when streaming an upload to disk, so large videos never sit in
# memory in full.
UPLOAD_CHUNK_BYTES = 1024 * 1024

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "Captionline transcription service %s starting (model=%s align=%s)",
        __version__,
        settings.whisperx_model,
        settings.whisperx_align_enabled,
    )
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
    """Liveness/readiness probe used by Railway and local checks."""
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
    )


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "captionline-transcription",
        "version": __version__,
        "health": "/api/health",
        "transcribe": "/api/transcribe",
    }


@app.post("/api/transcribe", response_model=TranscriptionResponse)
async def transcribe(file: UploadFile = File(...)) -> TranscriptionResponse:
    """Transcribe an uploaded video or audio file.

    The file is written to a temporary directory, transcribed and aligned with
    WhisperX, and the temporary directory is removed before returning.
    """
    filename = os.path.basename(file.filename or "upload")
    content_type = file.content_type

    if not _looks_like_media(filename, content_type):
        await file.close()
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type for '{filename}'. Upload a video or audio file "
                "(mp4, mov, mkv, webm, mp3, wav, m4a, flac, ogg)."
            ),
        )

    # Ephemeral by design: a fresh directory per request, always cleaned up.
    work_dir = tempfile.mkdtemp(prefix="captionline-", dir=settings.temp_dir)

    try:
        suffix = os.path.splitext(filename)[1].lower() or ".bin"
        destination = os.path.join(work_dir, f"input{suffix}")

        await _save_upload(file, destination, settings.max_upload_bytes)
        await file.close()

        logger.info("Transcribing upload %s (%s)", filename, content_type)

        # CPU/GPU heavy work must not block the event loop.
        result = await run_in_threadpool(transcribe_file, destination, settings)

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
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error("Transcription failed: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected transcription error")
        raise HTTPException(
            status_code=500, detail=f"Unexpected transcription error: {exc}"
        ) from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
