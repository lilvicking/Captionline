# Captionline

Captionline is a focused video-captioning SaaS. The product workflow is:

**Upload video → process/transcribe → edit timed captions → style captions → export captions/video**

Phase 1 is the frontend foundation. **Phase 2 adds real transcription** through a Python
WhisperX service. **Phase 3A adds accounts, plans, and usage tracking** on PostgreSQL.
**Phase 3B adds the commercial foundation**: metered processing, server-authoritative entitlement,
and Stripe subscriptions.

---

## What Phase 1 does

Phase 1 is a browser-only build that establishes the entire user-facing workflow and the component
architecture that later backend phases plug into.

- **Landing page** — wordmark, navigation, hero, drag-and-drop upload area, a three-step
  "How it works" section, and a pricing placeholder.
- **Local video selection** — click-to-select or drag-and-drop. The file is validated to be a video
  and read locally via `URL.createObjectURL`.
- **Processing state** — shows the transcription progress and reports clearly when the service is
  unavailable.
- **Caption editor** — real local video preview with a caption overlay, a list of timed captions
  that can be selected, edited, added, and deleted, plus a clickable timeline with a playhead and a
  scrubber.
- **Caption designer** — a full caption style panel with one-click presets (Clean, Bold, Creator,
  Minimal, Boxed, Karaoke) covering font family, size, weight, text colour, alignment, uppercase,
  letter spacing, word spacing, line height, background colour/opacity/padding/corner radius, text
  outline, outline colour and thickness, text shadow, vertical position, maximum width, and
  characters per line. Every control updates the preview immediately.
- **Karaoke word highlighting** — when the Karaoke preset is active and the caption came back with
  word timings, the word spanning `video.currentTime` is highlighted in real time.
- **Free-tier preview protection** — unpaid users get the first 30 seconds of the finished video
  preview. Playback stops at the boundary, seeking past it is refused, and a locked state covers the
  preview. Editing is never restricted.
- **SRT export** — working client-side `.srt` generation and download from the current caption data.

## What Phase 2 adds

- **`backend/`** — a small FastAPI service that transcribes an uploaded video or audio file with
  **WhisperX** and returns **word-level timestamps** in Captionline's own JSON format.
- The upload flow now calls `POST /api/transcribe`. Real captions replace the sample data when the
  service responds; if it is unreachable, the editor still opens with sample captions.
- Captions keep their word timings, which is what the karaoke preset highlights.

See [`backend/README.md`](backend/README.md) for the full service documentation, model
configuration, and Railway deployment.

## What Phase 3A adds

- **Accounts** — sign up, log in, log out, and a lightweight account panel with plan and usage
  (for example `3.2 / 10 minutes used`).
- **PostgreSQL** — SQLAlchemy 2.0 with Alembic migrations against the Railway Postgres service via
  `DATABASE_URL`.
- **Server-authoritative plans and usage** — the free plan (10 processing minutes per month, 30
  second preview, no export) is defined once on the backend and served from
  `GET /api/account/entitlement`.
- **Secure sessions** — Argon2id password hashing and opaque bearer tokens stored hashed, with
  working logout invalidation.

The preview limit is now read from the signed-in account when one exists, and always falls back to
the local 30-second free tier.

## What Phase 3B adds

- **Metered transcription** — uploading requires an account, and each file is charged its real
  measured duration. The backend measures duration itself with `ffprobe`, so a client cannot
  declare its own length.
- **Allowance enforcement** — a request that would exceed the remaining allowance is refused with
  `402` *before* WhisperX spends any compute, with a message stating exactly what is left and what
  the file needs.
- **Charge only for success** — allowance is reserved before processing and converted to real usage
  only if transcription succeeds. Failed, rejected, and unreadable uploads cost nothing.
- **Concurrency protection** — a row-level lock makes two simultaneous requests unable to spend the
  same remaining allowance.
- **Stripe subscriptions** — Checkout and the Customer Portal, with signature-verified webhooks as
  the only source of paid entitlement.
- **Real pricing** — Free, Creator ($19), Pro ($39), and Creator Annual ($149, billed annually),
  served from the backend catalogue so the frontend never hardcodes prices.

**Finished-video rendering still does not exist.** Paid plans carry the export *entitlement*; the
button stays disabled and says so plainly. Nothing is faked. Transcription is **not** gated by login yet, so the existing upload
flow keeps working.

## What is NOT implemented yet

Nothing below exists yet, by design:

