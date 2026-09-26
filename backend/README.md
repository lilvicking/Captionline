# Captionline transcription service

A FastAPI service that turns an uploaded video or audio file into timed captions with
**word-level timestamps** using [WhisperX](https://github.com/m-bain/whisperX), manages
**accounts, plans, and usage** in PostgreSQL, and handles **Stripe billing**.

WhisperX was chosen because it transcribes with faster-whisper and then runs a forced-alignment
pass, which produces the accurate per-word timings that Captionline's karaoke captions and
active-word highlighting depend on.

```
Video
  → Captionline transcription service
    → authenticate + measure duration + reserve allowance
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

**Requires authentication.** Consumes a metered allowance, so an anonymous or
unauthenticated caller is rejected with `401` and no processing is performed.

Accepts a single uploaded media file as `multipart/form-data` under the field name `file`.
Supported: mp4, mov, mkv, webm, avi, m4v, mp3, wav, m4a, flac, ogg.

```bash
curl -H "Authorization: Bearer $TOKEN" -F "file=@clip.mp4" http://localhost:8000/api/transcribe
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

### `GET /api/account/plans`

Public, so the pricing table renders while signed out. Returns the authoritative plan catalogue,
including `purchasable`, which is `false` when Stripe is not configured for that plan.

### `GET /api/account/entitlement`

Requires a token. Every value is computed from the authenticated user's database row; nothing is
taken from the request.

```json
{
  "plan": "creator_monthly",
  "plan_label": "Creator",
  "subscription_status": "active",
  "is_paid_plan": true,
  "monthly_processing_allowance_seconds": 30000,
  "processing_used_seconds": 192,
  "processing_reserved_seconds": 0,
  "processing_remaining_seconds": 29808,
  "usage_period_started_at": "2026-09-01T00:00:00Z",
  "usage_period_ends_at": "2026-10-01T00:00:00Z",
  "usage_resets_monthly": true,
  "billed_annually": false,
  "preview_limit_seconds": null,
  "has_full_preview": true,
  "can_export": true,
  "processing_allowance_minutes": 500.0,
  "processing_used_minutes": 3.2,
  "processing_remaining_minutes": 496.8
}
```

### `POST /api/billing/checkout`

Requires a token. Body is `{"plan": "creator_monthly"}`. Creates a Stripe Checkout session and
returns its hosted URL. The amount comes from the server-configured Price ID; the client cannot
influence what is charged.

### `POST /api/billing/portal`

Requires a token and an existing Stripe customer. Returns a Customer Portal URL.

### `POST /api/billing/webhook`

Stripe webhook receiver. Requires a valid `Stripe-Signature` header. Idempotent.

### Status codes

| Code | Meaning |
| ---- | ------- |
| 200 | Success |
| 201 | Account created |
| 204 | Logged out |
| 400 | Unsupported file, invalid plan, or malformed webhook payload |
| 401 | Missing, invalid, revoked, or expired session |
| 402 | Not enough processing allowance remaining |
| 409 | Email already registered |
| 413 | File exceeds `MAX_UPLOAD_MB`, or media exceeds the duration cap |
| 422 | Invalid payload, unreadable media, or no audio track |
| 502 | Stripe unreachable |
| 503 | WhisperX unavailable, Stripe not configured, or no `DATABASE_URL` |

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

`users` (19 columns)

| Group | Columns |
| ----- | ------- |
| Identity | `id`, `email`, `password_hash`, `is_active` |
| Plan | `plan` |
| Mirrored subscription | `subscription_status`, `subscription_provider`, `subscription_external_id`, `subscription_price_id`, `subscription_current_period_end` |
| Usage | `monthly_processing_allowance_seconds`, `processing_used_seconds`, `usage_period_started_at`, `usage_period_ends_at` |
| Entitlements | `preview_limit_seconds`, `has_full_preview`, `can_export` |
| Timestamps | `created_at`, `updated_at` |

`usage_reservations` — two-phase allowance holds (see accounting below).
`stripe_events` — processed Stripe event ids, for idempotent webhooks.
`sessions` — bearer sessions; tokens are stored only as SHA-256 hashes.

### Plan catalogue

Defined once in `app/plans.py`; no literal is duplicated in the backend and the frontend never
supplies plan information.

**Billing cadence and usage cadence are separate concerns.** `billing_period` is when Stripe
charges the customer. `usage_period_months` is when the processing allowance resets.

| Plan | id | Price | Allowance | Usage reset | Billing | Full preview | Export |
| ---- | -- | ----- | --------- | ----------- | ------- | ------------ | ------ |
| Free | `free` | $0 | 600 s (10 min) | monthly | — | no (30 s) | no |
| Creator | `creator_monthly` | $19 | 30,000 s (500 min) | monthly | monthly | yes | yes |
| Pro | `pro_monthly` | $39 | 90,000 s (1,500 min) | monthly | monthly | yes | yes |
| Creator Annual | `creator_annual` | $190 | 30,000 s (500 min) | **monthly** | **annual** | yes | yes |

`creator_annual` is charged once a year by Stripe but its allowance still resets every month, the
same as Creator Monthly. Buying a year does not buy twelve months up front, and **unused minutes do
not roll over** — a rollover sets usage back to zero and discards the remainder. It is simply the
same 500 minutes for $38 less per year ($19 × 12 = $228 versus $190).

A usage rollover never touches subscription state, so a paid customer keeps full preview and export
entitlement across every reset.

Unknown plan ids fall back to Free, so a bad value can never widen access.

### Processing accounting

Seconds are the unit of record; minutes are derived only for display, so rounding never loses time.
`remaining` is clamped at zero. Usage periods are the UTC calendar month for **every** plan —
including the annually billed one — rolling over lazily on read (`ensure_current_usage_period`) so
no scheduled job is needed. Unused allowance is discarded at the boundary rather than accumulated.

**Duration is measured server-side.** `app/media.py` runs `ffprobe` (which ships with ffmpeg and is
already required to decode uploads) and bills `ceil(duration)`. The client never declares its own
length. A file whose duration cannot be measured is **rejected** rather than transcribed, because
unmetered transcription would be worse than a refusal.

**Nothing is charged for an upload that merely starts.** Allowance is held, then converted:

1. `reserve_processing_seconds` — checks the allowance and inserts a `usage_reservations` row with
   status `reserved`.
2. Transcription runs.
3. On success `finalize_reservation` adds the seconds to `users.processing_used_seconds`.
4. On **any** failure `release_reservation` marks the row `released` and nothing is charged.

A request that crashes leaves a `reserved` row; `release_stale_reservations` reclaims it after
`USAGE_RESERVATION_TTL_SECONDS` (default 2 hours), so a crash cannot permanently consume allowance.

### Concurrency protection

Two simultaneous requests must not be able to spend the same remaining allowance.

`reserve_processing_seconds` performs the check and the hold in **one transaction that first takes a
row-level lock** on the account:

```python
locked_user = db.scalar(select(User).where(User.id == user.id).with_for_update())
```

On PostgreSQL, a second concurrent request for the same account blocks at that `SELECT ... FOR
UPDATE` until the first transaction commits. It then re-reads the committed `processing_used_seconds`
**and** the newly inserted reservation row, so `remaining` accounts for the in-flight hold and the
second request is refused if the allowance is genuinely exhausted.

The lock is released at commit, which happens *before* the expensive WhisperX work, so a long
transcription never holds a database lock.

Remaining allowance is therefore `allowance - used - SUM(active reservations)`, and `remaining`
never goes negative.

Note: SQLite (used by the test suite) does not implement `SELECT ... FOR UPDATE`. The test asserts
the observable contract — that a second hold cannot spend the first's seconds — which is what the
row lock guarantees on PostgreSQL.

### Entitlement authority

The backend is authoritative. `GET /api/account/entitlement` derives everything from the account's
database row, and the client sends no plan or entitlement values. Paid access exists only when a
**verified** Stripe webhook has set an active subscription.

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
protection. Moving to cookies would also require the custom domain to be attached first, since
`SameSite=None` cookies are rejected on cross-site requests.

### Session hygiene

- Tokens are never logged. The log records request outcomes, never headers or token values.
- Logout revokes the row, so the token stops working immediately.
- Login returns an identical `401` for an unknown email and a wrong password, so account existence
  cannot be probed.
- Expired and revoked rows are purged opportunistically by `purge_expired_sessions`, keeping a
  recently expired row briefly so it reports "expired" rather than "unknown".

---

## Stripe billing

### What is authoritative

**Stripe.** A browser returning from Checkout changes nothing: `POST /api/billing/checkout` only
creates a session. Paid access appears only when a **signature-verified webhook** is processed. An
unmapped Price ID grants nothing, so a configuration mistake degrades to Free rather than handing
out free premium access.

### Configuration

Every identifier comes from the environment. No key, product, or price is stored in this repository.

| Variable | Purpose |
| -------- | ------- |
| `STRIPE_SECRET_KEY` | Stripe API key. Absent means billing reports "not configured". |
| `STRIPE_WEBHOOK_SECRET` | Verifies webhook signatures. Absent means the webhook returns `503`. |
| `STRIPE_PRICE_CREATOR_MONTHLY` | Price ID backing `creator_monthly` |
| `STRIPE_PRICE_PRO_MONTHLY` | Price ID backing `pro_monthly` |
| `STRIPE_PRICE_CREATOR_ANNUAL` | Price ID backing `creator_annual` |
| `FRONTEND_URL` | Absolute frontend origin used for success/cancel redirects |

Internal plan id → Price ID mapping is built at startup by `refresh_price_mapping()` and is the only
place a plan becomes purchasable.

### Endpoints

| Endpoint | Auth | Purpose |
| -------- | ---- | ------- |
| `POST /api/billing/checkout` | Bearer | Create a Checkout session for a plan id |
| `POST /api/billing/portal` | Bearer | Open the Customer Portal for an existing subscriber |
| `POST /api/billing/webhook` | Stripe signature | Receive subscription lifecycle events |

### Webhook events

| Event | Effect |
| ----- | ------ |
| `checkout.session.completed` | Records the Stripe customer id on the account. **Grants no entitlement.** |
| `customer.subscription.created` | Grants the plan mapped to the subscription's price |
| `customer.subscription.updated` | Re-evaluates plan and status |
| `customer.subscription.deleted` | Returns the account to Free |
| `customer.subscription.paused` / `resumed` | Re-evaluates status |
| `invoice.paid` | Restores access after a lapse |
| `invoice.payment_failed` | Removes paid access on a failed renewal |

Unknown event types are acknowledged (`200`) and ignored, so Stripe stops retrying them.

**Idempotency:** every event id is recorded in `stripe_events` before processing. A redelivery is
acknowledged with `{"duplicate": true}` and not applied twice.

**Cancellation keeps the account.** When a subscription ends the account reverts to Free
entitlements, but the user row, sessions, and usage history are preserved. Only the entitlement
changes.

### Dashboard setup you must perform

1. Create three recurring **Prices** ($19/mo, $39/mo, $190/yr) and copy each `price_…` ID into the
   matching `STRIPE_PRICE_*` variable.
2. Copy the **restricted** API key into `STRIPE_SECRET_KEY`.
3. In **Developers → Webhooks**, add an endpoint at `https://<your-api-domain>/api/billing/webhook`
   subscribed to the events listed above, and copy its signing secret into `STRIPE_WEBHOOK_SECRET`.
4. Enable and configure the **Customer Portal** so subscribers can manage or cancel.
5. Set `FRONTEND_URL` to your real frontend origin.

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

The suite covers authentication, the plan catalogue, allowance accounting (including concurrency
and no-charge-on-failure), the transcription gate, Stripe checkout and webhooks, and the
no-database fallback. It runs the real Alembic migrations against a temporary SQLite database, so no
PostgreSQL server and no Stripe account are needed. WhisperX is mocked for accounting tests; a real
`ffprobe` call is made so duration measurement is genuinely exercised.

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
# REQUIRED
DATABASE_URL=${{Postgres.DATABASE_URL}}

# STRIPE REQUIRED (only for live billing; the service runs without them)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_CREATOR_MONTHLY=price_...
STRIPE_PRICE_PRO_MONTHLY=price_...
STRIPE_PRICE_CREATOR_ANNUAL=price_...

# RECOMMENDED
FRONTEND_URL=https://<your-frontend-custom-domain>
CORS_ORIGINS=https://<your-frontend-custom-domain>
WHISPERX_MODEL=small
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
MAX_UPLOAD_MB=500
SESSION_TTL_DAYS=30
```

`DATABASE_URL` must be present or the account endpoints return `503`. Transcription is also gated
behind an account, so it also requires the database.

Set `CORS_ORIGINS` to the deployed Captionline frontend origin. `*` is accepted for initial
testing but should not be used in production.

**Image size warning:** the CPU torch wheel plus the rest of the dependency tree produces an image
of roughly **4-6 GB**. A CUDA-based image is considerably larger still. This is the main practical
cost of running WhisperX on Railway, and it is worth measuring before relying on it.

### Deployment order

1. Apply migrations (the image does this on start, or run `alembic upgrade head` manually).
2. Deploy the API. Health should report `database.status: ok`.
3. Deploy the web app with `VITE_API_URL` pointing at the API origin.
4. Configure `CORS_ORIGINS` and `FRONTEND_URL` on the API to the web origin.
5. Add the Stripe variables and the webhook endpoint.

Migrations are additive in this release (`0002` adds a column and two tables), so rolling forward
does not require downtime.

### Rollback

- **Application rollback** is safe: revert the image. `0002` is additive, so the previous release
  keeps working against the migrated schema.
- **Schema rollback** (`alembic downgrade -1`) drops `subscription_price_id`,
  `usage_reservations`, and `stripe_events`. That discards in-flight usage holds and the webhook
  idempotency log, so do not downgrade while requests are being billed.

### Custom domain readiness

Nothing in the code depends on a Railway hostname. The three places a domain appears are all
environment driven:

| Purpose | Variable |
| ------- | -------- |
| Frontend calls the API | `VITE_API_URL` (web service) |
| API allows the browser | `CORS_ORIGINS` (API service) |
| Stripe redirect target | `FRONTEND_URL` (API service) |

In Railway, attach the custom domain to both the web service and the API service, then set
`CORS_ORIGINS` and `FRONTEND_URL` to that origin and rebuild the web app. Add the webhook endpoint
using the API's custom domain so the signature secret stays valid regardless of hostname changes.

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
│       ├── 0001_initial_accounts.py
│       └── 0002_billing_and_usage.py
├── alembic.ini                    # No connection string stored here
├── app/
│   ├── __init__.py
│   ├── config.py                  # Env-driven settings
│   ├── main.py                    # FastAPI app, CORS, health, transcribe gate
│   ├── schemas.py                 # Transcription, health, and Stripe health models
│   ├── plans.py                   # Plan catalogue (single source of truth)
│   ├── usage.py                   # Periods, reservations, allowance, snapshot
│   ├── media.py                   # ffprobe duration measurement + billing seconds
│   ├── transcribe.py              # WhisperX lifecycle + normalization
│   ├── stripe_client.py           # Stripe client, checkout, signature verification
│   ├── db/
│   │   ├── base.py                # Declarative base
│   │   ├── models.py              # User, Session, UsageReservation, StripeEvent
│   │   └── session.py             # Engine, session, DATABASE_URL handling
│   ├── routers/
│   │   ├── auth.py                # register, login, me, logout
│   │   ├── account.py             # entitlement, plans
│   │   └── billing.py             # checkout, portal, webhook
│   └── security/
│       ├── passwords.py           # Argon2id
│       ├── tokens.py              # Opaque token generation + hashing
│       ├── deps.py                # get_current_user, get_optional_user
│       ├── sessions.py            # Expired session cleanup
│       └── schemas.py             # Auth, entitlement, plan, checkout models
├── tests/                         # pytest suite
├── requirements.txt
├── requirements.lock.txt
├── pytest.ini
├── Dockerfile
├── .env.example
└── .dockerignore
```

---

## Known limitations

- **Long uploads and timeouts.** Transcription is synchronous. A long video on CPU can take far
  longer than a typical 60-second proxy timeout, so Railway will need either a longer timeout or a
  background-job design.
- **One transcription at a time per process.** WhisperX model inference is guarded by a lock, so
  concurrent requests queue. Multiple replicas would scale this out.
- **No email verification or password reset.** Deliberately out of scope.
- **Session tokens live in `localStorage`.** Acceptable now given the cross-origin setup; see the
  authentication tradeoff note. Attaching the custom domain would unblock httpOnly cookies.
- **Finished-video rendering does not exist.** `can_export` is granted as an *entitlement* only. The
  UI states plainly that rendering is not switched on; nothing is faked.
- **Usage holds live in PostgreSQL, not in memory**, so a restart mid-transcription does not leak a
  hold. The TTL reclaim is a backstop, not the primary mechanism.
- **`torchcodec` warning on Windows.** pyannote warns that built-in audio decoding is unavailable
  because `libtorchcodec` DLLs are missing. WhisperX passes audio in memory, so decoding still
  works, but the warning appears in the logs.
- **No diarization or translation.** Deliberately out of scope.
