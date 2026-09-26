# Captionline transcription service

A FastAPI service that turns an uploaded video or audio file into timed captions with
**word-level timestamps**, using [WhisperX](https://github.com/m-bain/whisperX), and (Phase 3A)
manages Captionline accounts, plans, and usage in PostgreSQL.

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
  "cuda_available": true,
  "database": { "configured": true, "reachable": true, "status": "ok" }
}
```

`database` reports a coarse status only. The connection string is never returned, and connection
errors are logged server-side, so credentials cannot leak through this endpoint.

### `POST /api/transcribe`

Accepts a single uploaded media file as `multipart/form-data` under the field name `file`.
Supported: mp4, mov, mkv, webm, avi, m4v, mp3, wav, m4a, flac, ogg.

The file is written to a temporary directory, transcribed and aligned, and the temporary directory
is deleted before the response is returned. Nothing is persisted.

**Not gated by authentication in Phase 3A.** Transcription stays open while accounts are being
validated; enforcement comes later.

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

### `POST /api/auth/register`

```json
{ "email": "you@example.com", "password": "at-least-8-characters" }
```

Returns `201` with a bearer token and the created user. Duplicate email returns `409`. The new
account is seeded from the free plan in `app/plans.py`.

### `POST /api/auth/login`

Same body. Returns `200` with a token, or `401` with a deliberately identical response whether the
email is unknown or the password is wrong, so registered addresses cannot be discovered.

### `GET /api/auth/me`

Requires `Authorization: Bearer <token>`. Returns the authenticated user.

### `POST /api/auth/logout`

Revokes the presented session. The token stops working immediately.

### `GET /api/account/entitlement`

Requires a token. Every value is computed from the authenticated user's database row; nothing is
taken from the request.

```json
{
  "plan": "free",
  "plan_label": "Free",
  "subscription_status": "none",
  "monthly_processing_allowance_seconds": 600,
  "processing_used_seconds": 192,
  "processing_remaining_seconds": 408,
  "usage_period_started_at": "2026-09-01T00:00:00Z",
  "usage_period_ends_at": "2026-10-01T00:00:00Z",
  "preview_limit_seconds": 30,
  "has_full_preview": false,
  "can_export": false,
  "processing_allowance_minutes": 10.0,
  "processing_used_minutes": 3.2,
  "processing_remaining_minutes": 6.8
}
```

### Status codes

| Code | Meaning |
| ---- | ------- |
| 200 | Success |
| 201 | Account created |
| 400 | Unsupported or empty file |
| 401 | Missing, invalid, revoked, or expired session |
| 409 | Email already registered |
| 413 | File exceeds `MAX_UPLOAD_MB` |
| 422 | Invalid payload, or media could not be decoded |
| 503 | WhisperX unavailable, or no `DATABASE_URL` configured |

---

## Database

PostgreSQL in production, via SQLAlchemy 2.0 with Alembic migrations.

### Why this stack

- **SQLAlchemy 2.0** is the reference Python ORM and its typed `Mapped[]` / `mapped_column` style
  keeps the schema declarative and reviewable. It is also portable, which is why the same models and
  the same migration revision run on PostgreSQL in production and on SQLite for local runs and the
  test suite.
- **Alembic** rather than `create_all`. `create_all` cannot alter an existing table, produces no
  history, and is unsafe to run against a live database. Every schema change is a reviewed revision.
- **psycopg 3** (`psycopg[binary]`) as the PostgreSQL driver. `postgres://` and `postgresql://` URLs
  from Railway are normalised to `postgresql+psycopg://` automatically.
- **Synchronous SQLAlchemy** with plain `def` route handlers. FastAPI runs `def` handlers in a thread
  pool, so nothing blocks the event loop, and it keeps one database style rather than mixing sync and
  async sessions. Transcription, the genuinely expensive part, is already offloaded with
  `run_in_threadpool`.

### Configuration

`DATABASE_URL` is the only database setting. It is optional: without it the service still starts and
transcribes, `/api/health` reports `database.status = "not_configured"`, and the account endpoints
return `503`. That keeps local development and transcription-only setups working.

```bash
# Production (Railway)
DATABASE_URL=${{Postgres.DATABASE_URL}}

# Local PostgreSQL
DATABASE_URL=postgresql://captionline:<your-local-password>@localhost:5432/captionline

# Local without PostgreSQL (development and tests only)
DATABASE_URL=sqlite:///./captionline.db
```