- No finished-video rendering (paid plans carry the entitlement only)
- No email verification or password reset
- No social/OAuth login
- No Google Drive or other cloud storage integration
- No permanent media storage (uploads are temporary and deleted immediately)
- No speaker diarization, no translation, no analytics
- No background job queue, so very long videos on CPU may exceed a proxy timeout
- No final pricing. Plan names are placeholders and no prices are published.

## Authentication architecture

Opaque bearer sessions rather than JWTs, because the web app and API are separate Railway origins
and because a real logout must invalidate a token immediately.

- Passwords are hashed with **Argon2id** (OWASP parameters) via `argon2-cffi`. Plaintext is never
  stored or logged.
- A 256-bit `secrets` token is issued on register/login. Only its SHA-256 hash is stored, so a
  database leak yields no usable credentials.
- `POST /api/auth/logout` revokes the session row, so the token stops working at once.
- Email enumeration is blocked: an unknown email and a wrong password return an identical `401`.

The token is kept in `localStorage` and sent as `Authorization: Bearer`. The hardening path, if
wanted later, is httpOnly `SameSite=None; Secure` cookies plus CSRF protection.

## Plan catalogue

Defined once in `backend/app/plans.py` and served to the frontend from `GET /api/account/plans`, so
prices are never duplicated or hardcoded in the UI.

| Plan | id | Price | Allowance | Usage reset | Billing | Full preview | Export |
| ---- | -- | ----- | --------- | ----------- | ------- | ------------ | ------ |
| Free | `free` | $0 | 600 s (10 min)/month | monthly | — | 30 s | no |
| Creator | `creator_monthly` | $19 | 30,000 s (500 min)/month | monthly | monthly | full | yes |
| Pro | `pro_monthly` | $39 | 90,000 s (1,500 min)/month | monthly | monthly | full | yes |
| Creator Annual | `creator_annual` | $149 | 30,000 s (500 min)/month | **monthly** | **annual** | full | yes |

**Billing cadence and usage cadence are separate.** Creator Annual is charged once a year by Stripe
but its 500-minute allowance still resets every month, the same as Creator Monthly — paying for a
year up front does not buy twelve months of processing at once, and **unused minutes do not roll
over**. It is simply the same allowance for $79 less per year ($19 × 12 = $228 versus $149).

The `PlanDefinition` model reflects this with `billing_period` (when Stripe charges) separate from
`usage_period_months` (when the allowance refreshes). Unknown plan ids fall back to Free, so a bad
value can never widen access.

## Processing accounting

Seconds are the unit of record; minutes are derived only for display. The **backend measures the
media itself** with `ffprobe` and bills `ceil(duration)`. A file whose duration cannot be measured
is rejected rather than transcribed, because unmetered transcription would be worse than a refusal.

Usage periods are the UTC calendar month for every plan — including the annually billed one — and
roll over lazily on read (`ensure_current_usage_period`) so no scheduled job is needed. A rollover
discards unused allowance and never touches the subscription status, so a paid customer keeps full
preview and export across every reset.

Nothing is charged for an upload that merely starts:

| Outcome | Allowance |
| ------- | --------- |
| Transcription succeeds | charged the measured duration |
| Transcription fails | released, nothing charged |
| Rejected (allowance, size, unreadable) | released, nothing charged |
| Process crashes | hold reclaimed after a TTL |

Allowance is checked and held in one transaction under a row-level lock, so two simultaneous
requests cannot spend the same remaining allowance. The lock is released before the expensive
WhisperX work, so a long transcription never holds a database lock.

## Authentication architecture

Opaque bearer sessions rather than JWTs, because the web app and API are separate origins and
because a real logout must invalidate a token immediately.

- Passwords are hashed with **Argon2id** (OWASP parameters) via `argon2-cffi`. Plaintext is never
  stored or logged.
- A 256-bit `secrets` token is issued on register/login. Only its SHA-256 hash is stored, so a
  database leak yields no usable credentials.
- `POST /api/auth/logout` revokes the session row, so the token stops working at once.
- Email enumeration is blocked: an unknown email and a wrong password return an identical `401`.
- Tokens are never logged, and expired/revoked rows are purged opportunistically.

The token is kept in `localStorage` and sent as `Authorization: Bearer`. The hardening path is
httpOnly `SameSite=None; Secure` cookies plus CSRF protection; attaching the custom domain
unblocks that, since `SameSite=None` is rejected across sites.

## Stripe architecture

**Stripe is the authority for paid access.** Creating a Checkout session changes nothing — a
browser returning from Stripe cannot grant access on its own. Entitlement changes only when a
**signature-verified webhook** is processed.

