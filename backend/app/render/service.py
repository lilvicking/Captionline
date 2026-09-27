"""Finished-video rendering.

## Command safety

FFmpeg is never invoked through a shell. Every argument is passed as a list
element, so shell metacharacters in a filename are inert. The user never
contributes an argument, a filter string, or a protocol: the only path FFmpeg sees
is a bare filename, because the subprocess runs with `cwd` set to a private
temporary directory that this module created. There is nothing to escape.

The FFmpeg command deliberately contains no `scale` or `-s`, so the source
dimensions and aspect ratio are preserved, and autorotation stays enabled so
rotation metadata is honoured rather than applied twice.

## Temporary files

Each render gets a `mkdtemp` directory. The uploaded source, the generated ASS
file, and the output MP4 all live there and are removed when the render finishes,
fails, or times out. The directory survives only for as long as the HTTP response
is streaming the finished file, and the route removes it from a background task
once the response has been sent.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from ..media import MediaProbeError, probe_media
from .ass import RenderGeometry, build_ass_document
from .ffmpeg import ffmpeg_available, ffprobe_available
from .models import RenderRequest

logger = logging.getLogger(__name__)

#: ffprobe container aliases mapped to an extension this service will write.
#: Ordered by preference, because one container reports several aliases (an MP4
#: file reports "mov,mp4,m4a,3gp,3g2,mj2", and .mp4 is the right choice).
#: The client's filename is never consulted.
_ALLOWED_SOURCE_EXTENSIONS: tuple[tuple[str, str], ...] = (
    ("matroska", ".mkv"),
    ("webm", ".webm"),
    ("avi", ".avi"),
    ("mpegts", ".ts"),
    ("flv", ".flv"),
    ("mp4", ".mp4"),
    ("mov", ".mp4"),
    ("quicktime", ".mov"),
    ("3gp", ".mp4"),
    ("wav", ".wav"),
    ("mp3", ".mp3"),
    ("aac", ".aac"),
    ("flac", ".flac"),
    ("ogg", ".ogg"),
    ("m4a", ".m4a"),
)
_DEFAULT_SOURCE_EXTENSION = ".mp4"

#: Fixed names inside the per-render directory. Because the subprocess runs with
#: this directory as its working directory, FFmpeg only ever sees these.
SOURCE_NAME = "source"
ASS_NAME = "captions.aa"
OUTPUT_NAME = "output.mp4"

#: ffmpeg is very chatty on stderr; only real errors are kept.
_LOG_LEVEL = "error"

_render_slots = threading.BoundedSemaphore(1)
_slots_lock = threading.Lock()


class RenderError(Exception):
    """A render failed for a reason worth showing the customer."""


class RenderUnavailable(RenderError):
    """FFmpeg or ffprobe is not installed, so export cannot run."""


class RenderTimeout(RenderError):
    """The render exceeded its time budget and was killed."""


@dataclass(frozen=True)
class RenderResult:
    """A finished render, plus everything the route needs to serve and clean up."""

    output_path: Path
    work_dir: Path
    filename: str
    width: int
    height: int
    duration_seconds: float
    caption_count: int
    karaoke_used: bool


def acquire_render_slot() -> bool:
    """Take one of the bounded render slots without blocking.

    Non-blocking so a request is rejected immediately rather than queueing, which
    would otherwise let a backlog build until Railway times every request out.
    """
    return _render_slots.acquire(blocking=False)


def release_render_slot() -> None:
    with _slots_lock:
        try:
            _render_slots.release()
        except ValueError:
            # Releasing more than was taken would corrupt the semaphore.
            logger.error("Render slot released without being held")


def source_extension_for(format_name: str) -> str:
    """Map a probed container name to an extension we are willing to write.

    ffprobe reports comma-separated aliases, so the names are compared as
    whole tokens. Substring matching would misfire: "mov,mp4,m4a,3gp" contains
    "m4a", and an audio extension would be chosen for a video.
    """
    names = {part.strip().lower() for part in format_name.split(",") if part.strip()}

    for container, extension in _ALLOWED_SOURCE_EXTENSIONS:
        if container in names:
            return extension

    return _DEFAULT_SOURCE_EXTENSION


def sanitize_download_name(original: str) -> str:
    """Build `name-captioned.mp4` from a client-supplied name.

    Only a conservative allowlist survives, so the header can carry no path
    separator, control character, quote, or shell metacharacter.
    """
    from .filenames import build_output_filename

    return build_output_filename(original)


def render_video(
    *,
    source_bytes_path: Path,
    work_dir: Path,
    request: RenderRequest,
    suggested_name: str,
) -> RenderResult:
    """Burn the supplied captions into the source video.

    `source_bytes_path` is the already-saved upload inside `work_dir`. The
    duration and dimensions are measured from the file itself, never from the
    request.
    """
    if not (ffmpeg_available() and ffprobe_available()):
        raise RenderUnavailable(
            "Finished-video export is not available on this server right now."
        )

    settings = get_settings()

    try:
        info = probe_media(str(source_bytes_path))
    except MediaProbeError as exc:
        raise RenderError("That file could not be read as a video.") from exc

    if settings.export_max_duration_seconds > 0 and (
        info.duration_seconds > settings.export_max_duration_seconds
    ):
        raise RenderError(
            "That video is longer than this service can render in one export."
        )

    geometry = RenderGeometry(
        width=max(1, round(info.width)), height=max(1, round(info.height))
    )

    ass_path = work_dir / ASS_NAME
    ass_document = build_ass_document(request, geometry)
    ass_path.write_text(ass_document, encoding="utf-8")

    output_path = work_dir / OUTPUT_NAME
    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg is None:  # pragma: no cover - guarded by ffmpeg_available()
        raise RenderUnavailable("Finished-video export is not available on this server right now.")

    # Both names come from this module: the upload's basename was chosen here
    # from an allowlist based on the probed container, never from the client.
    # `cwd` is the private render directory, so only a bare name is needed and
    # there is no path to escape. The filter argument is a fixed constant, which
    # is what keeps FFmpeg filter injection off the table entirely.
    source_name = source_bytes_path.name

    command = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        _LOG_LEVEL,
        "-i",
        source_name,
        "-vf",
        f"ass={ASS_NAME}",
        "-map",
        "0:v:0",
        # Optional: a file with no audio track still exports.
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        # Moves the index to the front so the browser can start playing at once.
        "-movflags",
        "+faststart",
        OUTPUT_NAME,
    ]

    logger.info(
        "Rendering %s captions over a %dx%d source (%.1fs)",
        len(request.captions),
        geometry.width,
        geometry.height,
        info.duration_seconds,
    )

    try:
        completed = subprocess.run(
            command,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=settings.export_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderTimeout(
            "Rendering took too long and was stopped. Try a shorter video."
        ) from exc

    if completed.returncode != 0 or not output_path.exists():
        # Keep a short, non-identifying tail for diagnosis; never the full command
        # or an absolute path.
        detail = (completed.stderr or "").strip().splitlines()[-3:]
        logger.warning("FFmpeg render failed: %s", " | ".join(detail))
        raise RenderError("The video could not be rendered. Please try a different file.")

    if output_path.stat().st_size == 0:
        raise RenderError("The render produced an empty file.")

    return RenderResult(
        output_path=output_path,
        work_dir=work_dir,
        filename=sanitize_download_name(suggested_name),
        width=geometry.width,
        height=geometry.height,
        duration_seconds=info.duration_seconds,
        caption_count=len(request.captions),
        karaoke_used=request.style.wordHighlight is not None,
    )


def create_render_directory() -> Path:
    """A private directory for one render, named by this process only."""
    return Path(tempfile.mkdtemp(prefix=f"captionline-render-{uuid.uuid4().hex[:8]}-"))


def discard_render_directory(work_dir: Path) -> None:
    """Remove a render directory and everything in it."""
    shutil.rmtree(work_dir, ignore_errors=True)


def probe_container_format(path: Path) -> str:
    """Best-effort container name, used only to pick a safe file extension."""
    try:
        result = subprocess.run(
            [
                shutil.which("ffprobe") or "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        payload = json.loads(result.stdout or "{}")
        return str((payload.get("format") or {}).get("format_name") or "")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return ""


__all__ = [
    "RenderError",
    "RenderResult",
    "RenderTimeout",
    "RenderUnavailable",
    "acquire_render_slot",
    "create_render_directory",
    "discard_render_directory",
    "release_render_slot",
    "render_video",
    "sanitize_download_name",
    "source_extension_for",
]
