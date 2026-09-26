"""Transcription gating, allowance enforcement, and charging behaviour.

WhisperX is mocked so the accounting and gating logic can be tested without
running an expensive transcription job. `ffprobe` is used for real against a
tiny generated WAV, so duration measurement is genuinely exercised.
"""

from __future__ import annotations

import math
import struct
import wave

import pytest
from sqlalchemy import select

from app.db.models import UsageReservation, User
from app.media import billable_seconds
from app.plans import FREE_PLAN_ID, PRO_MONTHLY_PLAN_ID
from tests.conftest import auth_header


@pytest.fixture()
def media_file(tmp_path):
    """A small but real 2-second WAV with an audio track."""
    path = tmp_path / "sample.wav"
    rate = 16000
    frames = bytearray()
    for index in range(rate * 2):
        t = index / rate
        value = int(8000 * math.sin(2 * math.pi * 220 * t))
        frames += struct.pack("<h", value)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))

    return path


def register(client, email="transcribe@example.com"):
    return client.post(
        "/api/auth/register", json={"email": email, "password": "a-strong-password-123"}
    )


# --- Authentication gate ---


def test_unauthenticated_transcription_is_rejected(client, media_file):
    """Phase 3B: transcription must require an account."""
    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe", files={"file": ("sample.wav", handle, "audio/wav")}
        )

    assert response.status_code == 401


def test_transcription_with_invalid_token_is_rejected(client, media_file):
    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header("not-a-real-token"),
        )

    assert response.status_code == 401


def test_transcription_with_revoked_token_is_rejected(client, media_file):
    token = register(client).json()["access_token"]
    client.post("/api/auth/logout", headers=auth_header(token))

    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 401


def test_non_media_upload_is_rejected_before_any_processing(client):
    token = register(client).json()["access_token"]

    response = client.post(
        "/api/transcribe",
        files={"file": ("notes.txt", b"not media", "text/plain")},
        headers=auth_header(token),
    )

    assert response.status_code == 400


# --- Successful transcription charges the real duration ---


def test_successful_transcription_charges_media_duration(
    client, db_session, media_file, monkeypatch
):
    token = register(client).json()["access_token"]
    monkeypatch.setattr("app.main.transcribe_file", _fake_transcriber(1))

    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 200

    user = db_session.execute(
        select(User).where(User.email == "transcribe@example.com")
    ).scalar_one()

    # A 2-second file bills 2 seconds, not 0 and not the whole allowance.
    assert user.processing_used_seconds == 2


def test_charge_is_reflected_in_entitlement(client, db_session, media_file, monkeypatch):
    token = register(client).json()["access_token"]
    monkeypatch.setattr("app.main.transcribe_file", _fake_transcriber(1))

    with media_file.open("rb") as handle:
        client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()

    assert entitlement["processing_used_seconds"] == 2
    assert entitlement["processing_remaining_seconds"] == 598
    assert entitlement["processing_reserved_seconds"] == 0


# --- Failures must not charge ---


def test_failed_transcription_charges_nothing(client, db_session, media_file, monkeypatch):
    token = register(client).json()["access_token"]

    def boom(*_args, **_kwargs):
        raise RuntimeError("decode failed")

    monkeypatch.setattr("app.main.transcribe_file", boom)

    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code in (422, 500, 503)

    user = db_session.execute(
        select(User).where(User.email == "transcribe@example.com")
    ).scalar_one()

    assert user.processing_used_seconds == 0


def test_failed_transcription_releases_the_reservation(client, db_session, media_file, monkeypatch):
    token = register(client).json()["access_token"]

    def boom(*_args, **_kwargs):
        raise RuntimeError("decode failed")

    monkeypatch.setattr("app.main.transcribe_file", boom)

    with media_file.open("rb") as handle:
        client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    reservations = db_session.execute(select(UsageReservation)).scalars().all()

    assert all(row.status == "released" for row in reservations)
    assert db_session.execute(select(UsageReservation)).scalars().all() != []

    entitlement = client.get("/api/account/entitlement", headers=auth_header(token)).json()
    assert entitlement["processing_remaining_seconds"] == 600
    assert entitlement["processing_reserved_seconds"] == 0


