"""Server-side media inspection.

The client is never trusted to declare how long a file is. Duration is measured
here, before any processing, using `ffprobe`, which ships with ffmpeg and is
already required to decode uploads. That avoids pulling in a large media
framework purely to read a duration.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass

from .config import get_settings

logger = logging.getLogger(__name__)

#: ffprobe is given a bounded budget; a pathological file must not hang the
#: request thread.
PROBE_TIMEOUT_SECONDS = 60


class MediaProbeError(Exception):
    """Raised when the media could not be inspected."""


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    has_audio: bool
    has_video: bool


def probe_media(path: str) -> MediaInfo:
    """Measure duration and stream layout of an uploaded file.

    Raises `MediaProbeError` when ffprobe is unavailable, times out, or reports
    something unusable. Callers must treat that as a rejection rather than
    transcribing for free, because an unmeasurable file cannot be billed.
    """
    settings = get_settings()

    command = [
        settings.ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        # Log the cause, never the media path beyond the temp file name.
        logger.error("ffprobe executable not found at %r", settings.ffprobe_path)
        raise MediaProbeError("Media inspection is unavailable on this server.") from exc
    except subprocess.TimeoutExpired as exc:
        logger.warning("ffprobe timed out after %ss", PROBE_TIMEOUT_SECONDS)
        raise MediaProbeError("The media file took too long to inspect.") from exc

    if completed.returncode != 0:
        logger.warning("ffprobe exited with code %s", completed.returncode)
        raise MediaProbeError("The uploaded file could not be read as media.")

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaProbeError("The media inspection result could not be parsed.") from exc

    duration = _extract_duration(payload)
    if duration is None or duration <= 0:
        raise MediaProbeError("The duration of the uploaded file could not be determined.")

    streams = payload.get("streams") or []
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    has_video = any(stream.get("codec_type") == "video" for stream in streams)

    return MediaInfo(
        duration_seconds=duration,
        has_audio=has_audio,
        has_video=has_video,
    )


def _extract_duration(payload: dict) -> float | None:
    """Prefer the container duration, falling back to the longest stream."""
    candidates: list[float] = []

    container = payload.get("format") or {}
    raw_container = container.get("duration")
    if raw_container is not None:
        try:
            candidates.append(float(raw_container))
        except (TypeError, ValueError):
            pass

    for stream in payload.get("streams") or []:
        raw_stream = stream.get("duration")
        if raw_stream is not None:
            try:
                candidates.append(float(raw_stream))
            except (TypeError, ValueError):
                continue

    usable = [value for value in candidates if value > 0 and value != float("inf")]
    return max(usable) if usable else None


def billable_seconds(duration_seconds: float) -> int:
    """Round a duration up to whole billable seconds.

    Rounding up means a customer is never billed less than the media actually
    consumed, while sub-second rounding error stays bounded at one second.
    """
    import math

    return max(int(math.ceil(duration_seconds)), 0)
