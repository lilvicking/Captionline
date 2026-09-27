r"""ASS subtitle generation.

ASS (Advanced SubStation Alpha) is used rather than SRT because it is the only
format libass can style to match the Caption Designer: per-event colours, letter
spacing, outline, shadow, an opaque background box, precise positioning, and
karaoke.

## Why two styles

libass renders *either* an opaque box (`BorderStyle: 3`) *or* a text outline and
shadow (`BorderStyle: 1`) — never both, because `BorderStyle` is a property of a
style definition and has no per-event override. So when the designer has both a
background and an outline, two dialogue events are emitted: a `Box` event with
transparent text drawn first, and a `Text` event on top. When only an outline is
set, a single `Text` event is emitted.

## Injection safety

ASS dialogue text is a small language: `{...}` opens an override block and `\`
starts a control code. Caption text containing either could otherwise restyle
itself, reposition itself, or corrupt the file, so both are escaped. This was
verified empirically: an unescaped `{b}` is consumed as a tag, while `\\{b\\}`
renders as literal ink.

No user text ever reaches a header line, and the only value passed to the FFmpeg
filter is a filename this process chooses itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fonts import font_family_for, glyph_ratio_for
from .models import REFERENCE_HEIGHT, RenderCaption, RenderRequest, RenderStyle

#: Kept clear of the frame edge, as a fraction of video height.
SAFE_MARGIN_RATIO = 0.04

#: Word gaps below this are left alone; the visual difference is negligible and
#: it keeps wrapped lines identical to the preview for the common case.
_WORD_GAP_THRESHOLD = 0.25

#: Above this ratio, extra vertical room is requested between lines.
_LINE_SPACING_THRESHOLD = 1.35


def hex_to_ass(hex_colour: str, alpha: float = 0.0) -> str:
    """Convert ``#RRGGBB`` plus alpha (0 = opaque) to ASS ``&HAABBGGRR``.

    ASS orders the bytes as alpha, blue, green, red. This is the form a style
    line wants, with no trailing ``&``; use :func:`ass_override_colour` inside an
    override block, which does need it.
    """
    value = hex_colour.lstrip("#")

    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)

    alpha_byte = max(0, min(255, round(alpha * 255)))
    return f"&H{alpha_byte:02X}{value[4:6]}{value[2:4]}{value[0:2]}"


def ass_override_colour(hex_colour: str, alpha: float = 0.0) -> str:
    """Same colour in the form an override tag requires, with a trailing ``&``."""
    return f"{hex_to_ass(hex_colour, alpha)}&"


def escape_ass_text(text: str) -> str:
    """Escape caption text so it renders literally instead of being parsed."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def format_ass_time(seconds: float) -> str:
    """Seconds to ``H:MM:SS.cc``, the format ASS dialogue times use."""
    safe = max(0.0, float(seconds))
    whole = int(safe)
    centis = min(99, round((safe - whole) * 100))
    return f"{whole // 3600}:{(whole % 3600) // 60:02d}:{whole % 60:02d}.{centis:02d}"


@dataclass(frozen=True)
class RenderGeometry:
    """The output frame the captions are laid out against."""

    width: int
    height: int


def _style_line(
    name: str,
    font_family: str,
    font_size_px: int,
    primary: str,
    secondary: str,
    outline_colour: str,
    back_colour: str,
    bold: int,
    spacing_px: int,
    border_style: int,
    outline_px: int,
    shadow_px: int,
    margin_h: int,
    margin_v: int,
) -> str:
    fields = [
        name,
        font_family,
        str(font_size_px),
        primary,
        secondary,
        outline_colour,
        back_colour,
        str(bold),
        "0",  # italic
        "0",  # underline
        "0",  # strikeout
        "100",  # scaleX
        "100",  # scaleY
        str(spacing_px),
        "0",  # angle
        str(border_style),
        str(outline_px),
        str(shadow_px),
        "5",  # middle-centre; overridden per event with \pos
        str(margin_h),
        str(margin_h),
        str(margin_v),
        "1",  # encoding
    ]
    return "Style: " + ",".join(fields)


def _event(layer: int, start: str, end: str, style: str, text: str) -> str:
    return f"Dialogue: {layer},{start},{end},{style},,0,0,0,,{text}"


