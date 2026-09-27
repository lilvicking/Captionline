"""Server-side finished-video rendering.

Turns the editor's current caption state into an MP4 with the captions burned in,
using FFmpeg's libass filter. Nothing here is reachable without a valid session.
"""

from .ass import build_ass_document, escape_ass_text, format_ass_time, hex_to_ass
from .ffmpeg import ffmpeg_available, ffprobe_available, renderer_available
from .filenames import build_output_filename
from .fonts import font_family_for
from .models import RenderCaption, RenderRequest, RenderStyle, RenderWord
from .service import (
    RenderError,
    RenderResult,
    RenderTimeout,
    RenderUnavailable,
    acquire_render_slot,
    create_render_directory,
    discard_render_directory,
    release_render_slot,
    render_video,
    source_extension_for,
)

__all__ = [
    "RenderCaption",
    "RenderError",
    "RenderRequest",
    "RenderResult",
    "RenderStyle",
    "RenderTimeout",
    "RenderUnavailable",
    "RenderWord",
    "acquire_render_slot",
    "build_ass_document",
    "build_output_filename",
    "create_render_directory",
    "discard_render_directory",
    "escape_ass_text",
    "ffmpeg_available",
    "ffprobe_available",
    "font_family_for",
    "format_ass_time",
    "hex_to_ass",
    "release_render_slot",
    "render_video",
    "renderer_available",
    "source_extension_for",
]