### Migrations

```bash
cd backend
alembic upgrade head          # apply
alembic downgrade -1          # roll back one revision
alembic current               # show applied revision
alembic revision --autogenerate -m "describe the change"   # author a new revision
alembic history               # list revisions
```

The Docker image runs `alembic upgrade head` before starting Uvicorn, so a new revision is applied on
deploy. Migrations never run on import.

### Schema

`users` (18 columns)

| Group | Columns |
| ----- | ------- |
| Identity | `id`, `email`, `password_hash`, `is_active` |
| Plan | `plan` |
| Mirrored subscription | `subscription_status`, `subscription_provider`, `subscription_external_id`, `subscription_current_period_end` |
| Usage | `monthly_processing_allowance_seconds`, `processing_used_seconds`, `usage_period_started_at`, `usage_period_ends_at` |
| Entitlements | `preview_limit_seconds`, `has_full_preview`, `can_export` |
| Timestamps | `created_at`, `updated_at` |

`sessions` (7 columns): `id`, `user_id`, `token_hash`, `created_at`, `expires_at`, `revoked_at`,
`last_used_at`. Tokens are stored only as SHA-256 hashes, so a database leak yields no usable
credentials.

### Free plan defaults

Defined once in `app/plans.py`; no literal is duplicated in the backend.

| Setting | Value |
| ------- | ----- |
| Monthly processing allowance | 600 seconds (10 minutes) |
| Finished-video preview | 30 seconds |
| Full preview | no |
| Finished-video export | no |
| Subscription status | `none` |

Unknown plan ids fall back to the free plan, so a bad value can never widen access.

### Usage calculation

Seconds are the unit of record; minutes are derived only for display, so rounding never loses time.
`remaining` is clamped at zero. The usage period is the UTC calendar month and rolls over lazily on
read (`ensure_current_usage_period`), so no scheduled job is needed.

`app/usage.py` also provides `record_processing_seconds`, but it is deliberately **not** called from
`/api/transcribe` in Phase 3A. Enforcing the allowance on transcription comes after account and usage
state has been validated in production.

### Stripe, later

Not implemented. The `subscription_*` columns are shaped as a local mirror so that Stripe can become
the authoritative source without a redesign: a future webhook writes `subscription_status`,
`subscription_external_id`, and the period end, and the backend then trusts Stripe over the mirror
when deciding paid access. See the note in `app/db/models.py`.

---

## Authentication

Opaque bearer sessions, which are simple for a cross-origin SPA and support real revocation.

- Registration and login return a 256-bit `secrets` token.
- Only the token's SHA-256 hash is stored, so the database never holds a usable credential.
- `POST /api/auth/logout` sets `revoked_at`; the token stops working immediately. A stateless JWT
  could not do this without a blocklist.
- Passwords are hashed with **Argon2id** via `argon2-cffi` at OWASP-recommended parameters
  (64 MiB memory, 3 iterations, parallelism 4). Plaintext is never stored or logged.
- `pwdlib` was evaluated and rejected: version 0.3.1 produced valid `$argon2id$` hashes that its own
  `verify` could not identify, which would have failed every login.

Not implemented, by design: OAuth or social login, email verification, and password reset.

**Tradeoff:** the token is held in `localStorage` and sent as an `Authorization: Bearer` header. The
Captionline web and API are separate Railway origins, so this avoids `SameSite` and cookie-credential
handling. The hardening path, if wanted, is httpOnly `SameSite=None; Secure` cookies plus CSRF
protection.

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

Apply migrations and run:

