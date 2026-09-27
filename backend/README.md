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

### `GET /api/auth/me`

Requires `Authorization: Bearer <token>`. Returns the authenticated user.

### `POST /api/auth/logout`

Revokes the presented session. The token stops working immediately.

### `POST /api/auth/forgot-password`

Body `{"email": "..."}`. Starts a password reset.

Always answers `200` with one fixed message, whether the address is unknown, the
account is inactive, the request is rate limited, or no email provider is
configured. Nothing about account existence can be inferred from the response.

### `POST /api/auth/reset-password`

Body `{"token": "...", "new_password": "..."}`. Redeems a reset token.

Every rejection — unknown, expired, already used, revoked — returns the same `400`
and the same message, so a token cannot be probed. On success the password is
rehashed with Argon2id, the token is consumed, every other outstanding token for
the account is revoked, and **all login sessions are revoked**.

### `POST /api/auth/change-password`

Requires a session. Body `{"current_password": "...", "new_password": "..."}`.
Verifies the current password, then revokes every session and outstanding reset
token. The caller is signed out too. Throttled by the `change-password` rate-limit
bucket.

### `POST /api/account/delete`

Requires a session. Body `{"current_password": "...", "confirmation": "DELETE"}`.
The confirmation must be the literal string `DELETE`, so deletion cannot happen
by accident.

| Status | Meaning |
| ------ | ------- |
| `200` | Deleted. Sessions are invalidated and the account record is removed |
| `400` | Missing or wrong confirmation word |
| `401` | No session, or the current password is wrong |
| `409` | An active subscription exists; cancel it through the portal first |
| `429` | Throttled by the `delete-account` rate-limit bucket |
| `500` | Generic failure. The transaction is rolled back, so nothing changed |

**The billing rule is block, not cancel.** An account with an active subscription and a Stripe
subscription id is refused with `409` and **no Stripe call is made**. Cancellation is already
portal-based (`POST /api/billing/portal`), so a server-side cancel would be a second, unspecified
path to the same state — and it can fail *after* the local commit, leaving two systems that cannot
be rolled back together. Making the customer open the portal is slower but it is one operation,
performed by the customer, with one outcome. An active status with **no** external id is treated as
a half-applied webhook and does not block, so one bad row cannot lock a customer out of deleting
their account.

Deletion is irreversible, so it has its own rate-limit bucket rather than sharing
`change-password`: a user who mistypes a new password five times must still be able to close their
account.

### `GET /api/legal/versions`

Public, no authentication, so `/terms` and `/privacy` can show the version a visitor is agreeing to
while signed out. The version strings live in `app/terms.py` and nowhere else, so the frontend can
never display a version that differs from the one recorded against an account.

```json
{
  "terms_version": "2026-09-27",
  "terms_effective_date": "2026-09-27",
  "privacy_version": "2026-09-27",
  "privacy_effective_date": "2026-09-27",
  "support_email": null,
  "support_email_configured": false,
  "governing_law": "[governing jurisdiction to be confirmed]"
}
```

`support_email` is `null` and `support_email_configured` is `false` until an operator sets
`SUPPORT_EMAIL`. `governing_law` is a deliberate **visible placeholder**: no jurisdiction has been
chosen, and printing a plausible-looking one would be a fabricated legal claim. Both must be resolved
before launch.

### `POST /api/export/video`

Renders the finished video. Requires a session, and the account's `can_export` entitlement —
which is `true` for **every** plan, Free included, so Free is never blocked.

Request is `multipart/form-data` with three parts: `video` (the source file), `captions` (JSON), and
`style` (JSON). The video is streamed to disk in chunks, never base64'd into JSON.

Returns the finished MP4 as a download, named `<original>-captioned.mp4`.

**Export does not consume processing allowance.** Transcription is charged once, by
`/api/transcribe`; re-rendering after a caption or style change is unlimited and free. This endpoint
never touches usage accounting.

| Status | Meaning |
| ------ | ------- |
| 200 | The MP4, as a download |
| 400 | No captions to render, empty video, or unreadable JSON |
| 401 | No valid session |
| 403 | The account is not entitled to export |
| 413 | Source or payload over the configured limit |
| 415 | The upload is not a video |
| 422 | Invalid captions/style, unreadable media, or a render failure |
| 429 | Another render is already running |
| 503 | FFmpeg or ffprobe is unavailable |
| 504 | The render exceeded its time budget |

### `GET /api/admin/summary`

Requires an administrator. Returns account counts for orientation: total, Free, paid, accounts
holding credit, and total outstanding credit seconds.

### `GET /api/admin/customer-options`

Requires an administrator. Returns `{options: [{id, email}], truncated, limit}` — only the two
fields a picker needs, so no plan, usage, entitlement, or billing data is exposed by a list endpoint.
Sorted case-insensitively, capped at 500, with `truncated: true` when the cap is reached so the UI
can fall back to search. Marked `Cache-Control: no-store`.

### `GET /api/admin/users?q=<email or id>`

Requires an administrator. Server-side search over email, or by numeric id, capped at 25 results, so
the console never downloads the customer table to filter it in the browser.

