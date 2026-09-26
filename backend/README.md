# Captionline transcription service

A small FastAPI service that turns an uploaded video or audio file into timed captions with
**word-level timestamps**, using [WhisperX](https://github.com/m-bain/whisperX).

WhisperX was chosen because it transcribes with faster-whisper and then runs a forced-alignment
pass, which produces the accurate per-word timings that Captionline's karaoke captions and
active-word highlighting depend on.

```
Video
  → Captionline transcription service
    → WhisperX (faster-whisper + alignment)
      → word-level timestamp JSON (Captionline format)
  → Captionline editor
```

WhisperX is consumed as a pinned pip dependency. No WhisperX source is vendored into this repo, so
Captionline owns the API surface and the data format.

---

## API

### `GET /api/health`

Liveness/readiness probe. Safe to call on Railway.

```json
{
  "status": "ok",
  "version": "0.2.0",
  "whisperx_model": "small",
  "device": "cuda",
  "compute_type": "float16",
  "batch_size": 8,
  "model_loaded": true,
  "alignment_enabled": true,
  "cuda_available": true
}
```

### `POST /api/transcribe`

Accepts a single uploaded media file as `multipart/form-data` under the field name `file`.
Supported: mp4, mov, mkv, webm, avi, m4v, mp3, wav, m4a, flac, ogg.

The file is written to a temporary directory, transcribed and aligned, and the temporary directory
is deleted before the response is returned. Nothing is persisted.

```bash
curl -F "file=@clip.mp4" http://localhost:8000/api/transcribe
```

Response — Captionline's own format, not raw WhisperX internals:

```json
{
  "language": "en",
  "duration": 12.4,
  "segments": [
    {
      "id": 1,
      "start": 0.0,
      "end": 3.2,
      "text": "Example caption text",
      "words": [{ "word": "Example", "start": 0.0, "end": 0.6, "score": 0.98 }]
    }
  ],
  "model": "small",
  "device": "cuda",
  "compute_type": "float16",
  "word_aligned": true
}
```

`word_aligned` is `false` when alignment was skipped, so the client can tell "no words" apart from
"words not requested". `score` is the engine confidence and is `null` when unavailable.

### Status codes

| Code | Meaning |
| ---- | ------- |
| 200 | Success |
| 400 | Unsupported or empty file |
| 413 | File exceeds `MAX_UPLOAD_MB` |
| 422 | The media could not be decoded or transcribed |
| 503 | The WhisperX model could not be loaded |

---

## Local setup

Requires **Python 3.12**. Python 3.14 is not supported by the WhisperX dependency chain (numba and
ctranslate2 lag new CPython releases). Python 3.10 and 3.11 also work.

`ffmpeg` must be installed and on `PATH`; WhisperX uses it to decode media.

```bash
cd backend
python3.12 -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env      # optional; sensible defaults are built in
```

Run it:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify:

```bash
curl http://localhost:8000/api/health
```

The first transcription request downloads the models (roughly 460 MB for `small` plus about 360 MB
for the alignment model) and is slow. Later requests reuse the cache and are much faster.

### Optional: exact local pins

`requirements.lock.txt` records the fully pinned environment used during development
(120 packages, including a CUDA build of torch). Use it to reproduce that machine exactly:

```bash
pip install -r requirements.lock.txt
```

Do not use it in the Linux container build: the `+cu128` torch build is platform specific.

---

## Configuration

Every setting is an environment variable. See `.env.example` for the annotated list.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `WHISPERX_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3` |
| `WHISPERX_DEVICE` | `auto` | `auto` uses CUDA when available, otherwise CPU |
| `WHISPERX_COMPUTE_TYPE` | `auto` | `auto` = float16 on CUDA, int8 on CPU |
| `WHISPERX_BATCH_SIZE` | `8` | Lower this on small GPUs if you hit OOM |
| `WHISPERX_LANGUAGE` | unset | Force a language; unset means auto-detect |
| `WHISPERX_ALIGN_MODEL` | `WAV2VEC2_ASR_BASE_960H` | Forced-alignment model |
| `WHISPERX_ALIGN_ENABLED` | `1` | Set `0` to skip alignment (faster, no word timings) |
| `PORT` | `8000` | Railway supplies this |
| `HOST` | `0.0.0.0` | Bind address |
| `CORS_ORIGINS` | localhost dev origins | Comma-separated allowed origins |
| `MAX_UPLOAD_MB` | `500` | Upload size limit |
| `TEMP_DIR` | system temp | Leave unset on ephemeral hosts |
| `PRELOAD_MODEL` | `0` | Set `1` to load the model at startup |

### Model choice

`small` is the development default: it is a reasonable accuracy/speed tradeoff and keeps the first
download manageable. Production should move to `large-v2` by setting `WHISPERX_MODEL=large-v2` and
nothing else.

`WHISPERX_DEVICE=auto` means no code change is needed to move between a GPU box and a CPU-only
host. On CPU the service runs with `int8`, which is dramatically smaller and faster than float32.

### GPU and CUDA

The PyPI default `torch` wheel is the **CPU** build, so `torch.cuda.is_available()` is `False` even
on a machine with an NVIDIA GPU. To use a local GPU, install the CUDA build from PyTorch's index:

```bash
pip install --upgrade torch==2.8.0 torchaudio==2.8.0 \
  --index-url https://download.pytorch.org/whl/cu128
```

Notes:

- This only affects the virtualenv. It does not install or modify a system CUDA toolkit, and it
  does not touch drivers.
- The CUDA wheel is about **3.5 GB**, so the download is slow and can fail on flaky connections.
  Retry it if pip reports a hash mismatch.
- `ffmpeg` is still required regardless of device.

---

## Railway deployment

The service is designed to run on Railway with no code changes.

- Binds to `0.0.0.0` and reads `PORT`, so Railway's health check and routing work.
- All configuration is environment driven.
- Uploads use the system temp directory and are deleted after each request, so **no volume or
  persistent disk is required**.
- No Windows-specific paths or commands are used, so the image is Linux-only by design.

### Using the Dockerfile

`backend/Dockerfile` is a CPU image based on `python:3.12-slim` with `ffmpeg` and `libgomp1`
installed. Its start command is container-aware:

```
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

In Railway, add a service with **Dockerfile** as the build method, root directory `backend`.

Railway environment variables to set:

```
WHISPERX_MODEL=small
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
CORS_ORIGINS=https://<your-frontend-domain>
MAX_UPLOAD_MB=500
```

Set `CORS_ORIGINS` to the deployed Captionline frontend origin. `*` is accepted for initial
testing but should not be used in production.

**Image size warning:** the CPU torch wheel plus the rest of the dependency tree produces an image
of roughly **4-6 GB**. A CUDA-based image is considerably larger still. This is the main practical
cost of running WhisperX on Railway, and it is worth measuring before relying on it.

### GPU deployment

`WHISPERX_DEVICE=auto` means the same code runs on CPU-only Railway infrastructure. If you later want
GPU acceleration you will need a host that actually provides an NVIDIA GPU, and the Dockerfile
would need a CUDA base image plus the CUDA torch index. **No GPU resources have been provisioned or
configured.**

### Startup time

The model loads lazily on the first request, so the first request after a cold start pays the
model-load cost. If Railway's startup timeout is tight, set `PRELOAD_MODEL=1` so the model loads
during startup instead.

---

## Project layout

```
backend/
├── app/
│   ├── __init__.py
│   ├── config.py       # Environment-driven settings, device/compute-type resolution
│   ├── main.py         # FastAPI app, CORS, health, /api/transcribe, temp cleanup
│   ├── schemas.py      # Captionline's response models (Pydantic)
│   └── transcribe.py   # WhisperX model lifecycle + output normalization
├── requirements.txt    # Direct dependencies
├── requirements.lock.txt # Fully pinned local environment
├── Dockerfile
├── .env.example
└── .dockerignore
```

Model loading is process-wide and guarded by a lock, so repeated requests reuse the loaded models
rather than paying the load cost again.

---

## Known limitations

- **Long uploads and timeouts.** Transcription is synchronous. A long video on CPU can take far
  longer than a typical 60-second proxy timeout, so Railway will need either a longer timeout or a
  background-job design. That is a Phase 3 concern, not solved here.
- **No queueing or persistence.** One request is transcribed at a time.
- **Word alignment is required for karaoke.** Setting `WHISPERX_ALIGN_ENABLED=0` removes word
  timings, and the frontend then renders captions as plain text.
- **`torchcodec` warning on Windows.** pyannote warns that built-in audio decoding is unavailable
  because `libtorchcodec` DLLs are missing. WhisperX passes audio in memory, so decoding still
  works, but the warning appears in the logs.
- **No diarization, translation, or rendering.** Deliberately out of scope.