def _wrap_text(
    caption: RenderCaption, style: RenderStyle, geometry: RenderGeometry, font_family: str
) -> list[str]:
    """Break a caption into display lines.

    Two constraints come from the editor: an optional character budget, and the
    caption block's maximum width. The width budget is estimated from the font
    size and the family because exact glyph advances are not known here;
    estimating slightly wide wraps a line early rather than letting it reach the
    frame edge.
    """
    text = caption.text.replace("\n", " ").replace("\t", " ").strip()

    if not text:
        return []

    scale = geometry.height / REFERENCE_HEIGHT
    font_size_px = max(style.fontSize * scale, 1.0)
    ratio = glyph_ratio_for(font_family)

    margin = geometry.height * SAFE_MARGIN_RATIO
    usable_width = max(
        geometry.width * (style.maxWidthPercent / 100.0) - (2 * margin),
        font_size_px,
    )

    budget = max(int(usable_width / (font_size_px * ratio)), 1)

    if style.maxCharsPerLine:
        budget = min(budget, style.maxCharsPerLine)

    lines: list[str] = []
    current: list[str] = []
    current_length = 0

    for word in text.split(" "):
        addition = len(word) if not current else current_length + 1 + len(word)

        if current and addition > budget:
            lines.append(" ".join(current))
            current = [word]
            current_length = len(word)
        else:
            current.append(word)
            current_length = addition

    if current:
        lines.append(" ".join(current))

    return lines


def _karaoke_text(caption: RenderCaption, line: str) -> str | None:
    """Build ``\\kf`` karaoke tags for a line, or None when they cannot apply.

    Karaoke is only honest when the timed words still describe the text being
    shown. If the user retyped the caption, the words no longer line up and
    forcing tags would light up the wrong words, so the caller falls back to a
    plain caption. That is the documented graceful degradation.
    """
    if not caption.words:
        return None

    joined = " ".join(word.word for word in caption.words).strip()

    if not joined:
        return None

    def squeeze(value: str) -> str:
        return "".join(value.split()).casefold()

    if squeeze(joined) != squeeze(line):
        return None

    tags: list[str] = []

    for word in caption.words:
        # \kf counts centiseconds, so the highlight tracks real word timing.
        centiseconds = max(1, round(max(0.0, word.end - word.start) * 100))
        tags.append("{\\kf%d}" % centiseconds)

    return "".join(tags) + line


def _render_line_text(
    lines: list[str], word_gap: str, escape: bool = True
) -> str:
    """Join wrapped lines into one ASS text run.

    ASS has no word-spacing property, so any extra gap is baked in at word
    boundaries. That is exactly what CSS ``word-spacing`` does at render time;
    the stored caption text is never modified.
    """
    rendered: list[str] = []

    for line in lines:
        escaped = escape_ass_text(line) if escape else line

        if word_gap:
            rendered.append((" " + word_gap).join(escaped.split(" ")))
        else:
            rendered.append(escaped)

    return r"\N".join(rendered)


