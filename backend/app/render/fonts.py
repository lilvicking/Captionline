"""Server-side font mapping.

The editor offers browser font families that mostly do not exist on a Linux
server. Rendering maps each choice onto an open-licensed font shipped in the
image, and always has a fallback, so an unavailable font can never fail an
export. All of these are DejaVu faces, which cover Latin, Cyrillic, Greek and
much of the CJK-adjacent punctuation used by transcription output.
"""

from __future__ import annotations

#: Frontend `CaptionFontId` -> fontconfig family name available in the image.
FONT_FAMILY_BY_ID: dict[str, str] = {
    "system": "DejaVu Sans",
    "helvetica": "DejaVu Sans",
    "trebuchet": "DejaVu Sans",
    "georgia": "DejaVu Serif",
    # Impact is a display face with no open equivalent; DejaVu Sans Bold is the
    # closest honest substitute.
    "impact": "DejaVu Sans",
    "mono": "DejaVu Sans Mono",
}

#: Used when the requested id is unknown, and as the ASS script default.
FALLBACK_FONT_FAMILY = "DejaVu Sans"

#: Approximate glyph width as a fraction of font size, used to estimate wrapping
#: before handing the line to libass. Slightly conservative so captions wrap a
#: little early rather than touching the frame edge.
AVERAGE_GLYPH_RATIO: dict[str, float] = {
    "DejaVu Sans": 0.52,
    "DejaVu Serif": 0.50,
    "DejaVu Sans Mono": 0.60,
}
FALLBACK_GLYPH_RATIO = 0.55


def font_family_for(font_id: str) -> str:
    """Map a frontend font id to an installed font family."""
    return FONT_FAMILY_BY_ID.get(font_id, FALLBACK_FONT_FAMILY)


def glyph_ratio_for(font_family: str) -> float:
    """Average glyph width ratio for a family, used for wrapping estimates."""
    return AVERAGE_GLYPH_RATIO.get(font_family, FALLBACK_GLYPH_RATIO)