### `GET /api/admin/users/{id}`

Requires an administrator. Support view of one account: plan, subscription state, monthly
allowance, used, remaining, usage-period bounds, credit balance, effective remaining, preview and
export entitlements, and consent timestamps.

Deliberately absent, because each is either a credential or unnecessary: the password hash, session
and reset tokens, and any payment data. The response is assembled field by field, so passing the
model through cannot leak one, and a test asserts the forbidden key names are absent.

### `POST /api/admin/users/{id}/credits`

Requires an administrator. Body `{"minutes": 30, "reason": "Transcription issue"}`. A positive
value grants credit, a negative value corrects a previous grant. The reason is mandatory and the
adjustment is capped at 24 hours.

**An administrator may adjust their own account**, so the owner can grant themselves credit for
testing, production QA, internal usage, or demonstrations. This is intentional and does not weaken
the guard: `require_admin` still gates the route, so a normal user adjusting either themselves or
anyone else is still refused, and a self-adjustment is still reasoned, confirmed, and audited — the
audit row simply carries the same id in both the admin and target columns.

### `GET /api/admin/users/{id}/audit`

Requires an administrator. Recent administrative actions against one account, newest first.

---

## Administrative support console

For owner administration, customer support, and goodwill processing credit.

### Authorization

Access is decided on the server, from the durable `users.is_admin` column, enforced by
`require_admin` on **every** admin route. That column is only ever written by applying the
`ADMIN_EMAILS` allow-list at startup, so there is no client-controlled path to it. It is never
inferred from a paid plan or an email domain, and no endpoint exists that a signed-in user can call
to change it.

### Bootstrap

`ADMIN_EMAILS` is a comma-separated allow-list, applied on startup:

| Value | Effect |
| ----- | ------ |
| unset or empty | **No change.** Nobody is made an administrator, so an unconfigured deployment cannot expose the console, and an existing administrator is never locked out by a typo. |
| set | Authoritative. Listed accounts gain administrator access; every other account loses it. |

Revoking the last administrator means pointing the variable at an address no account uses and
redeploying. The frontend only decides whether to draw an "Admin" link, inside the Account sheet; a
non-administrator who navigates to `/admin` directly gets whatever the server says.

### Deliberately not built

Each of these turns routine support into account takeover, so none exists:

* reading a customer's password hash, session token, or reset token
* setting a customer's password
* impersonating a customer or logging in as one
* spoofing a Stripe plan to grant processing time

### Processing credit

Support grants extra processing time through `users.bonus_processing_seconds`, an **addition** to
the plan allowance that is never a replacement for it.

| Rule | Behaviour |
| ---- | --------- |
| Consumption order | The monthly plan allowance is spent first; credit is used only for the excess. |
| `processing_used_seconds` | Never inflated past the plan allowance to represent credit usage, so the monthly figure keeps meaning "of your plan allowance". |
| Monthly reset | Restores the plan allowance. Credit is not part of the monthly cycle and persists until consumed. |
| Failed transcription | The hold is released, so a failure never burns credit. |
| Concurrency | Holds are taken off the *combined* balance under the same row lock as before, so two simultaneous requests cannot overspend plan plus credit. |
| Corrections | A separate audit row, never a rewrite. The balance is never allowed below zero. |

### Audit log

Every administrative mutation writes a row to `admin_audit_log` in PostgreSQL, not just a log line:
the administering account, the target account, the action, the signed amount in seconds, the reason,
and the timestamp. It stores no credentials, no payment data, and no customer media. Rows are
removed with the account, because an audit row about a specific person should not outlive that
person's data.

### Account deletion

Deleting an account cascades its sessions, reset tokens, allowance holds, and audit rows. Nothing
here interferes with the Stripe Customer Portal, and a customer's right to cancel and seek a refund
is untouched. Credit is something an administrator may choose to offer; the customer decides
whether that resolves their issue.

---

### Status codes

| Code | Meaning |
| ---- | ------- |
| 200 | Success |
| 201 | Account created |
| 204 | Logged out |
| 400 | Unsupported file, invalid plan, malformed webhook payload, or wrong deletion confirmation |
| 401 | Missing, invalid, revoked, or expired session |
| 402 | Not enough processing allowance remaining |
| 409 | Email already registered, or account deletion blocked by an active subscription |
| 413 | File exceeds `MAX_UPLOAD_MB`, or media exceeds the duration cap, or the payload is oversized |
| 422 | Invalid payload, unreadable media, or no audio track |
| 429 | Rate limit reached, or a render is already running |
| 502 | Stripe unreachable |
| 503 | WhisperX unavailable, Stripe not configured, or no `DATABASE_URL` |
| 504 | The render exceeded its time budget |

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

`users` (23 columns)

| Group | Columns |
| ----- | ------- |
| Identity | `id`, `email`, `password_hash`, `is_active` |
| Plan | `plan` |
| Mirrored subscription | `subscription_status`, `subscription_provider`, `subscription_external_id`, `subscription_price_id`, `subscription_current_period_end` |
| Usage | `monthly_processing_allowance_seconds`, `processing_used_seconds`, `usage_period_started_at`, `usage_period_ends_at` |
| Entitlements | `preview_limit_seconds`, `has_full_preview`, `can_export` |
| Legal consent | `terms_accepted_at`, `terms_version`, `privacy_acknowledged_at`, `privacy_version` |
| Timestamps | `created_at`, `updated_at` |