def test_engine_unavailable_does_not_charge(client, db_session, media_file, monkeypatch):
    from app.transcribe import ModelUnavailableError

    token = register(client).json()["access_token"]

    def unavailable(*_args, **_kwargs):
        raise ModelUnavailableError("no model")

    monkeypatch.setattr("app.main.transcribe_file", unavailable)

    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 503
    # The client-facing message is generic, not the internal detail.
    assert "no model" not in response.json()["detail"]

    user = db_session.execute(
        select(User).where(User.email == "transcribe@example.com")
    ).scalar_one()
    assert user.processing_used_seconds == 0


# --- Allowance enforcement before WhisperX runs ---


def test_insufficient_allowance_is_rejected_before_transcription(
    client, db_session, monkeypatch
):
    token = register(client).json()["access_token"]

    user = db_session.execute(
        select(User).where(User.email == "transcribe@example.com")
    ).scalar_one()
    user.processing_used_seconds = 595  # 5 seconds left this period
    db_session.commit()

    # A 10-second file cannot fit in the remaining 5 seconds.
    monkeypatch.setattr("app.main.probe_media", lambda _path: _fake_media(10))

    called = {"value": False}

    def should_not_run(*_args, **_kwargs):
        called["value"] = True

    monkeypatch.setattr("app.main.transcribe_file", should_not_run)

    path = _write_wav()
    with path.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert "5 seconds of processing remaining" in detail
    assert "10 seconds" in detail

    # Critically: WhisperX was never invoked.
    assert called["value"] is False

    db_session.refresh(user)
    assert user.processing_used_seconds == 595


def test_free_plan_rejects_media_longer_than_allowance(client, monkeypatch):
    """A 10-minute limit must be enforced, not assumed."""
    token = register(client).json()["access_token"]

    called = {"value": False}

    def should_not_run(*_args, **_kwargs):
        called["value"] = True

    monkeypatch.setattr("app.main.transcribe_file", should_not_run)
    monkeypatch.setattr("app.main.probe_media", lambda _path: _fake_media(700))

    path = _write_wav()
    with path.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 402
    assert called["value"] is False


def test_paid_plan_has_larger_allowance(client, db_session, monkeypatch):
    token = register(client).json()["access_token"]

    user = db_session.execute(
        select(User).where(User.email == "transcribe@example.com")
    ).scalar_one()
    user.plan = PRO_MONTHLY_PLAN_ID
    user.monthly_processing_allowance_seconds = 90_000
    user.has_full_preview = True
    user.can_export = True
    user.preview_limit_seconds = None
    db_session.commit()

    monkeypatch.setattr("app.main.probe_media", lambda _path: _fake_media(700))
    monkeypatch.setattr("app.main.transcribe_file", _fake_transcriber(1))

    path = _write_wav()
    with path.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    # 700 seconds fits inside the Pro allowance.
    assert response.status_code == 200


# --- Media probing failures ---


def test_file_without_audio_track_is_rejected(client, monkeypatch, media_file):
    token = register(client).json()["access_token"]
    monkeypatch.setattr("app.main.probe_media", lambda _path: _fake_media(2, has_audio=False))

    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 422
    assert "no audio track" in response.json()["detail"]


def test_unmeasurable_media_is_rejected_rather_than_free(client, monkeypatch, media_file):
    """Media we cannot measure cannot be billed, so it must not be transcribed."""
    from app.media import MediaProbeError

    token = register(client).json()["access_token"]

    def failing_probe(_path):
        raise MediaProbeError("The duration of the uploaded file could not be determined.")

    monkeypatch.setattr("app.main.probe_media", failing_probe)

    called = {"value": False}
    monkeypatch.setattr(
        "app.main.transcribe_file", lambda *a, **k: called.__setitem__("value", True)
    )

    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 422
    assert called["value"] is False