| Endpoint | Auth | Purpose |
| -------- | ---- | ------- |
| `POST /api/billing/checkout` | Bearer | Create a Checkout session for a plan id |
| `POST /api/billing/portal` | Bearer | Open the Customer Portal |
| `POST /api/billing/webhook` | Stripe signature | Subscription lifecycle events |

Handled events: `checkout.session.completed` (records the customer id only),
`customer.subscription.created/updated/deleted/paused/resumed`, `invoice.paid`,
`invoice.payment_failed`. Unknown events are acknowledged and ignored.

- **Idempotent** — every event id is recorded, so a redelivery is not applied twice.
- **Fails closed** — an unmapped Stripe Price ID grants no elevated access, and a
  `past_due`/`canceled`/`unpaid` status returns the account to Free.
- **Cancellation preserves data** — only entitlements change; the account and captions survive.

No key, product, or price is stored in this repository; every value comes from the environment.

### Stripe dashboard setup (manual)

1. Create three recurring Prices ($19/mo, $39/mo, $149/yr); copy each `price_…` ID.
2. Copy the restricted API key.
3. Add a webhook endpoint at `https://<your-api-domain>/api/billing/webhook` subscribed to the
   events above; copy its signing secret.
4. Enable the Customer Portal.
5. Point `FRONTEND_URL` at your real frontend origin.

## Preview entitlement (Phase 2)

`src/entitlement.ts` holds the whole preview policy in one typed place:

```ts
export const FREE_PREVIEW_SECONDS = 30;

export type PreviewEntitlement = {
  previewLimitSeconds: number | null; // null = unrestricted
  hasFullPreview: boolean;
  source: "free-tier" | "server";
};
```

`resolvePreviewEntitlement()` returns the free tier and is the value the app starts with.
`entitlementFromServer()` converts `GET /api/account/entitlement` into a preview entitlement, and
it **fails closed**: an unrestricted preview is only honoured when the server explicitly reports
`has_full_preview === true`. A missing, malformed, or unexpected payload collapses to the free
30-second window, so a bad response can never widen access. There is deliberately **no**
`isPaid = true` development flag that could be flipped and shipped by accident.

Unpaid users may transcribe, read, edit, restyle, and export captions for their entire project. The
limit applies only to the **finished video preview**:

- playback stops when it reaches the boundary
- seeking past the boundary is pulled back, so protected frames are never shown
- the browser's own video controls are covered by the same guard, because they drive the same
  `seeking` event

The timeline still represents the whole video and shades the protected region. Selecting a caption
past the boundary still selects and edits that caption; it simply does not move the protected
playhead there.

### This is still not a security boundary

The browser check is a UX gate. The backend independently enforces the paid preview decision, and
when Stripe is in place the backend is the authority. The client merely mirrors it and assumes the
more restrictive answer whenever it is unsure.

## Tech stack

- React 18 + TypeScript
- Vite 5
- lucide-react (icons)
- Hand-written CSS (no UI framework, no CSS-in-JS)
- Backend: Python 3.12, FastAPI, Uvicorn, WhisperX (faster-whisper + alignment)

## Project structure

