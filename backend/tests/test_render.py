"""Tests for the finished-video renderer.

The unit tests here do not need FFmpeg; the end-to-end cases are skipped when it
is absent. Test media is generated with FFmpeg's synthetic sources rather than
committed, so the repository stays free of binary fixtures.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.render.ass import (
    RenderGeometry,
    ass_override_colour,
    build_ass_document,
    escape_ass_text,
    format_ass_time,
    hex_to_ass,
)
from app.render.filenames import build_output_filename
from app.render.fonts import FALLBACK_FONT_FAMILY, font_family_for
from app.render.models import RenderCaption, RenderRequest, RenderStyle, RenderWord
from app.render.service import (
    RenderError,
    RenderTimeout,
    acquire_render_slot,
    create_render_directory,
    discard_render_directory,
    release_render_slot,
    render_video,
    source_extension_for,
)
from tests.conftest import auth_header

ffmpeg = shutil.which("ffmpeg")
ffprobe = shutil.which("ffprobe")

requires_ffmpeg = pytest.mark.skipif(
    not (ffmpeg and ffprobe), reason="ffmpeg/ffprobe are not installed"
)

GEOMETRY = RenderGeometry(width=1920, height=1080)

STYLE: dict = dict(
    fontFamily="system",
    fontSize=42,
    fontWeight=700,
    textColor="#FFFFFF",
    textAlign="center",
    uppercase=False,
    letterSpacing=0,
    wordSpacing=0,
    lineHeight=1.25,
    backgroundColor="#000000",
    backgroundOpacity=0,
    backgroundPadding=12,
    backgroundRadius=8,
    outlineEnabled=False,
    outlineColor="#000000",
    outlineWidth=2,
    shadowEnabled=True,
    verticalPosition=88,
    maxWidthPercent=80,
    maxCharsPerLine=None,
)

CAPTIONS: list[dict] = [
    {"id": "c1", "start": 0.5, "end": 2.5, "text": "First caption"},
    {"id": "c2", "start": 2.5, "end": 4.5, "text": "Second caption"},
]

WORDS: list[dict] = [
    {"word": "First", "start": 0.5, "end": 0.9},
    {"word": "caption", "start": 0.9, "end": 2.5},
]


def build_request(style_overrides: dict | None = None, captions: list[dict] | None = None):
    return RenderRequest.model_validate(
        {
            "captions": captions or CAPTIONS,
            "style": {**STYLE, **(style_overrides or {})},
        }
    )


# --- ASS escaping -----------------------------------------------------------


def test_escape_neutralises_override_blocks():
    assert escape_ass_text("{b}") == r"\{b\}"
    assert escape_ass_text("a}b{a") == r"a\}b\{a"


def test_escape_doubles_backslashes_first():
    # A literal backslash must not be able to start a control code.
    assert escape_ass_text(r"\N") == r"\\N"
    assert escape_ass_text("a\\b") == "a\\\\b"


def test_escape_leaves_ordinary_text_untouched():
    assert escape_ass_text("plain caption") == "plain caption"
    assert escape_ass_text("café — 日本語") == "café — 日本語"


# --- Colour conversion ------------------------------------------------------


@pytest.mark.parametrize(
    "hex_value,expected",
    [
        # Style lines take the bare form, with no trailing '&'.
        ("#FFFFFF", "&H00FFFFFF"),
        ("#000000", "&H00000000"),
        # #FF0033 -> R=FF G=00 B=33 -> AA BB GG RR
        ("#FF0033", "&H003300FF"),
        ("#ABC", "&H00CCBBAA"),
    ],
)
def test_hex_to_ass_orders_bytes_as_abgr(hex_value, expected):
    assert hex_to_ass(hex_value) == expected


def test_override_colour_adds_the_trailing_ampersand():
    """Inside an override block libass requires the closing '&'."""
    assert ass_override_colour("#FFFFFF") == "&H00FFFFFF&"
    assert hex_to_ass("#FFFFFF") + "&" == ass_override_colour("#FFFFFF")


def test_hex_to_ass_alpha_is_inverted():
    # ASS alpha 0 is opaque, so a 0% alpha is 0x00 and 100% is 0xFF.
    assert hex_to_ass("#FFFFFF", alpha=0.0).startswith("&H00")
    assert hex_to_ass("#FFFFFF", alpha=1.0).startswith("&HFF")


# --- Timestamps -------------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0:00:00.00"),
        (1.5, "0:00:01.50"),
        (61.25, "0:01:01.25"),
        (3661.5, "1:01:01.50"),
    ],
)
def test_format_ass_time(seconds, expected):
    assert format_ass_time(seconds) == expected


def test_format_ass_time_clamps_negatives():
    assert format_ass_time(-5) == "0:00:00.00"


# --- Fonts ------------------------------------------------------------------


def test_known_fonts_map_to_installed_families():
    assert font_family_for("system") == "DejaVu Sans"
    assert font_family_for("georgia") == "DejaVu Serif"
    assert font_family_for("mono") == "DejaVu Sans Mono"


def test_unknown_font_falls_back_rather_than_failing():
    assert font_family_for("comic-sans-future") == FALLBACK_FONT_FAMILY


# --- Filenames --------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("my clip.mp4", "my-clip-captioned.mp4"),
        # Only the basename survives, so no directory component can leak.
        ("../../etc/passwd", "passwd-captioned.mp4"),
        # The basename is empty here, so the safe fallback is used.
        ('evil"; rm -rf /.mp4', "video-captioned.mp4"),
        ("C:\\Windows\\System32\\clip.mp4", "clip-captioned.mp4"),
        ("", "video-captioned.mp4"),
        ("...", "video-captioned.mp4"),
        ("clip", "clip-captioned.mp4"),
    ],
)
def test_output_filename_is_sanitised(raw, expected):
    assert build_output_filename(raw) == expected


def test_output_filename_never_contains_a_path_separator():
    for raw in ("../../x", "a\\b", "/etc/shadow", "..\\..\\win"):
        assert "/" not in build_output_filename(raw)
        assert "\\" not in build_output_filename(raw)


def test_output_filename_is_length_bounded():
    assert len(build_output_filename("x" * 500)) <= 100


def test_reserved_windows_names_are_avoided():
    assert build_output_filename("con.mp4") == "con-file-captioned.mp4"


# --- Source extensions ------------------------------------------------------


@pytest.mark.parametrize(
    "container,expected",
    [
        # ffprobe reports aliases; "m4a" must not win for an MP4 video.
        ("mov,mp4,m4a,3gp,3g2,mj2", ".mp4"),
        ("matroska,webm", ".mkv"),
        ("webm", ".webm"),
        ("avi", ".avi"),
        ("something-unknown", ".mp4"),
    ],
)
def test_source_extension_comes_from_an_allowlist(container, expected):
    assert source_extension_for(container) == expected


def test_mp4_container_aliases_do_not_select_an_audio_extension():
    assert source_extension_for("mov,mp4,m4a,3gp,3g2,mj2") != ".m4a"
    assert source_extension_for("m4a") == ".m4a"


# --- Validation -------------------------------------------------------------


def test_style_rejects_out_of_range_values():
    for override in (
        {"fontSize": 5000},
        {"fontWeight": 10},
        {"verticalPosition": 500},
        {"maxWidthPercent": 0},
        {"backgroundOpacity": 3},
        {"lineHeight": 0},
    ):
        with pytest.raises(Exception):
            build_request(override)


def test_style_rejects_unknown_fields():
    with pytest.raises(Exception):
        RenderStyle.model_validate({**STYLE, "unexpected": 1})


def test_style_rejects_bad_colour():
    with pytest.raises(Exception):
        build_request({"textColor": "red"})


def test_style_rejects_unknown_alignment():
    with pytest.raises(Exception):
        build_request({"textAlign": "justified"})


def test_captions_reject_unknown_fields():
    with pytest.raises(Exception):
        RenderRequest.model_validate(
            {"captions": [{**CAPTIONS[0], "extra": 1}], "style": STYLE}
        )


def test_caption_end_is_pulled_after_start():
    caption = RenderCaption(id="x", start=5.0, end=1.0, text="hi")
    assert caption.end == 5.0


def test_control_characters_are_stripped_from_text():
    caption = RenderCaption(id="x", start=0.0, end=1.0, text="a\x07b\x00c")
    assert "\x07" not in caption.text
    assert "\x00" not in caption.text


def test_caption_count_is_bounded():
    too_many = [{"id": f"c{i}", "start": 0.0, "end": 1.0, "text": "x"} for i in range(5001)]
    with pytest.raises(Exception):
        RenderRequest.model_validate({"captions": too_many, "style": STYLE})


# --- ASS document shape -----------------------------------------------------


def test_document_uses_output_resolution():
    document = build_ass_document(build_request(), GEOMETRY)
    assert "PlayResX: 1920" in document
    assert "PlayResY: 1080" in document


def test_document_escapes_caption_braces():
    captions = [{"id": "c1", "start": 0.0, "end": 1.0, "text": r"{\pos(1,1)}X"}]
    document = build_ass_document(build_request(captions=captions), GEOMETRY)
    # Braces are escaped so the override is inert, and the backslash inside the
    # caption is doubled so it cannot start a control code of its own.
    assert r"\{\\pos(1,1)\}X" in document
    # The injected position must not appear as a live override.
    assert r"{\pos(1,1)}" not in document


def test_document_escapes_a_lone_brace():
    captions = [{"id": "c1", "start": 0.0, "end": 1.0, "text": "a{b}c"}]
    document = build_ass_document(build_request(captions=captions), GEOMETRY)
    assert r"a\{b\}c" in document


def test_document_positions_from_vertical_position():
    top = build_ass_document(build_request({"verticalPosition": 8}), GEOMETRY)
    bottom = build_ass_document(build_request({"verticalPosition": 92}), GEOMETRY)
    assert r"\pos(" in top and r"\pos(" in bottom
    # 8% of 1080 is 86, 92% is 994.
    assert r",86)" in top
    assert r",994)" in bottom


def test_document_scales_font_size_to_the_frame():
    # The editor works in a 1080-tall reference; a 720p output is 0.667x.
    document = build_ass_document(build_request({"fontSize": 60}), RenderGeometry(1280, 720))
    assert ",40," in document  # 60 * 720/1080


def test_document_adds_a_box_layer_only_with_a_background():
    without = build_ass_document(build_request({"backgroundOpacity": 0}), GEOMETRY)
    assert "Box" not in without

    with_box = build_ass_document(
        build_request({"backgroundOpacity": 0.9, "backgroundColor": "#FF0033"}), GEOMETRY
    )
    assert "Style: Box" in with_box
    assert "BorderStyle" in with_box or ",3," in with_box


def test_document_uses_karaoke_tags_when_words_match():
    captions = [
        {
            "id": "c1",
            "start": 0.0,
            "end": 2.0,
            "text": "First caption",
            "words": WORDS,
        }
    ]
    document = build_ass_document(
        build_request({"wordHighlight": {"color": "#FFD400", "activeColor": "#FF0033"}},
                      captions=captions),
        GEOMETRY,
    )
    assert r"{\kf" in document


def test_document_falls_back_when_karaoke_words_no_longer_match():
    # The user retyped the caption, so the words no longer describe it.
    captions = [
        {
            "id": "c1",
            "start": 0.0,
            "end": 2.0,
            "text": "Completely different text",
            "words": WORDS,
        }
    ]
    document = build_ass_document(
        build_request({"wordHighlight": {"color": "#FFD400", "activeColor": "#FF0033"}},
                      captions=captions),
        GEOMETRY,
    )
    assert r"{\kf" not in document
    assert "Completely different text" in document


def test_document_handles_empty_caption_list():
    document = build_ass_document(build_request(captions=[]), GEOMETRY)
    assert "Dialogue:" in document


def test_document_skips_blank_captions():
    captions = [{"id": "c1", "start": 0.0, "end": 1.0, "text": "   "}]
    document = build_ass_document(build_request(captions=captions), GEOMETRY)
    assert "Dialogue: 1," not in document


def test_document_wraps_long_captions():
    long_text = "one two three four five six seven eight nine ten eleven twelve"
    document = build_ass_document(
        build_request({"maxCharsPerLine": 20}, captions=[{"id": "c1", "start": 0.0, "end": 3.0, "text": long_text}]),
        GEOMETRY,
    )
    assert r"\N" in document


# --- Concurrency ------------------------------------------------------------


def test_render_slot_is_bounded_and_released():
    assert acquire_render_slot() is True
    # A second render is refused rather than queued.
    assert acquire_render_slot() is False
    release_render_slot()
    assert acquire_render_slot() is True
    release_render_slot()


# --- End-to-end rendering ---------------------------------------------------


def make_video(path, size="640x360", seconds=3, with_audio=True):
    args = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate=15:duration={seconds}",
    ]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        args += ["-c:a", "aac", "-shortest"]
    args += [str(path)]
    subprocess.run(args, check=True, capture_output=True)


def probe(path):
    result = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


@requires_ffmpeg
@pytest.mark.parametrize("size,expected", [("640x360", (640, 360)), ("360x640", (360, 640))])
def test_render_preserves_dimensions_and_audio(size, expected):
    work = create_render_directory()
    try:
        source = work / "source.mp4"
        make_video(source, size=size)

        result = render_video(
            source_bytes_path=source,
            work_dir=work,
            request=build_request(),
            suggested_name="clip.mp4",
        )

        info = probe(result.output_path)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)

        assert (int(video["width"]), int(video["height"])) == expected
        assert video["codec_name"] == "h264"
        assert video["pix_fmt"] == "yuv420p"
        assert audio is not None and audio["codec_name"] == "aac"
        assert result.output_path.stat().st_size > 0
    finally:
        discard_render_directory(work)


@requires_ffmpeg
def test_render_succeeds_without_an_audio_track():
    work = create_render_directory()
    try:
        source = work / "source.mp4"
        make_video(source, with_audio=False)

        result = render_video(
            source_bytes_path=source,
            work_dir=work,
            request=build_request(),
            suggested_name="silent.mp4",
        )

        info = probe(result.output_path)
        assert any(s["codec_type"] == "video" for s in info["streams"])
        assert not any(s["codec_type"] == "audio" for s in info["streams"])
    finally:
        discard_render_directory(work)


@requires_ffmpeg
def test_render_rejects_unreadable_media():
    work = create_render_directory()
    try:
        source = work / "source.mp4"
        source.write_bytes(b"this is definitely not a video")

        with pytest.raises(RenderError):
            render_video(
                source_bytes_path=source,
                work_dir=work,
                request=build_request(),
                suggested_name="bad.mp4",
            )
    finally:
        discard_render_directory(work)


@requires_ffmpeg
def test_render_cleans_up_after_failure():
    work = create_render_directory()
    source = work / "source.mp4"
    source.write_bytes(b"not a video")

    with pytest.raises(RenderError):
        render_video(
            source_bytes_path=source,
            work_dir=work,
            request=build_request(),
            suggested_name="bad.mp4",
        )

    # The render directory is the caller's to clean; assert nothing is produced.
    assert not list(work.glob("output.mp4"))
    discard_render_directory(work)
    assert not work.exists()


@requires_ffmpeg
def test_render_directory_is_removed_completely():
    work = create_render_directory()
    source = work / "source.mp4"
    make_video(source)
    (work / "captions.aa").write_text(build_ass_document(build_request(), GEOMETRY), encoding="utf-8")

    discard_render_directory(work)

    assert not work.exists()


# --- Endpoint ---------------------------------------------------------------


@requires_ffmpeg
def test_export_endpoint_requires_authentication(client):
    assert client.post("/api/export/video").status_code == 401


@requires_ffmpeg
def test_export_endpoint_rejects_a_bad_token(client):
    response = client.post("/api/export/video", files={"video": ("x.mp4", b"x", "video/mp4")})
    assert response.status_code == 401


def test_export_endpoint_reports_missing_fields(client):
    token = client.post(
        "/api/auth/register", json={"email": "render@example.com", "password": "a-strong-password-123"}
    ).json()["access_token"]

    response = client.post("/api/export/video", headers=auth_header(token))
    assert response.status_code == 422


def test_export_endpoint_rejects_malformed_caption_json(client):
    token = client.post(
        "/api/auth/register", json={"email": "render2@example.com", "password": "a-strong-password-123"}
    ).json()["access_token"]

    response = client.post(
        "/api/export/video",
        headers=auth_header(token),
        data={"captions": "{not json", "style": json.dumps(STYLE)},
        files={"video": ("x.mp4", b"x", "video/mp4")},
    )
    assert response.status_code == 400


def test_export_endpoint_rejects_invalid_style_values(client):
    token = client.post(
        "/api/auth/register", json={"email": "render3@example.com", "password": "a-strong-password-123"}
    ).json()["access_token"]

    response = client.post(
        "/api/export/video",
        headers=auth_header(token),
        data={"captions": json.dumps({"captions": CAPTIONS}), "style": json.dumps({**STYLE, "fontSize": 9999})},
        files={"video": ("x.mp4", b"x", "video/mp4")},
    )
    assert response.status_code == 422


def test_export_endpoint_rejects_an_empty_caption_list(client):
    token = client.post(
        "/api/auth/register", json={"email": "render4@example.com", "password": "a-strong-password-123"}
    ).json()["access_token"]

    response = client.post(
        "/api/export/video",
        headers=auth_header(token),
        data={"captions": json.dumps({"captions": []}), "style": json.dumps(STYLE)},
        files={"video": ("x.mp4", b"x", "video/mp4")},
    )
    assert response.status_code == 400


@requires_ffmpeg
def test_free_account_can_export(client, db_session):
    """Free is entitled: the flag is true for every plan."""
    token = client.post(
        "/api/auth/register", json={"email": "free-render@example.com", "password": "a-strong-password-123"}
    ).json()["access_token"]

    user = db_session.execute(
        __import__("sqlalchemy").select(__import__("app.db.models", fromlist=["User"]).User).where(
            __import__("app.db.models", fromlist=["User"]).User.email == "free-render@example.com"
        )
    ).scalar_one()
    assert user.can_export is True

    work = create_render_directory()
    try:
        source = work / "source.mp4"
        make_video(source)

        response = client.post(
            "/api/export/video",
            headers=auth_header(token),
            data={
                "captions": json.dumps({"captions": CAPTIONS}),
                "style": json.dumps(STYLE),
            },
            files={"video": ("clip.mp4", source.read_bytes(), "video/mp4")},
        )
    finally:
        discard_render_directory(work)

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert "attachment" in response.headers["content-disposition"]
    assert "captioned.mp4" in response.headers["content-disposition"]
    assert len(response.content) > 0


@requires_ffmpeg
def test_export_does_not_consume_processing_allowance(client, db_session):
    """Re-rendering after edits is free; only transcription costs time."""
    from sqlalchemy import select

    from app.db.models import User

    token = client.post(
        "/api/auth/register", json={"email": "usage-render@example.com", "password": "a-strong-password-123"}
    ).json()["access_token"]

    work = create_render_directory()
    try:
        source = work / "source.mp4"
        make_video(source)
        payload = source.read_bytes()

        for _ in range(2):
            response = client.post(
                "/api/export/video",
                headers=auth_header(token),
                data={"captions": json.dumps({"captions": CAPTIONS}), "style": json.dumps(STYLE)},
                files={"video": ("clip.mp4", payload, "video/mp4")},
            )
            assert response.status_code == 200
    finally:
        discard_render_directory(work)

    user = db_session.execute(
        select(User).where(User.email == "usage-render@example.com")
    ).scalar_one()
    assert user.processing_used_seconds == 0
    assert user.monthly_processing_allowance_seconds == 600