The four consent columns are **recorded, never enforced**. `NULL` means "we did not record an
agreement", which is true of every account created before this existed; nothing reads them to decide
whether an account may sign in, so a `NULL` can never lock anybody out. The version strings label
which published text was shown, so the text itself is never stored and can be replaced without a data
migration.

`usage_reservations` — two-phase allowance holds (see accounting below).
`stripe_events` — processed Stripe event ids, for idempotent webhooks.
`sessions` — bearer sessions; tokens are stored only as SHA-256 hashes.
`password_reset_tokens` — reset tokens, stored hashed, with expiry, single use, and revocation.
`rate_limit_buckets` — the shared, cross-replica rate-limit counters (see rate limiting below).

### Migrations

| Revision | Change |
| -------- | ------ |
| `0001_initial_accounts` | `users`, `sessions` |
| `0002_billing_and_usage` | `users.subscription_price_id`, `usage_reservations`, `stripe_events` |
| `0003_password_reset` | `password_reset_tokens` |
| `0004_account_consent` | four nullable consent columns on `users`. No backfill, no defaults, no `NOT NULL` |
| `0005_rate_limit_buckets` | `rate_limit_buckets` |

Every revision is additive, so an application rollback stays safe against a migrated schema. A
schema rollback is destructive: `0002` discards in-flight usage holds and the webhook idempotency
log, `0003` discards outstanding reset links, and `0005` empties the shared rate-limit budget (so a
downgrade is also a one-off reset of the abuse counters). Do not downgrade while requests are being
billed or password resets are in flight.

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
| Creator Annual | `creator_annual` | $149 | 30,000 s (500 min) | **monthly** | **annual** | yes | yes |

`creator_annual` is charged once a year by Stripe but its allowance still resets every month, the
same as Creator Monthly. Buying a year does not buy twelve months up front, and **unused minutes do
not roll over** — a rollover sets usage back to zero and discards the remainder. It is simply the
same 500 minutes for $79 less per year ($19 × 12 = $228 versus $149).

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

