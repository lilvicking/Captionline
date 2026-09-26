"""Captionline's public transcription contract.

These models are what the React frontend consumes. WhisperX's internal structures
are normalized into this shape in `transcribe.py` so that engine internals are
never exposed to the client and can change without breaking the frontend.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WordTiming(BaseModel):
    """A single word with its own start/end time and confidence."""

    word: str
    start: float
    end: float
    score: float | None = None


class CaptionSegment(BaseModel):
    """A caption cue with optional word-level alignment."""

    id: int
    start: float
    end: float
    text: str
    words: list[WordTiming] = Field(default_factory=list)


class TranscriptionResponse(BaseModel):
    """Normalized result returned by POST /api/transcribe."""

    language: str
    duration: float
    segments: list[CaptionSegment] = Field(default_factory=list)
    model: str = ""
    device: str = ""
    compute_type: str = ""
    # False when alignment was skipped or unavailable, so the frontend can tell
    # "no words" apart from "words not requested".
    word_aligned: bool = True


class HealthResponse(BaseModel):
    status: str
    version: str
    whisperx_model: str
    device: str
    compute_type: str
    batch_size: int
    model_loaded: bool
    alignment_enabled: bool
    cuda_available: bool
