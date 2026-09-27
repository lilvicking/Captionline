"""Validated render payloads.

Everything the client sends for a render is untrusted input. These models bound
it: unknown fields are rejected, every numeric range is clamped to something a
1080p frame can physically express, and lengths are capped so a payload cannot
be used to exhaust memory before FFmpeg is ever invoked.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Reference frame the editor's pixel values are expressed against. Kept in step
# with CAPTION_STYLE_REFERENCE_HEIGHT in the frontend.
REFERENCE_HEIGHT = 1080

MAX_CAPTIONS = 5000
MAX_WORDS_PER_CAPTION = 200
MAX_TEXT_LENGTH = 2000

_HEX = r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"

FontFamily = str  # validated below against the known ids
TextAlign = str
PositionPreset = str


class RenderWord(BaseModel):
    """One timed word inside a caption."""

    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=0, max_length=200)
    start: float = Field(ge=0, le=86_400)
    end: float = Field(ge=0, le=86_400)
    score: float | None = Field(default=None, ge=0, le=1)

    @field_validator("end")
    @classmethod
    def _end_not_before_start(cls, value: float, info) -> float:
        start = info.data.get("start")
        if start is not None and value < start:
            return start
        return value


class RenderCaption(BaseModel):
    """A caption as the editor currently holds it, after user edits."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=120)
    start: float = Field(ge=0, le=86_400)
    end: float = Field(ge=0, le=86_400)
    text: str = Field(max_length=MAX_TEXT_LENGTH)
    words: list[RenderWord] | None = Field(default=None, max_length=MAX_WORDS_PER_CAPTION)

    @field_validator("end")
    @classmethod
    def _end_not_before_start(cls, value: float, info) -> float:
        start = info.data.get("start")
        if start is not None and value < start:
            return start
        return value

    @field_validator("text")
    @classmethod
    def _strip_control_chars(cls, value: str) -> str:
        # Keep newlines and tabs (they are legitimate caption formatting) but drop
        # C0 control characters that would corrupt the subtitle file.
        return "".join(
            ch for ch in value if ch in "\n\t" or (ord(ch) >= 32 and ord(ch) != 127)
        )


class WordHighlight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    color: str = Field(pattern=_HEX)
    activeColor: str = Field(pattern=_HEX)


class RenderStyle(BaseModel):
    """Mirrors the frontend `CaptionStyle` exactly, in the units it uses."""

    model_config = ConfigDict(extra="forbid")

    # Text
    fontFamily: str = Field(max_length=40)
    fontSize: float = Field(ge=8, le=400)
    fontWeight: int = Field(ge=100, le=900)
    textColor: str = Field(pattern=_HEX)
    textAlign: str = Field(max_length=10)
    uppercase: bool
    letterSpacing: float = Field(ge=-0.2, le=1.0)
    wordSpacing: float = Field(ge=-0.2, le=2.0)
    lineHeight: float = Field(ge=0.7, le=4.0)

    # Appearance
    backgroundColor: str = Field(pattern=_HEX)
    backgroundOpacity: float = Field(ge=0, le=1)
    backgroundPadding: float = Field(ge=0, le=200)
    backgroundRadius: float = Field(ge=0, le=200)
    outlineEnabled: bool
    outlineColor: str = Field(pattern=_HEX)
    outlineWidth: float = Field(ge=0, le=40)
    shadowEnabled: bool

    # Position
    verticalPosition: float = Field(ge=0, le=100)

    # Layout
    maxWidthPercent: float = Field(ge=10, le=100)
    maxCharsPerLine: int | None = Field(default=None, ge=1, le=200)

    # Karaoke colours
    wordHighlight: WordHighlight | None = None

    @field_validator("textAlign")
    @classmethod
    def _known_align(cls, value: str) -> str:
        allowed = {"left", "center", "right"}
        if value not in allowed:
            raise ValueError(f"textAlign must be one of {sorted(allowed)}")
        return value

    @field_validator("fontFamily")
    @classmethod
    def _known_font(cls, value: str) -> str:
        # An unknown font falls back rather than failing the whole render, which
        # keeps a future font added in the app from breaking older exports.
        from .fonts import FALLBACK_FONT_FAMILY

        return value if value else FALLBACK_FONT_FAMILY


class RenderRequest(BaseModel):
    """Top-level payload: the captions plus the style to render them in."""

    model_config = ConfigDict(extra="forbid")

    captions: list[RenderCaption] = Field(max_length=MAX_CAPTIONS)
    style: RenderStyle

    @field_validator("captions")
    @classmethod
    def _sort_and_bound(cls, value: list[RenderCaption]) -> list[RenderCaption]:
        return sorted(value, key=lambda caption: caption.start)