Not implemented, by design: OAuth or social login, and email verification of new addresses. Password
reset **is** implemented — see [Password recovery](#password-recovery) below.

**Tradeoff:** the token is held in `localStorage` and sent as an `Authorization: Bearer` header. The
Captionline web and API are separate Railway origins, so this avoids `SameSite` and cookie-credential
handling. The hardening path, if wanted, is httpOnly `SameSite=None; Secure` cookies plus CSRF
protection, and it is **deferred rather than overlooked**: `SameSite=None` cookies are rejected on
cross-site requests, so the migration only becomes possible once the custom domain is attached to
both services, and it is a change to the auth path of every endpoint. The localStorage trade-off is
documented and revisited after launch; see [Known limitations](#known-limitations).

### Session hygiene

- Tokens are never logged. The log records request outcomes, never headers or token values.
- Logout revokes the row, so the token stops working immediately.
- Login returns an identical `401` for an unknown email and a wrong password, so account existence
  cannot be probed.
- Expired and revoked rows are purged opportunistically by `purge_expired_sessions`, keeping a
  recently expired row briefly so it reports "expired" rather than "unknown".

---

## Rate limiting

`app/ratelimit.py`. Registration, login, transcription, and the billing session endpoints were all
reachable without any request budget, which is not only a spam problem: Argon2id at 64 MiB makes an
unthrottled login endpoint a cheap way to burn a server's CPU and RAM, and unthrottled registration
is a way to mint unlimited free transcription time.

### Buckets

Each bucket is a fixed window, configured by an environment variable, and applied **both per client
address and per account**. Either dimension alone is trivially evaded — many addresses defeat a
per-address limit, and one account behind many addresses defeats a per-account limit. A limit or a
window of `0` disables that bucket.

| Bucket | Endpoint | Default |
| ------ | -------- | ------- |
| `register` | `POST /api/auth/register` | 5 / 3600 s |
| `login` | `POST /api/auth/login` | 10 / 300 s |
| `forgot-password` | `POST /api/auth/forgot-password` | 5 / 900 s (`PASSWORD_RESET_IP_*`) |
| `transcribe` | `POST /api/transcribe` | 20 / 300 s |
| `checkout` | `POST /api/billing/checkout` | 10 / 3600 s |
| `portal` | `POST /api/billing/portal` | 10 / 3600 s |
| `change-password` | `POST /api/auth/change-password` | 5 / 900 s |
| `reset-password` | `POST /api/auth/reset-password` | 10 / 900 s |
| `delete-account` | `POST /api/account/delete` | 5 / 900 s |

Every throttled endpoint answers `429` with one generic message and a `Retry-After` header, except
`forgot-password`, which keeps its ordinary response: a `429` there would reveal that the address is
under observation, which is itself an enumeration signal.

### Two layers, and the per-replica limitation of the first

**The in-process layer** is a bounded LRU map of TTL windows. It needs no database round trip, so a
flood is absorbed before it can reach Postgres, and it is what every bucket uses. It is bounded on
purpose: at most `RATE_LIMIT_MAX_KEYS` keys (default 10,000) are held, expired entries are pruned on
every call, and account subjects are stored as a truncated SHA-256 digest so email addresses are not
held in process memory.

It is also **per replica**, and that is a real limitation rather than a footnote:

- on a host running N replicas, an attacker who reaches all of them gets N times the limit;
- every counter resets when a replica is recycled;
- a rolling deploy resets the whole fleet's budget.

Those properties are tolerable for transcription and billing, where the caller is already
authenticated and a row in the database throttles them per account anyway. They are **not** tolerable
where password guessing, free-tier account minting, and mail-provider flooding all begin.

**The durable layer** (`rate_limit_buckets`, migration `0005`) is a shared, database-backed
fixed-window counter consulted for the three unauthenticated buckets only: `login`, `register`, and
`forgot-password`. It is always the *second* check, never the first — the cheap pre-filter runs in
front of it precisely so a burst is refused without a database connection. It uses an
`INSERT ... ON CONFLICT DO UPDATE` that increments and reopens the window in one statement, so two
replicas counting the same key cannot both read a stale count and both slip under the limit.

Two deliberate properties:

- **Availability over strictness.** If the database is unreachable, the table is missing, or the
  write fails, the durable check **allows the request and logs**. A limiter that turns a database blip
  into a `500` on the login page converts a degraded dependency into a total outage, and an outage is
  the worse outcome. The failure is logged, so an operator can see that the shared budget is not
  being enforced.
- **Bounded rows, no scheduler.** A row whose window is older than the longest configured bucket
  window can never be read again, so an opportunistic prune (at most once per
  `RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS`, from a request already writing the table) deletes it.
  The retention horizon is derived from the bucket windows rather than configured separately, so the
  two can never disagree. There is no background thread.

The durable table is deliberately **not** cleared at startup: wiping it when one replica restarts
would hand an attacker the whole fleet's budget, which is the exact property the layer exists to
remove. It needs `DATABASE_URL`; without a database the in-process layer is the whole control, and
`RATE_LIMIT_DURABLE_ENABLED=0` is the documented way to turn the durable half off.

### Client identity

The bucket key prefers `request.client.host`, the socket peer, which cannot be forged by a header.
`X-Forwarded-For` is consulted **only** when `TRUST_PROXY_HEADERS` is explicitly enabled, i.e. when a
proxy that *overwrites* that header is known to be in front of the service. Trusting it by default
would let a single `curl -H` call mint unlimited buckets and defeat the limits.

---

## Security response headers

`app/headers.py` is a plain ASGI wrapper (not `BaseHTTPMiddleware`, so it adds no response buffering)
that sets hardening headers on every HTTP response. A response that already carries a value keeps it,
so a route needing a different `Cache-Control` is not silently overridden.

| Header | Why |
| ------ | --- |
| `X-Content-Type-Options: nosniff` | Every response here is JSON and none of it is meant to be rendered |
| `X-Frame-Options: DENY` | No response may be framed, so a signed-in page cannot be clickjacked |
| `Referrer-Policy: strict-origin-when-cross-origin` | Keeps full paths and query strings, which carry reset tokens, out of third-party `Referer` headers |
| `Permissions-Policy` | Locks down camera, microphone, and geolocation, which a transcription UI never needs |
| `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` | A JSON API loads nothing, so everything is denied outright |
| `Strict-Transport-Security` | Sent only over HTTPS, or when `HSTS_ENABLED` says so. Conditional on purpose: pinning localhost to HTTPS would break local development |
| `Cache-Control: no-store` | On the endpoints that return a bearer token or a password-reset outcome, so nothing writes a token to a shared, CDN, or on-disk cache |

`/docs`, `/redoc`, and `/openapi.json` are exempted from the **CSP only** — they load their own
assets from a public CDN and `/openapi.json` is the schema they fetch, so `default-src 'none'` would
blank them. Every other header still applies to them, and the exemption is an explicit list
(`CSP_EXEMPT_PATHS`) rather than an implication.

---

## Production configuration gate

`APP_ENV` selects the deployment environment. It defaults to `development`, and **anything other than
`production` is treated as development**, so a misspelling cannot silently disable the checks.

`assert_production_ready()` runs in the lifespan **only** when `APP_ENV=production`, and calls
`Settings.production_problems()`. If that returns anything, the service logs each problem as
`CRITICAL` and raises before binding any traffic:

- `CORS_ORIGINS` contains `*` (list the exact frontend origin instead);
- `EMAIL_PROVIDER` is `console` or `memory`, which print password reset links — and their raw
  tokens — to the log;
- `DATABASE_ECHO` is on, so every SQL statement including bind parameters such as password and token
  hashes is logged;
- `FRONTEND_URL` is empty, is not an `https://` origin, or points at localhost, so reset and
  checkout links would be wrong or would travel in clear text;
- `STRIPE_SECRET_KEY` is set while `FRONTEND_URL` is not `https`, so Stripe's success and cancel
  redirects would land on a clear-text origin;
- `EMAIL_PROVIDER=resend` with no `EMAIL_API_KEY`, so no password reset mail can be sent.

**This is a breaking change for a misconfigured production, on purpose.** The first deploy that sets
`APP_ENV=production` will refuse to boot until those problems are fixed, which is the point: the
fault surfaces at startup rather than during an incident. Set the variables the gate checks
(`CORS_ORIGINS`, `FRONTEND_URL`, `EMAIL_*`) **before** setting `APP_ENV`.

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

1. Create three recurring **Prices** ($19/mo, $39/mo, $149/yr) and copy each `price_…` ID into the
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

`pytest.ini` sets `pythonpath = .`, so the suite runs from the repository root as well as from
`backend/`:

```bash
backend\.venv\Scripts\python.exe -m pytest backend\tests
```

The suite covers authentication, the plan catalogue, allowance accounting (including concurrency
and no-charge-on-failure), the transcription gate, Stripe checkout and webhooks, account deletion and
its billing rule, password recovery, the rate limiter (both layers, including the per-replica and
database-failure behaviour), the production configuration gate, the security headers, and the
no-database fallback. It runs the real Alembic migrations against a temporary SQLite database, so no
PostgreSQL server and no Stripe account are needed. WhisperX is mocked for accounting tests; a real
`ffprobe` call is made so duration measurement is genuinely exercised.

### Optional: exact local pins

`requirements.lock.txt` records the fully pinned environment used during development. Use it to
reproduce that machine exactly. Do not use it in the Linux container build: the `+cu128` torch build
is platform specific.

---

## Configuration

Every setting is an environment variable. **`.env.example` is the complete list** — all 60 of them,
each with its safe default, whether it is a secret, and what it does. The table below is only the
short list worth knowing about; `APP_ENV` and the `RATE_LIMIT_*` family are documented in full
there.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `APP_ENV` | `development` | **Production must set `production`.** Selects the startup configuration gate; see above |
| `DATABASE_URL` | unset | PostgreSQL (production) or SQLite (local) URL. **Secret** |
| `DATABASE_ECHO` | `0` | Log SQL. Never enable in production. |
| `EMAIL_PROVIDER` | `none` | `resend` in production; `console`/`memory` are dev and test only |
| `EMAIL_API_KEY` | unset | Resend API key. **Secret** |
| `EMAIL_FROM` | `Captionline <no-reply@captionline.pro>` | Verified sender |
| `SUPPORT_EMAIL` | unset | Monitored support mailbox, reported by `/api/legal/versions`. Must be set before launch |
| `STRIPE_SECRET_KEY` | unset | Stripe API key. **Secret** |
| `STRIPE_WEBHOOK_SECRET` | unset | Verifies webhook signatures. **Secret** |
| `TRUST_PROXY_HEADERS` | `0` | Allow `X-Forwarded-For` as a rate-limit key. Only behind a proxy that overwrites it |
| `HSTS_ENABLED` | unset | Force HSTS on/off. Unset means "only over HTTPS" |
| `RATE_LIMIT_MAX_KEYS` | `10000` | Ceiling on in-process rate-limit keys, so memory is bounded |
| `RATE_LIMIT_DURABLE_ENABLED` | `1` | Shared, cross-replica counters for the unauthenticated buckets |
| `TEMP_SWEEP_MAX_AGE_SECONDS` | `86400` | Age at which a work directory left by a killed request is swept at startup |
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

The four secrets in the system are `DATABASE_URL`, `EMAIL_API_KEY`, `STRIPE_SECRET_KEY`, and
`STRIPE_WEBHOOK_SECRET`. The WhisperX models are public, so transcription needs no secret at all.

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

# REQUIRED IN PRODUCTION. The safety gate below does not run without it, and
# without the gate a wildcard CORS origin, a console email provider logging
# reset tokens, or DATABASE_ECHO logging password hashes all boot silently.
APP_ENV=production

# STRIPE REQUIRED (only for live billing; the service runs without them)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_CREATOR_MONTHLY=price_...
STRIPE_PRICE_PRO_MONTHLY=price_...
STRIPE_PRICE_CREATOR_ANNUAL=price_...

# RECOMMENDED
FRONTEND_URL=https://<your-frontend-custom-domain>
CORS_ORIGINS=https://<your-frontend-custom-domain>
EMAIL_PROVIDER=resend
EMAIL_API_KEY=re_...
EMAIL_FROM=Captionline <no-reply@your-domain>
SUPPORT_EMAIL=support@your-domain
WHISPERX_MODEL=small
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
MAX_UPLOAD_MB=500
SESSION_TTL_DAYS=30
```

`DATABASE_URL` must be present or the account endpoints return `503`. Transcription is also gated
behind an account, so it also requires the database.

Set `CORS_ORIGINS` to the deployed Captionline frontend origin. `*` is accepted for initial
testing but **refuses to start** when `APP_ENV=production`.

**Set `APP_ENV` last.** It turns on the startup gate, so the service will refuse to boot until
`CORS_ORIGINS`, `FRONTEND_URL`, `EMAIL_PROVIDER`, `EMAIL_API_KEY`, and `DATABASE_ECHO` are all
production-correct. That is the intended behaviour; it just means the variable order matters on the
first production deploy.

**Image size warning:** the CPU torch wheel plus the rest of the dependency tree produces an image
of roughly **4-6 GB**. A CUDA-based image is considerably larger still. This is the main practical
cost of running WhisperX on Railway, and it is worth measuring before relying on it.

### Deployment order

1. Apply migrations (the image does this on start, or run `alembic upgrade head` manually).
2. Deploy the API. Health should report `database.status: ok`.
3. Deploy the web app with `VITE_API_URL` pointing at the API origin.
4. Configure `CORS_ORIGINS` and `FRONTEND_URL` on the API to the web origin.
5. Add the Stripe variables and the webhook endpoint.
6. Configure the email provider, then set `APP_ENV=production` and restart. The service now refuses
   to start unless every check above passes, which is the intended final gate.

Migrations in this release (`0002`–`0005`) are all additive, so rolling forward does not require
downtime.

### Rollback

- **Application rollback** is safe: revert the image. Every revision from `0002` to `0005` is
  additive, so the previous release keeps working against the migrated schema.
- **Schema rollback** (`alembic downgrade -1`) is destructive. `0005` empties the shared
  rate-limit budget, so a downgrade is also a one-off reset of the abuse counters; `0004` discards
  recorded legal consents; `0003` discards outstanding reset links; `0002` drops
  `subscription_price_id`, `usage_reservations`, and `stripe_events`, discarding in-flight usage
  holds and the webhook idempotency log. Do not downgrade while requests are being billed.

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
│       ├── 0002_billing_and_usage.py
│       ├── 0003_password_reset.py
│       ├── 0004_account_consent.py
│       └── 0005_rate_limit_buckets.py
├── alembic.ini                    # No connection string stored here
├── app/
│   ├── __init__.py
│   ├── config.py                  # Env-driven settings + the production configuration gate
│   ├── headers.py                 # Security response headers (ASGI middleware)
│   ├── ratelimit.py               # In-process and durable request budgets
│   ├── email.py                   # Transactional email provider abstraction
│   ├── terms.py                   # Legal versions, support mailbox, governing-law placeholder
│   ├── main.py                    # FastAPI app, CORS, health, transcribe gate, startup sweep
│   ├── schemas.py                 # Transcription, health, and Stripe health models
│   ├── plans.py                   # Plan catalogue (single source of truth)
│   ├── usage.py                   # Periods, reservations, allowance, snapshot
│   ├── media.py                   # ffprobe duration measurement + billing seconds
│   ├── transcribe.py              # WhisperX lifecycle + normalization
│   ├── stripe_client.py           # Stripe client, checkout, signature verification
│   ├── db/
│   │   ├── base.py                # Declarative base
│   │   ├── models.py              # User, Session, PasswordResetToken, UsageReservation, StripeEvent, RateLimitBucket
│   │   └── session.py             # Engine, session, DATABASE_URL handling
│   ├── routers/
│   │   ├── auth.py                # register, login, me, logout, change-password
│   │   ├── password_reset.py      # forgot-password, reset-password
│   │   ├── account.py             # plans, entitlement, account deletion, legal versions
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
├── pytest.ini                     # Sets pythonpath = . so the suite runs from any cwd
├── Dockerfile
├── .env.example                   # Every variable the service reads, annotated
└── .dockerignore
```

---

## Password recovery

### Token design

`password_reset_tokens` mirrors the existing `sessions` approach:

* The raw token is generated with `secrets` (256 bits), emailed once, and **never
  stored**. Only its SHA-256 hash is persisted, so a database leak yields nothing
  usable.
* Single use. Consuming a token takes a `SELECT ... FOR UPDATE` row lock, so two
  concurrent submissions with the same token cannot both succeed — the second
  blocks, then observes `used_at` and is rejected.
* Expiring. `PASSWORD_RESET_TTL_MINUTES` (default 60).
* Issuing a newer token revokes the account's older outstanding tokens, so an
  older emailed link stops working.
* A successful reset or password change revokes **all login sessions**, because a
  reset is the standard response to a suspected compromise and a session minted
  with the old password must not survive it.

### Abuse protection

Two independent guards:

* **Per account, durable** — a cooldown between requests and a cap on outstanding
  tokens (`PASSWORD_RESET_COOLDOWN_SECONDS`, `PASSWORD_RESET_MAX_ACTIVE`).
* **Per client address** — the `forgot-password` rate-limit bucket
  (`PASSWORD_RESET_IP_LIMIT`, `PASSWORD_RESET_IP_WINDOW_SECONDS`), which is in-process
  by default and therefore per replica, and is also counted in the shared
  `rate_limit_buckets` table when the durable rate limiter is enabled. See
  [Rate limiting](#rate-limiting). Either way the request still returns the generic
  `200`, so the throttle is not observable.

A throttled request still returns the generic `200`, so throttling is not
observable either.

### Email

`app/email.py` is a provider abstraction, so the vendor lives in one place.
`EMAIL_PROVIDER` selects it:

| Value | Behaviour |
| ----- | --------- |
| `resend` | HTTP API call. Requires `EMAIL_API_KEY`. Used in production. |
| `console` | Writes the message to the log. Local development only. |
| `memory` | Retains messages in memory. Tests only. |
| anything else / unset | No provider. Reset answers generically and sends nothing. |

`console` and `memory` are only reachable when named explicitly, so a production
deployment cannot print reset links to the log stream. Delivery is server side
only; the frontend never sees the API key.

The reset link is built from `FRONTEND_URL`, never a hardcoded domain, and the
token is percent-encoded into the query string, so it cannot become an open
redirect. Neither passwords nor raw tokens are ever logged.

### Frontend

The reset page lives at a real path (`/reset-password`) because the link arrives
by email and must survive a full page load. Captionline has no router
dependency, so `src/auth/route.ts` adds just enough History API support for that
one route.

> **Deployment note.** Because the reset link is a real path, the Railway web
> service needs an SPA rewrite so `/reset-password` serves `index.html` rather
> than 404 on a direct load. The Vite dev server already does this.

---

## Finished-video rendering

### Architecture

```
browser: original File + edited captions + CaptionStyle
  → POST /api/export/video   (authenticated, multipart)
    → stream upload to a private temp directory
    → probe real duration and dimensions with ffprobe
    → generate a temporary .ass subtitle file
    → ffmpeg: burn the subtitles in, H.264 + AAC
    → stream the MP4 back, then delete the temp directory
```

Code lives in `app/render/`: `models.py` (validation), `ass.py` (ASS generation), `ffmpeg.py`
(binary discovery), `filenames.py` (download names), `service.py` (orchestration).

### FFmpeg

Uses the FFmpeg already required for transcription, via its **libass** filter. The Debian `ffmpeg`
package already includes libass, so no new runtime dependency was added. The image also installs
`fonts-dejavu-core` and `fontconfig`; without a font, libass would resolve whatever fontconfig
happened to find, which is not reproducible.

`/api/health` reports `renderer.ffmpeg_available` and `renderer.ffprobe_available` as booleans. No
path or version is exposed.

### Why ASS rather than SRT

SRT carries no styling at all. ASS is the only subtitle format libass can style to match the Caption
Designer: per-event colours, letter spacing, outline, shadow, an opaque background box, exact
positioning, and karaoke.

libass renders *either* an opaque box (`BorderStyle: 3`) *or* a text outline and shadow
(`BorderStyle: 1`), never both, and `BorderStyle` is a style property with no per-event override. So
when the designer has both a background and an outline, two events are emitted: a transparent-text
`Box` event drawn first, and a `Text` event on top.

### Injection safety

- **No shell.** FFmpeg is invoked with a list of arguments and no `shell=True`.
- **No user input in any argument.** The user contributes no flag, filter string, or protocol. The
  subprocess runs with `cwd` set to the private render directory, so FFmpeg only ever sees bare
  filenames this service created — there is nothing to escape.
- **ASS injection is escaped.** `{...}` opens an override block and `\` starts a control code, so
  both are neutralised in caption text. This was verified empirically: an unescaped `{b}` is consumed
  as a tag, while `\{b\}` renders as literal ink.
- **Filenames are allow-listed.** The saved upload's extension comes from the probed container, never
  from the client. The download name is rebuilt from a strict allowlist, so no path separator, quote,
  or shell metacharacter reaches a `Content-Disposition` header.
- **Bounded.** File size, duration, payload size, caption count, and render time are all capped.

### CaptionStyle mapping

Pixel values arrive in the editor's 1080-tall reference frame and are scaled by
`output_height / 1080`, so a 720p and a 4K export look the same.

| Style | ASS |
| ----- | --- |
| `fontFamily` | mapped to an installed DejaVu family, with a fallback |
| `fontSize`, `letterSpacing` | scaled to the frame |
| `fontWeight >= 600` | `Bold` |
| `textColor` | `PrimaryColour` |
| `wordHighlight` | `SecondaryColour` (unsung) → `PrimaryColour` (sung) |
| `backgroundColor/Opacity/Padding` | `Box` style with `BorderStyle: 3` |
| `outlineColor/Width`, `shadowEnabled` | `OutlineColour`/`Outline`, `Shadow` |
| `verticalPosition` | `\an5\pos(x, y)` with `y = position% × height` |
| `textAlign` | shifts the anchor within the caption block |
| `maxWidthPercent`, `maxCharsPerLine` | server-side wrapping before libass |
| `uppercase` | text is upper-cased for the render only |
| `wordSpacing` | extra gaps baked in at word boundaries |

`backgroundRadius` has no ASS equivalent, so boxes are square-cornered.

### Fonts and Unicode

`system`/`helvetica`/`trebuchet`/`impact` map to DejaVu Sans, `georgia` to DejaVu Serif, and `mono`
to DejaVu Sans Mono. An unknown id falls back rather than failing, so a font added later cannot break
older exports. All are open-licensed and cover Latin, Cyrillic and Greek. Captions are written as
UTF-8 and rendered with `Encoding=1`, so multilingual transcription is preserved.

### Karaoke

When `wordHighlight` is set **and** the cue's timed words still match the text being shown, `\kf`
tags (centisecond-accurate) drive the highlight, with the unsung words in `color` and the sung word
in `activeColor` — the same behaviour as the editor preview.

**Graceful fallback:** if the user retyped the caption, the words no longer describe the text, and
forcing tags would light up the wrong words. The renderer detects that and emits a plain
single-colour caption instead. It never crashes and never fakes a highlight.

### Output

H.264 (`libx264`, veryfast, CRF 20) and AAC 192 kbps, `yuv420p`, `+faststart`. The command contains
no `scale` or `-s`, so source dimensions and aspect ratio are preserved, and autorotation stays on so
rotation metadata is honoured rather than applied twice. `-map 0:a:0?` means a file with no audio
still exports.

### Temporary files

Each render gets a `mkdtemp` directory holding the upload, the `.ass`, and the output. It is removed
when the render fails or times out, and on success it is removed by a background task **after** the
response has finished streaming, so a successful download is never truncated.

### Limits and concurrency

Defaults, all overridable: 500 MB, 1 hour, 900 s, 1 concurrent render, 2 MB payload. Renders
beyond the concurrency limit are refused with `429` rather than queued, because a backlog on a small
Railway instance would time out every waiting request.

### Known limitations

- `backgroundRadius` is not rendered; boxes are square.
- Line height above ~1.35 is approximated by widening the gap between wrapped lines.
- Word spacing below 0.25 em is ignored, so the common case matches the preview exactly.
- Progress is a stage label, not a percentage: FFmpeg progress is not streamed, and inventing a
  number would misinform the customer.
- Export needs the original file in the current browser session. A page refresh loses it, and the
  editor says so rather than pretending the server kept the project.

---

## Known limitations

- **Long uploads and timeouts.** Transcription is synchronous. A long video on CPU can take far
  longer than a typical 60-second proxy timeout, so Railway will need either a longer timeout or a
  background-job design.
- **One transcription at a time per process.** WhisperX model inference is guarded by a lock, so
  concurrent requests queue. Multiple replicas would scale this out.
- **No email verification.** Password recovery exists; address verification does not.
- **The per-address reset throttle is not shared across Railway replicas** unless
  `RATE_LIMIT_DURABLE_ENABLED=1` and `DATABASE_URL` is set, in which case `login`, `register`, and
  `forgot-password` also keep a shared counter in `rate_limit_buckets`. The per-account cooldown and
  outstanding-token cap are already durable. The buckets that have no durable half
  (`transcribe`, `checkout`, `portal`, `change-password`, `reset-password`, `delete-account`) are
  throttled per account in the database, so the per-replica address limit adds little there.
- **Uploaded media is deleted in a `finally`, so a `SIGKILL` or an OOM kill leaves the file on
  disk** until a later startup sweeps it. The bound is `TEMP_SWEEP_MAX_AGE_SECONDS` (24 hours by
  default) and the sweep only runs at startup, so the true guarantee is "removed at the first start
  more than that long after the request". The Privacy Policy states this rather than claiming
  immediate deletion.
- **FastAPI spools the multipart body before the request is authorised**, so the `401` for an
  unauthenticated upload happens after the file has been written to disk. `MAX_UPLOAD_MB` bounds
  that disk use but no in-application limit can prevent it; an ingress body-size limit is the
  remaining control.
- **Session tokens live in `localStorage`.** Acceptable now given the cross-origin setup; see the
  authentication tradeoff note. httpOnly cookies are deferred until the custom domain is attached,
  not forgotten — `SameSite=None` is rejected cross-site, and the cookie + CSRF migration touches
  every authenticated endpoint.
- **`ffprobe` runs in-process and inherits the full environment.** A malicious media file reaching
  an ffmpeg RCE is a full compromise including the database credentials. It is invoked with a list
  argv and `shell=False`, but the ffmpeg build is not pinned and no protocol allow-list or output
  size cap is applied.
- **No governing law and no verified support mailbox.** `GOVERNING_LAW` is a visible placeholder and
  `SUPPORT_EMAIL` is unset, so the Terms say the clause is not published and no page prints an
  address nobody watches. Both must be set before paid subscriptions are offered.
- **No published refund policy.** Terms §13 commits to nothing beyond the lawful-refund statement in
  §7, because the commercial policy is an open business decision. It must be decided and published
  before paid subscriptions are offered.
- **Finished-video rendering does not exist.** `can_export` is granted as an *entitlement* only. The
  UI states plainly that rendering is not switched on; nothing is faked.
- **Usage holds live in PostgreSQL, not in memory**, so a restart mid-transcription does not leak a
  hold. The TTL reclaim is a backstop, not the primary mechanism.
- **`torchcodec` warning on Windows.** pyannote warns that built-in audio decoding is unavailable
  because `libtorchcodec` DLLs are missing. WhisperX passes audio in memory, so decoding still
  works, but the warning appears in the logs.
- **No diarization or translation.** Deliberately out of scope.
