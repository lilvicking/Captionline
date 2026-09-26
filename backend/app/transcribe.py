"""WhisperX transcription engine wrapper.

WhisperX transcribes with faster-whisper and then runs a forced-alignment pass to
produce word-level timestamps. This module owns model lifetime (models are
expensive, so they are cached process-wide) and converts WhisperX output into
Captionline's own format.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .config import Settings, resolve_compute_type, resolve_device
from .schemas import CaptionSegment, TranscriptionResponse, WordTiming

logger = logging.getLogger(__name__)

# WhisperX audio is loaded at 16 kHz.
SAMPLE_RATE = 16_000

# Model load is not thread-safe (CTranslate2 + torch), so a single lock guards
# both loading and inference.
_model_lock = threading.Lock()

_state: dict[str, Any] = {
    "asr": None,
    "align": None,
    "align_meta": None,
    "device": None,
    "compute_type": None,
    "error": None,
}


class ModelUnavailableError(RuntimeError):
    """Raised when WhisperX cannot be imported or its model cannot be loaded."""


def cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def model_state(settings: Settings) -> dict[str, Any]:
    """Introspection for the health endpoint."""
    return {
        "loaded": _state["asr"] is not None,
        "device": _state["device"],
        "compute_type": _state["compute_type"],
        "error": _state["error"],
    }


def load_audio(audio_path: str) -> Any:
    """Load audio from disk as a mono 16 kHz numpy array via WhisperX."""
    try:
        import whisperx
    except Exception as exc:  # pragma: no cover
        raise ModelUnavailableError(f"WhisperX is not importable: {exc}") from exc

    try:
        return whisperx.load_audio(audio_path)
    except Exception as exc:
        raise RuntimeError(f"Could not decode audio from the uploaded file: {exc}") from exc


def _load_models(settings: Settings) -> tuple[Any, Any, Any]:
    """Load (and cache) the ASR model and, when enabled, the alignment model."""
    with _model_lock:
        if _state["asr"] is not None and _state["device"] == _effective_device(settings):
            return _state["asr"], _state["align"], _state["align_meta"]

        try:
            import whisperx
        except Exception as exc:  # pragma: no cover
            _state["error"] = f"WhisperX is not importable: {exc}"
            raise ModelUnavailableError(_state["error"]) from exc

        device = _effective_device(settings)
        compute_type = resolve_compute_type(settings.whisperx_compute_type, device)

        logger.info(
            "Loading WhisperX model=%s device=%s compute_type=%s",
            settings.whisperx_model,
            device,
            compute_type,
        )

        try:
            asr = whisperx.load_model(
                settings.whisperx_model,
                device,
                compute_type=compute_type,
            )
        except Exception as exc:
            _state["error"] = f"Failed to load WhisperX model: {exc}"
            logger.exception("WhisperX model load failed")
            raise ModelUnavailableError(_state["error"]) from exc

        align_model = None
        align_meta = None

        if settings.whisperx_align_enabled:
            try:
                align_model, align_meta = whisperx.load_align_model(
                    language_code=None,
                    model_name=settings.whisperx_align_model,
                    device=device,
                )
            except Exception as exc:
                # Alignment is required for word timestamps, so surface it, but
                # keep the transcribe path usable if the caller opted in.
                _state["error"] = f"Failed to load alignment model: {exc}"
                logger.exception("Alignment model load failed")
                raise ModelUnavailableError(_state["error"]) from exc

        _state["asr"] = asr
        _state["align"] = align_model
        _state["align_meta"] = align_meta
        _state["device"] = device
        _state["compute_type"] = compute_type
        _state["error"] = None

        return asr, align_model, align_meta


def _effective_device(settings: Settings) -> str:
    return resolve_device(settings.whisperx_device)


def preload(settings: Settings) -> None:
    """Warm the model cache at startup (optional)."""
    try:
        _load_models(settings)
    except ModelUnavailableError:
        logger.warning("Preload requested but the model could not be loaded")


def _clean_word(raw: Any) -> str:
    return str(raw or "").strip()


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _normalize_words(raw_words: Any) -> list[WordTiming]:
    """Keep only words that carry usable timing information."""
    words: list[WordTiming] = []

    if not isinstance(raw_words, list):
        return words

    for raw in raw_words:
        if not isinstance(raw, dict):
            continue

        start = _to_float(raw.get("start"))
        end = _to_float(raw.get("end"))
        text = _clean_word(raw.get("word"))

        if text == "" or start is None or end is None:
            continue

        words.append(
            WordTiming(
                word=text,
                start=start,
                end=end,
                score=_to_float(raw.get("score")),
            )
        )

    return words


def _normalize_segments(result: dict[str, Any]) -> list[CaptionSegment]:
    segments: list[CaptionSegment] = []
    raw_segments = result.get("segments") or []

    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            continue

        start = _to_float(raw.get("start"))
        end = _to_float(raw.get("end"))

        if start is None or end is None:
            continue

        text = str(raw.get("text") or "").strip()

        segments.append(
            CaptionSegment(
                id=index + 1,
                start=start,
                end=end,
                text=text,
                words=_normalize_words(raw.get("words")),
            )
        )

    return segments


def transcribe_file(audio_path: str, settings: Settings) -> TranscriptionResponse:
    """Transcribe and align one media file, returning Captionline's format."""
    try:
        import whisperx
    except Exception as exc:  # pragma: no cover
        raise ModelUnavailableError(f"WhisperX is not importable: {exc}") from exc

    audio = load_audio(audio_path)
    duration = round(len(audio) / SAMPLE_RATE, 3) if hasattr(audio, "__len__") else 0.0

    asr, align_model, align_meta = _load_models(settings)
    device = _state["device"] or resolve_device(settings.whisperx_device)

    with _model_lock:
        logger.info("Transcribing %s", audio_path)
        result = asr.transcribe(
            audio,
            batch_size=settings.whisperx_batch_size,
            language=settings.whisperx_language,
        )

        # Capture the language now: whisperx.align() returns only the segment and
        # word-segment keys, so reading it afterwards would lose the detection.
        language = str(result.get("language") or settings.whisperx_language or "unknown")

        word_aligned = False

        if settings.whisperx_align_enabled and align_model is not None:
            logger.info("Aligning word-level timestamps")
            result = whisperx.align(
                result["segments"],
                align_model,
                align_meta,
                audio,
                device,
                return_char_alignments=False,
            )
            word_aligned = True

    segments = _normalize_segments(result)

    if not segments and duration > 0:
        # No speech detected: keep the duration so the editor still has a timeline.
        logger.info("No speech segments detected in %s", audio_path)

    return TranscriptionResponse(
        language=language,
        duration=duration,
        segments=segments,
        model=settings.whisperx_model,
        device=device,
        compute_type=_state["compute_type"] or "",
        word_aligned=word_aligned,
    )