def build_ass_document(request: RenderRequest, geometry: RenderGeometry) -> str:
    """Render a validated request into a complete ASS document."""
    style = request.style
    font_family = font_family_for(style.fontFamily)

    # The editor expresses pixels against a 1080-tall reference frame; scale to
    # the real output so a 720p and a 4K export look the same.
    scale = geometry.height / REFERENCE_HEIGHT

    font_size_px = max(1, round(style.fontSize * scale))
    outline_px = round(style.outlineWidth * scale) if style.outlineEnabled else 0
    shadow_px = round(max(2.0, font_size_px * 0.06)) if style.shadowEnabled else 0
    padding_px = round(style.backgroundPadding * scale)

    letter_spacing_px = round(style.letterSpacing * font_size_px)
    bold = -1 if style.fontWeight >= 600 else 0

    margin_h = round(geometry.width * SAFE_MARGIN_RATIO)
    margin_v = round(geometry.height * SAFE_MARGIN_RATIO)

    karaoke_wanted = style.wordHighlight is not None

    if karaoke_wanted and style.wordHighlight is not None:
        # Karaoke repaints the not-yet-sung words from SecondaryColour into
        # PrimaryColour, so the two hold the inactive and active colours.
        sung_hex = style.wordHighlight.activeColor
        unsung_hex = style.wordHighlight.color
    else:
        sung_hex = style.textColor
        unsung_hex = style.textColor

    # Style lines carry the bare form; override tags need the trailing '&'.
    sung_style = hex_to_ass(sung_hex)
    unsung_style = hex_to_ass(unsung_hex)
    sung_tag = ass_override_colour(sung_hex)
    unsung_tag = ass_override_colour(unsung_hex)
    TRANSPARENT_STYLE = hex_to_ass("#FFFFFF", alpha=1.0)
    TRANSPARENT_TAG = ass_override_colour("#FFFFFF", alpha=1.0)

    background_alpha = 1.0 - style.backgroundOpacity
    has_background = style.backgroundOpacity > 0.01

    styles = [
        _style_line(
            name="Text",
            font_family=font_family,
            font_size_px=font_size_px,
            primary=sung_style,
            secondary=unsung_style,
            outline_colour=hex_to_ass(style.outlineColor) if style.outlineEnabled else TRANSPARENT_STYLE,
            back_colour=TRANSPARENT_STYLE,
            bold=bold,
            spacing_px=letter_spacing_px,
            border_style=1,
            outline_px=outline_px,
            shadow_px=shadow_px,
            margin_h=margin_h,
            margin_v=margin_v,
        )
    ]

    if has_background:
        styles.append(
            _style_line(
                name="Box",
                font_family=font_family,
                font_size_px=font_size_px,
                # Transparent text: only the box should be visible.
                primary=TRANSPARENT_STYLE,
                secondary=TRANSPARENT_STYLE,
                outline_colour=TRANSPARENT_STYLE,
                back_colour=hex_to_ass(style.backgroundColor, background_alpha),
                bold=bold,
                spacing_px=letter_spacing_px,
                border_style=3,
                # In BorderStyle 3 the outline field is the box padding.
                outline_px=padding_px,
                shadow_px=0,
                margin_h=margin_h,
                margin_v=margin_v,
            )
        )

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {geometry.width}",
        f"PlayResY: {geometry.height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: None",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # The caption block is centred within its own maximum width, so the anchor
    # shifts with the alignment the designer selected.
    block_width = geometry.width * (style.maxWidthPercent / 100.0)

    if style.textAlign == "left":
        centre_x = margin_h + block_width / 2
    elif style.textAlign == "right":
        centre_x = geometry.width - margin_h - block_width / 2
    else:
        centre_x = geometry.width / 2

    centre_y = geometry.height * (style.verticalPosition / 100.0)
    position = f"{position_tag(centre_x, centre_y)}"

    word_gap = (
        " " * max(1, round(style.wordSpacing / 0.5))
        if style.wordSpacing >= _WORD_GAP_THRESHOLD
        else ""
    )

    # ASS cannot set line height directly. For noticeably tall line heights the
    # gap between wrapped lines is widened instead, which is the closest a
    # renderer can get without a different engine.
    line_gap = ""
    if style.lineHeight >= _LINE_SPACING_THRESHOLD:
        line_gap = r"\h" * max(1, round((style.lineHeight - 1) * 2))

    events: list[str] = []

    for caption in request.captions:
        lines = _wrap_text(caption, style, geometry, font_family)

        if not lines:
            continue

        start = format_ass_time(caption.start)
        # A zero-length caption still needs to be on screen for a frame.
        end = format_ass_time(max(caption.end, caption.start + 0.1))

        if has_background:
            box_text = position + f"{{\\1c{TRANSPARENT_TAG}}}{{\\3c{TRANSPARENT_TAG}}}"
            events.append(
                _event(0, start, end, "Box", box_text + _render_line_text(lines, word_gap))
            )

        overrides = [
            position,
            f"{{\\1c{sung_tag}}}",
            f"{{\\3c{unsung_tag}}}",
        ]

        if letter_spacing_px:
            overrides.append(f"{{\\fsp{letter_spacing_px}}}")
        if bold:
            overrides.append("{\\b1}")

        karaoke_applied = False
        rendered: list[str] = []

        for line in lines:
            tagged = _karaoke_text(caption, line) if karaoke_wanted else None

            if tagged is not None:
                rendered.append(tagged)
                karaoke_applied = True
            else:
                # Plain text still needs escaping, but must not be preceded by
                # karaoke tags.
                rendered.append(escape_ass_text(line))

        if karaoke_wanted and not karaoke_applied:
            # Word timings no longer match the edited caption: render the whole
            # caption in the active colour rather than highlight the wrong words.
            overrides.append(f"{{\\1c{sung_tag}}}")

        body = "".join(overrides) + _join(rendered, line_gap)
        events.append(_event(1, start, end, "Text", body))

    if not events:
        # An empty caption list would produce a script with no events. Emit a
        # zero-length blank so libass still has valid input.
        events.append(_event(0, "0:00:00.00", "0:00:00.00", "Text", position + " "))

    return "\n".join(header + events) + "\n"


def position_tag(centre_x: float, centre_y: float) -> str:
    """Anchor the caption block by its centre at an exact frame position."""
    return f"{{\\an5\\pos({round(centre_x)},{round(centre_y)})}}"


def _join(lines: list[str], line_gap: str) -> str:
    """Join already-prepared lines with the ASS line break."""
    if not line_gap:
        return r"\N".join(lines)
    return (r"\N" + line_gap).join(lines)