```
.
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── .env.example                # VITE_API_URL for the frontend
├── .env.local                  # local overrides (git-ignored)
├── README.md
├── backend/                    # Phases 2-3 service
│   ├── alembic/                # Migration environment + revisions
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py             # FastAPI app, CORS, health, transcribe gate
│   │   ├── config.py           # Env-driven settings
│   │   ├── schemas.py          # Response models
│   │   ├── transcribe.py       # WhisperX lifecycle + output normalization
│   │   ├── plans.py            # Plan catalogue (single source of truth)
│   │   ├── usage.py            # Periods, reservations, allowance, snapshot
│   │   ├── media.py            # ffprobe duration measurement
│   │   ├── stripe_client.py    # Stripe client, checkout, signature verification
│   │   ├── db/                 # SQLAlchemy base, models, session
│   │   ├── routers/            # auth.py, account.py, billing.py
│   │   └── security/           # Argon2id, tokens, dependencies, sessions
│   ├── tests/                  # pytest suite
│   ├── requirements.txt
│   ├── requirements.lock.txt
│   ├── pytest.ini
│   ├── Dockerfile
│   └── README.md
└── src/
    ├── main.tsx                  # React entry point
    ├── App.tsx                   # Stage machine: landing -> processing -> editor
    ├── index.css                 # Design tokens and all styles
    ├── types.ts                  # CaptionCue, CaptionWord, the CaptionStyle model
    ├── entitlement.ts            # Preview entitlement policy + server bridge
    ├── vite-env.d.ts             # VITE_API_URL typing
    ├── auth/
    │   ├── AuthContext.tsx       # Session state + resolved entitlement
    │   └── AccountPanel.tsx      # Sign up / log in / usage
    ├── data/
    │   ├── sampleCaptions.ts     # Local fallback caption track
    │   ├── captionFonts.ts       # Font id -> CSS stack registry
    │   └── captionPresets.ts     # One-click CaptionStyle presets
    ├── lib/
    │   ├── api.ts                # Transcription client + response -> cue mapping
    │   ├── auth.ts               # Account API client + token storage
    │   ├── billing.ts            # Plan catalogue, checkout, portal
    │   ├── srt.ts                # .srt generation + client-side download
    │   ├── color.ts              # Hex validation / alpha conversion
    │   ├── text.ts               # Greedy caption line/word wrapping
    │   └── time.ts               # Timecode / percentage helpers
    └── components/
        ├── Nav.tsx
        ├── Hero.tsx
        ├── UploadZone.tsx        # Click-to-select + drag/drop + video validation
        ├── HowItWorks.tsx
        ├── Pricing.tsx           # Placeholder only, no prices
        ├── Footer.tsx
        ├── ProcessingState.tsx   # Real transcription progress + fallback notice
        └── editor/
            ├── Editor.tsx       # Editor composition, cue state, style state
            ├── CaptionDesigner.tsx  # Presets + Text/Appearance/Position/Layout
            ├── VideoStage.tsx    # Local video, caption overlay, drag positioning, karaoke, preview gate
            ├── PreviewLock.tsx   # Free-tier locked preview state
            ├── CaptionTrack.tsx  # Editable caption list
            ├── Timeline.tsx      # Progress visual + scrubbing + protected region
            ├── ExportPanel.tsx   # SRT export + disabled video export
            └── controls/
                └── CaptionControls.tsx  # Range, colour, toggle, select, segmented
```

The `CaptionCue` model (`{ id, start, end, text }`) is the contract a future transcription service
will return, so the editor wiring does not need to change when real transcription is connected.

### CaptionStyle and the future renderer

All caption styling lives in one typed `CaptionStyle` object (`src/types.ts`) rather than being
scattered across components. The video preview consumes that object directly, and its values are
designed to be handed to a rendering backend unchanged:

- Every pixel value (`fontSize`, `backgroundPadding`, `backgroundRadius`, `outlineWidth`) is
  expressed against a **1080px-tall reference frame** (`CAPTION_STYLE_REFERENCE_HEIGHT`). The preview
  scales them to the rendered stage height, which is the same arithmetic a renderer performs.
- Colours are plain hex strings plus a separate `backgroundOpacity` value, so a backend can compose
  them as it needs.
- `verticalPosition` is a single percentage from the top edge. The Top / Middle / Bottom buttons are
  derived from it, so the slider and the quick presets can never disagree.
- `maxCharsPerLine` uses the same greedy word-wrap rule as the preview
  (`src/lib/text.ts`), including hard-splitting of over-long words.
- `wordHighlight` drives karaoke. The active word is whichever word timestamp contains
  `video.currentTime`, so highlighting follows the real alignment rather than a guessed timeline.
- `letterSpacing` (between characters) and `wordSpacing` (between words) are independent `em` values.
  Both are purely visual: caption text, transcription data, and `.srt` output are never modified.

## Install

Frontend requires Node.js 18 or newer.

```bash
npm install
```

## Run the frontend locally

```bash
npm run dev
```

