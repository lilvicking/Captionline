"""FFmpeg and ffprobe discovery.

Availability is probed once and cached, and reported through `/api/health` as
booleans. No filesystem path is ever returned to a client.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

_availability: dict[str, bool] | None = None


def _probe(executable: str) -> bool:
    """Whether a binary runs and reports a version.

    Both ffmpeg and ffprobe exit non-zero for a bad flag, so `-version` on a
    real binary exits 0. Timeouts keep a broken PATH from hanging startup.
    """
    path = shutil.which(executable)

    if not path:
        return False

    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0


def ffmpeg_available() -> bool:
    """Whether FFmpeg is installed and runnable."""
    global _availability

    if _availability is None:
        _availability = {
            "ffmpeg": _probe("ffmpeg"),
            "ffprobe": _probe("ffprobe"),
        }
        if not all(_availability.values()):
            logger.warning(
                "Renderer support is incomplete: ffmpeg=%s ffprobe=%s. "
                "Finished-video export will report itself unavailable.",
                _availability["ffmpeg"],
                _availability["ffprobe"],
            )

    return _availability["ffmpeg"]


def ffprobe_available() -> bool:
    """Whether ffprobe is installed and runnable."""
    ffmpeg_available()
    assert _availability is not None
    return _availability["ffprobe"]


def renderer_available() -> bool:
    """Both binaries are required: ffmpeg burns in, ffprobe measures."""
    return ffmpeg_available() and ffprobe_available()


def reset_availability_cache() -> None:
    """Forget cached probe results. Used by tests."""
    global _availability
    _availability = None