```bash
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify:

```bash
curl http://localhost:8000/api/health
```

The first transcription request downloads the models (roughly 460 MB for `small` plus about 360 MB
for the alignment model) and is slow. Later requests reuse the cache and are much faster.

### Tests

```bash
pytest
```

The suite covers plan defaults, usage-period arithmetic, registration, duplicate email, login
success and failure, token storage, session revocation, entitlement, and the no-database fallback. It
runs the real Alembic migration against a temporary SQLite database, so no PostgreSQL server is
needed to run it.

### Optional: exact local pins

`requirements.lock.txt` records the fully pinned environment used during development. Use it to
reproduce that machine exactly. Do not use it in the Linux container build: the `+cu128` torch build
is platform specific.

---

## Configuration

Every setting is an environment variable. See `.env.example` for the annotated list.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DATABASE_URL` | unset | PostgreSQL (production) or SQLite (local) URL |
| `DATABASE_ECHO` | `0` | Log SQL. Never enable in production. |
| `WHISPERX_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3` |
| `WHISPERX_DEVICE` | `auto` | `auto` uses CUDA when available, otherwise CPU |
| `WHISPERX_COMPUTE_TYPE` | `auto` | `auto` = float16 on CUDA, int8 on CPU |
| `WHISPERX_BATCH_SIZE` | `8` | Lower this on small GPUs if you hit OOM |
| `WHISPERX_LANGUAGE` | unset | Force a language; unset means auto-detect |
| `WHISPERX_ALIGN_MODEL` | `WAV2VEC2_ASR_BASE_960H` | Forced-alignment model |
| `WHISPERX_ALIGN_ENABLED` | `1` | Set `0` to skip alignment (faster, no word timings) |
| `SESSION_TTL_DAYS` | `30` | Bearer session lifetime |
| `MIN_PASSWORD_LENGTH` | `8` | Minimum registration password length |
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

- Binds to `0.0.0.0` and reads `PORT`.
- All configuration is environment driven.
- Uploads use the system temp directory and are deleted after each request, so **no volume or
  persistent disk is required**.
- No Windows-specific paths or commands are used, so the image is Linux-only by design.

### Using the Dockerfile

`backend/Dockerfile` is a CPU image based on `python:3.12-slim` with `ffmpeg`, `libgomp1`, and
`libpq5` installed. Its start command applies migrations, then serves:

```
alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

In Railway, add a service with **Dockerfile** as the build method, root directory `backend`.

Railway environment variables to set:

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
WHISPERX_MODEL=small
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
CORS_ORIGINS=https://<your-frontend-domain>
MAX_UPLOAD_MB=500
SESSION_TTL_DAYS=30
```

`DATABASE_URL` must be present or the account endpoints return `503`. Transcription is unaffected.

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
├── alembic/
│   ├── env.py                     # Reads DATABASE_URL from app settings
│   └── versions/
│       └── 0001_initial_accounts.py
├── alembic.ini                    # No connection string stored here
├── app/
│   ├── __init__.py
│   ├── config.py                  # Env-driven settings
│   ├── main.py                    # FastAPI app, CORS, health, transcribe
│   ├── schemas.py                 # Transcription models
│   ├── plans.py                   # Free plan defaults (single source of truth)
│   ├── usage.py                   # Usage periods, snapshots, entitlement
│   ├── transcribe.py              # WhisperX lifecycle + normalization
│   ├── db/
│   │   ├── base.py                # Declarative base
│   │   ├── models.py              # User, Session
│   │   └── session.py             # Engine, session, DATABASE_URL handling
│   ├── routers/
│   │   ├── auth.py                # register, login, me, logout
│   │   └── account.py             # entitlement
│   └── security/
│       ├── passwords.py           # Argon2id
│       ├── tokens.py              # Opaque token generation + hashing
│       ├── deps.py                # get_current_user, require_database
│       └── schemas.py             # Auth + entitlement models
├── tests/                         # pytest suite
├── requirements.txt
├── requirements.lock.txt
├── pytest.ini
├── Dockerfile
├── .env.example
└── .dockerignore
```

Model loading and database sessions are process-wide and pooled, so repeat requests do not pay the
load cost again.

---

## Known limitations

- **Long uploads and timeouts.** Transcription is synchronous. A long video on CPU can take far
  longer than a typical 60-second proxy timeout, so Railway will need either a longer timeout or a
  background-job design.
- **No usage enforcement yet.** `record_processing_seconds` exists but is not wired to
  `/api/transcribe`, by design for Phase 3A.
- **No email verification or password reset.** Deliberately out of scope.
- **Session tokens live in `localStorage`.** Acceptable for now given the cross-origin setup; see the
  authentication tradeoff note.
- **`torchcodec` warning on Windows.** pyannote warns that built-in audio decoding is unavailable
  because `libtorchcodec` DLLs are missing. WhisperX passes audio in memory, so decoding still
  works, but the warning appears in the logs.
- **No diarization, translation, or rendering.** Deliberately out of scope.