Then open the printed local URL (default <http://localhost:5173>).

The frontend reads the backend location from `VITE_API_URL`:

```bash
cp .env.example .env.local
```

`VITE_API_URL=http://localhost:8000` is the default, so no local configuration is required.

## Run the backend locally

Requires **Python 3.12** and `ffmpeg` on `PATH`.

```bash
cd backend
python3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows
source .venv/bin/activate           # macOS / Linux

pip install -r requirements.txt
```

### Database

`DATABASE_URL` is the only database setting, and it is optional. Without it the service still starts
and transcribes, `/api/health` reports `database.status = "not_configured"`, and the account
endpoints return `503` — so transcription-only local work is unaffected.

```bash
# Local PostgreSQL
export DATABASE_URL=postgresql://captionline:<your-local-password>@localhost:5432/captionline

# Local without PostgreSQL (development and tests only)
export DATABASE_URL=sqlite:///./captionline.db
```

`postgres://` and `postgresql://` are both accepted and normalised automatically.

Apply migrations and run:

```bash
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Check it:

```bash
curl http://localhost:8000/api/health
```

Run the backend tests (they use the real migration against a temporary SQLite database, so no
PostgreSQL server is needed):

```bash
pytest
```

Full backend documentation, model configuration, and Railway deployment:
[`backend/README.md`](backend/README.md).

## Production build

```bash
npm run build
```

This runs the TypeScript check (`tsc --noEmit`) and then builds to `dist/`.

Preview the production build locally:

```bash
npm run preview
```

## Environment variables

### Frontend (Vite)

| Variable | Purpose |
| -------- | ------- |
| `VITE_API_URL` | Base URL of the transcription service. Production example: `https://<backend>.up.railway.app` |

Only `VITE_`-prefixed variables reach the browser bundle, so no secret ever belongs in this file.

### Backend

Server-side configuration lives in `backend/.env.example`:

| Variable | Purpose |
| -------- | ------- |
| `DATABASE_URL` | PostgreSQL in production (`${{Postgres.DATABASE_URL}}`), optional locally |
| `STRIPE_SECRET_KEY` | Stripe API key. Absent means billing reports "not configured" |
| `STRIPE_WEBHOOK_SECRET` | Verifies webhook signatures |
| `STRIPE_PRICE_CREATOR_MONTHLY` | Price ID for Creator |
| `STRIPE_PRICE_PRO_MONTHLY` | Price ID for Pro |
| `STRIPE_PRICE_CREATOR_ANNUAL` | Price ID for Creator Annual |
| `FRONTEND_URL` | Absolute frontend origin for Stripe redirects |
| `SESSION_TTL_DAYS` | Bearer session lifetime |
| `MIN_PASSWORD_LENGTH` | Minimum registration password length |
| `WHISPERX_MODEL` | Transcription model |
| `WHISPERX_DEVICE` | `auto` (CUDA when available) or `cpu` |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `MAX_UPLOAD_MB` | Upload size limit |
| `FFPROBE_PATH` | `ffprobe` location, used to measure real duration |
| `PORT` | Supplied by Railway |

These must **not** be prefixed with `VITE_`. `DATABASE_URL` and the Stripe values are the only
secrets, and the platform supplies them.

## Railway deployment

```
Captionline Web  →  Captionline API  →  PostgreSQL
```

The backend is Railway-ready: it binds `0.0.0.0`, reads `PORT`, uses temporary storage only, and
contains no Windows-specific behavior. `backend/Dockerfile` is a CPU image with `ffmpeg`, `libgomp1`,
and `libpq5` installed. Its start command applies migrations before serving:

```
alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Set on the Railway API service:

```
# REQUIRED
DATABASE_URL=${{Postgres.DATABASE_URL}}

# STRIPE REQUIRED (for live billing; the service runs without them)
STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=...
STRIPE_PRICE_CREATOR_MONTHLY=...
STRIPE_PRICE_PRO_MONTHLY=...
STRIPE_PRICE_CREATOR_ANNUAL=...

# RECOMMENDED
FRONTEND_URL=https://<your-frontend-domain>
CORS_ORIGINS=https://<your-frontend-domain>
WHISPERX_MODEL=small
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
MAX_UPLOAD_MB=500
SESSION_TTL_DAYS=30
```

Then set `VITE_API_URL` on the frontend to the Railway backend URL and rebuild the frontend. No
source change is needed to switch environments.

**Deployment order:** migrations → API → web (`VITE_API_URL`) → `CORS_ORIGINS`/`FRONTEND_URL` →
Stripe variables and webhook.

**Migration safety:** the schema is only ever changed by a reviewed Alembic revision. `create_all`
is never used against a live database, so a deploy cannot silently reshape a table. `0002` is purely
additive (one column, two tables), so an application rollback stays safe; a schema rollback would
discard in-flight usage holds and the webhook idempotency log.

**Custom domain:** nothing depends on a Railway hostname. Attach the domain to both services, set
`CORS_ORIGINS` and `FRONTEND_URL` to it, rebuild the web app, and register the webhook against the
API's custom domain. DNS is not touched by this repository.

**Not yet done:** nothing has been deployed from this branch, and no GPU infrastructure was
provisioned. See the size and timeout caveats in `backend/README.md`.

## Git

- Phase 1 lives on `phase-1-foundation` (committed as `542f718`).
- Phase 2 lives on `phase-2-transcription` (committed as `460a53a`).
- Phase 3A lives on `phase-3-accounts` (committed as `0a62286`).
- Phase 3B work is on `phase-3b-commercial`.
- `main` is untouched.
