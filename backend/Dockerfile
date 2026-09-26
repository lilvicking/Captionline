# Captionline transcription service
#
# Railway builds this image when the service has no other build configuration.
# Railway injects PORT at runtime; the start command binds to 0.0.0.0:$PORT.
#
# This image is CPU-only by default. It contains no CUDA runtime, which keeps the
# image far smaller. If you later attach GPU infrastructure, switch the torch
# install to the CUDA index (see README "GPU deployment").
#
# Image size warning: the CPU torch wheel alone is roughly 200-250 MB, and the
# full dependency tree lands around 4-6 GB. A CUDA build is considerably larger.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg is required by WhisperX/faster-whisper to decode uploaded media.
# libgomp1 is needed by torch CPU kernels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# Container-aware: honours the PORT variable supplied by Railway.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