def test_max_media_duration_cap_is_enforced(client, monkeypatch, media_file, live_settings):
    token = register(client).json()["access_token"]
    monkeypatch.setattr("app.main.probe_media", lambda _path: _fake_media(120))

    monkeypatch.setenv("MAX_MEDIA_DURATION_SECONDS", "60")
    live_settings()

    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 413


def test_media_within_the_cap_is_accepted(client, monkeypatch, media_file, live_settings):
    token = register(client).json()["access_token"]
    monkeypatch.setattr("app.main.probe_media", lambda _path: _fake_media(30))
    monkeypatch.setattr("app.main.transcribe_file", _fake_transcriber(1))

    monkeypatch.setenv("MAX_MEDIA_DURATION_SECONDS", "60")
    live_settings()

    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 200


# --- Temp file hygiene ---


def test_uploaded_media_is_deleted_after_success(client, monkeypatch, media_file):
    import os
    import tempfile

    seen: dict[str, str] = {}

    def recording_transcriber(path, _settings):
        seen["path"] = path
        assert os.path.exists(path)
        return _fake_transcriber(1)()

    token = register(client).json()["access_token"]
    monkeypatch.setattr("app.main.transcribe_file", recording_transcriber)

    with media_file.open("rb") as handle:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert response.status_code == 200
    # The temporary upload is gone once the request returns.
    assert not os.path.exists(seen["path"])
    assert not os.path.isdir(os.path.dirname(seen["path"]))


def test_uploaded_media_is_deleted_after_failure(client, monkeypatch, media_file):
    import os

    seen: dict[str, str] = {}

    def failing(path, _settings):
        seen["path"] = path
        raise RuntimeError("decode failed")

    token = register(client).json()["access_token"]
    monkeypatch.setattr("app.main.transcribe_file", failing)

    with media_file.open("rb") as handle:
        client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", handle, "audio/wav")},
            headers=auth_header(token),
        )

    assert seen["path"]
    assert not os.path.exists(seen["path"])


# --- Helpers ---


def _fake_transcriber(count: int):
    from app.schemas import TranscriptionResponse

    def run(*_args, **_kwargs):
        return TranscriptionResponse(
            language="en",
            duration=2.0,
            segments=[],
            model="fake",
            device="cpu",
            compute_type="int8",
            word_aligned=True,
        )

    return run


def _fake_media(duration: float, has_audio: bool = True):
    from app.media import MediaInfo

    return MediaInfo(duration_seconds=duration, has_audio=has_audio, has_video=False)


def _write_wav():
    """Write a short real WAV to the system temp dir and return its Path."""
    import tempfile
    from pathlib import Path

    path = Path(tempfile.gettempdir()) / "captionline_billing_test.wav"
    rate = 16000
    frames = bytearray()
    for index in range(rate):
        value = int(8000 * math.sin(2 * math.pi * 220 * (index / rate)))
        frames += struct.pack("<h", value)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))

    return path


def test_billable_seconds_rounds_up():
    assert billable_seconds(0.1) == 1
    assert billable_seconds(1.0) == 1
    assert billable_seconds(1.4) == 2
    assert billable_seconds(90.0) == 90
    assert billable_seconds(0) == 0


def test_probe_measures_real_duration(tmp_path):
    """ffprobe is used for real, so measurement is genuinely verified."""
    from app.media import probe_media

    path = tmp_path / "measured.wav"
    rate = 16000
    frames = bytearray()
    for index in range(rate * 3):
        value = int(8000 * math.sin(2 * math.pi * 220 * (index / rate)))
        frames += struct.pack("<h", value)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))

    info = probe_media(str(path))

    assert info.duration_seconds == pytest.approx(3.0, abs=0.2)
    assert info.has_audio is True
    assert billable_seconds(info.duration_seconds) == 3
