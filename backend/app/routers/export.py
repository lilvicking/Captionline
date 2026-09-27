"""Finished-video export.

`POST /api/export/video` takes the source video plus the caption data and style
currently in the editor, burns the captions in, and streams back an MP4.

Notes on behaviour that matters elsewhere:

* **Export does not consume processing allowance.** Transcription is what costs
  processing time, and it is charged once, by `/api/transcribe`. Re-rendering
  after a caption or style change is unlimited and free, so this endpoint never
  touches usage accounting.
* **Every plan is entitled.** Entitlement is read from the authenticated
  account's `can_export` flag, which is true for Free and every paid plan.
* **No transcription happens here.** The captions sent by the editor are
  rendered as given, so corrections the user made are what appears in the file.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as OrmSession
from starlette.background import BackgroundTask

from ..config import get_settings
from ..db.models import User
from ..db.session import get_db
from ..render.filenames import build_output_filename
from ..render.ffmpeg import renderer_available
from ..render.models import RenderRequest
from ..render.service import (
    SOURCE_NAME,
    RenderError,
    RenderResult,
    RenderTimeout,
    RenderUnavailable,
    acquire_render_slot,
    create_render_directory,
    discard_render_directory,
    probe_container_format,
    release_render_slot,
    render_video,
    source_extension_for,
)
from ..security.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export", tags=["export"])

#: Stem used for the saved upload inside the private render directory. Chosen by
#: this service, never taken from the client.
SOURCE_STEM = SOURCE_NAME

#: Cap the declared content type of the uploaded source. The real type is
#: determined by ffprobe, never trusted from the client.
ALLOWED_VIDEO_MIME_PREFIXES = ("video/",)
ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".flv", ".ts", ".mpg", ".mpeg",
}

UNSUPPORTED_MEDIA = "That file is not a supported video."
PAYLOAD_TOO_LARGE = "The caption data is too large to render."
NO_CAPTIONS = "There are no captions to burn into the video."
CAPACITY_BUSY = "Another export is already running. Please try again in a moment."


def _parse_payload(raw: str, label: str) -> dict:
    """Parse and bound a JSON field from a multipart form."""
    settings = get_settings()

    if len(raw.encode("utf-8")) > settings.export_max_payload_bytes:
        raise HTTPException(status_code=413, detail=PAYLOAD_TOO_LARGE)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"The {label} could not be read."
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=f"The {label} must be an object.")

    return parsed


def _looks_like_video(upload: UploadFile) -> bool:
    """Cheap pre-filter. ffprobe has the final say."""
    content_type = (upload.content_type or "").lower()

    if content_type.startswith(ALLOWED_VIDEO_MIME_PREFIXES):
        return True

    suffix = Path((upload.filename or "").rsplit(".", 1)[-1]).lower() if "." in (upload.filename or "") else ""
    return f".{suffix}" in ALLOWED_VIDEO_EXTENSIONS


@router.post("/video")
async def export_video(
    video: UploadFile = File(...),
    captions: str = Form(...),
    style: str = Form(...),
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> FileResponse:
    """Render the supplied captions into the video and stream back an MP4."""
    del db  # Entitlement is read from the already-resolved account.

    if not renderer_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Finished-video export is not available on this server right now.",
        )

    # Entitlement is a commercial answer the server already computed. Every
    # current plan carries it, so Free is not blocked.
    if not user.can_export:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Finished-video export is not included with your plan.",
        )

    payload = _parse_payload(captions, "captions")
    payload["style"] = _parse_payload(style, "style")

    try:
        render_request = RenderRequest.model_validate(payload)
    except Exception as exc:
        # Pydantic's message can echo submitted values, so the detail is generic.
        logger.info("Rejected an export payload: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The caption data or style could not be used.",
        ) from exc

    if not render_request.captions:
        raise HTTPException(status_code=400, detail=NO_CAPTIONS)

    if not _looks_like_video(video):
        raise HTTPException(status_code=415, detail=UNSUPPORTED_MEDIA)

    # Refuse rather than queue: a backlog on a small instance would time out
    # every waiting request.
    if not acquire_render_slot():
        raise HTTPException(status_code=429, detail=CAPACITY_BUSY)

    settings = get_settings()
    work_dir: Path | None = None
    # Set once the response owns the file, so the finally block leaves it alone.
    handed_off = False

    try:
        work_dir = create_render_directory()

        # The uploaded bytes are streamed to disk in chunks so a large video never
        # sits in memory in full.
        probe_tmp = work_dir / "upload.bin"
        written = 0

        with probe_tmp.open("wb") as handle:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.export_max_file_mb * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail="That video is larger than this service can render.",
                    )
                handle.write(chunk)

        await video.close()

        if written == 0:
            raise HTTPException(status_code=400, detail="The uploaded video was empty.")

        # The extension is chosen by this service from the probed container, so
        # no part of the client's filename reaches the filesystem.
        extension = source_extension_for(probe_container_format(probe_tmp))
        saved_source = work_dir / f"{SOURCE_STEM}{extension}"
        shutil.move(str(probe_tmp), str(saved_source))

        # Rendering is blocking and CPU bound: keep it off the event loop.
        result: RenderResult = await asyncio.to_thread(
            render_video,
            source_bytes_path=saved_source,
            work_dir=work_dir,
            request=render_request,
            suggested_name=video.filename or "video.mp4",
        )

        logger.info(
            "Completed an export for user_id=%s: %d captions, %dx%d, %s",
            user.id,
            result.caption_count,
            result.width,
            result.height,
            result.filename,
        )

        # The response streams the file, so the directory is removed only after
        # the bytes have been sent.
        handed_off = True
        return FileResponse(
            path=result.output_path,
            media_type="video/mp4",
            filename=result.filename,
            background=BackgroundTask(discard_render_directory, work_dir),
            headers={"Cache-Control": "no-store"},
        )

    except RenderUnavailable as exc:
        logger.error("Export requested but the renderer is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except RenderTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        release_render_slot()
        # A success handed the directory to the response's background task, so it
        # is cleaned up once streaming finishes. Every other path cleans up now,
        # which is what stops failed renders accumulating on the host's disk.
        if work_dir is not None and not handed_off:
            discard_render_directory(work_dir)
