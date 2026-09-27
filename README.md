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

- **Accounts** — sign up, log in, log out, change password, and a lightweight account panel with plan and usage
  (for example `3.2 / 10 minutes used`).
- **Password recovery** — a "Forgot password?" flow that emails a single-use reset link, plus
  change-password while signed in. Reset tokens are stored hashed, expire, are single-use, and
  revoke every session when redeemed.
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
- **Account deletion** — a `Delete my account` control in the account panel, behind the current
  password and a typed confirmation word. An active subscription must be canceled through the Stripe
  portal first, so the deletion blocks with `409` rather than silently ending a subscription
  server-side.
- **Published legal pages** — `/terms`, `/privacy`, and `/contact` at real routes, with the
  recorded Terms and Privacy versions and effective dates served from `GET /api/legal/versions`
  rather than hardcoded in the frontend.
- **Security posture** — security response headers on every response, request rate limiting on the
  sensitive and metered endpoints, and a production configuration gate. See
  [Security posture](#security-posture).

**Finished-video rendering still does not exist.** Paid plans carry the export *entitlement*; the
button stays disabled and says so plainly. Nothing is faked. Transcription **is** gated by login
now, so an upload requires an account and a signed-out visitor is asked to create one.

## What is NOT implemented yet

Nothing below exists yet, by design:

- No finished-video rendering (paid plans carry the entitlement only)
- No email verification of new addresses
- No social/OAuth login
- No Google Drive or other cloud storage integration
- No permanent media storage (uploads live in a per-request temporary directory and are deleted when
  processing ends)
- No speaker diarization, no translation, no analytics
- No background job queue, so very long videos on CPU may exceed a proxy timeout
- No published refund policy, and no published governing law or support address. The Terms say so
  plainly rather than naming one, so they must be settled before paid subscriptions are offered

## Security posture

Added after the first commercial pass, and described in full in
[`backend/README.md`](backend/README.md).

- **Security response headers** on every response (`app/headers.py`): `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, a deny-by-default
  `Content-Security-Policy`, and `Strict-Transport-Security` over HTTPS only. Endpoints that return
  a token or a password-reset outcome also send `Cache-Control: no-store`.
- **Rate limiting** (`app/ratelimit.py`) on registration, login, transcription, checkout, portal,
  change-password, reset-password, forgot-password, and account deletion. Each limit is applied per
  client address *and* per account, so rotating addresses does not defeat it. The unauthenticated
  buckets also keep a shared counter in the database, so the budget is fleet-wide rather than per
  replica. The client address comes from the socket peer unless `TRUST_PROXY_HEADERS` is explicitly
  enabled, because `X-Forwarded-For` is otherwise client-controlled.
- **`APP_ENV`** is the switch for the production configuration gate. It defaults to `development`,
  and **production must set it to `production`**, or the gate below never runs.
- **The production gate** (`assert_production_ready`) refuses to start at all when `APP_ENV` is
  `production` and the configuration is unsafe: a wildcard `CORS_ORIGINS`, the `console` or
  `memory` email provider (which print reset tokens to the log), `DATABASE_ECHO` (which logs
  password and token hashes as SQL bind parameters), an `FRONTEND_URL` that is empty, not
  `https://`, or localhost, or Stripe set with a non-https `FRONTEND_URL`, or `resend` with no
  `EMAIL_API_KEY`. Failing at startup is far cheaper than finding out during an incident.
- **Temp-file sweeping.** Each request deletes its own working directory in a `finally` block, so
  the normal and failure paths both clean up. If the process is killed outright the `finally`
  cannot run, so a startup sweep deletes any leftover `captionline-*` directory older than
  `TEMP_SWEEP_MAX_AGE_SECONDS` (24 hours by default). That is the real bound on how long an
  uploaded file can survive an abnormal termination, and the Privacy Policy says exactly that
  rather than claiming deletion is immediate.

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

### Password recovery

`POST /api/auth/forgot-password` always returns one fixed message, whether the address is unknown,
inactive, rate limited, or the mail provider is unconfigured — so account existence cannot be probed.

The emailed link points at `/reset-password?token=…` on `FRONTEND_URL`. Only a SHA-256 hash of the
token is stored, it expires after `PASSWORD_RESET_TTL_MINUTES` (default 60), and redeeming it takes
a row lock so it cannot be used twice. Every rejection returns the same message, so a token cannot
be probed for validity or prior use. A successful reset **revokes every login session**, on the
assumption that a reset is a response to a suspected compromise.

Abuse is limited twice: a durable per-account cooldown and outstanding-token cap, plus an in-process
per-client-address throttle applied before any database work. A throttled request still returns the
generic `200`, so the throttle is not observable either.

`console` and `memory` email providers are development and test only, and are reachable solely by
naming them explicitly in `EMAIL_PROVIDER` — a production deployment cannot print reset links to
the log stream.

> Because the reset link is a real path, the Railway web service needs an SPA rewrite so
> `/reset-password` serves `index.html` on a direct load. The Vite dev server already does this.

### Frontend routes and session storage

Captionline has no router dependency, so `src/auth/route.ts` adds just enough History API support
for the paths that must survive a full page load — an emailed link, a bookmark, or a hard refresh:

| Route | Page | Notes |
| ----- | ---- | ----- |
| `/reset-password` | `ResetPasswordPage` | The emailed link target. Must be a real route |
| `/terms` | `TermsPage` | Terms of Service, with the recorded version and effective date |
| `/privacy` | `PrivacyPage` | Privacy Policy, same |
| `/contact` | `ContactPage` | Support contact. Not a versioned document, so it shows no version line |

`VITE_SUPPORT_EMAIL` and `VITE_GOVERNING_LAW` are the only frontend values the legal pages read,
and both are optional: unset, the pages say support is not yet available and that the governing law
is not published yet, rather than inventing an address or a jurisdiction. Both must be set, and the
SPA rewrite above must be in place, before launch.

**Session storage: deferred, deliberately.** The session is still an opaque bearer token kept in
`localStorage` under `captionline.session.token` and sent as `Authorization: Bearer`. httpOnly
`SameSite=None; Secure` cookies plus CSRF protection is the real hardening, and it is **explicitly
deferred rather than overlooked**: `SameSite=None` cookies are rejected on cross-site requests, so
the migration only becomes possible once the custom domain is attached to both services, and the
cross-site cookie + CSRF work is a large change to every authenticated endpoint. Making that change
immediately before launch would be a much larger risk than the exposure it removes, on a codebase
with no integration tests for a cookie flow. It is a documented follow-up, gated on the domain being
attached — not an oversight. See the authentication tradeoff note above.

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
├── .env.example                # VITE_API_URL, VITE_SUPPORT_EMAIL, VITE_GOVERNING_LAW
├── .env.local                  # local overrides (git-ignored)
├── README.md
├── public/
│   └── _redirects              # SPA rewrite for Netlify-style hosts
├── backend/                    # Phases 2-3 service
│   ├── alembic/                # Migration environment + revisions
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py             # FastAPI app, CORS, health, transcribe gate, lifespan checks
│   │   ├── config.py           # Env-driven settings
│   │   ├── headers.py          # Security response headers
│   │   ├── ratelimit.py        # In-process + durable request budgets
│   │   ├── email.py            # Transactional email provider abstraction
│   │   ├── terms.py            # Legal versions, support mailbox, governing-law placeholder
│   │   ├── schemas.py          # Response models
│   │   ├── transcribe.py       # WhisperX lifecycle + output normalization
│   │   ├── plans.py            # Plan catalogue (single source of truth)
│   │   ├── usage.py            # Periods, reservations, allowance, snapshot
│   │   ├── media.py            # ffprobe duration measurement
│   │   ├── stripe_client.py    # Stripe client, checkout, signature verification
│   │   ├── db/                 # SQLAlchemy base, models, session
│   │   ├── routers/            # auth.py, password_reset.py, account.py, billing.py
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
    ├── vite-env.d.ts             # VITE_* typing
    ├── auth/
    │   ├── AuthContext.tsx       # Session state + resolved entitlement
    │   ├── AccountPanel.tsx      # Sign up / log in / usage / delete account
    │   ├── ForgotPasswordForm.tsx
    │   ├── ResetPasswordPage.tsx # /reset-password, the emailed-link target
    │   └── route.ts              # History API routing for the real-path routes
    ├── data/
    │   ├── sampleCaptions.ts     # Local fallback caption track
    │   ├── captionFonts.ts       # Font id -> CSS stack registry
    │   └── captionPresets.ts     # One-click CaptionStyle presets
    ├── legal/
    │   ├── config.ts             # VITE_SUPPORT_EMAIL / VITE_GOVERNING_LAW, and the safe fallbacks
    │   ├── LegalPage.tsx         # Shared document shell (version line, TOC)
    │   ├── TermsPage.tsx         # /terms
    │   ├── PrivacyPage.tsx       # /privacy
    │   └── ContactPage.tsx       # /contact
    ├── lib/
    │   ├── api.ts                # Transcription client + response -> cue mapping
    │   ├── auth.ts               # Account API client + token storage
    │   ├── billing.ts            # Plan catalogue, checkout, portal
    │   ├── legal.ts              # GET /api/legal/versions reader
    │   ├── srt.ts                # .srt generation + client-side download
    │   ├── color.ts              # Hex validation / alpha conversion
    │   ├── text.ts               # Greedy caption line/word wrapping
    │   └── time.ts               # Timecode / percentage helpers
    └── components/
        ├── Nav.tsx
        ├── Hero.tsx
        ├── UploadZone.tsx        # Click-to-select + drag/drop + video validation
        ├── HowItWorks.tsx
        ├── Pricing.tsx           # Real plan catalogue, no hardcoded prices
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
cd backend
pytest
```

`backend/pytest.ini` sets `pythonpath = .`, so the suite also runs from the repository root without
changing anything else:

```bash
backend\.venv\Scripts\python.exe -m pytest backend\tests
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
| `VITE_SUPPORT_EMAIL` | Monitored support address published on `/contact` and the legal pages. Unset means the pages say support is not yet available |
| `VITE_GOVERNING_LAW` | The law and forum the Terms are governed by. Unset means the Terms say the clause is not published yet |

Only `VITE_`-prefixed variables reach the browser bundle, so no secret ever belongs in this file.
None of the three is a secret: all three are printed on a public page.

### Backend

`backend/.env.example` is the complete list — every variable the service reads, with its safe
default and whether it is a secret. The most important one is not obvious from a variable name:

| Variable | Purpose |
| -------- | ------- |
| `APP_ENV` | **Production must set this to `production`.** Any other value (it defaults to `development`) means the production configuration gate never runs. See [Security posture](#security-posture) |
| `DATABASE_URL` | PostgreSQL in production (`${{Postgres.DATABASE_URL}}`), optional locally |
| `EMAIL_PROVIDER` | `resend` in production; `console`/`memory` are dev and test only |
| `EMAIL_API_KEY` | Resend API key. Server side only |
| `EMAIL_FROM` | Verified sender, e.g. `Captionline <no-reply@captionline.pro>` |
| `SUPPORT_EMAIL` | Monitored support mailbox, reported by `GET /api/legal/versions`. Keep aligned with `VITE_SUPPORT_EMAIL` |
| `PASSWORD_RESET_TTL_MINUTES` | Reset link lifetime (default 60) |
| `PASSWORD_RESET_COOLDOWN_SECONDS` | Per-account cooldown between reset requests |
| `PASSWORD_RESET_MAX_ACTIVE` | Cap on outstanding reset tokens per account |
| `PASSWORD_RESET_IP_LIMIT` | Per-address throttle on forgot-password (default 5/900s) |
| `RATE_LIMIT_*` | Per-endpoint limits and windows: register, login, transcribe, checkout, portal, change-password, reset-password, delete-account. Plus `RATE_LIMIT_MAX_KEYS`, `RATE_LIMIT_DURABLE_ENABLED`, and `RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS` |
| `TRUST_PROXY_HEADERS` | Whether `X-Forwarded-For` may be used for rate-limit keys. Only enable behind a proxy that overwrites it |
| `HSTS_ENABLED` | Force HSTS on/off. Unset means "only over HTTPS" |
| `TEMP_SWEEP_MAX_AGE_SECONDS` | Age at which a work directory left by a killed request is swept at startup (default 86400) |
| `STRIPE_SECRET_KEY` | Stripe API key. Absent means billing reports "not configured" |
| `STRIPE_WEBHOOK_SECRET` | Verifies webhook signatures |
| `STRIPE_PRICE_CREATOR_MONTHLY` | Price ID for Creator |
| `STRIPE_PRICE_PRO_MONTHLY` | Price ID for Pro |
| `STRIPE_PRICE_CREATOR_ANNUAL` | Price ID for Creator Annual |
| `FRONTEND_URL` | Absolute frontend origin for Stripe redirects and reset links |
| `SESSION_TTL_DAYS` | Bearer session lifetime |
| `MIN_PASSWORD_LENGTH` | Minimum registration password length |
| `WHISPERX_MODEL` | Transcription model |
| `WHISPERX_DEVICE` | `auto` (CUDA when available) or `cpu` |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `MAX_UPLOAD_MB` | Upload size limit |
| `FFPROBE_PATH` | `ffprobe` location, used to measure real duration |
| `PORT` | Supplied by Railway |

These must **not** be prefixed with `VITE_`. The four secrets in the system are **`DATABASE_URL`,
`EMAIL_API_KEY`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET`**, and nothing else: the WhisperX
models are public, and every other setting is a non-sensitive deployment value. The platform
supplies them; none is ever committed.

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

# REQUIRED FOR PRODUCTION - without it the startup safety gate never runs
APP_ENV=production

# STRIPE REQUIRED (for live billing; the service runs without them)
STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=...
STRIPE_PRICE_CREATOR_MONTHLY=...
STRIPE_PRICE_PRO_MONTHLY=...
STRIPE_PRICE_CREATOR_ANNUAL=...

# RECOMMENDED
FRONTEND_URL=https://<your-frontend-domain>
CORS_ORIGINS=https://<your-frontend-domain>
EMAIL_PROVIDER=resend
EMAIL_API_KEY=...
SUPPORT_EMAIL=...
WHISPERX_MODEL=small
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
MAX_UPLOAD_MB=500
SESSION_TTL_DAYS=30
```

Then set `VITE_API_URL` on the frontend to the Railway backend URL and rebuild the frontend, and set
`VITE_SUPPORT_EMAIL` and `VITE_GOVERNING_LAW` before offering paid subscriptions. No source change is
needed to switch environments.

**Deployment order:** migrations → API → web (`VITE_API_URL`) → `CORS_ORIGINS`/`FRONTEND_URL` →
`APP_ENV=production` → Stripe variables and webhook. Set `APP_ENV` **after** the variables it checks
(`CORS_ORIGINS`, `FRONTEND_URL`, `EMAIL_*`), because setting it earlier makes the service refuse to
boot until they are correct.

**Migration safety:** the schema is only ever changed by a reviewed Alembic revision. `create_all`
is never used against a live database, so a deploy cannot silently reshape a table. `0002` is purely
additive (one column, two tables) and `0003`–`0005` are additive too: `0003` adds the password-reset
table, `0004` adds four **nullable** consent columns with no backfill, and `0005` adds the
rate-limit bucket table. An application rollback therefore stays safe against a migrated schema; a
schema rollback would discard in-flight usage holds, password-reset tokens, recorded legal
consents, and the webhook idempotency log.

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
